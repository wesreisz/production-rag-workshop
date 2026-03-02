# Video Upload & Workflow Trigger

**Deliverable:** Uploading a file to `s3://<bucket>/uploads/` triggers a Step Functions state machine execution. There are two sample files in the samples folder.

---

## Overview

1. Bootstrap Terraform remote state
2. Create an S3 bucket for video/media uploads
3. Wire an EventBridge rule that detects new objects in the `uploads/` prefix
4. Create a skeleton Step Functions state machine as the trigger target
5. Verify end-to-end: upload a file → state machine executes

---

## Prerequisites

- [ ] AWS account active with CLI configured (`aws sts get-caller-identity` succeeds)
- [ ] Terraform >= 1.5 installed (`terraform --version` succeeds)
- [ ] Repository cloned locally
- [ ] Working in `us-east-1` region

---

## Architecture Context

```
Video Upload ──▶ S3 ──▶ EventBridge ──▶ Step Functions (skeleton)
                                              │
                                              ├── Transcribe (future)
                                              ├── Chunk (future)
                                              ├── Embed (future)
                                              └── Done
```

---

## S3 → EventBridge Event Format

When a file is uploaded to S3 with EventBridge notifications enabled, S3 emits this event:

```json
{
  "version": "0",
  "id": "example-event-id",
  "detail-type": "Object Created",
  "source": "aws.s3",
  "account": "123456789012",
  "time": "2026-02-27T09:45:00Z",
  "region": "us-east-1",
  "resources": ["arn:aws:s3:::production-rag-media-123456789012"],
  "detail": {
    "version": "0",
    "bucket": {
      "name": "production-rag-media-123456789012"
    },
    "object": {
      "key": "uploads/sample.mp4",
      "size": 15728640,
      "etag": "abcdef1234567890",
      "sequencer": "0A1B2C3D4E5F6G7H"
    },
    "request-id": "C3D13FE58DE4C810",
    "requester": "123456789012",
    "source-ip-address": "203.0.113.1",
    "reason": "PutObject"
  }
}
```

Step Functions receives this full event as execution input. Downstream Lambda states extract `detail.bucket.name` and `detail.object.key`.

---

## EventBridge Rule Pattern

Match only `Object Created` events for the `uploads/` prefix in the media bucket:

```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": {
    "bucket": {
      "name": ["production-rag-media-ACCOUNT_ID"]
    },
    "object": {
      "key": [{
        "prefix": "uploads/"
      }]
    }
  }
}
```

---

## Resources

### Part A: Terraform Bootstrap (one-time setup)

Creates the remote state backend. Run once, never destroy.

| Resource | Type | Purpose |
|----------|------|---------|
| S3 bucket | `aws_s3_bucket` | Terraform state storage |
| S3 versioning | `aws_s3_bucket_versioning` | State file version history |
| S3 encryption | `aws_s3_bucket_server_side_encryption_configuration` | Encrypt state at rest |
| S3 public access block | `aws_s3_bucket_public_access_block` | Prevent public access |
| DynamoDB table | `aws_dynamodb_table` | State locking |

**Naming:**
- State bucket: `production-rag-tf-state-<account-id>`
- Lock table: `production-rag-tf-lock`

**Files to create:**

| File | Content |
|------|---------|
| `infra/bootstrap/main.tf` | Provider, S3 bucket, DynamoDB table |
| `infra/bootstrap/variables.tf` | `aws_region` (default `us-east-1`) |
| `infra/bootstrap/outputs.tf` | Bucket name, DynamoDB table name |

**Commands:**
```
cd infra/bootstrap
terraform init
terraform apply
```

---

### Part B: Dev Environment Configuration

The root module that composes all infrastructure modules.

**Files to create:**

| File | Content |
|------|---------|
| `infra/environments/dev/versions.tf` | Terraform version constraint, AWS provider, S3 backend config |
| `infra/environments/dev/variables.tf` | `environment`, `aws_region`, `project_name` |
| `infra/environments/dev/locals.tf` | Common tags, account ID data source, naming prefix |
| `infra/environments/dev/main.tf` | Module calls (S3, EventBridge, Step Functions) |
| `infra/environments/dev/outputs.tf` | Media bucket name, Step Functions ARN |

