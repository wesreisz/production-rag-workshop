# MCP Server & Cursor Integration — Implementation Plan

**Goal:** Create a local MCP server Python package (`modules/mcp-server/`) using FastMCP and stdio transport that exposes three tools — `ask_video_question`, `list_indexed_videos`, `search_by_speaker` — calling the deployed Question Service API Gateway, with unit tests using `unittest.mock`, and Cursor IDE configuration via `.cursor/mcp.json`.

---

## New Files (15)

| # | File | Purpose |
|---|------|---------|
| 1 | `modules/mcp-server/requirements.txt` | Runtime deps: `fastmcp>=2.0.0`, `httpx>=0.24.0`, `pydantic-settings>=2.0.0` |
| 2 | `modules/mcp-server/dev-requirements.txt` | Test deps: `pytest>=7.4.0`, `pytest-asyncio>=0.21.0` |
| 3 | `modules/mcp-server/src/__init__.py` | Empty package marker (no `__version__` — matches other modules) |
| 4 | `modules/mcp-server/tests/__init__.py` | Empty package marker |
| 5 | `modules/mcp-server/tests/unit/__init__.py` | Empty package marker |
| 6 | `modules/mcp-server/src/config.py` | pydantic-settings `Settings` class + `get_settings()` with `@lru_cache` |
| 7 | `modules/mcp-server/src/prompts.py` | Three prompt string constants |
| 8 | `modules/mcp-server/src/api_client.py` | `ApiClient` class wrapping httpx async calls to Question API |
| 9 | `modules/mcp-server/src/server.py` | `mcp = FastMCP("video-knowledge")` + three `@mcp.prompt()` registrations |
| 10 | `modules/mcp-server/src/tools.py` | Three `@mcp.tool()` functions importing `mcp` from `server.py` |
| 11 | `modules/mcp-server/src/__main__.py` | Entry point: logging, config validation, `mcp.run()` |
| 12 | `modules/mcp-server/tests/unit/test_config.py` | 4 tests for Settings validation |
| 13 | `modules/mcp-server/tests/unit/test_api_client.py` | 7 tests for ApiClient HTTP behavior |
| 14 | `modules/mcp-server/tests/unit/test_tools.py` | 4 tests for tool functions |
| 15 | `.cursor/mcp.json` | Cursor IDE MCP server configuration |

## Files to Modify (0)

No existing files are modified. No Terraform changes — the MCP server runs locally.

---

## Architecture Decisions

**1. `unittest.mock.patch` + `MagicMock` for tests (deviation from spec).** The spec mentions `respx` in `dev-requirements.txt` but the rest of the project consistently uses `unittest.mock.patch` and `MagicMock` for all test mocking (embedding-module, question-endpoint). Following the project pattern: mock `httpx.AsyncClient` methods via `patch` rather than intercepting HTTP at transport level with `respx`. This means `respx` is dropped from `dev-requirements.txt`.

**2. Empty `src/__init__.py` (deviation from spec).** The spec says `__init__.py` should have `__version__`. Every other module in the project has empty `__init__.py` files. Keeping consistency — no version string.

**3. Async tool functions, sync `unittest.mock`.** The MCP tools call `ApiClient` async methods. Tests will use `AsyncMock` (from `unittest.mock`, Python 3.8+) to mock async coroutines. `pytest-asyncio` provides the `@pytest.mark.asyncio` decorator to run async test functions.

**4. Per-call `httpx.AsyncClient` lifecycle.** Each `ApiClient` method creates a fresh `httpx.AsyncClient` via `async with` context manager. This avoids managing client lifecycle across tool calls and matches the spec's "Option A".

**5. `get_settings()` with `@lru_cache` for singleton config.** pydantic-settings validates env vars once at import time. The `lru_cache` ensures a single `Settings` instance across all tool calls. Tests clear the cache via `get_settings.cache_clear()` in fixtures.

**6. Error handling in `ApiClient` translates httpx exceptions to `RuntimeError`.** All httpx-specific exceptions are caught and re-raised as `RuntimeError` with human-readable messages. Tool functions propagate these — FastMCP handles returning error responses to the MCP client.

