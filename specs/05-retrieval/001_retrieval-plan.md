# Question & Retrieval Endpoint — Implementation Plan

**Goal:** Create the API Gateway Terraform module, the question-endpoint Lambda module (Python handler + retrieval service + tests), deploy both via Terraform, and wire them together — so that `POST /ask`, `POST /videos/{video_id}/ask`, `GET /health`, and `GET /videos` return relevant transcript chunks from pgvector.

---

## New Files (19)

| # | File | Purpose |
|---|------|---------|
| 1 | `infra/modules/api-gateway/variables.tf` | Input variables: `api_name`, `lambda_invoke_arn`, `lambda_function_name`, `stage_name`, `tags` |
| 2 | `infra/modules/api-gateway/main.tf` | REST API, resources, methods, integrations, API key, usage plan, deployment, stage, Lambda permission |
| 3 | `infra/modules/api-gateway/outputs.tf` | `api_url`, `rest_api_id`, `api_key_value` |
| 4 | `modules/question-endpoint/requirements.txt` | `boto3`, `psycopg2-binary` |
| 5 | `modules/question-endpoint/dev-requirements.txt` | `pytest` |
| 6 | `modules/question-endpoint/src/__init__.py` | Empty package marker |
| 7 | `modules/question-endpoint/src/handlers/__init__.py` | Empty package marker |
| 8 | `modules/question-endpoint/src/services/__init__.py` | Empty package marker |
| 9 | `modules/question-endpoint/src/utils/__init__.py` | Empty package marker |
| 10 | `modules/question-endpoint/tests/__init__.py` | Empty package marker |
| 11 | `modules/question-endpoint/tests/unit/__init__.py` | Empty package marker |
| 12 | `modules/question-endpoint/src/utils/logger.py` | Identical to embedding-module's logger |
| 13 | `modules/question-endpoint/tests/conftest.py` | Shared fixtures: `aws_credentials`, `sample_ask_event`, `sample_video_ask_event`, `sample_health_event`, `sample_videos_event` |
| 14 | `modules/question-endpoint/tests/unit/test_retrieval_service.py` | 14 unit tests |
| 15 | `modules/question-endpoint/src/services/retrieval_service.py` | Business logic: `get_db_connection`, `generate_embedding`, `search_similar`, `list_videos` |
| 16 | `modules/question-endpoint/src/handlers/question.py` | Lambda entry point: route dispatch, input validation, response formatting |

## Files to Modify (2)

| # | File | Change |
|---|------|--------|
| 1 | `infra/environments/dev/main.tf` | Add `module "question"` (lambda-vpc) and `module "question_api"` (api-gateway) |
| 2 | `infra/environments/dev/outputs.tf` | Add `question_api_url`, `question_api_key` (sensitive), `question_function_name` outputs |

---

## Architecture Decisions

**1. Injectable clients (same deviation as embedding module).** The spec shows hardcoded `boto3.client()` calls in `RetrievalService.__init__`. Following the established pattern from `EmbeddingService`, the constructor accepts optional `bedrock_client` and `secretsmanager_client` parameters with `or boto3.client(...)` fallbacks. No `s3_client` needed — the question endpoint reads from pgvector, not S3.

**2. No moto — all MagicMock.** Per the spec, `dev-requirements.txt` contains only `pytest`. All Bedrock and psycopg2 interactions are replaced with `MagicMock` directly in each test. No `mock_aws_services` fixture needed.

**3. Cursor management with `finally` blocks.** Both `search_similar` and `list_videos` use `try/except/finally` to guarantee cursor closure on both success and exception paths. On exception, `self._db_conn = None` invalidates the stale connection before re-raising. The cursor is closed in `finally`, but the connection is cached.

**4. Dynamic SQL building for filters.** `search_similar` builds its SQL query by starting with a base `SELECT ... FROM video_chunks` and appending `WHERE` clauses conditionally: `WHERE video_id = %s` if `video_id` is provided, `WHERE speaker = %s` if `speaker` is provided, combining with `AND` if both present. Parameters are built as a list in the same order as the `%s` placeholders. The `embedding_str` parameter appears twice (once in the `SELECT` for similarity calculation, once in the `ORDER BY`).

