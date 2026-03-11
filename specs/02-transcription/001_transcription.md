# Transcription with AWS Transcribe

**Deliverable:** When a video/audio file is uploaded to `s3://<bucket>/uploads/`, the Step Functions pipeline automatically starts an AWS Transcribe job, polls for completion, and stores the raw transcript JSON in S3 at `transcripts/{video_id}/raw.json`.

---

## Overview

1. Create the transcribe Lambda module (Python): two handlers + shared service layer
2. Create a reusable Terraform Lambda module for deploying Lambda functions
3. Deploy two Lambda functions (start transcription, check status)
4. Update the Step Functions state machine with transcription states and a wait/poll loop
5. Update Step Functions IAM role with Lambda invoke permissions
6. Verify end-to-end: upload audio → transcription completes → transcript in S3

---

## Prerequisites

- [ ] Stage 1 (Video Upload & Workflow Trigger) is complete and verified
- [ ] Step Functions state machine is deployed with the skeleton `ValidateInput` Pass state
- [ ] Sample audio file exists in `samples/` (e.g. `hello-my_name_is_wes.mp3`)

---

## Architecture Context

```
Video Upload ──▶ S3 ──▶ EventBridge ──▶ Step Functions
                                              │
                                              ├── ValidateInput (existing)
                                              ├── StartTranscription (Lambda) ◄── THIS STAGE
                                              ├── WaitForTranscription (Wait 30s)
                                              ├── CheckTranscriptionStatus (Lambda)
                                              ├── IsTranscriptionComplete? (Choice)
                                              │     ├── COMPLETED → TranscriptionSucceeded
                                              │     ├── IN_PROGRESS → WaitForTranscription
                                              │     └── FAILED → TranscriptionFailed
                                              ├── Chunk (future)
                                              ├── Embed (future)
                                              └── Done
```

---

## Step Functions Input

The state machine receives the full S3 EventBridge event from Stage 1. The `detail` payload flows through ValidateInput and into the transcription states.

```json
{
  "version": "0",
  "id": "example-event-id",
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
  }
}
```

Downstream Lambda handlers extract `detail.bucket.name` and `detail.object.key`.

---

## Lambda Response Format

All Lambda functions return this structure for Step Functions compatibility (per PRD Section 6.4):

```json
{
  "statusCode": 200,
  "detail": {
    "...module-specific fields..."
  }
}
```

---

## AWS Transcribe Output Format

AWS Transcribe writes a JSON file to S3 with this structure (simplified):

```json
{
  "jobName": "production-rag-hello-my_name_is_wes",
  "status": "COMPLETED",
  "results": {
    "transcripts": [
      {
        "transcript": "Hello, my name is Wes..."
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
      }
    ]
  }
}
```

The `items` array contains word-level timing data used by the chunking stage (Stage 3) for timestamp alignment.

---

## Video ID Derivation

The `video_id` is derived from the S3 object key by stripping the `uploads/` prefix and the file extension:

| S3 Key | Video ID |
|--------|----------|
| `uploads/sample.mp4` | `sample` |
| `uploads/hello-my_name_is_wes.mp3` | `hello-my_name_is_wes` |
| `uploads/my-talk.wav` | `my-talk` |

The video ID is used for:
- Transcription job naming: `production-rag-{video_id}`
- Transcript output path: `transcripts/{video_id}/raw.json`
- Downstream chunk and embedding IDs

---

## Resources

### Part A: Transcribe Module (Python)

Application code for the transcription Lambda functions. Follows the thin-handlers-thick-services pattern (PRD Section 6.2).

**Directory structure:**

```
modules/transcribe-module/
├── src/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start_transcription.py
│   │   └── check_transcription.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── transcribe_service.py
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── unit/
│       ├── __init__.py
│       └── test_transcribe_service.py
├── requirements.txt
└── dev-requirements.txt
```

**Files to create:**

| File | Purpose |
|------|---------|
| `modules/transcribe-module/src/handlers/start_transcription.py` | Lambda entry point: extract S3 info, call service, return job name |
| `modules/transcribe-module/src/handlers/check_transcription.py` | Lambda entry point: check job status, return status + transcript location |
| `modules/transcribe-module/src/services/transcribe_service.py` | Business logic: start job, check status, derive video_id, detect media format |
| `modules/transcribe-module/src/utils/logger.py` | Structured JSON logger |
| `modules/transcribe-module/requirements.txt` | Runtime dependencies |
| `modules/transcribe-module/dev-requirements.txt` | Test dependencies |
| All `__init__.py` files | Python package markers (empty files) |

