# Chunking & Fan-Out

**Deliverable:** When transcription completes, the Step Functions pipeline automatically reads the raw transcript from S3, splits it into ~500-token chunks with sentence-boundary awareness, stores each chunk as a JSON file in `s3://<bucket>/chunks/{video_id}/`, and publishes each chunk reference to an SQS queue for embedding fan-out.

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
                                              ├── ChunkingSucceeded (pipeline end)
                                              │
SQS Queue ◄── chunk references published by ChunkTranscript Lambda
    │
    └── Embed Lambda (future — triggered per SQS message)
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
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
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
| `metadata.speaker` | `string` (nullable) | Speaker name (from S3 object user metadata, propagated via transcription handler) |
| `metadata.title` | `string` (nullable) | Video title (from S3 object user metadata, propagated via transcription handler) |
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
| `modules/chunking-module/src/utils/logger.py` | Shared logger utility — same as transcribe module's `logger.py` |
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
    "source_key": "uploads/hello-my_name_is_wes.mp3",
    "speaker": "Jane Doe",
    "title": "Building RAG Systems"
  }
}
```

The `speaker` and `title` fields are propagated from the transcription handler (which reads them from S3 object user metadata). Both are nullable.

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
    "messages_published": 3,
    "video_id": "hello-my_name_is_wes",
    "bucket_name": "production-rag-media-123456789012"
  }
}
```

**Handler responsibilities:**

