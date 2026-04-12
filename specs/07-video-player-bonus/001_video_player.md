# Video Playback (Bonus)

**Deliverable:** A `GET /videos/{video_id}/presign` JSON endpoint on the existing Question API that returns a pre-signed S3 URL for the source media file, plus a new `watch_video_segment` MCP tool that calls this endpoint and opens the video directly in the user's browser at the correct timestamp using the Media Fragments URI `#t=` spec. The user asks a question in Cursor, gets transcript results, then says "play that clip" — and their browser opens the video at the exact moment.

---

## Overview

1. Add S3 read permissions and `MEDIA_BUCKET` env var to the question Lambda
2. Add a `GET /videos/{video_id}/presign` route (JSON response) to the question handler
3. Add the route to the API Gateway Terraform module
4. Add a `presign` method to the MCP server's `ApiClient`
5. Add a `watch_video_segment` MCP tool that calls presign and opens the browser
6. Write unit tests for both the endpoint and the MCP tool
7. Verify end-to-end: ask a question in Cursor → invoke `watch_video_segment` → browser plays from correct timestamp

---

## Prerequisites

- [ ] Stage 5 (Retrieval / Question Service) is complete and verified
- [ ] Stage 6 (MCP Server) is complete and verified
- [ ] API Gateway is deployed with the question Lambda behind it
- [ ] Media files exist in S3 at `uploads/{video_id}.mp4` (or `.mp3`)
- [ ] Aurora `video_chunks` table is populated with `source_s3_key`, `start_time`, `end_time` columns

---

## Architecture Context

```
Cursor IDE
    │
    │ "play that clip"
    │
    ▼
MCP Server (local)                                       <<< EXTENDED
    │
    │  1. GET /videos/{video_id}/presign (httpx)
    │
    ▼
API Gateway REST API
    │
    ├── POST /ask                         (existing)
    ├── POST /videos/{video_id}/ask       (existing)
    ├── GET  /health                      (existing)
    ├── GET  /videos                      (existing)
    └── GET  /videos/{video_id}/presign   <<< NEW
                    │
                    ▼
        Question Lambda (VPC-attached)    <<< EXTENDED
                    │
                ┌───┴───┐
                │       │
                ▼       ▼
          Aurora      S3
        (resolve    (pre-sign
         s3 key)     URL)

    2. webbrowser.open(presigned_url#t=start_time)
                    │
                    ▼
            Default Browser
            (plays video at timestamp via native player)
```

The presign endpoint reuses the existing question Lambda. Two additions to the Lambda:
1. An S3 client with `s3:GetObject` permission to generate pre-signed URLs
2. A handler route that queries Aurora for the `source_s3_key` and returns the pre-signed URL

The MCP server gets a new tool that ties the flow together — no HTML templates, no custom player.

---

## Why No Custom HTML Player

Chrome, Firefox, and Safari all have built-in video players when navigating directly to a video URL. The Media Fragments URI spec (`url#t=120`) is supported across all modern browsers for temporal seeking. The `#` fragment is client-side only — it never reaches S3, so it does not interfere with the pre-signed URL signature.

S3 supports HTTP `Range` requests (returns `206 Partial Content`), which Chrome requires for seeking in remote videos. This means `presigned_url#t=120` works out of the box: the browser opens its native player and seeks to 120 seconds.

The tradeoff: no metadata display (title, speaker) in the player UI. The user sees Chrome's bare video player. For a bonus workshop module, this is acceptable — the "wow" is that the right moment plays, not the styling.

---

## User Flow

1. User asks a question in Cursor via MCP → `ask_video_question` returns results with `video_id`, `start_time`, `chunk_id`
2. User says "play that clip" (or similar)
3. Cursor invokes `watch_video_segment(video_id="hello-my_name_is_wes", start_time=234.5)`
4. MCP tool calls `GET /videos/hello-my_name_is_wes/presign` → gets pre-signed S3 URL
5. MCP tool calls `webbrowser.open(f"{presigned_url}#t=234.5")`
6. Browser opens and plays the video from 3:54

