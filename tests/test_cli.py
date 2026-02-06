"""Tests for the CLI commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from pytest_httpx import HTTPXMock  # noqa: TC002

from fling.cli import main

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
