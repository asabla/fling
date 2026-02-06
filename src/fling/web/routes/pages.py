"""Page routes for the fling web interface.

Serves the main index page, request detail partials, and environment switching.
Supports both single-file and multi-file (directory) modes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fling.core.environment import list_environments, load_environment

if TYPE_CHECKING:
    from fling.core.models import HttpFile, HttpRequestDefinition

router = APIRouter()


def _get_environments(directory: str | None) -> list[str]:
    """Load available environment names from the working directory."""
    if not directory:
        return []
    env_config = load_environment(Path(directory))
    if not env_config:
        return []
    return sorted(list_environments(env_config))


def _get_file(request: Request, file_key: str) -> HttpFile | None:
    """Look up a parsed HttpFile by its key."""
    files: dict[str, HttpFile] = request.app.state.files
    return files.get(file_key)


def _get_requests(http_file: HttpFile | None) -> list[HttpRequestDefinition]:
    """Get the list of requests from an HttpFile."""
    if not http_file:
        return []
    return list(http_file.requests)


def _build_file_tree(files: dict[str, object]) -> list[dict[str, object]]:
    """Build a hierarchical tree structure from file keys.

    Returns a list of tree nodes.  Each node is a dict with:

    * ``name`` — display name (directory or file basename)
    * ``key`` — full relative path (only for files)
    * ``children`` — nested list of nodes (only for directories)
    * ``is_dir`` — whether this node is a directory
    """
    tree: dict[str, object] = {}

    for key in sorted(files.keys()):
        parts = key.split("/")
        node = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Leaf — file
                assert isinstance(node, dict)
                node[part] = key
            else:
                # Directory
                assert isinstance(node, dict)
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]  # type: ignore[assignment]

    def _to_list(d: dict[str, object], prefix: str = "") -> list[dict[str, object]]:
        nodes: list[dict[str, object]] = []
        for name, value in sorted(d.items()):
            if isinstance(value, dict):
                nodes.append(
                    {
                        "name": name,
                        "is_dir": True,
                        "children": _to_list(value, f"{prefix}{name}/"),
                    }
                )
            else:
                nodes.append(
                    {
                        "name": name,
                        "key": value,
                        "is_dir": False,
                    }
                )
        return nodes

    return _to_list(tree)


def _common_context(request: Request) -> dict[str, object]:
    """Build template context shared across pages."""
    files: dict[str, object] = request.app.state.files
    directory: str | None = request.app.state.directory
    env_name: str | None = request.app.state.env_name

    environments = _get_environments(directory)
    file_tree = _build_file_tree(files)

    # Determine display name for the header
    dir_name = Path(directory).name if directory else None

    return {
        "files": files,
        "file_tree": file_tree,
        "dir_name": dir_name,
        "environments": environments,
        "env_name": env_name,
    }


@router.get("/")
async def index(request: Request, env: str | None = None) -> object:
    """Serve the main page with the file tree and request viewer.

    Accepts an optional ``env`` query parameter to switch the active
    environment.
    """
    templates = request.app.state.templates
    files: dict[str, HttpFile] = request.app.state.files

    # Update active environment if provided via query param
    if env is not None:
        request.app.state.env_name = env or None

    ctx = _common_context(request)

    # Auto-select first request of first file
    first_key = next(iter(files), None)
    first_file = files[first_key] if first_key else None
    first_request = first_file.requests[0] if first_file and first_file.requests else None

    # Backward compat: expose flat fields used by old templates
    ctx["file_name"] = first_key
    ctx["requests"] = first_file.requests if first_file else []
    ctx["selected_request"] = first_request
    ctx["selected_index"] = 0 if first_request else None
    ctx["selected_file_key"] = first_key

    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/file/{file_key:path}/request/{index}")
async def get_file_request(request: Request, file_key: str, index: int) -> HTMLResponse:
    """Get the request detail partial for a specific request in a file.

    Returns the request detail HTML plus an out-of-band swap for the
    sidebar so the active item highlighting updates.
    """
    templates = request.app.state.templates
    http_file = _get_file(request, file_key)
    requests_list = _get_requests(http_file)

    if not http_file or index < 0 or index >= len(requests_list):
        detail = templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "selected_request": None,
                "selected_index": None,
                "selected_file_key": None,
            },
        )
        return HTMLResponse(detail.body)

    selected = requests_list[index]

    # Render request detail
    detail_resp = templates.TemplateResponse(
        request,
        "partials/request_detail.html",
        {
            "selected_request": selected,
            "selected_index": index,
            "selected_file_key": file_key,
        },
    )

    # Render updated file tree with new active state (OOB swap)
    ctx = _common_context(request)
    ctx["selected_file_key"] = file_key
    ctx["selected_index"] = index
    # Also pass requests for the selected file (used by collection_tree partial)
    ctx["requests"] = requests_list
    tree_resp = templates.TemplateResponse(
        request,
        "partials/file_tree.html",
        ctx,
    )

    # Render Run All button with updated file_key (OOB swap)
    run_all_resp = templates.TemplateResponse(
        request,
        "partials/run_all_button.html",
        {"selected_file_key": file_key},
    )

    # Combine: main swap content + OOB swaps for tree and Run All button
    detail_html = detail_resp.body.decode()
    tree_html = tree_resp.body.decode()
    run_all_html = run_all_resp.body.decode()

    combined = (
        f"{detail_html}\n"
        f'<div id="file-tree" hx-swap-oob="innerHTML:#sidebar-tree">{tree_html}</div>\n'
        f'<div hx-swap-oob="outerHTML:#run-all-btn">{run_all_html}</div>'
    )

    return HTMLResponse(combined)


# Backward-compat route for single-file mode (used by old tests / bookmarks)
@router.get("/request/{index}")
async def get_request_compat(request: Request, index: int) -> HTMLResponse:
    """Backward-compatible request detail route.

    Resolves the first file and delegates to the multi-file handler.
    """
    files: dict[str, HttpFile] = request.app.state.files
    first_key = next(iter(files), None)

    if not first_key:
        templates = request.app.state.templates
        detail = templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "selected_request": None,
                "selected_index": None,
                "selected_file_key": None,
            },
        )
        return HTMLResponse(detail.body)

    return await get_file_request(request, first_key, index)


@router.get("/env")
async def switch_env(request: Request, env: str = "") -> object:
    """Switch the active environment and redirect back to the index.

    This is an HTMX endpoint used by the environment selector dropdown.
    For HTMX requests, returns an HX-Redirect header so the page reloads
    cleanly without killing SSE connections.  For normal requests, returns
    a standard HTTP redirect.
    """
    request.app.state.env_name = env or None

    target = f"/?env={env}" if env else "/"

    # HTMX request — use HX-Redirect header
    if request.headers.get("hx-request"):
        return HTMLResponse(content="", headers={"HX-Redirect": target})

    # Non-HTMX — standard redirect
    from starlette.responses import RedirectResponse

    return RedirectResponse(url=target, status_code=302)
