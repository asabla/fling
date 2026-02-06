# Implementation Plan — fling

**Generated from**: `docs/plans/01_initial_implementation.md`
**Date**: 2026-02-06

---

## Decisions

| Decision | Choice |
|---|---|
| Scope | All 7 phases, 25 tasks |
| Python minimum | 3.12+ |
| Testing | pytest-httpx for HTTP mocking, tests alongside each module |
| Async strategy | Fully async core (httpx.AsyncClient throughout) |
| Build backend | uv_build |
| TUI mode | Read-only runner (no request editing) |
| Web CSS | pytailwindcss (no Node.js) |
| Scripting | Python-based response handlers |
| Prompt variables | CLI + Web; skip TUI; document the gap |
| Commits | One per task (25 commits) |
| CI | GitHub Actions |

---

## Phase 1: Project Scaffold and Core Parser

### Task 1.1 — Project initialization

- Update `pyproject.toml` with full config: all dependencies, optional extras (`tui`, `web`, `all`), `[project.scripts]` entry point, tool configs (ruff, pytest, mypy), `[build-system]` with `uv_build`
- Update `.python-version` to `3.12`
- Create full directory structure:
  ```
  src/fling/__init__.py
  src/fling/cli.py
  src/fling/core/__init__.py
  src/fling/core/models.py
  src/fling/core/parser.py
  src/fling/core/variables.py
  src/fling/core/executor.py
  src/fling/core/runner.py
  src/fling/core/environment.py
  src/fling/core/scripting.py
  src/fling/core/postman.py
  src/fling/tui/__init__.py
  src/fling/tui/app.py
  src/fling/tui/screens/
  src/fling/tui/widgets/
  src/fling/tui/styles/
  src/fling/web/__init__.py
  src/fling/web/app.py
  src/fling/web/routes/
  src/fling/web/templates/
  src/fling/web/static/
  tests/conftest.py
  tests/fixtures/
  ```
- Create `src/fling/cli.py` with minimal Click group printing version
- Run `uv sync --all-extras --all-groups` and verify `uv run fling` works

**Outputs**: Working `uv run fling` command, full directory skeleton
**Tests**: `uv run fling` exits 0 with version output

### Task 1.2 — Pydantic data models

- Implement all models in `src/fling/core/models.py`:
  - `HttpMethod` (enum)
  - `SourceLocation` (file_path, start_line, end_line)
  - `RequestMetadata` (name, refs, no_redirect, no_cookie_jar, timeout_ms, disabled, prompt_vars, note)
  - `Header` (name, value)
  - `RequestBody` (content, file_ref, is_graphql)
  - `ResponseHandler` (inline_script, file_ref)
  - `HttpRequestDefinition` (method, url, http_version, headers, body, metadata, response_handler, response_save_path, pre_request_script, location, comments)
  - `VariableDefinition` (name, value, location)
  - `HttpFile` (file_path, variables, requests, named_requests property)
  - `EnvironmentFile` (environments)
  - `ExecutionResult` (request, resolved_url, resolved_headers, resolved_body, status_code, response_headers, response_body, elapsed_ms, error)
  - `ParseError` (message, location)
  - `ParseResult` (http_file, errors)
- Write `tests/test_models.py`

**Outputs**: ~200 lines model code, ~100 lines tests
**Tests**: Model creation, serialization, computed properties

### Task 1.3 — Core parser: basic requests

- Implement line-by-line state machine in `src/fling/core/parser.py`
- States: `IDLE`, `META`, `REQUEST_LINE`, `HEADERS`, `BODY`, `RESPONSE_HANDLER`
- Handle:
  - `###` separators
  - Comments (`#`, `//`)
  - Request lines (`METHOD URL [HTTP/version]`)
  - Headers (`Name: Value`)
  - Blank-line body separator
  - Body accumulation
  - `@variable = value` file variables
- Create test fixtures:
  - `tests/fixtures/simple.http` (single GET)
  - `tests/fixtures/multiple.http` (3 requests with `###`)
  - `tests/fixtures/headers_body.http` (POST with JSON body)
  - `tests/fixtures/variables.http` (file-level variables)
