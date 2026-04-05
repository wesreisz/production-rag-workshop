# Transcription Stage Implementation Plan

## Current State

- No `modules/` directory exists
- No `infra/modules/lambda/` exists
- State machine is a skeleton: `ValidateInput` Pass -> End
- Step Functions IAM has CloudWatch Logs only; `additional_policy_json` is wired but unused (`null`)
- `samples/hello-my_name_is_wes.mp3` exists for testing

## Implementation Checklist

- [ ] 1. Create `modules/transcribe-module/requirements.txt` with boto3
- [ ] 2. Create `modules/transcribe-module/dev-requirements.txt` with pytest, moto[transcribe,s3]
- [ ] 3. Create all 6 `__init__.py` files (src/, handlers/, services/, utils/, tests/, tests/unit/)
- [ ] 4. Create `modules/transcribe-module/src/utils/logger.py` with structured logger
- [ ] 5. Create `modules/transcribe-module/src/services/transcribe_service.py` with 4 methods
- [ ] 6. Create `modules/transcribe-module/src/handlers/start_transcription.py` handler
- [ ] 7. Create `modules/transcribe-module/src/handlers/check_transcription.py` handler
- [ ] 8. Create `modules/transcribe-module/tests/conftest.py` with shared fixtures
- [ ] 9. Create `modules/transcribe-module/tests/unit/test_transcribe_service.py` with unit tests
- [ ] 10. Create `infra/modules/lambda/main.tf` with Lambda, IAM, archive, log group
- [ ] 11. Create `infra/modules/lambda/variables.tf` with module interface
- [ ] 12. Create `infra/modules/lambda/outputs.tf` with function_name, ARN, invoke_arn, role_arn
- [ ] 13. Add start_transcription Lambda module call to `infra/environments/dev/main.tf`
- [ ] 14. Add check_transcription Lambda module call to `infra/environments/dev/main.tf`
- [ ] 15. Update Step Functions state machine definition with transcription states
- [ ] 16. Add `lambda:InvokeFunction` permissions via `additional_policy_json` to pipeline module
- [ ] 17. Add start/check transcription function name outputs to `outputs.tf`
- [ ] 18. Run `terraform init && terraform apply` (user-driven)
- [ ] 19. End-to-end verification (user-driven)

---

## Part A: Transcribe Module (Python) — Steps 1-9

### Step 1: `modules/transcribe-module/requirements.txt`

Single dependency:

```
boto3
```

### Step 2: `modules/transcribe-module/dev-requirements.txt`

```
pytest
moto[transcribe,s3]
```

### Step 3: All `__init__.py` files (6 empty files)

- `modules/transcribe-module/src/__init__.py`
- `modules/transcribe-module/src/handlers/__init__.py`
- `modules/transcribe-module/src/services/__init__.py`
- `modules/transcribe-module/src/utils/__init__.py`
- `modules/transcribe-module/tests/__init__.py`
- `modules/transcribe-module/tests/unit/__init__.py`

### Step 4: `modules/transcribe-module/src/utils/logger.py`

- `get_logger(name)` function returning `logging.Logger` at INFO level
- JSON-structured formatting per architecture rules

### Step 5: `modules/transcribe-module/src/services/transcribe_service.py`

`TranscribeService` class with boto3 Transcribe client, four methods:

- `derive_video_id(s3_key)` — Strip `uploads/` prefix and file extension via `os.path.splitext` and string replace
- `detect_media_format(s3_key)` — Extract extension, validate against supported list: mp3, mp4, wav, flac, ogg, amr, webm
- `start_job(bucket, key, video_id)` — Call `transcribe_client.start_transcription_job(...)` with params from spec, return dict with job_name, transcript_key, status="IN_PROGRESS"
- `check_job(job_name)` — Call `transcribe_client.get_transcription_job(...)`, extract and return status

Service instantiated at module level for Lambda warm-start reuse.

### Step 6: `modules/transcribe-module/src/handlers/start_transcription.py`

- `handler(event, context)` — extract `event["detail"]["bucket"]["name"]` and `event["detail"]["object"]["key"]`
- Call `TranscribeService.derive_video_id()` then `start_job()`
- Return `{"statusCode": 200, "detail": {...}}` with all fields from spec
- Try/except: `ValueError` -> 400, `Exception` -> 500

