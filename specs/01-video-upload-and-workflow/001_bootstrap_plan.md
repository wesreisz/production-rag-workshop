# Implementation Plan: Bootstrap (001)

**Goal:** Create the dev environment configuration, S3 module, Step Functions skeleton, and EventBridge rule so that uploading a file to `s3://<bucket>/uploads/` triggers a Step Functions execution.

**Status:** Part A (bootstrap) is complete. Parts B–E remain.

---

## New Files (8)

| # | File | Purpose |
|---|------|---------|
| 1 | `infra/modules/s3/variables.tf` | Module input: `bucket_name` (string, required), `enable_eventbridge` (bool, default true), `tags` (map(string), default {}) |
| 2 | `infra/modules/s3/main.tf` | 5 resources: S3 bucket, versioning, encryption, public access block, EventBridge notification (conditional) |
| 3 | `infra/modules/s3/outputs.tf` | 3 outputs: `bucket_name`, `bucket_arn`, `bucket_id` |
| 4 | `infra/environments/dev/versions.tf` | Terraform/provider constraints, S3 backend config |
| 5 | `infra/environments/dev/variables.tf` | `environment`, `aws_region`, `project_name` |
| 6 | `infra/environments/dev/locals.tf` | `aws_caller_identity` data source, `account_id`, `common_tags` |
| 7 | `infra/environments/dev/main.tf` | Provider, S3 module call, Step Functions (4 resources), EventBridge (4 resources) |
| 8 | `infra/environments/dev/outputs.tf` | `media_bucket_name`, `state_machine_arn` |

---

## Architecture Decisions

1. **S3 backend** — `backend "s3"` cannot use variables. Hardcode `key`, `region`, `dynamodb_table` in `versions.tf`; pass `bucket` via `-backend-config` at init time.
2. **EventBridge notification** — `aws_s3_bucket_notification` with `count = var.enable_eventbridge ? 1 : 0`.
3. **Event pattern** — Built with `jsonencode`, bucket name from S3 module output.
4. **Step Functions ASL** — Inline `jsonencode`: `{ StartAt: "ValidateInput", States: { ValidateInput: { Type: "Pass", End: true } } }`.
5. **IAM roles** — Two separate roles: Step Functions execution (trusts `states.amazonaws.com`), EventBridge (trusts `events.amazonaws.com`). Both use inline policies (`aws_iam_role_policy`).
6. **Naming** — All names per spec: `production-rag-pipeline`, `production-rag-s3-upload-trigger`, `production-rag-media-<account-id>`.

---

## Risks / Assumptions

- AWS credentials configured with sufficient permissions
- Bootstrap applied (confirmed — tfstate exists)
- S3 backend bucket name requires account ID at init time (partial backend config)
- EventBridge propagation delay handled by verify script's 5-second sleep
- Region is `us-east-1` throughout

---

## Implementation Checklist

- [ ] 1. Create directory `infra/modules/s3/`
- [ ] 2. Create `infra/modules/s3/variables.tf` — three variables: `bucket_name` (string, required), `enable_eventbridge` (bool, default true), `tags` (map(string), default {})
- [ ] 3. Create `infra/modules/s3/main.tf` — five resources:
  - `aws_s3_bucket.this` using `var.bucket_name`, `tags = var.tags`
  - `aws_s3_bucket_versioning.this` with status "Enabled"
  - `aws_s3_bucket_server_side_encryption_configuration.this` with AES256
  - `aws_s3_bucket_public_access_block.this` with all four block flags = true
  - `aws_s3_bucket_notification.this` with `count = var.enable_eventbridge ? 1 : 0`, `eventbridge = true`
- [ ] 4. Create `infra/modules/s3/outputs.tf` — `bucket_name` (.bucket), `bucket_arn` (.arn), `bucket_id` (.id)
- [ ] 5. Create directory `infra/environments/dev/`
- [ ] 6. Create `infra/environments/dev/versions.tf` — `required_version = ">= 1.5"`, `required_providers` (aws ~> 5.0), `backend "s3"` with key `dev/terraform.tfstate`, region `us-east-1`, dynamodb_table `production-rag-tf-lock` (bucket at init time)
- [ ] 7. Create `infra/environments/dev/variables.tf` — `environment` (default "dev"), `aws_region` (default "us-east-1"), `project_name` (default "production-rag")
- [ ] 8. Create `infra/environments/dev/locals.tf` — `data "aws_caller_identity" "current" {}`, locals: `account_id`, `common_tags` (Environment, Project, ManagedBy)
- [ ] 9. Create `infra/environments/dev/main.tf`:
  - Provider `aws` with `region = var.aws_region`, `default_tags { tags = local.common_tags }`
  - `module "media_bucket"` → `../../modules/s3`, bucket_name = `"${var.project_name}-media-${local.account_id}"`, enable_eventbridge = true
  - `aws_cloudwatch_log_group.pipeline` → `/aws/stepfunctions/${var.project_name}-pipeline`, retention 14 days
  - `aws_iam_role.step_functions` → trust `states.amazonaws.com`
  - `aws_iam_role_policy.step_functions_logging` → 8 CloudWatch Logs actions on `"*"`
  - `aws_sfn_state_machine.pipeline` → name `${var.project_name}-pipeline`, role, definition (ValidateInput Pass), logging ALL with log group ARN (`:*` suffix)
  - `aws_iam_role.eventbridge` → trust `events.amazonaws.com`
  - `aws_iam_role_policy.eventbridge_sfn` → `states:StartExecution` on state machine ARN
  - `aws_cloudwatch_event_rule.s3_upload` → name `${var.project_name}-s3-upload-trigger`, event_pattern matching source aws.s3, detail-type Object Created, bucket name, key prefix uploads/
  - `aws_cloudwatch_event_target.start_pipeline` → target_id `start-pipeline`, state machine ARN, eventbridge role ARN
- [ ] 10. Create `infra/environments/dev/outputs.tf` — `media_bucket_name` (from module), `state_machine_arn` (from sfn resource)
- [ ] 11. Run `terraform init` in `infra/environments/dev/` with `-backend-config="bucket=production-rag-tf-state-$(aws sts get-caller-identity --query Account --output text)"`
- [ ] 12. Run `terraform plan` to verify
- [ ] 13. Run `terraform apply -auto-approve`
- [ ] 14. Run `bash tests/01-video-upload-and-workflow/verify.sh` to confirm end-to-end

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