---

## API Contract

### GET /videos/{video_id}/presign

Returns a JSON object with a pre-signed S3 URL for the video's source media file. The API key is required (same as all other routes).

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `chunk_id` | `string` | No | `null` | If provided, response includes the chunk's `start_time` and `end_time` |

**Response (200):**

```json
{
    "video_id": "hello-my_name_is_wes",
    "presigned_url": "https://production-rag-media-123456.s3.amazonaws.com/uploads/hello-my_name_is_wes.mp3?X-Amz-...",
    "expires_in": 3600,
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "speaker": "Wesley Reisz",
    "title": "Building RAG Systems"
}
```

When `chunk_id` is provided and found:

```json
{
    "video_id": "hello-my_name_is_wes",
    "presigned_url": "https://...",
    "expires_in": 3600,
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "speaker": "Wesley Reisz",
    "title": "Building RAG Systems",
    "start_time": 234.5,
    "end_time": 279.8
}
```

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 404 | `video_id` not found in `video_chunks` | `{"error": "video not found"}` |
| 404 | `chunk_id` provided but not found | `{"error": "chunk not found"}` |
| 500 | S3 pre-sign failure or other error | `{"error": "internal error"}` |

---

## Pre-signed URL Generation

```python
s3_client.generate_presigned_url(
    "get_object",
    Params={"Bucket": bucket_name, "Key": source_s3_key},
    ExpiresIn=3600,
)
```

The pre-signed URL allows the browser to stream the media directly from S3 without making the bucket public. The URL expires after 1 hour.

Pre-signed URLs generated inside a VPC-attached Lambda use the regional S3 endpoint by default. The URL works from any client with internet access — no VPC endpoint is needed for the browser's request to S3.

---

## S3 Key Resolution

The handler queries Aurora for the `source_s3_key` rather than constructing it by convention. This is resilient to different file extensions (`.mp4`, `.mp3`, `.webm`).

**Video lookup:**

```sql
SELECT DISTINCT source_s3_key, speaker, title
FROM video_chunks
WHERE video_id = %s
LIMIT 1
```

**Chunk lookup** (when `chunk_id` is provided):

```sql
SELECT source_s3_key, video_id, speaker, title, start_time, end_time
FROM video_chunks
WHERE chunk_id = %s
LIMIT 1
```

---

## MP4 Fast-Start Consideration

For MP4 files, the `moov` atom (metadata) must be at the beginning of the file for seeking to work. If it is at the end, the browser must download the entire file before playback starts and `#t=` seeking will not work until then.

This spec does **not** add an FFmpeg processing step. Most modern recording tools place the `moov` atom first by default. If participants encounter issues, re-encode with:

```bash
ffmpeg -i input.mp4 -movflags +faststart -c copy output.mp4
```

---

## Resources

### Part A: Handler Changes (Question Endpoint)

**File:** `modules/question-endpoint/src/handlers/question.py`

Add one new route and a module-level S3 client.

**Module-level additions:**

```python
import os
s3_client = boto3.client("s3")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
```

**New route in `handler(event, context)`:**

```python
if resource == "/videos/{video_id}/presign":
    return _handle_presign(event)
```

**`_handle_presign` function:**

1. Extract `video_id` from `event["pathParameters"]["video_id"]`
2. Read `chunk_id` from `event["queryStringParameters"]` (may be `None`)
3. If `chunk_id` is provided:
   a. Query Aurora for chunk metadata (SQL above)
   b. If no row, return 404 `{"error": "chunk not found"}`
   c. Build response with `start_time`, `end_time`
4. Else:
   a. Query Aurora for video metadata (SQL above)
   b. If no row, return 404 `{"error": "video not found"}`
