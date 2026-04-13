# Embedding Module & SQS Wiring — Implementation Plan

**Goal:** Create the embedding Lambda module (Python handler + service + tests), deploy it via the `lambda-vpc` Terraform module, wire SQS event source mapping, fix `archive_file` excludes in both Lambda Terraform modules, and fix the `null_resource.run_migrations` error-checking — so that SQS messages from chunking trigger embedding generation and pgvector upsert.

---

## New Files (13)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/embedding-module/requirements.txt` | `boto3`, `psycopg2-binary` |
| 2 | `modules/embedding-module/dev-requirements.txt` | `pytest`, `moto[s3,secretsmanager]` |
| 3 | `modules/embedding-module/src/__init__.py` | Empty package marker |
| 4 | `modules/embedding-module/src/handlers/__init__.py` | Empty package marker |
| 5 | `modules/embedding-module/src/services/__init__.py` | Empty package marker |
| 6 | `modules/embedding-module/src/utils/__init__.py` | Empty package marker |
| 7 | `modules/embedding-module/tests/__init__.py` | Empty package marker |
| 8 | `modules/embedding-module/tests/unit/__init__.py` | Empty package marker |
| 9 | `modules/embedding-module/src/utils/logger.py` | Identical to transcribe/chunking modules |
| 10 | `modules/embedding-module/src/services/embedding_service.py` | Business logic: read chunk, generate embedding, store in pgvector |
| 11 | `modules/embedding-module/src/handlers/process_embedding.py` | Lambda entry point: iterate SQS records, call service |
| 12 | `modules/embedding-module/tests/conftest.py` | Shared fixtures: `aws_credentials`, `mock_aws_services`, `sample_chunk`, `sample_sqs_event`, `s3_bucket` |
| 13 | `modules/embedding-module/tests/unit/test_embedding_service.py` | 8 unit tests |

## Files to Modify (4)

| # | File | Change |
|---|------|--------|
| 1 | `infra/modules/lambda/main.tf` | Add `excludes` to `archive_file` data source |
| 2 | `infra/modules/lambda-vpc/main.tf` | Add `excludes` to `archive_file` data source |
| 3 | `infra/environments/dev/main.tf` | Add `module "embed_chunk"`, `aws_lambda_event_source_mapping.embedding`, fix `null_resource.run_migrations` provisioner |
| 4 | `infra/environments/dev/outputs.tf` | Add `embedding_function_name` output |

---

## Architecture Decisions

**1. Injectable clients (deviation from spec).** The spec shows hardcoded `boto3.client()` calls in `EmbeddingService.__init__`. Following the established pattern from `TranscribeService` and `ChunkingService`, the constructor accepts optional `s3_client`, `bedrock_client`, `secretsmanager_client` parameters with `or boto3.client(...)` fallbacks. This enables direct moto injection in tests without monkeypatching.

**2. `__init__.py` files (deviation from existing modules).** Existing modules (transcribe, chunking) have no `__init__.py` files yet work because Lambda zips the module root as `PYTHONPATH`. The spec explicitly calls for them. Including them is harmless and makes the package structure explicit, so we follow the spec.

**3. Bedrock mocking via `unittest.mock`, not moto.** Moto does not support Bedrock Runtime. `generate_embedding` tests mock `self._bedrock.invoke_model` directly. S3 tests use moto. psycopg2 tests use `unittest.mock` for the connection and cursor.

**4. DB connection caching on the service instance.** `self._db_conn` is set on first call to `get_db_connection()` and reused across warm invocations. If the connection is closed (checked via `self._db_conn.closed`), it reconnects. On connection error, `self._db_conn` is set to `None` and the exception re-raises.

**5. Handler does not catch exceptions.** Per the spec and the SQS event source mapping contract: unhandled exceptions cause the Lambda invocation to fail, SQS retries the message, and after 3 failures the message moves to the DLQ. No `try/except`, no `statusCode` return.

**6. `archive_file` excludes scope.** Both `lambda/main.tf` and `lambda-vpc/main.tf` get the same excludes: `.venv`, `.pytest_cache`, `tests`, `dev-requirements.txt`. This protects all modules from oversized zips.