- Write `tests/test_parser.py`
- Variable interpolation is **NOT** resolved — raw `{{var}}` strings stay in the AST

**Outputs**: ~300 lines parser, ~200 lines tests
**Tests**: Correct parsing of each fixture

### Task 1.4 — Core parser: advanced features

- Extend parser for:
  - Metadata comments: `# @name`, `# @ref`, `# @no-redirect`, `# @timeout`, `# @prompt`, `# @disabled`, `# @note`
  - Multiline URLs (lines starting with `?` or `&`)
  - File body references (`< ./file.json`)
  - Response handlers (`> {% script %}` and `> ./file.js`)
  - Pre-request scripts (`< {% script %}`)
  - Response save directives (`>> file.json`, `>>! file.json`)
  - GraphQL detection (`X-REQUEST-TYPE: GraphQL`)
- Error recovery: emit `ParseError` with location info and continue parsing
- Additional fixtures and tests

**Outputs**: ~200 additional lines parser, ~300 lines tests
**Tests**: Each advanced feature has dedicated fixture and test

### Task 1.5 — Environment loading

- Implement `src/fling/core/environment.py`
- Load `http-client.env.json` and `http-client.private.env.json` from a directory
- Private values override public
- `.env` support via `python-dotenv`
- Environment listing and selection
- `_shared` concept (variables available in all environments)
- Tests with fixture JSON files

**Outputs**: ~150 lines code, ~150 lines tests
**Tests**: Environment merging, private override, .env fallback, _shared

---

## Phase 2: Variable Resolution and Execution Engine

### Task 2.1 — Variable resolution engine

- Implement `src/fling/core/variables.py` with `VariableResolver` class
- Resolution precedence: request-scoped > file vars > env vars > .env > system vars
- System variables:
  - `{{$uuid}}` / `{{$guid}}`
  - `{{$timestamp}}`
  - `{{$isoTimestamp}}` / `{{$datetime iso8601}}`
  - `{{$randomInt min max}}`
  - `{{$env.VAR}}` / `{{$processEnv VAR}}`
  - `{{$dotenv VAR}}`
- No request chaining yet (deferred to Task 2.3)
- Tests for each variable type and precedence ordering

**Outputs**: ~250 lines code, ~200 lines tests

### Task 2.2 — HTTP execution engine

- Implement `src/fling/core/executor.py` with `HttpExecutor` class
- Wraps `httpx.AsyncClient`
- `async execute(request, resolved_vars) -> ExecutionResult`
- Handles: redirects (`@no-redirect`), timeouts (`@timeout`), SSL, cookie jar persistence, multipart form data
- Progress event emission as async callback pattern
- Tests with `pytest-httpx`

**Outputs**: ~200 lines code, ~200 lines tests

### Task 2.3 — Request chaining and runner

- Implement `src/fling/core/runner.py` with `HttpRunner` class
- Dependency graph from `@ref` metadata and `{{requestName.response...}}` references
- Topological sort for execution order
- Sequential execution, result storage keyed by request name
- JSONPath extraction via `jsonpath-ng` for chained variable references (e.g., `{{login.response.body.$.token}}`)
- Extend `VariableResolver` for request chaining
- `async run_all()` and `async run_single(name)` yielding `(request, result)` tuples
- `chaining.http` fixture and tests

**Outputs**: ~250 lines code, ~200 lines tests

### Task 2.4 — CLI implementation

- Full Click commands in `src/fling/cli.py`:
  - `fling run <file.http> [--name NAME] [--all] [--env ENV] [--env-file PATH] [--verbose] [--output json|headers|body|exchange] [--timeout MS] [--insecure]`
  - `fling list <file.http>` — list all requests in a file
  - `fling envs [--env-file PATH]` — list available environments
- Rich-formatted console output:
  - Colored status codes (green 2xx, yellow 3xx, red 4xx/5xx)
  - Formatted response headers
  - Syntax-highlighted JSON/XML response bodies
  - Request timing
- `@prompt` variable support via `click.prompt()`
- Integration tests

