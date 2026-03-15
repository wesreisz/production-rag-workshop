# Question & Retrieval Endpoint

**Deliverable:** An API Gateway REST API backed by a VPC-attached Lambda function that accepts natural language questions at `POST /ask` (cross-video) and `POST /videos/{video_id}/ask` (single-video), embeds them via Bedrock Titan V2, queries Aurora pgvector for cosine similarity, and returns ranked transcript chunks. Additional endpoints `GET /health` and `GET /videos` provide health checks and video listing.

---

## Overview

1. Create the API Gateway Terraform module (`infra/modules/api-gateway/`)
2. Create the question-endpoint Lambda module (Python): one HTTP handler + retrieval service
3. Write unit tests for the retrieval service
4. Deploy the question Lambda using the `lambda-vpc` Terraform module
5. Wire API Gateway to the Lambda in the dev environment Terraform
6. Verify end-to-end: `POST /ask` and `POST /videos/{video_id}/ask` return relevant chunks from pgvector

---

## Prerequisites

- [ ] Stage 4 (Embedding & Vector Storage) is complete and verified
- [ ] Aurora Serverless v2 is running with pgvector extension and `video_chunks` table populated with embeddings
- [ ] VPC endpoints for S3, Bedrock Runtime, and Secrets Manager are available
- [ ] psycopg2 Lambda layer is deployed
- [ ] Bedrock model access is enabled for `amazon.titan-embed-text-v2:0`

---

## Architecture Context

```
Client (curl / MCP Server)
    │
    ▼
API Gateway REST API                                          <<< THIS STAGE
    │
    ├── POST /ask ─────────────────────────────┐
    ├── POST /videos/{video_id}/ask ───────────┤
    ├── GET  /health ──────────────────────────┤
    └── GET  /videos ──────────────────────────┤
                                               │
                                               ▼
                                   Question Lambda (VPC-attached)  <<< THIS STAGE
                                               │
                                   ┌───────────┴───────────┐
                                   │                       │
                                   ▼                       ▼
                           Bedrock Titan V2          Aurora pgvector
                           (embed question)        (similarity search)
                           via VPC Endpoint         via direct VPC access
```

The question Lambda handles all four routes in a single function. It runs inside the VPC to access Aurora directly. It reaches Bedrock and Secrets Manager through VPC endpoints deployed in Stage 4.

---

## API Contract

### POST /ask

**Request:**