**7. Prompts registered in `server.py`, not `prompts.py`.** `prompts.py` defines string constants only. `server.py` imports them and registers with `@mcp.prompt()` decorators. This separates content from registration.

**8. Cursor config uses venv Python path + `PYTHONPATH`.** Per spec notes from real-world testing: Cursor spawns MCP servers without venv activation, so `command` must point to `.venv/bin/python` directly. `PYTHONPATH` ensures `python -m src` resolves regardless of Cursor's working directory.

---

## Detailed Per-File Descriptions

### Part A: Dependencies and Package Structure

**`modules/mcp-server/requirements.txt`**
- `fastmcp>=2.0.0`
- `httpx>=0.24.0`
- `pydantic-settings>=2.0.0`

**`modules/mcp-server/dev-requirements.txt`**
- `pytest>=7.4.0`
- `pytest-asyncio>=0.21.0`

**3 empty `__init__.py` files** at: `src/`, `tests/`, `tests/unit/`

### Part B: Configuration (`src/config.py`)

**Class: `Settings(BaseSettings)`**
- `model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")`
- Field `api_endpoint`: type `str`, `min_length=10`, field validator that checks value starts with `"http"` (raise `ValueError` otherwise)
- Field `api_key`: type `str`, `min_length=10`

**Function: `get_settings()`**
- Decorated with `@lru_cache`
- Returns `Settings()` (reads from env vars)

Imports: `functools.lru_cache`, `pydantic_settings.BaseSettings`, `pydantic_settings.SettingsConfigDict`, `pydantic.field_validator`

### Part C: Prompts (`src/prompts.py`)

Three module-level string constants:

- `VIDEO_KNOWLEDGE_OVERVIEW` — `"This provides information on the video_knowledge mcp. It provides transcribed information on uploaded videos."`

- `EXAMPLE_QUESTIONS` — A string containing:
  - "What were the key takeaways of Wes Reisz talks?"
  - "What were the key things discussed in all of the talks?"

- `FORMATTING_GUIDANCE` — `"When presenting results from the video knowledge base, make suggestions for follow-up questions the user could ask to explore the topic further."`

### Part D: API Client (`src/api_client.py`)

**Class: `ApiClient`**

**Constructor:** `__init__(self, settings)`
- `self.settings = settings` (a `Settings` instance)

**Method: `async ask(question, top_k, speaker=None)`**
1. Build `payload = {"question": question, "top_k": top_k}`
2. If `speaker` is not None: `payload["filters"] = {"speaker": speaker}`
3. `async with httpx.AsyncClient(timeout=30.0, base_url=self.settings.api_endpoint) as client:`
4. `response = await client.post("/ask", json=payload, headers={"x-api-key": self.settings.api_key})`
5. `response.raise_for_status()`
6. `return response.json()`
7. Error handling wraps entire body in `try/except`:
   - `httpx.TimeoutException` → raise `RuntimeError("Request timed out after 30 seconds")`
   - `httpx.HTTPStatusError` with status 401 → raise `RuntimeError("Authentication failed — check API_KEY")`
   - `httpx.HTTPStatusError` with status 400 → raise `RuntimeError("Invalid request: {response.text}")`
   - `httpx.HTTPStatusError` other → raise `RuntimeError("API error: status {status_code}")`
   - `httpx.RequestError` → raise `RuntimeError("Network error: {exc}")`

**Method: `async list_videos()`**
1. Same `async with httpx.AsyncClient(...)` pattern
2. `response = await client.get("/videos", headers={"x-api-key": self.settings.api_key})`
3. `response.raise_for_status()`
4. `return response.json()`
5. Same error handling pattern

**Method: `async health()`**
1. Same pattern
2. `response = await client.get("/health", headers={"x-api-key": self.settings.api_key})`
3. Same error handling

Imports: `httpx`

### Part E: Server (`src/server.py`)

