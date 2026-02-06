"""Response comparison routes for the fling web interface.

Provides a side-by-side comparison view of two execution history records,
including text and structural JSON diffs of their response bodies.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from fling.web.diff import DiffKind, json_diff, text_diff
from fling.web.history import get_record

if TYPE_CHECKING:
    import sqlite3

    from fling.core.models import ExecutionRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compare")

# ---------------------------------------------------------------------------
# Jinja2 template helper
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


def _load_record(conn: sqlite3.Connection, record_id: str, label: str) -> ExecutionRecord:
    """Load a record by ID or raise 404."""
    record = get_record(conn, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} record '{record_id}' not found")
    return record


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("")
async def compare_records(
    request: Request,
    left: str,
    right: str,
) -> HTMLResponse:
    """Compare two execution history records side-by-side.

    Query params:
        left: ID of the left (baseline) record.
        right: ID of the right (comparison) record.
    """
    conn = _get_history_conn(request)
    left_record = _load_record(conn, left, "Left")
    right_record = _load_record(conn, right, "Right")

    # Compute text diff of response bodies
    left_body = left_record.result.response_body or ""
    right_body = right_record.result.response_body or ""
    body_diff = text_diff(left_body, right_body)

    # Attempt JSON diff if both bodies are valid JSON
    json_diff_result = None
    if left_body.strip() and right_body.strip():
        with contextlib.suppress(ValueError):
            json_diff_result = json_diff(left_body, right_body)

    html_content = _render(
        "partials/compare.html",
        left_record=left_record,
        right_record=right_record,
        body_diff=body_diff,
        json_diff=json_diff_result,
        DiffKind=DiffKind,
    )
    return HTMLResponse(html_content)
