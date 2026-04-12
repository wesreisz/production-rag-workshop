# Code Review Fixes

**Deliverable:** Resolve all Critical and Required findings from the automated code review audit. Fixes span five areas: infrastructure security, Step Functions pipeline reliability, query correctness, input validation, and test coverage gaps.

---

## Overview

The audit identified 3 Critical issues (must fix before any production deploy), 6 Required changes (must fix before merge), and several cross-cutting improvements. This spec addresses all Critical and Required items. Nit-level items (shared DB utils, pinned deps, DRY fixtures) are included as a separate, lower-priority section.

**Issues resolved by this spec:**

| # | Severity | Module | Issue |
|---|----------|--------|-------|
| 1 | Critical | `infra` | `embed_text_public_invoke` grants `lambda:InvokeFunction` to `principal="*"` |
| 2 | Critical | `transcribe-module` | `try/except` in Step Functions handlers causes indefinite pipeline hang |
| 3 | Critical | `infra` | `skip_final_snapshot=true` + `recovery_window_in_days=0` undocumented data-loss risk |
| 4 | Required | `question-endpoint` | `JSONDecodeError` returns 500 instead of 400 |
| 5 | Required | `question-endpoint` | `similarity_threshold` filtered in Python after SQL `LIMIT` — wrong results |
| 6 | Required | `question-endpoint` | `LIST_VIDEOS_SQL` has no `LIMIT` — unbounded query |
| 7 | Required | `transcribe-module` | `derive_video_id` allows `/` in job name — AWS Transcribe rejects it |
| 8 | Required | `embedding-endpoint` | Zero test coverage; empty `API_KEY` passes auth |
| 9 | Required | `migration-module` | URL credentials in f-string connection string — breaks on special characters |

---

## Prerequisites

- [ ] All existing unit tests pass before starting
- [ ] `terraform plan` runs cleanly in `infra/environments/dev/`

---

## Fix 1 — Remove Over-Permissive IAM on Embedding Lambda

**File:** `infra/environments/dev/main.tf`

The `embed_text_public_invoke` resource grants `lambda:InvokeFunction` to `principal = "*"`. This is different from `lambda:InvokeFunctionUrl` (which governs the Function URL). With this permission in place, any AWS account can invoke the Lambda directly via the SDK, bypassing the Function URL and its `x-api-key` check entirely.

**Change:** Delete the `aws_lambda_permission.embed_text_public_invoke` resource block. The `embed_text_public_url` permission (which grants `lambda:InvokeFunctionUrl` to `"*"`) is the correct one and must remain.

```hcl
# DELETE this entire block:
resource "aws_lambda_permission" "embed_text_public_invoke" {
  statement_id  = "FunctionURLInvokeAllowPublicAccess"
  action        = "lambda:InvokeFunction"
  function_name = module.embed_text_endpoint.function_name
  principal     = "*"
}
```

**Verification:** After `terraform apply`, confirm via `aws lambda get-policy --function-name <embed_text_fn_name>` that no `lambda:InvokeFunction` statement with `Principal: "*"` exists.

---

## Fix 2 — Step Functions Handler Exception Propagation

**Files:**
- `modules/transcribe-module/src/handlers/start_transcription.py`
- `modules/transcribe-module/src/handlers/check_transcription.py`

**Root cause:** Both handlers wrap all logic in `try/except` blocks and return structured error payloads on failure. Step Functions sees a *successful Lambda invocation* in all cases. When `start_transcription` fails (e.g., unsupported file format), the error payload missing `transcription_job_name` causes `check_transcription` to raise a `KeyError`, which is also caught — producing another error payload. The `WaitForTranscription` loop then polls indefinitely because `check_transcription` always "succeeds."

The state machine already has `Retry` and `Catch` clauses on every task state. These exist precisely to handle Lambda exceptions. The handlers must let exceptions propagate.

**Change — `start_transcription.py`:**

Remove the outer `try/except ValueError` and `except Exception` blocks. The handler body becomes a direct call sequence with no exception handling. The `request_id` extraction and logging remain.

Before (abbreviated):
```python
def handler(event, context):
    request_id = context.aws_request_id
    try:
        ...
        return {"statusCode": 200, "detail": {...}}
    except ValueError as e:
        logger.error(...)
        return {"statusCode": 400, "detail": {"error": str(e)}}
    except Exception as e:
        logger.error(...)
        return {"statusCode": 500, "detail": {"error": "internal error"}}
```