Module level:
1. `from fastmcp import FastMCP`
2. `from src.prompts import VIDEO_KNOWLEDGE_OVERVIEW, EXAMPLE_QUESTIONS, FORMATTING_GUIDANCE`
3. `mcp = FastMCP("video-knowledge")`
4. Three `@mcp.prompt()` decorated functions:
   - `video_knowledge_overview()` → returns `VIDEO_KNOWLEDGE_OVERVIEW`
   - `example_questions()` → returns `EXAMPLE_QUESTIONS`
   - `formatting_guidance()` → returns `FORMATTING_GUIDANCE`

The `mcp` object is imported by `tools.py` and `__main__.py`.

### Part F: Tools (`src/tools.py`)

Imports `mcp` from `src.server`, `get_settings` from `src.config`, `ApiClient` from `src.api_client`.

**`@mcp.tool()` — `async def ask_video_question(question: str, top_k: int = 5) -> str`**

Docstring: `"Ask a natural language question about indexed video content and receive relevant transcript chunks."`

1. If `not question or not question.strip()`: raise `ValueError("question must not be empty")`
2. `settings = get_settings()`
3. `client = ApiClient(settings)`
4. `data = await client.ask(question, top_k)`
5. Format output string:
   - Header: `## Results for: "{question}"\n\n`
   - If `data["results"]` is empty: `"No results found."`
   - For each result (1-indexed):
     - `### Result {i} (similarity: {similarity:.2f})\n`
     - `**Speaker:** {speaker} | **Title:** {title}\n`
     - `**Time:** {start_time}s – {end_time}s\n\n`
     - `{text}\n\n---\n`
6. Return the formatted string

**`@mcp.tool()` — `async def list_indexed_videos() -> str`**

Docstring: `"List all videos currently indexed in the system."`

1. `settings = get_settings()`
2. `client = ApiClient(settings)`
3. `data = await client.list_videos()`
4. Format output string:
   - Header: `## Indexed Videos\n\n`
   - Table header: `| Video ID | Title | Speaker | Chunks |\n|----------|-------|---------|--------|\n`
   - For each video in `data["videos"]`:
     - `| {video_id} | {title} | {speaker} | {chunk_count} |\n`
5. Return the formatted string

**`@mcp.tool()` — `async def search_by_speaker(speaker: str, question: str, top_k: int = 5) -> str`**

Docstring: `"Search across all content from a specific speaker."`

1. If `not question or not question.strip()`: raise `ValueError("question must not be empty")`
2. If `not speaker or not speaker.strip()`: raise `ValueError("speaker must not be empty")`
3. `settings = get_settings()`
4. `client = ApiClient(settings)`
5. `data = await client.ask(question, top_k, speaker=speaker)`
6. Same formatting as `ask_video_question` but header says: `## Results from {speaker} for: "{question}"\n\n`
7. Return the formatted string

### Part G: Entry Point (`src/__main__.py`)

1. `import logging`, `import sys`
2. Configure logging: `logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")`
3. `logger = logging.getLogger("mcp-server")`
4. `try:`
   - Import `get_settings` from `src.config` — call `get_settings()` to validate config at startup
   - `logger.info("Starting video-knowledge MCP Server")`
   - Import `mcp` from `src.server`
   - Import `src.tools` (side-effect: registers tool functions with `mcp`)
   - Call `mcp.run()`
5. `except ValidationError as e:` (from pydantic)
   - Print to stderr: `"Configuration error: ..."` listing which env vars are missing/invalid
   - `sys.exit(1)`
6. `except KeyboardInterrupt:`
   - `logger.info("Server stopped")`
   - `sys.exit(0)`
7. `except Exception as e:`
   - `logger.exception("Unexpected error")`
   - `sys.exit(1)`

Imports: `logging`, `sys`, `pydantic.ValidationError`

### Part H: Tests

All tests use `unittest.mock.patch`, `unittest.mock.MagicMock`, `unittest.mock.AsyncMock`. Tests follow AAA pattern with `# Arrange`, `# Act`, `# Assert` comments. Test classes group related tests.

**`tests/unit/test_config.py`** — 4 tests

