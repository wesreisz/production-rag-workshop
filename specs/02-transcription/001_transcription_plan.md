# Implementation Plan: Transcription (001)

**Goal:** Implement two Lambda functions (start + check transcription), a reusable Lambda Terraform module, and update the Step Functions state machine with a wait/poll loop so that uploading audio to `uploads/` triggers AWS Transcribe and stores the transcript at `transcripts/{video_id}/raw.json`.

**Status:** Not started. All prerequisites met (Stage 1 infra deployed, sample audio exists).

---

## New Files (17)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/transcribe-module/requirements.txt` | Runtime dep: `boto3` |
| 2 | `modules/transcribe-module/dev-requirements.txt` | Test deps: `pytest`, `moto[transcribe,s3]` |
| 3 | `modules/transcribe-module/src/__init__.py` | Package marker (empty) |
| 4 | `modules/transcribe-module/src/handlers/__init__.py` | Package marker (empty) |
| 5 | `modules/transcribe-module/src/services/__init__.py` | Package marker (empty) |
| 6 | `modules/transcribe-module/src/utils/__init__.py` | Package marker (empty) |
| 7 | `modules/transcribe-module/tests/__init__.py` | Package marker (empty) |
| 8 | `modules/transcribe-module/tests/unit/__init__.py` | Package marker (empty) |
| 9 | `modules/transcribe-module/src/utils/logger.py` | `get_logger(name)` returning `logging.Logger` at INFO with structured JSON output |
| 10 | `modules/transcribe-module/tests/conftest.py` | Shared pytest fixtures: `aws_credentials` (monkeypatch env vars), `mock_aws_services` (moto mock for transcribe + s3) |
| 11 | `modules/transcribe-module/tests/unit/test_transcribe_service.py` | Unit tests for all four `TranscribeService` methods |
| 12 | `modules/transcribe-module/src/services/transcribe_service.py` | `TranscribeService` class: `derive_video_id`, `detect_media_format`, `start_job`, `check_job` |
| 13 | `modules/transcribe-module/src/handlers/start_transcription.py` | Thin handler: extract S3 info from event, call service, return Step Functions response |
| 14 | `modules/transcribe-module/src/handlers/check_transcription.py` | Thin handler: extract job name from event, call service, propagate all fields + updated status |
| 15 | `infra/modules/lambda/main.tf` | Reusable module: `data.archive_file`, `aws_lambda_function`, `aws_iam_role`, `aws_iam_role_policy`, `aws_iam_role_policy_attachment`, `aws_cloudwatch_log_group` |
| 16 | `infra/modules/lambda/variables.tf` | Module inputs: `function_name`, `handler`, `runtime`, `timeout`, `memory_size`, `source_dir`, `environment_variables`, `policy_statements`, `tags` |
| 17 | `infra/modules/lambda/outputs.tf` | Module outputs: `function_name`, `function_arn`, `invoke_arn`, `role_arn` |

## Files to Modify (3)

| # | File | Change |
|---|------|--------|
| 18 | `infra/environments/dev/main.tf` | Add two Lambda module calls (Parts C), replace SFN definition with 7-state transcription flow (Part D), add new IAM policy for `lambda:InvokeFunction` (Part E) |
| 19 | `infra/environments/dev/outputs.tf` | Add `start_transcription_function_name`, `check_transcription_function_name` (Part F) |
| 20 | `tests/02-transcription/verify.sh` | Fix bug on line 10: change `pip install -f` to `pip install -r` |

---

## Architecture Decisions