---

#### start_transcription handler

**Input (from Step Functions — full EventBridge event):**

```json
{
  "detail": {
    "bucket": {
      "name": "production-rag-media-123456789012"
    },
    "object": {
      "key": "uploads/hello-my_name_is_wes.mp3",
      "size": 15728640
    }
  }
}
```

**Output (returned to Step Functions):**

```json
{
  "statusCode": 200,
  "detail": {
    "transcription_job_name": "production-rag-hello-my_name_is_wes",
    "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
    "bucket_name": "production-rag-media-123456789012",
    "source_key": "uploads/hello-my_name_is_wes.mp3",
    "video_id": "hello-my_name_is_wes",
    "speaker": "Jane Doe",
    "title": "Building RAG Systems",
    "status": "IN_PROGRESS"
  }
}
```

The `speaker` and `title` fields are read from S3 object user metadata (`x-amz-meta-speaker`, `x-amz-meta-title`) via `head_object`. If the uploader did not set metadata, both default to `null`.

**Handler responsibilities:**

1. Extract `detail.bucket.name` and `detail.object.key` from event
2. Call `TranscribeService.get_object_metadata(bucket, key)` to read `speaker` and `title` from S3 object user metadata
3. Call `TranscribeService.derive_video_id(key)` to get the video ID
4. Call `TranscribeService.start_job(bucket, key, video_id)` to start the Transcribe job
5. Return standardized response with job name, output key, `speaker`, `title`, and status

---

#### check_transcription handler

**Input (from Step Functions — transcription detail from previous state):**

```json
{
  "detail": {
    "transcription_job_name": "production-rag-hello-my_name_is_wes",
    "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
    "bucket_name": "production-rag-media-123456789012",
    "source_key": "uploads/hello-my_name_is_wes.mp3",
    "video_id": "hello-my_name_is_wes",
    "speaker": "Jane Doe",
    "title": "Building RAG Systems"
  }
}
```

**Output (returned to Step Functions):**

```json
{
  "statusCode": 200,
  "detail": {
    "transcription_job_name": "production-rag-hello-my_name_is_wes",
    "transcript_s3_key": "transcripts/hello-my_name_is_wes/raw.json",
    "bucket_name": "production-rag-media-123456789012",
    "source_key": "uploads/hello-my_name_is_wes.mp3",
    "video_id": "hello-my_name_is_wes",
    "speaker": "Jane Doe",
    "title": "Building RAG Systems",
    "status": "COMPLETED"
  }
}
```

**Handler responsibilities:**

1. Extract `detail.transcription_job_name` from event
2. Call `TranscribeService.check_job(job_name)` to get current status
3. Propagate all fields from input (including `speaker` and `title`) via `**detail` spread, updating only the `status` field
4. Return standardized response

**Status values:** `IN_PROGRESS`, `COMPLETED`, `FAILED`

---

#### TranscribeService

Business logic layer. All AWS API calls live here.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `derive_video_id(s3_key)` | `"uploads/sample.mp4"` | `"sample"` | Strip `uploads/` prefix and file extension |
| `detect_media_format(s3_key)` | `"uploads/sample.mp4"` | `"mp4"` | Extract format from file extension |
| `get_object_metadata(bucket, key)` | bucket, S3 key | dict with `speaker`, `title` (both nullable) | Read S3 object user metadata via `head_object` |
| `start_job(bucket, key, video_id)` | bucket, S3 key, video_id | dict with job_name, transcript_key, status | Start AWS Transcribe job |
| `check_job(job_name)` | job name | dict with status | Get job status from Transcribe API |

**`get_object_metadata` details:**

1. Call `self._s3.head_object(Bucket=bucket, Key=key)`
2. Read `response.get("Metadata", {})` (S3 lowercases user metadata keys)
3. Return `{"speaker": metadata.get("speaker"), "title": metadata.get("title")}`

The `TranscribeService.__init__` must create an S3 client (`self._s3 = boto3.client("s3")`) in addition to the existing Transcribe client.

**Transcribe API call parameters for `start_job`:**

