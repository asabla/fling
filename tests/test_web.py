"""Tests for the web app scaffold, collection tree, request display, and execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient

from fling.cli import main
from fling.core.models import (
    ExecutionResult,
    HttpMethod,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.web.app import create_app
from fling.web.routes.execution import (
    _build_response_html,
    _detect_language,
    _format_body,
    _format_elapsed,
    _format_size,
    _log_entry_html,
    _log_start_html,
    _progress_html,
    _status_class,
    _summary_html,
)

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
        assert "htmx" in response.text

    async def test_index_contains_tailwind(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "app.css" in response.text

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
        assert response.status_code == 302
        assert app.state.env_name == "staging"
        assert response.headers["location"] == "/?env=staging"

    async def test_env_route_clears_env(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"), env_name="dev")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=")
        assert response.status_code == 302
        assert app.state.env_name is None
        assert response.headers["location"] == "/"

    async def test_env_route_returns_redirect(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=dev")
        assert response.status_code == 302
        assert response.headers["location"] == "/?env=dev"
        assert app.state.env_name == "dev"

    async def test_env_route_htmx_returns_hx_redirect(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/env?env=staging", headers={"hx-request": "true"})
        assert response.status_code == 200
        assert response.headers["hx-redirect"] == "/?env=staging"
        assert app.state.env_name == "staging"


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
        assert "prism" in response.text

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


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_request(**kwargs: object) -> HttpRequestDefinition:
    """Create a minimal request definition for testing."""
    defaults: dict[str, object] = {
        "method": HttpMethod.GET,
        "url": "https://example.com",
        "location": _LOC,
    }
    defaults.update(kwargs)
    return HttpRequestDefinition(**defaults)  # type: ignore[arg-type]


def _make_result(**kwargs: object) -> ExecutionResult:
    """Create a minimal execution result for testing."""
    defaults: dict[str, object] = {
        "request": _make_request(),
        "resolved_url": "https://example.com",
        "status_code": 200,
        "response_headers": {"content-type": ["application/json"]},
        "response_body": '{"ok": true}',
        "elapsed_ms": 123.4,
    }
    defaults.update(kwargs)
    return ExecutionResult(**defaults)  # type: ignore[arg-type]


class TestStatusClass:
    """Tests for _status_class helper."""

    def test_2xx_success(self) -> None:
        assert _status_class(200) == "text-status-success"
        assert _status_class(201) == "text-status-success"
        assert _status_class(204) == "text-status-success"
        assert _status_class(299) == "text-status-success"

    def test_3xx_redirect(self) -> None:
        assert _status_class(301) == "text-status-redirect"
        assert _status_class(302) == "text-status-redirect"
        assert _status_class(304) == "text-status-redirect"
        assert _status_class(399) == "text-status-redirect"

    def test_4xx_error(self) -> None:
        assert _status_class(400) == "text-status-error"
        assert _status_class(404) == "text-status-error"
        assert _status_class(422) == "text-status-error"

    def test_5xx_error(self) -> None:
        assert _status_class(500) == "text-status-error"
        assert _status_class(503) == "text-status-error"


class TestFormatElapsed:
    """Tests for _format_elapsed helper."""

    def test_milliseconds(self) -> None:
        assert _format_elapsed(42) == "42ms"
        assert _format_elapsed(999) == "999ms"

    def test_seconds(self) -> None:
        assert _format_elapsed(1000) == "1.00s"
        assert _format_elapsed(1500) == "1.50s"
        assert _format_elapsed(2345) == "2.35s"

    def test_zero(self) -> None:
        assert _format_elapsed(0) == "0ms"

    def test_fractional_ms(self) -> None:
        assert _format_elapsed(0.7) == "1ms"


class TestFormatSize:
    """Tests for _format_size helper."""

    def test_bytes(self) -> None:
        assert _format_size("hi") == "2 B"
        assert _format_size("") == "0 B"

    def test_kilobytes(self) -> None:
        body = "x" * 2048
        result = _format_size(body)
        assert "KB" in result

    def test_megabytes(self) -> None:
        body = "x" * (1024 * 1024 + 1)
        result = _format_size(body)
        assert "MB" in result

    def test_under_1kb(self) -> None:
        body = "a" * 100
        assert _format_size(body) == "100 B"


class TestDetectLanguage:
    """Tests for _detect_language helper."""

    def test_json_content_type(self) -> None:
        assert _detect_language(["application/json"], "") == "json"

    def test_xml_content_type(self) -> None:
        assert _detect_language(["application/xml"], "") == "markup"

    def test_html_content_type(self) -> None:
        assert _detect_language(["text/html"], "") == "markup"

    def test_yaml_content_type(self) -> None:
        assert _detect_language(["application/yaml"], "") == "yaml"
        assert _detect_language(["text/yml"], "") == "yaml"

    def test_json_heuristic(self) -> None:
        assert _detect_language(["text/plain"], '{"key": "value"}') == "json"
        assert _detect_language([], "[1, 2, 3]") == "json"

    def test_xml_heuristic(self) -> None:
        assert _detect_language([], "<root><item/></root>") == "markup"

    def test_plain_text(self) -> None:
        assert _detect_language(["text/plain"], "hello world") == ""

    def test_empty(self) -> None:
        assert _detect_language([], "") == ""


class TestFormatBody:
    """Tests for _format_body helper."""

    def test_json_pretty_print(self) -> None:
        result = _format_body('{"a":1,"b":2}', "json")
        assert '"a": 1' in result
        assert "\n" in result  # indented

    def test_invalid_json_passthrough(self) -> None:
        result = _format_body("{not json}", "json")
        assert result == "{not json}"

    def test_non_json_passthrough(self) -> None:
        result = _format_body("<root/>", "markup")
        assert result == "<root/>"


class TestProgressHtml:
    """Tests for _progress_html helper."""

    def test_contains_message(self) -> None:
        result = _progress_html("Loading...")
        assert "Loading..." in result
        assert "sse-loading" in result

    def test_html_escaped(self) -> None:
        result = _progress_html("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestBuildResponseHtml:
    """Tests for _build_response_html helper."""

    def test_success_response(self) -> None:
        result_obj = _make_result()
        html = _build_response_html(result_obj)
        assert "200" in html
        assert "text-status-success" in html
        assert "123ms" in html

    def test_error_response(self) -> None:
        result_obj = _make_result(error="Connection refused", status_code=0)
        html = _build_response_html(result_obj)
        assert "Error" in html
        assert "Connection refused" in html
        assert "text-status-error" in html

    def test_response_body_displayed(self) -> None:
        result_obj = _make_result(response_body='{"message": "hello"}')
        html = _build_response_html(result_obj)
        assert "hello" in html

    def test_response_headers_tab(self) -> None:
        result_obj = _make_result(
            response_headers={"content-type": ["application/json"], "x-custom": ["val1"]},
        )
        html = _build_response_html(result_obj)
        assert "content-type" in html
        assert "x-custom" in html
        assert "val1" in html
        assert "Headers (2)" in html

    def test_body_html_escaped(self) -> None:
        result_obj = _make_result(response_body='<script>alert("xss")</script>')
        html = _build_response_html(result_obj)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_json_body_formatted(self) -> None:
        result_obj = _make_result(
            response_body='{"a":1}',
            response_headers={"content-type": ["application/json"]},
        )
        html_out = _build_response_html(result_obj)
        # JSON is pretty-printed then HTML-escaped: "a" becomes &quot;a&quot;
        assert "&quot;a&quot;: 1" in html_out

    def test_redirect_status(self) -> None:
        result_obj = _make_result(status_code=301)
        html = _build_response_html(result_obj)
        assert "301" in html
        assert "text-status-redirect" in html

    def test_client_error_status(self) -> None:
        result_obj = _make_result(status_code=404)
        html = _build_response_html(result_obj)
        assert "404" in html
        assert "text-status-error" in html

    def test_size_displayed(self) -> None:
        result_obj = _make_result(response_body="abcdef")
        html = _build_response_html(result_obj)
        assert "6 B" in html

    def test_tabs_present(self) -> None:
        result_obj = _make_result()
        html = _build_response_html(result_obj)
        assert "Body" in html
        assert "Headers" in html
        assert 'data-tab="body"' in html
        assert 'data-tab="headers"' in html


# ---------------------------------------------------------------------------
# Send button visibility
# ---------------------------------------------------------------------------


class TestSendButton:
    """Tests for Send button rendering in request detail."""

    async def test_send_button_shown_for_normal_request(self) -> None:
        """Non-disabled requests should have a Send button."""
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "send-btn" in response.text
        assert "data-sse-url" in response.text

    async def test_send_button_hidden_for_disabled_request(self) -> None:
        """Disabled requests should NOT have a Send button."""
        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Request 2 (createUser) is disabled
            response = await client.get("/request/2")
        assert response.status_code == 200
        assert "send-btn" not in response.text

    async def test_send_button_targets_response_content(self) -> None:
        """Send button onclick should target the response-content div."""
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "'#response-content'" in response.text

    async def test_send_button_sse_connect_url(self) -> None:
        """Send button data-sse-url should include the file key and request index."""
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/1")
        assert response.status_code == 200
        assert 'data-sse-url="/execute/multiple.http/request/1"' in response.text


# ---------------------------------------------------------------------------
# Execution SSE route
# ---------------------------------------------------------------------------


class TestExecutionRoute:
    """Tests for the /execute/{index} SSE streaming route."""

    async def test_execute_returns_event_stream(self) -> None:
        """The execute route should return an SSE event stream content type."""
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/0") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    async def test_execute_no_file_returns_error(self) -> None:
        """Executing with no file loaded should return an error event."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/0") as response,
        ):
            body = (await response.aread()).decode()
        assert "Request not found" in body

    async def test_execute_invalid_index_returns_error(self) -> None:
        """Executing with out-of-range index should return an error event."""
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/99") as response,
        ):
            body = (await response.aread()).decode()
        assert "Request not found" in body

    async def test_execute_negative_index_returns_error(self) -> None:
        """Executing with negative index should return an error event."""
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/-1") as response,
        ):
            body = (await response.aread()).decode()
        assert "Request not found" in body

    async def test_execute_streams_progress_and_response(self) -> None:
        """Executing a valid request should stream progress and response events."""
        mock_result = _make_result()

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        # We patch HttpRunner.run_all to return our mock result
        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/0") as response,
            ):
                body = (await response.aread()).decode()

        # Should have progress events
        assert "event: progress" in body
        assert "Preparing request" in body
        assert "Sending request" in body
        # Should have response event
        assert "event: response" in body
        assert "200" in body
        # Should have complete event
        assert "event: complete" in body

    async def test_execute_named_request_uses_run_single(self) -> None:
        """Named requests should use run_single for dependency resolution."""
        mock_result = _make_result()

        async def mock_run_single(http_file, name):
            yield (_make_request(), mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "advanced.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_single = lambda f, n: mock_run_single(f, n)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/0") as response,
            ):
                body = (await response.aread()).decode()

        assert "event: response" in body
        assert "200" in body

    async def test_execute_error_result_shows_error(self) -> None:
        """Execution errors should render in the error format."""
        mock_result = _make_result(error="Connection timed out", status_code=0)

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/0") as response,
            ):
                body = (await response.aread()).decode()

        assert "Connection timed out" in body
        assert "Error" in body


