# Chunking & Fan-Out — Implementation Plan

**Spec:** `specs/03-chunking-and-fanout/001_chunking.md`

---

## Spec Gap Identified

The spec assumes `$.transcription.detail.speaker` and `$.transcription.detail.title` exist in the Step Functions state after transcription. The `ChunkTranscript` state's Parameters reference these paths:

```
speaker.$: $.transcription.detail.speaker
title.$: $.transcription.detail.title
```

**Current state:** Neither `start_transcription.py` nor `check_transcription.py` returns `speaker` or `title`. Referencing a nonexistent path in Step Functions causes a `States.Runtime` error, which would route to `ChunkingFailed` on every execution.

**Resolution:** Phase 1 of this plan updates the transcription module to read S3 object user metadata (`speaker`, `title`) and propagate them through the transcription loop. Both fields are nullable (default `None` if metadata is absent).

---

## Phase 1: Prerequisite — Update Transcription Module

### P1. Update `TranscribeService` — `modules/transcribe-module/src/services/transcribe_service.py`

- Add optional `s3_client` parameter to `__init__` (default `boto3.client("s3")`)
- Add method `get_upload_metadata(self, bucket, key) -> dict`
  - Calls `self.s3_client.head_object(Bucket=bucket, Key=key)`
  - Returns `{"speaker": metadata.get("speaker"), "title": metadata.get("title")}` from `response["Metadata"]`
  - S3 user metadata keys are lowercased by AWS, so read `speaker` and `title` directly
- Module-level singleton unchanged: `service = TranscribeService()`

### P2. Update `start_transcription.py` handler — `modules/transcribe-module/src/handlers/start_transcription.py`

- After extracting `bucket` and `key`, call `service.get_upload_metadata(bucket, key)`
- Add `"speaker": metadata.get("speaker")` and `"title": metadata.get("title")` to the return `detail` dict
- These fields will be `None` if S3 object has no user metadata

### P3. Update `check_transcription.py` handler — `modules/transcribe-module/src/handlers/check_transcription.py`

- Add `"speaker": detail.get("speaker")` and `"title": detail.get("title")` to the return `detail` dict
- Uses `.get()` for backward compatibility if fields are absent

### P4. Update transcription tests — `modules/transcribe-module/tests/unit/test_transcribe_service.py`

- Add `TestGetUploadMetadata` class:
  - `test_returns_speaker_and_title` — put object with metadata `{"speaker": "Jane", "title": "Talk"}`, call `get_upload_metadata`, assert both returned
  - `test_returns_none_when_no_metadata` — put object without metadata, assert both are `None`
- Requires updating `mock_aws_services` fixture in `conftest.py` to also yield `"s3"` client (already yields it)
- Update `TestStartJob.test_starts_transcription_job` to also put S3 object with user metadata and verify `speaker`/`title` in result (if testing handler, otherwise service test is sufficient)

### P5. Run transcription tests

- `cd modules/transcribe-module && python -m pytest tests/ -v`
- All existing tests must still pass; new metadata tests must pass

---

## Phase 2: Chunking Module — Python Code

### A1. Create directory structure

Create all directories and empty `__init__.py` files:

```
modules/chunking-module/
├── src/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   ├── services/
│   │   ├── __init__.py
│   └── utils/
│       ├── __init__.py
├── tests/
│   ├── __init__.py
│   └── unit/
│       ├── __init__.py
```

Total: 7 empty `__init__.py` files.

### A2. Create `modules/chunking-module/requirements.txt`

Contents: `boto3` (single line).

### A3. Create `modules/chunking-module/dev-requirements.txt`

Contents:
```
pytest
moto[s3,sqs]
```

Note: spec checklist step 2 says `moto[s3]` but the dependencies section (spec line 337) correctly says `moto[s3,sqs]`. Using `moto[s3,sqs]` to support both S3 and SQS test fixtures.

### A4. Create `modules/chunking-module/src/utils/logger.py`

