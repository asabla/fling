# Architecture document and build plan for a Python .http file API testing tool

**A Python-native HTTP API testing tool built on .http files does not exist today.** The closest competitors — httpYac (TypeScript/Node), Hurl (Rust), and JetBrains' `ijhttp` (Java) — all require heavy non-Python runtimes. This tool fills a clear gap: a fast, Python-native .http file runner with both a Textual TUI and a FastAPI+HTMX web interface, installable via `pip install` with zero runtime dependencies beyond Python. The architecture below covers every module, data model, API surface, and a 7-phase build plan broken into Claude Code–sized tasks.

---

## Naming and identity

The tool is named **`fling`** — an action verb, 5 characters, easy to type, and evocative of the core action: "fling a request." It follows the pattern of successful CLI tools like `curl` (4 chars), `xh` (2 chars), and `hurl` (4 chars).

---

## The .http file format the parser must support

The parser must handle the union of the **REST Client (VS Code)** and **JetBrains HTTP Client** formats. These share a common core but diverge on scripting, environments, and request chaining.

### Compatible core syntax (both tools agree)

Requests start with `METHOD URL [HTTP/version]`, followed by `Header: Value` lines, a blank line, then a body. Requests are separated by `###`. Comments use `#` or `//`. File-level variables use `@variable = value`. Variable interpolation uses `{{variableName}}`. Query parameters can span multiple lines starting with `?` or `&`. File body references use `< ./file.json`. Both support Basic and Digest auth via `Authorization: Basic user password`.

### Key divergences to handle

| Feature | REST Client (VS Code) | JetBrains HTTP Client |
|---|---|---|
| **Environments** | VS Code `settings.json` (`$shared` key) | `http-client.env.json` + `.private.env.json` |
| **Request chaining** | Declarative: `{{login.response.body.$.token}}` | Programmatic: `client.global.set()` in `> {% %}` |
| **Response handlers** | None | `> {% javascript %}` blocks |
| **Pre-request scripts** | None | `< {% javascript %}` blocks |
| **Test framework** | None | `client.test()`, `client.assert()` |
| **Prompt variables** | `# @prompt varName desc` | Not supported |
| **UUID variable** | `{{$guid}}` | `{{$uuid}}` |
| **Env variable access** | `{{$processEnv VAR}}` | `{{$env.VAR}}` |
| **Request tags** | Not supported | `@no-redirect`, `@timeout`, `@no-cookie-jar` |
| **Response save** | Not supported | `>> file.json`, `>>! file.json` |

**Design decision**: Support both dialects. The parser produces a unified AST regardless of which syntax variant was used. JetBrains' environment file format (`http-client.env.json`) is adopted as the primary environment mechanism since it's file-based and CI-friendly. REST Client's `$shared` environment maps to a `_shared` key in the env file.

---

## Core data models (Pydantic v2)

```python
class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    CONNECT = "CONNECT"

class SourceLocation(BaseModel):
    file_path: str
    start_line: int
    end_line: int

class RequestMetadata(BaseModel):
    name: str | None = None              # @name
    refs: list[str] = []                 # @ref dependencies
    no_redirect: bool = False            # @no-redirect
    no_cookie_jar: bool = False          # @no-cookie-jar
    timeout_ms: int | None = None        # @timeout
    disabled: bool = False               # @disabled
    prompt_vars: dict[str, str] = {}     # @prompt varName description
    note: str | None = None              # @note

class Header(BaseModel):
    name: str
    value: str  # may contain {{variables}}

class RequestBody(BaseModel):
    content: str
    file_ref: str | None = None          # < ./file.json
    is_graphql: bool = False

class ResponseHandler(BaseModel):
    inline_script: str | None = None     # > {% ... %}
    file_ref: str | None = None          # > ./handler.js

class HttpRequestDefinition(BaseModel):
    method: HttpMethod = HttpMethod.GET
    url: str                              # raw, with {{variables}}
    http_version: str | None = None
    headers: list[Header] = []
    body: RequestBody | None = None
    metadata: RequestMetadata = RequestMetadata()
    response_handler: ResponseHandler | None = None
    response_save_path: str | None = None # >> file.json
    pre_request_script: str | None = None # < {% ... %}
    location: SourceLocation
    comments: list[str] = []

class VariableDefinition(BaseModel):
    name: str
    value: str
    location: SourceLocation

class HttpFile(BaseModel):
    file_path: str
    variables: list[VariableDefinition] = []
    requests: list[HttpRequestDefinition] = []
    
    @property
    def named_requests(self) -> dict[str, HttpRequestDefinition]:
        return {r.metadata.name: r for r in self.requests if r.metadata.name}

class EnvironmentFile(BaseModel):
    environments: dict[str, dict[str, Any]]  # env_name -> {var: value}
    
class ExecutionResult(BaseModel):
    request: HttpRequestDefinition
    resolved_url: str
    resolved_headers: dict[str, str]
    resolved_body: str | None
    status_code: int
    response_headers: dict[str, list[str]]
    response_body: str
    elapsed_ms: float
    error: str | None = None
```