**Outputs**: ~250 lines CLI code, ~150 lines tests

---

## Phase 3: Postman Collection Converter

### Task 3.1 — Postman JSON parser

- Implement reader in `src/fling/core/postman.py`
- Parse Postman v2.1 schema: `info`, recursive `item` arrays, `variable` arrays, `auth` objects, `event` arrays
- Intermediate models: `PostmanCollection`, `PostmanFolder`, `PostmanRequest`, `PostmanAuth`, `PostmanVariable`
- Auth inheritance resolution (request -> folder -> collection chain)
- Tests with `tests/fixtures/postman_collection.json`

**Outputs**: ~300 lines code, ~200 lines tests

### Task 3.2 — Postman-to-.http translator

- Output generator: intermediate objects -> .http file strings
- Handle:
  - Collection variables -> `@variable = value`
  - Folder boundaries -> `# ===== Folder: Name =====` comments
  - Requests -> `### Name` + method/url/headers/body
  - Auth -> explicit `Authorization` headers
  - URL construction from structured `url` objects
  - Body mode translation (raw, urlencoded, formdata, graphql)
  - Pre-request/test scripts -> comment blocks with `# TODO:` markers
  - Disabled headers/params -> commented out
- `fling convert <postman.json> [--output DIR] [--split-folders]` CLI command
- Round-trip tests

**Outputs**: ~300 lines code, ~200 lines tests

---

## Phase 4: Textual TUI

### Task 4.1 — TUI app scaffold and collection tree

- `src/fling/tui/app.py`: `FlingApp(App)` with key bindings, CSS, layout (Header, Footer, horizontal split)
- `src/fling/tui/widgets/collection_tree.py`: Tree widget loading .http file, showing requests grouped by `###` sections, emitting selection messages
- `fling tui [file.http]` CLI command
- Textual Pilot tests

**Outputs**: ~200 lines app, ~100 lines tree widget, ~100 lines tests

### Task 4.2 — Request panel

- `src/fling/tui/widgets/request_panel.py`
- TabbedContent: Headers (DataTable), Body (TextArea, read-only, syntax highlighted), Auth info
- URL bar: method + URL as static display
- Reactive updates on tree selection
- Pilot tests

**Outputs**: ~200 lines widget, ~100 lines tests

### Task 4.3 — Response panel and execution

- `src/fling/tui/widgets/response_panel.py`
- Status code (color-coded), response time, size
- TabbedContent: Body (RichLog, syntax highlighted), Headers (DataTable)
- `Ctrl+R` -> `@work(exclusive=True)` worker calling `HttpRunner`
- Streaming response body into RichLog
- Progress indicator during execution
- Environment selector (`Select` widget in header)
- Pilot tests

**Outputs**: ~250 lines widget, ~150 lines tests

### Task 4.4 — Collection runner and progress

- "Run All" via `Ctrl+Shift+R`
- `src/fling/tui/widgets/progress_bar.py`: overall progress X/N, per-request status, elapsed time
- Results accumulate in response panel
- Results summary screen
- Tests

**Outputs**: ~200 lines code, ~100 lines tests

---

## Phase 5: FastAPI Web Interface

### Task 5.1 — Web app scaffold and base templates

- `src/fling/web/app.py`: FastAPI + Uvicorn, lifespan hook (pytailwindcss build), static files, Jinja2Blocks
- `templates/base.html`: Tailwind CSS, HTMX 2.x, SSE extension, Prism.js, dark mode default, responsive layout
- `templates/index.html`: main layout blocks
- `fling serve [file.http] [--port 8000] [--host 0.0.0.0]` CLI command
- pytailwindcss config
- Verify page loads with correct styling

**Outputs**: ~150 lines Python, ~200 lines HTML/CSS

### Task 5.2 — Collection tree and request display

- `src/fling/web/routes/pages.py` and `collections.py`
- Full-page route: load .http file, render tree + first request
- HTMX partials: click request -> load details via `hx-get`
- Request editor component (read-only: method, URL, headers, body, syntax highlighted)
- Environment selector dropdown
- `@prompt` variable support via web form
- Templates: `collection_tree.html`, `request_editor.html`, `env_selector.html`

