# MCP Server & Cursor Integration

**Deliverable:** A local MCP server (using FastMCP and stdio transport) that exposes three tools — `ask_video_question`, `list_indexed_videos`, and `search_by_speaker` — calling the deployed Question Service API Gateway, so participants can query video knowledge directly from Cursor IDE.

---

## Overview

1. Create the `modules/mcp-server/` Python package with FastMCP server, tools, config, and prompts
2. Write unit tests using `respx` to mock HTTP calls to the Question API
3. Install and run the MCP server locally
4. Configure Cursor IDE to connect to the MCP server via `mcp.json`
5. Verify tools work from Cursor chat

---

## Prerequisites

- [ ] Stage 5 (Retrieval / Question Service) is complete and verified
- [ ] Question API Gateway is deployed and accessible (`POST /ask`, `GET /videos`, `GET /health`)
- [ ] API key is available via `terraform output -raw question_api_key`
- [ ] API URL is available via `terraform output -raw question_api_url`
- [ ] Python 3.11+ is installed locally with `pip` and `venv`

---

## Architecture Context

```
Cursor IDE (MCP Client)                                           <<< THIS STAGE
    │
    │ stdio (stdin/stdout)
    │
    ▼
MCP Server (local Python process)                                 <<< THIS STAGE
    │
    │ HTTPS (httpx)
    │
    ▼
API Gateway REST API (deployed in Stage 5)
    │
    ├── POST /ask ─────────────────────────────┐
    ├── GET  /videos ──────────────────────────┤
    └── GET  /health ──────────────────────────┤
                                               │
                                               ▼
                                   Question Lambda (VPC-attached)
                                               │
                                   ┌───────────┴───────────┐
                                   │                       │
                                   ▼                       ▼
                               Bedrock Titan V2      Aurora pgvector
```

The MCP server runs locally on the participant's machine. It does NOT connect directly to Aurora or Bedrock. All data access goes through the Question API Gateway endpoint deployed in Stage 5.

---

## Reference Implementation