5. Generate pre-signed URL: `s3_client.generate_presigned_url("get_object", Params={"Bucket": MEDIA_BUCKET, "Key": source_s3_key}, ExpiresIn=3600)`
6. Return JSON response with `_response()` helper (same as existing routes)

**Service layer:** Add two methods to `RetrievalService`:

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `get_video_metadata(video_id)` | video_id string | `dict` or `None` | Query Aurora for `source_s3_key`, `speaker`, `title` |
| `get_chunk_metadata(chunk_id)` | chunk_id string | `dict` or `None` | Query Aurora for `source_s3_key`, `video_id`, `speaker`, `title`, `start_time`, `end_time` |

These follow the same try/except pattern as `list_videos` and `search_similar`: get connection, execute, return dict or `None`, reset `self._db_conn = None` on error.

**File:** `modules/question-endpoint/src/services/retrieval_service.py`

Add after the existing SQL constants:

```python
VIDEO_METADATA_SQL = """SELECT DISTINCT source_s3_key, speaker, title
FROM video_chunks
WHERE video_id = %s
LIMIT 1"""

CHUNK_METADATA_SQL = """SELECT source_s3_key, video_id, speaker, title, start_time, end_time
FROM video_chunks
WHERE chunk_id = %s
LIMIT 1"""
```

---

### Part B: API Gateway Terraform Changes

**File:** `infra/modules/api-gateway/main.tf`

Add one new resource, method, and integration for the presign route.

| Resource | Path | Method | Integration |
|----------|------|--------|-------------|
| `aws_api_gateway_resource.video_presign` | `/videos/{video_id}/presign` | GET | Lambda proxy (`AWS_PROXY`) |

The `video_presign` resource is a child of the existing `aws_api_gateway_resource.video_id` resource (which represents `/videos/{video_id}`). The `path_part` is `"presign"`.

The method uses `authorization = "NONE"`, `api_key_required = true`, and Lambda proxy integration — same pattern as all other routes.

**Update the deployment triggers** to include the new resource, method, and integration hashes so that `terraform apply` redeploys the API stage.

---

### Part C: Lambda IAM and Environment Variable Changes

**File:** `infra/environments/dev/main.tf`

