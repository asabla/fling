"""Tests for the web app scaffold, collection tree, and request display."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient

from fling.cli import main
from fling.web.app import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# create_app factory
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for the create_app factory function."""

    def test_creates_fastapi_instance(self) -> None:
        app = create_app()
        assert app.title == "fling"

    def test_state_defaults_without_file(self) -> None:
        app = create_app()
        assert app.state.file_path is None
        assert app.state.env_name is None
        assert app.state.http_file is None

    def test_state_with_file(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        assert app.state.file_path is not None
        assert app.state.http_file is not None
        assert len(app.state.http_file.requests) == 1

    def test_state_with_env_name(self) -> None:
        app = create_app(env_name="dev")
        assert app.state.env_name == "dev"

    def test_invalid_file_returns_none_http_file(self) -> None:
        app = create_app(file_path="/nonexistent/file.http")
        assert app.state.http_file is None


# ---------------------------------------------------------------------------
# GET / — index page
# ---------------------------------------------------------------------------


class TestIndexRoute:
    """Tests for the index page route."""

    async def test_index_no_file(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "fling" in response.text

    async def test_index_with_file(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "simple.http" in response.text
        # Should contain the request URL from the fixture
        assert "api.example.com/users" in response.text

    async def test_index_with_multiple_requests(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        # Should show GET, POST, DELETE methods from the fixture
        assert "GET" in response.text
        assert "POST" in response.text
        assert "DELETE" in response.text

    async def test_index_contains_htmx(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "htmx.org" in response.text

    async def test_index_contains_tailwind(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "tailwindcss" in response.text

    async def test_index_dark_mode(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert 'class="dark"' in response.text


# ---------------------------------------------------------------------------
# GET /request/{index} — request detail partial
# ---------------------------------------------------------------------------


class TestRequestDetailRoute:
    """Tests for the request detail HTMX partial route."""

    async def test_get_valid_request(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "api.example.com/users" in response.text
        assert "GET" in response.text

    async def test_get_second_request(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/1")
        assert response.status_code == 200
        assert "POST" in response.text

    async def test_get_request_out_of_range(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/99")
        assert response.status_code == 200
        assert "Select a request" in response.text

    async def test_get_request_negative_index(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/-1")
        assert response.status_code == 200
        assert "Select a request" in response.text

    async def test_get_request_no_file_loaded(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "Select a request" in response.text

    async def test_request_detail_shows_headers(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Request 1 (POST) has Content-Type header
            response = await client.get("/request/1")
        assert response.status_code == 200
        assert "Content-Type" in response.text
        assert "application/json" in response.text

    async def test_request_detail_includes_oob_tree(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/1")
        assert response.status_code == 200
        # Should contain OOB swap element for collection tree
        assert "hx-swap-oob" in response.text

    async def test_request_detail_oob_tree_has_active_state(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/2")
        assert response.status_code == 200
        # OOB tree should contain the collection tree
        assert "collection-tree" in response.text


# ---------------------------------------------------------------------------
# GET /env — environment switching
# ---------------------------------------------------------------------------


class TestEnvSwitching:
    """Tests for environment switching routes."""

    async def test_index_with_env_query_param(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/?env=production")
        assert response.status_code == 200
        assert app.state.env_name == "production"

    async def test_index_clear_env_with_empty_string(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"), env_name="dev")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/?env=")
        assert response.status_code == 200
        assert app.state.env_name is None

    async def test_env_route_switches_env(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=staging")
        assert response.status_code == 200
        assert app.state.env_name == "staging"

    async def test_env_route_clears_env(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"), env_name="dev")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=")
        assert response.status_code == 200
        assert app.state.env_name is None

    async def test_env_route_returns_full_page(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=dev")
        assert response.status_code == 200
        # Should be a full page with HTML structure
        assert "<!DOCTYPE html>" in response.text
        assert "fling" in response.text


# ---------------------------------------------------------------------------
# Prompt variables form
# ---------------------------------------------------------------------------


class TestPromptVariables:
    """Tests for prompt variable form rendering."""

    async def test_prompt_vars_form_shown(self) -> None:
        """Requests with @prompt variables should show input fields."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Request index 3 is searchUsers with @prompt vars
            response = await client.get("/request/3")
        assert response.status_code == 200
        assert "Prompt Variables" in response.text
        assert "query" in response.text
        assert "limit" in response.text

    async def test_prompt_vars_input_fields(self) -> None:
        """Prompt variable inputs should have proper name attributes."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/3")
        assert response.status_code == 200
        assert 'name="prompt_query"' in response.text
        assert 'name="prompt_limit"' in response.text

    async def test_no_prompt_vars_no_form(self) -> None:
        """Requests without @prompt variables should not show the form."""
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "Prompt Variables" not in response.text


# ---------------------------------------------------------------------------
# CLI serve command
# ---------------------------------------------------------------------------


class TestServeCommand:
    """Tests for the fling serve CLI command."""

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Launch the web interface" in result.output

    def test_serve_shows_port_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output

    def test_serve_shows_host_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output

    def test_serve_shows_env_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--env" in result.output


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestTemplateContent:
    """Tests for specific template content rendering."""

    async def test_collection_tree_shows_method_badges(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        # Collection tree should have request items with hx-get attributes
        assert "hx-get" in response.text
        assert "/request/" in response.text

    async def test_response_panel_placeholder(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert "No response yet" in response.text

    async def test_no_requests_message(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert "No requests loaded" in response.text

    async def test_prism_js_included(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert "prismjs" in response.text

    async def test_sse_extension_included(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert "sse" in response.text


# ---------------------------------------------------------------------------
# Request metadata display
# ---------------------------------------------------------------------------


class TestRequestMetadataDisplay:
    """Tests for displaying request metadata flags and attributes."""

    async def test_disabled_request_shown(self) -> None:
        """Disabled requests should display the disabled status."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Request 2 (createUser) is disabled
            response = await client.get("/request/2")
        assert response.status_code == 200
        assert "Disabled" in response.text

    async def test_no_redirect_flag(self) -> None:
        """Requests with @no-redirect should show the flag."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Request 1 (getUsers) has @no-redirect
            response = await client.get("/request/1")
        assert response.status_code == 200
        assert "@no-redirect" in response.text

    async def test_request_name_display(self) -> None:
        """Named requests should show their name."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "login" in response.text

    async def test_response_handler_shown(self) -> None:
        """Requests with response handlers should indicate it."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "Response handler" in response.text or "inline script" in response.text

    async def test_collection_tree_disabled_strikethrough(self) -> None:
        """Disabled requests in tree should have line-through styling."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "line-through" in response.text