### Step 7: `modules/transcribe-module/src/handlers/check_transcription.py`

- `handler(event, context)` — extract `event["detail"]["transcription_job_name"]`
- Call `TranscribeService.check_job()`
- Propagate all input fields, update only `status`
- Return `{"statusCode": 200, "detail": {...}}`
- Same error handling pattern

### Step 8: `modules/transcribe-module/tests/conftest.py`

- `aws_credentials` fixture — set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SECURITY_TOKEN`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION` env vars to fake values
- `mock_aws_services` fixture — use moto mock decorators for transcribe and s3

### Step 9: `modules/transcribe-module/tests/unit/test_transcribe_service.py`

Hybrid test strategy:

- **Pure logic tests** (no mocking): `derive_video_id` with various inputs (mp3, mp4, wav), `detect_media_format` with valid and invalid extensions
- **moto tests**: `start_job` — create mock S3 bucket/object, call `start_job`, assert Transcribe API was called with correct params and return dict has expected shape
- **unittest.mock tests**: `check_job` — patch `get_transcription_job` response to return each status (COMPLETED, IN_PROGRESS, FAILED), assert return value

---

## Part B: Lambda Terraform Module — Steps 10-12

### Step 10: `infra/modules/lambda/main.tf`

Resources:

- `data.archive_file` — zip `var.source_dir` to `/tmp/${var.function_name}.zip`
- `aws_lambda_function` — using archive output, `source_code_hash` for redeploy detection
- `aws_iam_role` — trust `lambda.amazonaws.com`
- `aws_iam_role_policy` — function-specific permissions from `var.policy_statements`
- `aws_iam_role_policy_attachment` — `AWSLambdaBasicExecutionRole` managed policy
- `aws_cloudwatch_log_group` — `/aws/lambda/${var.function_name}`, 14-day retention

### Step 11: `infra/modules/lambda/variables.tf`

Variables: `function_name`, `handler`, `runtime` (default `python3.11`), `timeout` (default `30`), `memory_size` (default `256`), `source_dir`, `environment_variables` (default `{}`), `policy_statements`, `tags` (default `{}`)

### Step 12: `infra/modules/lambda/outputs.tf`

Outputs: `function_name`, `function_arn`, `invoke_arn`, `role_arn`

---

## Parts C-F: Deployment Wiring — Steps 13-17

All edits in existing files under `infra/environments/dev/`.

### Steps 13-14: Add Lambda module calls to `infra/environments/dev/main.tf`

Two new `module` blocks:

- `module "start_transcription"` — function name `${var.project_name}-start-transcription`, handler `src.handlers.start_transcription.handler`, timeout 60, IAM: s3:GetObject, s3:PutObject on transcripts/*, transcribe:StartTranscriptionJob on *
- `module "check_transcription"` — function name `${var.project_name}-check-transcription`, handler `src.handlers.check_transcription.handler`, timeout 30, IAM: transcribe:GetTranscriptionJob on *

Both set `MEDIA_BUCKET` env var from `module.media_bucket.bucket_name`.

### Step 15: Update Step Functions state machine definition in `infra/environments/dev/main.tf`

Replace the inline `definition = jsonencode({...})` in the `pipeline` module with the full 7-state machine from the spec. Lambda ARNs interpolated as `module.start_transcription.function_arn` and `module.check_transcription.function_arn`.

States: ValidateInput -> StartTranscription -> WaitForTranscription (30s) -> CheckTranscriptionStatus -> IsTranscriptionComplete (Choice) -> TranscriptionSucceeded/TranscriptionFailed/loop back.

### Step 16: Add `lambda:InvokeFunction` to Step Functions IAM

Pass `additional_policy_json` to the `pipeline` module with `lambda:InvokeFunction` on both `module.start_transcription.function_arn` and `module.check_transcription.function_arn`.

### Step 17: Add outputs to `infra/environments/dev/outputs.tf`

- `start_transcription_function_name`
- `check_transcription_function_name`

---

## Post-implementation

### Step 18: `terraform init && terraform apply`

Run from `infra/environments/dev/`. User-driven (not automated).

### Step 19: End-to-end verification

Upload sample audio, monitor Step Functions, verify transcript in S3. User-driven using verification commands from spec.