```python
transcribe_client.start_transcription_job(
    TranscriptionJobName=f"production-rag-{video_id}",
    Media={"MediaFileUri": f"s3://{bucket}/{key}"},
    MediaFormat=media_format,
    LanguageCode="en-US",
    OutputBucketName=bucket,
    OutputKey=f"transcripts/{video_id}/raw.json"
)
```

**Transcribe API call for `check_job`:**

```python
response = transcribe_client.get_transcription_job(
    TranscriptionJobName=job_name
)
status = response["TranscriptionJob"]["TranscriptionJobStatus"]
```

**Media format detection:** Extract from file extension. Supported formats: `mp3`, `mp4`, `wav`, `flac`, `ogg`, `amr`, `webm`.

---

#### Dependencies

**`requirements.txt`:**
```
boto3
```

`boto3` is already available in the Lambda runtime but pinning it in requirements.txt ensures local testing parity.

**`dev-requirements.txt`:**
```
pytest
moto[transcribe,s3]
```

---

### Part B: Lambda Terraform Module

Reusable Terraform module for deploying Lambda functions. Used by transcribe (this stage) and future modules (chunking, embedding, question).

**Files to create:**

| File | Content |
|------|---------|
| `infra/modules/lambda/main.tf` | Lambda function, IAM role, CloudWatch log group, archive data source |
| `infra/modules/lambda/variables.tf` | Function name, handler, runtime, source path, env vars, IAM policy |
| `infra/modules/lambda/outputs.tf` | Function name, function ARN, invoke ARN, role ARN |

**Resources in this module:**

| Resource | Type | Purpose |
|----------|------|---------|
| Archive | `data.archive_file` | Zip the Python source code |
| Lambda function | `aws_lambda_function` | Compute |
| IAM role | `aws_iam_role` | Execution role (trust: `lambda.amazonaws.com`) |
| IAM policy | `aws_iam_role_policy` | Function-specific permissions (passed via variable) |
| Managed policy attachment | `aws_iam_role_policy_attachment` | `AWSLambdaBasicExecutionRole` for CloudWatch Logs |
| CloudWatch log group | `aws_cloudwatch_log_group` | Function logs with 14-day retention |

**Module interface:**

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `function_name` | `string` | yes | — | Lambda function name |
| `handler` | `string` | yes | — | Handler path (e.g. `src.handlers.start_transcription.handler`) |
| `runtime` | `string` | no | `"python3.11"` | Lambda runtime |
| `timeout` | `number` | no | `30` | Timeout in seconds |
| `memory_size` | `number` | no | `256` | Memory in MB |
| `source_dir` | `string` | yes | — | Absolute path to Python source directory to zip |
| `environment_variables` | `map(string)` | no | `{}` | Environment variables |
| `policy_statements` | `string` | yes | — | JSON-encoded IAM policy document for function-specific permissions |
| `tags` | `map(string)` | no | `{}` | Resource tags |

| Output | Description |
|--------|-------------|
| `function_name` | Lambda function name |
| `function_arn` | Lambda function ARN |
| `invoke_arn` | Lambda invoke ARN |
| `role_arn` | IAM execution role ARN |

**Archive configuration:**

The `data.archive_file` zips the `source_dir` directory. Output path: `/tmp/${var.function_name}.zip`. The `source_code_hash` on the Lambda function ensures redeployment when code changes.

---

### Part C: Transcribe Lambda Deployment

Add two Lambda module calls to `infra/environments/dev/main.tf`.

**1. start_transcription Lambda:**

| Setting | Value |
|---------|-------|
| Function name | `${var.project_name}-start-transcription` |
| Handler | `src.handlers.start_transcription.handler` |
| Source dir | `${path.module}/../../../modules/transcribe-module` |
| Runtime | `python3.11` |
| Timeout | `60` |
| Memory | `256` |

IAM permissions:
- `s3:GetObject` on `${module.media_bucket.bucket_arn}/*`
- `s3:PutObject` on `${module.media_bucket.bucket_arn}/transcripts/*`
- `transcribe:StartTranscriptionJob` on `*`

Environment variables:
- `MEDIA_BUCKET` = `module.media_bucket.bucket_name`

**2. check_transcription Lambda:**

| Setting | Value |
|---------|-------|
| Function name | `${var.project_name}-check-transcription` |
| Handler | `src.handlers.check_transcription.handler` |
| Source dir | `${path.module}/../../../modules/transcribe-module` |
| Runtime | `python3.11` |
| Timeout | `30` |
| Memory | `256` |