1. **TDD ordering** — Tests (conftest + unit tests) are written before implementation code per workspace coding standards, then verified after implementation is complete.
2. **`policy_statements` as JSON string** — The Lambda module accepts a JSON-encoded IAM policy document string (not native HCL objects) for maximum flexibility across different callers. Intentional per spec.
3. **Separate IAM policy resource for Lambda invoke** — A new `aws_iam_role_policy.step_functions_lambda` is added alongside the existing `step_functions_logging` policy, rather than merging them. Keeps separation of concerns, avoids modifying the logging policy.
4. **Archive output path** — `/tmp/${var.function_name}.zip` per spec. Both Lambda functions share the same `source_dir` (the whole `transcribe-module` directory) but produce separate zips.
5. **SFN definition inline** — Continues the pattern from Stage 1. The `jsonencode` block in `main.tf` contains the full ASL definition. No separate `.asl.json` file.
6. **Lambda ARN in SFN** — Uses `module.start_transcription.function_arn` and `module.check_transcription.function_arn` interpolated into the `jsonencode` block. This creates an implicit dependency so Terraform orders correctly.
7. **TranscribeService instantiated at module level** — The boto3 client is created inside the class constructor. The service instance lives at module level (outside the handler function) for Lambda warm-start connection reuse.

---

## Risks / Assumptions

- AWS credentials configured in environment with permissions for Lambda, Transcribe, S3, Step Functions, IAM, CloudWatch Logs
- `moto[transcribe,s3]` provides sufficient mock coverage for `start_transcription_job` and `get_transcription_job` — if not, tests may need adjustments
- `data.archive_file` zips the entire `transcribe-module` directory (including `tests/`, `requirements.txt`) — this is acceptable for dev; a production build would exclude test files
- Terraform `jsonencode` for the SFN definition must produce valid ASL JSON — HCL key ordering and `.$` suffix keys need careful handling (HCL keys with special characters require quoting)
- The `TranscriptionFailed` state is a `Fail` type, which means the SFN `Catch` on `StartTranscription` and `CheckTranscriptionStatus` route to a terminal failure — no retry at the state machine level beyond the per-state `Retry` config

---

## Implementation Checklist

### Part A: Transcribe Module (Python)