| # | Test | Description |
|---|------|-------------|
| 1 | `test_valid_settings` | Use `monkeypatch.setenv` to set `API_ENDPOINT` (valid URL, >= 10 chars) and `API_KEY` (>= 10 chars). Create `Settings()`. Assert `settings.api_endpoint` and `settings.api_key` match. Call `get_settings.cache_clear()` in fixture teardown. |
| 2 | `test_missing_api_endpoint` | Only set `API_KEY`. Assert `Settings()` raises `ValidationError`. |
| 3 | `test_missing_api_key` | Only set `API_ENDPOINT`. Assert `Settings()` raises `ValidationError`. |
| 4 | `test_api_endpoint_too_short` | Set `API_ENDPOINT` to `"http"` (4 chars, below `min_length=10`). Assert `ValidationError`. |

Fixture: `clear_settings_cache` (autouse) — calls `get_settings.cache_clear()` before each test. Also use `monkeypatch.delenv` with `raising=False` to clear `API_ENDPOINT` and `API_KEY` before each test to avoid leaking between tests.

Imports: `pytest`, `pydantic.ValidationError`, `src.config.Settings`, `src.config.get_settings`

**`tests/unit/test_api_client.py`** — 7 tests

All tests are `async def` with `@pytest.mark.asyncio`. Each test creates a `Settings`-like mock (or uses `monkeypatch` to set env vars and create real `Settings`), then creates `ApiClient(settings)`.

Mocking strategy: `patch("httpx.AsyncClient")` — the patched class returns a mock async context manager. Configure `mock_client.__aenter__.return_value` to return a mock with `post`/`get` returning `AsyncMock` responses.

| # | Test | Description |
|---|------|-------------|
| 1 | `test_ask_sends_correct_request` | Mock `client.post` to return mock response with `.json()` returning `{"question": "...", "results": [...]}`. Call `await api_client.ask("What is RAG?", 5)`. Assert `client.post` called with `"/ask"`, `json={"question": "What is RAG?", "top_k": 5}`, headers containing `x-api-key`. |
| 2 | `test_ask_with_speaker_filter` | Same setup. Call `await api_client.ask("What is RAG?", 5, speaker="Jane Doe")`. Assert `json` payload includes `"filters": {"speaker": "Jane Doe"}`. |
| 3 | `test_list_videos_sends_correct_request` | Mock `client.get` to return mock response. Call `await api_client.list_videos()`. Assert `client.get` called with `"/videos"`, headers containing `x-api-key`. |
| 4 | `test_health_returns_status` | Mock `client.get` to return response with `.json()` returning `{"status": "healthy"}`. Call `await api_client.health()`. Assert result equals `{"status": "healthy"}`. |
| 5 | `test_ask_timeout_raises_runtime_error` | Mock `client.post` to raise `httpx.TimeoutException("timeout")`. Call `await api_client.ask(...)`. Assert `RuntimeError` raised with "timed out" in message. |
| 6 | `test_ask_401_raises_auth_error` | Mock `client.post` side-effect: call `response.raise_for_status()` that raises `httpx.HTTPStatusError` with 401 status. Assert `RuntimeError` with "Authentication" in message. |
| 7 | `test_ask_network_error_raises_runtime_error` | Mock `client.post` to raise `httpx.RequestError("connection failed")`. Assert `RuntimeError` with "Network error" in message. |

Helper: Create a `_make_mock_settings()` function that returns a `MagicMock` with `api_endpoint = "https://test-api.example.com/prod"` and `api_key = "test-api-key-12345"`.

Imports: `pytest`, `unittest.mock.patch`, `unittest.mock.MagicMock`, `unittest.mock.AsyncMock`, `httpx`, `src.api_client.ApiClient`

**`tests/unit/test_tools.py`** — 4 tests

All tests are `async def` with `@pytest.mark.asyncio`. Tests patch `src.tools.get_settings` and `src.tools.ApiClient` (or the specific import paths) to avoid real HTTP calls and real env var requirements.

