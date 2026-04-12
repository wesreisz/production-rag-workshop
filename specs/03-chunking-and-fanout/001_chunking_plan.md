# Implementation Plan: Chunking & Fan-Out (001)

**Goal:** Update transcription handlers to propagate `speaker`/`title` metadata, then create the chunking Lambda module, deploy it with SQS infrastructure, and wire it into the Step Functions pipeline after transcription.

**Status:** Not started. Prerequisite (transcription handler update) must be completed first.

---

## Phase 0: Prerequisite — Transcription Handler Speaker/Title Propagation

The chunking spec requires `$.transcription.detail.speaker` and `$.transcription.detail.title` in the Step Functions state. The current transcription handlers don't read S3 object user metadata or propagate these fields. This phase adds that capability.

### Modified Files (4)

| # | File | Change |
|---|------|--------|
| 1 | `modules/transcribe-module/src/services/transcribe_service.py` | Add S3 client to `__init__`, add `get_object_metadata(bucket, key)` method |
| 2 | `modules/transcribe-module/src/handlers/start_transcription.py` | Call `service.get_object_metadata()`, include `speaker` and `title` in returned detail |
| 3 | `modules/transcribe-module/src/handlers/check_transcription.py` | Pass through `speaker` and `title` from input detail (same pattern as other fields) |
| 4 | `modules/transcribe-module/tests/unit/test_transcribe_service.py` | Add tests for `get_object_metadata` |

### Decisions

- `TranscribeService.__init__` currently accepts only `transcribe_client`. Add an optional `s3_client` parameter following the same pattern: `self._s3 = s3_client or boto3.client("s3")`.
- `get_object_metadata(bucket, key)` calls `self._s3.head_object(Bucket=bucket, Key=key)` and returns `{"speaker": metadata.get("speaker"), "title": metadata.get("title")}`. S3 lowercases user metadata keys, so `.get("speaker")` is correct.
- Both fields are nullable — return `None` if the metadata key is absent.
- No Terraform IAM changes needed: `start_transcription` Lambda already has `s3:GetObject` on `${bucket_arn}/*`, which covers `HeadObject`.

---

## Phase 1: Chunking Module (Python) — Tests First

### New Files (11)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/chunking-module/requirements.txt` | `boto3` |
| 2 | `modules/chunking-module/dev-requirements.txt` | `pytest`, `moto[s3,sqs]` |
| 3 | `modules/chunking-module/src/__init__.py` | Empty package marker |
| 4 | `modules/chunking-module/src/handlers/__init__.py` | Empty package marker |
| 5 | `modules/chunking-module/src/services/__init__.py` | Empty package marker |
| 6 | `modules/chunking-module/src/utils/__init__.py` | Empty package marker |
| 7 | `modules/chunking-module/tests/__init__.py` | Empty package marker |
| 8 | `modules/chunking-module/tests/unit/__init__.py` | Empty package marker |
| 9 | `modules/chunking-module/src/utils/logger.py` | Copy of transcribe-module's `logger.py` (identical `JsonFormatter` + `get_logger`) |
| 10 | `modules/chunking-module/tests/conftest.py` | Fixtures: `aws_credentials`, `mock_aws_services`, `sample_transcript`, `long_transcript`, `s3_bucket` |
| 11 | `modules/chunking-module/tests/unit/test_chunking_service.py` | 12 unit tests per spec Part B |

### Decisions

- Tests written first per coding standards. Service and handler created after.
- `conftest.py` follows same structure as transcribe-module: `aws_credentials` monkeypatches env vars, `mock_aws_services` uses `mock_aws()` context manager.
- `sample_transcript` fixture: minimal Transcribe JSON with ~10 words across 2-3 sentences, including pronunciation + punctuation items with timing.
- `long_transcript` fixture: programmatically generated transcript with >1000 words to trigger multi-chunk splitting. Build items list in a loop with sequential timing.
- `s3_bucket` fixture: creates moto S3 bucket `test-bucket` via `mock_aws_services["s3"]`.
- SQS publish tests: `test_publish_chunks_sends_sqs_messages` and `test_publish_chunks_returns_count` use moto SQS (create queue in fixture, pass URL to `publish_chunks`).

### Test Details