**7. `null_resource.run_migrations` fix scope.** Two changes: (a) add `--cli-read-timeout 310` so the CLI doesn't abandon the invocation before the Lambda completes, (b) add `grep -q '"errorMessage"'` check so Terraform fails if the Lambda returned an error.

---

## Detailed Per-File Descriptions

### Part A: Embedding Module — Dependencies and Package Structure

**`modules/embedding-module/requirements.txt`**
- `boto3`
- `psycopg2-binary`

**`modules/embedding-module/dev-requirements.txt`**
- `pytest`
- `moto[s3,secretsmanager]`

**8 empty `__init__.py` files** at `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`

**`modules/embedding-module/src/utils/logger.py`**
- Identical copy of `modules/transcribe-module/src/utils/logger.py`: `JsonFormatter` class + `get_logger(name)` factory

### Part B: EmbeddingService

**`modules/embedding-module/src/services/embedding_service.py`**

**Constructor:** `__init__(self, s3_client=None, bedrock_client=None, secretsmanager_client=None)`
- `self._s3 = s3_client or boto3.client("s3")`
- `self._bedrock = bedrock_client or boto3.client("bedrock-runtime")`
- `self._secretsmanager = secretsmanager_client or boto3.client("secretsmanager")`
- `self._db_conn = None`
- `self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))`
- `self._secret_arn = os.environ["SECRET_ARN"]`
- `self._db_name = os.environ["DB_NAME"]`

**Method: `get_db_connection()`**
- If `self._db_conn` is not `None` and `not self._db_conn.closed`, return it
- Call `self._secretsmanager.get_secret_value(SecretId=self._secret_arn)`
- Parse JSON secret → extract `host`, `port`, `username`, `password`
- `psycopg2.connect(host=host, port=port, dbname=self._db_name, user=username, password=password)`
- Set `self._db_conn`, return it
- On any exception: set `self._db_conn = None`, re-raise

**Method: `read_chunk(bucket, key)`**
- `self._s3.get_object(Bucket=bucket, Key=key)`
- `json.loads(response["Body"].read())`
- Returns parsed dict

**Method: `generate_embedding(text)`**
- `self._bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", contentType="application/json", accept="application/json", body=json.dumps({"inputText": text, "dimensions": self._dimensions, "normalize": True}))`
- Parse `json.loads(response["body"].read())`
- Return `result["embedding"]`

**Method: `store_embedding(chunk, embedding)`**
- `conn = self.get_db_connection()`
- `cursor = conn.cursor()`
- Convert embedding list to string: `str(embedding)`
- Extract `speaker = chunk["metadata"].get("speaker")`, `title = chunk["metadata"].get("title")`, `source_s3_key = chunk["metadata"]["source_s3_key"]`
- Execute upsert SQL (per spec) with 10 positional parameters: `chunk_id`, `video_id`, `sequence`, `text`, `embedding_str` (cast to `::vector`), `speaker`, `title`, `start_time`, `end_time`, `source_s3_key`
- `conn.commit()`
- `cursor.close()` (not connection — connection is cached)

### Part C: Handler

**`modules/embedding-module/src/handlers/process_embedding.py`**

- Module-level: `service = EmbeddingService()`, `logger = get_logger(__name__)`
- `handler(event, context)`:
  1. Extract `request_id` from `context` (same guard as other handlers)
  2. Iterate `event["Records"]`
  3. For each record: `body = json.loads(record["body"])` → extract `chunk_s3_key`, `bucket`, `video_id`
  4. `chunk = service.read_chunk(bucket, chunk_s3_key)`
  5. `embedding = service.generate_embedding(chunk["text"])`
  6. `service.store_embedding(chunk, embedding)`
  7. Log success with `chunk_id` and `video_id`
- No try/except, no return value (SQS contract)

### Part D: Tests

**`modules/embedding-module/tests/conftest.py`**

