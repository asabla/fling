"""Tests for environment CRUD web routes."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from fling.core.environment import PUBLIC_ENV_FILENAME
from fling.web.app import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _create_app_with_env(tmp_path: Path, env_data: dict | None = None) -> object:
    """Create a test app with a writable environment directory.

    Writes an initial ``http-client.env.json`` in *tmp_path* and creates a
    minimal ``.http`` file so the app has a valid directory to work with.
    """
    if env_data is None:
        env_data = {
            "_shared": {"baseUrl": "https://api.example.com"},
            "development": {"token": "dev-123", "debug": True},
            "production": {"token": "prod-456", "debug": False},
        }

    # Write environment file
    env_path = tmp_path / PUBLIC_ENV_FILENAME
    env_path.write_text(json.dumps(env_data, indent=4), encoding="utf-8")

    # Write a minimal .http file so the app can scan the directory
    http_file = tmp_path / "test.http"
    http_file.write_text("GET https://example.com\n", encoding="utf-8")

    return create_app(directory=str(tmp_path), watch=False)


# ---------------------------------------------------------------------------
# GET /environments — list all
# ---------------------------------------------------------------------------


class TestListEnvironments:
    """Tests for GET /environments."""

    async def test_list_returns_200(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments")
        assert resp.status_code == 200

    async def test_list_shows_env_names(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments")
        assert "development" in resp.text
        assert "production" in resp.text

    async def test_list_shows_shared(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments")
        assert "_shared" in resp.text

    async def test_list_no_directory(self) -> None:
        """Without a directory, should return 400."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments")
        assert resp.status_code == 400

    async def test_list_empty_envs(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path, env_data={})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments")
        assert resp.status_code == 200
        assert "No environments configured" in resp.text


# ---------------------------------------------------------------------------
# GET /environments/{name} — get single
# ---------------------------------------------------------------------------


class TestGetEnvironment:
    """Tests for GET /environments/{name}."""

    async def test_get_existing_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments/development")
        assert resp.status_code == 200
        assert "dev-123" in resp.text

    async def test_get_shared(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments/_shared")
        assert resp.status_code == 200
        assert "baseUrl" in resp.text

    async def test_get_nonexistent_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/environments/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /environments — create
# ---------------------------------------------------------------------------


class TestCreateEnvironment:
    """Tests for POST /environments."""

    async def test_create_new_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/environments",
                json={"name": "staging", "variables": [{"name": "host", "value": "staging.example.com"}]},
            )
        assert resp.status_code == 200
        assert "staging" in resp.text

        # Verify it was persisted
        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert "staging" in data
        assert data["staging"]["host"] == "staging.example.com"

    async def test_create_empty_name_rejected(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/environments", json={"name": "", "variables": []})
        assert resp.status_code == 422

    async def test_create_internal_name_rejected(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/environments", json={"name": "_private", "variables": []})
        assert resp.status_code == 422

    async def test_create_duplicate_rejected(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/environments",
                json={"name": "development", "variables": []},
            )
        assert resp.status_code == 409

    async def test_create_env_with_no_vars(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/environments", json={"name": "staging", "variables": []})
        assert resp.status_code == 200

        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert data["staging"] == {}


# ---------------------------------------------------------------------------
# PUT /environments/{name} — update
# ---------------------------------------------------------------------------


class TestUpdateEnvironment:
    """Tests for PUT /environments/{name}."""

    async def test_update_existing_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/environments/development",
                json={"variables": [{"name": "token", "value": "new-token"}, {"name": "newVar", "value": "hello"}]},
            )
        assert resp.status_code == 200
        assert "new-token" in resp.text

        # Verify persistence
        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert data["development"]["token"] == "new-token"
        assert data["development"]["newVar"] == "hello"
        # Old "debug" key should be gone (full replacement)
        assert "debug" not in data["development"]

    async def test_update_nonexistent_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/environments/nonexistent", json={"variables": []})
        assert resp.status_code == 404

    async def test_update_shared_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/environments/_shared",
                json={
                    "variables": [
                        {"name": "baseUrl", "value": "https://new.api.com"},
                        {"name": "apiVersion", "value": "v3"},
                    ]
                },
            )
        assert resp.status_code == 200

        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert data["_shared"]["baseUrl"] == "https://new.api.com"
        assert data["_shared"]["apiVersion"] == "v3"

    async def test_update_strips_empty_var_names(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/environments/development",
                json={"variables": [{"name": "", "value": "ignored"}, {"name": "valid", "value": "kept"}]},
            )
        assert resp.status_code == 200

        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert "" not in data["development"]
        assert data["development"]["valid"] == "kept"


# ---------------------------------------------------------------------------
# DELETE /environments/{name} — delete
# ---------------------------------------------------------------------------


class TestDeleteEnvironment:
    """Tests for DELETE /environments/{name}."""

    async def test_delete_existing_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/environments/production")
        assert resp.status_code == 200
        assert "production" not in resp.text

        # Verify persistence
        data = json.loads((tmp_path / PUBLIC_ENV_FILENAME).read_text())
        assert "production" not in data
        assert "development" in data  # other envs unaffected

    async def test_delete_nonexistent_env(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/environments/nonexistent")
        assert resp.status_code == 404

    async def test_delete_shared_rejected(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/environments/_shared")
        assert resp.status_code == 422

    async def test_delete_active_env_clears_selection(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        app.state.env_name = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/environments/development")
        assert resp.status_code == 200
        assert app.state.env_name is None

    async def test_delete_non_active_env_keeps_selection(self, tmp_path: Path) -> None:
        app = _create_app_with_env(tmp_path)
        app.state.env_name = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/environments/production")
        assert resp.status_code == 200
        assert app.state.env_name == "development"