---

## Parser architecture

**No Python library exists for parsing .http files.** After evaluating httpYac's line-by-line regex approach (fragile, hard to maintain), Hurl's hand-written recursive descent (flexible but labor-intensive), and grammar-based options, the recommendation is a **hybrid approach: hand-written line-aware parser with regex patterns**, similar to httpYac but with a cleaner Python design.

Why not Lark/PEG: The .http format is inherently line-oriented with context-dependent sections (headers vs. body determined by a blank line, not by syntax). This makes it awkward to express as a context-free grammar. A line-by-line state machine is the most natural fit, as both httpYac and REST Client independently chose this approach.

### Parser state machine

```
IDLE → (sees @var = val) → emit VariableDefinition, stay IDLE
IDLE → (sees ### or EOF) → emit separator, stay IDLE
IDLE → (sees # @meta) → accumulate metadata, → META
IDLE → (sees METHOD URL) → → REQUEST_LINE
META → (sees METHOD URL) → → REQUEST_LINE
REQUEST_LINE → (sees Header: Value) → → HEADERS
REQUEST_LINE → (sees blank line) → → BODY
HEADERS → (sees Header: Value) → accumulate, stay HEADERS
HEADERS → (sees blank line) → → BODY
BODY → (sees > {% or > file) → → RESPONSE_HANDLER
BODY → (sees ### or EOF) → emit request, → IDLE
BODY → (other) → accumulate body, stay BODY
RESPONSE_HANDLER → (sees ### or EOF) → emit request, → IDLE
```

Variable interpolation (`{{...}}`) is **not resolved during parsing**. The parser produces an AST with raw template strings. Resolution happens at execution time via a separate `VariableResolver` that walks the AST and substitutes values based on the active environment, file variables, and request chain results.

---

## Module architecture

```
src/fling/
├── __init__.py                 # Package root, version
├── cli.py                      # Click CLI entry point
├── core/
│   ├── __init__.py
│   ├── parser.py               # .http file parser → HttpFile AST
│   ├── variables.py            # Variable resolution engine
│   ├── executor.py             # HTTP request execution (httpx)
│   ├── runner.py               # Orchestrates parse → resolve → execute
│   ├── environment.py          # Environment file loading
│   ├── scripting.py            # Response handler execution (optional)
│   ├── models.py               # All Pydantic data models
│   └── postman.py              # Postman collection → .http converter
├── tui/
│   ├── __init__.py
│   ├── app.py                  # Textual App class
│   ├── screens/
│   │   ├── main.py             # Main split-pane screen
│   │   └── environment.py      # Environment editor screen
│   ├── widgets/
│   │   ├── request_panel.py    # URL bar + method + headers/body tabs
│   │   ├── response_panel.py   # Status + headers/body viewer
│   │   ├── collection_tree.py  # Tree widget for .http file navigation
│   │   └── progress_bar.py     # Collection run progress
│   └── styles/
│       └── app.tcss            # Textual CSS
├── web/
│   ├── __init__.py
│   ├── app.py                  # FastAPI application
│   ├── routes/
│   │   ├── pages.py            # Full page renders
│   │   ├── requests.py         # HTMX partials for request ops
│   │   ├── execution.py        # SSE streaming for execution
│   │   ├── collections.py      # Collection management
│   │   └── environments.py     # Environment CRUD
│   ├── templates/
│   │   ├── base.html           # Base layout (Tailwind + HTMX)
│   │   ├── index.html          # Main page with blocks
│   │   ├── components/         # Reusable Jinja2 includes
│   │   └── partials/           # HTMX fragment responses
│   └── static/
│       ├── src/input.css       # Tailwind source
│       └── css/output.css      # Compiled Tailwind
└── tests/
    ├── conftest.py
    ├── test_parser.py
    ├── test_variables.py
    ├── test_executor.py
    ├── test_runner.py
    ├── test_postman.py
    ├── test_cli.py
    ├── test_tui.py             # Textual Pilot tests
    └── fixtures/
        ├── simple.http
        ├── variables.http
        ├── chaining.http
        └── postman_collection.json
```