# ---------------------------------------------------------------------------
# Execution log helpers
# ---------------------------------------------------------------------------


class TestLogEntryHtml:
    """Tests for _log_entry_html helper."""

    def test_success_entry(self) -> None:
        req = _make_request(method=HttpMethod.GET, url="https://example.com/users")
        result = _make_result(status_code=200, elapsed_ms=50.0)
        html_out = _log_entry_html(req, result, 0)
        assert "200" in html_out
        assert "50ms" in html_out
        assert "example.com/users" in html_out
        assert "GET" in html_out

    def test_error_entry(self) -> None:
        req = _make_request()
        result = _make_result(error="Timeout", status_code=0)
        html_out = _log_entry_html(req, result, 1)
        assert "ERR" in html_out
        assert "text-status-error" in html_out

    def test_named_request_uses_name(self) -> None:
        from fling.core.models import RequestMetadata

        req = _make_request(metadata=RequestMetadata(name="getUsers"))
        result = _make_result()
        html_out = _log_entry_html(req, result, 0)
        assert "getUsers" in html_out

    def test_data_log_index(self) -> None:
        req = _make_request()
        result = _make_result()
        html_out = _log_entry_html(req, result, 5)
        assert 'data-log-index="5"' in html_out

    def test_4xx_status(self) -> None:
        req = _make_request()
        result = _make_result(status_code=404)
        html_out = _log_entry_html(req, result, 0)
        assert "404" in html_out
        assert "text-status-error" in html_out

    def test_3xx_status(self) -> None:
        req = _make_request()
        result = _make_result(status_code=302)
        html_out = _log_entry_html(req, result, 0)
        assert "302" in html_out
        assert "text-status-redirect" in html_out