| # | Test | Description |
|---|------|-------------|
| 1 | `test_ask_video_question_returns_formatted_results` | Patch `ApiClient` so `ask()` returns `{"question": "...", "results": [{"text": "...", "similarity": 0.89, "speaker": "Jane Doe", "title": "Building RAG", "start_time": 234.5, "end_time": 279.8}]}`. Call `await ask_video_question("What is RAG?", 5)`. Assert output contains `"Results for"`, `"0.89"`, `"Jane Doe"`, `"Building RAG"`. |
| 2 | `test_ask_video_question_empty_question_raises` | Call `await ask_video_question("", 5)`. Assert `ValueError` with "empty" in message. |
| 3 | `test_list_indexed_videos_returns_formatted_table` | Patch `ApiClient` so `list_videos()` returns `{"videos": [{"video_id": "vid-1", "title": "RAG Talk", "speaker": "Jane", "chunk_count": 3}]}`. Call `await list_indexed_videos()`. Assert output contains `"Indexed Videos"`, `"vid-1"`, `"RAG Talk"`, `"Jane"`, `"3"`. |
| 4 | `test_search_by_speaker_passes_speaker_filter` | Patch `ApiClient` so `ask()` returns results. Call `await search_by_speaker("Jane Doe", "What about RAG?", 5)`. Assert `ApiClient().ask` was called with `speaker="Jane Doe"`. |

Imports: `pytest`, `unittest.mock.patch`, `unittest.mock.MagicMock`, `unittest.mock.AsyncMock`, `src.tools.ask_video_question`, `src.tools.list_indexed_videos`, `src.tools.search_by_speaker`

### Part I: Cursor IDE Configuration (`.cursor/mcp.json`)

Create `.cursor/mcp.json` at project root:

Structure:
- `mcpServers.video-knowledge.command` → `/workspaces/production-rag/modules/mcp-server/.venv/bin/python`
- `mcpServers.video-knowledge.args` → `["-m", "src"]`
- `mcpServers.video-knowledge.cwd` → `/workspaces/production-rag/modules/mcp-server`
- `mcpServers.video-knowledge.env.PYTHONPATH` → `/workspaces/production-rag/modules/mcp-server`
- `mcpServers.video-knowledge.env.API_ENDPOINT` → placeholder `"<run: terraform output -raw question_api_url>"`
- `mcpServers.video-knowledge.env.API_KEY` → placeholder `"<run: terraform output -raw question_api_key>"`

---

## Risks / Assumptions

1. **`fastmcp>=2.0.0` API stability.** FastMCP v2 changed the API surface significantly from v1. The `@mcp.tool()` and `@mcp.prompt()` decorator patterns are based on the spec and PRD appendix D. If the installed version has different decorators, the registration will fail at import time — visible immediately on startup.

2. **`pytest-asyncio` mode configuration.** `pytest-asyncio>=0.21` requires either `asyncio_mode = "auto"` in `pyproject.toml` / `pytest.ini`, or explicit `@pytest.mark.asyncio` on each async test. Plan uses explicit markers to avoid needing a config file.

3. **Mocking `httpx.AsyncClient` context manager.** The `async with httpx.AsyncClient(...) as client` pattern requires the mock to implement `__aenter__` and `__aexit__`. Using `AsyncMock` for the context manager return value handles this. Tests must configure `mock_client_class.return_value.__aenter__.return_value` to get at the inner client mock.

4. **pydantic v2 `field_validator` syntax.** The plan uses `@field_validator("api_endpoint")` with `@classmethod` decorator (pydantic v2 style). If the environment has pydantic v1, this will fail. `pydantic-settings>=2.0.0` depends on pydantic v2, so this should be safe.

5. **`lru_cache` and test isolation.** `get_settings()` is cached via `@lru_cache`. Tests must call `get_settings.cache_clear()` before each test (via autouse fixture) to prevent settings from one test leaking into another.

6. **Cursor venv path is workspace-specific.** The `.cursor/mcp.json` uses `/workspaces/production-rag/...` which is correct for the devcontainer but would need updating for other environments. The plan uses placeholder values for `API_ENDPOINT` and `API_KEY` since they come from Terraform output.