- [ ] 1. Create `modules/transcribe-module/requirements.txt` — single line: `boto3`
- [ ] 2. Create `modules/transcribe-module/dev-requirements.txt` — two lines: `pytest`, `moto[transcribe,s3]`
- [ ] 3. Create 6 empty `__init__.py` files: `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`
- [ ] 4. Create `modules/transcribe-module/src/utils/logger.py` — function `get_logger(name)` that returns a `logging.Logger` at INFO level with a `logging.StreamHandler` and a JSON-structured formatter including `timestamp`, `level`, `name`, `message`, and `request_id` from `extra`
- [ ] 5. Create `modules/transcribe-module/tests/conftest.py` — two fixtures:
  - `aws_credentials`: monkeypatch `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SECURITY_TOKEN`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION` to dummy/`us-east-1` values
  - `mock_aws_services`: depends on `aws_credentials`, uses `moto.mock_aws` context manager, yields dict with `transcribe` (boto3 Transcribe client) and `s3` (boto3 S3 client)
- [ ] 6. Create `modules/transcribe-module/tests/unit/test_transcribe_service.py` — tests using AAA pattern:
  - `test_derive_video_id` — input `"uploads/hello-my_name_is_wes.mp3"` → output `"hello-my_name_is_wes"`
  - `test_derive_video_id_mp4` — input `"uploads/sample.mp4"` → output `"sample"`
  - `test_detect_media_format_mp3` — input `"uploads/sample.mp3"` → output `"mp3"`
  - `test_detect_media_format_mp4` — input `"uploads/sample.mp4"` → output `"mp4"`
  - `test_start_job` — use `mock_aws_services`, create S3 bucket, call `start_job`, assert returned dict has `job_name` matching `"production-rag-{video_id}"`, `transcript_key` matching `"transcripts/{video_id}/raw.json"`, `status` is `"IN_PROGRESS"`
  - `test_check_job_in_progress` — use `mock_aws_services`, start a job first, then call `check_job`, assert status is `"IN_PROGRESS"`
- [ ] 7. Create `modules/transcribe-module/src/services/transcribe_service.py` — class `TranscribeService`:
  - Constructor: accept optional `transcribe_client` param, default to `boto3.client("transcribe")`
  - `derive_video_id(s3_key)`: strip `"uploads/"` prefix via split, strip extension via `os.path.splitext`, return filename stem
  - `detect_media_format(s3_key)`: `os.path.splitext(s3_key)[1]` stripped of leading dot, lowercased
  - `start_job(bucket, key, video_id)`: call `transcribe_client.start_transcription_job(...)` with params from spec, return dict `{"job_name": ..., "transcript_key": ..., "status": "IN_PROGRESS"}`
  - `check_job(job_name)`: call `transcribe_client.get_transcription_job(...)`, extract `TranscriptionJobStatus`, return dict `{"status": ...}`
- [ ] 8. Create `modules/transcribe-module/src/handlers/start_transcription.py`:
  - Module-level `TranscribeService` instance
  - `handler(event, context)`: extract `bucket_name` from `event["detail"]["bucket"]["name"]`, `object_key` from `event["detail"]["object"]["key"]`, call `derive_video_id`, call `start_job`, return `{"statusCode": 200, "detail": {...}}` with all 6 fields from spec
  - Wrap in try/except: `ValueError` → 400, `Exception` → 500 with `{"error": "internal error"}`
- [ ] 9. Create `modules/transcribe-module/src/handlers/check_transcription.py`:
  - Module-level `TranscribeService` instance
  - `handler(event, context)`: extract `detail` dict from `event["detail"]`, get `transcription_job_name`, call `check_job`, copy all fields from input detail, update `status` from check result, return `{"statusCode": 200, "detail": {...}}`
  - Same try/except pattern as start handler
- [ ] 10. Install deps and run tests: `cd modules/transcribe-module && pip install -r dev-requirements.txt -r requirements.txt && python -m pytest tests/ -v`

### Part B: Lambda Terraform Module

- [ ] 11. Create `infra/modules/lambda/variables.tf` — 9 variables exactly matching spec table: `function_name` (string, required), `handler` (string, required), `runtime` (string, default `"python3.11"`), `timeout` (number, default `30`), `memory_size` (number, default `256`), `source_dir` (string, required), `environment_variables` (map(string), default `{}`), `policy_statements` (string, required), `tags` (map(string), default `{}`)
- [ ] 12. Create `infra/modules/lambda/main.tf` — 6 resources:
  - `data.archive_file.lambda_zip`: type `"zip"`, `source_dir = var.source_dir`, `output_path = "/tmp/${var.function_name}.zip"`
  - `aws_lambda_function.this`: `function_name`, `handler`, `runtime`, `timeout`, `memory_size`, `filename = data.archive_file.lambda_zip.output_path`, `source_code_hash = data.archive_file.lambda_zip.output_base64sha256`, `role = aws_iam_role.this.arn`, environment block from `var.environment_variables`, `tags = var.tags`
  - `aws_iam_role.this`: name `"${var.function_name}-role"`, trust policy for `lambda.amazonaws.com`
  - `aws_iam_role_policy.this`: name `"${var.function_name}-policy"`, role `aws_iam_role.this.id`, `policy = var.policy_statements`
  - `aws_iam_role_policy_attachment.basic_execution`: role `aws_iam_role.this.name`, `policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"`
  - `aws_cloudwatch_log_group.this`: name `"/aws/lambda/${var.function_name}"`, `retention_in_days = 14`, `tags = var.tags`
- [ ] 13. Create `infra/modules/lambda/outputs.tf` — 4 outputs: `function_name` (`.function_name`), `function_arn` (`.arn`), `invoke_arn` (`.invoke_arn`), `role_arn` (`aws_iam_role.this.arn`)

### Part C: Transcribe Lambda Deployment