Exact copy of `modules/transcribe-module/src/utils/logger.py`. Contains `JsonFormatter` class and `get_logger(name)` function.

### A5. Create `modules/chunking-module/src/services/chunking_service.py`

Class: `ChunkingService`

**Constructor:** `__init__(self, s3_client=None, sqs_client=None)`
- `self.s3_client = s3_client or boto3.client("s3")`
- `self.sqs_client = sqs_client or boto3.client("sqs")`

**Constants** (module-level):
- `TARGET_CHUNK_WORDS = 500`
- `OVERLAP_WORDS = 50`

**Method: `read_transcript(self, bucket, key) -> dict`**
- `self.s3_client.get_object(Bucket=bucket, Key=key)`
- `json.loads(response["Body"].read())`
- Return parsed dict

**Method: `parse_timed_words(self, transcript) -> list[dict]`**
- Iterate `transcript["results"]["items"]`
- For `"pronunciation"` items: append `{"text": alt["content"], "start_time": float(item["start_time"]), "end_time": float(item["end_time"])}` where `alt = item["alternatives"][0]`
- For `"punctuation"` items: append `alt["content"]` to the preceding timed word's `text` field (if list is non-empty)
- Return list of timed word dicts

**Method: `build_sentences(self, timed_words) -> list[dict]`**
- Walk timed words; accumulate into current sentence
- Sentence boundary: word `text` ends with `.`, `!`, or `?`
- Each sentence: `{"text": "joined words", "start_time": first_word.start_time, "end_time": last_word.end_time, "word_count": N}`
- Edge case: if no sentence-ending punctuation in entire transcript, treat entire text as one sentence
- After loop, finalize any remaining words as a sentence

**Method: `chunk(self, timed_words, video_id, source_key, speaker, title) -> list[dict]`**
- Call `self.build_sentences(timed_words)` to get sentences
- Accumulate sentences into chunks targeting `TARGET_CHUNK_WORDS` per chunk:
  1. Start a new chunk (tracking sentences, running word count)
  2. For each sentence:
     - If adding it would exceed `TARGET_CHUNK_WORDS` AND current chunk is non-empty: finalize current chunk, start new chunk with overlap
     - If current chunk is empty (single sentence > 500 words): include it anyway, finalize
     - Otherwise: add sentence to current chunk
  3. Finalize any remaining chunk
- **Overlap logic:** when starting a new chunk, include the last ~`OVERLAP_WORDS` words worth of sentences from the previous chunk as prefix. Walk backward through previous chunk's sentences, collecting until word count >= `OVERLAP_WORDS`. Prepend those sentences to the new chunk. The new chunk's `start_time` = start time of first overlapping sentence.
- After all chunks are built, set `total_chunks = len(chunks)` and build chunk objects:
  ```
  {
    "chunk_id": f"{video_id}-chunk-{sequence:03d}",
    "video_id": video_id,
    "sequence": sequence,  # 1-based
    "text": joined sentence texts,
    "word_count": total words in chunk,
    "start_time": first sentence's start_time,
    "end_time": last sentence's end_time,
    "metadata": {
      "speaker": speaker,  # nullable
      "title": title,  # nullable
      "source_s3_key": source_key,
      "total_chunks": total_chunks
    }
  }
  ```

**Method: `store_chunks(self, bucket, video_id, chunks) -> list[str]`**
- For each chunk: compute key `f"chunks/{video_id}/chunk-{chunk['sequence']:03d}.json"`
- `self.s3_client.put_object(Bucket=bucket, Key=key, Body=json.dumps(chunk), ContentType="application/json")`
- Return list of S3 keys

**Method: `publish_chunks(self, queue_url, chunk_keys, bucket, video_id, speaker, title) -> int`**
- For each key in `chunk_keys`:
  - `message_body = json.dumps({"chunk_s3_key": key, "bucket": bucket, "video_id": video_id, "speaker": speaker, "title": title})`
  - `self.sqs_client.send_message(QueueUrl=queue_url, MessageBody=message_body)`