| # | Test | What It Asserts |
|---|------|-----------------|
| 1 | `test_parse_timed_words_attaches_punctuation` | Input: pronunciation "Hello" + punctuation "," → output: single timed word with `text="Hello,"`, correct `start_time`/`end_time` |
| 2 | `test_parse_timed_words_empty_items` | Input: empty list → output: empty list |
| 3 | `test_build_sentences_splits_on_period` | Input: timed words ending with "word." → splits into separate sentences at period boundary |
| 4 | `test_build_sentences_no_punctuation` | Input: timed words with no sentence-ending punctuation → returns single sentence containing all words |
| 5 | `test_chunk_short_transcript` | Input: <500 words → returns single chunk with `sequence=1`, correct `chunk_id`, `start_time`, `end_time` |
| 6 | `test_chunk_long_transcript` | Input: >1000 words → returns multiple chunks, each ≤500 words (except overlap), correct sequence numbering |
| 7 | `test_chunk_overlap` | Input: >1000 words → second chunk's text starts with words from end of first chunk (~50 words overlap) |
| 8 | `test_chunk_metadata` | Chunk dicts contain `video_id`, `sequence`, `start_time`, `end_time`, `word_count`, `chunk_id`, `metadata.source_s3_key`, `metadata.total_chunks`, `metadata.speaker`, `metadata.title` |
| 9 | `test_store_chunks_writes_to_s3` | After `store_chunks`, `s3.get_object` for each expected key succeeds and body parses as valid JSON matching chunk content |
| 10 | `test_store_chunks_returns_keys` | Returned list matches `["chunks/{video_id}/chunk-001.json", ...]` pattern |
| 11 | `test_publish_chunks_sends_sqs_messages` | After `publish_chunks` with 3 keys, SQS `receive_message` returns 3 messages with correct body JSON (including `chunk_s3_key`, `bucket`, `video_id`, `speaker`, `title`) |
| 12 | `test_publish_chunks_returns_count` | Return value equals number of chunk keys passed in |

---

## Phase 2: Chunking Module (Python) — Implementation

### New Files (2)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/chunking-module/src/services/chunking_service.py` | `ChunkingService` class with 6 methods |
| 2 | `modules/chunking-module/src/handlers/chunk_transcript.py` | Lambda entry point |

### ChunkingService Class Design

**Constructor:** `__init__(self, s3_client=None, sqs_client=None)` — creates `self._s3` and `self._sqs` via `boto3.client()` if not injected. Instantiated at module level in handler file.

**Constants (module-level):**
- `TARGET_CHUNK_WORDS = 500`
- `OVERLAP_WORDS = 50`

**Method: `read_transcript(bucket, key)`**
- `self._s3.get_object(Bucket=bucket, Key=key)`
- `json.loads(response["Body"].read())`
- Returns parsed dict

**Method: `parse_timed_words(transcript)`**
- Iterates `transcript["results"]["items"]`
- For `"pronunciation"`: append `{"text": item["alternatives"][0]["content"], "start_time": float(item["start_time"]), "end_time": float(item["end_time"])}`
- For `"punctuation"`: append punctuation text to last timed word's `text` field (if list non-empty)
- Returns list of timed word dicts

**Method: `build_sentences(timed_words)`**
- Walk timed words, accumulate into current sentence
- Sentence boundary: word text ends with `.`, `!`, or `?`
- Each sentence: `{"text": " ".join(word texts), "start_time": first_word.start_time, "end_time": last_word.end_time, "word_count": len(words), "words": [word_dicts]}`
- Store `words` list on each sentence to support overlap calculation later
- Edge case: if no sentence boundary found after all words, finalize remaining words as one sentence
- Returns list of sentence dicts

**Method: `chunk(timed_words, video_id, source_key, speaker, title)`**
- Calls `self.build_sentences(timed_words)`
- Accumulates sentences into chunks targeting `TARGET_CHUNK_WORDS`
- Algorithm:
  1. Initialize `current_sentences = []`, `current_word_count = 0`, `chunks = []`
  2. For each sentence:
     - If `current_word_count + sentence["word_count"] > TARGET_CHUNK_WORDS` AND `current_sentences` is non-empty:
       - Finalize current chunk from `current_sentences`
       - Start new chunk: compute overlap sentences from end of previous chunk's sentences (accumulate from last sentence backward until ≥ `OVERLAP_WORDS`), prepend them + current sentence
     - Else: add sentence to `current_sentences`, increment `current_word_count`
  3. Finalize remaining `current_sentences` as last chunk
