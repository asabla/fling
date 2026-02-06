# Agent Instructions — fling

## Project Overview

**fling** is a Python-native HTTP API testing tool built on `.http` files. It provides a CLI, Textual TUI, and FastAPI+HTMX web interface for running and managing HTTP requests defined in `.http` files.

## Key Documents

- **Architecture & Design**: `docs/plans/01_initial_implementation.md` — Full architecture document covering the .http format, data models, parser design, module responsibilities, TUI/Web architecture, and Postman converter design.
- **Implementation Plan**: `docs/plans/02_implementation_plan.md` — Detailed 25-task, 7-phase build plan with decisions, outputs, and test criteria for each task.

## Project Structure

```
src/fling/
├── __init__.py              # Package root, version
├── cli.py                   # Click CLI entry point (run, list, envs, convert, tui, serve)
├── core/
│   ├── models.py            # Pydantic v2 data models (HttpFile, ExecutionResult, ScriptResult, etc.)
│   ├── parser.py            # .http file parser (line-by-line state machine)
│   ├── variables.py         # Variable resolution engine (env, chaining, system vars)
│   ├── executor.py          # HTTP execution (httpx async)
│   ├── runner.py            # Orchestrator (parse -> resolve -> execute -> script)
│   ├── environment.py       # Environment file loading (http-client.env.json, .env)
│   ├── scripting.py         # Response handler scripting engine (JS transpilation)
│   └── postman.py           # Postman v2.1 collection converter
├── tui/                     # Textual TUI (read-only runner)
│   ├── app.py               # Main TUI application
│   ├── widgets/
│   │   ├── collection_tree.py
│   │   ├── request_panel.py
│   │   ├── response_panel.py
│   │   └── runner_panel.py
│   └── styles/
│       └── app.tcss
└── web/                     # FastAPI + HTMX web interface
    ├── app.py               # FastAPI factory with route registration
    ├── scanner.py           # Directory scanning (scan_directory, scan_single_file)
    ├── watcher.py           # Live file watcher (FileWatcher, FileChangeEvent)
    ├── routes/
    │   ├── pages.py          # Page routes (index, request detail, env switching)
    │   ├── execution.py      # Execution routes (single + Run All via SSE)
    │   └── watch.py          # Watch routes (SSE file-change stream, POST /reload)
    ├── templates/
    │   ├── base.html
    │   ├── index.html
    │   └── partials/         # HTMX partial templates
    └── static/
```

## Technical Decisions

- **Python**: 3.12+ minimum
- **Async**: Fully async core using `httpx.AsyncClient`
- **Build**: `uv_build` backend, installable via `pip install fling`
- **Package manager**: `uv` for development
- **Testing**: `pytest` + `pytest-asyncio` + `pytest-httpx`, `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed)
- **Linting**: `ruff` for linting and formatting
- **Type checking**: `mypy` with strict mode
- **Dependencies**: Click, httpx, Rich, Pydantic v2, jsonpath-ng, python-dotenv
- **Optional extras**: `fling[tui]` (Textual), `fling[web]` (FastAPI+HTMX), `fling[all]`

## Implementation Status

### Completed (25 of 25 original tasks + Web Overhaul Phases A–E + Task 6.3)

| Phase | Task | Description | Commit |
|-------|------|-------------|--------|
| 1 | 1.1 | Project initialization | `496d1e7` |
| 1 | 1.2 | Pydantic data models | `fcc62fd` |
| 1 | 1.3 | Core parser: basic requests | `3ded889` |
| 1 | 1.4 | Core parser: advanced features | `6717939` |
| 1 | 1.5 | Environment loading | `75498fb` |
| 2 | 2.1 | Variable resolution engine | `c48995f` |
| 2 | 2.2 | HTTP executor | `8b72ec4` |
| 2 | 2.3 | Request chaining and runner | `d7dd12a` |
| 2 | 2.4 | Full CLI | `150c8ba` |
| 3 | 3.1 | Postman JSON parser | `c28a4d5` |
| 3 | 3.2 | Postman-to-.http converter | `5fe7e4b` |
| 4 | 4.1 | TUI scaffold and collection tree | `46835fc` |
| 4 | 4.2 | Request panel with tabs | `e8e2f0e` |
| 4 | 4.3 | Response panel and execution | `9a60187` |
| 4 | 4.4 | Collection runner and progress | `e587853` |
| 5 | 5.1 | Web app scaffold | `35d37f2` |
| 5 | 5.2 | Collection tree, env switching | `9bba5ff` |
| 5 | 5.3 | Request execution with SSE | `b725828` |
| 5 | 5.4 | Collection runner with Run All | `62bb5e2` |
| 6 | 6.1 | Response handler scripting | `01e7999` |
| 6 | 6.2 | Output formats and CI flags | `74e13a7` |
| A | — | Bundle web assets locally (Tailwind, vendor JS) | `eb39643` |
| B | — | Directory scanning + multi-file state | `65c9068` |
| C | — | Live file watching with SSE hot-reload | `549a78e` |
| D | — | UI polish & UX improvements (search, keyboard nav, responsive) | `b9a8a0c` |
| E | — | Advanced features (env editing, history, comparison) | `91a639b` |
| 6 | 6.3 | File formatting (`fling fmt`) and validation (`fling validate`) | `57bf13d` |
| 7 | 7.1 | Documentation (README, CLI ref, format guide, env guide, scripting guide, Postman guide) | |

### Remaining

| Phase | Task | Description |
|-------|------|-------------|
| 7 | 7.2 | CI/CD (GitHub Actions) |

## Conventions

- One commit per implementation task
- Tests live in `tests/` mirroring `src/fling/` structure
- Test fixtures (`.http` files, JSON) live in `tests/fixtures/`
- All core modules are async-first
- Variable interpolation (`{{...}}`) is NOT resolved during parsing — only at execution time
- The parser produces an AST with raw template strings; resolution is a separate pass
- Use `from __future__ import annotations` in all Python files
- Use `TYPE_CHECKING` blocks for type-only imports (ruff TC001/TC003 rules)
- Test classes: `class TestFeatureName:` with methods
- Standard test location stub: `_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)`

## Development Workflow

```bash
# Run all checks before committing
make check

# Or individually
make test       # pytest
make lint       # ruff check
make fmt        # ruff format
make typecheck  # mypy
```

## Known Gotchas

- `.gitignore` blocks `env/` and `.env` patterns — test fixture dirs using those names needed renaming (e.g. `tests/fixtures/env_full/`)
- LSP errors about unresolved imports (`pydantic`, `textual`, `httpx`, `fastapi`, etc.) are false positives — all packages are installed in the venv
- `asyncio_mode = "auto"` in pytest config — no `@pytest.mark.asyncio` decorator needed on async tests
