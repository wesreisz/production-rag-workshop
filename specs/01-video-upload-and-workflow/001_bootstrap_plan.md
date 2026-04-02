# 001_bootstrap Implementation Plan

## Design Decisions (from research + innovate)

- Step Functions + EventBridge → single reusable module at `infra/modules/step-functions/`
- EventBridge always included (no toggle flag)
- State machine definition JSON passed in from caller via `jsonencode()`
- Module accepts `additional_policy_json` (default `null`) for future IAM extensions
- S3 backend account ID hardcoded in `versions.tf`
- Build exactly what the spec needs, nothing more

## Deviation from Spec

The spec puts Step Functions (Part D) and EventBridge (Part E) resources inline in `dev/main.tf`. We extract them into `infra/modules/step-functions/` per the terraform.mdc rule guidance and user decision. The module accepts `project_name` and derives all resource names internally.

---

## Implementation Checklist

- [ ] 1. Run `terraform init && terraform apply` in `infra/bootstrap/` (no file changes)
- [ ] 2. Create `infra/modules/s3/` (main.tf, variables.tf, outputs.tf)
- [ ] 3. Create `infra/modules/step-functions/` (main.tf, variables.tf, outputs.tf)
- [ ] 4. Create `infra/environments/dev/` (versions.tf, variables.tf, locals.tf, main.tf, outputs.tf)
- [ ] 5. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 6. Run `verify.sh` to confirm S3 upload triggers Step Functions execution

---

## File-by-File Plan

### Part A: Bootstrap (files exist, just apply)

Run `terraform init && terraform apply` in `infra/bootstrap/`. No file changes needed — existing `main.tf`, `variables.tf`, `outputs.tf` match the spec exactly.

---

### Part B: Dev Environment — 5 files

**`infra/environments/dev/versions.tf`**
- `terraform` block: `required_version = ">= 1.5"`, AWS provider `~> 5.0`
- `backend "s3"` block: bucket `production-rag-tf-state-ACCOUNT_ID` (hardcoded), key `dev/terraform.tfstate`, dynamodb_table `production-rag-tf-lock`, region `us-east-1`

**`infra/environments/dev/variables.tf`**
- `environment` (string, default `"dev"`, validation: must be dev/staging/prod)
- `aws_region` (string, default `"us-east-1"`)
- `project_name` (string, default `"production-rag"`)

**`infra/environments/dev/locals.tf`**
- `data.aws_caller_identity.current` for account_id
- `local.account_id` = `data.aws_caller_identity.current.account_id`
- `local.common_tags` = `{ Environment, Project, ManagedBy }`

**`infra/environments/dev/main.tf`**
- `provider "aws"` with region and `default_tags` using `local.common_tags`
- `module "media_bucket"` calling `../../modules/s3` with:
  - `bucket_name = "production-rag-media-${local.account_id}"`
  - `enable_eventbridge = true`
  - `tags = local.common_tags`
- `module "pipeline"` calling `../../modules/step-functions` with:
  - `project_name = var.project_name`
  - `source_bucket_name = module.media_bucket.bucket_name`
  - `object_key_prefix = "uploads/"`
  - `tags = local.common_tags`
  - `definition = jsonencode({ StartAt = "ValidateInput", States = { ValidateInput = { Type = "Pass", End = true } } })`

**`infra/environments/dev/outputs.tf`**
- `media_bucket_name` = `module.media_bucket.bucket_name` (verify script depends on this exact name)
- `state_machine_arn` = `module.pipeline.state_machine_arn` (verify script depends on this exact name)

---

### Part C: S3 Module — 3 files

**`infra/modules/s3/main.tf`**
- `aws_s3_bucket.this` with `bucket = var.bucket_name`, `tags = var.tags`
- `aws_s3_bucket_versioning.this` — Enabled
- `aws_s3_bucket_server_side_encryption_configuration.this` — AES256
- `aws_s3_bucket_public_access_block.this` — all four flags true
- `aws_s3_bucket_notification.this` — `count = var.enable_eventbridge ? 1 : 0`, `eventbridge = true`

**`infra/modules/s3/variables.tf`**
- `bucket_name` (string, required)
- `enable_eventbridge` (bool, default `true`)
- `tags` (map(string), default `{}`)

**`infra/modules/s3/outputs.tf`**
- `bucket_name` = `aws_s3_bucket.this.bucket`
- `bucket_arn` = `aws_s3_bucket.this.arn`
- `bucket_id` = `aws_s3_bucket.this.id`

---

### Part D+E: Step Functions Module — 3 files

**`infra/modules/step-functions/main.tf`**

Resources (9 total):

- `aws_sfn_state_machine.this` — name `${var.project_name}-pipeline`, definition from `var.definition`, role from `aws_iam_role.execution.arn`, logging config at ALL level
- `aws_iam_role.execution` — name `${var.project_name}-sfn-execution`, trust policy for `states.amazonaws.com`
- `aws_iam_role_policy.logging` — CloudWatch Logs permissions (the 8 actions listed in the spec on `*`)
- `aws_iam_role_policy.additional` — `count = var.additional_policy_json != null ? 1 : 0`, attaches `var.additional_policy_json`
- `aws_cloudwatch_log_group.this` — name `/aws/stepfunctions/${var.project_name}-pipeline`
- `aws_cloudwatch_event_rule.trigger` — name `${var.project_name}-s3-upload-trigger`, event pattern matching `aws.s3` / `Object Created` / bucket name / key prefix
- `aws_cloudwatch_event_target.trigger` — target_id `start-pipeline`, arn = state machine, role = eventbridge role
- `aws_iam_role.eventbridge` — name `${var.project_name}-eventbridge-sfn`, trust policy for `events.amazonaws.com`
- `aws_iam_role_policy.eventbridge` — `states:StartExecution` on the state machine ARN

**`infra/modules/step-functions/variables.tf`**
- `project_name` (string, required) — used to derive all resource names
- `definition` (string, required) — state machine definition JSON
- `source_bucket_name` (string, required) — for EventBridge event pattern
- `object_key_prefix` (string, default `"uploads/"`) — for EventBridge event pattern
- `additional_policy_json` (string, default `null`) — extra IAM policy for the execution role
- `tags` (map(string), default `{}`)

**`infra/modules/step-functions/outputs.tf`**
- `state_machine_arn` = `aws_sfn_state_machine.this.arn`
- `state_machine_name` = `aws_sfn_state_machine.this.name`
- `execution_role_arn` = `aws_iam_role.execution.arn`

---

### Verification (no file changes)

After `terraform apply` in both bootstrap and dev:
- Run `bash tests/01-video-upload-and-workflow/verify.sh` (not modified)
- Expects: upload triggers Step Functions execution, script exits 0

---

## Directory Structure After Implementation

```
infra/
  bootstrap/              (exists, no changes)
    main.tf
    variables.tf
    outputs.tf
  environments/dev/       (new, 5 files)
    versions.tf
    variables.tf
    locals.tf
    main.tf
    outputs.tf
  modules/
    s3/                   (new, 3 files)
      main.tf
      variables.tf
      outputs.tf
    step-functions/       (new, 3 files)
      main.tf
      variables.tf
      outputs.tf
```

Total: **11 new files**, 0 modified files.