- After all chunks built, set `metadata.total_chunks` on every chunk
- Each chunk dict: `{"chunk_id": f"{video_id}-chunk-{seq:03d}", "video_id": video_id, "sequence": seq (1-based), "text": combined text, "word_count": total words, "start_time": first sentence start, "end_time": last sentence end, "metadata": {"source_s3_key": source_key, "total_chunks": N, "speaker": speaker, "title": title}}`
- Returns list of chunk dicts

**Method: `store_chunks(bucket, video_id, chunks)`**
- For each chunk: `self._s3.put_object(Bucket=bucket, Key=f"chunks/{video_id}/chunk-{chunk['sequence']:03d}.json", Body=json.dumps(chunk), ContentType="application/json")`
- Returns list of S3 keys written

**Method: `publish_chunks(queue_url, chunk_keys, bucket, video_id, speaker, title)`**
- For each key: `self._sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"chunk_s3_key": key, "bucket": bucket, "video_id": video_id, "speaker": speaker, "title": title}))`
- Returns count of messages sent (i.e., `len(chunk_keys)`)

### Handler Design

**`chunk_transcript.py`:**
- Module-level: `service = ChunkingService()`, `logger = get_logger(__name__)`
- `handler(event, context)`:
  1. Extract `request_id` from context (same pattern as transcribe handlers)
  2. Extract from `event["detail"]`: `bucket_name`, `transcript_s3_key`, `video_id`, `source_key`, `speaker` (via `.get("speaker")`), `title` (via `.get("title")`)
  3. `queue_url = os.environ["EMBEDDING_QUEUE_URL"]`
  4. `transcript = service.read_transcript(bucket_name, transcript_s3_key)`
  5. `timed_words = service.parse_timed_words(transcript)`
  6. `chunks = service.chunk(timed_words, video_id, source_key, speaker, title)`
  7. `chunk_keys = service.store_chunks(bucket_name, video_id, chunks)`
  8. `messages_published = service.publish_chunks(queue_url, chunk_keys, bucket_name, video_id, speaker, title)`
  9. Return `{"statusCode": 200, "detail": {"chunk_count": len(chunks), "chunks_s3_prefix": f"chunks/{video_id}/", "chunk_keys": chunk_keys, "messages_published": messages_published, "video_id": video_id, "bucket_name": bucket_name}}`
- No try/except — exceptions propagate for Step Functions Retry/Catch

---

## Phase 3: Terraform Infrastructure

### Modified Files (2)

| # | File | Change |
|---|------|--------|
| 1 | `infra/environments/dev/main.tf` | Add SQS resources, Lambda module, Step Functions states, IAM update |
| 2 | `infra/environments/dev/outputs.tf` | Add 3 new outputs |

### New Resources in `main.tf`

**SQS Dead-Letter Queue** (`aws_sqs_queue.embedding_dlq`):
- `name = "${var.project_name}-embedding-dlq"`
- `message_retention_seconds = 86400`

**SQS Embedding Queue** (`aws_sqs_queue.embedding`):
- `name = "${var.project_name}-embedding-queue"`
- `visibility_timeout_seconds = 300`
- `message_retention_seconds = 86400`

**SQS Redrive Policy** (`aws_sqs_queue_redrive_policy.embedding`):
- `queue_url = aws_sqs_queue.embedding.url`
- `redrive_policy = jsonencode({deadLetterTargetArn = aws_sqs_queue.embedding_dlq.arn, maxReceiveCount = 3})`

**Lambda Module** (`module.chunk_transcript`):
- `source = "../../modules/lambda"`
- `function_name = "${var.project_name}-chunk-transcript"`
- `handler = "src.handlers.chunk_transcript.handler"`
- `source_dir = "${path.module}/../../../modules/chunking-module"`
- `timeout = 120`
- `environment_variables`:
  - `MEDIA_BUCKET = module.media_bucket.bucket_name`
  - `EMBEDDING_QUEUE_URL = aws_sqs_queue.embedding.url`
