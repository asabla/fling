"""Tests for the HTTP execution engine."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock  # noqa: TC002

from fling.core.executor import HttpExecutor, ProgressEvent
from fling.core.models import (
    HttpMethod,
    HttpRequestDefinition,
    RequestMetadata,
    SourceLocation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_request(
    method: HttpMethod = HttpMethod.GET,
    url: str = "https://api.example.com/test",
    *,
    no_redirect: bool = False,
    no_cookie_jar: bool = False,
    timeout_ms: int | None = None,
) -> HttpRequestDefinition:
    """Create a minimal HttpRequestDefinition for testing."""
    return HttpRequestDefinition(
        method=method,
        url=url,
        metadata=RequestMetadata(
            no_redirect=no_redirect,
            no_cookie_jar=no_cookie_jar,
            timeout_ms=timeout_ms,
        ),
        location=_LOC,
    )


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestBasicExecution:
    """Tests for basic request execution."""

    @pytest.mark.asyncio
    async def test_simple_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            json={"message": "hello"},
            status_code=200,
        )
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert result.status_code == 200
        assert '"message"' in result.response_body
        assert result.error is None
        assert result.resolved_url == "https://api.example.com/test"

    @pytest.mark.asyncio
    async def test_post_with_body(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(text="created", status_code=201)
        executor = HttpExecutor()
        req = _make_request(method=HttpMethod.POST)
        result = await executor.execute(
            req,
            "https://api.example.com/test",
            {"Content-Type": "application/json"},
            '{"name": "test"}',
        )

        assert result.status_code == 201
        assert result.response_body == "created"
        assert result.resolved_body == '{"name": "test"}'
        assert result.resolved_headers == {"Content-Type": "application/json"}

    @pytest.mark.asyncio
    async def test_various_http_methods(self, httpx_mock: HTTPXMock) -> None:
        for method in [HttpMethod.PUT, HttpMethod.DELETE, HttpMethod.PATCH]:
            httpx_mock.add_response(status_code=200)
            executor = HttpExecutor()
            req = _make_request(method=method)
            result = await executor.execute(req, "https://api.example.com/test", {})
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_response_headers_captured(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            status_code=200,
            headers={"X-Custom": "value", "Content-Type": "text/plain"},
            text="ok",
        )
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert "x-custom" in result.response_headers
        assert result.response_headers["x-custom"] == ["value"]

    @pytest.mark.asyncio
    async def test_elapsed_time_positive(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(status_code=200, text="ok")
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})
        assert result.elapsed_ms >= 0


# ---------------------------------------------------------------------------
# Redirect handling
# ---------------------------------------------------------------------------


class TestRedirects:
    """Tests for redirect behavior."""

    @pytest.mark.asyncio
    async def test_no_redirect_flag(self, httpx_mock: HTTPXMock) -> None:
        """With @no-redirect, redirects should not be followed."""
        httpx_mock.add_response(
            status_code=302,
            headers={"Location": "https://api.example.com/other"},
        )
        executor = HttpExecutor()
        req = _make_request(no_redirect=True)
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert result.status_code == 302
        assert "location" in result.response_headers


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestTimeouts:
    """Tests for timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert result.error is not None
        assert "timed out" in result.error.lower()
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_custom_timeout_from_metadata(self, httpx_mock: HTTPXMock) -> None:
        """@timeout metadata should override the default timeout."""
        httpx_mock.add_response(status_code=200, text="ok")
        executor = HttpExecutor(default_timeout=30.0)
        req = _make_request(timeout_ms=5000)

        # The executor should use 5s timeout (5000ms)
        result = await executor.execute(req, "https://api.example.com/test", {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_default_timeout_used(self) -> None:
        executor = HttpExecutor(default_timeout=15.0)
        assert executor._resolve_timeout(None) == 15.0

    @pytest.mark.asyncio
    async def test_metadata_timeout_conversion(self) -> None:
        executor = HttpExecutor()
        assert executor._resolve_timeout(5000) == 5.0
        assert executor._resolve_timeout(500) == 0.5


# ---------------------------------------------------------------------------
# Cookie jar
# ---------------------------------------------------------------------------


class TestCookieJar:
    """Tests for cookie jar persistence."""

    @pytest.mark.asyncio
    async def test_cookie_jar_persists(self, httpx_mock: HTTPXMock) -> None:
        """Cookies from responses should be stored for subsequent requests."""
        httpx_mock.add_response(
            status_code=200,
            headers=[("Set-Cookie", "session=abc123; Path=/")],
            text="ok",
        )

        executor = HttpExecutor()
        req1 = _make_request()
        await executor.execute(req1, "https://api.example.com/login", {})

        # Cookie jar should now contain the session cookie
        assert "session" in executor._cookie_jar

    @pytest.mark.asyncio
    async def test_no_cookie_jar_flag(self, httpx_mock: HTTPXMock) -> None:
        """With @no-cookie-jar, cookies should not be persisted."""
        httpx_mock.add_response(
            status_code=200,
            headers=[("Set-Cookie", "session=abc123; Path=/")],
            text="ok",
        )
        executor = HttpExecutor()
        req = _make_request(no_cookie_jar=True)
        await executor.execute(req, "https://api.example.com/login", {})

        # Cookie jar should be empty since @no-cookie-jar was set
        assert "session" not in executor._cookie_jar

    @pytest.mark.asyncio
    async def test_clear_cookies(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            status_code=200,
            headers=[("Set-Cookie", "session=abc123; Path=/")],
            text="ok",
        )
        executor = HttpExecutor()
        req = _make_request()
        await executor.execute(req, "https://api.example.com/login", {})
        assert len(executor._cookie_jar) > 0

        executor.clear_cookies()
        assert len(executor._cookie_jar) == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_connection_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert result.error is not None
        assert "connection error" in result.error.lower()
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_generic_http_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.DecodingError("bad encoding"))
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})

        assert result.error is not None
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_error_result_preserves_request_info(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("fail"))
        executor = HttpExecutor()
        req = _make_request()
        result = await executor.execute(
            req,
            "https://api.example.com/test",
            {"Authorization": "Bearer token"},
            '{"key": "value"}',
        )

        assert result.resolved_url == "https://api.example.com/test"
        assert result.resolved_headers == {"Authorization": "Bearer token"}
        assert result.resolved_body == '{"key": "value"}'
        assert result.request == req


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