**Backend configuration** must reference the bootstrap bucket:
- Bucket: `production-rag-tf-state-<account-id>`
- Key: `dev/terraform.tfstate`
- DynamoDB table: `production-rag-tf-lock`
- Region: `us-east-1`

**Variables:**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `environment` | `string` | `"dev"` | Deployment environment |
| `aws_region` | `string` | `"us-east-1"` | AWS region |
| `project_name` | `string` | `"production-rag"` | Project name prefix |

**Locals:**
- `account_id` from `data.aws_caller_identity.current`
- `common_tags` with Environment, Project, ManagedBy

---

### Part C: S3 Module

Reusable Terraform module for S3 buckets with EventBridge notification support.

**Files to create:**

| File | Content |
|------|---------|
| `infra/modules/s3/main.tf` | S3 bucket, versioning, encryption, public access block, EventBridge notification config |
| `infra/modules/s3/variables.tf` | Bucket name, enable_eventbridge flag, tags |
| `infra/modules/s3/outputs.tf` | Bucket name, bucket ARN |

**Resources in this module:**

| Resource | Type | Purpose |
|----------|------|---------|
| S3 bucket | `aws_s3_bucket` | Media storage |
| Versioning | `aws_s3_bucket_versioning` | Object version history |
| Server-side encryption | `aws_s3_bucket_server_side_encryption_configuration` | AES-256 encryption |
| Public access block | `aws_s3_bucket_public_access_block` | Block all public access |
| EventBridge notification | `aws_s3_bucket_notification` | Enable S3 → EventBridge events |

**Module interface:**

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `bucket_name` | `string` | yes | Full bucket name |
| `enable_eventbridge` | `bool` | no (default `true`) | Enable EventBridge notifications |
| `tags` | `map(string)` | no (default `{}`) | Resource tags |

| Output | Description |
|--------|-------------|
| `bucket_name` | The bucket name |
| `bucket_arn` | The bucket ARN |
| `bucket_id` | The bucket ID |

**Media bucket naming:** `production-rag-media-<account-id>`

**Bucket prefixes** (convention, not enforced by Terraform):

| Prefix | Purpose |
|--------|---------|
| `uploads/` | Raw video/audio files |
| `transcripts/` | Raw transcript JSON from AWS Transcribe |
| `chunks/` | Chunked transcript segments |

---

### Part D: Step Functions Skeleton

A minimal state machine that accepts the S3 event and succeeds. Extended with Transcribe, Chunk, and Embed states in subsequent specs.

**Resources (defined directly in dev/main.tf for now):**

| Resource | Type | Purpose |
|----------|------|---------|
| State machine | `aws_sfn_state_machine` | Pipeline orchestration |
| IAM role | `aws_iam_role` | Execution role for Step Functions |
| IAM policy | `aws_iam_role_policy` | CloudWatch Logs permissions |
| Log group | `aws_cloudwatch_log_group` | Step Functions execution logs |

**State machine definition:**

```
StartAt: ValidateInput
States:
  ValidateInput:
    Type: Pass
    End: true
```

**State machine naming:** `production-rag-pipeline`

**Logging:** Enable ALL level logging to CloudWatch. Log group: `/aws/stepfunctions/production-rag-pipeline`

**IAM role trust policy:** Allow `states.amazonaws.com` to assume the role.

**IAM permissions (for now):**
- `logs:CreateLogDelivery`, `logs:GetLogDelivery`, `logs:UpdateLogDelivery`, `logs:DeleteLogDelivery`, `logs:ListLogDeliveries`, `logs:PutResourcePolicy`, `logs:DescribeResourcePolicies`, `logs:DescribeLogGroups` on `*` (required by Step Functions logging)

---

### Part E: EventBridge Rule

Connects S3 upload events to the Step Functions state machine.