### Module responsibilities

**`core/parser.py`** — The line-by-line state-machine parser. Input: file path or string. Output: `HttpFile` with all `HttpRequestDefinition` objects, raw `{{variable}}` references preserved. **~400 lines of code**, the most critical module.

**`core/variables.py`** — Resolves `{{variable}}` templates. Handles: file variables (`@var = value`), environment variables (from `http-client.env.json`), system/dynamic variables (`{{$uuid}}`, `{{$timestamp}}`, `{{$randomInt}}`, `{{$env.VAR}}`, `{{$dotenv VAR}}`), and request chaining references (`{{login.response.body.$.token}}`). Uses `jsonpath-ng` for JSONPath extraction from chained responses.

**`core/executor.py`** — Wraps `httpx.AsyncClient`. Sends a resolved request, returns `ExecutionResult`. Handles: redirects, timeouts, SSL, cookies (jar persistence), streaming responses. Emits progress events (DNS, connect, TLS, send, receive) for the TUI/web UI.

**`core/runner.py`** — Top-level orchestrator. Loads an `.http` file, resolves the execution order (topological sort on `@ref` dependencies), runs requests sequentially or selectively, manages the variable context across the chain. Exposes an async generator of `(request, result)` tuples for streaming progress to UIs.

**`core/environment.py`** — Loads `http-client.env.json` and `http-client.private.env.json` from the project directory. Merges public + private. Supports `.env` files via `python-dotenv`. Environment selection at runtime.

**`core/postman.py`** — Reads a Postman Collection v2.1 JSON file and emits one or more `.http` files. Handles: flattening folder hierarchy (one file per folder or comment-delimited sections), translating auth inheritance, converting `{{variable}}` syntax (already compatible), mapping body modes (raw/urlencoded/formdata/graphql), and outputting pre-request/test scripts as comments with `TODO` markers for manual translation.

**`cli.py`** — Click-based CLI. Commands: `fling run <file.http>` (execute requests), `fling run --all <file.http>` (run all), `fling tui [file.http]` (launch TUI), `fling serve [file.http]` (launch web UI), `fling convert <postman.json>` (Postman import), `fling fmt <file.http>` (format/lint).

---

## Web interface architecture (FastAPI + HTMX + Tailwind)

### Technology stack

| Component | Choice | Rationale |
|---|---|---|
| **Server** | FastAPI + Uvicorn | Async-native, excellent for SSE streaming |
| **Templates** | Jinja2 + `jinja2-fragments` | Render individual template blocks for HTMX partials |
| **Interactivity** | HTMX 2.x + SSE extension | No JavaScript framework needed; SSE for unidirectional streaming |
| **Styling** | Tailwind CSS via `pytailwindcss` | No Node.js build step; standalone binary via pip |
| **Syntax highlighting** | Prism.js (CDN) | Re-highlight after HTMX swaps via `htmx:afterSwap` event |
| **Dark mode** | Tailwind `darkMode: 'class'` | Default dark for developer tool |

### SSE streaming pattern for request execution

The web UI streams execution progress using **Server-Sent Events**. This is unidirectional (server→browser), works through proxies, and has built-in reconnection. The FastAPI endpoint uses `sse-starlette`:

```python
@router.get("/execute/{request_name}/stream")
async def execute_stream(request: Request, request_name: str):
    async def event_generator():
        async for phase, data in runner.execute_streaming(request_name):
            if await request.is_disconnected():
                break
            yield {"event": phase, "data": render_partial(phase, data)}
    return EventSourceResponse(event_generator())
```

The HTMX client uses named SSE events (`sse-swap="progress"`, `sse-swap="complete"`) to route different update types to different UI panels. Out-of-band swaps update the status badge and timing display simultaneously.

### Route structure

Full-page routes (`GET /`, `GET /collections/{id}`) return complete HTML extending `base.html`. HTMX partial routes (detected via `HX-Request` header) return rendered template blocks using `jinja2-fragments`. The `jinja2-fragments` library enables rendering a single `{% block response_viewer %}` from `index.html` without re-rendering the entire page.