After:
```python
def handler(event, context):
    request_id = context.aws_request_id
    ...
    return {"statusCode": 200, "detail": {...}}
```

Apply the same change to `check_transcription.py`.

**Verification:** In the test suite, update any tests that assert on the 400/500 return payloads from handler-level exception paths — those tests should instead assert that the exception propagates (i.e., `pytest.raises`).

---

## Fix 3 — Document Data-Loss Risk in Aurora and Secrets Manager Config

**File:** `infra/modules/aurora-vectordb/main.tf`

Two settings in combination create a silent data-loss risk:
- `skip_final_snapshot = true` — `terraform destroy` permanently deletes all vector embeddings
- `recovery_window_in_days = 0` on the Secrets Manager secret — the secret can be immediately and permanently deleted

These are intentional for a dev sandbox environment but must be guarded so they cannot accidentally be applied to a production workspace.

**Change:** Add a Terraform variable `enable_deletion_protection` (default `false`) to the `aurora-vectordb` module. When `true`, set `skip_final_snapshot = false` and `deletion_protection = true` on the cluster, and set `recovery_window_in_days = 30` on the secret. Add inline comments to both resource blocks explaining the risk.

**Variable to add in `infra/modules/aurora-vectordb/variables.tf`:**

```hcl
variable "enable_deletion_protection" {
  description = "Set to true for production. Enables final snapshot on destroy and 30-day secret recovery window."
  type        = bool
  default     = false
}
```

**Cluster block changes:**

```hcl
skip_final_snapshot    = !var.enable_deletion_protection
final_snapshot_identifier = var.enable_deletion_protection ? "${var.project_name}-final-snapshot" : null
deletion_protection    = var.enable_deletion_protection
# WARNING: skip_final_snapshot=true means terraform destroy permanently deletes all data.
# Set enable_deletion_protection=true for any non-throwaway environment.
```

**Secret block changes:**

```hcl
recovery_window_in_days = var.enable_deletion_protection ? 30 : 0
# WARNING: recovery_window_in_days=0 allows immediate permanent secret deletion.
# Set enable_deletion_protection=true for any non-throwaway environment.
```

**Verification:** Run `terraform plan` and confirm no resource changes. Review plan output confirms the new variable appears with its default.

---

## Fix 4 — Return 400 for Malformed JSON Body

**File:** `modules/question-endpoint/src/handlers/question.py`

`_parse_post_body` calls `json.loads` directly. A client sending a non-JSON body triggers `json.JSONDecodeError`, which bubbles up to the outer `except Exception` handler and produces a 500. The `embedding-endpoint` handler already handles this correctly — match that pattern.

**Change:** Wrap `json.loads` in a `try/except json.JSONDecodeError` inside `_parse_post_body` and raise a `ValueError` with a descriptive message. The outer handler's `except ValueError` path already returns a 400.

Before:
```python
def _parse_post_body(event):
    raw_body = event.get("body") or "{}"
    return json.loads(raw_body)
```

After:
```python
def _parse_post_body(event):
    raw_body = event.get("body") or "{}"
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        raise ValueError("request body must be valid JSON")
```

**Tests to add in `modules/question-endpoint/tests/unit/test_question_handler.py`:**

| Test | Description |
|------|-------------|
| `test_post_ask_malformed_json_returns_400` | Send `POST /ask` with `body: "not-json"`, verify 400 response with error message |
| `test_post_video_ask_malformed_json_returns_400` | Same for `POST /videos/{video_id}/ask` |

---

## Fix 5 — Push similarity_threshold into SQL WHERE Clause

**File:** `modules/question-endpoint/src/services/retrieval_service.py`

**Root cause:** The current code fetches `top_k` rows and then filters by `similarity_threshold` in Python. This is wrong: if the top-k results include low-similarity items and there are higher-similarity items beyond the `LIMIT`, those are never returned.

**Change:** Add `similarity_threshold` as a SQL parameter and push the filter into the `WHERE` clause on all four search query constants (`SEARCH_SQL`, `SEARCH_SQL_VIDEO_ID`, `SEARCH_SQL_SPEAKER`, `SEARCH_SQL_BOTH`). Remove the Python-level list comprehension filter.