- `policy_statements`: 3 statements:
  1. `s3:GetObject` on `${module.media_bucket.bucket_arn}/transcripts/*`
  2. `s3:PutObject` on `${module.media_bucket.bucket_arn}/chunks/*`
  3. `sqs:SendMessage` on `aws_sqs_queue.embedding.arn`

### Step Functions State Machine Changes

**Modify `TranscriptionSucceeded`:**
- Change `End = true` → `Next = "ChunkTranscript"` (remove `End` key)

**Add `ChunkTranscript` state:**
- `Type = "Task"`
- `Resource = "arn:aws:states:::lambda:invoke"`
- `Parameters`:
  - `FunctionName = module.chunk_transcript.function_arn`
  - `Payload` with `"detail"` object mapping 6 fields from `$.transcription.detail.*`:
    - `"bucket_name.$" = "$.transcription.detail.bucket_name"`
    - `"transcript_s3_key.$" = "$.transcription.detail.transcript_s3_key"`
    - `"video_id.$" = "$.transcription.detail.video_id"`
    - `"source_key.$" = "$.transcription.detail.source_key"`
    - `"speaker.$" = "$.transcription.detail.speaker"`
    - `"title.$" = "$.transcription.detail.title"`
- `ResultPath = "$.chunking"`
- `ResultSelector`: `"detail.$" = "$.Payload.detail"`, `"statusCode.$" = "$.Payload.statusCode"`
- `Next = "ChunkingSucceeded"`
- `Retry`: same pattern as existing states (Lambda.ServiceException, IntervalSeconds 5, MaxAttempts 2, BackoffRate 2.0)
- `Catch`: `States.ALL` → `ChunkingFailed`, `ResultPath = "$.error"`

**Add `ChunkingSucceeded` state:**
- `Type = "Pass"`, `End = true`

**Add `ChunkingFailed` state:**
- `Type = "Fail"`, `Error = "ChunkingFailed"`, `Cause = "Chunking failed or encountered an error"`

### IAM Update

**Modify `aws_iam_role_policy.step_functions_lambda`:**
- Add `module.chunk_transcript.function_arn` to the existing `Resource` list (alongside `module.start_transcription.function_arn` and `module.check_transcription.function_arn`)

### New Outputs in `outputs.tf`

- `chunk_transcript_function_name` = `module.chunk_transcript.function_name`
- `embedding_queue_url` = `aws_sqs_queue.embedding.url`
- `embedding_queue_arn` = `aws_sqs_queue.embedding.arn`

---

## Risks / Assumptions

- `s3:GetObject` permission covers `HeadObject` (confirmed — AWS S3 uses same permission for both).
- S3 user metadata keys are lowercased by AWS — reading `.get("speaker")` and `.get("title")` is correct.
- `speaker` and `title` can be `None` throughout the pipeline — all code treats them as nullable.
- Overlap calculation uses full sentences, so overlap may be slightly above or below 50 words depending on sentence lengths.
- The `Payload` block in `ChunkTranscript` uses explicit field mapping (not `"Payload.$": "$"`) because chunking only needs a subset of the state.
- `dev-requirements.txt` in spec says `moto[s3]` but SQS publish tests need `moto[s3,sqs]` — using `moto[s3,sqs]`.

---

## Implementation Checklist

### Phase 0: Transcription Handler Update

- [ ] 0.1. Add `get_object_metadata(bucket, key)` method to `TranscribeService` in `modules/transcribe-module/src/services/transcribe_service.py` — calls `self._s3.head_object()`, returns `{"speaker": ..., "title": ...}` (both nullable)
- [ ] 0.2. Add `s3_client` parameter to `TranscribeService.__init__` — `self._s3 = s3_client or boto3.client("s3")`
- [ ] 0.3. Update `start_transcription.py` handler — call `service.get_object_metadata(bucket_name, object_key)`, add `"speaker"` and `"title"` to returned detail dict
- [ ] 0.4. Update `check_transcription.py` handler — pass through `detail.get("speaker")` and `detail.get("title")` in returned detail dict
- [ ] 0.5. Add `test_get_object_metadata_returns_speaker_and_title` to `test_transcribe_service.py` — upload object with metadata via moto, call method, assert both fields returned
- [ ] 0.6. Add `test_get_object_metadata_returns_none_when_missing` to `test_transcribe_service.py` — upload object without metadata, assert both fields are `None`
- [ ] 0.7. Update `test_returns_200_with_correct_detail` in `TestStartTranscriptionHandler` — mock `get_object_metadata` return value, assert `speaker` and `title` in result detail
- [ ] 0.8. Update `_make_event` in `TestCheckTranscriptionHandler` — add `speaker` and `title` to event detail fixture
- [ ] 0.9. Update `test_returns_200_with_updated_status` in `TestCheckTranscriptionHandler` — assert `speaker` and `title` passed through in result detail
- [ ] 0.10. Run `cd modules/transcribe-module && python -m pytest tests/ -v` — all tests pass