---

## TUI architecture (Textual)

**Textual is the clear winner** for this use case. The **Posting** project (10.9k GitHub stars) — an HTTP API client built by a Textual core contributor — validates that every required feature (request editing, response viewing, environment management, syntax highlighting, collection navigation) is achievable with Textual.

### Key Textual patterns

**Async workers** (`@work(exclusive=True)`) fire HTTP requests via `httpx.AsyncClient` without blocking the UI. Responses stream back to a `RichLog` widget in real-time. **Reactive attributes** (`status_code = reactive(0)`) auto-update the UI when values change. **CSS-like styling** (`.tcss` files) enables rapid layout iteration with hot-reloading. **Built-in widgets**: `Tree` for collection navigation, `DataTable` for headers, `TabbedContent` for request/response sections, `TextArea` for body editing with syntax highlighting, `RichLog` for streaming response bodies.

### Screen layout

```
┌─ Header ────────────────────────────────────────────────┐
│ fling v0.1.0 | env: development | [Ctrl+R] Run          │
├──────────┬──────────────────────────────────────────────┤
│ Tree     │ Request Panel                                 │
│          │ [GET ▼] https://api.example.com/users         │
│ ### auth │ ┌─Params─┬─Headers─┬─Body─┬─Auth─┐           │
│   login  │ │ Accept: application/json          │         │
│   refresh│ │                                    │         │
│ ### users│ ├─────────────────────────────────────┤        │
│   list   │ Response Panel                                │
│   create │ [200 OK] 245ms  1.2 KB                        │
│   update │ ┌─Body────┬─Headers─┐                         │
│          │ │ {"users": [{"id": 1, ...}]}       │         │
├──────────┴──────────────────────────────────────────────┤
│ Footer: [Ctrl+R] Run [Ctrl+E] Env [Ctrl+N] Next [Q] Quit│
└─────────────────────────────────────────────────────────┘
```

---

## Postman collection translator design

The translator reads Postman Collection v2.1 JSON and outputs `.http` files. The Postman format uses `item` arrays (which can nest as folders), `variable` arrays, `auth` objects with inheritance, and `event` arrays containing JavaScript `exec` lines.

### Translation mapping

Features that map cleanly: HTTP method + URL → request line, headers → header lines, raw/JSON body → body after blank line, `{{variable}}` → `{{variable}}` (identical syntax), collection variables → `@variable = value`, request names → `### Request Name`, descriptions → comments.

Features requiring creative solutions: folder hierarchy → comment-delimited sections (`# ===== Folder: Auth =====`) or separate files per folder, auth inheritance → resolved and flattened at each request (e.g., collection-level bearer token becomes explicit `Authorization: Bearer {{token}}` on every request that inherits it), pre-request scripts → preserved as comments with `# TODO: translate pre-request script` markers, test assertions → preserved as JetBrains-style `> {% %}` response handlers where possible.

Features lost in translation: `pm.sendRequest()` sub-requests, `postman.setNextRequest()` flow control, saved response examples, `pm.visualizer`, interactive OAuth2 flows. These are documented as comments in the output.

---

## uv project configuration

The project uses `uv init --package fling` with optional dependency groups for the web and TUI interfaces, so users install only what they need.

```toml
[project]
name = "fling"
version = "0.1.0"
description = "A Python .http file runner with CLI, TUI, and web interfaces"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "httpx>=0.27",
    "rich>=13.0",
    "pydantic>=2.7",
    "jsonpath-ng>=1.6",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
tui = ["textual>=0.70"]
web = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "jinja2-fragments>=1.4",
    "sse-starlette>=2.0",
]
all = ["fling[tui,web]"]

[project.scripts]
fling = "fling.cli:main"

[build-system]
requires = ["uv_build>=0.10.0,<0.11.0"]
build-backend = "uv_build"

[dependency-groups]
dev = [{include-group = "test"}, {include-group = "lint"}, "mypy>=1.10", "pre-commit>=3.7"]
test = ["pytest>=8.0", "pytest-cov>=5.0", "pytest-asyncio>=0.23"]
lint = ["ruff>=0.4"]
```