```json
{
  "question": "What did the speaker say about error handling?",
  "top_k": 5,
  "similarity_threshold": 0.5,
  "filters": {
    "speaker": "Jane Doe"
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `question` | `string` | Yes | — | Natural language question (non-empty) |
| `top_k` | `integer` | No | `5` | Number of results to return (1–100) |
| `similarity_threshold` | `float` | No | `0.0` | Minimum similarity score (0.0–1.0). Only chunks scoring above this threshold are returned |
| `filters.speaker` | `string` | No | `null` | Filter results to a specific speaker |

**Response (200):**

```json
{
  "question": "What did the speaker say about error handling?",
  "results": [
    {
      "chunk_id": "hello-my_name_is_wes-chunk-003",
      "video_id": "hello-my_name_is_wes",
      "text": "Error handling in production RAG systems requires...",
      "similarity": 0.89,
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
      "start_time": 234.5,
      "end_time": 279.8,
      "source_s3_key": "uploads/hello-my_name_is_wes.mp3"
    }
  ]
}
```

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Missing or empty `question` | `{"error": "question is required"}` |
| 400 | `top_k` out of range | `{"error": "top_k must be between 1 and 100"}` |
| 400 | `similarity_threshold` out of range | `{"error": "similarity_threshold must be between 0.0 and 1.0"}` |
| 500 | Internal error | `{"error": "internal error"}` |

### POST /videos/{video_id}/ask

Scoped version of `POST /ask` — searches only within chunks belonging to the specified video.

**Request:**

```json
{
  "question": "What did the speaker say about error handling?",
  "top_k": 5,
  "similarity_threshold": 0.5
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `video_id` | `string` | Yes (path) | — | Video identifier from the URL path |
| `question` | `string` | Yes | — | Natural language question (non-empty) |
| `top_k` | `integer` | No | `5` | Number of results to return (1–100) |
| `similarity_threshold` | `float` | No | `0.0` | Minimum similarity score (0.0–1.0) |

Note: `filters.speaker` is not included — the query is already scoped to a single video. If the `video_id` does not exist in the database, the response is a 200 with an empty `results` array (not a 404).

**Response (200):**

```json
{
  "video_id": "hello-my_name_is_wes",
  "question": "What did the speaker say about error handling?",
  "results": [
    {
      "chunk_id": "hello-my_name_is_wes-chunk-003",
      "video_id": "hello-my_name_is_wes",
      "text": "Error handling in production RAG systems requires...",
      "similarity": 0.89,
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
      "start_time": 234.5,
      "end_time": 279.8,
      "source_s3_key": "uploads/hello-my_name_is_wes.mp3"
    }
  ]
}
```

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Missing or empty `question` | `{"error": "question is required"}` |
| 400 | `top_k` out of range | `{"error": "top_k must be between 1 and 100"}` |
| 400 | `similarity_threshold` out of range | `{"error": "similarity_threshold must be between 0.0 and 1.0"}` |
| 500 | Internal error | `{"error": "internal error"}` |

---

### GET /health

**Response (200):**

```json
{
  "status": "healthy"
}
```

### GET /videos

**Response (200):**

```json
{
  "videos": [
    {
      "video_id": "hello-my_name_is_wes",
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
      "chunk_count": 3
    }
  ]
}
```

---

## Similarity Search SQL

```sql
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

With speaker filter:

```sql
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
WHERE speaker = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

The `<=>` operator computes cosine distance. `1 - distance = similarity` (1.0 = identical, 0.0 = orthogonal).

Parameters without filter: `(embedding_str, embedding_str, top_k)`
Parameters with filter: `(embedding_str, speaker, embedding_str, top_k)`

With video_id filter (for `POST /videos/{video_id}/ask`):

```sql
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
WHERE video_id = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

Parameters: `(embedding_str, video_id, embedding_str, top_k)`

The service method builds the appropriate query based on which filters are provided.

---

## Videos Aggregate SQL

No separate `videos` table is needed. The video listing is derived from the `video_chunks` table:

```sql
SELECT video_id, speaker, title, COUNT(*) AS chunk_count
FROM video_chunks
GROUP BY video_id, speaker, title
ORDER BY video_id;
```

---

## API Gateway Event Format (Lambda Input)

API Gateway delivers proxy integration events to the Lambda:

```json
{
  "resource": "/ask",
  "path": "/ask",
  "httpMethod": "POST",
  "headers": {
    "Content-Type": "application/json"
  },
  "queryStringParameters": null,
  "body": "{\"question\": \"What is RAG?\", \"top_k\": 5}",
  "isBase64Encoded": false
}
```

For GET endpoints:

```json
{
  "resource": "/health",
  "path": "/health",
  "httpMethod": "GET",
  "headers": {},
  "queryStringParameters": null,
  "body": null,
  "isBase64Encoded": false
}
```

For path-parameterized endpoints (`/videos/{video_id}/ask`):

```json
{
  "resource": "/videos/{video_id}/ask",
  "path": "/videos/hello-my_name_is_wes/ask",
  "httpMethod": "POST",
  "headers": {
    "Content-Type": "application/json"
  },
  "pathParameters": {
    "video_id": "hello-my_name_is_wes"
  },
  "queryStringParameters": null,
  "body": "{\"question\": \"What is this about?\", \"top_k\": 5}",
  "isBase64Encoded": false
}
```

The handler routes based on the `resource` field (which contains the template `/videos/{video_id}/ask`, not the resolved path). The actual video ID is in `event["pathParameters"]["video_id"]`.

---

## Resources

### Part A: API Gateway Terraform Module

Create a reusable Terraform module for an API Gateway REST API with Lambda proxy integration.

**Directory structure:**

```
infra/modules/api-gateway/
├── main.tf
├── variables.tf
└── outputs.tf
```

**Files to create:**

| File | Purpose |
|------|---------|
| `infra/modules/api-gateway/main.tf` | REST API, resources, methods, integrations, deployment, stage, Lambda permission |
| `infra/modules/api-gateway/variables.tf` | Module input variables |
| `infra/modules/api-gateway/outputs.tf` | Module outputs |

---

#### main.tf

**REST API:**

| Resource | Type | Key Settings |
|----------|------|--------------|
| `aws_api_gateway_rest_api.this` | REST API | `name` = `var.api_name` |

**Resources and Methods:**

| Resource | Path | Method | Integration |
|----------|------|--------|-------------|
| `aws_api_gateway_resource.ask` | `/ask` | POST | Lambda proxy (`AWS_PROXY`) |
| `aws_api_gateway_resource.videos` | `/videos` | GET | Lambda proxy (`AWS_PROXY`) |
| `aws_api_gateway_resource.video_id` | `/videos/{video_id}` | — | Parent resource (no method) |
| `aws_api_gateway_resource.video_ask` | `/videos/{video_id}/ask` | POST | Lambda proxy (`AWS_PROXY`) |
| `aws_api_gateway_resource.health` | `/health` | GET | Lambda proxy (`AWS_PROXY`) |

The `/videos/{video_id}` resource uses `path_part = "{video_id}"` and is a child of `aws_api_gateway_resource.videos`. The `/videos/{video_id}/ask` resource uses `path_part = "ask"` and is a child of `aws_api_gateway_resource.video_id`. API Gateway passes the `video_id` path parameter to Lambda in `event["pathParameters"]["video_id"]`.

All methods use `authorization = "NONE"`, `api_key_required = true`, and Lambda proxy integration (`type = "AWS_PROXY"`). The `integration_http_method` is always `"POST"` (Lambda invocations are always POST regardless of the client's HTTP method).

Setting `api_key_required = true` means API Gateway rejects requests that don't include a valid `x-api-key` header before the Lambda is ever invoked. This protects the endpoint from unauthorized access and prevents Lambda costs from bad actors.

**API Key and Usage Plan:**

| Resource | Type | Key Settings |
|----------|------|--------------|
| `aws_api_gateway_api_key.this` | API Key | `name` = `"${var.api_name}-key"`, `enabled` = `true` |
| `aws_api_gateway_usage_plan.this` | Usage Plan | `name` = `"${var.api_name}-usage-plan"`, `api_stages` = `[{api_id, stage}]`, `throttle_settings` = `{rate_limit = 50, burst_limit = 100}`, `quota_settings` = `{limit = 10000, period = "DAY"}` |
| `aws_api_gateway_usage_plan_key.this` | Plan ↔ Key link | `key_id` = API key ID, `key_type` = `"API_KEY"`, `usage_plan_id` = usage plan ID |

Throttle and quota settings:

| Setting | Value | Description |
|---------|-------|-------------|
| `rate_limit` | `50` | Steady-state requests per second |
| `burst_limit` | `100` | Maximum concurrent requests (token bucket burst) |
| `quota limit` | `10000` | Maximum requests per day |
| `quota period` | `DAY` | Quota resets daily |

These limits are generous for workshop use but prevent abuse. API Gateway returns `429 Too Many Requests` when limits are exceeded.

**Deployment and Stage:**

| Resource | Type | Key Settings |
|----------|------|--------------|
| `aws_api_gateway_deployment.this` | Deployment | `depends_on` all integrations (ask, video_ask, health, videos); `triggers` based on resource/method/integration hashes; `lifecycle { create_before_destroy = true }` |
| `aws_api_gateway_stage.this` | Stage | `stage_name` = `var.stage_name` (default `"prod"`) |

**Lambda Permission:**

| Resource | Type | Key Settings |
|----------|------|--------------|
| `aws_lambda_permission.api_gateway` | Permission | `principal` = `"apigateway.amazonaws.com"`, `source_arn` = `"${rest_api.execution_arn}/*/*"` |

---

#### variables.tf

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `api_name` | `string` | — | REST API name |
| `lambda_invoke_arn` | `string` | — | Lambda function invoke ARN |
| `lambda_function_name` | `string` | — | Lambda function name (for permission resource) |
| `stage_name` | `string` | `"prod"` | API Gateway stage name |
| `tags` | `map(string)` | `{}` | Resource tags |

---

#### outputs.tf

| Output | Value | Description |
|--------|-------|-------------|
| `api_url` | `aws_api_gateway_stage.this.invoke_url` | Base URL (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/prod`) |
| `rest_api_id` | `aws_api_gateway_rest_api.this.id` | REST API ID |
| `api_key_value` | `aws_api_gateway_api_key.this.value` | API key value (sensitive — used in `x-api-key` header) |

