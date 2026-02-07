"""Tests for error handling and edge case improvements (Task 7.3)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from fling.cli import _configure_logging, main
from fling.core.environment import load_environment
from fling.core.executor import HttpExecutor
from fling.core.models import (
    EnvironmentFile,
    ExecutionResult,
    HttpFile,
    HttpMethod,
    HttpRequestDefinition,
    RequestBody,
    RequestMetadata,
    ResponseHandler,
    SourceLocation,
    VariableDefinition,
)
from fling.core.parser import parse_http_file
from fling.core.runner import HttpRunner
from fling.core.scripting import (
    _exec_with_timeout,
    _ScriptTimeoutError,
    execute_handler,
)
from fling.core.variables import VariableResolver

if TYPE_CHECKING:
    from pytest_httpx import HTTPXMock

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# CLI: logging setup
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Tests for _configure_logging."""

    def test_default_level(self) -> None:
        _configure_logging()
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_verbose_level(self) -> None:
        _configure_logging(verbose=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_quiet_level(self) -> None:
        _configure_logging(quiet=True)
        root = logging.getLogger()
        assert root.level == logging.ERROR


# ---------------------------------------------------------------------------
# CLI: --quiet flag
# ---------------------------------------------------------------------------


class TestQuietFlag:
    """Tests for the --quiet flag on the run command."""

    def test_quiet_suppresses_output(self, httpx_mock: HTTPXMock) -> None:
        """--quiet should suppress normal output but still return exit code."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", str(FIXTURES_DIR / "simple.http"), "--quiet"],
        )
        assert result.exit_code == 0
        # With --quiet, no status code or response body should be printed
        assert "200" not in result.output


# ---------------------------------------------------------------------------
# CLI: Ctrl+C handling
# ---------------------------------------------------------------------------


class TestKeyboardInterrupt:
    """Tests for graceful Ctrl+C handling."""

    def test_keyboard_interrupt_exit_code(self) -> None:
        """KeyboardInterrupt should exit with code 130."""
        runner = CliRunner()
        with patch("fling.cli.asyncio.run", side_effect=KeyboardInterrupt):
            result = runner.invoke(
                main,
                ["run", str(FIXTURES_DIR / "simple.http")],
            )
        assert result.exit_code == 130

    def test_keyboard_interrupt_message(self) -> None:
        """KeyboardInterrupt should show 'Interrupted.' message."""
        runner = CliRunner()
        with patch("fling.cli.asyncio.run", side_effect=KeyboardInterrupt):
            result = runner.invoke(
                main,
                ["run", str(FIXTURES_DIR / "simple.http")],
            )
        # Message goes to stderr but CliRunner captures everything in output
        assert "Interrupted" in result.output


# ---------------------------------------------------------------------------
# CLI: top-level exception handling
# ---------------------------------------------------------------------------


class TestTopLevelExceptionHandler:
    """Tests for the top-level exception handler in the run command."""

    def test_unexpected_error_exit_code(self) -> None:
        """Unexpected exceptions should exit with code 1."""
        runner = CliRunner()
        with patch("fling.cli.asyncio.run", side_effect=RuntimeError("boom")):
            result = runner.invoke(
                main,
                ["run", str(FIXTURES_DIR / "simple.http")],
            )
        assert result.exit_code == 1

    def test_unexpected_error_message(self) -> None:
        """Unexpected exceptions should show a user-friendly message."""
        runner = CliRunner()
        with patch("fling.cli.asyncio.run", side_effect=RuntimeError("boom")):
            result = runner.invoke(
                main,
                ["run", str(FIXTURES_DIR / "simple.http")],
            )
        assert "Unexpected error" in result.output
        assert "boom" in result.output


# ---------------------------------------------------------------------------
# Parser: I/O error handling
# ---------------------------------------------------------------------------


class TestParserIOErrors:
    """Tests for parse_http_file I/O error handling."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Missing file should return ParseResult with error."""
        result = parse_http_file(tmp_path / "nonexistent.http")
        assert result.has_errors
        assert any("not found" in e.message.lower() for e in result.errors)

    def test_permission_denied(self, tmp_path: Path) -> None:
        """Unreadable file should return ParseResult with error."""
        target = tmp_path / "noperm.http"
        target.write_text("GET https://example.com\n")
        target.chmod(0o000)
        try:
            result = parse_http_file(target)
            assert result.has_errors
            assert any("permission" in e.message.lower() for e in result.errors)
        finally:
            target.chmod(0o644)

    def test_encoding_error(self, tmp_path: Path) -> None:
        """File with invalid UTF-8 should return ParseResult with error."""
        target = tmp_path / "badenc.http"
        target.write_bytes(b"\x80\x81\x82")
        result = parse_http_file(target)
        assert result.has_errors
        assert any("encoding" in e.message.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Environment: invalid JSON handling
# ---------------------------------------------------------------------------


class TestEnvironmentInvalidJSON:
    """Tests for graceful handling of malformed env files."""

    def test_invalid_public_env_json(self, tmp_path: Path) -> None:
        """Invalid JSON in public env file should not crash, just warn."""
        env_file = tmp_path / "http-client.env.json"
        env_file.write_text("{invalid json", encoding="utf-8")
        env = load_environment(tmp_path)
        # Should return an empty environment (not crash)
        assert env.environments == {} or "_dotenv" not in env.environments

    def test_invalid_private_env_json(self, tmp_path: Path) -> None:
        """Invalid JSON in private env file should not crash."""
        # Write valid public
        (tmp_path / "http-client.env.json").write_text(
            json.dumps({"dev": {"key": "val"}}),
            encoding="utf-8",
        )
        # Write invalid private
        (tmp_path / "http-client.private.env.json").write_text(
            "not json",
            encoding="utf-8",
        )
        env = load_environment(tmp_path)
        # Public should still be loaded
        assert "dev" in env.environments


# ---------------------------------------------------------------------------
# Variables: unknown env name warning
# ---------------------------------------------------------------------------


class TestUnknownEnvWarning:
    """Tests for warning on unknown --env name."""

    def test_unknown_env_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown environment name should log a warning."""
        env_file = EnvironmentFile(environments={"dev": {"key": "val"}, "prod": {"key": "val2"}})
        with caplog.at_level(logging.WARNING, logger="fling.core.variables"):
            VariableResolver(env_file=env_file, env_name="typo_env")
        assert "typo_env" in caplog.text
        assert "not found" in caplog.text.lower()

    def test_valid_env_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Valid environment name should not log a warning."""
        env_file = EnvironmentFile(environments={"dev": {"key": "val"}})
        with caplog.at_level(logging.WARNING, logger="fling.core.variables"):
            VariableResolver(env_file=env_file, env_name="dev")
        assert "not found" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# Variables: unresolved variable warning
# ---------------------------------------------------------------------------


class TestUnresolvedVariableWarning:
    """Tests for warning on unresolved variables."""

    def test_unresolved_var_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unresolved variables should log a warning."""
        resolver = VariableResolver()
        with caplog.at_level(logging.WARNING, logger="fling.core.variables"):
            result = resolver.resolve_string("https://{{base_url}}/api")
        assert "{{base_url}}" in caplog.text
        assert result == "https://{{base_url}}/api"

    def test_resolved_var_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Resolved variables should not log a warning."""
        http_file = HttpFile(
            file_path="test.http",
            variables=[VariableDefinition(name="host", value="example.com", location=_LOC)],
        )
        resolver = VariableResolver(http_file=http_file)
        with caplog.at_level(logging.WARNING, logger="fling.core.variables"):
            result = resolver.resolve_string("https://{{host}}/api")
        assert "Unresolved" not in caplog.text
        assert result == "https://example.com/api"


# ---------------------------------------------------------------------------
# Runner: failed chain propagation
# ---------------------------------------------------------------------------


class TestFailedChainPropagation:
    """Tests for skipping dependents when a chained request fails."""

    @pytest.mark.asyncio
    async def test_dependent_skipped_on_failure(self, httpx_mock: HTTPXMock) -> None:
        """When request A fails, dependent request B should be skipped."""
        # A will get a connection error; B is skipped so no mock needed for it
        httpx_mock.add_exception(ConnectionError("simulated failure"))

        req_a = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://api.example.com/a",
            metadata=RequestMetadata(name="a"),
            location=_LOC,
        )
        req_b = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://api.example.com/b",
            metadata=RequestMetadata(name="b", refs=["a"]),
            location=_LOC,
        )
        http_file = HttpFile(file_path="test.http", variables=[], requests=[req_a, req_b])

        runner = HttpRunner()
        results: list[tuple[str | None, ExecutionResult]] = []
        async for req, result in runner.run_all(http_file):
            results.append((req.metadata.name, result))

        assert len(results) == 2
        # A should have an error
        assert results[0][0] == "a"
        assert results[0][1].error is not None
        # B should be skipped due to dependency failure
        assert results[1][0] == "b"
        assert results[1][1].error is not None
        assert "dependency failed" in results[1][1].error.lower()

    @pytest.mark.asyncio
    async def test_independent_requests_not_affected(self, httpx_mock: HTTPXMock) -> None:
        """When A fails, independent request C should still run."""
        httpx_mock.add_exception(ConnectionError("simulated failure"))
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req_a = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://api.example.com/a",
            metadata=RequestMetadata(name="a"),
            location=_LOC,
        )
        req_c = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://api.example.com/c",
            metadata=RequestMetadata(name="c"),
            location=_LOC,
        )
        http_file = HttpFile(file_path="test.http", variables=[], requests=[req_a, req_c])

        runner = HttpRunner()
        results: list[tuple[str | None, ExecutionResult]] = []
        async for req, result in runner.run_all(http_file):
            results.append((req.metadata.name, result))

        # A fails but C should succeed since it has no deps on A
        assert len(results) == 2
        assert results[0][0] == "a"
        assert results[0][1].error is not None
        assert results[1][0] == "c"
        assert results[1][1].error is None