IAM permissions:
- `transcribe:GetTranscriptionJob` on `*`

Environment variables:
- `MEDIA_BUCKET` = `module.media_bucket.bucket_name`

---

### Part D: Step Functions State Machine Update

Replace the current skeleton state machine with transcription states. The wait/poll loop checks Transcribe job status every 30 seconds.

**Updated state machine definition:**

```
StartAt: ValidateInput

States:
  ValidateInput:
    Type: Pass
    Next: StartTranscription

  StartTranscription:
    Type: Task
    Resource: arn:aws:states:::lambda:invoke
    Parameters:
      FunctionName: <start-transcription-function-arn>
      Payload.$: $
    ResultPath: $.transcription
    ResultSelector:
      detail.$: $.Payload.detail
      statusCode.$: $.Payload.statusCode
    Next: WaitForTranscription
    Retry:
      - ErrorEquals: [Lambda.ServiceException, Lambda.AWSLambdaException, Lambda.SdkClientException]
        IntervalSeconds: 5
        MaxAttempts: 2
        BackoffRate: 2.0
    Catch:
      - ErrorEquals: [States.ALL]
        Next: TranscriptionFailed
        ResultPath: $.error

  WaitForTranscription:
    Type: Wait
    Seconds: 30
    Next: CheckTranscriptionStatus

  CheckTranscriptionStatus:
    Type: Task
    Resource: arn:aws:states:::lambda:invoke
    Parameters:
      FunctionName: <check-transcription-function-arn>
      Payload:
        detail.$: $.transcription.detail
    ResultPath: $.transcription
    ResultSelector:
      detail.$: $.Payload.detail
      statusCode.$: $.Payload.statusCode
    Next: IsTranscriptionComplete
    Retry:
      - ErrorEquals: [Lambda.ServiceException, Lambda.AWSLambdaException, Lambda.SdkClientException]
        IntervalSeconds: 5
        MaxAttempts: 2
        BackoffRate: 2.0
    Catch:
      - ErrorEquals: [States.ALL]
        Next: TranscriptionFailed
        ResultPath: $.error

  IsTranscriptionComplete:
    Type: Choice
    Choices:
      - Variable: $.transcription.detail.status
        StringEquals: COMPLETED
        Next: TranscriptionSucceeded
      - Variable: $.transcription.detail.status
        StringEquals: FAILED
        Next: TranscriptionFailed
    Default: WaitForTranscription

  TranscriptionSucceeded:
    Type: Pass
    End: true

  TranscriptionFailed:
    Type: Fail
    Error: TranscriptionFailed
    Cause: Transcription job failed or encountered an error
```

**State data flow:**

The original S3 EventBridge event is preserved at `$` (root). Transcription results are stored at `$.transcription`. This means downstream stages (chunking, embedding) will have access to:
- `$.detail.bucket.name` — original S3 bucket
- `$.detail.object.key` — original uploaded file key
- `$.transcription.detail.transcript_s3_key` — path to raw transcript
- `$.transcription.detail.video_id` — derived video ID
- `$.transcription.detail.speaker` — speaker name (from S3 object user metadata, nullable)
- `$.transcription.detail.title` — video title (from S3 object user metadata, nullable)

---

### Part E: Step Functions IAM Update

Add Lambda invoke permissions to the existing `sfn_execution` role policy.

**Add to the existing policy statements:**

- `lambda:InvokeFunction` on both:
  - `module.start_transcription.function_arn`
  - `module.check_transcription.function_arn`

---

### Part F: Outputs

