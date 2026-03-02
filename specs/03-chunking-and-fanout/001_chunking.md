# Chunking & Fan-Out

**Deliverable:** When transcription completes, the Step Functions pipeline automatically reads the raw transcript from S3, splits it into ~500-token chunks with sentence-boundary awareness, stores each chunk as a JSON file in `s3://<bucket>/chunks/{video_id}/`, and returns a list of chunk keys suitable for Map-state fan-out in the embedding stage.

---

## Overview

1. Create the chunking Lambda module (Python): one handler + shared service layer
2. Deploy the chunking Lambda function using the existing Lambda Terraform module
3. Update the Step Functions state machine to add the chunking state after transcription
4. Update Step Functions IAM role with Lambda invoke permission for the chunking function
5. Verify end-to-end: upload audio → transcription completes → chunks appear in S3

---

## Prerequisites

- [ ] Stage 2 (Transcription) is complete and verified
- [ ] Step Functions state machine has transcription states ending at `TranscriptionSucceeded`
- [ ] A transcript exists in S3 at `transcripts/{video_id}/raw.json` (from a previous transcription run, or upload one now)

---

## Architecture Context

```
Video Upload ──▶ S3 ──▶ EventBridge ──▶ Step Functions
                                              │
                                              ├── ValidateInput (existing)
                                              ├── StartTranscription (existing)
                                              ├── WaitForTranscription (existing)
                                              ├── CheckTranscriptionStatus (existing)
                                              ├── IsTranscriptionComplete? (existing)
                                              ├── TranscriptionSucceeded (existing, updated)
                                              ├── ChunkTranscript (Lambda) ◄── THIS STAGE
                                              ├── ChunkingSucceeded (temporary end)
                                              ├── Embed (future — Map state over chunk_keys)
                                              └── Done
```

---

## Step Functions State After Transcription

After `TranscriptionSucceeded`, the full state machine payload looks like this. The chunking state receives this as input.

```json
{
  "version": "0",
  "detail-type": "Object Created",
  "source": "aws.s3",
  "detail": {
    "bucket": {
      "name": "production-rag-media-123456789012"
    },
    "object": {
      "key": "uploads/hello-my_name_is_wes.mp3",
      "size": 15728640
    },
    "reason": "PutObject"
  },
  "transcription": {
    "detail": {
      "transcription_job_name": "production-rag-hello-my_name_is_wes",
      "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
      "bucket_name": "production-rag-media-123456789012",
      "source_key": "uploads/hello-my_name_is_wes.mp3",
      "video_id": "hello-my_name_is_wes",
      "status": "COMPLETED"
    },
    "statusCode": 200
  }
}
```

The `ChunkTranscript` state extracts the fields it needs from `$.transcription.detail` via the Step Functions `Parameters` block.

---

## AWS Transcribe Output Format (Input to Chunking)

The chunking Lambda reads this JSON from S3 at the `transcript_s3_key` path. The key structures are `results.transcripts[0].transcript` (full text) and `results.items` (word-level timing).

```json
{
  "jobName": "production-rag-hello-my_name_is_wes",
  "status": "COMPLETED",
  "results": {
    "transcripts": [
      {
        "transcript": "Hello, my name is Wes. I'm going to talk about RAG pipelines."
      }
    ],
    "items": [
      {
        "type": "pronunciation",
        "alternatives": [{ "confidence": "0.99", "content": "Hello" }],
        "start_time": "0.0",
        "end_time": "0.43"
      },
      {
        "type": "punctuation",
        "alternatives": [{ "confidence": "0.0", "content": "," }]
      },
      {
        "type": "pronunciation",
        "alternatives": [{ "confidence": "0.98", "content": "my" }],
        "start_time": "0.44",
        "end_time": "0.62"
      }
    ]
  }
}
```

- `"pronunciation"` items have `start_time` and `end_time` (as strings)
- `"punctuation"` items have no timing — they attach to the preceding word

---

## Chunk Schema