class TestSummaryHtml:
    """Tests for _summary_html helper."""

    def test_basic_summary(self) -> None:
        result = _summary_html(total=3, completed=2, passed=2, failed=0, total_ms=150.0)
        assert "2/3" in result
        assert "2 ok" in result
        assert "150ms" in result

    def test_with_failures(self) -> None:
        result = _summary_html(total=5, completed=5, passed=3, failed=2, total_ms=2500.0)
        assert "5/5" in result
        assert "3 ok" in result
        assert "2 fail" in result
        assert "2.50s" in result

    def test_no_passed(self) -> None:
        result = _summary_html(total=1, completed=1, passed=0, failed=1, total_ms=100.0)
        assert "1/1" in result
        assert "ok" not in result
        assert "1 fail" in result

    def test_no_failed(self) -> None:
        result = _summary_html(total=2, completed=2, passed=2, failed=0, total_ms=200.0)
        assert "2/2" in result
        assert "2 ok" in result
        assert "fail" not in result


class TestLogStartHtml:
    """Tests for _log_start_html helper."""

    def test_contains_loading(self) -> None:
        result = _log_start_html()
        assert "sse-loading" in result
        assert "Running all requests" in result

    def test_contains_timestamp(self) -> None:
        result = _log_start_html()
        # Should have HH:MM:SS format
        assert ":" in result


