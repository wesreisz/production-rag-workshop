# Embedding Endpoint (Workshop Utility)

**Deliverable:** A public HTTPS endpoint that accepts a text string and returns its 256-dimensional embedding vector from Amazon Bedrock Titan Text Embeddings V2. Workshop participants can `curl` this endpoint to generate embeddings for use in pgvector similarity queries via the RDS Query Editor.

---

## Overview

1. Create a small Lambda handler that takes a JSON body with a `text` field, calls Bedrock, and returns the embedding vector
2. Deploy using the non-VPC `lambda` Terraform module (Bedrock is accessible over the public internet — no VPC needed)
3. Attach a Lambda Function URL with `NONE` auth type for a public HTTPS endpoint
4. Output the URL so participants can immediately `curl` it

---

## Prerequisites

- [ ] Stage 4 Part 2 (002_embedding) is complete and verified
- [ ] Bedrock model access is enabled for `amazon.titan-embed-text-v2:0`

---

## Architecture Context

```
curl POST ──> Lambda Function URL ──> Lambda ──> Bedrock Titan V2
                (public HTTPS)         (no VPC)    (embedding API)
```

This is a workshop utility — not part of the production pipeline. It exists so participants can generate embeddings interactively and paste them into pgvector queries in the RDS Query Editor, bridging the gap between "embeddings are stored" and "here's how similarity search actually works."

---

## API Contract

### Request

```
POST https://<function-url-id>.lambda-url.<region>.on.aws/
Content-Type: application/json

{
  "text": "What did Wes talk about?"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | `string` | Yes | The text to embed. Max ~8,000 tokens for Titan V2. |

### Response (success)

```json
{
  "embedding": [0.0123, -0.0456, ...],
  "dimensions": 256,
  "model": "amazon.titan-embed-text-v2:0"
}
```

### Response (error)

```json
{
  "error": "text field is required"
}
```

Status code `400` for missing/invalid input, `500` for Bedrock failures.

### Example usage

```bash
EMBED_URL="<function URL from terraform output>"

# Generate embedding
curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -d '{"text": "What did Wes talk about?"}' | python3 -m json.tool

# Use in pgvector similarity search (RDS Query Editor):
# 1. Copy the embedding array from the curl response
# 2. Paste into this query:
#
#    SELECT chunk_id, left(text, 80) AS text_preview,
#           1 - (embedding <=> '<paste_embedding_here>'::vector) AS similarity
#    FROM video_chunks
#    ORDER BY embedding <=> '<paste_embedding_here>'::vector
#    LIMIT 5;
```

---

## Resources

### Part A: Lambda Handler

**Directory structure:**

```
modules/embedding-endpoint/
└── src/
    ├── __init__.py
    └── handlers/
        ├── __init__.py
        └── embed_text.py
```

**`embed_text.py` handler logic:**

1. Parse the request body from `event["body"]` (Lambda Function URLs pass the HTTP body as a JSON string in `event["body"]`)
2. Validate `text` field is present and non-empty
3. Call Bedrock Titan V2 with `inputText`, `dimensions` from `EMBEDDING_DIMENSIONS` env var (default `256`), `normalize = true`
4. Return JSON response with `statusCode`, `headers` (including CORS `Access-Control-Allow-Origin: *`), and `body`
5. On validation error, return `statusCode: 400`
6. On Bedrock error, return `statusCode: 500`

**Environment variables:**

| Variable | Value |
|----------|-------|
| `EMBEDDING_DIMENSIONS` | `"256"` |

---

### Part B: Terraform Configuration

**New resources in `infra/environments/dev/main.tf`:**

| Resource | Type | Key Settings |
|----------|------|-------------|
| `module "embed_text_endpoint"` | `lambda` module (non-VPC) | `function_name` = `${var.project_name}-embed-text`, `handler` = `src.handlers.embed_text.handler`, `timeout` = `30`, `source_dir` = embedding-endpoint module path |
| `aws_lambda_function_url.embed_text` | Function URL | `function_name` = module output, `authorization_type` = `NONE` |

**IAM policy for the Lambda:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0"
    }
  ]
}
```

**New output in `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `embed_text_endpoint_url` | `aws_lambda_function_url.embed_text.function_url` | Public URL for generating embeddings |

---

## Implementation Checklist

- [ ] 1. Create `modules/embedding-endpoint/src/__init__.py` (empty)
- [ ] 2. Create `modules/embedding-endpoint/src/handlers/__init__.py` (empty)
- [ ] 3. Create `modules/embedding-endpoint/src/handlers/embed_text.py` with handler that parses body, validates `text`, calls Bedrock, returns embedding JSON with CORS headers
- [ ] 4. Add `module "embed_text_endpoint"` to `infra/environments/dev/main.tf` using the non-VPC `lambda` module with Bedrock IAM permissions
- [ ] 5. Add `aws_lambda_function_url.embed_text` resource with `authorization_type = "NONE"`
- [ ] 6. Add `embed_text_endpoint_url` output to `infra/environments/dev/outputs.tf`
- [ ] 7. Run `terraform apply`
- [ ] 8. Verify: `curl` the endpoint with a sample text and confirm a 256-dimensional embedding is returned

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 2: Get the endpoint URL

```bash
terraform output embed_text_endpoint_url
```

### Step 3: Generate an embedding

```bash
EMBED_URL=$(terraform output -raw embed_text_endpoint_url)

curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -d '{"text": "What did Wes talk about?"}' | python3 -m json.tool
```

Expected: JSON response with `embedding` (array of 256 floats), `dimensions` (256), and `model`.

### Step 4: Use in pgvector similarity search

1. Copy the `embedding` array from the curl response
2. Open the RDS Query Editor, connect to `production-rag-vectordb` / `ragdb`
3. Run:

```sql
SELECT chunk_id, left(text, 80) AS text_preview,
       1 - (embedding <=> '<paste_embedding_here>'::vector) AS similarity
FROM video_chunks
ORDER BY embedding <=> '<paste_embedding_here>'::vector
LIMIT 5;
```

Expected: Results sorted by semantic similarity to "What did Wes talk about?"

### Step 5: Test error handling

```bash
# Missing text field
curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

Expected: `{"error": "text field is required"}` with status 400.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Lambda deployed | `aws lambda get-function --function-name production-rag-embed-text` succeeds |
| Lambda is NOT VPC-attached | Function configuration shows no `VpcConfig` subnets |
| Function URL exists | `aws lambda get-function-url-config --function-name production-rag-embed-text` returns a URL |
| Auth type is NONE | Function URL config shows `AuthType: NONE` |
| Endpoint returns embedding | `curl` with `{"text": "hello"}` returns 256-dimensional vector |
| CORS headers present | Response includes `Access-Control-Allow-Origin: *` |
| Missing text returns 400 | `curl` with `{}` returns status 400 and error message |
| Embedding matches Bedrock output | Dimensions match `EMBEDDING_DIMENSIONS` env var (256) |
| Terraform output exists | `terraform output embed_text_endpoint_url` returns the function URL |