Each chunk is stored as an individual JSON file in S3 at `chunks/{video_id}/chunk-{NNN}.json`:

```json
{
  "chunk_id": "hello-my_name_is_wes-chunk-001",
  "video_id": "hello-my_name_is_wes",
  "sequence": 1,
  "text": "Hello, my name is Wes. I'm going to talk about RAG pipelines...",
  "word_count": 487,
  "start_time": 0.0,
  "end_time": 45.2,
  "metadata": {
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "total_chunks": 3
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `string` | `{video_id}-chunk-{NNN}` (zero-padded to 3 digits) |
| `video_id` | `string` | Derived from S3 key (same as transcription stage) |
| `sequence` | `int` | 1-based chunk sequence number |
| `text` | `string` | The chunk text content |
| `word_count` | `int` | Number of words in the chunk (proxy for token count) |
| `start_time` | `float` | Start timestamp in seconds from the first word |
| `end_time` | `float` | End timestamp in seconds from the last word |
| `metadata.source_s3_key` | `string` | Original uploaded file S3 key |
| `metadata.total_chunks` | `int` | Total number of chunks produced for this video |

---

## Chunking Algorithm

The algorithm splits transcript text into retrieval-friendly chunks using sentence boundaries and word-level timestamps from the Transcribe output.

### Step 1: Parse Transcript Items into Timed Words

Iterate through `results.items` and build a flat list of timed words:

- For `"pronunciation"` items: create a timed word with `text`, `start_time` (float), `end_time` (float)
- For `"punctuation"` items: append the punctuation character to the preceding timed word's text

Result: a list of `{text: "Hello,", start_time: 0.0, end_time: 0.43}` objects where punctuation is attached to its preceding word.

### Step 2: Group Timed Words into Sentences

Walk through the timed words and group them into sentences. A sentence boundary occurs when a word's text ends with `.`, `!`, or `?`.

Each sentence tracks:
- The combined text of its words
- `start_time` from its first word
- `end_time` from its last word
- The word count

### Step 3: Group Sentences into Chunks

Accumulate sentences into chunks targeting **~500 words** per chunk:

1. Start a new chunk
2. Add sentences one by one, tracking the running word count
3. When adding the next sentence would exceed **500 words**:
   - If the current chunk is non-empty, finalize it and start a new chunk with that sentence
   - If the current chunk is empty (single sentence > 500 words), include the sentence anyway and finalize
4. After processing all sentences, finalize any remaining chunk

**Overlap:** When starting a new chunk, include the **last ~50 words** of the previous chunk's sentences as prefix context. The overlapping sentences are prepended to the new chunk. The new chunk's `start_time` is the start time of the first *overlapping* sentence. This ensures retrieval doesn't miss context at chunk boundaries.

### Step 4: Store Chunks in S3

For each chunk, write a JSON file to `chunks/{video_id}/chunk-{NNN}.json` where `NNN` is the zero-padded sequence number (starting from 001).

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `TARGET_CHUNK_WORDS` | `500` | Target words per chunk |
| `OVERLAP_WORDS` | `50` | Overlap words from previous chunk |

---

## Resources

### Part A: Chunking Module (Python)

Application code for the chunking Lambda function. Follows the same thin-handlers-thick-services pattern as the transcribe module.

**Directory structure:**

```
modules/chunking-module/
├── src/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── chunk_transcript.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── chunking_service.py
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── unit/
│       ├── __init__.py
│       └── test_chunking_service.py
├── requirements.txt
└── dev-requirements.txt
```

**Files to create:**

| File | Purpose |
|------|---------|
| `modules/chunking-module/src/handlers/chunk_transcript.py` | Lambda entry point: read transcript, chunk, store, return keys |
| `modules/chunking-module/src/services/chunking_service.py` | Business logic: parse transcript, chunk text, store chunks |
| `modules/chunking-module/src/utils/logger.py` | Structured JSON logger (same as transcribe module) |
| `modules/chunking-module/requirements.txt` | Runtime dependencies |
| `modules/chunking-module/dev-requirements.txt` | Test dependencies |
| All `__init__.py` files | Python package markers (empty files) |

---

#### chunk_transcript handler

**Input (from Step Functions — extracted fields from transcription output):**

```json
{
  "detail": {
    "bucket_name": "production-rag-media-123456789012",
    "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
    "video_id": "hello-my_name_is_wes",
    "source_key": "uploads/hello-my_name_is_wes.mp3"
  }
}
```

**Output (returned to Step Functions):**

```json
{
  "statusCode": 200,
  "detail": {
    "chunk_count": 3,
    "chunks_s3_prefix": "chunks/hello-my_name_is_wes/",
    "chunk_keys": [
      "chunks/hello-my_name_is_wes/chunk-001.json",
      "chunks/hello-my_name_is_wes/chunk-002.json",
      "chunks/hello-my_name_is_wes/chunk-003.json"
    ],
    "video_id": "hello-my_name_is_wes",
    "bucket_name": "production-rag-media-123456789012"
  }
}
```

**Handler responsibilities:**

1. Extract `detail.bucket_name`, `detail.transcript_s3_key`, `detail.video_id`, `detail.source_key` from event
2. Call `ChunkingService.read_transcript(bucket, transcript_key)` to get the raw transcript JSON from S3
3. Call `ChunkingService.parse_timed_words(transcript_json)` to extract timed words
4. Call `ChunkingService.chunk(timed_words, video_id, source_key)` to produce chunk objects
5. Call `ChunkingService.store_chunks(bucket, video_id, chunks)` to write chunk JSONs to S3
6. Return standardized response with chunk keys and count

**Error handling** follows the same pattern as the transcribe handlers: `ValueError` → 400, unhandled → 500.

---

#### ChunkingService

Business logic layer. All S3 I/O and chunking logic lives here.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `read_transcript(bucket, key)` | bucket name, S3 key | `dict` (parsed JSON) | Read and parse the raw transcript JSON from S3 |
| `parse_timed_words(transcript)` | transcript dict | `list[dict]` | Extract timed words from `results.items`, attach punctuation to preceding word |
| `build_sentences(timed_words)` | list of timed words | `list[dict]` | Group timed words into sentences, splitting on `.` `!` `?` |
| `chunk(timed_words, video_id, source_key)` | timed words, video_id, source_key | `list[dict]` | Full chunking pipeline: build sentences → group into chunks → build chunk objects |
| `store_chunks(bucket, video_id, chunks)` | bucket, video_id, list of chunk dicts | `list[str]` | Write each chunk as JSON to S3, return list of S3 keys |

**`read_transcript` implementation:**

```python
s3_client.get_object(Bucket=bucket, Key=key)
json.loads(response["Body"].read())
```

**`parse_timed_words` implementation:**

Iterate through `transcript["results"]["items"]`:

```python
for item in items:
    content = item["alternatives"][0]["content"]
    if item["type"] == "pronunciation":
        timed_words.append({
            "text": content,
            "start_time": float(item["start_time"]),
            "end_time": float(item["end_time"]),
        })
    elif item["type"] == "punctuation" and timed_words:
        timed_words[-1]["text"] += content