**Resources (defined directly in dev/main.tf):**

| Resource | Type | Purpose |
|----------|------|---------|
| EventBridge rule | `aws_cloudwatch_event_rule` | Match S3 Object Created events on uploads/ prefix |
| EventBridge target | `aws_cloudwatch_event_target` | Route matched events to Step Functions |
| IAM role | `aws_iam_role` | Permission for EventBridge to start Step Functions executions |
| IAM policy | `aws_iam_role_policy` | `states:StartExecution` on the state machine ARN |

**Rule naming:** `production-rag-s3-upload-trigger`

**Event pattern:** Match `source: aws.s3`, `detail-type: Object Created`, bucket name, and key prefix `uploads/`.

**Target configuration:**
- Target ID: `start-pipeline`
- ARN: Step Functions state machine ARN
- Role ARN: EventBridge execution role ARN

---

## Implementation Checklist

- [ ] 1. Create `infra/bootstrap/main.tf` with S3 state bucket + DynamoDB lock table
- [ ] 2. Create `infra/bootstrap/variables.tf` and `infra/bootstrap/outputs.tf`
- [ ] 3. Run `terraform init && terraform apply` in `infra/bootstrap/`
- [ ] 4. Create `infra/environments/dev/versions.tf` with provider and S3 backend
- [ ] 5. Create `infra/environments/dev/variables.tf` with environment, region, project_name
- [ ] 6. Create `infra/environments/dev/locals.tf` with common_tags and account_id
- [ ] 7. Create `infra/modules/s3/main.tf` with bucket, versioning, encryption, public access block, EventBridge notification
- [ ] 8. Create `infra/modules/s3/variables.tf` and `infra/modules/s3/outputs.tf`
- [ ] 9. Create `infra/environments/dev/main.tf` calling the S3 module for the media bucket
- [ ] 10. Add Step Functions skeleton state machine to `infra/environments/dev/main.tf` (IAM role, log group, state machine)
- [ ] 11. Add EventBridge rule and target to `infra/environments/dev/main.tf` (rule, target, IAM role)
- [ ] 12. Create `infra/environments/dev/outputs.tf` exposing media bucket name, state machine ARN
- [ ] 13. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 14. Verify: upload a test file and confirm Step Functions execution starts

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform init
terraform plan
terraform apply
```

### Step 2: Upload a test file

```bash
aws s3 cp ../../../samples/sample.mp3 s3://$(terraform output -raw media_bucket_name)/uploads/sample.mp3
```

If no sample file exists yet, any small file works:

```bash
echo "test" > /tmp/test-upload.txt
aws s3 cp /tmp/test-upload.txt s3://$(terraform output -raw media_bucket_name)/uploads/test-upload.txt
```

### Step 3: Confirm Step Functions execution

```bash
aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw state_machine_arn) \
  --max-results 1
```

Expected: An execution in `SUCCEEDED` status.

### Step 4: Inspect the execution input

```bash
EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw state_machine_arn) \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

aws stepfunctions describe-execution \
  --execution-arn $EXECUTION_ARN \
  --query 'input' \
  --output text | python3 -m json.tool
```

Expected: The full S3 EventBridge event JSON showing `detail.bucket.name` and `detail.object.key`.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Terraform state is remote | `infra/bootstrap/` applied; `.terraform/` in dev uses S3 backend |
| S3 media bucket exists | `aws s3 ls` shows `production-rag-media-<account-id>` |
| EventBridge notifications enabled on bucket | AWS Console → S3 → bucket → Properties → Amazon EventBridge → "On" |
| EventBridge rule exists | `aws events list-rules` shows `production-rag-s3-upload-trigger` |
| Step Functions state machine exists | `aws stepfunctions list-state-machines` shows `production-rag-pipeline` |
| Upload triggers execution | Upload to `uploads/` prefix → new execution appears in Step Functions |
| Non-upload prefix is ignored | Upload to root or another prefix → no new execution |
| Execution input contains S3 event | Describe execution → input has `detail.bucket.name` and `detail.object.key` |
