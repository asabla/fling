"""Tests for Phase C: live file watching, SSE events, and reload."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from fling.core.models import (
    HttpFile as HttpFileModel,
)
from fling.core.models import (
    HttpMethod,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.web.app import create_app
from fling.web.watcher import FileChangeEvent, FileWatcher

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)

_SIMPLE_HTTP = """\
GET https://example.com/api/test
"""

_UPDATED_HTTP = """\
GET https://example.com/api/updated

###

POST https://example.com/api/new
Content-Type: application/json

{"key": "value"}
"""


def _make_request(**kwargs: object) -> HttpRequestDefinition:
    defaults: dict[str, object] = {
        "method": HttpMethod.GET,
        "url": "https://example.com",
        "location": _LOC,
    }
    defaults.update(kwargs)
    return HttpRequestDefinition(**defaults)  # type: ignore[arg-type]


def _make_http_file(**kwargs: object) -> HttpFileModel:
    defaults: dict[str, object] = {
        "file_path": "test.http",
        "requests": [_make_request()],
    }
    defaults.update(kwargs)
    return HttpFileModel(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# FileChangeEvent
# ---------------------------------------------------------------------------


class TestFileChangeEvent:
    """Tests for the FileChangeEvent data class."""

    def test_attributes(self) -> None:
        event = FileChangeEvent("added", "api/users.http", "/abs/api/users.http")
        assert event.change_type == "added"
        assert event.file_key == "api/users.http"
        assert event.file_path == "/abs/api/users.http"

    def test_modified_event(self) -> None:
        event = FileChangeEvent("modified", "test.http", "/abs/test.http")
        assert event.change_type == "modified"

    def test_deleted_event(self) -> None:
        event = FileChangeEvent("deleted", "old.http", "/abs/old.http")
        assert event.change_type == "deleted"


# ---------------------------------------------------------------------------
# FileWatcher — subscriber management
# ---------------------------------------------------------------------------


class TestFileWatcherSubscribers:
    """Tests for FileWatcher subscribe/unsubscribe/broadcast."""

    def test_subscribe_returns_queue(self) -> None:
        files: dict[str, HttpFileModel] = {}
        watcher = FileWatcher("/tmp", files)
        queue = watcher.subscribe()
        assert isinstance(queue, asyncio.Queue)
        assert queue in watcher._subscribers

    def test_unsubscribe_removes_queue(self) -> None:
        files: dict[str, HttpFileModel] = {}
        watcher = FileWatcher("/tmp", files)
        queue = watcher.subscribe()
        watcher.unsubscribe(queue)
        assert queue not in watcher._subscribers

    def test_unsubscribe_idempotent(self) -> None:
        files: dict[str, HttpFileModel] = {}
        watcher = FileWatcher("/tmp", files)
        queue = watcher.subscribe()
        watcher.unsubscribe(queue)
        watcher.unsubscribe(queue)  # Should not raise

    def test_broadcast_sends_to_all_subscribers(self) -> None:
        files: dict[str, HttpFileModel] = {}
        watcher = FileWatcher("/tmp", files)
        q1 = watcher.subscribe()
        q2 = watcher.subscribe()
        event = FileChangeEvent("added", "test.http", "/tmp/test.http")
        watcher._broadcast(event)
        assert q1.get_nowait() is event
        assert q2.get_nowait() is event

    def test_broadcast_skips_unsubscribed(self) -> None:
        files: dict[str, HttpFileModel] = {}
        watcher = FileWatcher("/tmp", files)
        q1 = watcher.subscribe()
        q2 = watcher.subscribe()
        watcher.unsubscribe(q1)
        event = FileChangeEvent("modified", "test.http", "/tmp/test.http")
        watcher._broadcast(event)
        assert q1.empty()
        assert q2.get_nowait() is event


# ---------------------------------------------------------------------------
# FileWatcher — relative key
# ---------------------------------------------------------------------------


class TestFileWatcherRelativeKey:
    """Tests for FileWatcher._relative_key."""

    def test_relative_key_subdir(self) -> None:
        watcher = FileWatcher("/project/root", {})
        key = watcher._relative_key(Path("/project/root/api/users.http"))
        assert key == "api/users.http"

    def test_relative_key_root_file(self) -> None:
        watcher = FileWatcher("/project/root", {})
        key = watcher._relative_key(Path("/project/root/test.http"))
        assert key == "test.http"

    def test_relative_key_outside_root_raises(self) -> None:
        watcher = FileWatcher("/project/root", {})
        import pytest

        with pytest.raises(ValueError):
            watcher._relative_key(Path("/other/dir/test.http"))


# ---------------------------------------------------------------------------
# FileWatcher — parse_file
# ---------------------------------------------------------------------------


class TestFileWatcherParseFile:
    """Tests for FileWatcher._parse_file."""

    def test_parse_valid_file(self) -> None:
        watcher = FileWatcher(str(FIXTURES_DIR), {})
        result = watcher._parse_file(FIXTURES_DIR / "simple.http")
        assert result is not None
        assert len(result.requests) == 1

    def test_parse_nonexistent_file(self) -> None:
        watcher = FileWatcher("/tmp", {})
        result = watcher._parse_file(Path("/tmp/nonexistent.http"))
        assert result is None

    def test_parse_malformed_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".http", mode="w", delete=False) as f:
            f.write("not a valid http file line without method\n")
            f.flush()
            watcher = FileWatcher(str(Path(f.name).parent), {})
            result = watcher._parse_file(Path(f.name))
            # May return None or a file with no requests depending on parser
            # The key test is it doesn't crash
            assert result is None or isinstance(result, HttpFileModel)


# ---------------------------------------------------------------------------
# FileWatcher — handle_changes
# ---------------------------------------------------------------------------


class TestFileWatcherHandleChanges:
    """Tests for FileWatcher._handle_changes."""

    async def test_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a valid .http file
            http_path = Path(tmpdir) / "new.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            queue = watcher.subscribe()

            from watchfiles import Change

            await watcher._handle_changes({(Change.added, str(http_path))})

            assert "new.http" in files
            assert len(files["new.http"].requests) == 1

            event = queue.get_nowait()
            assert event.change_type == "added"
            assert event.file_key == "new.http"

    async def test_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)

            # First add
            from watchfiles import Change

            await watcher._handle_changes({(Change.added, str(http_path))})
            assert "test.http" in files
            assert len(files["test.http"].requests) == 1

            # Now modify
            http_path.write_text(_UPDATED_HTTP)
            queue = watcher.subscribe()
            await watcher._handle_changes({(Change.modified, str(http_path))})

            assert len(files["test.http"].requests) == 2
            event = queue.get_nowait()
            assert event.change_type == "modified"

    async def test_deleted_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "delete_me.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)

            from watchfiles import Change

            # Add first
            await watcher._handle_changes({(Change.added, str(http_path))})
            assert "delete_me.http" in files

            # Delete
            queue = watcher.subscribe()
            http_path.unlink()
            await watcher._handle_changes({(Change.deleted, str(http_path))})

            assert "delete_me.http" not in files
            event = queue.get_nowait()
            assert event.change_type == "deleted"

    async def test_non_http_file_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "readme.txt"
            txt_path.write_text("hello")

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            queue = watcher.subscribe()

            from watchfiles import Change

            await watcher._handle_changes({(Change.added, str(txt_path))})

            assert len(files) == 0
            assert queue.empty()

    async def test_file_outside_root_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            queue = watcher.subscribe()

            from watchfiles import Change

            await watcher._handle_changes({(Change.added, "/other/dir/test.http")})

            assert len(files) == 0
            assert queue.empty()

    async def test_delete_nonexistent_key_no_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            queue = watcher.subscribe()

            from watchfiles import Change

            http_path = Path(tmpdir) / "ghost.http"
            await watcher._handle_changes({(Change.deleted, str(http_path))})

            assert queue.empty()


# ---------------------------------------------------------------------------
# FileWatcher — lifecycle (start/stop)
# ---------------------------------------------------------------------------


class TestFileWatcherLifecycle:
    """Tests for FileWatcher start/stop."""

    async def test_start_creates_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(tmpdir, {})
            assert not watcher.running

            # Patch watchfiles.awatch so the lazy import inside _watch picks it up
            async def _fake_awatch(*a: object, **kw: object) -> object:
                while True:
                    await asyncio.sleep(100)
                    yield set()  # type: ignore[misc]

            with patch("watchfiles.awatch", _fake_awatch):
                watcher.start()
                await asyncio.sleep(0.05)
                assert watcher.running
                await watcher.stop()
                assert not watcher.running

    async def test_stop_signals_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(tmpdir, {})
            queue = watcher.subscribe()

            async def _fake_awatch(*a: object, **kw: object) -> object:
                while True:
                    await asyncio.sleep(100)
                    yield set()  # type: ignore[misc]

            with patch("watchfiles.awatch", _fake_awatch):
                watcher.start()
                await asyncio.sleep(0.05)
                await watcher.stop()
                # Subscriber should receive None as shutdown signal
                assert queue.get_nowait() is None

    async def test_start_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(tmpdir, {})

            async def _fake_awatch(*a: object, **kw: object) -> object:
                while True:
                    await asyncio.sleep(100)
                    yield set()  # type: ignore[misc]

            with patch("watchfiles.awatch", _fake_awatch):
                watcher.start()
                await asyncio.sleep(0.05)
                task1 = watcher._task
                watcher.start()
                assert watcher._task is task1  # Same task, not duplicated
                await watcher.stop()

    async def test_stop_without_start(self) -> None:
        watcher = FileWatcher("/tmp", {})
        await watcher.stop()  # Should not raise


# ---------------------------------------------------------------------------
# FileWatcher — reload_all
# ---------------------------------------------------------------------------


class TestFileWatcherReloadAll:
    """Tests for FileWatcher.reload_all."""

    def test_reload_detects_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)

            # Write a file after watcher was created
            http_path = Path(tmpdir) / "new.http"
            http_path.write_text(_SIMPLE_HTTP)

            events = watcher.reload_all()
            assert "new.http" in files
            assert any(e.change_type == "added" and e.file_key == "new.http" for e in events)

    def test_reload_detects_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            watcher.reload_all()  # Load initial
            assert "test.http" in files

            # Delete and reload
            http_path.unlink()
            events = watcher.reload_all()
            assert "test.http" not in files
            assert any(e.change_type == "deleted" and e.file_key == "test.http" for e in events)

    def test_reload_detects_modified_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            watcher.reload_all()
            assert len(files["test.http"].requests) == 1

            # Modify
            http_path.write_text(_UPDATED_HTTP)
            events = watcher.reload_all()
            assert len(files["test.http"].requests) == 2
            assert any(e.change_type == "modified" for e in events)

    def test_reload_broadcasts_to_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            files: dict[str, HttpFileModel] = {}
            watcher = FileWatcher(tmpdir, files)
            queue = watcher.subscribe()

            watcher.reload_all()
            event = queue.get_nowait()
            assert event.file_key == "test.http"


# ---------------------------------------------------------------------------
# watch_events async generator
# ---------------------------------------------------------------------------


class TestWatchEvents:
    """Tests for the watch_events async generator."""

    async def test_yields_events(self) -> None:
        from fling.web.watcher import watch_events

        watcher = FileWatcher("/tmp", {})
        event = FileChangeEvent("added", "test.http", "/tmp/test.http")

        async def consume() -> list[FileChangeEvent]:
            results: list[FileChangeEvent] = []
            async for e in watch_events(watcher):
                results.append(e)
                if len(results) >= 1:
                    break
            return results

        # Start consumer
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        # Push event
        watcher._broadcast(event)
        results = await asyncio.wait_for(task, timeout=2.0)
        assert len(results) == 1
        assert results[0].change_type == "added"

    async def test_stops_on_none(self) -> None:
        from fling.web.watcher import watch_events

        watcher = FileWatcher("/tmp", {})

        async def consume() -> list[FileChangeEvent]:
            results: list[FileChangeEvent] = []
            async for e in watch_events(watcher):
                results.append(e)
            return results

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        # Send None to signal shutdown
        for q in watcher._subscribers:
            q.put_nowait(None)

        results = await asyncio.wait_for(task, timeout=2.0)
        assert results == []

    async def test_unsubscribes_on_exit(self) -> None:
        from fling.web.watcher import watch_events

        watcher = FileWatcher("/tmp", {})
        event = FileChangeEvent("added", "test.http", "/tmp/test.http")

        # Consume one event then break — watch_events should unsubscribe in finally
        received: list[FileChangeEvent] = []

        async def _consume() -> None:
            async for e in watch_events(watcher):
                received.append(e)
                break  # Exit after first event

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)

        # Push an event so the consumer can proceed and break
        watcher._broadcast(event)
        await asyncio.wait_for(task, timeout=2.0)
        # Allow the async generator finalizer to run
        await asyncio.sleep(0.01)

        assert len(received) == 1
        assert len(watcher._subscribers) == 0


# ---------------------------------------------------------------------------
# _http_file_filter
# ---------------------------------------------------------------------------


class TestHttpFileFilter:
    """Tests for the watchfiles filter function."""

    def test_accepts_http_files(self) -> None:
        from fling.web.watcher import _http_file_filter

        assert _http_file_filter(None, "/path/to/test.http") is True

    def test_rejects_non_http_files(self) -> None:
        from fling.web.watcher import _http_file_filter

        assert _http_file_filter(None, "/path/to/test.py") is False
        assert _http_file_filter(None, "/path/to/test.json") is False
        assert _http_file_filter(None, "/path/to/test.txt") is False


# ---------------------------------------------------------------------------
# create_app with watch parameter
# ---------------------------------------------------------------------------


class TestCreateAppWatch:
    """Tests for create_app with the watch parameter."""

    def test_directory_mode_creates_watcher(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR))
        assert app.state.watcher is not None
        assert isinstance(app.state.watcher, FileWatcher)

    def test_directory_mode_no_watch(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR), watch=False)
        assert app.state.watcher is None

    def test_single_file_mode_no_watcher(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple)
        assert app.state.watcher is None

    def test_no_args_creates_watcher(self) -> None:
        # Default to CWD — but create_app with no args will have no directory
        # so watcher is None
        app = create_app()
        assert app.state.watcher is None


# ---------------------------------------------------------------------------
# Reload endpoint (POST /reload)
# ---------------------------------------------------------------------------


class TestReloadEndpoint:
    """Tests for the POST /reload endpoint."""

    async def test_reload_json_response(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR), watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/reload", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["files"] > 0

    async def test_reload_html_response(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR), watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/reload", headers={"accept": "text/html"})
            assert resp.status_code == 200
            assert "collection-tree" in resp.text or "No requests" in resp.text

    async def test_reload_single_file_mode(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/reload", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["files"] == 1

    async def test_reload_updates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            app = create_app(directory=tmpdir, watch=False)
            transport = ASGITransport(app=app)
            assert len(app.state.files) == 1

            # Add another file
            new_path = Path(tmpdir) / "new.http"
            new_path.write_text(_SIMPLE_HTTP)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/reload", headers={"accept": "application/json"})
                data = resp.json()
                assert data["files"] == 2
                assert "new.http" in app.state.files

    async def test_reload_with_watcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            http_path = Path(tmpdir) / "test.http"
            http_path.write_text(_SIMPLE_HTTP)

            app = create_app(directory=tmpdir)
            transport = ASGITransport(app=app)

            # Add a second file
            new_path = Path(tmpdir) / "second.http"
            new_path.write_text(_SIMPLE_HTTP)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/reload", headers={"accept": "application/json"})
                data = resp.json()
                assert data["files"] == 2


# ---------------------------------------------------------------------------
# SSE /events/files endpoint
# ---------------------------------------------------------------------------


class TestFileEventsEndpoint:
    """Tests for the GET /events/files SSE endpoint."""

    def test_events_route_registered(self) -> None:
        app = create_app(directory=str(FIXTURES_DIR), watch=False)
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/events/files" in route_paths

    def test_events_route_registered_single_file(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/events/files" in route_paths


# ---------------------------------------------------------------------------
# Template updates
# ---------------------------------------------------------------------------


class TestTemplateUpdates:
    """Tests that templates include file watcher elements."""

    async def test_index_has_sse_watcher(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            # Check for SSE file watcher listener
            assert "file-watcher-sse" in resp.text
            assert "/events/files" in resp.text

    async def test_index_has_reload_button(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "reload-btn" in resp.text
            assert 'hx-post="/reload"' in resp.text

    async def test_index_has_toast_container(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "toast-container" in resp.text

    async def test_index_has_toast_script(self) -> None:
        simple = str(FIXTURES_DIR / "simple.http")
        app = create_app(file_path=simple, watch=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "showToast" in resp.text


# ---------------------------------------------------------------------------
# CLI --watch flag
# ---------------------------------------------------------------------------


class TestCLIWatchFlag:
    """Tests for the CLI serve command --watch flag."""

    def test_serve_has_watch_option(self) -> None:
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--watch" in result.output
        assert "--no-watch" in result.output