Each SQL query currently ends with:
```sql
ORDER BY similarity DESC
LIMIT %(top_k)s
```

Change to:
```sql
WHERE 1 - (embedding <=> %(embedding)s::vector) >= %(similarity_threshold)s
ORDER BY similarity DESC
LIMIT %(top_k)s
```

The `%(embedding)s` reference in the WHERE clause requires adding it as a named parameter. Since embedding already appears in the SELECT, add it as a named bind parameter: `%(embedding)s::vector` in both the SELECT expression and the WHERE clause.

In the `search_similar` method, remove:
```python
return [r for r in results if r["similarity"] >= similarity_threshold]
```

And update the SQL parameter dict to include `similarity_threshold`.

**Tests to update/add in `modules/question-endpoint/tests/unit/test_retrieval_service.py`:**

| Test | Description |
|------|-------------|
| `test_search_respects_similarity_threshold` | Mock cursor returning rows with varied similarity scores, verify only rows at or above threshold are returned |
| `test_search_threshold_in_sql_params` | Verify `similarity_threshold` is passed to `cursor.execute` as a parameter, not applied post-fetch |

---

## Fix 6 — Add LIMIT to LIST_VIDEOS_SQL

**File:** `modules/question-endpoint/src/services/retrieval_service.py`

`LIST_VIDEOS_SQL` has no `LIMIT`, making it unbounded as the corpus grows.

**Change:** Add `LIMIT 500` to the query as a reasonable default ceiling. If pagination is needed later, it can be added as a follow-up.

```sql
SELECT video_id, speaker, title, COUNT(*) AS chunk_count
FROM video_chunks
GROUP BY video_id, speaker, title
ORDER BY video_id
LIMIT 500;
```

**Tests:** No test change required — existing `test_list_videos_*` tests mock the cursor and are not affected by the SQL change.

---

## Fix 7 — Validate video_id Before Forming Transcribe Job Name

**File:** `modules/transcribe-module/src/services/transcribe_service.py`

`derive_video_id` strips the `uploads/` prefix and splits on the extension. A nested key like `uploads/subfolder/talk.mp3` produces `video_id = "subfolder/talk"`. AWS Transcribe job names cannot contain `/` and will reject the request with a `ValidationException`.

**Change:** After deriving the video ID, validate it contains no `/`. Raise `ValueError` with a descriptive message if it does.

```python
@staticmethod
def derive_video_id(s3_key):
    filename = s3_key.replace("uploads/", "", 1)
    video_id, _ = os.path.splitext(filename)
    if "/" in video_id:
        raise ValueError(
            f"S3 key '{s3_key}' contains a nested path. "
            "Upload files directly under uploads/ with no subdirectories."
        )
    return video_id
```

**Tests to add in `modules/transcribe-module/tests/unit/test_transcribe_service.py`:**

| Test | Description |
|------|-------------|
| `test_derive_video_id_rejects_nested_path` | Call `derive_video_id("uploads/subfolder/talk.mp3")`, assert `ValueError` is raised |
| `test_derive_video_id_flat_path_succeeds` | Call `derive_video_id("uploads/talk.mp3")`, assert returns `"talk"` |

---

## Fix 8 — embedding-endpoint: Tests and API Key Guard

**Files:**
- `modules/embedding-endpoint/src/handlers/embed_text.py`
- `modules/embedding-endpoint/tests/unit/test_embed_text.py` *(new file)*
- `modules/embedding-endpoint/tests/conftest.py` *(new file)*
- `modules/embedding-endpoint/tests/__init__.py` *(new file)*

### 8a — Guard Empty API Key at Startup

If `API_KEY` is unset, `_api_key = ""` and a request with `x-api-key: ` (empty string) passes the check.

**Change:** Add a module-level guard that raises `ValueError` at cold start if `_api_key` is empty:

```python
_api_key = os.environ.get("API_KEY", "")
if not _api_key:
    raise ValueError("API_KEY environment variable must be set")
```

In production, Terraform always sets a 32-char random key, so this guard will never trigger in a correctly deployed environment. It catches misconfigured deployments immediately rather than silently.

### 8b — Add Unit Tests