# ---------------------------------------------------------------------------
# Runner: missing file body error
# ---------------------------------------------------------------------------


class TestMissingFileBody:
    """Tests for error when body file reference is missing."""

    @pytest.mark.asyncio
    async def test_missing_body_file_returns_error(self) -> None:
        """A missing < ./file.json body should produce an error result."""
        req = HttpRequestDefinition(
            method=HttpMethod.POST,
            url="https://api.example.com/test",
            metadata=RequestMetadata(name="test"),
            body=RequestBody(file_ref="nonexistent.json"),
            location=_LOC,
        )
        http_file = HttpFile(file_path="test.http", variables=[], requests=[req])

        runner = HttpRunner()
        results: list[ExecutionResult] = []
        async for _req, result in runner.run_all(http_file):
            results.append(result)

        assert len(results) == 1
        assert results[0].error is not None
        assert "body file not found" in results[0].error.lower()


# ---------------------------------------------------------------------------
# Executor: SSL error messaging
# ---------------------------------------------------------------------------


class TestSSLErrorMessaging:
    """Tests for SSL-specific error messages."""

    @pytest.mark.asyncio
    async def test_ssl_error_suggests_insecure(self) -> None:
        """SSL errors should suggest --insecure flag."""
        import httpx

        executor = HttpExecutor()
        request = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://example.com",
            metadata=RequestMetadata(),
            location=_LOC,
        )

        with patch.object(
            httpx.AsyncClient,
            "request",
            side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"),
        ):
            result = await executor.execute(
                request=request,
                resolved_url="https://example.com",
                resolved_headers={},
            )

        assert result.error is not None
        assert "ssl" in result.error.lower()
        assert "--insecure" in result.error

    @pytest.mark.asyncio
    async def test_non_ssl_connect_error(self, httpx_mock: HTTPXMock) -> None:
        """Non-SSL connection errors should not mention --insecure."""
        import httpx

        executor = HttpExecutor()
        request = HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://example.com",
            metadata=RequestMetadata(),
            location=_LOC,
        )

        with patch.object(
            httpx.AsyncClient,
            "request",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await executor.execute(
                request=request,
                resolved_url="https://example.com",
                resolved_headers={},
            )

        assert result.error is not None
        assert "connection error" in result.error.lower()
        assert "--insecure" not in result.error


# ---------------------------------------------------------------------------
# Scripting: timeout
# ---------------------------------------------------------------------------


class TestScriptTimeout:
    """Tests for script execution timeout."""

    def test_exec_with_timeout_normal(self) -> None:
        """Normal script should execute without timeout."""
        ns: dict[str, object] = {}
        _exec_with_timeout("x = 42", ns, timeout=5)
        assert ns["x"] == 42

    @pytest.mark.skipif(
        not hasattr(__import__("signal"), "SIGALRM"),
        reason="SIGALRM not available on this platform",
    )
    def test_exec_with_timeout_raises(self) -> None:
        """Long-running script should raise _ScriptTimeoutError."""
        with pytest.raises(_ScriptTimeoutError):
            _exec_with_timeout("import time; time.sleep(10)", {}, timeout=1)

    def test_timeout_in_execute_handler(self) -> None:
        """execute_handler should return error on timeout."""
        result = ExecutionResult(
            request=HttpRequestDefinition(
                method=HttpMethod.GET,
                url="https://example.com",
                location=_LOC,
            ),
            resolved_url="https://example.com",
            status_code=200,
            response_body="{}",
            response_headers={},
        )
        handler = ResponseHandler(inline_script="x = 1")

        with patch(
            "fling.core.scripting._exec_with_timeout",
            side_effect=_ScriptTimeoutError,
        ):
            script_result = execute_handler(
                handler=handler,
                result=result,
                source_file="test.http",
            )

        assert script_result.error is not None
        assert "timed out" in script_result.error.lower()
