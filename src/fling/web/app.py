"""FastAPI web application for fling.

Provides a web-based interface for viewing and executing .http files
using HTMX for interactivity and SSE for streaming execution results.

Supports live file watching: when a directory is monitored, ``.http``
file changes are detected automatically and pushed to connected
browsers via SSE so the sidebar refreshes without a manual reload.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncGenerator

    from fling.core.models import HttpFile
    from fling.web.watcher import FileWatcher

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the file-watcher and history-database lifecycles."""
    watcher: FileWatcher | None = app.state.watcher
    if watcher is not None:
        watcher.start()
    try:
        yield
    finally:
        if watcher is not None:
            await watcher.stop()
        # Close the history database connection if open
        history_conn: sqlite3.Connection | None = getattr(app.state, "history_conn", None)
        if history_conn is not None:
            history_conn.close()


def create_app(
    file_path: str | None = None,
    directory: str | None = None,
    env_name: str | None = None,
    *,
    watch: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Supports two modes:

    * **Single-file mode** — pass ``file_path`` to serve one ``.http`` file.
    * **Directory mode** — pass ``directory`` (or omit both) to scan a
      directory tree for ``.http`` files.

    Args:
        file_path: Path to a single .http file to load.
        directory: Root directory to scan for .http files.
        env_name: Active environment name.
        watch: Enable live file watching in directory mode (default ``True``).

    Returns:
        Configured FastAPI application.
    """
    from fling.web.scanner import scan_directory, scan_single_file

    app = FastAPI(
        title="fling",
        description="HTTP API Testing",
        lifespan=_lifespan,
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Scan / parse files
    files: dict[str, HttpFile] = {}
    resolved_dir: str | None = None

    if file_path:
        files = scan_single_file(file_path)
        resolved_dir = str(Path(file_path).resolve().parent)
    elif directory:
        files = scan_directory(directory)
        resolved_dir = str(Path(directory).resolve())

    # Store shared state on app
    app.state.templates = templates
    app.state.env_name = env_name
    app.state.directory = resolved_dir
    app.state.files = files

    # Backward-compat helpers (used by existing routes / tests)
    app.state.file_path = file_path
    first_key = next(iter(files), None)
    app.state.http_file = files[first_key] if first_key else None

    # File watcher (directory mode only)
    watcher: FileWatcher | None = None
    if directory and resolved_dir and watch:
        from fling.web.watcher import FileWatcher as _FileWatcher

        watcher = _FileWatcher(resolved_dir, files)
    app.state.watcher = watcher

    # Execution history database
    from fling.web.history import init_db as _init_history_db

    history_conn = None
    if resolved_dir:
        try:
            history_conn = _init_history_db(resolved_dir)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Could not initialise history database", exc_info=True)
    app.state.history_conn = history_conn

    # Register routes
    from fling.web.routes.compare import router as compare_router
    from fling.web.routes.environments import router as environments_router
    from fling.web.routes.execution import router as execution_router
    from fling.web.routes.history import router as history_router
    from fling.web.routes.pages import router as pages_router
    from fling.web.routes.watch import router as watch_router

    app.include_router(pages_router)
    app.include_router(environments_router)
    app.include_router(history_router)
    app.include_router(compare_router)
    app.include_router(execution_router)
    app.include_router(watch_router)

    return app