**`modules/embedding-endpoint/tests/conftest.py`:**

Fixtures follow the same pattern as other modules: `aws_credentials` fixture sets fake env vars, `mock_aws_services` mocks Bedrock.

**`modules/embedding-endpoint/tests/unit/test_embed_text.py`:**

| Test | Description |
|------|-------------|
| `test_valid_request_returns_200` | Send valid JSON body with `text` field and correct `x-api-key`, verify 200 with `embedding` in response |
| `test_missing_api_key_returns_401` | Omit `x-api-key` header, verify 401 |
| `test_wrong_api_key_returns_401` | Send wrong API key, verify 401 |
| `test_missing_text_field_returns_400` | Send body without `text`, verify 400 |
| `test_empty_text_returns_400` | Send body with `text: ""`, verify 400 |
| `test_malformed_json_returns_400` | Send non-JSON body, verify 400 |
| `test_bedrock_error_returns_500` | Mock Bedrock raising `ClientError`, verify 500 with `{"error": "internal error"}` |

---

## Fix 9 — URL-Encode Credentials in Migration Connection String

**File:** `modules/migration-module/src/handlers/run_migrations.py`

Passwords containing `@`, `/`, `:`, or `?` corrupt the f-string connection URL. This causes a silent connection failure at deployment time.

**Change:** Apply `urllib.parse.quote_plus` to username and password before embedding them in the URL:

```python
from urllib.parse import quote_plus

username = quote_plus(secret["username"])
password = quote_plus(secret["password"])
connection_url = (
    f"postgresql+psycopg2://{username}:{password}"
    f"@{secret['host']}:{secret['port']}/{db_name}"
)
```

**Tests to add in `modules/migration-module/tests/unit/test_run_migrations.py`** *(new file)*:

| Test | Description |
|------|-------------|
| `test_special_chars_in_password_encoded` | Mock Secrets Manager returning a password containing `@`, verify connection URL has `%40` |
| `test_special_chars_in_username_encoded` | Same for username |

---

## Cross-Cutting Improvements (Lower Priority)

These improve maintainability but are not blocking issues. Implement after the Critical and Required fixes are merged.

### C1 — Extract Shared DB Connection Utility

`get_db_connection()` is copy-pasted verbatim between `embedding_service.py` and `retrieval_service.py`. Extract to `modules/shared/db.py` or a per-module `src/utils/db.py` that both services import. Include `conn.rollback()` in the exception path of `store_embedding` / any cursor execute call.

### C2 — Extract Shared Bedrock Embedding Utility

`generate_embedding()` is identical in both `EmbeddingService` and `RetrievalService`. Both call `bedrock-runtime` with the same model ID and dimensions. Extract to a shared utility function.

### C3 — DRY Test Fixtures

The `aws_credentials` and `mock_aws_services` fixtures are copy-pasted across all `conftest.py` files. Add a root-level `tests/conftest.py` with a shared `aws_credentials` fixture. Module-level `conftest.py` files extend with module-specific mocks only.

### C4 — Pin Dependency Versions

All `requirements.txt` and `dev-requirements.txt` files list packages without version pins. Run `pip freeze` in each module's venv and commit pinned output to prevent silent breakage on fresh deploys.

---

## Implementation Checklist

### Critical (block production deploy)

- [ ] 1. Delete `aws_lambda_permission.embed_text_public_invoke` from `infra/environments/dev/main.tf`
- [ ] 2. Run `terraform plan` — verify the permission removal is the only change
- [ ] 3. Remove `try/except` from `modules/transcribe-module/src/handlers/start_transcription.py`
- [ ] 4. Remove `try/except` from `modules/transcribe-module/src/handlers/check_transcription.py`
- [ ] 5. Add `enable_deletion_protection` variable to `infra/modules/aurora-vectordb/variables.tf`
- [ ] 6. Update Aurora cluster block to gate `skip_final_snapshot` and `deletion_protection` on the new variable
- [ ] 7. Update Secrets Manager secret block to gate `recovery_window_in_days` on the new variable
- [ ] 8. Add inline warning comments to both resource blocks
- [ ] 9. Run `terraform plan` — verify no resource changes

### Required (block merge)

