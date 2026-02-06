"""Page routes for the fling web interface.

Serves the main index page and handles full-page navigation.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from fling.core.environment import list_environments, load_environment

router = APIRouter()


@router.get("/")
async def index(request: Request) -> object:
    """Serve the main page with the collection tree and request viewer."""
    templates = request.app.state.templates
    http_file = request.app.state.http_file
    file_path = request.app.state.file_path
    env_name = request.app.state.env_name

    requests_list = http_file.requests if http_file else []
    file_name = Path(file_path).name if file_path else None

    # Load available environments
    environments: list[str] = []
    if file_path:
        env_dir = Path(file_path).parent
        env_config = load_environment(str(env_dir))
        if env_config:
            environments = sorted(list_environments(env_config))

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
async def get_request(request: Request, index: int) -> object:
    """Get the request detail partial for a specific request.

    Returns an HTMX partial for the request editor panel.
    """
    templates = request.app.state.templates
    http_file = request.app.state.http_file

    if not http_file or index < 0 or index >= len(http_file.requests):
        return templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "selected_request": None,
                "selected_index": None,
            },
        )

    selected = http_file.requests[index]
    return templates.TemplateResponse(
        request,
        "partials/request_detail.html",
        {
            "selected_request": selected,
            "selected_index": index,
        },
    )