---

### Part B: Question Endpoint Module (Python)

Application code for the question Lambda function. Same thin-handler-thick-service pattern as the embedding module.

**Directory structure:**

```
modules/question-endpoint/
├── src/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── question.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── retrieval_service.py
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── unit/
│       ├── __init__.py
│       └── test_retrieval_service.py
├── requirements.txt
└── dev-requirements.txt
```

**Files to create:**

| File | Purpose |
|------|---------|
| `modules/question-endpoint/src/handlers/question.py` | Lambda entry point: route by resource, call service, return HTTP response |
| `modules/question-endpoint/src/services/retrieval_service.py` | Business logic: embed question, search pgvector, list videos |
| `modules/question-endpoint/src/utils/logger.py` | Shared logger utility — same as other modules |
| `modules/question-endpoint/requirements.txt` | Runtime dependencies |
| `modules/question-endpoint/dev-requirements.txt` | Test dependencies |
| All `__init__.py` files | Python package markers (empty files) |

---

#### question handler

**Input:** API Gateway proxy integration event

**Output:** HTTP response `{statusCode, headers, body}`

**Handler responsibilities:**

1. Read `resource` from the event
2. Route:
   - `GET /health` → return `{"status": "healthy"}`
   - `GET /videos` → call `RetrievalService.list_videos()`, return results
   - `POST /ask` → parse body, validate, call service methods, return results
   - `POST /videos/{video_id}/ask` → parse body, extract `video_id` from `event["pathParameters"]["video_id"]`, validate, call service with `video_id` filter, return results
   - Any other route → return 404
