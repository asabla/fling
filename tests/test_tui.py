"""Tests for the TUI app scaffold, collection tree, request panel, and response panel."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, RichLog, Select, Static, TextArea

from fling.core.models import (
    ExecutionResult,
    HttpMethod,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.tui.app import FlingApp
from fling.tui.widgets.collection_tree import CollectionTree
from fling.tui.widgets.request_panel import RequestPanel, UrlBar
from fling.tui.widgets.response_panel import ResponsePanel, StatusBar

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MULTIPLE_FILE = str(FIXTURES_DIR / "multiple.http")
SIMPLE_FILE = str(FIXTURES_DIR / "simple.http")
ADVANCED_FILE = str(FIXTURES_DIR / "advanced.http")
HEADERS_BODY_FILE = str(FIXTURES_DIR / "headers_body.http")

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(file_path: str | None = None, env_name: str | None = None) -> FlingApp:
    """Create a FlingApp instance for testing."""
    return FlingApp(file_path=file_path, env_name=env_name)


def _select_first_request(app: FlingApp) -> None:
    """Select the first request node in the collection tree."""
    tree = app.query_one("#collection-tree", CollectionTree)
    first_child = tree.root.children[0]
    tree.select_node(first_child)
    tree.action_select_cursor()


def _make_result(
    *,
    status_code: int = 200,
    body: str = '{"ok": true}',
    headers: dict[str, list[str]] | None = None,
    elapsed_ms: float = 42.0,
    error: str | None = None,
) -> ExecutionResult:
    """Create a test ExecutionResult."""
    return ExecutionResult(
        request=HttpRequestDefinition(
            method=HttpMethod.GET,
            url="https://api.example.com/test",
            location=_LOC,
        ),
        resolved_url="https://api.example.com/test",
        status_code=status_code,
        response_body=body,
        response_headers=headers or {"content-type": ["application/json"]},
        elapsed_ms=elapsed_ms,
        error=error,
    )


# ---------------------------------------------------------------------------
# FlingApp — mounting and layout
# ---------------------------------------------------------------------------


class TestFlingAppLayout:
    """Tests for FlingApp composition and mounting."""

    @pytest.mark.asyncio
    async def test_app_mounts_successfully(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            assert pilot.app.title == "fling"

    @pytest.mark.asyncio
    async def test_app_subtitle_shows_filename(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            assert pilot.app.sub_title == "multiple.http"

    @pytest.mark.asyncio
    async def test_app_no_file_subtitle(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            assert pilot.app.sub_title == "HTTP API Testing"

    @pytest.mark.asyncio
    async def test_app_has_sidebar(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            sidebar = app.query_one("#sidebar")
            assert sidebar is not None

    @pytest.mark.asyncio
    async def test_app_has_content_area(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            content = app.query_one("#content")
            assert content is not None

    @pytest.mark.asyncio
    async def test_app_has_collection_tree(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree is not None

    @pytest.mark.asyncio
    async def test_app_has_request_panel(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            panel = app.query_one("#request-panel", RequestPanel)
            assert panel is not None

    @pytest.mark.asyncio
    async def test_app_has_response_panel(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            panel = app.query_one("#response-panel", ResponsePanel)
            assert panel is not None

    @pytest.mark.asyncio
    async def test_app_has_env_selector(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            env_select = app.query_one("#env-select", Select)
            assert env_select is not None


# ---------------------------------------------------------------------------
# CollectionTree — populating and selection
# ---------------------------------------------------------------------------


class TestCollectionTree:
    """Tests for the CollectionTree widget."""

    @pytest.mark.asyncio
    async def test_tree_loads_requests(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 3

    @pytest.mark.asyncio
    async def test_tree_single_request(self) -> None:
        app = _make_app(SIMPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 1

    @pytest.mark.asyncio
    async def test_tree_no_file(self) -> None:
        app = _make_app()
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 0

    @pytest.mark.asyncio
    async def test_tree_root_label_shows_file_path(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            root_label = str(tree.root.label)
            assert "multiple.http" in root_label

    @pytest.mark.asyncio
    async def test_tree_root_label_no_file(self) -> None:
        app = _make_app()
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert str(tree.root.label) == "No file loaded"


# ---------------------------------------------------------------------------
# Request selection
# ---------------------------------------------------------------------------


class TestRequestSelection:
    """Tests for selecting a request from the tree."""

    @pytest.mark.asyncio
    async def test_selecting_request_updates_panel(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            url_bar = app.query_one("#url-bar", UrlBar)
            rendered = str(url_bar.render())
            assert "GET" in rendered

    @pytest.mark.asyncio
    async def test_selected_request_stored_on_app(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            assert app._selected_request is not None
            assert app._selected_request.method.value == "GET"


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------


class TestKeyBindings:
    """Tests for TUI key bindings."""

    @pytest.mark.asyncio
    async def test_quit_binding_registered(self) -> None:
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "q" in binding_keys

    @pytest.mark.asyncio
    async def test_run_binding_registered(self) -> None:
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "ctrl+r" in binding_keys

    @pytest.mark.asyncio
    async def test_reload_binding_registered(self) -> None:
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "r" in binding_keys

    @pytest.mark.asyncio
    async def test_env_binding_registered(self) -> None:
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "ctrl+e" in binding_keys

    @pytest.mark.asyncio
    async def test_next_binding_registered(self) -> None:
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "ctrl+n" in binding_keys


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------


class TestReload:
    """Tests for the reload action."""

    @pytest.mark.asyncio
    async def test_reload_repopulates_tree(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 3

            await pilot.press("r")
            await pilot.pause()
            assert tree.request_count == 3

    @pytest.mark.asyncio
    async def test_reload_clears_selection(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()
            assert app._selected_request is not None

            await pilot.press("r")
            await pilot.pause()
            assert app._selected_request is None


# ---------------------------------------------------------------------------
# RequestPanel — URL bar
# ---------------------------------------------------------------------------


class TestRequestPanelUrlBar:
    """Tests for the URL bar in the RequestPanel."""

    @pytest.mark.asyncio
    async def test_url_bar_shows_method_and_url(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "POST" in text
            assert "api.example.com/login" in text

    @pytest.mark.asyncio
    async def test_url_bar_empty_state(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "No request selected" in text


# ---------------------------------------------------------------------------
# RequestPanel — Headers tab
# ---------------------------------------------------------------------------


class TestRequestPanelHeaders:
    """Tests for the Headers tab in the RequestPanel."""

    @pytest.mark.asyncio
    async def test_headers_table_populated(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            assert table.row_count == 3

    @pytest.mark.asyncio
    async def test_headers_table_empty_for_no_headers(self) -> None:
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_headers_table_has_columns(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            col_labels = [str(col.label) for col in table.columns.values()]
            assert "Header" in col_labels
            assert "Value" in col_labels


# ---------------------------------------------------------------------------
# RequestPanel — Body tab
# ---------------------------------------------------------------------------


class TestRequestPanelBody:
    """Tests for the Body tab in the RequestPanel."""

    @pytest.mark.asyncio
    async def test_body_text_populated(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert "username" in body.text
            assert "admin" in body.text

    @pytest.mark.asyncio
    async def test_body_text_empty_for_get(self) -> None:
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.text == ""

    @pytest.mark.asyncio
    async def test_body_text_json_language(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.language == "json"

    @pytest.mark.asyncio
    async def test_body_read_only(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.read_only is True


# ---------------------------------------------------------------------------
# RequestPanel — Info tab
# ---------------------------------------------------------------------------


class TestRequestPanelInfo:
    """Tests for the Info tab in the RequestPanel."""

    @pytest.mark.asyncio
    async def test_info_shows_name(self) -> None:
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "login" in text

    @pytest.mark.asyncio
    async def test_info_shows_timeout(self) -> None:
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "5000" in text

    @pytest.mark.asyncio
    async def test_info_shows_note(self) -> None:
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "Authentication request" in text

    @pytest.mark.asyncio
    async def test_info_empty_metadata(self) -> None:
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "No additional metadata" in text

    @pytest.mark.asyncio
    async def test_info_shows_response_handler(self) -> None:
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "Response Handler" in text


# ---------------------------------------------------------------------------
# RequestPanel — clear and update cycle
# ---------------------------------------------------------------------------


class TestRequestPanelClearUpdate:
    """Tests for clearing and updating the request panel."""

    @pytest.mark.asyncio
    async def test_clear_resets_url_bar(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            panel = app.query_one("#request-panel", RequestPanel)
            panel.clear_request()
            await pilot.pause()

            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "No request selected" in text

    @pytest.mark.asyncio
    async def test_clear_empties_headers(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            panel = app.query_one("#request-panel", RequestPanel)
            panel.clear_request()
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_clear_empties_body(self) -> None:
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            panel = app.query_one("#request-panel", RequestPanel)
            panel.clear_request()
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.text == ""

    @pytest.mark.asyncio
    async def test_switching_requests_updates_panel(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)

            first = tree.root.children[0]
            tree.select_node(first)
            tree.action_select_cursor()
            await pilot.pause()
            assert app._selected_request is not None
            assert app._selected_request.method.value == "GET"

            second = tree.root.children[1]
            tree.select_node(second)
            tree.action_select_cursor()
            await pilot.pause()
            assert app._selected_request.method.value == "POST"

            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "POST" in text


# ---------------------------------------------------------------------------
# ResponsePanel — status bar
# ---------------------------------------------------------------------------


class TestResponsePanelStatusBar:
    """Tests for the StatusBar in the ResponsePanel."""

    @pytest.mark.asyncio
    async def test_status_bar_shows_status_code(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(status_code=200)
            response_panel.show_result(result)
            await pilot.pause()

            status_bar = app.query_one("#status-bar", StatusBar)
            text = str(status_bar.render())
            assert "200" in text

    @pytest.mark.asyncio
    async def test_status_bar_shows_elapsed_time(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(elapsed_ms=150.0)
            response_panel.show_result(result)
            await pilot.pause()

            status_bar = app.query_one("#status-bar", StatusBar)
            text = str(status_bar.render())
            assert "150ms" in text

    @pytest.mark.asyncio
    async def test_status_bar_shows_error(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(error="Connection refused")
            response_panel.show_result(result)
            await pilot.pause()

            status_bar = app.query_one("#status-bar", StatusBar)
            text = str(status_bar.render())
            assert "ERROR" in text
            assert "Connection refused" in text

    @pytest.mark.asyncio
    async def test_status_bar_loading_state(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            response_panel.show_loading()
            await pilot.pause()

            status_bar = app.query_one("#status-bar", StatusBar)
            text = str(status_bar.render())
            assert "Running" in text


# ---------------------------------------------------------------------------
# ResponsePanel — body
# ---------------------------------------------------------------------------


class TestResponsePanelBody:
    """Tests for the response body RichLog."""

    @pytest.mark.asyncio
    async def test_body_shows_json_response(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(body='{"name": "test"}')
            response_panel.show_result(result)
            await pilot.pause()

            body_log = app.query_one("#response-body", RichLog)
            assert len(body_log.lines) > 0

    @pytest.mark.asyncio
    async def test_body_shows_empty_for_empty_response(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(body="", headers={})
            response_panel.show_result(result)
            await pilot.pause()

            body_log = app.query_one("#response-body", RichLog)
            assert len(body_log.lines) > 0  # Shows "Empty response body"

    @pytest.mark.asyncio
    async def test_body_shows_error_message(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(error="Timeout", body="")
            response_panel.show_result(result)
            await pilot.pause()

            body_log = app.query_one("#response-body", RichLog)
            assert len(body_log.lines) > 0


# ---------------------------------------------------------------------------
# ResponsePanel — headers
# ---------------------------------------------------------------------------


class TestResponsePanelHeaders:
    """Tests for the response headers DataTable."""

    @pytest.mark.asyncio
    async def test_response_headers_populated(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(
                headers={
                    "content-type": ["application/json"],
                    "x-request-id": ["abc-123"],
                },
            )
            response_panel.show_result(result)
            await pilot.pause()

            table = app.query_one("#response-headers-table", DataTable)
            assert table.row_count == 2

    @pytest.mark.asyncio
    async def test_response_headers_empty_initially(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            table = app.query_one("#response-headers-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_response_headers_multi_value(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            result = _make_result(
                headers={"set-cookie": ["a=1", "b=2"]},
            )
            response_panel.show_result(result)
            await pilot.pause()

            table = app.query_one("#response-headers-table", DataTable)
            assert table.row_count == 2


# ---------------------------------------------------------------------------
# ResponsePanel — clear
# ---------------------------------------------------------------------------


class TestResponsePanelClear:
    """Tests for clearing the response panel."""

    @pytest.mark.asyncio
    async def test_clear_resets_status(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            response_panel.show_result(_make_result())
            await pilot.pause()

            response_panel.clear_result()
            await pilot.pause()

            status_bar = app.query_one("#status-bar", StatusBar)
            text = str(status_bar.render())
            assert "Run a request" in text

    @pytest.mark.asyncio
    async def test_clear_empties_headers_table(self) -> None:
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            await pilot.pause()

            response_panel = app.query_one("#response-panel", ResponsePanel)
            response_panel.show_result(
                _make_result(headers={"x-foo": ["bar"]}),
            )
            await pilot.pause()

            response_panel.clear_result()
            await pilot.pause()

            table = app.query_one("#response-headers-table", DataTable)
            assert table.row_count == 0


# ---------------------------------------------------------------------------
# CLI tui command
# ---------------------------------------------------------------------------


class TestTuiCliCommand:
    """Tests for the `fling tui` CLI command."""

    def test_tui_help(self) -> None:
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the interactive TUI" in result.output

    def test_tui_listed_in_main_help(self) -> None:
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "tui" in result.output