- Return `len(chunk_keys)`

**Module-level singleton:** `service = ChunkingService()`

### A6. Create `modules/chunking-module/src/handlers/chunk_transcript.py`

**Imports:**
- `os`
- `from src.services.chunking_service import service`
- `from src.utils.logger import get_logger`

**Handler function:** `handler(event, context)`

1. `request_id = getattr(context, "aws_request_id", "local")`
2. Extract from `event["detail"]`: `bucket_name`, `transcript_s3_key`, `video_id`, `source_key`, `speaker` (use `.get("speaker")` for nullable), `title` (use `.get("title")` for nullable)
3. `queue_url = os.environ["EMBEDDING_QUEUE_URL"]`
4. Log: "Chunking transcript for video {video_id}"
5. `transcript = service.read_transcript(bucket_name, transcript_s3_key)`
6. `timed_words = service.parse_timed_words(transcript)`
7. `chunks = service.chunk(timed_words, video_id, source_key, speaker, title)`
8. `chunk_keys = service.store_chunks(bucket_name, video_id, chunks)`
9. `messages_published = service.publish_chunks(queue_url, chunk_keys, bucket_name, video_id, speaker, title)`
10. Return:
    ```
    {
      "statusCode": 200,
      "detail": {
        "chunk_count": len(chunks),
        "chunks_s3_prefix": f"chunks/{video_id}/",
        "chunk_keys": chunk_keys,
        "messages_published": messages_published,
        "video_id": video_id,
        "bucket_name": bucket_name
      }
    }
    ```

**No try/except.** Exceptions propagate as Lambda failures — Step Functions Retry/Catch handles them. This differs from the transcribe handlers intentionally (spec line 304).

---

## Phase 3: Chunking Module — Unit Tests

### B1. Create `modules/chunking-module/tests/conftest.py`

**Fixtures:**

- `aws_credentials` — same pattern as transcribe-module: sets fake AWS env vars, yields, cleans up
- `mock_aws_services(aws_credentials)` — uses `moto.mock_aws()`, yields dict with `"s3"` and `"sqs"` boto3 clients
- `s3_bucket(mock_aws_services)` — creates bucket `"test-bucket"` via moto S3 client, returns bucket name
- `sample_transcript` — returns a minimal Transcribe output dict with 2-3 short sentences, word-level timing items (mix of pronunciation and punctuation), total < 500 words
- `long_transcript` — returns a Transcribe output dict with > 1000 words to test multi-chunk splitting; needs enough sentence-ending punctuation to test boundary logic

### B2. Create `modules/chunking-module/tests/unit/test_chunking_service.py`

**Test classes and methods:**

`TestParseTimedWords`
- `test_parse_timed_words_attaches_punctuation` — pronunciation + punctuation items → punctuation attached to preceding word's text; verify list length and text content
- `test_parse_timed_words_empty_items` — empty `results.items` → returns empty list

`TestBuildSentences`
- `test_build_sentences_splits_on_period` — words with periods create sentence boundaries; verify sentence count, text content, start/end times, word counts
- `test_build_sentences_no_punctuation` — no `.` `!` `?` endings → single sentence containing all words

`TestChunk`
- `test_chunk_short_transcript(sample_transcript)` — transcript under 500 words → single chunk with correct fields
- `test_chunk_long_transcript(long_transcript)` — transcript over 500 words → multiple chunks; verify each chunk's word count is <= ~500 (except possibly the last)
- `test_chunk_overlap(long_transcript)` — verify consecutive chunks share ~50 words of overlapping text content
- `test_chunk_metadata(sample_transcript)` — verify chunk objects contain correct `video_id`, `sequence` (1-based), `start_time`, `end_time`, `metadata.speaker`, `metadata.title`, `metadata.source_s3_key`, `metadata.total_chunks`