Fixtures:
- `aws_credentials(monkeypatch)` — monkeypatch 5 AWS env vars + `SECRET_ARN`, `DB_NAME`, `EMBEDDING_DIMENSIONS`
- `mock_aws_services(aws_credentials)` — `mock_aws()` context manager yielding `{"s3": ..., "secretsmanager": ...}` clients
- `sample_chunk` — dict matching chunk JSON schema: `chunk_id`, `video_id`, `sequence`, `text`, `word_count`, `start_time`, `end_time`, `metadata` (with `speaker`, `title`, `source_s3_key`, `total_chunks`)
- `sample_sqs_event` — dict matching SQS event format with one Record whose body contains `chunk_s3_key`, `bucket`, `video_id`, `speaker`, `title`
- `s3_bucket(mock_aws_services)` — creates moto S3 bucket `test-bucket`, returns bucket name

**`modules/embedding-module/tests/unit/test_embedding_service.py`**

| # | Test | How |
|---|------|-----|
| 1 | `test_read_chunk_parses_json` | Upload chunk JSON to moto S3, create `EmbeddingService` with moto s3_client, call `read_chunk`, assert returned dict matches `sample_chunk` |
| 2 | `test_read_chunk_missing_key_raises` | Call `read_chunk` with nonexistent key, assert `ClientError` raised |
| 3 | `test_generate_embedding_returns_vector` | Create service with mock bedrock_client, configure `invoke_model` to return a `StreamingBody` wrapping JSON with 256-float embedding, call `generate_embedding`, assert result is list of 256 floats |
| 4 | `test_generate_embedding_passes_correct_params` | Same mock setup, call `generate_embedding`, assert `invoke_model` called with correct `modelId`, and body JSON contains `dimensions=256`, `normalize=True` |
| 5 | `test_store_embedding_executes_upsert` | Mock `get_db_connection` to return a mock connection with mock cursor, call `store_embedding`, assert `cursor.execute` called once with SQL containing `INSERT INTO video_chunks` and `ON CONFLICT (chunk_id) DO UPDATE`, verify all 10 positional params |
| 6 | `test_store_embedding_commits` | Same mock setup, call `store_embedding`, assert `connection.commit()` called once |
| 7 | `test_handler_processes_single_record` | Patch module-level `service` with mock, invoke handler with 1-record SQS event, assert `read_chunk`, `generate_embedding`, `store_embedding` each called once |
| 8 | `test_handler_processes_multiple_records` | Patch module-level `service` with mock, invoke handler with 2-record SQS event, assert service methods each called twice |

### Part E: Terraform Changes

**`infra/modules/lambda/main.tf`** — add `excludes` to `archive_file`:
- `excludes = [".venv", ".pytest_cache", "tests", "dev-requirements.txt"]`

**`infra/modules/lambda-vpc/main.tf`** — same `excludes` addition

**`infra/environments/dev/main.tf`** — 3 changes:

1. `module "embed_chunk"` using `../../modules/lambda-vpc`:
   - `function_name = "${var.project_name}-embed-chunk"`
   - `handler = "src.handlers.process_embedding.handler"`
   - `source_dir = "${path.module}/../../../modules/embedding-module"`
   - `timeout = 120`
   - `subnet_ids = module.networking.subnet_ids`
   - `security_group_ids = [module.networking.lambda_security_group_id]`
   - `layers = [aws_lambda_layer_version.psycopg2.arn]`
   - `environment_variables`: `SECRET_ARN = module.aurora_vectordb.secret_arn`, `DB_NAME = module.aurora_vectordb.db_name`, `EMBEDDING_DIMENSIONS = "256"`
   - `policy_statements`: 4 statements — `s3:GetObject` on `${module.media_bucket.bucket_arn}/chunks/*`, `bedrock:InvokeModel` on `arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0`, `secretsmanager:GetSecretValue` on `${module.aurora_vectordb.secret_arn}`, SQS `ReceiveMessage`+`DeleteMessage`+`GetQueueAttributes` on `${aws_sqs_queue.embedding.arn}`