- [ ] 10. Add `try/except json.JSONDecodeError` in `_parse_post_body` in `question.py`
- [ ] 11. Add handler tests for malformed JSON → 400 in `test_question_handler.py`
- [ ] 12. Add `similarity_threshold` to all four SQL query constants in `retrieval_service.py`
- [ ] 13. Remove Python-level similarity filter from `search_similar`
- [ ] 14. Add/update retrieval service tests for threshold pushed into SQL
- [ ] 15. Add `LIMIT 500` to `LIST_VIDEOS_SQL` in `retrieval_service.py`
- [ ] 16. Add `/` validation and `ValueError` to `derive_video_id` in `transcribe_service.py`
- [ ] 17. Add `test_derive_video_id_rejects_nested_path` and `test_derive_video_id_flat_path_succeeds`
- [ ] 18. Add `if not _api_key: raise ValueError(...)` to `modules/embedding-endpoint/src/handlers/embed_text.py`
- [ ] 19. Create `modules/embedding-endpoint/tests/__init__.py`
- [ ] 20. Create `modules/embedding-endpoint/tests/conftest.py` with `aws_credentials` fixture
- [ ] 21. Create `modules/embedding-endpoint/tests/unit/test_embed_text.py` with all 7 test cases
- [ ] 22. Add `from urllib.parse import quote_plus` and encode credentials in `run_migrations.py`
- [ ] 23. Create `modules/migration-module/tests/unit/test_run_migrations.py` with credential encoding tests

### Verify all tests pass

- [ ] 24. `cd modules/transcribe-module && python -m pytest tests/ -v`
- [ ] 25. `cd modules/question-endpoint && python -m pytest tests/ -v`
- [ ] 26. `cd modules/embedding-endpoint && python -m pytest tests/ -v`
- [ ] 27. `cd modules/migration-module && python -m pytest tests/ -v`

---

## Verification

### Infrastructure

```bash
cd infra/environments/dev

# Confirm permission removal and variable addition are the only changes
terraform plan -var="aurora_master_password=YourPassword123!"

# Confirm embed_text_public_invoke is gone from Lambda policy
aws lambda get-policy \
  --function-name $(terraform output -raw embed_text_function_name) \
  --query 'Policy' --output text | python3 -m json.tool
# Expected: No Statement with Action "lambda:InvokeFunction" and Principal "*"
```

### Transcription pipeline

Deploy a test Step Function execution with an unsupported file type (e.g., `.txt`). Confirm the execution transitions to `TranscriptionFailed` state rather than looping in `WaitForTranscription`.

### Question endpoint

```bash
cd modules/question-endpoint

# Malformed JSON → 400
python -c "
import json
from src.handlers.question import handler
event = {'resource': '/ask', 'httpMethod': 'POST', 'headers': {}, 'body': 'not-json', 'queryStringParameters': None, 'pathParameters': None}
print(handler(event, None))
"
# Expected: {'statusCode': 400, ...}
```

### Embedding endpoint

```bash
cd modules/embedding-endpoint
python -m pytest tests/ -v
# Expected: All 7 new tests pass
```

### Migration module

```bash
cd modules/migration-module
python -m pytest tests/ -v
# Expected: Credential encoding tests pass
```

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| No `lambda:InvokeFunction` for `principal="*"` | `aws lambda get-policy` shows no such statement |
| Step Functions pipeline fails fast on bad input | Execution reaches `TranscriptionFailed` state, not infinite loop |
| Deletion protection gated by variable | `terraform plan` with `enable_deletion_protection=true` shows final snapshot enabled |
| Malformed JSON body returns 400 | Handler test + curl to deployed endpoint |
| Similarity threshold applied in SQL | Test asserts threshold in SQL params; no Python-level filter |
| `LIST_VIDEOS_SQL` has `LIMIT 500` | Code review confirms SQL constant |
| Nested S3 key raises `ValueError` in transcription | Unit test `test_derive_video_id_rejects_nested_path` passes |
| Empty `API_KEY` raises at cold start | Module-level `ValueError` raised when env var absent |
| All 7 embedding-endpoint tests pass | `python -m pytest tests/ -v` in `modules/embedding-endpoint/` |
| Special-char passwords URL-encoded | Unit test `test_special_chars_in_password_encoded` passes |
| All existing tests still pass | Full test run across all modules green |