**5. Post-filter similarity threshold in Python.** The spec explicitly states the threshold is applied after the SQL query returns results. The `LIMIT` caps the pgvector scan and the threshold trims low-relevance results in Python. This avoids complicating the SQL with subqueries.

**6. Single Lambda for all 4 routes.** The handler routes on `event["resource"]` (the API Gateway template path, not the resolved path). Routes: `/health` → GET, `/videos` → GET, `/ask` → POST, `/videos/{video_id}/ask` → POST. The video_id comes from `event["pathParameters"]["video_id"]`.

**7. API Gateway API key required.** All methods set `api_key_required = true`. Requests without a valid `x-api-key` header get 403 from API Gateway before reaching Lambda.

**8. Handler routing uses both `resource` and `httpMethod`.** The handler checks `event["resource"]` for the route template and `event["httpMethod"]` for the HTTP verb. This matches the API Gateway proxy integration event format.

---

## Detailed Per-File Descriptions

### Part A: API Gateway Terraform Module

**`infra/modules/api-gateway/variables.tf`**

5 variables:
- `api_name` (string, required) — REST API name
- `lambda_invoke_arn` (string, required) — Lambda function invoke ARN
- `lambda_function_name` (string, required) — Lambda function name (for permission resource)
- `stage_name` (string, default `"prod"`) — API Gateway stage name
- `tags` (map(string), default `{}`) — Resource tags

**`infra/modules/api-gateway/main.tf`**

Resources in order:

1. `aws_api_gateway_rest_api.this` — `name = var.api_name`

2. Resources (5):
   - `aws_api_gateway_resource.ask` — `path_part = "ask"`, parent = root
   - `aws_api_gateway_resource.videos` — `path_part = "videos"`, parent = root
   - `aws_api_gateway_resource.video_id` — `path_part = "{video_id}"`, parent = `videos`
   - `aws_api_gateway_resource.video_ask` — `path_part = "ask"`, parent = `video_id`
   - `aws_api_gateway_resource.health` — `path_part = "health"`, parent = root

3. Methods (4) — all with `authorization = "NONE"`, `api_key_required = true`:
   - `aws_api_gateway_method.post_ask` — `POST` on `ask` resource
   - `aws_api_gateway_method.get_videos` — `GET` on `videos` resource
   - `aws_api_gateway_method.post_video_ask` — `POST` on `video_ask` resource
   - `aws_api_gateway_method.get_health` — `GET` on `health` resource

4. Integrations (4) — all `type = "AWS_PROXY"`, `integration_http_method = "POST"`, `uri = var.lambda_invoke_arn`:
   - `aws_api_gateway_integration.ask`
   - `aws_api_gateway_integration.videos`
   - `aws_api_gateway_integration.video_ask`
   - `aws_api_gateway_integration.health`

5. API Key + Usage Plan:
   - `aws_api_gateway_api_key.this` — `name = "${var.api_name}-key"`, `enabled = true`
   - `aws_api_gateway_usage_plan.this` — `name = "${var.api_name}-usage-plan"`, `api_stages` referencing the stage, `throttle_settings { rate_limit = 50, burst_limit = 100 }`, `quota_settings { limit = 10000, period = "DAY" }`
   - `aws_api_gateway_usage_plan_key.this` — links API key to usage plan, `key_type = "API_KEY"`

6. Deployment + Stage:
   - `aws_api_gateway_deployment.this` — `depends_on` all 4 integrations, `triggers` block with `redeployment` key hashing all resource/method/integration IDs, `lifecycle { create_before_destroy = true }`
   - `aws_api_gateway_stage.this` — `stage_name = var.stage_name`, `rest_api_id` and `deployment_id` from above

7. Lambda permission:
   - `aws_lambda_permission.api_gateway` — `action = "lambda:InvokeFunction"`, `principal = "apigateway.amazonaws.com"`, `source_arn = "${aws_api_gateway_rest_api.this.execution_arn}/*/*"`

**`infra/modules/api-gateway/outputs.tf`**