class TestProgressEvents:
    """Tests for progress event emission."""

    @pytest.mark.asyncio
    async def test_progress_events_emitted(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(status_code=200, text="ok")

        events: list[tuple[ProgressEvent, dict[str, Any]]] = []

        async def callback(event: ProgressEvent, data: dict[str, Any]) -> None:
            events.append((event, data))

        executor = HttpExecutor(progress_callback=callback)
        req = _make_request()
        await executor.execute(req, "https://api.example.com/test", {})

        event_types = [e[0] for e in events]
        assert ProgressEvent.PREPARING in event_types
        assert ProgressEvent.SENDING in event_types
        assert ProgressEvent.RECEIVING in event_types
        assert ProgressEvent.COMPLETE in event_types

    @pytest.mark.asyncio
    async def test_error_event_on_failure(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("fail"))

        events: list[tuple[ProgressEvent, dict[str, Any]]] = []

        async def callback(event: ProgressEvent, data: dict[str, Any]) -> None:
            events.append((event, data))

        executor = HttpExecutor(progress_callback=callback)
        req = _make_request()
        await executor.execute(req, "https://api.example.com/test", {})

        event_types = [e[0] for e in events]
        assert ProgressEvent.ERROR in event_types

    @pytest.mark.asyncio
    async def test_no_callback_is_fine(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(status_code=200, text="ok")
        executor = HttpExecutor()  # No callback
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# SSL configuration
# ---------------------------------------------------------------------------


class TestSSLConfig:
    """Tests for SSL verification configuration."""

    @pytest.mark.asyncio
    async def test_insecure_mode(self, httpx_mock: HTTPXMock) -> None:
        """verify_ssl=False should create client without SSL verification."""
        httpx_mock.add_response(status_code=200, text="ok")
        executor = HttpExecutor(verify_ssl=False)
        req = _make_request()
        result = await executor.execute(req, "https://api.example.com/test", {})
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# ProgressEvent enum
# ---------------------------------------------------------------------------


class TestProgressEventEnum:
    """Tests for the ProgressEvent enum."""

    def test_event_values(self) -> None:
        assert ProgressEvent.PREPARING == "preparing"
        assert ProgressEvent.SENDING == "sending"
        assert ProgressEvent.RECEIVING == "receiving"
        assert ProgressEvent.COMPLETE == "complete"
        assert ProgressEvent.ERROR == "error"