2. `aws_lambda_event_source_mapping.embedding`:
   - `event_source_arn = aws_sqs_queue.embedding.arn`
   - `function_name = module.embed_chunk.function_arn`
   - `batch_size = 1`
   - `enabled = true`

3. Fix `null_resource.run_migrations` provisioner:
   - Add `--cli-read-timeout 310` to `aws lambda invoke`
   - Change output file to `/tmp/migration-response.json`
   - Add `grep -q '"errorMessage"' /tmp/migration-response.json && exit 1 || true` after `cat`

**`infra/environments/dev/outputs.tf`** — add:
- `embedding_function_name = module.embed_chunk.function_name`

---

## Risks / Assumptions

1. **psycopg2 import at module level in service.** The Lambda layer provides psycopg2 at runtime, but `import psycopg2` at the top of `embedding_service.py` will fail in tests unless psycopg2-binary is installed in the test venv. The `requirements.txt` includes `psycopg2-binary` for this reason. In tests that mock psycopg2, we mock `get_db_connection` on the service instance rather than patching the psycopg2 import.

2. **Bedrock model ARN in IAM policy.** The ARN format `arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0` uses an empty account ID (foundation models are AWS-managed). This is the correct format per AWS documentation.

3. **`str(embedding)` for vector casting.** Python's `str([0.01, -0.02, ...])` produces `[0.01, -0.02, ...]` which pgvector accepts via `::vector` cast. This matches the spec's format.

4. **Connection caching across warm invocations.** The service instance is module-level, so `self._db_conn` persists across invocations within the same Lambda container. The `closed` check handles container recycling and connection timeouts.

5. **`archive_file` excludes apply to all existing modules.** Adding excludes to the shared Terraform modules is safe — the excluded paths should never be in a Lambda deployment package regardless.

---

## Implementation Checklist

### Phase 1: Embedding Module — Tests First

- [ ] 1.1. Create `modules/embedding-module/requirements.txt` with `boto3`, `psycopg2-binary`
- [ ] 1.2. Create `modules/embedding-module/dev-requirements.txt` with `pytest`, `moto[s3,secretsmanager]`
- [ ] 1.3. Create 8 empty `__init__.py` files: `src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`
- [ ] 1.4. Create `modules/embedding-module/src/utils/logger.py` — copy of transcribe-module's logger
- [ ] 1.5. Create `modules/embedding-module/tests/conftest.py` with fixtures: `aws_credentials`, `mock_aws_services`, `sample_chunk`, `sample_sqs_event`, `s3_bucket`
- [ ] 1.6. Create `modules/embedding-module/tests/unit/test_embedding_service.py` with 8 test cases (tests will fail until Phase 2)

### Phase 2: Embedding Module — Implementation

- [ ] 2.1. Create `modules/embedding-module/src/services/embedding_service.py` — `EmbeddingService` class with `get_db_connection`, `read_chunk`, `generate_embedding`, `store_embedding`
- [ ] 2.2. Create `modules/embedding-module/src/handlers/process_embedding.py` — SQS handler iterating records, calling service methods, no exception handling
- [ ] 2.3. Install deps and run tests: `cd modules/embedding-module && pip install -r dev-requirements.txt -r requirements.txt && python -m pytest tests/ -v` — all 8 pass
- [ ] 2.4. Run lint check

### Phase 3: Terraform Changes

- [ ] 3.1. Add `excludes` to `archive_file` in `infra/modules/lambda/main.tf`
- [ ] 3.2. Add `excludes` to `archive_file` in `infra/modules/lambda-vpc/main.tf`
- [ ] 3.3. Fix `null_resource.run_migrations` provisioner in `infra/environments/dev/main.tf` — add `--cli-read-timeout 310` and `grep` error check
- [ ] 3.4. Add `module "embed_chunk"` (lambda-vpc) to `infra/environments/dev/main.tf`
- [ ] 3.5. Add `aws_lambda_event_source_mapping.embedding` to `infra/environments/dev/main.tf`
- [ ] 3.6. Add `embedding_function_name` output to `infra/environments/dev/outputs.tf`

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