3. For `POST /ask`:
   a. Parse `json.loads(event["body"])`
   b. Validate: `question` is non-empty string, `top_k` is 1–100, `similarity_threshold` is 0.0–1.0
   c. Extract optional `filters.speaker`
   d. Call `RetrievalService.generate_embedding(question)` to get 256-dim vector
   e. Call `RetrievalService.search_similar(embedding, top_k, similarity_threshold, speaker)` to query pgvector
   f. Return results with similarity scores
4. Wrap all responses with CORS headers

**Error handling:**

- Missing/empty `question` → 400 with `{"error": "question is required"}`
- `top_k` out of range → 400 with `{"error": "top_k must be between 1 and 100"}`
- `similarity_threshold` out of range → 400 with `{"error": "similarity_threshold must be between 0.0 and 1.0"}`
- Any unhandled exception → 500 with `{"error": "internal error"}`

**Response helper** (same pattern as `embedding-endpoint`):

```python
def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
```

**Environment variables used:**

| Variable | Description |
|----------|-------------|
| `SECRET_ARN` | Secrets Manager secret ARN for database credentials |
| `DB_NAME` | Database name (e.g. `ragdb`) |
| `EMBEDDING_DIMENSIONS` | Vector dimensions (e.g. `256`) |

---

#### RetrievalService

Business logic layer. Same pattern as `EmbeddingService`: class with boto3 clients in `__init__`, instantiated once at module level for warm-invocation reuse.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `get_db_connection()` | — | `psycopg2.connection` | Read credentials from Secrets Manager, connect to Aurora. Cache connection for warm invocations. |
| `generate_embedding(text)` | question text string | `list[float]` | Call Bedrock Titan V2 InvokeModel, return 256-dim embedding vector |
| `search_similar(embedding, top_k, similarity_threshold=0.0, speaker=None, video_id=None)` | embedding list, top_k int, threshold float, optional speaker string, optional video_id string | `list[dict]` | Query pgvector with cosine similarity, return ranked chunks above threshold. When `video_id` is provided, results are scoped to that video only. |
| `list_videos()` | — | `list[dict]` | Aggregate query on `video_chunks` for video listing |

**Constructor (`__init__`):**

- `self._bedrock = boto3.client("bedrock-runtime")`
- `self._secretsmanager = boto3.client("secretsmanager")`
- `self._db_conn = None` (lazy connection, cached across warm invocations)
- `self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))`
- `self._secret_arn = os.environ["SECRET_ARN"]`
- `self._db_name = os.environ["DB_NAME"]`

Note: No S3 client needed — the question endpoint reads from pgvector, not S3.

**`get_db_connection` details:**

Same as `EmbeddingService.get_db_connection()`:

1. If `self._db_conn` is not `None` and connection is not closed, return it
2. Call `self._secretsmanager.get_secret_value(SecretId=self._secret_arn)`
3. Parse the JSON secret string to get `host`, `port`, `username`, `password`
4. Connect: `psycopg2.connect(host=host, port=port, dbname=self._db_name, user=username, password=password)`
5. Set `self._db_conn` and return it
6. On connection error, set `self._db_conn = None` and re-raise