# ---------------------------------------------------------------------------
# Run All button
# ---------------------------------------------------------------------------


class TestRunAllButton:
    """Tests for Run All button rendering."""

    async def test_run_all_button_shown_with_requests(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "run-all-btn" in response.text
        assert "Run All" in response.text

    async def test_run_all_button_hidden_without_requests(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert 'id="run-all-btn"' not in response.text

    async def test_run_all_button_targets_log(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert 'data-sse-url="/execute/simple.http/all"' in response.text


# ---------------------------------------------------------------------------
# Execution log panel
# ---------------------------------------------------------------------------


class TestExecutionLogPanel:
    """Tests for execution log panel rendering."""

    async def test_execution_log_shown_in_layout(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "execution-log" in response.text
        assert "Execution Log" in response.text

    async def test_execution_log_placeholder(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "Run All" in response.text

    async def test_execution_summary_container(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "execution-summary" in response.text


# ---------------------------------------------------------------------------
# Execute All SSE route
# ---------------------------------------------------------------------------


class TestExecuteAllRoute:
    """Tests for the /execute/all SSE streaming route."""

    async def test_execute_all_returns_event_stream(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/all") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    async def test_execute_all_no_file_returns_error(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/all") as response,
        ):
            body = (await response.aread()).decode()
        assert "No requests to execute" in body

    async def test_execute_all_streams_log_entries(self) -> None:
        results = [
            _make_result(status_code=200, elapsed_ms=50.0),
            _make_result(status_code=201, elapsed_ms=30.0),
            _make_result(status_code=404, elapsed_ms=10.0, error=None),
        ]
        call_index = 0

        async def mock_run_all(http_file):
            nonlocal call_index
            for i, req in enumerate(http_file.requests):
                if not req.metadata.disabled:
                    yield (req, results[min(i, len(results) - 1)])
                    call_index += 1

        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/all") as response,
            ):
                body = (await response.aread()).decode()

        # Should have log entries
        assert "event: log" in body
        assert "Running all requests" in body
        # Should have summary updates
        assert "event: summary" in body
        assert "execution-summary" in body
        # Should have complete event
        assert "event: complete" in body

    async def test_execute_all_summary_updates_incrementally(self) -> None:
        mock_result = _make_result(status_code=200, elapsed_ms=100.0)

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/all") as response,
            ):
                body = (await response.aread()).decode()

        # Summary should show 1/1 and 1 ok
        assert "1/1" in body
        assert "1 ok" in body

    async def test_execute_all_tracks_failures(self) -> None:
        mock_result = _make_result(error="Connection refused", status_code=0)

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/all") as response,
            ):
                body = (await response.aread()).decode()

        assert "1 fail" in body
        assert "ERR" in body

    async def test_execute_all_log_entry_has_method(self) -> None:
        mock_result = _make_result(status_code=200, elapsed_ms=42.0)

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch(
            "fling.web.routes.execution.HttpRunner",
        ) as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/all") as response,
            ):
                body = (await response.aread()).decode()

        assert "GET" in body
        assert "42ms" in body
