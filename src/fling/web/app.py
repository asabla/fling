"""FastAPI web application for fling.

Provides a web-based interface for viewing and executing .http files
using HTMX for interactivity and SSE for streaming execution results.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from fling.core.models import HttpFile

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


def create_app(
    file_path: str | None = None,
    env_name: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        file_path: Path to the .http file to load.
        env_name: Active environment name.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="fling",
        description="HTTP API Testing",
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Store shared state on app
    app.state.templates = templates
    app.state.file_path = file_path
    app.state.env_name = env_name
    app.state.http_file = None

    if file_path:
        app.state.http_file = _load_file(file_path)

    # Register routes
    from fling.web.routes.execution import router as execution_router
    from fling.web.routes.pages import router as pages_router

    app.include_router(pages_router)
    app.include_router(execution_router)

    return app


def _load_file(file_path: str) -> HttpFile | None:
    """Parse an .http file and return the result.

    Args:
        file_path: Path to the .http file.

    Returns:
        Parsed HttpFile or None if parsing failed.
    """
    from fling.core.parser import parse_http_file

    try:
        result = parse_http_file(file_path)
    except (FileNotFoundError, OSError):
        return None
    if result.has_errors:
        return None
    return result.http_file