- [ ] 14. Add `module "start_transcription"` block to `infra/environments/dev/main.tf` — source `../../modules/lambda`, `function_name = "${var.project_name}-start-transcription"`, `handler = "src.handlers.start_transcription.handler"`, `source_dir = "${path.module}/../../../modules/transcribe-module"`, `timeout = 60`, `memory_size = 256`, `environment_variables = { MEDIA_BUCKET = module.media_bucket.bucket_name }`, `policy_statements = jsonencode(...)` with S3 GetObject on `${module.media_bucket.bucket_arn}/*`, S3 PutObject on `${module.media_bucket.bucket_arn}/transcripts/*`, `transcribe:StartTranscriptionJob` on `*`
- [ ] 15. Add `module "check_transcription"` block to `infra/environments/dev/main.tf` — same source, `function_name = "${var.project_name}-check-transcription"`, `handler = "src.handlers.check_transcription.handler"`, same `source_dir`, `timeout = 30`, `memory_size = 256`, `environment_variables = { MEDIA_BUCKET = module.media_bucket.bucket_name }`, `policy_statements = jsonencode(...)` with `transcribe:GetTranscriptionJob` on `*`

### Part D: Step Functions State Machine Update

- [ ] 16. Replace the `definition` block in `aws_sfn_state_machine.pipeline` in `infra/environments/dev/main.tf` — change from single `ValidateInput` Pass (End: true) to 7 states:
  - `ValidateInput`: Pass, Next → `StartTranscription`
  - `StartTranscription`: Task, Resource `arn:aws:states:::lambda:invoke`, Parameters with FunctionName from `module.start_transcription.function_arn`, `Payload.$: "$"`, ResultPath `$.transcription`, ResultSelector extracting `detail` and `statusCode` from `Payload`, Retry on Lambda service errors (interval 5, max 2, backoff 2.0), Catch all → `TranscriptionFailed` with ResultPath `$.error`, Next → `WaitForTranscription`
  - `WaitForTranscription`: Wait 30 seconds, Next → `CheckTranscriptionStatus`
  - `CheckTranscriptionStatus`: Task, same Resource, Parameters with FunctionName from `module.check_transcription.function_arn`, `Payload` with `detail.$: "$.transcription.detail"`, same ResultPath/ResultSelector/Retry/Catch pattern, Next → `IsTranscriptionComplete`
  - `IsTranscriptionComplete`: Choice, check `$.transcription.detail.status` — COMPLETED → `TranscriptionSucceeded`, FAILED → `TranscriptionFailed`, Default → `WaitForTranscription`
  - `TranscriptionSucceeded`: Pass, End true
  - `TranscriptionFailed`: Fail, Error `"TranscriptionFailed"`, Cause `"Transcription job failed or encountered an error"`
  - **Note:** HCL keys containing `.$` must be quoted strings in the `jsonencode` block (e.g., `"Payload.$" = "$"`)

### Part E: Step Functions IAM Update

- [ ] 17. Add new `aws_iam_role_policy.step_functions_lambda` resource in `infra/environments/dev/main.tf` — name `"${var.project_name}-step-functions-lambda"`, role `aws_iam_role.step_functions.id`, policy with `lambda:InvokeFunction` on both `module.start_transcription.function_arn` and `module.check_transcription.function_arn`

### Part F: Outputs

- [ ] 18. Add two outputs to `infra/environments/dev/outputs.tf`: `start_transcription_function_name` = `module.start_transcription.function_name`, `check_transcription_function_name` = `module.check_transcription.function_name`

### Bug Fix

- [ ] 19. Fix `tests/02-transcription/verify.sh` line 10: change `pip install -f dev-requirements.txt && requirements.txt` to `pip install -r dev-requirements.txt -r requirements.txt`

### Verify

- [ ] 20. Run `terraform init` in `infra/environments/dev/` (needed to pick up new Lambda module)
- [ ] 21. Run `terraform plan` to verify no errors
- [ ] 22. Run `terraform apply` to deploy
- [ ] 23. Upload sample audio and confirm transcription completes end-to-end (via `tests/02-transcription/verify.sh` or manual steps from spec)

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