**`generate_embedding` details:**

Same as `EmbeddingService.generate_embedding()`:

1. Call `self._bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", contentType="application/json", accept="application/json", body=json.dumps({"inputText": text, "dimensions": self._dimensions, "normalize": True}))`
2. Parse response body JSON
3. Return `result["embedding"]`

**`search_similar` details:**

1. Get connection via `self.get_db_connection()`
2. Create cursor
3. Convert embedding list to string format: `"[0.01, -0.02, ...]"`
4. Build the SQL query dynamically: add `WHERE video_id = %s` if video_id is provided, add `WHERE speaker = %s` if speaker is provided (combine with `AND` if both present)
5. Execute with appropriate parameters
6. Fetch all rows
7. Convert each row to a dict with keys: `chunk_id`, `video_id`, `text`, `similarity`, `speaker`, `title`, `start_time`, `end_time`, `source_s3_key`
8. Filter results: discard any row where `similarity < similarity_threshold`
9. Close cursor (not connection — connection is cached)
10. Return the list of dicts
11. On any exception: reset `self._db_conn = None` (invalidate stale connection so next invocation reconnects), then re-raise

The similarity threshold is applied in Python after the query (post-filter) rather than in SQL. This keeps the SQL simple and avoids a subquery. The `LIMIT` still caps the pgvector scan, and the threshold trims low-relevance results from the response.

If the query fails due to a stale or broken connection, setting `self._db_conn = None` ensures the next Lambda invocation will establish a fresh connection rather than reusing the broken one.

**`list_videos` details:**

1. Get connection via `self.get_db_connection()`
2. Create cursor
3. Execute the aggregate SQL
4. Fetch all rows
5. Convert each row to a dict with keys: `video_id`, `speaker`, `title`, `chunk_count`
6. Close cursor
7. Return the list of dicts
8. On any exception: reset `self._db_conn = None`, then re-raise

---

#### Dependencies

**`requirements.txt`:**

```
boto3
psycopg2-binary
```

Same as the embedding module. `psycopg2-binary` is for local development; the Lambda layer provides the runtime binary.

**`dev-requirements.txt`:**

```
pytest
moto[secretsmanager]
```

---

### Part C: Unit Tests

**File:** `modules/question-endpoint/tests/unit/test_retrieval_service.py`

| Test | Description |
|------|-------------|
| `test_generate_embedding_returns_vector` | Mock Bedrock `invoke_model` response, call `generate_embedding`, verify list of 256 floats |
| `test_generate_embedding_passes_correct_params` | Mock Bedrock, call `generate_embedding`, verify `modelId`, `dimensions`, and `normalize` in request |
| `test_search_similar_returns_ranked_results` | Mock psycopg2 cursor with fake rows, call `search_similar`, verify results are returned as list of dicts |
| `test_search_similar_with_speaker_filter` | Mock cursor, call `search_similar` with speaker, verify SQL includes `WHERE speaker =` |
| `test_search_similar_without_filter` | Mock cursor, call `search_similar` without speaker, verify SQL has no `WHERE` clause |
| `test_search_similar_filters_below_threshold` | Mock cursor with rows at varying similarities, call `search_similar` with `similarity_threshold=0.5`, verify only results with similarity >= 0.5 are returned |
| `test_search_similar_with_video_id_filter` | Mock cursor, call `search_similar` with `video_id`, verify SQL includes `WHERE video_id =` |
| `test_list_videos_returns_aggregated` | Mock cursor with fake rows, call `list_videos`, verify dicts with `video_id`, `speaker`, `title`, `chunk_count` |
| `test_handler_post_ask_returns_results` | Mock service methods, send POST /ask event, verify 200 response with `question` and `results` |
| `test_handler_post_ask_missing_question` | Send POST /ask with empty question, verify 400 with `{"error": "question is required"}` |
| `test_handler_post_video_ask_returns_results` | Mock service methods, send POST /videos/{video_id}/ask event, verify 200 response with `video_id`, `question`, and `results` |
| `test_handler_post_video_ask_passes_video_id` | Mock service, send POST /videos/{video_id}/ask, verify `search_similar` called with `video_id` parameter |
| `test_handler_get_health` | Send GET /health event, verify 200 with `{"status": "healthy"}` |
| `test_handler_get_videos` | Mock service, send GET /videos event, verify 200 with video list |
| `test_handler_unknown_route` | Send event with unknown resource, verify 404 |

