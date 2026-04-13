# Embedding Endpoint — Implementation Plan

**Goal:** Create the `embedding-endpoint` Lambda module with a flat handler and deploy it via Terraform with a public Function URL, API key auth, and CORS — so workshop participants can `curl` to generate embeddings for pgvector queries.

---

## New Files (3)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/embedding-endpoint/src/__init__.py` | Empty package marker |
| 2 | `modules/embedding-endpoint/src/handlers/__init__.py` | Empty package marker |
| 3 | `modules/embedding-endpoint/src/handlers/embed_text.py` | Flat Lambda handler: validate API key, parse body, call Bedrock, return embedding JSON with CORS headers |

## Files to Modify (3)

| # | File | Change |
|---|------|--------|
| 1 | `infra/environments/dev/versions.tf` | Add `hashicorp/random` provider to `required_providers` |
| 2 | `infra/environments/dev/main.tf` | Add `random_password.embed_text_api_key`, `module "embed_text_endpoint"`, `aws_lambda_function_url.embed_text`, two `aws_lambda_permission` resources |
| 3 | `infra/environments/dev/outputs.tf` | Add `embed_text_endpoint_url` and `embed_text_api_key` outputs |

## Bugfix (1)

| # | File | Change |
|---|------|--------|
| 1 | `modules/embedding-module/src/__init__.py` | Replace `git ` with empty content |

---

## Architecture Decisions

1. **Flat handler, no service class.** Per user decision. The handler reads `API_KEY` env var, validates `x-api-key` header, parses body, calls Bedrock directly, returns response. Simple enough for one file.

2. **Non-VPC `lambda` module.** Bedrock is accessible over public internet — no VPC, no psycopg2, no Secrets Manager needed. Uses existing `infra/modules/lambda` module.

3. **`random_password` for API key.** 32 characters, `special = false`. Requires `hashicorp/random` provider added to `versions.tf`.

4. **Two `aws_lambda_permission` resources.** Since October 2025, Function URLs require both `lambda:InvokeFunctionUrl` AND `lambda:InvokeFunction` permissions — without both, the URL returns 403.

5. **Auth at application level.** The Function URL has `authorization_type = "NONE"` (publicly accessible). The handler itself validates the `x-api-key` header against the `API_KEY` env var — this is the spec's design for workshop simplicity.

---

## Detailed Per-File Descriptions

### `modules/embedding-endpoint/src/handlers/embed_text.py`

- Import: `json`, `os`, `boto3`
- Module-level: create `bedrock_client = boto3.client("bedrock-runtime")`, read `API_KEY = os.environ["API_KEY"]`, read `DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))`
- `handler(event, context)`:
  - Read `event["headers"]`, get `x-api-key` header (lowercase — Lambda Function URLs lowercase all headers)
  - If missing or doesn't match `API_KEY` → return `statusCode: 401`, body `{"error": "unauthorized"}`, CORS headers
  - Parse `json.loads(event["body"])` — if fails or `text` field missing/empty → return `statusCode: 400`, body `{"error": "text field is required"}`, CORS headers
  - Call `bedrock_client.invoke_model(modelId="amazon.titan-embed-text-v2:0", contentType="application/json", accept="application/json", body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}))`
  - Parse response, extract `embedding`
  - Return `statusCode: 200`, CORS headers, body `{"embedding": [...], "dimensions": DIMENSIONS, "model": "amazon.titan-embed-text-v2:0"}`
  - On Bedrock error → `statusCode: 500`, body `{"error": "internal error"}`, CORS headers
- CORS headers dict: `{"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}`

### `infra/environments/dev/versions.tf`

- Add `random` provider block inside `required_providers`: `random = { source = "hashicorp/random", version = "~> 3.0" }`

### `infra/environments/dev/main.tf`

Append after `aws_lambda_event_source_mapping.embedding`, before `null_resource.run_migrations`:

- `random_password.embed_text_api_key`: `length = 32`, `special = false`
- `module "embed_text_endpoint"` using `../../modules/lambda`: `function_name = "${var.project_name}-embed-text"`, `handler = "src.handlers.embed_text.handler"`, `source_dir = "${path.module}/../../../modules/embedding-endpoint"`, `timeout = 30`, env vars `API_KEY = random_password.embed_text_api_key.result`, `EMBEDDING_DIMENSIONS = "256"`, IAM policy with single statement: `bedrock:InvokeModel` on `arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0`
- `aws_lambda_function_url.embed_text`: `function_name = module.embed_text_endpoint.function_name`, `authorization_type = "NONE"`
- `aws_lambda_permission.embed_text_public_url`: `statement_id = "FunctionURLAllowPublicAccess"`, `action = "lambda:InvokeFunctionUrl"`, `function_name = module.embed_text_endpoint.function_name`, `principal = "*"`, `function_url_auth_type = "NONE"`
- `aws_lambda_permission.embed_text_public_invoke`: `statement_id = "FunctionURLInvokeAllowPublicAccess"`, `action = "lambda:InvokeFunction"`, `function_name = module.embed_text_endpoint.function_name`, `principal = "*"`

### `infra/environments/dev/outputs.tf`

- `embed_text_endpoint_url`: value `aws_lambda_function_url.embed_text.function_url`
- `embed_text_api_key`: value `random_password.embed_text_api_key.result`, `sensitive = true`

---

## Risks / Assumptions

1. **`terraform init` required.** Adding the `random` provider requires a `terraform init -upgrade` before `terraform apply`. This is an AWS deployment step, not part of code implementation.

2. **Lambda Function URL header casing.** Function URLs lowercase all HTTP headers. The handler must read `x-api-key` (lowercase), not `X-Api-Key`. Verified via AWS documentation.

3. **No tests specified.** The spec's directory structure shows no `tests/` directory for the endpoint module. The `verify-2.sh` script already has curl-based integration tests covering 200, 401, and 400 cases. No unit tests to write.

4. **No `requirements.txt` needed.** The handler only uses `boto3` (available in Lambda runtime) and stdlib. No pip dependencies to install.

---

## Implementation Checklist

- [ ] 1. Create `modules/embedding-endpoint/src/__init__.py` — empty file
- [ ] 2. Create `modules/embedding-endpoint/src/handlers/__init__.py` — empty file
- [ ] 3. Create `modules/embedding-endpoint/src/handlers/embed_text.py` — flat handler with API key validation, body parsing, Bedrock call, CORS response
- [ ] 4. Fix `modules/embedding-module/src/__init__.py` — replace `git ` with empty content
- [ ] 5. Add `hashicorp/random` provider to `infra/environments/dev/versions.tf`
- [ ] 6. Add `random_password.embed_text_api_key` to `infra/environments/dev/main.tf`
- [ ] 7. Add `module "embed_text_endpoint"` (non-VPC lambda) to `infra/environments/dev/main.tf`
- [ ] 8. Add `aws_lambda_function_url.embed_text` to `infra/environments/dev/main.tf`
- [ ] 9. Add `aws_lambda_permission.embed_text_public_url` to `infra/environments/dev/main.tf`
- [ ] 10. Add `aws_lambda_permission.embed_text_public_invoke` to `infra/environments/dev/main.tf`
- [ ] 11. Add `embed_text_endpoint_url` and `embed_text_api_key` outputs to `infra/environments/dev/outputs.tf`

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