The `[project.scripts]` entry point means `uv run fling` or `pip install fling && fling` both work. Optional extras mean `pip install fling[tui]` adds Textual and `pip install fling[web]` adds FastAPI — keeping the base install lightweight.

---

## Phased build plan

Each phase produces a working, testable increment. Tasks are sized for a single Claude Code session (roughly 30–90 minutes each). Dependencies flow strictly downward — no task references code that hasn't been built in a prior task.

### Phase 1: Project scaffold and core parser (5 tasks)

**Task 1.1 — Project initialization**
Set up the project with `uv init --package fling`. Create the full directory structure under `src/fling/` with empty `__init__.py` files for all subpackages (`core/`, `tui/`, `web/`). Write the complete `pyproject.toml` with all dependencies, optional extras, dependency groups, and tool configs (ruff, pytest, mypy). Add `.gitignore`, `.python-version` (3.12), `LICENSE` (MIT), and a starter `README.md`. Run `uv sync --all-extras --all-groups` to verify everything resolves. Create `src/fling/cli.py` with a minimal Click group that prints `fling v0.1.0`. Verify `uv run fling` works.

**Task 1.2 — Pydantic data models**
Implement all models in `src/fling/core/models.py`: `HttpMethod`, `SourceLocation`, `RequestMetadata`, `Header`, `RequestBody`, `ResponseHandler`, `HttpRequestDefinition`, `VariableDefinition`, `HttpFile`, `EnvironmentFile`, `ExecutionResult`, `ParseError`, `ParseResult`. Include all properties (`named_requests`, `requests`). Write comprehensive tests in `tests/test_models.py` verifying model creation, serialization, and computed properties. Target: **~200 lines of model code, ~100 lines of tests**.

**Task 1.3 — Core parser: basic requests**
Implement the line-by-line state machine parser in `src/fling/core/parser.py`. This task handles: `###` separators, comments (`#`, `//`), request lines (`METHOD URL [HTTP/version]`), headers, blank-line body separator, request body accumulation, and `@variable = value` file variables. Create test fixtures in `tests/fixtures/`: `simple.http` (single GET), `multiple.http` (3 requests with `###`), `headers_body.http` (POST with JSON body), `variables.http` (file-level variables). Write tests in `tests/test_parser.py` verifying correct parsing of each fixture. **Do not handle variable interpolation** — raw `{{var}}` strings stay in the AST. Target: **~300 lines parser, ~200 lines tests**.

**Task 1.4 — Core parser: advanced features**
Extend the parser to handle: metadata comments (`# @name`, `# @ref`, `# @no-redirect`, `# @timeout`, `# @prompt`, `# @disabled`, `# @note`), multiline URLs (lines starting with `?` or `&`), file body references (`< ./file.json`), response handlers (`> {% script %}` and `> ./file.js`), pre-request scripts (`< {% script %}`), response save directives (`>> file.json`, `>>! file.json`), GraphQL detection (`X-REQUEST-TYPE: GraphQL`), and cURL command detection. Add fixtures for each feature. Add error recovery: when the parser encounters invalid syntax, it should emit a `ParseError` with location info and continue parsing the rest of the file. Target: **~200 additional lines parser, ~300 lines tests**.

**Task 1.5 — Environment loading**
Implement `src/fling/core/environment.py`: load `http-client.env.json` and `http-client.private.env.json` from a given directory. Private values override public. Support `.env` files via `python-dotenv`. Implement environment listing and selection. Handle the `$shared`/`_shared` concept (variables available in all environments). Write tests with fixture JSON files. Target: **~150 lines code, ~150 lines tests**.

### Phase 2: Variable resolution and execution engine (4 tasks)

**Task 2.1 — Variable resolution engine**
Implement `src/fling/core/variables.py`. Build a `VariableResolver` class that takes an `HttpFile`, an `EnvironmentFile`, and the active environment name. It resolves `{{variable}}` references in URLs, headers, and bodies using this precedence: (1) request-scoped variables, (2) file variables (`@var = value`), (3) environment variables, (4) `.env` file variables, (5) system variables. Implement system variables: `{{$uuid}}` / `{{$guid}}`, `{{$timestamp}}`, `{{$isoTimestamp}}` / `{{$datetime iso8601}}`, `{{$randomInt min max}}`, `{{$env.VAR}}` / `{{$processEnv VAR}}`, `{{$dotenv VAR}}`. Use regex to find `{{...}}` patterns and substitute. **Do not implement request chaining yet.** Write tests covering each variable type and precedence ordering. Target: **~250 lines code, ~200 lines tests**.

