"""Tests for the CLI commands."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from pytest_httpx import HTTPXMock  # noqa: TC002

from fling.cli import main
from fling.core.models import HttpFile, ParseError, ParseResult, SourceLocation

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# fling (root)
# ---------------------------------------------------------------------------


class TestRootCommand:
    """Tests for the root fling command."""

    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "fling" in result.output

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_no_args_shows_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "Commands" in result.output


# ---------------------------------------------------------------------------
# fling list
# ---------------------------------------------------------------------------


class TestListCommand:
    """Tests for the 'fling list' command."""

    def test_list_simple(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["list", str(FIXTURES_DIR / "simple.http")])
        assert result.exit_code == 0
        assert "GET" in result.output
        assert "api.example.com" in result.output

    def test_list_multiple(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["list", str(FIXTURES_DIR / "multiple.http")])
        assert result.exit_code == 0
        # Should show multiple requests
        assert "GET" in result.output

    def test_list_chaining(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["list", str(FIXTURES_DIR / "chaining.http")])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "get-profile" in result.output
        assert "update-profile" in result.output
        assert "disabled" in result.output

    def test_list_nonexistent_file(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["list", "nonexistent.http"])
        assert result.exit_code != 0

    def test_list_shows_refs(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["list", str(FIXTURES_DIR / "chaining.http")])
        assert result.exit_code == 0
        assert "refs:" in result.output


# ---------------------------------------------------------------------------
# fling envs
# ---------------------------------------------------------------------------


class TestEnvsCommand:
    """Tests for the 'fling envs' command."""

    def test_envs_with_env_file(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["envs", "--env-file", str(FIXTURES_DIR / "env_full")])
        assert result.exit_code == 0
        assert "development" in result.output
        assert "production" in result.output

    def test_envs_no_env_file(self, tmp_path: Path) -> None:
        """Empty directory has no environments."""
        runner = CliRunner()
        result = runner.invoke(main, ["envs", "--env-file", str(tmp_path)])
        assert result.exit_code == 0
        assert "No environments" in result.output


# ---------------------------------------------------------------------------
# fling run
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for the 'fling run' command."""

    def test_run_simple(self, httpx_mock: HTTPXMock) -> None:
        """Run a simple GET request."""
        httpx_mock.add_response(
            json={"message": "hello"},
            status_code=200,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["run", str(FIXTURES_DIR / "simple.http")])
        assert result.exit_code == 0
        assert "200" in result.output

    def test_run_all_flag(self, httpx_mock: HTTPXMock) -> None:
        """--all runs all requests."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--all", str(FIXTURES_DIR / "multiple.http")])
        assert result.exit_code == 0

    def test_run_body_output(self, httpx_mock: HTTPXMock) -> None:
        """--output body only shows body."""
        httpx_mock.add_response(
            json={"data": "value"},
            status_code=200,
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--output", "body", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0
        assert "200" in result.output
        assert "data" in result.output

    def test_run_nonexistent_file(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "nonexistent.http"])
        assert result.exit_code != 0

    def test_run_named_request(self, httpx_mock: HTTPXMock) -> None:
        """--name selects a specific request."""
        httpx_mock.add_response(
            json={"token": "abc"},
            status_code=200,
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--name", "login", str(FIXTURES_DIR / "chaining.http")],
        )
        assert result.exit_code == 0
        assert "200" in result.output

    def test_run_named_not_found(self, httpx_mock: HTTPXMock) -> None:
        """--name with unknown name fails."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--name", "nonexistent", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code != 0

    def test_run_insecure_flag(self, httpx_mock: HTTPXMock) -> None:
        """--insecure flag works without error."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--insecure", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0

    def test_run_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--all" in result.output
        assert "--env" in result.output
        assert "--output" in result.output
        assert "--timeout" in result.output
        assert "--insecure" in result.output
        assert "--bail" in result.output
        assert "--filter" in result.output
        assert "--repeat" in result.output
        assert "--repeat-mode" in result.output


# ---------------------------------------------------------------------------
# fling run -- exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Tests for exit code behavior."""

    def test_exit_code_2_on_parse_error(self) -> None:
        """Parse errors should exit with code 2."""
        mock_result = ParseResult(
            http_file=HttpFile(file_path="test.http"),
            errors=[
                ParseError(
                    message="Bad syntax",
                    location=SourceLocation(file_path="test.http", start_line=1, end_line=1),
                )
            ],
        )
        with patch("fling.cli.parse_http_file", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, ["run", str(FIXTURES_DIR / "simple.http")])
            assert result.exit_code == 2

    def test_exit_code_0_on_success(self, httpx_mock: HTTPXMock) -> None:
        """Successful requests exit with code 0."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(main, ["run", str(FIXTURES_DIR / "simple.http")])
        assert result.exit_code == 0

    def test_exit_code_1_on_request_error(self, httpx_mock: HTTPXMock) -> None:
        """Request errors exit with code 1."""
        httpx_mock.add_exception(ConnectionError("refused"))
        runner = CliRunner()
        result = runner.invoke(main, ["run", str(FIXTURES_DIR / "simple.http")])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# fling run --filter
# ---------------------------------------------------------------------------


class TestFilterOption:
    """Tests for the --filter option."""

    def test_filter_by_name(self, httpx_mock: HTTPXMock) -> None:
        """--filter selects matching named requests."""
        httpx_mock.add_response(json={"token": "abc"}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--all", "--filter", "login", str(FIXTURES_DIR / "chaining.http")],
        )
        assert result.exit_code == 0
        assert "200" in result.output

    def test_filter_glob_pattern(self, httpx_mock: HTTPXMock) -> None:
        """--filter supports glob patterns."""
        # *-profile matches get-profile and update-profile
        httpx_mock.add_response(json={"email": "a@b.com"}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--all", "--filter", "*-profile", str(FIXTURES_DIR / "chaining.http")],
        )
        assert result.exit_code == 0

    def test_filter_no_matches(self) -> None:
        """--filter with no matches prints message and exits 0."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--all", "--filter", "nonexistent*", str(FIXTURES_DIR / "chaining.http")],
        )
        assert result.exit_code == 0
        assert "No requests matching" in result.output