The MCP server follows the same patterns as [wesreisz-tw/icsaet-demo](https://github.com/wesreisz-tw/icsaet-demo):

- **FastMCP** for server and tool registration (not the lower-level `mcp` SDK)
- **pydantic-settings** for configuration validation from environment variables
- **httpx** for HTTP calls to the API Gateway
- **stdio transport** for Cursor IDE communication
- **Prompts** for providing context to the AI assistant about available tools

---

## MCP Tools

### ask_video_question

Ask a natural language question about indexed video content and receive relevant transcript chunks.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `question` | `string` | Yes | — | Natural language question about video content |
| `top_k` | `integer` | No | `5` | Number of results to return (1–100) |

**Behavior:** Calls `POST /ask` on the Question API with `{"question": ..., "top_k": ...}` and `x-api-key` header.

**Output:** Formatted string containing the question, each result's text, similarity score, speaker, title, and timestamp range.

### list_indexed_videos

List all videos currently indexed in the system.

**Input:** None.

**Behavior:** Calls `GET /videos` on the Question API with `x-api-key` header.

**Output:** Formatted string listing each video's ID, title, speaker, and chunk count.

### search_by_speaker

Search across all content from a specific speaker.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `speaker` | `string` | Yes | — | Speaker name to filter by |
| `question` | `string` | Yes | — | Natural language question about speaker's content |
| `top_k` | `integer` | No | `5` | Number of results to return (1–100) |

**Behavior:** Calls `POST /ask` on the Question API with `{"question": ..., "top_k": ..., "filters": {"speaker": ...}}` and `x-api-key` header.

**Output:** Formatted string containing results filtered to the specified speaker.

---

## MCP Prompts

Three prompts provide context to the AI assistant about how to use the tools effectively.

| Prompt | Purpose |
|--------|---------|
| `video_knowledge_overview` | Explains what the video knowledge base contains and how to query it |
| `example_questions` | Provides sample questions participants can try |
| `formatting_guidance` | Tips for writing effective questions to get better results |

---

## Configuration

The MCP server reads configuration from environment variables, validated at startup via pydantic-settings.

| Environment Variable | Type | Required | Description |
|---------------------|------|----------|-------------|
| `API_ENDPOINT` | `string` | Yes | Question API base URL (e.g. `https://abc.execute-api.us-east-1.amazonaws.com/prod`) |
| `API_KEY` | `string` | Yes | API Gateway API key (from `terraform output -raw question_api_key`) |

If either variable is missing or invalid, the server prints a helpful error message to stderr and exits with code 1 (same pattern as the icsaet-demo reference).

---

## API Client

An `ApiClient` class encapsulates all HTTP communication with the Question API.

| Method | Input | HTTP Call | Returns |
|--------|-------|-----------|---------|
| `ask(question, top_k, speaker=None)` | question string, top_k int, optional speaker string | `POST /ask` with JSON body and `x-api-key` header | `dict` (parsed JSON response) |
| `list_videos()` | — | `GET /videos` with `x-api-key` header | `dict` (parsed JSON response) |
| `health()` | — | `GET /health` with `x-api-key` header | `dict` (parsed JSON response) |

**Error handling:**

| Exception | Behavior |
|-----------|----------|
| `httpx.TimeoutException` | Raise `RuntimeError` with timeout message |
| `httpx.HTTPStatusError` (401) | Raise `RuntimeError` with auth failure message |
| `httpx.HTTPStatusError` (400) | Raise `RuntimeError` with invalid request message |
| `httpx.HTTPStatusError` (other) | Raise `RuntimeError` with status code |
| `httpx.RequestError` | Raise `RuntimeError` with network error message |

The client uses a 30-second timeout and sets `x-api-key` header on every request.

---

## Resources

### Part A: Directory Structure

```
modules/mcp-server/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py
│   ├── tools.py
│   ├── config.py
│   ├── api_client.py
│   └── prompts.py
├── tests/
│   ├── __init__.py
│   └── unit/
│       ├── __init__.py
│       ├── test_config.py
│       ├── test_tools.py
│       └── test_api_client.py
├── requirements.txt
└── dev-requirements.txt
```

**Files to create:**

| File | Purpose |
|------|---------|
| `src/__init__.py` | Package marker with `__version__` |
| `src/__main__.py` | Entry point: configure logging, validate config, run `mcp.run()` |
| `src/server.py` | FastMCP server setup, register prompts |
| `src/tools.py` | Tool function definitions registered with `@mcp.tool()` |
| `src/config.py` | pydantic-settings `Settings` class with `API_ENDPOINT` and `API_KEY` |
| `src/api_client.py` | `ApiClient` class wrapping httpx calls to the Question API |
| `src/prompts.py` | Prompt string constants for `video_knowledge_overview`, `example_questions`, `formatting_guidance` |
| `requirements.txt` | Runtime dependencies |
| `dev-requirements.txt` | Test dependencies |
| All `__init__.py` files | Python package markers |

---

### Part B: Configuration (config.py)

Uses pydantic-settings `BaseSettings` with `SettingsConfigDict(case_sensitive=False, extra="ignore")`.

| Field | Type | Validation | Description |
|-------|------|------------|-------------|
| `api_endpoint` | `str` | `min_length=10`, must start with `http` | Question API base URL |
| `api_key` | `str` | `min_length=10` | API Gateway API key |

A `get_settings()` function with `@lru_cache` returns a singleton instance.

---

### Part C: API Client (api_client.py)

| Attribute | Description |
|-----------|-------------|
| `self.settings` | `Settings` instance |
| `self._client` | `httpx.Client(timeout=30.0, base_url=settings.api_endpoint)` |

All requests include `headers={"x-api-key": self.settings.api_key}`.

**`ask` method request body:**

Without speaker filter:

```json
{"question": "What is RAG?", "top_k": 5}
```

With speaker filter:

```json
{"question": "What is RAG?", "top_k": 5, "filters": {"speaker": "Jane Doe"}}
```

**`list_videos` method:** `GET /videos`, return parsed JSON.

**`health` method:** `GET /health`, return parsed JSON.

---

### Part D: Tools (tools.py)

Creates `mcp = FastMCP("video-knowledge")` at module level.

Each tool function:
1. Validates input (empty question raises `ValueError`)
2. Gets settings via `get_settings()`
3. Creates an `ApiClient` instance
4. Calls the appropriate API method
5. Formats the response as a human-readable string

**Tool output formatting:**

`ask_video_question` and `search_by_speaker` format each result as:

```
## Results for: "What is RAG?"

### Result 1 (similarity: 0.89)
**Speaker:** Jane Doe | **Title:** Building RAG Systems
**Time:** 234.5s – 279.8s

Error handling in production RAG systems requires...

---
```

`list_indexed_videos` formats as:

```
## Indexed Videos

| Video ID | Title | Speaker | Chunks |
|----------|-------|---------|--------|
| hello-my_name_is_wes | Building RAG Systems | Jane Doe | 3 |
```

---

### Part E: Server and Entry Point

**server.py:** Imports `mcp` from `tools.py`, registers three prompts using `@mcp.prompt()` decorators. Exports `mcp`.

**__main__.py:**
1. Configure logging to stderr at INFO level
2. Log server version
3. Validate config via `get_settings()` — on `ValidationError`, print helpful error to stderr listing missing env vars, then `sys.exit(1)`
4. Call `mcp.run()`
5. Handle `KeyboardInterrupt` gracefully (exit 0)
6. Handle unexpected `Exception` (log, exit 1)

---

### Part F: Dependencies

**`requirements.txt`:**

```
fastmcp>=2.0.0
httpx>=0.24.0
pydantic-settings>=2.0.0
```

**`dev-requirements.txt`:**

```
pytest>=7.4.0
pytest-asyncio>=0.21.0
respx>=0.20.0
```

---

### Part G: Unit Tests

**`tests/unit/test_config.py`:**

| Test | Description |
|------|-------------|
| `test_valid_settings` | Set env vars, create `Settings`, verify fields |
| `test_missing_api_endpoint` | Omit `API_ENDPOINT`, verify `ValidationError` |
| `test_missing_api_key` | Omit `API_KEY`, verify `ValidationError` |
| `test_api_endpoint_too_short` | Set `API_ENDPOINT` to `"http"`, verify `ValidationError` |

**`tests/unit/test_api_client.py`:**

| Test | Description |
|------|-------------|
| `test_ask_sends_correct_request` | Mock `POST /ask`, call `ask()`, verify request body and headers |
| `test_ask_with_speaker_filter` | Mock `POST /ask`, call `ask()` with speaker, verify `filters.speaker` in body |
| `test_list_videos_sends_correct_request` | Mock `GET /videos`, call `list_videos()`, verify headers |
| `test_health_returns_status` | Mock `GET /health`, call `health()`, verify response |
| `test_ask_timeout_raises_runtime_error` | Mock timeout, call `ask()`, verify `RuntimeError` |
| `test_ask_401_raises_auth_error` | Mock 401 response, call `ask()`, verify `RuntimeError` with auth message |
| `test_ask_network_error_raises_runtime_error` | Mock `httpx.RequestError`, verify `RuntimeError` with network message |

**`tests/unit/test_tools.py`:**

| Test | Description |
|------|-------------|
| `test_ask_video_question_returns_formatted_results` | Mock `ApiClient.ask`, call tool function, verify formatted output contains question and results |
| `test_ask_video_question_empty_question_raises` | Call with empty question, verify `ValueError` |
| `test_list_indexed_videos_returns_formatted_table` | Mock `ApiClient.list_videos`, call tool function, verify markdown table output |
| `test_search_by_speaker_passes_speaker_filter` | Mock `ApiClient.ask`, call tool function with speaker, verify speaker passed to API |

**Fixture pattern:** Use `respx` to mock httpx requests at the HTTP level. Use `monkeypatch` to set environment variables before creating `Settings`.

---

### Part H: Cursor IDE Configuration

After the MCP server is installed, add to Cursor MCP settings (`.cursor/mcp.json` or via Cursor Settings > MCP):

```json
{
  "mcpServers": {
    "video-knowledge": {
      "command": "python",
      "args": ["-m", "src"],
      "cwd": "<absolute-path-to>/modules/mcp-server",
      "env": {
        "API_ENDPOINT": "https://<api-gateway-id>.execute-api.us-east-1.amazonaws.com/prod",
        "API_KEY": "<question-api-key>"
      }
    }
  }
}
```

Get the values from Terraform:

```bash
cd infra/environments/dev
terraform output -raw question_api_url    # → API_ENDPOINT
terraform output -raw question_api_key    # → API_KEY
```

---

## Implementation Checklist

- [ ] 1. Create `modules/mcp-server/requirements.txt` with `fastmcp`, `httpx`, `pydantic-settings`
- [ ] 2. Create `modules/mcp-server/dev-requirements.txt` with `pytest`, `pytest-asyncio`, `respx`
- [ ] 3. Create all `__init__.py` files (`src/`, `tests/`, `tests/unit/`)
- [ ] 4. Create `modules/mcp-server/src/config.py` with `Settings` class and `get_settings()`
- [ ] 5. Create `modules/mcp-server/src/prompts.py` with three prompt constants
- [ ] 6. Create `modules/mcp-server/src/api_client.py` with `ApiClient` class
- [ ] 7. Create `modules/mcp-server/tests/unit/test_config.py`
- [ ] 8. Create `modules/mcp-server/tests/unit/test_api_client.py`
- [ ] 9. Create `modules/mcp-server/src/tools.py` with three `@mcp.tool()` functions
- [ ] 10. Create `modules/mcp-server/src/server.py` registering prompts
- [ ] 11. Create `modules/mcp-server/src/__main__.py` entry point
- [ ] 12. Create `modules/mcp-server/tests/unit/test_tools.py`
- [ ] 13. Run `pip install -r requirements.txt -r dev-requirements.txt && python -m pytest tests/ -v` — all tests pass
- [ ] 14. Configure Cursor MCP settings with `API_ENDPOINT` and `API_KEY`
- [ ] 15. Verify MCP server starts: `python -m src` (from `modules/mcp-server/`) logs startup and waits for stdio
- [ ] 16. Verify tools appear in Cursor MCP panel
- [ ] 17. Verify `ask_video_question` returns results from Cursor chat

---

## Verification

### Step 1: Install dependencies

```bash
cd modules/mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
```

### Step 2: Run unit tests

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

### Step 3: Verify config validation

```bash
python -m src
```

Expected (without env vars): Error message listing missing `API_ENDPOINT` and `API_KEY`, exit code 1.

### Step 4: Start with valid config

```bash
cd infra/environments/dev
API_URL=$(terraform output -raw question_api_url)
API_KEY=$(terraform output -raw question_api_key)

cd ../../../modules/mcp-server
API_ENDPOINT=$API_URL API_KEY=$API_KEY python -m src
```

Expected: Logs "Starting video-knowledge MCP Server" and waits for stdio input. Press Ctrl+C to stop.

### Step 5: Configure Cursor

Add to Cursor MCP settings:

```json
{
  "mcpServers": {
    "video-knowledge": {
      "command": "python",
      "args": ["-m", "src"],
      "cwd": "<absolute-path-to>/modules/mcp-server",
      "env": {
        "API_ENDPOINT": "<question_api_url value>",
        "API_KEY": "<question_api_key value>"
      }
    }
  }
}
```

### Step 6: Verify in Cursor

1. Open Cursor Settings > MCP — verify `video-knowledge` server shows green status
2. In Cursor chat, ask: "What videos are indexed in the knowledge base?"
   - Expected: Cursor invokes `list_indexed_videos` tool and returns a list of videos
3. Ask: "What is this video about?"
   - Expected: Cursor invokes `ask_video_question` and returns relevant transcript chunks with similarity scores
4. Ask: "What did Wesley Reisz say about RAG pipelines?"
   - Expected: Cursor invokes `search_by_speaker` with speaker filter

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| MCP server package exists | `ls modules/mcp-server/src/` shows `__main__.py`, `server.py`, `tools.py`, `config.py`, `api_client.py`, `prompts.py` |
| Config validation works | Running without env vars prints helpful error and exits 1 |
| Config accepts valid env vars | Running with valid `API_ENDPOINT` and `API_KEY` starts the server |
| Unit tests pass | `python -m pytest tests/ -v` passes all tests |
| `ask_video_question` tool works | Cursor chat invokes the tool and returns formatted results |
| `list_indexed_videos` tool works | Cursor chat invokes the tool and returns a video list |
| `search_by_speaker` tool works | Cursor chat invokes the tool with speaker filter |
| Prompts are registered | MCP server exposes `video_knowledge_overview`, `example_questions`, `formatting_guidance` |
| API key is sent on all requests | Requests include `x-api-key` header (verified by tests) |
| Error handling works | Timeout, auth failure, and network errors produce clear error messages |
| No Terraform resources needed | MCP server runs locally; no infra changes required |