**Task 2.2 — HTTP execution engine**
Implement `src/fling/core/executor.py`. Build an `HttpExecutor` class wrapping `httpx.AsyncClient`. Method: `async execute(request: HttpRequestDefinition, resolved_vars: dict) -> ExecutionResult`. Handles: building the full `httpx.Request` from resolved URL/headers/body, following redirects (respecting `@no-redirect`), timeouts (respecting `@timeout`), SSL verification, cookie jar persistence across requests in a session, and multipart form data. Implement progress event emission as an async callback pattern (for TUI/web to hook into). Write tests using `pytest-httpx` or `respx` for mocking. Target: **~200 lines code, ~200 lines tests**.

**Task 2.3 — Request chaining and runner**
Implement `src/fling/core/runner.py`. Build an `HttpRunner` class that: (1) parses the `.http` file, (2) builds a dependency graph from `@ref` metadata and `{{requestName.response...}}` references, (3) performs topological sort, (4) executes requests in dependency order, (5) stores results keyed by request name, (6) resolves chained variable references (`{{login.response.body.$.token}}`) using `jsonpath-ng`. Extend `VariableResolver` to handle request chaining references. Expose `async run_all()` and `async run_single(name)` methods that yield `(request, result)` tuples. Write tests with a `chaining.http` fixture that has login → use-token flow. Target: **~250 lines code, ~200 lines tests**.

**Task 2.4 — CLI implementation**
Flesh out `src/fling/cli.py` with full Click commands: `fling run <file.http> [--name NAME] [--all] [--env ENV] [--env-file PATH] [--verbose] [--output json|headers|body|exchange] [--timeout MS] [--insecure]`. Implement Rich-formatted console output: colored status codes (green 2xx, yellow 3xx, red 4xx/5xx), formatted response headers, syntax-highlighted JSON/XML response bodies, request timing. Add `fling list <file.http>` to list all requests in a file. Add `fling envs [--env-file PATH]` to list available environments. Write integration tests that run actual CLI commands against fixture files. Target: **~250 lines CLI code, ~150 lines tests**.

### Phase 3: Postman collection converter (2 tasks)

**Task 3.1 — Postman JSON parser**
Implement the Postman collection reader in `src/fling/core/postman.py`. Parse the v2.1 JSON schema: extract `info`, recursively walk `item` arrays (handling both `Item` with `request` and `ItemGroup` with nested `item`), extract `variable` arrays, `auth` objects, and `event` arrays. Build intermediate Python objects: `PostmanCollection`, `PostmanFolder`, `PostmanRequest`, `PostmanAuth`, `PostmanVariable`. Implement auth inheritance resolution: walk the tree, at each request compute the effective auth by checking request → folder → collection chain. Write tests against a comprehensive `tests/fixtures/postman_collection.json` fixture. Target: **~300 lines code, ~200 lines tests**.

**Task 3.2 — Postman-to-.http translator**
Implement the output generator that converts the parsed Postman intermediate objects into `.http` file strings. Handle: collection variables → `@variable = value`, folder boundaries → `# ===== Folder: Name =====` comments, requests → `### Name` + method/url/headers/body, auth → explicit `Authorization` headers, URL construction from structured `url` objects (host + path + query params), body mode translation (raw → plain body, urlencoded → key=value pairs, formdata → multipart syntax, graphql → POST with JSON body), disabled headers/params → commented out. Pre-request and test scripts → preserved as `# [Pre-request Script]` and `# [Test Script]` comment blocks. Add `fling convert <postman.json> [--output DIR] [--split-folders]` CLI command. `--split-folders` creates one `.http` file per folder. Write round-trip tests. Target: **~300 lines code, ~200 lines tests**.

### Phase 4: Textual TUI (4 tasks)

**Task 4.1 — TUI app scaffold and collection tree**
Create `src/fling/tui/app.py` with the main `FlingApp(App)` class. Define key bindings (`Ctrl+R` run, `Ctrl+E` environment, `Ctrl+N` next, `Q` quit), CSS path, and `compose()` layout with `Header`, `Footer`, and a horizontal split between sidebar and main content. Implement `src/fling/tui/widgets/collection_tree.py`: a `Tree` widget that loads an `.http` file, shows requests grouped by `###` sections, displays method + name for each request, and emits a message when a request is selected. Add the `fling tui [file.http]` CLI command. Write Textual Pilot tests verifying the app launches and the tree populates. Target: **~200 lines app, ~100 lines tree widget, ~100 lines tests**.