3 outputs:
- `api_url` — `aws_api_gateway_stage.this.invoke_url`
- `rest_api_id` — `aws_api_gateway_rest_api.this.id`
- `api_key_value` — `aws_api_gateway_api_key.this.value`, `sensitive = true`

### Part B: Question Endpoint Module — Dependencies and Package Structure

**`modules/question-endpoint/requirements.txt`**
- `boto3`
- `psycopg2-binary`

**`modules/question-endpoint/dev-requirements.txt`**
- `pytest`

**6 empty `__init__.py` files** at: `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`

**`modules/question-endpoint/src/utils/logger.py`**
- Identical copy of `modules/embedding-module/src/utils/logger.py`: `JsonFormatter` class + `get_logger(name)` factory

### Part C: RetrievalService

**`modules/question-endpoint/src/services/retrieval_service.py`**

**Constructor:** `__init__(self, bedrock_client=None, secretsmanager_client=None)`
- `self._bedrock = bedrock_client or boto3.client("bedrock-runtime")`
- `self._secretsmanager = secretsmanager_client or boto3.client("secretsmanager")`
- `self._db_conn = None`
- `self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))`
- `self._secret_arn = os.environ["SECRET_ARN"]`
- `self._db_name = os.environ["DB_NAME"]`

**Method: `get_db_connection()`**
- Identical logic to `EmbeddingService.get_db_connection()`
- If `self._db_conn` is not `None` and `not self._db_conn.closed`, return it
- Call Secrets Manager, parse JSON, `psycopg2.connect(...)`, cache and return
- On exception: set `self._db_conn = None`, re-raise

**Method: `generate_embedding(text)`**
- Identical logic to `EmbeddingService.generate_embedding()`
- Call `self._bedrock.invoke_model(...)`, parse response, return `result["embedding"]`

**Method: `search_similar(embedding, top_k, similarity_threshold=0.0, speaker=None, video_id=None)`**
- `conn = self.get_db_connection()`
- `cursor = conn.cursor()` inside a `try` block
- `embedding_str = str(embedding)`
- Build base SQL: `SELECT chunk_id, video_id, text, speaker, title, start_time, end_time, source_s3_key, 1 - (embedding <=> %s::vector) AS similarity FROM video_chunks`
- Build `WHERE` clauses list and `params` list:
  - Start `params = [embedding_str]`
  - If `video_id` is not None: append `"video_id = %s"` to conditions, append `video_id` to params
  - If `speaker` is not None: append `"speaker = %s"` to conditions, append `speaker` to params
  - If conditions exist: append `" WHERE " + " AND ".join(conditions)` to SQL
- Append ` ORDER BY embedding <=> %s::vector LIMIT %s`
- Append `embedding_str` and `top_k` to params
- `cursor.execute(sql, params)`
- `rows = cursor.fetchall()`
- Column names list: `["chunk_id", "video_id", "text", "speaker", "title", "start_time", "end_time", "source_s3_key", "similarity"]`
- Convert each row to dict using `zip(column_names, row)`
- Filter: keep only dicts where `similarity >= similarity_threshold`
- Return results list
- `except` block: set `self._db_conn = None`, re-raise
- `finally` block: `cursor.close()`

**Method: `list_videos()`**
- `conn = self.get_db_connection()`
- `cursor = conn.cursor()` inside a `try` block
- Execute: `SELECT video_id, speaker, title, COUNT(*) AS chunk_count FROM video_chunks GROUP BY video_id, speaker, title ORDER BY video_id`
- `rows = cursor.fetchall()`
- Column names: `["video_id", "speaker", "title", "chunk_count"]`
- Convert each row to dict using `zip(column_names, row)`
- Return results list
- `except` block: set `self._db_conn = None`, re-raise
- `finally` block: `cursor.close()`

### Part D: Question Handler

**`modules/question-endpoint/src/handlers/question.py`**

Module-level:
- `service = RetrievalService()`
- `logger = get_logger(__name__)`
- Define `_response(status_code, body)` helper returning `{"statusCode", "headers" (CORS), "body" (json.dumps)}`
- Define `_validate_ask_body(body)` helper returning `(question, top_k, similarity_threshold, speaker, error_response)` — returns error_response if validation fails, else None for error_response

