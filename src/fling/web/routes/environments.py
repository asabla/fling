"""Environment CRUD routes for the fling web interface.

Provides endpoints for listing, viewing, creating, updating, and deleting
environments and their variables.  Only the **public** environment file
(``http-client.env.json``) is modified — the private file is never touched.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from fling.core.environment import (
    SHARED_ENV_KEY,
    load_environment,
    save_environment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/environments")

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
# Request / response bodies
# ---------------------------------------------------------------------------


class VariablePayload(BaseModel):
    """A single variable key-value pair."""

    name: str
    value: Any = ""


class EnvironmentPayload(BaseModel):
    """Payload for creating or updating an environment."""

    name: str = ""
    variables: list[VariablePayload] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_directory(request: Request) -> Path:
    """Return the project directory or raise 400 if not configured."""
    directory: str | None = request.app.state.directory
    if not directory:
        raise HTTPException(status_code=400, detail="No project directory configured")
    return Path(directory)


def _load_public_env(directory: Path) -> dict[str, dict[str, Any]]:
    """Load the environment file and return only the public environments.

    Strips runtime-only keys like ``_dotenv`` so we only deal with data
    that can be round-tripped through ``save_environment()``.
    """
    env_file = load_environment(directory)
    # Filter out _dotenv — it comes from .env files, not the JSON
    envs = {k: dict(v) for k, v in env_file.environments.items() if k != "_dotenv"}
    return envs


def _visible_env_names(envs: dict[str, dict[str, Any]]) -> list[str]:
    """Return sorted visible (non-internal) environment names."""
    return sorted(name for name in envs if not name.startswith("_"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_envs(request: Request) -> HTMLResponse:
    """List all environments with their variables.

    Returns an HTML partial for the environment editor panel.
    """
    directory = _get_directory(request)
    envs = _load_public_env(directory)
    env_names = _visible_env_names(envs)
    shared = envs.get(SHARED_ENV_KEY, {})

    html = _render(
        "partials/env_editor.html",
        env_names=env_names,
        environments=envs,
        shared=shared,
    )
    return HTMLResponse(html)


@router.get("/{env_name}")
async def get_env(request: Request, env_name: str) -> HTMLResponse:
    """Get a single environment's variables for editing.

    Returns an HTML partial with the environment's variable rows.
    """
    directory = _get_directory(request)
    envs = _load_public_env(directory)

    if env_name not in envs:
        raise HTTPException(status_code=404, detail=f"Environment '{env_name}' not found")

    variables = envs[env_name]
    html = _render(
        "partials/env_variables.html",
        env_name=env_name,
        variables=variables,
    )
    return HTMLResponse(html)


@router.post("")
async def create_env(request: Request, payload: EnvironmentPayload) -> HTMLResponse:
    """Create a new environment.

    Returns the updated environment editor panel.
    """
    directory = _get_directory(request)
    envs = _load_public_env(directory)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Environment name is required")
    if name.startswith("_"):
        raise HTTPException(status_code=422, detail="Environment name cannot start with '_'")
    if name in envs:
        raise HTTPException(status_code=409, detail=f"Environment '{name}' already exists")

    # Build the variables dict from the payload
    variables: dict[str, Any] = {}
    for var in payload.variables:
        if var.name.strip():
            variables[var.name.strip()] = var.value

    envs[name] = variables
    save_environment(directory, envs)

    # Return the full updated editor
    env_names = _visible_env_names(envs)
    shared = envs.get(SHARED_ENV_KEY, {})
    html = _render(
        "partials/env_editor.html",
        env_names=env_names,
        environments=envs,
        shared=shared,
    )
    return HTMLResponse(html)


@router.put("/{env_name}")
async def update_env(
    request: Request,
    env_name: str,
    payload: EnvironmentPayload,
) -> HTMLResponse:
    """Update an existing environment's variables.

    Replaces all variables for the environment with the provided ones.
    Returns the updated variable rows.
    """
    directory = _get_directory(request)
    envs = _load_public_env(directory)

    if env_name not in envs:
        raise HTTPException(status_code=404, detail=f"Environment '{env_name}' not found")

    # Build the new variables dict
    variables: dict[str, Any] = {}
    for var in payload.variables:
        if var.name.strip():
            variables[var.name.strip()] = var.value

    envs[env_name] = variables
    save_environment(directory, envs)

    html = _render(
        "partials/env_variables.html",
        env_name=env_name,
        variables=variables,
    )
    return HTMLResponse(html)


@router.delete("/{env_name}")
async def delete_env(request: Request, env_name: str) -> HTMLResponse:
    """Delete an environment.

    Returns the updated environment editor panel.
    """
    directory = _get_directory(request)
    envs = _load_public_env(directory)

    if env_name not in envs:
        raise HTTPException(status_code=404, detail=f"Environment '{env_name}' not found")
    if env_name == SHARED_ENV_KEY:
        raise HTTPException(status_code=422, detail="Cannot delete the _shared environment")

    del envs[env_name]
    save_environment(directory, envs)

    # If the deleted env was the active env, clear the selection
    if request.app.state.env_name == env_name:
        request.app.state.env_name = None

    env_names = _visible_env_names(envs)
    shared = envs.get(SHARED_ENV_KEY, {})
    html = _render(
        "partials/env_editor.html",
        env_names=env_names,
        environments=envs,
        shared=shared,
    )
    return HTMLResponse(html)
