"""Tests for Phase B: directory scanning, file tree, and multi-file web routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from fling.core.models import (
    ExecutionResult,
    HttpMethod,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.web.app import create_app
from fling.web.routes.pages import _build_file_tree
from fling.web.scanner import scan_directory, scan_single_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_request(**kwargs: object) -> HttpRequestDefinition:
    defaults: dict[str, object] = {
        "method": HttpMethod.GET,
        "url": "https://example.com",
        "location": _LOC,
    }
    defaults.update(kwargs)
    return HttpRequestDefinition(**defaults)  # type: ignore[arg-type]


def _make_result(**kwargs: object) -> ExecutionResult:
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


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class TestScanDirectory:
    """Tests for scan_directory."""

    def test_scan_fixtures_dir(self) -> None:
        files = scan_directory(str(FIXTURES_DIR))
        assert len(files) > 0
        # All keys should be basenames (no subdirs in fixtures/)
        for key in files:
            assert "/" not in key
            assert key.endswith(".http")

    def test_scan_finds_simple_http(self) -> None:
        files = scan_directory(str(FIXTURES_DIR))
        assert "simple.http" in files
        assert len(files["simple.http"].requests) == 1

    def test_scan_finds_multiple_http(self) -> None:
        files = scan_directory(str(FIXTURES_DIR))
        assert "multiple.http" in files
        assert len(files["multiple.http"].requests) >= 3

    def test_scan_nonexistent_dir(self) -> None:
        files = scan_directory("/nonexistent/dir")
        assert files == {}

    def test_scan_returns_sorted_keys(self) -> None:
        files = scan_directory(str(FIXTURES_DIR))
        keys = list(files.keys())
        assert keys == sorted(keys)


class TestScanSingleFile:
    """Tests for scan_single_file."""

    def test_scan_single_valid_file(self) -> None:
        files = scan_single_file(str(FIXTURES_DIR / "simple.http"))
        assert len(files) == 1
        assert "simple.http" in files
        assert len(files["simple.http"].requests) == 1

    def test_scan_single_nonexistent(self) -> None:
        files = scan_single_file("/nonexistent/file.http")
        assert files == {}

    def test_scan_single_uses_basename_as_key(self) -> None:
        files = scan_single_file(str(FIXTURES_DIR / "multiple.http"))
        assert "multiple.http" in files


# ---------------------------------------------------------------------------
# File tree building
# ---------------------------------------------------------------------------


class TestBuildFileTree:
    """Tests for _build_file_tree."""

    def test_empty_files(self) -> None:
        tree = _build_file_tree({})
        assert tree == []

    def test_single_file(self) -> None:
        tree = _build_file_tree({"simple.http": "dummy"})
        assert len(tree) == 1
        assert tree[0]["name"] == "simple.http"
        assert tree[0]["key"] == "simple.http"
        assert tree[0]["is_dir"] is False

    def test_nested_files(self) -> None:
        tree = _build_file_tree(
            {
                "api/users.http": "dummy",
                "api/auth.http": "dummy",
                "tests/smoke.http": "dummy",
            }
        )
        assert len(tree) == 2  # api, tests
        api_node = tree[0]
        assert api_node["name"] == "api"
        assert api_node["is_dir"] is True
        assert len(api_node["children"]) == 2  # auth.http, users.http (sorted)
        assert api_node["children"][0]["name"] == "auth.http"
        assert api_node["children"][0]["key"] == "api/auth.http"

    def test_flat_multiple_files(self) -> None:
        tree = _build_file_tree(
            {
                "a.http": "dummy",
                "b.http": "dummy",
            }
        )
        assert len(tree) == 2
        assert all(not n["is_dir"] for n in tree)

    def test_deeply_nested(self) -> None:
        tree = _build_file_tree({"a/b/c/d.http": "dummy"})
        assert len(tree) == 1
        assert tree[0]["name"] == "a"
        assert tree[0]["is_dir"] is True
        child = tree[0]["children"][0]
        assert child["name"] == "b"
        assert child["is_dir"] is True
        grandchild = child["children"][0]
        assert grandchild["name"] == "c"
        assert grandchild["is_dir"] is True
        leaf = grandchild["children"][0]
        assert leaf["name"] == "d.http"
        assert leaf["key"] == "a/b/c/d.http"
        assert leaf["is_dir"] is False


# ---------------------------------------------------------------------------
# create_app with directory mode
# ---------------------------------------------------------------------------


class TestCreateAppDirectory:
    """Tests for create_app in directory mode."""

    def test_directory_mode_populates_files(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        assert len(app.state.files) > 0
        assert "simple.http" in app.state.files

    def test_directory_mode_sets_directory(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        assert app.state.directory is not None
        assert Path(app.state.directory).name == "fixtures"

    def test_directory_mode_backward_compat(self) -> None:
        """First file should be set for backward compatibility."""
        app = create_app(directory=str(FIXTURES_DIR))
        assert app.state.http_file is not None

    def test_single_file_mode_still_works(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        assert len(app.state.files) == 1
        assert "simple.http" in app.state.files


# ---------------------------------------------------------------------------
# Multi-file page routes
# ---------------------------------------------------------------------------


class TestMultiFilePageRoutes:
    """Tests for the multi-file page routes."""

    async def test_file_request_route(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/file/multiple.http/request/0")
        assert response.status_code == 200
        assert "api.example.com/users" in response.text
        assert "GET" in response.text

    async def test_file_request_route_second_request(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/file/multiple.http/request/1")
        assert response.status_code == 200
        assert "POST" in response.text

    async def test_file_request_out_of_range(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/file/simple.http/request/99")
        assert response.status_code == 200
        assert "Select a request" in response.text

    async def test_file_request_invalid_file_key(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/file/nonexistent.http/request/0")
        assert response.status_code == 200
        assert "Select a request" in response.text

    async def test_file_request_includes_oob_tree(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/file/multiple.http/request/1")
        assert response.status_code == 200
        assert "hx-swap-oob" in response.text
        assert "sidebar-tree" in response.text

    async def test_backward_compat_request_route_delegates(self) -> None:
        """The old /request/{index} route should still work."""
        app = create_app(file_path=str(FIXTURES_DIR / "multiple.http"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/request/0")
        assert response.status_code == 200
        assert "api.example.com/users" in response.text


# ---------------------------------------------------------------------------
# Multi-file execution routes
# ---------------------------------------------------------------------------


class TestMultiFileExecutionRoutes:
    """Tests for the multi-file execution routes."""

    async def test_execute_file_request(self) -> None:
        mock_result = _make_result()

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch("fling.web.routes.execution.HttpRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/simple.http/request/0") as response,
            ):
                body = (await response.aread()).decode()

        assert "event: progress" in body
        assert "event: response" in body
        assert "200" in body

    async def test_execute_file_all(self) -> None:
        mock_result = _make_result()

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch("fling.web.routes.execution.HttpRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/simple.http/all") as response,
            ):
                body = (await response.aread()).decode()

        assert "event: log" in body
        assert "event: summary" in body
        assert "event: complete" in body

    async def test_execute_file_request_invalid_key(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/nonexistent.http/request/0") as response,
        ):
            body = (await response.aread()).decode()
        assert "Request not found" in body

    async def test_execute_file_all_invalid_key(self) -> None:
        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("GET", "/execute/nonexistent.http/all") as response,
        ):
            body = (await response.aread()).decode()
        assert "No requests to execute" in body

    async def test_backward_compat_execute_single(self) -> None:
        """The old /execute/{index} route should still work."""
        mock_result = _make_result()

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch("fling.web.routes.execution.HttpRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/0") as response,
            ):
                body = (await response.aread()).decode()

        assert "event: response" in body
        assert "200" in body

    async def test_backward_compat_execute_all(self) -> None:
        """The old /execute/all route should still work."""
        mock_result = _make_result()

        async def mock_run_all(http_file):
            yield (http_file.requests[0], mock_result)

        app = create_app(file_path=str(FIXTURES_DIR / "simple.http"))
        transport = ASGITransport(app=app)

        with patch("fling.web.routes.execution.HttpRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run_all = lambda f: mock_run_all(f)
            mock_runner_cls.return_value = mock_runner

            async with (
                AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream("GET", "/execute/all") as response,
            ):
                body = (await response.aread()).decode()

        assert "event: log" in body
        assert "event: complete" in body


# ---------------------------------------------------------------------------
# Index page with directory mode
# ---------------------------------------------------------------------------


class TestIndexDirectoryMode:
    """Tests for the index page in directory mode."""

    async def test_index_shows_dir_name(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "fixtures" in response.text

    async def test_index_directory_has_file_tree(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        # Should have the file tree with sidebar-tree container
        assert "sidebar-tree" in response.text

    async def test_index_directory_shows_multiple_files(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "simple.http" in response.text
        assert "multiple.http" in response.text

    async def test_index_directory_file_links_use_file_key(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        # File tree links should use the /file/{key}/request/{index} pattern
        assert "/file/" in response.text
        assert "/request/" in response.text


# ---------------------------------------------------------------------------
# CLI serve command updates
# ---------------------------------------------------------------------------


class TestServeCommandUpdated:
    """Tests for the updated serve CLI command."""

    def test_serve_help_shows_path(self) -> None:
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "PATH" in result.output

    def test_serve_help_mentions_directory(self) -> None:
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "directory" in result.output