**`handler(event, context)`:**
1. Extract `request_id` from `context`
2. Read `resource = event.get("resource", "")`
3. Read `http_method = event.get("httpMethod", "")`
4. Route on `(http_method, resource)`:
   - `("GET", "/health")` → return `_response(200, {"status": "healthy"})`
   - `("GET", "/videos")` → wrapped in `try/except`: call `service.list_videos()`, return `_response(200, {"videos": results})`; on exception → `_response(500, {"error": "internal error"})`
   - `("POST", "/ask")` → wrapped in `try/except`:
     a. Parse `json.loads(event.get("body", "{}"))` (handle JSONDecodeError → 400)
     b. Validate via `_validate_ask_body(body)` — if error_response, return it
     c. Call `service.generate_embedding(question)`
     d. Call `service.search_similar(embedding, top_k, similarity_threshold, speaker=speaker)`
     e. Return `_response(200, {"question": question, "results": results})`
     f. On unhandled exception → `_response(500, {"error": "internal error"})`
   - `("POST", "/videos/{video_id}/ask")` → wrapped in `try/except`:
     a. Extract `video_id = event["pathParameters"]["video_id"]`
     b. Parse body, validate (same as /ask but no speaker filter)
     c. Call `service.generate_embedding(question)`
     d. Call `service.search_similar(embedding, top_k, similarity_threshold, video_id=video_id)`
     e. Return `_response(200, {"video_id": video_id, "question": question, "results": results})`
     f. On unhandled exception → `_response(500, {"error": "internal error"})`
   - Default → `_response(404, {"error": "not found"})`

**`_validate_ask_body(body)`:**
- Extract `question = body.get("question", "")`
- If not `question` or not `isinstance(question, str)` or `question.strip() == ""` → return error: `_response(400, {"error": "question is required"})`
- Extract `top_k = body.get("top_k", 5)` — if not int or `< 1` or `> 100` → return error: `_response(400, {"error": "top_k must be between 1 and 100"})`
- Extract `similarity_threshold = body.get("similarity_threshold", 0.0)` — if not numeric or `< 0.0` or `> 1.0` → return error: `_response(400, {"error": "similarity_threshold must be between 0.0 and 1.0"})`
- Extract `speaker = body.get("filters", {}).get("speaker")` if called from `/ask` route (or `None` for video-scoped route)
- Return `(question, top_k, similarity_threshold, speaker, None)`

### Part E: Tests

**`modules/question-endpoint/tests/conftest.py`**