`TestStoreChunks`
- `test_store_chunks_writes_to_s3(s3_bucket, mock_aws_services)` — create ChunkingService with moto s3_client, call `store_chunks` with 2 chunks, verify objects exist in S3 via `get_object`
- `test_store_chunks_returns_keys(s3_bucket, mock_aws_services)` — verify returned keys match `chunks/{video_id}/chunk-001.json` pattern

`TestPublishChunks`
- `test_publish_chunks_sends_sqs_messages` — create `ChunkingService` with `MagicMock` sqs_client, call `publish_chunks` with 3 chunk keys, assert `send_message` called 3 times with correct message bodies (including speaker/title)
- `test_publish_chunks_returns_count` — call with 3 chunk keys, assert return value is `3`

### B3. Run chunking tests

- `cd modules/chunking-module && pip install -r dev-requirements.txt && python -m pytest tests/ -v`
- All 12 tests must pass

---

## Phase 4: Terraform Infrastructure

### C1. Add SQS resources to `infra/environments/dev/main.tf`

Add after the existing `module "check_transcription"` block, before `module "pipeline"`:

**Resource: `aws_sqs_queue.embedding_dlq`**
- `name = "${var.project_name}-embedding-dlq"`
- `message_retention_seconds = 86400`
- `tags = local.common_tags`

**Resource: `aws_sqs_queue.embedding`**
- `name = "${var.project_name}-embedding-queue"`
- `visibility_timeout_seconds = 300`
- `message_retention_seconds = 86400`
- `tags = local.common_tags`

**Resource: `aws_sqs_queue_redrive_policy.embedding`**
- `queue_url = aws_sqs_queue.embedding.id`
- `redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.embedding_dlq.arn, maxReceiveCount = 3 })`

### C2. Add chunk_transcript Lambda to `infra/environments/dev/main.tf`

Add after SQS resources, before `module "pipeline"`:

**Module: `module "chunk_transcript"`**
- `source = "../../modules/lambda"`
- `function_name = "${var.project_name}-chunk-transcript"`
- `handler = "src.handlers.chunk_transcript.handler"`
- `runtime = "python3.11"`
- `timeout = 120`
- `memory_size = 256`
- `source_dir = "${path.module}/../../../modules/chunking-module"`
- `tags = local.common_tags`
- `environment_variables`:
  - `MEDIA_BUCKET = module.media_bucket.bucket_name`
  - `EMBEDDING_QUEUE_URL = aws_sqs_queue.embedding.url`
- `policy_statements` — jsonencode with 3 statements:
  1. `s3:GetObject` on `${module.media_bucket.bucket_arn}/transcripts/*`
  2. `s3:PutObject` on `${module.media_bucket.bucket_arn}/chunks/*`
  3. `sqs:SendMessage` on `aws_sqs_queue.embedding.arn`

### E1. Update `TranscriptionSucceeded` state in `infra/environments/dev/main.tf`

Change from:
```
TranscriptionSucceeded = { Type = "Pass", End = true }
```
To:
```
TranscriptionSucceeded = { Type = "Pass", Next = "ChunkTranscript" }
```

### E2. Add 3 new states to the Step Functions definition

**`ChunkTranscript`** — Task state:
- `Resource = "arn:aws:states:::lambda:invoke"`
- `Parameters`:
  - `FunctionName = module.chunk_transcript.function_arn`
  - `"Payload"` with `"detail"` containing:
    - `"bucket_name.$" = "$.transcription.detail.bucket_name"`
    - `"transcript_s3_key.$" = "$.transcription.detail.transcript_s3_key"`
    - `"video_id.$" = "$.transcription.detail.video_id"`
    - `"source_key.$" = "$.transcription.detail.source_key"`
    - `"speaker.$" = "$.transcription.detail.speaker"`
    - `"title.$" = "$.transcription.detail.title"`