**`conftest.py` fixtures:**

| Fixture | Description |
|---------|-------------|
| `aws_credentials` | Set mock AWS env vars + `SECRET_ARN`, `DB_NAME`, `EMBEDDING_DIMENSIONS` |
| `mock_aws_services` | `mock_aws()` context |
| `sample_ask_event` | API Gateway proxy event for `POST /ask` with question and top_k |
| `sample_video_ask_event` | API Gateway proxy event for `POST /videos/{video_id}/ask` with `pathParameters: {"video_id": "hello-my_name_is_wes"}` |
| `sample_health_event` | API Gateway proxy event for `GET /health` |
| `sample_videos_event` | API Gateway proxy event for `GET /videos` |

---

### Part D: Question Lambda Deployment (Terraform)

Add one Lambda module call and one API Gateway module call to `infra/environments/dev/main.tf`.

**Lambda module call** (using `lambda-vpc`):

| Setting | Value |
|---------|-------|
| Module name | `question` |
| Function name | `${var.project_name}-question` |
| Handler | `src.handlers.question.handler` |
| Source dir | `${path.module}/../../../modules/question-endpoint` |
| Runtime | `python3.11` (module default) |
| Timeout | `30` |
| Memory | `256` (module default) |
| Layers | `[aws_lambda_layer_version.psycopg2.arn]` |
| Subnet IDs | `module.networking.subnet_ids` |
| Security group IDs | `[module.networking.lambda_security_group_id]` |

**Environment variables:**

| Variable | Value |
|----------|-------|
| `SECRET_ARN` | `module.aurora_vectordb.secret_arn` |
| `DB_NAME` | `module.aurora_vectordb.db_name` |
| `EMBEDDING_DIMENSIONS` | `"256"` |

**IAM permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    },
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "${module.aurora_vectordb.secret_arn}"
    }
  ]
}
```

**API Gateway module call:**

| Setting | Value |
|---------|-------|
| Module name | `question_api` |
| `api_name` | `${var.project_name}-question-api` |
| `lambda_invoke_arn` | `module.question.invoke_arn` |
| `lambda_function_name` | `module.question.function_name` |
| `stage_name` | `"prod"` |
| `tags` | `local.common_tags` |

---

### Part E: Outputs

**Add to `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `question_api_url` | `module.question_api.api_url` | API Gateway base URL (e.g. `https://abc.execute-api.us-east-1.amazonaws.com/prod`) |
| `question_api_key` | `module.question_api.api_key_value` | API key for `x-api-key` header (sensitive) |
| `question_function_name` | `module.question.function_name` | Question Lambda function name |

---

## Implementation Checklist

- [ ] 1. Create `infra/modules/api-gateway/variables.tf` with `api_name`, `lambda_invoke_arn`, `lambda_function_name`, `stage_name`, `tags`
- [ ] 2. Create `infra/modules/api-gateway/main.tf` with REST API, resources (`/ask`, `/videos`, `/videos/{video_id}`, `/videos/{video_id}/ask`, `/health`), methods (`api_key_required = true`), Lambda proxy integrations, API key, usage plan (rate 50/s, burst 100, daily quota 10000), deployment with triggers, stage, Lambda permission
- [ ] 3. Create `infra/modules/api-gateway/outputs.tf` with `api_url`, `rest_api_id`, `api_key_value`
- [ ] 4. Create `modules/question-endpoint/requirements.txt` with `boto3`, `psycopg2-binary`
- [ ] 5. Create `modules/question-endpoint/dev-requirements.txt` with `pytest`, `moto[secretsmanager]`
- [ ] 6. Create all `__init__.py` files (`src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`)
- [ ] 7. Create `modules/question-endpoint/src/utils/logger.py`
- [ ] 8. Create `modules/question-endpoint/tests/conftest.py` with shared fixtures
- [ ] 9. Create `modules/question-endpoint/tests/unit/test_retrieval_service.py` with unit tests
- [ ] 10. Create `modules/question-endpoint/src/services/retrieval_service.py` with `get_db_connection`, `generate_embedding`, `search_similar`, `list_videos`
- [ ] 11. Create `modules/question-endpoint/src/handlers/question.py` handler with route dispatch, input validation, response formatting
- [ ] 12. Add `module "question"` (lambda-vpc) to `infra/environments/dev/main.tf`
- [ ] 13. Add `module "question_api"` (api-gateway) to `infra/environments/dev/main.tf`
- [ ] 14. Add `question_api_url`, `question_api_key` (sensitive), and `question_function_name` outputs to `infra/environments/dev/outputs.tf`
- [ ] 15. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 16. Verify: `POST /ask` returns relevant chunks
- [ ] 17. Verify: `GET /health` returns healthy
- [ ] 18. Verify: `GET /videos` returns indexed videos

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform init
terraform plan -var="aurora_master_password=YourSecurePassword123!"
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 2: Get the API URL and key