```

**`build_sentences` implementation:**

Walk through timed words, accumulate into current sentence. When a word ends with `.`, `!`, or `?`, finalize the sentence:

```python
sentence = {
    "text": " ".join(word["text"] for word in sentence_words),
    "start_time": sentence_words[0]["start_time"],
    "end_time": sentence_words[-1]["end_time"],
    "word_count": len(sentence_words),
}
```

If no sentence-ending punctuation is found in the entire transcript, treat the whole text as one sentence.

**`chunk` implementation:**

1. Call `build_sentences(timed_words)`
2. Accumulate sentences until `word_count >= TARGET_CHUNK_WORDS` (500)
3. On overflow, finalize the current chunk
4. For overlap: prepend trailing sentences from the previous chunk (up to `OVERLAP_WORDS` = 50 words) to the start of the new chunk
5. After all sentences, finalize any remaining chunk
6. Build chunk objects with the chunk schema defined above
7. Sequence numbers are 1-based; chunk IDs are `{video_id}-chunk-{NNN}`

**`store_chunks` implementation:**

For each chunk, write JSON to S3:

```python
key = f"chunks/{video_id}/chunk-{chunk['sequence']:03d}.json"
s3_client.put_object(
    Bucket=bucket,
    Key=key,
    Body=json.dumps(chunk),
    ContentType="application/json",
)
```

Return the list of S3 keys.

---

#### Dependencies

**`requirements.txt`:**
```
boto3
```

No additional dependencies beyond `boto3` (available in Lambda runtime). Word count is used as a token proxy — no external tokenizer needed.

**`dev-requirements.txt`:**
```
pytest
moto[s3]
```

---

### Part B: Unit Tests

**File:** `modules/chunking-module/tests/unit/test_chunking_service.py`

Test the core chunking logic without AWS calls (mock S3 with moto).

| Test | Description |
|------|-------------|
| `test_parse_timed_words_attaches_punctuation` | Pronunciation + punctuation items → punctuation attached to preceding word |
| `test_parse_timed_words_empty_items` | Empty items list → empty timed words |
| `test_build_sentences_splits_on_period` | Words ending with period create sentence boundaries |
| `test_build_sentences_no_punctuation` | No sentence-ending punctuation → single sentence |
| `test_chunk_short_transcript` | Transcript under 500 words → single chunk |
| `test_chunk_long_transcript` | Transcript over 500 words → multiple chunks with correct boundaries |
| `test_chunk_overlap` | Consecutive chunks share ~50 words of overlapping content |
| `test_chunk_metadata` | Chunk objects contain correct video_id, sequence, start/end times, metadata |
| `test_store_chunks_writes_to_s3` | Chunks are written to correct S3 paths (moto) |
| `test_store_chunks_returns_keys` | Returned keys match expected `chunks/{video_id}/chunk-NNN.json` pattern |

**`conftest.py` fixtures:**

| Fixture | Description |
|---------|-------------|
| `sample_transcript` | A minimal Transcribe output JSON with a few sentences and word-level timing |
| `long_transcript` | A transcript with > 1000 words to test multi-chunk splitting |
| `s3_bucket` | Moto-mocked S3 bucket for store_chunks tests |

---

### Part C: Chunking Lambda Deployment (Terraform)

Add one Lambda module call to `infra/environments/dev/main.tf`.

| Setting | Value |
|---------|-------|
| Function name | `${var.project_name}-chunk-transcript` |
| Handler | `src.handlers.chunk_transcript.handler` |
| Source dir | `${path.module}/../../../modules/chunking-module` |
| Runtime | `python3.11` |
| Timeout | `120` |
| Memory | `256` |

IAM permissions:

- `s3:GetObject` on `${module.media_bucket.bucket_arn}/transcripts/*`
- `s3:PutObject` on `${module.media_bucket.bucket_arn}/chunks/*`

Environment variables:

- `MEDIA_BUCKET` = `module.media_bucket.bucket_name`

---

### Part D: Step Functions State Machine Update

Modify the existing state machine to add the chunking state after transcription.

**Changes to existing states:**

1. `TranscriptionSucceeded`: Change from `End: true` to `Next: ChunkTranscript`

**New states:**

```
TranscriptionSucceeded:
  Type: Pass
  Next: ChunkTranscript

ChunkTranscript:
  Type: Task
  Resource: arn:aws:states:::lambda:invoke
  Parameters:
    FunctionName: <chunk-transcript-function-arn>
    Payload:
      detail:
        bucket_name.$: $.transcription.detail.bucket_name
        transcript_s3_key.$: $.transcription.detail.transcript_s3_key
        video_id.$: $.transcription.detail.video_id
        source_key.$: $.transcription.detail.source_key
  ResultPath: $.chunking
  ResultSelector:
    detail.$: $.Payload.detail
    statusCode.$: $.Payload.statusCode
  Next: ChunkingSucceeded
  Retry:
    - ErrorEquals: [Lambda.ServiceException, Lambda.AWSLambdaException, Lambda.SdkClientException]
      IntervalSeconds: 5
      MaxAttempts: 2
      BackoffRate: 2.0
  Catch:
    - ErrorEquals: [States.ALL]
      Next: ChunkingFailed
      ResultPath: $.error

ChunkingSucceeded:
  Type: Pass
  End: true

ChunkingFailed:
  Type: Fail
  Error: ChunkingFailed
  Cause: Chunking failed or encountered an error
```

**State data flow after chunking:**

The full state payload after `ChunkingSucceeded` will contain:

```json
{
  "detail": { "bucket": {...}, "object": {...} },
  "transcription": {
    "detail": {
      "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
      "video_id": "hello-my_name_is_wes",
      "bucket_name": "production-rag-media-123456789012",
      "source_key": "uploads/hello-my_name_is_wes.mp3",
      "status": "COMPLETED"
    }
  },
  "chunking": {
    "detail": {
      "chunk_count": 3,
      "chunks_s3_prefix": "chunks/hello-my_name_is_wes/",
      "chunk_keys": [
        "chunks/hello-my_name_is_wes/chunk-001.json",
        "chunks/hello-my_name_is_wes/chunk-002.json",
        "chunks/hello-my_name_is_wes/chunk-003.json"
      ],
      "video_id": "hello-my_name_is_wes",
      "bucket_name": "production-rag-media-123456789012"
    },
    "statusCode": 200
  }
}
```

The `$.chunking.detail.chunk_keys` array is designed for the Stage 4 embedding fan-out: a Step Functions Map state will iterate over this list, invoking the embedding Lambda once per chunk key.

---

### Part E: Step Functions IAM Update

Add Lambda invoke permission for the chunking function to the existing `sfn_lambda_invoke` policy.

**Add to the existing policy Resource list:**

- `module.chunk_transcript.function_arn`

---

### Part F: Outputs

**Add to `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `chunk_transcript_function_name` | `module.chunk_transcript.function_name` | Chunk transcript Lambda |

---

## Implementation Checklist

- [ ] 1. Create `modules/chunking-module/requirements.txt` with `boto3`
- [ ] 2. Create `modules/chunking-module/dev-requirements.txt` with `pytest`, `moto[s3]`
- [ ] 3. Create all `__init__.py` files (`src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`)
- [ ] 4. Create `modules/chunking-module/src/utils/logger.py` (copy from transcribe module)
- [ ] 5. Create `modules/chunking-module/src/services/chunking_service.py` with `read_transcript`, `parse_timed_words`, `build_sentences`, `chunk`, `store_chunks`
- [ ] 6. Create `modules/chunking-module/src/handlers/chunk_transcript.py` handler
- [ ] 7. Create `modules/chunking-module/tests/conftest.py` with shared fixtures
- [ ] 8. Create `modules/chunking-module/tests/unit/test_chunking_service.py` with unit tests
- [ ] 9. Add `chunk_transcript` Lambda module call to `infra/environments/dev/main.tf`
- [ ] 10. Update `TranscriptionSucceeded` state from `End: true` to `Next: ChunkTranscript` in `infra/environments/dev/main.tf`
- [ ] 11. Add `ChunkTranscript`, `ChunkingSucceeded`, `ChunkingFailed` states to Step Functions definition in `infra/environments/dev/main.tf`
- [ ] 12. Add `module.chunk_transcript.function_arn` to `sfn_lambda_invoke` policy Resource list in `infra/environments/dev/main.tf`
- [ ] 13. Add new output to `infra/environments/dev/outputs.tf`
- [ ] 14. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 15. Verify: upload sample audio and confirm chunking completes end-to-end

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform init
terraform plan
terraform apply
```

### Step 2: Upload a sample audio file (or reuse existing transcript)

If a transcript already exists from Stage 2 testing, skip to Step 3. Otherwise:

```bash
aws s3 cp ../../../samples/hello-my_name_is_wes.mp3 \
  s3://$(terraform output -raw media_bucket_name)/uploads/hello-my_name_is_wes.mp3
```

### Step 3: Monitor Step Functions execution

```bash
STATE_MACHINE_ARN=$(terraform output -raw state_machine_arn)

sleep 10

aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 1 \
  --query 'executions[0].{status: status, startDate: startDate}'
```

### Step 4: Wait for pipeline to complete

The pipeline now includes transcription (~30-120s) and chunking (~5-15s).

```bash
EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

watch -n 10 "aws stepfunctions describe-execution \
  --execution-arn $EXECUTION_ARN \
  --query '{status: status}' --output table"
```

Expected: Status transitions from `RUNNING` to `SUCCEEDED`.

### Step 5: Verify chunks in S3

```bash
BUCKET=$(terraform output -raw media_bucket_name)

aws s3 ls "s3://${BUCKET}/chunks/hello-my_name_is_wes/"
```

Expected: One or more `chunk-NNN.json` files.

### Step 6: Inspect a chunk

```bash
aws s3 cp "s3://${BUCKET}/chunks/hello-my_name_is_wes/chunk-001.json" /tmp/chunk.json

python3 -c "
import json
c = json.load(open('/tmp/chunk.json'))
print('Chunk ID:', c['chunk_id'])
print('Sequence:', c['sequence'])
print('Words:', c['word_count'])
print('Time:', c['start_time'], '-', c['end_time'])
print('Text preview:', c['text'][:200])
"
```

### Step 7: Verify execution output has chunk keys

```bash
aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query 'output' \
  --output text | python3 -c "
import json, sys
output = json.loads(sys.stdin.read())
chunking = output['chunking']['detail']
print('Chunk count:', chunking['chunk_count'])
print('Keys:', json.dumps(chunking['chunk_keys'], indent=2))
"
```

Expected: `chunk_count` matches the number of files in S3. `chunk_keys` is a list of S3 keys.

### Step 8: Verify Step Functions execution history

```bash
aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --query "events[?type=='TaskStateExited'].stateExitedEventDetails.name" \
  --output table
```

Expected: Shows `StartTranscription`, `CheckTranscriptionStatus`, `ChunkTranscript`, and `ChunkingSucceeded`.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Chunking module code exists | `modules/chunking-module/src/` has handlers and services directories with Python files |
| Chunking Lambda deployed | `aws lambda list-functions` shows `production-rag-chunk-transcript` |
| Step Functions has chunking states | State machine includes `ChunkTranscript`, `ChunkingSucceeded`, `ChunkingFailed` |
| Transcription flows into chunking | `TranscriptionSucceeded` transitions to `ChunkTranscript` (not End) |
| Chunks stored in S3 | `s3://<bucket>/chunks/<video-id>/` contains `chunk-NNN.json` files |
| Chunk JSON is valid | Each chunk file has `chunk_id`, `video_id`, `sequence`, `text`, `word_count`, `start_time`, `end_time`, `metadata` |
| Chunk text is non-empty | Every chunk has a non-empty `text` field |
| Timestamps are valid | `start_time < end_time` for every chunk; timestamps increase across chunk sequence |
| Chunk count is reasonable | For a short audio file (~30s), expect 1 chunk; for a 50-min video, expect ~50-100 chunks |
| Execution output has chunk_keys | `$.chunking.detail.chunk_keys` is a non-empty array of S3 keys |
| chunk_keys match S3 files | Every key in `chunk_keys` exists as an object in S3 |
| Error handling works | `ChunkingFailed` state catches Lambda errors |
| Original event preserved | Execution output still contains `$.detail.bucket.name` and `$.transcription.detail` |
| Unit tests pass | `cd modules/chunking-module && python -m pytest tests/` passes |