- `ResultPath = "$.chunking"`
- `ResultSelector`: `"detail.$" = "$.Payload.detail"`, `"statusCode.$" = "$.Payload.statusCode"`
- `Next = "ChunkingSucceeded"`
- `Retry`: same pattern as existing Lambda states (Lambda.ServiceException, etc.), IntervalSeconds=5, MaxAttempts=2, BackoffRate=2.0
- `Catch`: `States.ALL` → `ChunkingFailed`, ResultPath `$.error`

**`ChunkingSucceeded`** — Pass state:
- `Type = "Pass"`, `End = true`

**`ChunkingFailed`** — Fail state:
- `Error = "ChunkingFailed"`
- `Cause = "Chunking failed or encountered an error"`

### F1. Update IAM policy in `infra/environments/dev/main.tf`

Add `module.chunk_transcript.function_arn` to the `additional_policy_json` Resource array (alongside `module.start_transcription.function_arn` and `module.check_transcription.function_arn`).

### G1. Add outputs to `infra/environments/dev/outputs.tf`

- `chunk_transcript_function_name` — `module.chunk_transcript.function_name` — "Chunk transcript Lambda"
- `embedding_queue_url` — `aws_sqs_queue.embedding.url` — "Embedding fan-out queue URL"
- `embedding_queue_arn` — `aws_sqs_queue.embedding.arn` — "Embedding fan-out queue ARN"

---

## Implementation Checklist

### Phase 1: Prerequisite — Transcription Module Update

- [ ] P1. Add `s3_client` param and `get_upload_metadata` method to `TranscribeService` in `modules/transcribe-module/src/services/transcribe_service.py`
- [ ] P2. Add `speaker`/`title` to return dict in `modules/transcribe-module/src/handlers/start_transcription.py`
- [ ] P3. Pass through `speaker`/`title` in `modules/transcribe-module/src/handlers/check_transcription.py`
- [ ] P4. Add `TestGetUploadMetadata` tests to `modules/transcribe-module/tests/unit/test_transcribe_service.py`
- [ ] P5. Run transcription tests — all must pass

### Phase 2: Chunking Module — Python Code

- [ ] A1. Create directory structure and 7 empty `__init__.py` files
- [ ] A2. Create `modules/chunking-module/requirements.txt`
- [ ] A3. Create `modules/chunking-module/dev-requirements.txt`
- [ ] A4. Create `modules/chunking-module/src/utils/logger.py` (copy from transcribe-module)
- [ ] A5. Create `modules/chunking-module/src/services/chunking_service.py` with all 6 methods
- [ ] A6. Create `modules/chunking-module/src/handlers/chunk_transcript.py`

### Phase 3: Chunking Module — Unit Tests

- [ ] B1. Create `modules/chunking-module/tests/conftest.py` with fixtures
- [ ] B2. Create `modules/chunking-module/tests/unit/test_chunking_service.py` with 12 tests
- [ ] B3. Run chunking tests — all 12 must pass

### Phase 4: Terraform Infrastructure

- [ ] C1. Add SQS embedding queue + DLQ + redrive policy to `infra/environments/dev/main.tf`
- [ ] C2. Add `chunk_transcript` Lambda module call to `infra/environments/dev/main.tf`
- [ ] E1. Change `TranscriptionSucceeded` from `End: true` to `Next: ChunkTranscript`
- [ ] E2. Add `ChunkTranscript`, `ChunkingSucceeded`, `ChunkingFailed` states to Step Functions definition
- [ ] F1. Add `module.chunk_transcript.function_arn` to `sfn_lambda_invoke` IAM policy Resource list
- [ ] G1. Add 3 outputs to `infra/environments/dev/outputs.tf`

### Verification (manual, post-deploy)

- [ ] V1. `terraform init && terraform plan && terraform apply`
- [ ] V2. Upload sample audio and verify chunking completes end-to-end
- [ ] V3. Verify chunk JSON files in S3
- [ ] V4. Verify SQS messages in embedding queue
