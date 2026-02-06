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
├── cli.py                   # Click CLI entry point
├── core/
│   ├── models.py            # Pydantic v2 data models
│   ├── parser.py            # .http file parser (line-by-line state machine)
│   ├── variables.py         # Variable resolution engine
│   ├── executor.py          # HTTP execution (httpx async)
│   ├── runner.py            # Orchestrator (parse -> resolve -> execute)
│   ├── environment.py       # Environment file loading
│   ├── scripting.py         # Python-based response handlers
│   └── postman.py           # Postman collection converter
├── tui/                     # Textual TUI (read-only runner)
│   ├── app.py
│   ├── screens/
│   ├── widgets/
│   └── styles/
└── web/                     # FastAPI + HTMX web interface
    ├── app.py
    ├── routes/
    ├── templates/
    └── static/
```

## Technical Decisions

- **Python**: 3.12+ minimum
- **Async**: Fully async core using `httpx.AsyncClient`
- **Build**: `uv_build` backend, installable via `pip install fling`
- **Testing**: `pytest` + `pytest-asyncio` + `pytest-httpx`, tests alongside code
- **Linting**: `ruff` for linting and formatting
- **Type checking**: `mypy`
- **Dependencies**: Click, httpx, Rich, Pydantic v2, jsonpath-ng, python-dotenv
- **Optional extras**: `fling[tui]` (Textual), `fling[web]` (FastAPI+HTMX), `fling[all]`

## Conventions

- One commit per implementation task
- Tests live in `tests/` mirroring `src/fling/` structure
- Test fixtures (`.http` files, JSON) live in `tests/fixtures/`
- All core modules are async-first
- Variable interpolation (`{{...}}`) is NOT resolved during parsing — only at execution time
- The parser produces an AST with raw template strings; resolution is a separate pass
