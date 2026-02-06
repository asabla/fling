"""Page routes for the fling web interface.

Serves the main index page, request detail partials, and environment switching.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fling.core.environment import list_environments, load_environment

if TYPE_CHECKING:
    from fling.core.models import HttpRequestDefinition

router = APIRouter()


def _get_environments(file_path: str | None) -> list[str]:
    """Load available environment names for the given file path."""
    if not file_path:
        return []
    env_dir = Path(file_path).parent
    env_config = load_environment(str(env_dir))
    if not env_config:
        return []
    return sorted(list_environments(env_config))


def _get_requests(request: Request) -> list[HttpRequestDefinition]:
    """Get the list of requests from the loaded HTTP file."""
    http_file = request.app.state.http_file
    if not http_file:
        return []
    return list(http_file.requests)


@router.get("/")
async def index(request: Request, env: str | None = None) -> object:
    """Serve the main page with the collection tree and request viewer.

    Accepts an optional ``env`` query parameter to switch the active
    environment.
    """
    templates = request.app.state.templates
    http_file = request.app.state.http_file
    file_path = request.app.state.file_path

    # Update active environment if provided via query param
    if env is not None:
        request.app.state.env_name = env or None

    env_name = request.app.state.env_name

    requests_list = http_file.requests if http_file else []
    file_name = Path(file_path).name if file_path else None

    environments = _get_environments(file_path)

    # Select first request by default
    first_request = requests_list[0] if requests_list else None

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "file_name": file_name,
            "requests": requests_list,
            "selected_request": first_request,
            "selected_index": 0 if first_request else None,
            "environments": environments,
            "env_name": env_name,
        },
    )


@router.get("/request/{index}")
async def get_request(request: Request, index: int) -> HTMLResponse:
    """Get the request detail partial for a specific request.

    Returns the request detail HTML plus an out-of-band swap for the
    collection tree so the active item highlighting updates.
    """
    templates = request.app.state.templates
    http_file = request.app.state.http_file
    requests_list = _get_requests(request)

    if not http_file or index < 0 or index >= len(requests_list):
        detail = templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "selected_request": None,
                "selected_index": None,
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
        },
    )

    # Render updated collection tree with new active state (OOB swap)
    tree_resp = templates.TemplateResponse(
        request,
        "partials/collection_tree.html",
        {
            "requests": requests_list,
            "selected_index": index,
        },
    )

    # Combine: main swap content + OOB swap for tree
    detail_html = detail_resp.body.decode()
    tree_html = tree_resp.body.decode()

    combined = (
        f"{detail_html}\n"
        f'<div id="collection-tree" hx-swap-oob="innerHTML:#sidebar .p-3">'
        f'<h2 class="text-xs font-semibold uppercase tracking-wider text-accent-dim mb-2">Requests</h2>'
        f"{tree_html}</div>"
    )

    return HTMLResponse(combined)


@router.get("/env")
async def switch_env(request: Request, env: str = "") -> object:
    """Switch the active environment and return the full page.

    This is an HTMX endpoint used by the environment selector dropdown.
    """
    request.app.state.env_name = env or None

    templates = request.app.state.templates
    http_file = request.app.state.http_file
    file_path = request.app.state.file_path
    env_name = request.app.state.env_name

    requests_list = http_file.requests if http_file else []
    file_name = Path(file_path).name if file_path else None

    environments = _get_environments(file_path)

    first_request = requests_list[0] if requests_list else None

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "file_name": file_name,
            "requests": requests_list,
            "selected_request": first_request,
            "selected_index": 0 if first_request else None,
            "environments": environments,
            "env_name": env_name,
        },
    )
