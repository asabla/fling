"""Execution history routes for the fling web interface.

Provides endpoints for viewing, listing, and deleting past execution
records.  Records are persisted in a lightweight SQLite database
located in ``.fling/history.db`` within the project directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from fling.web.history import (
    count_records,
    delete_record,
    get_record,
    list_records,
)

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history")

# ---------------------------------------------------------------------------
# Jinja2 template helper (identical pattern to execution.py)
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
# Helpers
# ---------------------------------------------------------------------------


def _get_history_conn(request: Request) -> sqlite3.Connection:
    """Return the history database connection or raise 400."""
    conn: sqlite3.Connection | None = getattr(request.app.state, "history_conn", None)
    if conn is None:
        raise HTTPException(status_code=400, detail="History database not available")
    return conn


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def history_list(
    request: Request,
    file_key: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> HTMLResponse:
    """List execution history records, newest first.

    Returns an HTML partial for the history panel.

    Query params:
        file_key: Filter by file key.
        page: Page number (1-based).
        per_page: Number of records per page.
    """
    conn = _get_history_conn(request)

    offset = (max(page, 1) - 1) * per_page
    records = list_records(conn, file_key=file_key, limit=per_page, offset=offset)
    total = count_records(conn)

    html = _render(
        "partials/history_list.html",
        records=records,
        total=total,
        page=page,
        per_page=per_page,
        file_key=file_key,
    )
    return HTMLResponse(html)


@router.get("/{record_id}")
async def history_detail(request: Request, record_id: str) -> HTMLResponse:
    """Get a single execution history record.

    Returns an HTML partial with the full execution detail.
    """
    conn = _get_history_conn(request)
    record = get_record(conn, record_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    html = _render(
        "partials/history_detail.html",
        record=record,
    )
    return HTMLResponse(html)


@router.delete("/{record_id}")
async def history_delete(request: Request, record_id: str) -> HTMLResponse:
    """Delete a single execution history record.

    Returns the updated history list.
    """
    conn = _get_history_conn(request)

    if not delete_record(conn, record_id):
        raise HTTPException(status_code=404, detail="Record not found")

    # Return the refreshed list
    records = list_records(conn, limit=50, offset=0)
    total = count_records(conn)

    html = _render(
        "partials/history_list.html",
        records=records,
        total=total,
        page=1,
        per_page=50,
        file_key=None,
    )
    return HTMLResponse(html)
