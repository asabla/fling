"""Execution routes for the fling web interface.

Handles running individual HTTP requests with SSE streaming for real-time
progress updates, response headers, body, and timing information.
Also provides a collection runner that executes all requests with a
streaming execution log.

Supports both single-file and multi-file (directory) modes.
"""

from __future__ import annotations

import html
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from sse_starlette.sse import EventSourceResponse

from fling.core.environment import load_environment
from fling.core.models import ExecutionRecord
from fling.core.models import HttpFile as HttpFileModel
from fling.core.runner import HttpRunner
from fling.web.history import prune_old, save_record

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncGenerator

    from fling.core.models import ExecutionResult, HttpRequestDefinition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execute")

# ---------------------------------------------------------------------------
# Template environment for rendering execution HTML fragments
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


def _render(template_name: str, **ctx: object) -> str:
    """Render a Jinja2 template to a string."""
    return _jinja_env.get_template(template_name).render(**ctx)


# ---------------------------------------------------------------------------
# Helpers — formatting
# ---------------------------------------------------------------------------


def _status_class(code: int) -> str:
    """Return a Tailwind CSS color class for an HTTP status code."""
    if code < 300:
        return "text-status-success"
    if code < 400:
        return "text-status-redirect"
    return "text-status-error"


def _format_elapsed(ms: float) -> str:
    """Format elapsed milliseconds for display."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _format_size(body: str) -> str:
    """Format response body size for display."""
    size = len(body.encode("utf-8"))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _detect_language(content_types: list[str], body: str) -> str:
    """Detect syntax highlighting language from content type."""
    for ct in content_types:
        if "json" in ct:
            return "json"
        if "xml" in ct or "html" in ct:
            return "markup"
        if "yaml" in ct or "yml" in ct:
            return "yaml"

    # Heuristic fallback
    stripped = body.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        return "json"
    if stripped.startswith("<"):
        return "markup"
    return ""


def _format_body(body: str, language: str) -> str:
    """Pretty-format body content if possible."""
    if language == "json":
        try:
            parsed = json.loads(body)
            return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, ValueError):
            pass
    return body


# ---------------------------------------------------------------------------
# Helpers — HTML builders (now backed by Jinja2 templates)
# ---------------------------------------------------------------------------


def _build_response_html(result: ExecutionResult) -> str:
    """Build the full response panel HTML from an execution result."""
    if result.error:
        return _render(
            "partials/response_content.html",
            error=Markup(html.escape(result.error)),
        )

    content_types = result.response_headers.get("content-type", [])
    language = _detect_language(content_types, result.response_body)
    formatted_body = _format_body(result.response_body, language)

    # Flatten headers into (name, value) pairs — pre-escape for exact compat
    header_rows: list[tuple[Markup, Markup]] = []
    for h_name, h_values in result.response_headers.items():
        for h_val in h_values:
            header_rows.append((Markup(html.escape(h_name)), Markup(html.escape(h_val))))

    return _render(
        "partials/response_content.html",
        error=None,
        status_class=_status_class(result.status_code),
        status_code=result.status_code,
        elapsed=_format_elapsed(result.elapsed_ms),
        size=_format_size(result.response_body),
        language=language,
        formatted_body=Markup(html.escape(formatted_body)),
        header_count=len(result.response_headers),
        header_rows=header_rows,
    )


def _log_entry_html(
    request_def: HttpRequestDefinition,
    result: ExecutionResult,
    index: int,
) -> str:
    """Build HTML for a single execution log entry."""
    name = request_def.metadata.name or request_def.url
    method = request_def.method.value

    return _render(
        "partials/log_entry.html",
        timestamp=time.strftime("%H:%M:%S"),
        method=method,
        name=Markup(html.escape(name)),
        error=result.error,
        status_class=_status_class(result.status_code) if not result.error else "",
        status_code=result.status_code,
        elapsed=_format_elapsed(result.elapsed_ms),
        index=index,
    )


def _summary_html(
    total: int,
    completed: int,
    passed: int,
    failed: int,
    total_ms: float,
) -> str:
    """Build HTML for the execution summary counter."""
    return _render(
        "partials/summary.html",
        total=total,
        completed=completed,
        passed=passed,
        failed=failed,
        elapsed=_format_elapsed(total_ms),
    )


def _log_start_html() -> str:
    """Build HTML to clear the log and show a starting message."""
    return _render(
        "partials/log_start.html",
        timestamp=time.strftime("%H:%M:%S"),
    )


def _progress_html(message: str) -> str:
    """Build HTML for a progress indicator."""
    return _render(
        "partials/progress.html",
        message=message,
    )


# ---------------------------------------------------------------------------
# Helpers — resolve file context
# ---------------------------------------------------------------------------


def _resolve_file(
    request: Request, file_key: str | None = None
) -> tuple[HttpFileModel | None, Path | None, str | None]:
    """Resolve an HttpFile, its directory, and the active env name.

    When *file_key* is given the file is looked up from ``app.state.files``;
    otherwise the legacy ``app.state.http_file`` / ``app.state.file_path``
    attributes are used (backward-compat single-file mode).

    Returns:
        ``(http_file, env_dir, env_name)`` — any may be ``None``.
    """
    env_name: str | None = request.app.state.env_name
    directory: str | None = request.app.state.directory

    if file_key is not None:
        files: dict[str, HttpFileModel] = request.app.state.files
        http_file = files.get(file_key)
        env_dir = Path(directory) if directory else None
        return http_file, env_dir, env_name

    # Legacy single-file mode
    http_file = request.app.state.http_file
    file_path: str | None = request.app.state.file_path
    env_dir = Path(file_path).parent if file_path else None
    return http_file, env_dir, env_name


# ---------------------------------------------------------------------------
# Multi-file routes
# ---------------------------------------------------------------------------


@router.get("/{file_key:path}/all")
async def execute_file_all(request: Request, file_key: str) -> EventSourceResponse:
    """Execute all requests in a specific file, streaming results via SSE."""
    http_file, env_dir, env_name = _resolve_file(request, file_key)
    history_conn: sqlite3.Connection | None = getattr(request.app.state, "history_conn", None)
    return _execute_all_impl(http_file, env_dir, env_name, file_key=file_key, history_conn=history_conn)


@router.get("/{file_key:path}/request/{index}")
async def execute_file_request(request: Request, file_key: str, index: int) -> EventSourceResponse:
    """Execute a single request from a specific file via SSE."""
    http_file, env_dir, env_name = _resolve_file(request, file_key)
    history_conn: sqlite3.Connection | None = getattr(request.app.state, "history_conn", None)
    return _execute_request_impl(http_file, env_dir, env_name, index, file_key=file_key, history_conn=history_conn)


# ---------------------------------------------------------------------------
# Backward-compat routes (single-file mode)
# ---------------------------------------------------------------------------


@router.get("/all")
async def execute_all(request: Request) -> EventSourceResponse:
    """Execute all requests and stream results as an execution log via SSE.

    Backward-compatible route — uses the first (or only) loaded file.
    """
    http_file, env_dir, env_name = _resolve_file(request)
    history_conn: sqlite3.Connection | None = getattr(request.app.state, "history_conn", None)
    return _execute_all_impl(http_file, env_dir, env_name, history_conn=history_conn)


@router.get("/{index}")
async def execute_request(request: Request, index: int) -> EventSourceResponse:
    """Execute a single request by index and stream results via SSE.

    Backward-compatible route — uses the first (or only) loaded file.
    """
    http_file, env_dir, env_name = _resolve_file(request)
    history_conn: sqlite3.Connection | None = getattr(request.app.state, "history_conn", None)
    return _execute_request_impl(http_file, env_dir, env_name, index, history_conn=history_conn)


# ---------------------------------------------------------------------------
# Shared implementation
# ---------------------------------------------------------------------------


def _execute_all_impl(
    http_file: HttpFileModel | None,
    env_dir: Path | None,
    env_name: str | None,
    *,
    file_key: str | None = None,
    history_conn: sqlite3.Connection | None = None,
) -> EventSourceResponse:
    """Shared implementation for execute-all routes."""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        if not http_file or not http_file.requests:
            yield {
                "event": "log",
                "data": '<div class="px-2 py-1 text-sm text-status-error">No requests to execute.</div>',
            }
            yield {"event": "complete", "data": "done"}
            return

        total = len([r for r in http_file.requests if not r.metadata.disabled])

        # Clear log and show start message
        yield {
            "event": "log",
            "data": _log_start_html(),
        }

        # Load environment
        env_config = None
        if env_dir:
            env_config = load_environment(env_dir)

        runner = HttpRunner(env_file=env_config, env_name=env_name)

        completed = 0
        passed = 0
        failed = 0
        total_ms = 0.0

        async for req_def, result in runner.run_all(http_file):
            completed += 1
            total_ms += result.elapsed_ms

            if result.error or result.status_code >= 400:
                failed += 1
            else:
                passed += 1

            # Save to history
            _save_to_history(
                history_conn,
                result,
                env_name=env_name,
                file_key=file_key,
                request_index=completed - 1,
                request_name=req_def.metadata.name,
            )

            # Stream log entry
            yield {
                "event": "log",
                "data": _log_entry_html(req_def, result, completed - 1),
            }

            # Stream updated summary via OOB swap
            yield {
                "event": "summary",
                "data": (
                    f'<div id="execution-summary" hx-swap-oob="innerHTML:#execution-summary">'
                    f"{_summary_html(total, completed, passed, failed, total_ms)}"
                    f"</div>"
                ),
            }

        yield {"event": "complete", "data": "done"}

    return EventSourceResponse(event_generator())


def _execute_request_impl(
    http_file: HttpFileModel | None,
    env_dir: Path | None,
    env_name: str | None,
    index: int,
    *,
    file_key: str | None = None,
    history_conn: sqlite3.Connection | None = None,
) -> EventSourceResponse:
    """Shared implementation for execute-single-request routes."""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        if not http_file or index < 0 or index >= len(http_file.requests):
            yield {
                "event": "response",
                "data": '<div class="p-4 text-status-error">Request not found.</div>',
            }
            yield {"event": "complete", "data": "done"}
            return

        target_request: HttpRequestDefinition = http_file.requests[index]

        # Send initial progress
        yield {
            "event": "progress",
            "data": _progress_html("Preparing request..."),
        }

        # Load environment
        env_config = None
        if env_dir:
            env_config = load_environment(env_dir)

        # Build runner
        runner_kwargs: dict[str, Any] = {
            "env_file": env_config,
            "env_name": env_name,
        }
        runner = HttpRunner(**runner_kwargs)

        # Execute: if named, use run_single (handles deps); otherwise run directly
        yield {
            "event": "progress",
            "data": _progress_html("Sending request..."),
        }

        result: ExecutionResult | None = None
        if target_request.metadata.name:
            async for _req, res in runner.run_single(http_file, target_request.metadata.name):
                result = res
        else:
            # For unnamed requests, create a single-request file
            single_file = HttpFileModel(
                file_path=http_file.file_path,
                variables=http_file.variables,
                requests=[target_request],
            )
            async for _req, res in runner.run_all(single_file):
                result = res

        if result is None:
            yield {
                "event": "response",
                "data": '<div class="p-4 text-status-error">No result returned.</div>',
            }
        else:
            # Save to history
            _save_to_history(
                history_conn,
                result,
                env_name=env_name,
                file_key=file_key,
                request_index=index,
                request_name=target_request.metadata.name,
            )

            # Send full response HTML
            yield {
                "event": "response",
                "data": _build_response_html(result),
            }

        yield {"event": "complete", "data": "done"}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _save_to_history(
    conn: sqlite3.Connection | None,
    result: ExecutionResult,
    *,
    env_name: str | None,
    file_key: str | None,
    request_index: int,
    request_name: str | None,
) -> None:
    """Persist an execution result to the history database (best-effort)."""
    if conn is None:
        return
    try:
        record = ExecutionRecord(
            env_name=env_name,
            file_key=file_key,
            request_index=request_index,
            request_name=request_name,
            result=result,
        )
        save_record(conn, record)
        prune_old(conn)
    except Exception:
        logger.warning("Failed to save execution record to history", exc_info=True)