7. **No `conftest.py` needed.** Unlike the Lambda modules which share fixtures (like `aws_credentials`), the MCP server tests are self-contained. Each test file manages its own mock setup. If common patterns emerge during execution, a `conftest.py` can be extracted, but is not planned.

---

## Implementation Checklist

### Phase 1: Package Structure and Dependencies (steps 1–3)

- [ ] 1. Create `modules/mcp-server/requirements.txt` with `fastmcp>=2.0.0`, `httpx>=0.24.0`, `pydantic-settings>=2.0.0`
- [ ] 2. Create `modules/mcp-server/dev-requirements.txt` with `pytest>=7.4.0`, `pytest-asyncio>=0.21.0`
- [ ] 3. Create 3 empty `__init__.py` files: `src/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`

### Phase 2: Config and Prompts — Tests First (steps 4–6)

- [ ] 4. Create `modules/mcp-server/src/config.py` — `Settings(BaseSettings)` with `api_endpoint` (str, min_length=10, must start with "http") and `api_key` (str, min_length=10), `SettingsConfigDict(case_sensitive=False, extra="ignore")`, `get_settings()` with `@lru_cache`
- [ ] 5. Create `modules/mcp-server/tests/unit/test_config.py` — 4 tests: `test_valid_settings`, `test_missing_api_endpoint`, `test_missing_api_key`, `test_api_endpoint_too_short`. Autouse fixture clears `lru_cache` and env vars.
- [ ] 6. Create `modules/mcp-server/src/prompts.py` — three string constants: `VIDEO_KNOWLEDGE_OVERVIEW`, `EXAMPLE_QUESTIONS`, `FORMATTING_GUIDANCE`

### Phase 3: API Client — Tests First (steps 7–8)

- [ ] 7. Create `modules/mcp-server/tests/unit/test_api_client.py` — 7 async tests mocking `httpx.AsyncClient`: correct request/headers, speaker filter, list_videos, health, timeout error, 401 error, network error
- [ ] 8. Create `modules/mcp-server/src/api_client.py` — `ApiClient` class with `async ask(question, top_k, speaker=None)`, `async list_videos()`, `async health()`. Per-call `httpx.AsyncClient` context manager, 30s timeout, `x-api-key` header, error handling translating httpx exceptions to `RuntimeError`

### Phase 4: Server and Tools — Tests First (steps 9–12)

- [ ] 9. Create `modules/mcp-server/src/server.py` — `mcp = FastMCP("video-knowledge")` at module level, three `@mcp.prompt()` functions returning constants from `prompts.py`
- [ ] 10. Create `modules/mcp-server/tests/unit/test_tools.py` — 4 async tests: formatted results, empty question raises, formatted table, speaker filter passed
- [ ] 11. Create `modules/mcp-server/src/tools.py` — import `mcp` from `server.py`, three `@mcp.tool()` async functions: `ask_video_question`, `list_indexed_videos`, `search_by_speaker`. Each validates input, creates `ApiClient`, calls API, formats response as markdown string
- [ ] 12. Create `modules/mcp-server/src/__main__.py` — configure logging to stderr, validate config via `get_settings()`, import `mcp` and `tools`, call `mcp.run()`. Handle `ValidationError` (exit 1), `KeyboardInterrupt` (exit 0), unexpected `Exception` (log, exit 1)

### Phase 5: Verify Tests Pass (step 13)

- [ ] 13. Create venv, install deps, run tests: `cd modules/mcp-server && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r dev-requirements.txt && python -m pytest tests/ -v` — all 15 tests pass

### Phase 6: Cursor IDE Configuration (step 14)

- [ ] 14. Create `.cursor/mcp.json` at project root with `video-knowledge` server entry: `command` pointing to `.venv/bin/python`, `args` of `["-m", "src"]`, `cwd`, `PYTHONPATH`, and placeholder `API_ENDPOINT`/`API_KEY` env vars

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