1. Extract `detail.bucket_name`, `detail.transcript_s3_key`, `detail.video_id`, `detail.source_key`, `detail.speaker` (nullable), `detail.title` (nullable) from event
2. Call `ChunkingService.read_transcript(bucket, transcript_key)` to get the raw transcript JSON from S3
3. Call `ChunkingService.parse_timed_words(transcript_json)` to extract timed words
4. Call `ChunkingService.chunk(timed_words, video_id, source_key, speaker, title)` to produce chunk objects (speaker/title stored in each chunk's metadata)
5. Call `ChunkingService.store_chunks(bucket, video_id, chunks)` to write chunk JSONs to S3
6. Call `ChunkingService.publish_chunks(queue_url, chunk_keys, bucket, video_id, speaker, title)` to publish each chunk S3 key as a message to the SQS embedding queue (speaker/title included in each message body)
7. Return standardized response with chunk keys, count, and messages_published

**Error handling:** Same pattern as transcribe handlers — `ValueError` → 400, unhandled exceptions → 500.

---

#### ChunkingService

Business logic layer. All S3 I/O, chunking logic, and SQS publishing lives here. Follows the same pattern as `TranscribeService`: a class with boto3 clients (`s3`, `sqs`) created in `__init__`, instantiated once at module level for warm-invocation reuse.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `read_transcript(bucket, key)` | bucket name, S3 key | `dict` (parsed JSON) | Read and parse the raw transcript JSON from S3 |
| `parse_timed_words(transcript)` | transcript dict | `list[dict]` | Extract timed words from `results.items`, attach punctuation to preceding word |
| `build_sentences(timed_words)` | list of timed words | `list[dict]` | Group timed words into sentences, splitting on `.` `!` `?` |
| `chunk(timed_words, video_id, source_key, speaker, title)` | timed words, video_id, source_key, speaker (nullable), title (nullable) | `list[dict]` | Full chunking pipeline: build sentences → group into chunks → build chunk objects with speaker/title in metadata |
| `store_chunks(bucket, video_id, chunks)` | bucket, video_id, list of chunk dicts | `list[str]` | Write each chunk as JSON to S3, return list of S3 keys |
| `publish_chunks(queue_url, chunk_keys, bucket, video_id, speaker, title)` | SQS queue URL, list of S3 keys, bucket, video_id, speaker (nullable), title (nullable) | `int` | Publish one SQS message per chunk key (message body includes speaker/title), return count |

**Edge case:** If no sentence-ending punctuation is found in the entire transcript, `build_sentences` treats the whole text as one sentence.

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
moto[s3,sqs]
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
| `test_publish_chunks_sends_sqs_messages` | Calls `publish_chunks` with a stubbed SQS client, asserts `send_message` called once per chunk key with correct message body |
| `test_publish_chunks_returns_count` | Calls `publish_chunks` with 3 chunk keys, asserts return value is `3` |

**`conftest.py` fixtures:**

| Fixture | Description |
|---------|-------------|
| `sample_transcript` | A minimal Transcribe output JSON with a few sentences and word-level timing |
| `long_transcript` | A transcript with > 1000 words to test multi-chunk splitting |
| `s3_bucket` | Moto-mocked S3 bucket for store_chunks tests |

---

### Part C: Chunking Lambda Deployment (Terraform)

Add one Lambda module call to `infra/environments/dev/main.tf` using the shared `infra/modules/lambda` module (same as transcribe Lambdas).

| Setting | Value |
|---------|-------|
| Function name | `${var.project_name}-chunk-transcript` |
| Handler | `src.handlers.chunk_transcript.handler` |
| Source dir | `${path.module}/../../../modules/chunking-module` |
| Runtime | `python3.11` (module default) |
| Timeout | `120` |
| Memory | `256` (module default) |

IAM permissions:

- `s3:GetObject` on `${module.media_bucket.bucket_arn}/transcripts/*`
- `s3:PutObject` on `${module.media_bucket.bucket_arn}/chunks/*`
- `sqs:SendMessage` on the embedding queue ARN

Environment variables:

- `MEDIA_BUCKET` = `module.media_bucket.bucket_name`
- `EMBEDDING_QUEUE_URL` = SQS queue URL for the embedding fan-out queue

---

### Part D: SQS Embedding Queue (Terraform)

Create the SQS queue that the chunking Lambda publishes to. The embedding Lambda (Stage 4) will be wired as a consumer in a later spec. Add these resources directly to `infra/environments/dev/main.tf`.

| Resource | Type | Purpose |
|----------|------|---------|
| Embedding queue | `aws_sqs_queue` | Receive chunk references for embedding fan-out |
| Dead-letter queue | `aws_sqs_queue` | Capture failed messages after max retries |
| Redrive policy | `aws_sqs_queue_redrive_policy` | Route failed messages to DLQ after 3 attempts |

**Queue naming:**
- Embedding queue: `${var.project_name}-embedding-queue`
- Dead-letter queue: `${var.project_name}-embedding-dlq`

| Setting | Value | Rationale |
|---------|-------|-----------|
| Visibility timeout | `300` (5 min) | Must exceed embedding Lambda timeout so in-flight messages aren't redelivered |
| Message retention | `86400` (1 day) | Enough time to debug failures without losing messages |
| DLQ max receive count | `3` | Messages that fail 3 times move to DLQ for inspection |

**SQS message format** (published by chunking Lambda):

```json
{
  "chunk_s3_key": "chunks/hello-my_name_is_wes/chunk-001.json",
  "bucket": "production-rag-media-123456789012",
  "video_id": "hello-my_name_is_wes",
  "speaker": "Jane Doe",
  "title": "Building RAG Systems"
}
```

The `speaker` and `title` fields are nullable — they are `null` if S3 object user metadata was not set at upload time.

---

### Part E: Step Functions State Machine Update

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
        speaker.$: $.transcription.detail.speaker
        title.$: $.transcription.detail.title
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

The chunking Lambda publishes each chunk key as an individual SQS message to the embedding queue. The Step Functions pipeline ends at `ChunkingSucceeded`. The embedding Lambda (Stage 4) is triggered independently by SQS, processing one chunk per message invocation.

---

### Part F: Step Functions IAM Update

Add Lambda invoke permission for the chunking function to the existing `sfn_lambda_invoke` policy.

**Add to the existing policy Resource list:**

- `module.chunk_transcript.function_arn`

---

### Part G: Outputs

**Add to `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `chunk_transcript_function_name` | `module.chunk_transcript.function_name` | Chunk transcript Lambda |
| `embedding_queue_url` | `aws_sqs_queue.embedding.url` | Embedding fan-out queue URL |
| `embedding_queue_arn` | `aws_sqs_queue.embedding.arn` | Embedding fan-out queue ARN |

---

## Implementation Checklist

- [ ] 1. Create `modules/chunking-module/requirements.txt` with `boto3`
- [ ] 2. Create `modules/chunking-module/dev-requirements.txt` with `pytest`, `moto[s3]`
- [ ] 3. Create all `__init__.py` files (`src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`)
- [ ] 4. Create `modules/chunking-module/src/utils/logger.py` (content specified in Part A)
- [ ] 5. Create `modules/chunking-module/src/services/chunking_service.py` with `read_transcript`, `parse_timed_words`, `build_sentences`, `chunk` (accepts `speaker`/`title`), `store_chunks`, `publish_chunks` (accepts `speaker`/`title`)
- [ ] 6. Create `modules/chunking-module/src/handlers/chunk_transcript.py` handler (extracts `speaker`/`title` from event detail, passes to service methods)
- [ ] 7. Create `modules/chunking-module/tests/conftest.py` with shared fixtures
- [ ] 8. Create `modules/chunking-module/tests/unit/test_chunking_service.py` with unit tests (including SQS publish tests)
- [ ] 9. Add SQS embedding queue and DLQ resources to `infra/environments/dev/main.tf`
- [ ] 10. Add `chunk_transcript` Lambda module call to `infra/environments/dev/main.tf` (include `EMBEDDING_QUEUE_URL` env var)
- [ ] 11. Add `sqs:SendMessage` to chunking Lambda IAM policy for the embedding queue ARN
- [ ] 12. Update `TranscriptionSucceeded` state from `End: true` to `Next: ChunkTranscript` in `infra/environments/dev/main.tf`
- [ ] 13. Add `ChunkTranscript` (with `speaker.$` and `title.$` in Parameters), `ChunkingSucceeded`, `ChunkingFailed` states to Step Functions definition in `infra/environments/dev/main.tf`
- [ ] 14. Add `module.chunk_transcript.function_arn` to `sfn_lambda_invoke` policy Resource list in `infra/environments/dev/main.tf`
- [ ] 15. Add new outputs (`chunk_transcript_function_name`, `embedding_queue_url`, `embedding_queue_arn`) to `infra/environments/dev/outputs.tf`
- [ ] 16. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 17. Verify: upload sample audio and confirm chunking completes end-to-end and SQS messages appear in the embedding queue

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
  s3://$(terraform output -raw media_bucket_name)/uploads/hello-my_name_is_wes.mp3 \
  --metadata '{"speaker":"Wesley Reisz","title":"Hello, my name is Wes"}'
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

### Step 9: Verify SQS messages

```bash
QUEUE_URL=$(terraform -chdir=infra/environments/dev output -raw embedding_queue_url)
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" \
  --output text
```

Expected: A number greater than 0, matching the `chunk_count` from the Step Functions output.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Chunking module code exists | `modules/chunking-module/src/` has handlers and services directories with Python files |
| Chunking Lambda deployed | `aws lambda list-functions` shows `production-rag-chunk-transcript` |
| Step Functions has chunking states | State machine includes `ChunkTranscript`, `ChunkingSucceeded`, `ChunkingFailed` |
| Transcription flows into chunking | `TranscriptionSucceeded` transitions to `ChunkTranscript` (not End) |
| Chunks stored in S3 | `s3://<bucket>/chunks/<video-id>/` contains `chunk-NNN.json` files |
| Chunk JSON is valid | Each chunk file has `chunk_id`, `video_id`, `sequence`, `text`, `word_count`, `start_time`, `end_time`, `metadata` (including `speaker`, `title`, `source_s3_key`, `total_chunks`) |
| Chunk text is non-empty | Every chunk has a non-empty `text` field |
| Timestamps are valid | `start_time < end_time` for every chunk; timestamps increase across chunk sequence |
| Chunk count is reasonable | For a short audio file (~30s), expect 1 chunk; for a 50-min video, expect ~50-100 chunks |
| Execution output has chunk_keys | `$.chunking.detail.chunk_keys` is a non-empty array of S3 keys |
| chunk_keys match S3 files | Every key in `chunk_keys` exists as an object in S3 |
| SQS messages published | `$.chunking.detail.messages_published` equals `$.chunking.detail.chunk_count` |
| SQS messages include speaker/title | SQS message body JSON contains `speaker` and `title` fields (values or `null`) |
| SQS queue has messages | `aws sqs get-queue-attributes --attribute-names ApproximateNumberOfMessages` returns > 0 after execution |
| Error handling works | `ChunkingFailed` state catches Lambda errors |
| Original event preserved | Execution output still contains `$.detail.bucket.name` and `$.transcription.detail` |
| Unit tests pass | `cd modules/chunking-module && python -m pytest tests/` passes |