**Task 4.2 — Request panel**
Implement `src/fling/tui/widgets/request_panel.py`: displays the selected request's details in a `TabbedContent` widget with tabs for Headers (DataTable), Body (TextArea with syntax highlighting), and Auth info. The URL bar shows method + URL as a static display (this is a runner, not an editor). When a request is selected from the tree, the panel updates reactively. Write Pilot tests verifying tab switching and content display. Target: **~200 lines widget, ~100 lines tests**.

**Task 4.3 — Response panel and execution**
Implement `src/fling/tui/widgets/response_panel.py`: shows status code (color-coded), response time, response size, and tabbed content for Body (RichLog with syntax highlighting) and Headers (DataTable). Wire up the `Ctrl+R` binding to execute the selected request using a Textual `@work(exclusive=True)` worker that calls `HttpRunner`. Stream the response body into the RichLog in real time. Show a progress indicator during execution. Add environment selection (a `Select` widget in the header bar). Write Pilot tests verifying execution and response display. Target: **~250 lines widget, ~150 lines tests**.

**Task 4.4 — Collection runner and workflow progress**
Add a "Run All" mode (`Ctrl+Shift+R`) that executes all requests in dependency order. Implement `src/fling/tui/widgets/progress_bar.py`: a panel showing overall progress (X/N requests), per-request status (pending/running/pass/fail), and elapsed time. Results accumulate in the response panel. Add a results summary screen showing pass/fail counts with details. Write tests verifying collection run completion and progress updates. Target: **~200 lines code, ~100 lines tests**.

### Phase 5: FastAPI web interface (4 tasks)

**Task 5.1 — Web app scaffold and base templates**
Create `src/fling/web/app.py` with the FastAPI application, lifespan hook (builds Tailwind CSS on startup via `pytailwindcss`), static file mounting, and Jinja2Blocks template engine. Create `templates/base.html` with: Tailwind CSS (compiled), HTMX 2.x (CDN), SSE extension, Prism.js (CDN), dark mode default, responsive layout shell (sidebar + main content). Create `templates/index.html` extending base with the main layout blocks. Add `fling serve [file.http] [--port 8000] [--host 0.0.0.0]` CLI command. Verify the page loads in a browser with correct styling. Set up Tailwind config with `pytailwindcss`. Target: **~150 lines Python, ~200 lines HTML/CSS**.

**Task 5.2 — Collection tree and request display**
Implement `src/fling/web/routes/pages.py` and `collections.py`. Full-page route loads the `.http` file and renders the collection tree sidebar + first request details. HTMX partials: clicking a request in the tree loads its details via `hx-get` into the main panel. Implement request editor component (read-only display of method, URL, headers, body with syntax highlighting). Implement environment selector dropdown that triggers re-rendering of variable-dependent content via `hx-get`. Write `templates/components/collection_tree.html`, `request_editor.html`, `env_selector.html`. Target: **~200 lines Python, ~300 lines HTML**.

**Task 5.3 — Request execution with SSE streaming**
Implement `src/fling/web/routes/execution.py`. The execute endpoint returns an `EventSourceResponse` that streams named events: `progress` (execution phase updates), `headers` (response headers), `body` (response body, potentially chunked for large responses), `timing` (elapsed time), `complete` (final status). HTMX client routes each event to the appropriate panel. Implement response viewer component with status badge (color-coded), timing display, tabbed body/headers view, and syntax highlighting. Use OOB swaps to update status badge and timing simultaneously. Target: **~200 lines Python, ~200 lines HTML**.

**Task 5.4 — Collection runner and execution log**
Add "Run All" button that streams collection execution progress via SSE. Implement execution log component at the bottom of the page: a scrollable log panel that receives `sse-swap="log"` events with `hx-swap="beforeend scroll:bottom"`. Each log entry shows timestamp, request name, status, and duration. Add a results summary that updates as requests complete. Style with Tailwind for a polished developer-tool appearance. Target: **~150 lines Python, ~200 lines HTML**.

### Phase 6: Advanced features (3 tasks)