Fixtures:
- `aws_credentials(monkeypatch)` — monkeypatch `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SECURITY_TOKEN`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION` + `SECRET_ARN`, `DB_NAME`, `EMBEDDING_DIMENSIONS`
- `sample_ask_event` — API Gateway proxy event for `POST /ask`:
  - `resource = "/ask"`, `path = "/ask"`, `httpMethod = "POST"`, `headers = {"Content-Type": "application/json"}`, `body = json.dumps({"question": "What is RAG?", "top_k": 5})`
- `sample_video_ask_event` — API Gateway proxy event for `POST /videos/{video_id}/ask`:
  - `resource = "/videos/{video_id}/ask"`, `path = "/videos/hello-my_name_is_wes/ask"`, `httpMethod = "POST"`, `pathParameters = {"video_id": "hello-my_name_is_wes"}`, `body = json.dumps({"question": "What is this about?", "top_k": 3})`
- `sample_health_event` — `resource = "/health"`, `httpMethod = "GET"`, `body = None`
- `sample_videos_event` — `resource = "/videos"`, `httpMethod = "GET"`, `body = None`

**`modules/question-endpoint/tests/unit/test_retrieval_service.py`**

Top of file: set env vars with `os.environ.setdefault(...)` for `SECRET_ARN`, `DB_NAME`, `EMBEDDING_DIMENSIONS` before imports. Import `RetrievalService` directly. Patch `boto3.client` when importing the handler module (same pattern as embedding-module tests).

| # | Class | Test | How |
|---|-------|------|-----|
| 1 | `TestGenerateEmbedding` | `test_generate_embedding_returns_vector` | Create service with mock bedrock_client, configure `invoke_model` to return `StreamingBody` wrapping JSON with 256-float embedding, call `generate_embedding`, assert result is list of 256 floats |
| 2 | `TestGenerateEmbedding` | `test_generate_embedding_passes_correct_params` | Same mock setup, call `generate_embedding`, assert `invoke_model` called with correct `modelId`, `dimensions=256`, `normalize=True` |
| 3 | `TestSearchSimilar` | `test_search_similar_returns_ranked_results` | Create service with `__new__`, mock `get_db_connection` to return mock conn/cursor, configure `cursor.fetchall` to return 2 fake rows, call `search_similar`, assert list of 2 dicts with correct keys |
| 4 | `TestSearchSimilar` | `test_search_similar_with_speaker_filter` | Same mock setup, call `search_similar(speaker="Jane")`, capture executed SQL, assert `WHERE` contains `speaker =` |
| 5 | `TestSearchSimilar` | `test_search_similar_without_filter` | Same mock setup, call `search_similar` without speaker/video_id, capture SQL, assert no `WHERE` clause |
| 6 | `TestSearchSimilar` | `test_search_similar_filters_below_threshold` | Configure fetchall with rows at similarities [0.9, 0.4, 0.7], call with `similarity_threshold=0.5`, assert only 2 results returned (0.9 and 0.7) |
| 7 | `TestSearchSimilar` | `test_search_similar_with_video_id_filter` | Call `search_similar(video_id="test-vid")`, capture SQL, assert `WHERE` contains `video_id =` |
| 8 | `TestListVideos` | `test_list_videos_returns_aggregated` | Mock cursor.fetchall with fake rows, call `list_videos`, assert list of dicts with `video_id`, `speaker`, `title`, `chunk_count` |
| 9 | `TestHandler` | `test_handler_post_ask_returns_results` | Patch module-level `service`, invoke handler with `sample_ask_event`, assert 200 response with `question` and `results` in body |
| 10 | `TestHandler` | `test_handler_post_ask_missing_question` | Invoke handler with event where body has empty question, assert 400 with `{"error": "question is required"}` |
| 11 | `TestHandler` | `test_handler_post_video_ask_returns_results` | Patch service, invoke with `sample_video_ask_event`, assert 200 with `video_id`, `question`, `results` |
| 12 | `TestHandler` | `test_handler_post_video_ask_passes_video_id` | Patch service, invoke with `sample_video_ask_event`, assert `search_similar` called with `video_id="hello-my_name_is_wes"` |
| 13 | `TestHandler` | `test_handler_get_health` | Invoke with `sample_health_event`, assert 200 with `{"status": "healthy"}` |
| 14 | `TestHandler` | `test_handler_get_videos` | Patch service.list_videos to return fake list, invoke with `sample_videos_event`, assert 200 with `{"videos": [...]}` |
| 15 | `TestHandler` | `test_handler_unknown_route` | Invoke with `resource = "/unknown"`, assert 404 |

### Part F: Terraform — Dev Environment

**`infra/environments/dev/main.tf`** — append 2 blocks after the existing `embed_text_public_invoke` permission and before `null_resource.run_migrations`:

1. `module "question"` using `../../modules/lambda-vpc`:
   - `function_name = "${var.project_name}-question"`
   - `handler = "src.handlers.question.handler"`
   - `source_dir = "${path.module}/../../../modules/question-endpoint"`
   - `timeout = 30`
   - `subnet_ids = module.networking.subnet_ids`
   - `security_group_ids = [module.networking.lambda_security_group_id]`
   - `layers = [aws_lambda_layer_version.psycopg2.arn]`
   - `environment_variables`: `SECRET_ARN`, `DB_NAME`, `EMBEDDING_DIMENSIONS = "256"`
   - `policy_statements`: 2 statements — `bedrock:InvokeModel` on Titan V2, `secretsmanager:GetSecretValue` on `module.aurora_vectordb.secret_arn`

2. `module "question_api"` using `../../modules/api-gateway`:
   - `api_name = "${var.project_name}-question-api"`
   - `lambda_invoke_arn = module.question.invoke_arn`
   - `lambda_function_name = module.question.function_name`
   - `stage_name = "prod"`
   - `tags = local.common_tags`

**`infra/environments/dev/outputs.tf`** — append 3 outputs:
- `question_api_url = module.question_api.api_url`
- `question_api_key = module.question_api.api_key_value` (sensitive)
- `question_function_name = module.question.function_name`

---

## Risks / Assumptions

1. **psycopg2 import at module level in service.** Same as embedding module — Lambda layer provides psycopg2 at runtime, `psycopg2-binary` in requirements.txt covers local dev/testing. Tests mock `get_db_connection` rather than patching the import.

2. **Bedrock model ARN in IAM policy.** Uses empty account ID (`arn:aws:bedrock:{region}::foundation-model/...`) — foundation models are AWS-managed. Same pattern as embedding module.

3. **`str(embedding)` for vector casting.** Python's `str([0.01, -0.02, ...])` produces `[0.01, -0.02, ...]` which pgvector accepts via `::vector` cast. Same pattern as embedding module.

4. **API Gateway deployment triggers.** Uses `sha1(jsonencode(...))` of all resource/method/integration IDs to force redeployment when routes change. Without this, API Gateway may serve stale routes.

5. **`api_key_required = true` without CORS preflight.** OPTIONS requests are not configured. If a browser client needs CORS preflight, an OPTIONS method with `MOCK` integration would be needed. The spec does not call for this — the expected client is `curl` or the MCP server.

6. **Connection caching across warm invocations.** The `RetrievalService` instance is module-level, so `self._db_conn` persists across invocations within the same Lambda container. The `closed` check handles container recycling.

7. **Threshold filtering in Python not SQL.** This means `top_k` rows are always fetched from pgvector even if many are below threshold. For the expected scale (small number of chunks), this is fine.

---

## Implementation Checklist

### Phase 1: Question Endpoint — Tests First (steps 1–9)

- [ ] 1. Create `modules/question-endpoint/requirements.txt` with `boto3`, `psycopg2-binary`
- [ ] 2. Create `modules/question-endpoint/dev-requirements.txt` with `pytest`
- [ ] 3. Create 6 empty `__init__.py` files: `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`
- [ ] 4. Create `modules/question-endpoint/src/utils/logger.py` — copy of embedding-module's logger
- [ ] 5. Create `modules/question-endpoint/tests/conftest.py` with fixtures: `aws_credentials`, `sample_ask_event`, `sample_video_ask_event`, `sample_health_event`, `sample_videos_event`
- [ ] 6. Create `modules/question-endpoint/tests/unit/test_retrieval_service.py` with 15 test cases (tests will fail until Phase 2)

### Phase 2: Question Endpoint — Implementation (steps 7–10)

- [ ] 7. Create `modules/question-endpoint/src/services/retrieval_service.py` — `RetrievalService` class with `get_db_connection`, `generate_embedding`, `search_similar`, `list_videos`
- [ ] 8. Create `modules/question-endpoint/src/handlers/question.py` — HTTP handler with route dispatch, validation, `_response` helper
- [ ] 9. Install deps and run tests: `cd modules/question-endpoint && pip install -r dev-requirements.txt -r requirements.txt && python -m pytest tests/ -v` — all 15 pass
- [ ] 10. Run lint check

### Phase 3: API Gateway Terraform Module (steps 11–13)

- [ ] 11. Create `infra/modules/api-gateway/variables.tf` with 5 variables
- [ ] 12. Create `infra/modules/api-gateway/main.tf` with REST API, 5 resources, 4 methods, 4 integrations, API key, usage plan, deployment, stage, Lambda permission
- [ ] 13. Create `infra/modules/api-gateway/outputs.tf` with 3 outputs

### Phase 4: Terraform Dev Environment Wiring (steps 14–16)

- [ ] 14. Add `module "question"` (lambda-vpc) to `infra/environments/dev/main.tf`
- [ ] 15. Add `module "question_api"` (api-gateway) to `infra/environments/dev/main.tf`
- [ ] 16. Add `question_api_url`, `question_api_key` (sensitive), `question_function_name` outputs to `infra/environments/dev/outputs.tf`

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