**New IAM permission** (add to the question Lambda's policy):

```json
{
    "Effect": "Allow",
    "Action": ["s3:GetObject"],
    "Resource": "arn:aws:s3:::${media_bucket_name}/uploads/*"
}
```

This scopes S3 read access to the `uploads/` prefix only.

**New environment variable:**

| Variable | Value | Description |
|----------|-------|-------------|
| `MEDIA_BUCKET` | `module.s3_media.bucket_name` | S3 bucket name for generating pre-signed URLs |

---

### Part D: MCP Server — API Client Addition

**File:** `modules/mcp-server/src/api_client.py`

Add one new method to the existing `ApiClient` class:

| Method | Input | HTTP Call | Returns |
|--------|-------|-----------|---------|
| `async presign(video_id, chunk_id=None)` | video_id string, optional chunk_id string | `GET /videos/{video_id}/presign` with optional `?chunk_id=X` query param and `x-api-key` header | `dict` (parsed JSON response) |

The method uses the existing `_get` helper but needs to support query parameters. Since `_get` doesn't currently support query params, either:

**Option 1 (simpler):** Build the path with the query string inline:

```python
async def presign(self, video_id: str, chunk_id: str | None = None) -> dict[str, Any]:
    path = f"/videos/{video_id}/presign"
    if chunk_id:
        path += f"?chunk_id={chunk_id}"
    return await self._get(path)
```

**Option 2:** Add a `params` argument to `_get`. This is cleaner but touches existing code.

Use Option 1 to minimize changes to existing code.

---

### Part E: MCP Server — New Tool

**File:** `modules/mcp-server/src/tools.py`

Add one new tool function and one new import:

```python
import webbrowser
```

**New tool:**

```python
@mcp.tool
async def watch_video_segment(video_id: str, start_time: float = 0) -> str:
    """Open a video in the browser, seeking to a specific timestamp. Use this after asking a question to watch the relevant video segment."""
```

**Tool behavior:**

1. Validate: `video_id` must be non-empty, `start_time` must be non-negative
2. Get settings via `get_settings()`
3. Create `ApiClient`, call `presign(video_id)`
4. Extract `presigned_url` from response
5. Build playback URL: `f"{presigned_url}#t={start_time}"` (if `start_time > 0`)
6. Call `webbrowser.open(playback_url)`
7. Return a formatted confirmation string:

```
## Now Playing

**Title:** Building RAG Systems
**Speaker:** Wesley Reisz
**Starting at:** 3:54

Opened in your default browser. The video will play from the specified timestamp.
```

**Error handling:**

- If `video_id` is empty → raise `ValueError("Video ID cannot be empty.")`
- If `start_time` is negative → raise `ValueError("Start time must be non-negative.")`
- If the presign call fails (404, network error) → the `ApiClient` error handling already converts these to `RuntimeError`, which FastMCP surfaces to the user

**Time formatting helper:**

Add a `_format_time(seconds)` function to convert float seconds to `m:ss` format:

```python
def _format_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"
```

---

### Part F: Update `__all__` Export

**File:** `modules/mcp-server/src/tools.py`

Update the `__all__` list:

```python
__all__ = ["mcp", "ask_video_question", "list_indexed_videos", "search_by_speaker", "watch_video_segment"]
```

---

### Part G: Unit Tests — Question Endpoint

**File:** `modules/question-endpoint/tests/unit/test_retrieval_service.py`

Add tests for the new service methods:

| Test | Description |
|------|-------------|
| `test_get_video_metadata_returns_dict` | Mock psycopg2 cursor with fake row, call `get_video_metadata("test-video")`, verify returned dict has `source_s3_key`, `speaker`, `title` |
| `test_get_video_metadata_not_found` | Mock cursor returning no rows, verify returns `None` |
| `test_get_chunk_metadata_returns_dict` | Mock cursor, call `get_chunk_metadata("test-chunk-001")`, verify dict has `source_s3_key`, `video_id`, `speaker`, `title`, `start_time`, `end_time` |
| `test_get_chunk_metadata_not_found` | Mock cursor returning no rows, verify returns `None` |
| `test_handler_presign_returns_url` | Mock service + S3, send GET `/videos/{video_id}/presign` event, verify 200 JSON response with `presigned_url` |
| `test_handler_presign_with_chunk_id` | Send event with `queryStringParameters: {"chunk_id": "test-chunk-001"}`, verify response includes `start_time` and `end_time` |
| `test_handler_presign_video_not_found` | Mock metadata returning `None`, verify 404 with `{"error": "video not found"}` |
| `test_handler_presign_chunk_not_found` | Mock chunk metadata returning `None`, verify 404 with `{"error": "chunk not found"}` |

**New conftest fixture:**

| Fixture | Description |
|---------|-------------|
| `sample_presign_event` | API Gateway proxy event for `GET /videos/{video_id}/presign` with `pathParameters: {"video_id": "hello-my_name_is_wes"}` and `queryStringParameters: null` |
| `sample_presign_with_chunk_event` | Same but with `queryStringParameters: {"chunk_id": "hello-my_name_is_wes-chunk-003"}` |

---

### Part H: Unit Tests — MCP Server

**File:** `modules/mcp-server/tests/unit/test_api_client.py`

| Test | Description |
|------|-------------|
| `test_presign_sends_correct_request` | Mock `GET /videos/v1/presign`, call `presign("v1")`, verify request path and `x-api-key` header |
| `test_presign_with_chunk_id` | Mock `GET /videos/v1/presign?chunk_id=v1-chunk-001`, call `presign("v1", chunk_id="v1-chunk-001")`, verify query param in request URL |
| `test_presign_404_raises_runtime_error` | Mock 404 response, verify `RuntimeError` |

**File:** `modules/mcp-server/tests/unit/test_tools.py`

| Test | Description |
|------|-------------|
| `test_watch_video_segment_opens_browser` | Mock `ApiClient.presign` and `webbrowser.open`, call tool, verify `webbrowser.open` called with presigned URL containing `#t=` fragment |
| `test_watch_video_segment_no_start_time` | Mock presign, call with `start_time=0`, verify URL has no `#t=` fragment |
| `test_watch_video_segment_returns_confirmation` | Mock presign + browser, verify return string contains title, speaker, and formatted time |
| `test_watch_video_segment_empty_video_id_raises` | Call with empty `video_id`, verify `ValueError` |
| `test_watch_video_segment_negative_start_time_raises` | Call with negative `start_time`, verify `ValueError` |

---

## Implementation Checklist

- [ ] 1. Add `VIDEO_METADATA_SQL`, `CHUNK_METADATA_SQL` constants and `get_video_metadata`, `get_chunk_metadata` methods to `modules/question-endpoint/src/services/retrieval_service.py`
- [ ] 2. Add `s3_client`, `MEDIA_BUCKET`, `_handle_presign` function, and `/videos/{video_id}/presign` route to `modules/question-endpoint/src/handlers/question.py`
- [ ] 3. Add `MEDIA_BUCKET` environment variable to the question Lambda in `infra/environments/dev/main.tf`
- [ ] 4. Add `s3:GetObject` permission (scoped to `uploads/*`) to the question Lambda IAM policy in `infra/environments/dev/main.tf`
- [ ] 5. Add `video_presign` resource, method, and integration to `infra/modules/api-gateway/main.tf`
- [ ] 6. Update API Gateway deployment triggers to include the new resource/method/integration
- [ ] 7. Add presign endpoint tests to `modules/question-endpoint/tests/unit/test_retrieval_service.py`
- [ ] 8. Add `sample_presign_event` fixture to `modules/question-endpoint/tests/conftest.py`
- [ ] 9. Add `presign` method to `modules/mcp-server/src/api_client.py`
- [ ] 10. Add `watch_video_segment` tool and `_format_time` helper to `modules/mcp-server/src/tools.py`
- [ ] 11. Update `__all__` in `tools.py`
- [ ] 12. Add presign tests to `modules/mcp-server/tests/unit/test_api_client.py`
- [ ] 13. Add `watch_video_segment` tests to `modules/mcp-server/tests/unit/test_tools.py`
- [ ] 14. Run question-endpoint unit tests — all pass
- [ ] 15. Run MCP server unit tests — all pass
- [ ] 16. Run `terraform plan && terraform apply` in `infra/environments/dev/`
- [ ] 17. Verify: `GET /videos/{video_id}/presign` returns JSON with valid pre-signed URL
- [ ] 18. Verify: `watch_video_segment` opens browser and video plays from correct timestamp

---

## Verification

### Step 1: Run question-endpoint unit tests

```bash
cd modules/question-endpoint
source .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
python -m pytest tests/ -v
deactivate
```

Expected: All tests pass (existing + new presign tests).

### Step 2: Run MCP server unit tests

```bash
cd modules/mcp-server
source .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
python -m pytest tests/ -v
deactivate
```

Expected: All tests pass (existing + new watch_video_segment tests).

### Step 3: Deploy

```bash
cd infra/environments/dev
terraform plan -var="aurora_master_password=YourSecurePassword123!"
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 4: Get API URL and key

```bash
API_URL=$(terraform output -raw question_api_url)
API_KEY=$(terraform output -raw question_api_key)
```

### Step 5: Test presign endpoint

```bash
curl -s -H "x-api-key: $API_KEY" \
  "$API_URL/videos/hello-my_name_is_wes/presign" | python3 -m json.tool
```

Expected:

```json
{
    "video_id": "hello-my_name_is_wes",
    "presigned_url": "https://production-rag-media-...",
    "expires_in": 3600,
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "speaker": "Wesley Reisz",
    "title": "..."
}
```

### Step 6: Test presign with chunk_id

```bash
curl -s -H "x-api-key: $API_KEY" \
  "$API_URL/videos/hello-my_name_is_wes/presign?chunk_id=hello-my_name_is_wes-chunk-003" | python3 -m json.tool
```

Expected: Same as above, plus `start_time` and `end_time` fields.

### Step 7: Test pre-signed URL plays in browser

```bash
PRESIGNED_URL=$(curl -s -H "x-api-key: $API_KEY" \
  "$API_URL/videos/hello-my_name_is_wes/presign" | python3 -c "import sys,json; print(json.load(sys.stdin)['presigned_url'])")

open "${PRESIGNED_URL}#t=30"
```

Expected: Browser opens and plays the video from 30 seconds using its native player.

### Step 8: Verify S3 supports range requests

```bash
curl -H "Range: bytes=0-1023" -I "$PRESIGNED_URL"
```

Expected: Response includes `HTTP/1.1 206 Partial Content` and `Content-Range` header.

### Step 9: Test video not found

```bash
curl -s -H "x-api-key: $API_KEY" \
  "$API_URL/videos/nonexistent/presign" | python3 -m json.tool
```

Expected: `{"error": "video not found"}` with status 404.

### Step 10: Test from Cursor

1. Restart MCP server (to pick up new tool)
2. In Cursor chat, ask: "What videos are indexed?"
3. Then ask a question about the video content
4. Then say: "Play that clip" or "Watch the segment from result 1"
5. Expected: Cursor invokes `watch_video_segment`, browser opens with video at the correct timestamp

### Troubleshooting: MP4 won't seek / long buffering

If the video won't seek to the timestamp, the MP4 `moov` atom may be at the end of the file. Re-encode:

```bash
ffmpeg -i input.mp4 -movflags +faststart -c copy output.mp4
aws s3 cp output.mp4 s3://<bucket>/uploads/original.mp4
```

Verify `moov` position with:

```bash
ffprobe -v error -show_entries format_tags=major_brand input.mp4
```

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Presign route exists in API Gateway | `aws apigateway get-resources` shows `/videos/{video_id}/presign` |
| Presign route requires API key | `curl $API_URL/videos/test/presign` without `x-api-key` returns 403 |
| Lambda has S3 read permission | Lambda IAM policy includes `s3:GetObject` on `uploads/*` |
| Lambda has `MEDIA_BUCKET` env var | Lambda configuration shows `MEDIA_BUCKET` environment variable |
| `GET /presign` returns JSON | Response `Content-Type` is `application/json` with `presigned_url` field |
| Pre-signed URL is valid | Opening the URL streams the media file |
| Pre-signed URL supports range requests | `curl -H "Range: bytes=0-1023"` returns `206 Partial Content` |
| `#t=` seeking works | Opening `presigned_url#t=120` in Chrome starts playback at 2:00 |
| `chunk_id` returns timestamps | Adding `?chunk_id=X` includes `start_time` and `end_time` in response |
| Video not found returns 404 | Requesting a nonexistent `video_id` returns `{"error": "video not found"}` |
| MCP tool `watch_video_segment` exists | Tool appears in Cursor MCP panel |
| MCP tool opens browser | Invoking tool opens default browser with video at correct time |
| Existing routes still work | `POST /ask`, `GET /health`, `GET /videos` return expected responses |
| Existing MCP tools still work | `ask_video_question`, `list_indexed_videos`, `search_by_speaker` function correctly |
| Question-endpoint unit tests pass | `python -m pytest tests/ -v` in `modules/question-endpoint/` passes all tests |
| MCP server unit tests pass | `python -m pytest tests/ -v` in `modules/mcp-server/` passes all tests |
| Terraform plan is clean | `terraform plan` shows no pending changes after apply |