### Phase 1: Chunking Module — Tests First

- [ ] 1.1. Create `modules/chunking-module/requirements.txt` — content: `boto3`
- [ ] 1.2. Create `modules/chunking-module/dev-requirements.txt` — content: `pytest` and `moto[s3,sqs]`
- [ ] 1.3. Create 6 empty `__init__.py` files: `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`
- [ ] 1.4. Create `modules/chunking-module/src/utils/logger.py` — copy of transcribe-module's logger.py (identical `JsonFormatter` + `get_logger`)
- [ ] 1.5. Create `modules/chunking-module/tests/conftest.py` — fixtures: `aws_credentials`, `mock_aws_services` (s3 + sqs clients), `sample_transcript`, `long_transcript`, `s3_bucket`
- [ ] 1.6. Create `modules/chunking-module/tests/unit/test_chunking_service.py` — all 12 test cases (tests will fail until Phase 2)

### Phase 2: Chunking Module — Implementation

- [ ] 2.1. Create `modules/chunking-module/src/services/chunking_service.py` — `ChunkingService` class with `read_transcript`, `parse_timed_words`, `build_sentences`, `chunk`, `store_chunks`, `publish_chunks`
- [ ] 2.2. Create `modules/chunking-module/src/handlers/chunk_transcript.py` — thin handler extracting event fields, calling service methods, returning response
- [ ] 2.3. Run `cd modules/chunking-module && pip install -r dev-requirements.txt -r requirements.txt && python -m pytest tests/ -v` — all 12 tests pass
- [ ] 2.4. Run lint check

### Phase 3: Terraform Infrastructure

- [ ] 3.1. Add `aws_sqs_queue.embedding_dlq` to `infra/environments/dev/main.tf` — name `${var.project_name}-embedding-dlq`, retention 86400
- [ ] 3.2. Add `aws_sqs_queue.embedding` to `infra/environments/dev/main.tf` — name `${var.project_name}-embedding-queue`, visibility 300, retention 86400
- [ ] 3.3. Add `aws_sqs_queue_redrive_policy.embedding` to `infra/environments/dev/main.tf` — DLQ ARN, maxReceiveCount 3
- [ ] 3.4. Add `module.chunk_transcript` Lambda to `infra/environments/dev/main.tf` — function name, handler, source dir, timeout 120, env vars (MEDIA_BUCKET + EMBEDDING_QUEUE_URL), policy (s3:GetObject transcripts/*, s3:PutObject chunks/*, sqs:SendMessage)
- [ ] 3.5. Modify `TranscriptionSucceeded` state — remove `End = true`, add `Next = "ChunkTranscript"`
- [ ] 3.6. Add `ChunkTranscript` state — Task type, lambda:invoke, Parameters with 6 field mappings from `$.transcription.detail`, ResultPath `$.chunking`, ResultSelector, Retry, Catch → ChunkingFailed
- [ ] 3.7. Add `ChunkingSucceeded` state — Pass type, End = true
- [ ] 3.8. Add `ChunkingFailed` state — Fail type, Error "ChunkingFailed"
- [ ] 3.9. Add `module.chunk_transcript.function_arn` to `aws_iam_role_policy.step_functions_lambda` Resource list
- [ ] 3.10. Add 3 outputs to `infra/environments/dev/outputs.tf` — `chunk_transcript_function_name`, `embedding_queue_url`, `embedding_queue_arn`

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