```bash
API_URL=$(terraform output -raw question_api_url)
API_KEY=$(terraform output -raw question_api_key)
echo "API URL: $API_URL"
```

### Step 3: Test health endpoint

```bash
curl -s -H "x-api-key: $API_KEY" "$API_URL/health" | python3 -m json.tool
```

Expected:

```json
{
  "status": "healthy"
}
```

### Step 4: Test videos endpoint

```bash
curl -s -H "x-api-key: $API_KEY" "$API_URL/videos" | python3 -m json.tool
```

Expected: A JSON object with a `videos` array containing entries with `video_id`, `speaker`, `title`, `chunk_count`.

### Step 5: Test ask endpoint

```bash
curl -s -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": "What is this video about?", "top_k": 3}' | python3 -m json.tool
```

Expected: A JSON response with `question` and `results` array containing chunks sorted by similarity.

### Step 6: Test ask with speaker filter

```bash
curl -s -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": "What is this video about?", "top_k": 3, "filters": {"speaker": "Wesley Reisz"}}' | python3 -m json.tool
```

Expected: Results filtered to the specified speaker only.

### Step 7: Test ask scoped to a specific video

```bash
VIDEO_ID="hello-my_name_is_wes"
curl -s -X POST "$API_URL/videos/$VIDEO_ID/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": "What is this video about?", "top_k": 3}' | python3 -m json.tool
```

Expected: Results scoped to the specified video only. Response includes `video_id` field matching the path parameter.

### Step 8: Test request without API key (should be rejected)

```bash
curl -s -o /dev/null -w "%{http_code}" "$API_URL/health"
```

Expected: `403` — API Gateway rejects the request before it reaches the Lambda.

### Step 9: Test validation

```bash
curl -s -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": ""}' | python3 -m json.tool
```

Expected: 400 with `{"error": "question is required"}`.

### Step 10: Run unit tests

```bash
cd modules/question-endpoint
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
python -m pytest tests/ -v
deactivate
```

Expected: All tests pass.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| API Gateway exists | `aws apigateway get-rest-apis` shows `production-rag-question-api` |
| API Gateway has four routes | REST API has resources for `/ask`, `/videos`, `/videos/{video_id}/ask`, `/health` |
| API Gateway stage is `prod` | Stage named `prod` exists with deployment |
| API key exists | `aws apigateway get-api-keys` shows `production-rag-question-api-key` |
| Usage plan has throttling | Usage plan shows `rateLimit: 50`, `burstLimit: 100`, daily quota `10000` |
| Request without API key returns 403 | `curl $API_URL/health` without `x-api-key` header returns 403 |
| Question Lambda deployed | `aws lambda list-functions` shows `production-rag-question` |
| Lambda is VPC-attached | Function configuration shows `VpcConfig` with subnet and security group IDs |
| Lambda has psycopg2 layer | Function configuration shows psycopg2 layer ARN |
| `GET /health` returns 200 | `curl $API_URL/health` returns `{"status": "healthy"}` |
| `GET /videos` returns video list | Response includes videos with `video_id`, `speaker`, `title`, `chunk_count` |
| `POST /ask` returns ranked chunks | Response includes `results` array sorted by `similarity` descending |
| Similarity values are 0–1 | All `similarity` scores are between 0.0 and 1.0 |
| Speaker filter works | Adding `filters.speaker` restricts results to that speaker |
| `POST /videos/{video_id}/ask` returns scoped results | Response only contains chunks from the specified video |
| Empty question returns 400 | Response is `{"error": "question is required"}` |
| Unknown route returns 404 | Requesting a non-existent path returns 404 |
| Unit tests pass | `cd modules/question-endpoint && python -m pytest tests/` passes all tests |
| Terraform plan is clean | `terraform plan` shows no pending changes after apply |