**Add to `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `start_transcription_function_name` | `module.start_transcription.function_name` | Start transcription Lambda |
| `check_transcription_function_name` | `module.check_transcription.function_name` | Check transcription Lambda |

---

## Implementation Checklist

- [ ] 1. Create `modules/transcribe-module/requirements.txt` with `boto3`
- [ ] 2. Create `modules/transcribe-module/dev-requirements.txt` with `pytest`, `moto[transcribe,s3]`
- [ ] 3. Create all `__init__.py` files (`src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`)
- [ ] 4. Create `modules/transcribe-module/src/utils/logger.py` with structured logger
- [ ] 5. Create `modules/transcribe-module/src/services/transcribe_service.py` with `derive_video_id`, `detect_media_format`, `get_object_metadata`, `start_job`, `check_job`
- [ ] 6. Create `modules/transcribe-module/src/handlers/start_transcription.py` handler (must call `get_object_metadata` and include `speaker`/`title` in response)
- [ ] 7. Create `modules/transcribe-module/src/handlers/check_transcription.py` handler
- [ ] 8. Create `modules/transcribe-module/tests/conftest.py` with shared fixtures
- [ ] 9. Create `modules/transcribe-module/tests/unit/test_transcribe_service.py` with unit tests
- [ ] 10. Create `infra/modules/lambda/main.tf` with Lambda function, IAM role, log group, archive
- [ ] 11. Create `infra/modules/lambda/variables.tf` with module interface
- [ ] 12. Create `infra/modules/lambda/outputs.tf` with function name, ARN, invoke ARN, role ARN
- [ ] 13. Add `start_transcription` Lambda module call to `infra/environments/dev/main.tf`
- [ ] 14. Add `check_transcription` Lambda module call to `infra/environments/dev/main.tf`
- [ ] 15. Update Step Functions state machine definition in `infra/environments/dev/main.tf` with transcription states
- [ ] 16. Add `lambda:InvokeFunction` permissions to Step Functions IAM role policy in `infra/environments/dev/main.tf`
- [ ] 17. Add new outputs to `infra/environments/dev/outputs.tf`
- [ ] 18. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 19. Verify: upload sample audio and confirm transcription completes end-to-end

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform init
terraform plan
terraform apply
```

### Step 2: Upload a sample audio file

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

The execution should show `RUNNING` status while transcription is in progress.

### Step 4: Wait for transcription to complete

Transcription typically takes 30-120 seconds for a short audio file.

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

### Step 5: Verify transcript in S3

```bash
BUCKET=$(terraform output -raw media_bucket_name)

aws s3 ls "s3://${BUCKET}/transcripts/hello-my_name_is_wes/"
```

Expected: `raw.json` file exists.

```bash
aws s3 cp "s3://${BUCKET}/transcripts/hello-my_name_is_wes/raw.json" /tmp/transcript.json

python3 -c "
import json
t = json.load(open('/tmp/transcript.json'))
print('Transcript:', t['results']['transcripts'][0]['transcript'][:200])
print('Word count:', len(t['results']['items']))
"
```

### Step 6: Inspect Step Functions execution history

```bash
aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --query "events[?type=='TaskStateExited'].stateExitedEventDetails.name" \
  --output table
```

Expected: Shows `StartTranscription`, `CheckTranscriptionStatus` (possibly multiple times), and `TranscriptionSucceeded`.

### Step 7: Verify wait/poll loop

```bash
aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --query "length(events[?type=='WaitStateExited'])"
```

Expected: At least 1 (likely 2-4 iterations for a short audio file).

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Transcribe module code exists | `modules/transcribe-module/src/` has handlers and services directories with Python files |
| Lambda Terraform module exists | `infra/modules/lambda/` has `main.tf`, `variables.tf`, `outputs.tf` |
| Both Lambda functions deployed | `aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'production-rag')]"` shows start and check functions |
| Step Functions has transcription states | State machine definition includes `StartTranscription`, `WaitForTranscription`, `CheckTranscriptionStatus`, `IsTranscriptionComplete`, `TranscriptionSucceeded`, `TranscriptionFailed` |
| Upload triggers transcription | Upload to `uploads/` → execution starts → StartTranscription Lambda invoked |
| Wait/poll loop operates | Execution history shows `WaitForTranscription` → `CheckTranscriptionStatus` cycle |
| Transcription completes successfully | Execution reaches `TranscriptionSucceeded` state with `SUCCEEDED` status |
| Transcript stored in S3 | `s3://<bucket>/transcripts/<video-id>/raw.json` exists and contains valid JSON |
| Transcript contains text | `results.transcripts[0].transcript` is a non-empty string |
| Transcript has word-level timing | `results.items` array contains pronunciation entries with `start_time` and `end_time` |
| Speaker/title propagated | `$.transcription.detail.speaker` and `$.transcription.detail.title` are present in execution state (values from S3 object metadata, or `null` if not set) |
| Error handling works | TranscriptionFailed state catches invalid input or Transcribe failures |
| Original event preserved | Execution output still contains `$.detail.bucket.name` and `$.detail.object.key` |