**Outputs**: ~200 lines Python, ~300 lines HTML

### Task 5.3 — Request execution with SSE streaming

- `src/fling/web/routes/execution.py`
- `EventSourceResponse` streaming named events: `progress`, `headers`, `body`, `timing`, `complete`
- HTMX client routes events to appropriate panels
- Response viewer: status badge (color-coded), timing, tabbed body/headers, syntax highlighting
- OOB swaps for simultaneous updates

**Outputs**: ~200 lines Python, ~200 lines HTML

### Task 5.4 — Collection runner and execution log

- "Run All" button with SSE progress streaming
- Execution log component: scrollable, `sse-swap="log"`, `hx-swap="beforeend scroll:bottom"`
- Per-entry: timestamp, request name, status, duration
- Results summary updating as requests complete

**Outputs**: ~150 lines Python, ~200 lines HTML

---

## Phase 6: Advanced Features

### Task 6.1 — Response handler scripting

- Implement `src/fling/core/scripting.py`
- Python-based response handler syntax:
  - `client.test("name", lambda: assert condition)` assertions
  - `client.global.set(name, value)` for global variables
  - Response access: `response.body`, `response.status`, `response.headers`
- Best-effort transpilation of simple JetBrains-style `> {% %}` JS patterns
- Warn on unsupported constructs
- Integration with `HttpRunner`
- Tests

**Outputs**: ~200 lines code, ~150 lines tests

### Task 6.2 — Output formats and CI integration

- `--output json` (machine-readable)
- `--output junit` (JUnit XML for CI)
- `--output markdown` (human-readable report)
- Exit codes: 0 = all pass, 1 = request failures, 2 = parse errors
- `--bail` flag (stop on first failure)
- `--repeat N` and `--repeat-mode sequential|parallel`
- `--filter` by request name glob pattern
- Integration tests for each output format

**Outputs**: ~250 lines code, ~150 lines tests

### Task 6.3 — File formatting and validation

- `fling fmt <file.http>`: normalize whitespace, align headers, consistent `###` separators, sort variables to top
- `fling validate <file.http>`: undefined variable references, circular `@ref` dependencies, duplicate request names, missing Content-Type for bodies, syntax errors with file locations
- Tests for formatting edge cases and all validation rules

**Outputs**: ~200 lines code, ~150 lines tests

---

## Phase 7: Polish and Distribution

### Task 7.1 — Documentation

- Comprehensive `README.md`: feature overview, installation, quick start, CLI reference, .http format guide, environment config guide, Postman migration guide, examples
- `docs/` directory with extended documentation
- `--help` text for all CLI commands

**Outputs**: README ~500 lines, docs ~1000 lines

### Task 7.2 — CI/CD pipeline

- `.github/workflows/ci.yml`: matrix test Python 3.12/3.13, ruff lint, mypy check, pytest+coverage, build verification
- `.github/workflows/publish.yml`: triggered on version tags, PyPI trusted publishing
- `.pre-commit-config.yaml` with ruff and uv-lock hooks
- Verify `uv build --no-sources` produces clean wheel

**Outputs**: ~100 lines YAML, ~50 lines config

### Task 7.3 — Error handling, edge cases, final polish

- Audit all modules for graceful error handling (network failures, malformed files, missing env files, permission errors)
- Helpful error messages with file/line references
- `--verbose` and `--quiet` modes throughout
- Signal handling (Ctrl+C gracefully cancels running request)
- Large response handling (streaming, truncation)
- Binary response detection
- Redirect chain display
- Certificate error messages
- Proxy support (`HTTPS_PROXY` env var)
- Unicode handling
- Full test suite run, fix failures, target >90% coverage

**Outputs**: ~300 lines hardening, ~200 lines additional tests

---

## Totals

| Metric | Estimate |
|---|---|
| Tasks | 25 |
| Commits | 25 |
| Application code | ~5,000 lines |
| Test code | ~3,500 lines |
| Templates/HTML | ~1,100 lines |
| Docs | ~1,500 lines |
| CI/Config | ~150 lines |
