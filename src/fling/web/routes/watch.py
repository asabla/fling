"""Watch routes for the fling web interface.

Provides a Server-Sent Events (SSE) endpoint that streams file-change
notifications to connected browsers so the sidebar auto-refreshes when
``.http`` files are created, modified, or deleted on disk.

Also provides a ``POST /reload`` endpoint for explicit manual re-scans.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fling.web.watcher import FileWatcher

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_sidebar_html(request: Request) -> str:
    """Render the file-tree partial and return it as an HTML string."""
    from fling.web.routes.pages import _common_context

    templates = request.app.state.templates
    ctx = _common_context(request)
    # No specific selection after a file change — clear active state
    ctx["selected_file_key"] = None
    ctx["selected_index"] = None
    ctx["requests"] = []

    resp = templates.TemplateResponse(
        request,
        "partials/file_tree.html",
        ctx,
    )
    return str(resp.body.decode())


# ---------------------------------------------------------------------------
# SSE endpoint — file-change stream
# ---------------------------------------------------------------------------


@router.get("/events/files")
async def file_events(request: Request) -> EventSourceResponse:
    """Stream file-change events to the browser via SSE.

    Each event carries the updated sidebar HTML so HTMX can swap it in.
    The SSE event name is ``file-change`` so the template can target it
    with ``sse-swap="file-change"``.

    If file watching is disabled (single-file mode) the connection stays
    open but idle — no events are emitted.
    """
    watcher: FileWatcher | None = request.app.state.watcher

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        if watcher is None:
            # No watcher — keep connection open but idle.
            # The SSE listener in the template still connects even in
            # single-file mode; we just sit here until the client leaves.
            try:
                while True:
                    await asyncio.sleep(30)
                    if await request.is_disconnected():
                        return
            except (asyncio.CancelledError, Exception):
                return

        from fling.web.watcher import watch_events

        async for event in watch_events(watcher):
            sidebar_html = _render_sidebar_html(request)

            # Push the sidebar HTML as the main event data
            yield {
                "event": "file-change",
                "data": sidebar_html,
            }

            # Also push a lightweight JSON payload with change details
            # (useful for JS-side logic, e.g. toast notifications)
            yield {
                "event": "file-change-meta",
                "data": json.dumps(
                    {
                        "type": event.change_type,
                        "file": event.file_key,
                    }
                ),
            }

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Manual reload endpoint
# ---------------------------------------------------------------------------


@router.post("/reload", response_model=None)
async def reload_files(request: Request) -> Response:
    """Manually re-scan the directory and return the updated sidebar.

    If the ``Accept`` header includes ``text/html`` the response is the
    rendered file-tree partial; otherwise a JSON summary is returned.
    """
    watcher: FileWatcher | None = request.app.state.watcher

    if watcher is not None:
        events = watcher.reload_all()
        logger.info("Reload: %d change(s) detected", len(events))
    else:
        file_path: str | None = request.app.state.file_path
        directory: str | None = request.app.state.directory

        if file_path:
            # Single-file mode — just re-parse the single file
            from fling.web.scanner import scan_single_file

            new_files = scan_single_file(file_path)
            request.app.state.files.clear()
            request.app.state.files.update(new_files)
        elif directory:
            # Directory mode without watcher — full re-scan
            from fling.web.scanner import scan_directory

            new_files = scan_directory(directory)
            request.app.state.files.clear()
            request.app.state.files.update(new_files)

    # Update backward-compat state
    files = request.app.state.files
    first_key = next(iter(files), None)
    request.app.state.http_file = files[first_key] if first_key else None

    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        sidebar_html = _render_sidebar_html(request)
        return HTMLResponse(sidebar_html)

    file_count = len(request.app.state.files)
    return JSONResponse({"status": "ok", "files": file_count})