# ---------------------------------------------------------------------------
# fling run --bail
# ---------------------------------------------------------------------------


class TestBailOption:
    """Tests for the --bail option."""

    def test_bail_stops_on_first_failure(self, httpx_mock: HTTPXMock) -> None:
        """--bail should stop after first failed request."""
        # First request succeeds, second fails
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_exception(ConnectionError("refused"))
        # Third response should NOT be needed — bail stops before it

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--all", "--bail", str(FIXTURES_DIR / "multiple.http")],
        )
        assert result.exit_code == 1

    def test_no_bail_continues_after_failure(self, httpx_mock: HTTPXMock) -> None:
        """Without --bail, all requests run even with failures."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_exception(ConnectionError("refused"))
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--all", str(FIXTURES_DIR / "multiple.http")],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# fling run --repeat
# ---------------------------------------------------------------------------


class TestRepeatOption:
    """Tests for the --repeat option."""

    def test_repeat_sequential(self, httpx_mock: HTTPXMock) -> None:
        """--repeat N runs the requests N times sequentially."""
        # Need 2 responses (1 request x 2 repeats)
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--repeat", "2", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0

    def test_repeat_parallel(self, httpx_mock: HTTPXMock) -> None:
        """--repeat N --repeat-mode parallel runs concurrently."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "run",
                "--repeat",
                "2",
                "--repeat-mode",
                "parallel",
                str(FIXTURES_DIR / "simple.http"),
            ],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# fling run --output (report formats)
# ---------------------------------------------------------------------------


class TestOutputFormats:
    """Tests for report output formats via CLI."""

    def test_json_report_output(self, httpx_mock: HTTPXMock) -> None:
        """--output json-report produces valid JSON."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--output", "json-report", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["summary"]["total"] == 1
        assert data["summary"]["passed"] == 1

    def test_junit_output(self, httpx_mock: HTTPXMock) -> None:
        """--output junit produces valid XML."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--output", "junit", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0
        root = ET.fromstring(result.output)
        assert root.tag == "testsuite"
        assert root.get("tests") == "1"

    def test_markdown_output(self, httpx_mock: HTTPXMock) -> None:
        """--output markdown produces markdown report."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--output", "markdown", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 0
        assert "# Test Report" in result.output
        assert "**Passed**: 1" in result.output

    def test_json_report_with_error(self, httpx_mock: HTTPXMock) -> None:
        """--output json-report shows errors correctly."""
        httpx_mock.add_exception(ConnectionError("refused"))
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["run", "--output", "json-report", str(FIXTURES_DIR / "simple.http")],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["summary"]["errors"] == 1