**Task 6.1 — Response handler scripting (lightweight)**
Implement `src/fling/core/scripting.py`. Rather than embedding a full JavaScript engine, implement a **Python-based response handler** syntax. Support: `client.test("name", lambda: assert condition)` style assertions, `client.global.set(name, value)`, response body access (`response.body`, `response.status`, `response.headers`). For JetBrains-style `> {% %}` JavaScript blocks, provide a best-effort transpilation of simple patterns (variable setting, basic assertions) to Python, and warn on unsupported constructs. Integrate with `HttpRunner`. Write tests covering common assertion patterns. Target: **~200 lines code, ~150 lines tests**.

**Task 6.2 — Output formats and CI integration**
Add output format support to the CLI: `--output json` (machine-readable results), `--output junit` (JUnit XML for CI), `--output markdown` (human-readable report). Implement exit codes: 0 = all pass, 1 = request failures, 2 = parse errors. Add `--bail` flag to stop on first failure. Add `--repeat N` and `--repeat-mode sequential|parallel` for load-style testing. Implement `--filter` by request name glob pattern. Write integration tests verifying each output format. Target: **~250 lines code, ~150 lines tests**.

**Task 6.3 — File formatting and validation**
Implement `fling fmt <file.http>` that normalizes whitespace, aligns headers, ensures consistent `###` separators, and sorts file-level variables to the top. Implement `fling validate <file.http>` that checks for: undefined variable references, circular `@ref` dependencies, duplicate request names, missing Content-Type for requests with bodies, and syntax errors. Output validation errors with file locations. Write tests covering formatting edge cases and all validation rules. Target: **~200 lines code, ~150 lines tests**.

### Phase 7: Polish and distribution (3 tasks)

**Task 7.1 — Documentation**
Write comprehensive `README.md` with: feature overview, installation (`pip install fling`, `pip install fling[tui]`, `pip install fling[web]`), quick start guide, CLI reference, .http file format guide (covering both REST Client and JetBrains syntax), environment configuration guide, Postman migration guide, and examples. Add `docs/` directory with extended documentation in Markdown. Add `--help` text to all CLI commands. Target: **README ~500 lines, docs ~1000 lines**.

**Task 7.2 — CI/CD pipeline**
Create `.github/workflows/ci.yml`: matrix test across Python 3.11/3.12/3.13, run ruff lint, mypy type check, pytest with coverage, build verification. Create `.github/workflows/publish.yml`: triggered on version tags, builds and publishes to PyPI using trusted publishing. Add `.pre-commit-config.yaml` with ruff and uv-lock hooks. Ensure `uv build --no-sources` produces clean wheel. Test installation from built wheel in a clean environment. Target: **~100 lines YAML, ~50 lines config**.

**Task 7.3 — Error handling, edge cases, and final polish**
Audit all modules for: graceful error handling (network failures, malformed files, missing environment files, permission errors), helpful error messages with file/line references, `--verbose` and `--quiet` modes throughout, proper signal handling (Ctrl+C cancels running request gracefully), large response handling (streaming, truncation), binary response detection, redirect chain display, certificate error messages, proxy support (`HTTPS_PROXY` env var), and Unicode handling. Run the full test suite, fix any failures, ensure >90% code coverage. Target: **~300 lines of hardening across modules, ~200 lines additional tests**.

---

## How the phases connect

Phase 1 delivers a parser that turns `.http` files into a Pydantic AST. Phase 2 makes that AST executable — resolve variables, send HTTP requests, chain results. Phase 3 adds Postman import. Phase 4 wraps the core in a Textual TUI. Phase 5 wraps it in a web UI. Phase 6 adds CI-grade features (JUnit output, assertions, formatting). Phase 7 polishes for distribution.

Each task within a phase is designed to be completable by Claude Code in a single session, with clear inputs (which modules/files to create or modify), clear outputs (what should work when done), and clear test criteria (specific test files to create and what they verify). The total is **25 tasks across 7 phases**, roughly **~5,000 lines of application code and ~3,500 lines of tests** at completion.

The core technical risks are: (1) parser correctness across the two .http dialects — mitigated by extensive fixture-based testing from Task 1.3 onward; (2) variable resolution ordering and circular dependency detection — mitigated by explicit precedence rules and topological sort in Task 2.3; (3) Textual/HTMX real-time streaming — mitigated by proven patterns from Posting (TUI) and sse-starlette (web). No fundamental technical unknowns remain after this research.
