"""Execution routes for the fling web interface.

Handles running individual HTTP requests with SSE streaming for real-time
progress updates, response headers, body, and timing information.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from fling.core.environment import load_environment
from fling.core.models import HttpFile as HttpFileModel
from fling.core.runner import HttpRunner

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fling.core.models import ExecutionResult, HttpRequestDefinition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execute")


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


def _build_response_html(result: ExecutionResult) -> str:
    """Build the full response panel HTML from an execution result."""
    if result.error:
        return (
            '<div class="p-4">'
            '<div class="flex items-center gap-2 mb-4">'
            '<span class="text-status-error font-bold text-lg">Error</span>'
            "</div>"
            f'<pre class="bg-surface-light rounded p-3 text-sm text-status-error">'
            f"{html.escape(result.error)}</pre>"
            "</div>"
        )

    status_class = _status_class(result.status_code)
    elapsed = _format_elapsed(result.elapsed_ms)
    size = _format_size(result.response_body)

    # Status bar
    status_html = (
        '<div class="flex items-center gap-3 mb-4">'
        f'<span class="{status_class} font-bold text-lg">{result.status_code}</span>'
        f'<span class="text-accent-dim text-sm">{elapsed}</span>'
        f'<span class="text-accent-dim text-sm">{size}</span>'
        "</div>"
    )

    # Tabs
    tabs_html = (
        '<div data-tab-group="response-tabs">'
        '<div class="flex border-b border-surface-lighter mb-3">'
        '<button class="tab-btn active px-3 py-1.5 text-sm" data-tab="body" '
        "onclick=\"switchTab('response-tabs', 'body')\">Body</button>"
        '<button class="tab-btn px-3 py-1.5 text-sm" data-tab="headers" '
        "onclick=\"switchTab('response-tabs', 'headers')\">"
        f"Headers ({len(result.response_headers)})</button>"
        "</div>"
    )

    # Body tab
    content_types = result.response_headers.get("content-type", [])
    language = _detect_language(content_types, result.response_body)
    formatted_body = _format_body(result.response_body, language)
    escaped_body = html.escape(formatted_body)

    lang_class = f" language-{language}" if language else ""
    body_html = (
        '<div class="tab-content active" data-tab="body">'
        f'<pre class="bg-surface-light rounded p-3 overflow-x-auto">'
        f'<code class="text-sm font-mono{lang_class}">{escaped_body}</code></pre>'
        "</div>"
    )

    # Headers tab
    headers_rows = ""
    for h_name, h_values in result.response_headers.items():
        for h_val in h_values:
            headers_rows += (
                f'<tr class="border-b border-surface-lighter/50">'
                f'<td class="py-1 pr-4 text-accent font-mono">{html.escape(h_name)}</td>'
                f'<td class="py-1 font-mono text-accent-dim">{html.escape(h_val)}</td>'
                f"</tr>"
            )

    headers_html = (
        '<div class="tab-content" data-tab="headers">'
        '<table class="w-full text-sm">'
        "<thead>"
        '<tr class="text-left text-accent-dim text-xs border-b border-surface-lighter">'
        '<th class="pb-1 pr-4 font-medium">Name</th>'
        '<th class="pb-1 font-medium">Value</th>'
        "</tr>"
        "</thead>"
        f"<tbody>{headers_rows}</tbody>"
        "</table>"
        "</div>"
    )

    return f'<div class="p-4">{status_html}{tabs_html}{body_html}{headers_html}</div></div>'


@router.get("/{index}")
async def execute_request(request: Request, index: int) -> EventSourceResponse:
    """Execute a single request by index and stream results via SSE.

    Streams the following named events:
    - ``progress``: Execution progress updates (preparing, sending, etc.)
    - ``response``: Full response HTML for the response panel
    - ``complete``: Final signal indicating execution is done

    Args:
        request: The FastAPI request object.
        index: Zero-based index of the request to execute.

    Returns:
        SSE event stream.
    """
    http_file = request.app.state.http_file
    file_path = request.app.state.file_path
    env_name = request.app.state.env_name

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
        if file_path:
            env_config = load_environment(Path(file_path).parent)

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
            # Send full response HTML
            yield {
                "event": "response",
                "data": _build_response_html(result),
            }

        yield {"event": "complete", "data": "done"}

    return EventSourceResponse(event_generator())


def _progress_html(message: str) -> str:
    """Build HTML for a progress indicator."""
    return (
        '<div class="flex items-center justify-center h-full p-4">'
        '<div class="text-center space-y-2">'
        f'<p class="text-accent sse-loading">{html.escape(message)}</p>'
        "</div></div>"
    )
