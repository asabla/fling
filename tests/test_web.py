"""Tests for the web app scaffold and base templates."""

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
