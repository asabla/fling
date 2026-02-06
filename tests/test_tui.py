"""Tests for the TUI app scaffold, collection tree, and request panel."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Static, TextArea

from fling.tui.app import FlingApp, ResponsePanel
from fling.tui.widgets.collection_tree import CollectionTree
from fling.tui.widgets.request_panel import RequestPanel, UrlBar

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MULTIPLE_FILE = str(FIXTURES_DIR / "multiple.http")
SIMPLE_FILE = str(FIXTURES_DIR / "simple.http")
ADVANCED_FILE = str(FIXTURES_DIR / "advanced.http")
HEADERS_BODY_FILE = str(FIXTURES_DIR / "headers_body.http")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(file_path: str | None = None) -> FlingApp:
    """Create a FlingApp instance for testing."""
    return FlingApp(file_path=file_path)


def _select_first_request(app: FlingApp) -> None:
    """Select the first request node in the collection tree."""
    tree = app.query_one("#collection-tree", CollectionTree)
    first_child = tree.root.children[0]
    tree.select_node(first_child)
    tree.action_select_cursor()


# ---------------------------------------------------------------------------
# FlingApp — mounting and layout
# ---------------------------------------------------------------------------


class TestFlingAppLayout:
    """Tests for FlingApp composition and mounting."""

    @pytest.mark.asyncio
    async def test_app_mounts_successfully(self) -> None:
        """App should mount without errors."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            assert pilot.app.title == "fling"

    @pytest.mark.asyncio
    async def test_app_subtitle_shows_filename(self) -> None:
        """When a file is loaded, subtitle shows the filename."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            assert pilot.app.sub_title == "multiple.http"

    @pytest.mark.asyncio
    async def test_app_no_file_subtitle(self) -> None:
        """When no file is loaded, subtitle stays at default."""
        app = _make_app()
        async with app.run_test() as pilot:
            assert pilot.app.sub_title == "HTTP API Testing"

    @pytest.mark.asyncio
    async def test_app_has_sidebar(self) -> None:
        """App should have a sidebar container."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            sidebar = app.query_one("#sidebar")
            assert sidebar is not None

    @pytest.mark.asyncio
    async def test_app_has_content_area(self) -> None:
        """App should have a content container."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            content = app.query_one("#content")
            assert content is not None

    @pytest.mark.asyncio
    async def test_app_has_collection_tree(self) -> None:
        """App should contain a CollectionTree widget."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree is not None

    @pytest.mark.asyncio
    async def test_app_has_request_panel(self) -> None:
        """App should contain a RequestPanel widget."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            panel = app.query_one("#request-panel", RequestPanel)
            assert panel is not None

    @pytest.mark.asyncio
    async def test_app_has_response_panel(self) -> None:
        """App should contain a ResponsePanel widget."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            panel = app.query_one("#response-panel", ResponsePanel)
            assert panel is not None


# ---------------------------------------------------------------------------
# CollectionTree — populating and selection
# ---------------------------------------------------------------------------


class TestCollectionTree:
    """Tests for the CollectionTree widget."""

    @pytest.mark.asyncio
    async def test_tree_loads_requests(self) -> None:
        """Tree should show all requests from the .http file."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 3

    @pytest.mark.asyncio
    async def test_tree_single_request(self) -> None:
        """Tree should show one request for a single-request file."""
        app = _make_app(SIMPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 1

    @pytest.mark.asyncio
    async def test_tree_no_file(self) -> None:
        """Tree should have zero requests when no file is loaded."""
        app = _make_app()
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 0

    @pytest.mark.asyncio
    async def test_tree_root_label_shows_file_path(self) -> None:
        """Tree root label should show the file path."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            tree = app.query_one("#collection-tree", CollectionTree)
            root_label = str(tree.root.label)
            assert "multiple.http" in root_label

    @pytest.mark.asyncio
    async def test_tree_root_label_no_file(self) -> None:
        """Tree root should say 'No file loaded' without a file."""
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
        """Clicking a request in the tree should update RequestPanel."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            # The URL bar should show the request method
            url_bar = app.query_one("#url-bar", UrlBar)
            rendered = str(url_bar.render())
            assert "GET" in rendered

    @pytest.mark.asyncio
    async def test_selected_request_stored_on_app(self) -> None:
        """After selection, _selected_request should be set."""
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
        """The 'q' quit binding should be registered."""
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "q" in binding_keys

    @pytest.mark.asyncio
    async def test_run_binding_registered(self) -> None:
        """The ctrl+r run binding should be registered."""
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "ctrl+r" in binding_keys

    @pytest.mark.asyncio
    async def test_reload_binding_registered(self) -> None:
        """The 'r' reload binding should be registered."""
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "r" in binding_keys

    @pytest.mark.asyncio
    async def test_env_binding_registered(self) -> None:
        """The ctrl+e env binding should be registered."""
        app = _make_app()
        async with app.run_test():
            binding_keys = [b.key for b in app.BINDINGS]
            assert "ctrl+e" in binding_keys

    @pytest.mark.asyncio
    async def test_next_binding_registered(self) -> None:
        """The ctrl+n next binding should be registered."""
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
        """Reload should rebuild the collection tree."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)
            assert tree.request_count == 3

            # Trigger reload
            await pilot.press("r")
            await pilot.pause()

            assert tree.request_count == 3

    @pytest.mark.asyncio
    async def test_reload_clears_selection(self) -> None:
        """Reload should clear the selected request."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            # Select a request first
            _select_first_request(app)
            await pilot.pause()
            assert app._selected_request is not None

            # Reload
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
        """URL bar should display the method and URL."""
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
        """URL bar should show placeholder when no request selected."""
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
        """Headers DataTable should contain the request headers."""
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            assert table.row_count == 3  # Content-Type, Accept, Authorization

    @pytest.mark.asyncio
    async def test_headers_table_empty_for_no_headers(self) -> None:
        """Headers table should be empty for requests without headers."""
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            table = app.query_one("#headers-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_headers_table_has_columns(self) -> None:
        """Headers table should have Header and Value columns."""
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
        """Body TextArea should contain the request body content."""
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert "username" in body.text
            assert "admin" in body.text

    @pytest.mark.asyncio
    async def test_body_text_empty_for_get(self) -> None:
        """Body TextArea should be empty for GET requests."""
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.text == ""

    @pytest.mark.asyncio
    async def test_body_text_json_language(self) -> None:
        """Body TextArea should detect JSON content type."""
        app = _make_app(HEADERS_BODY_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            body = app.query_one("#body-text", TextArea)
            assert body.language == "json"

    @pytest.mark.asyncio
    async def test_body_read_only(self) -> None:
        """Body TextArea should be read-only."""
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
        """Info tab should display the request name."""
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "login" in text

    @pytest.mark.asyncio
    async def test_info_shows_timeout(self) -> None:
        """Info tab should display timeout flag."""
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "5000" in text

    @pytest.mark.asyncio
    async def test_info_shows_note(self) -> None:
        """Info tab should display the request note."""
        app = _make_app(ADVANCED_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "Authentication request" in text

    @pytest.mark.asyncio
    async def test_info_empty_metadata(self) -> None:
        """Info tab should show placeholder for requests without metadata."""
        app = _make_app(SIMPLE_FILE)
        async with app.run_test() as pilot:
            _select_first_request(app)
            await pilot.pause()

            info = app.query_one("#info-text", Static)
            text = str(info.render())
            assert "No additional metadata" in text

    @pytest.mark.asyncio
    async def test_info_shows_response_handler(self) -> None:
        """Info tab should note presence of response handler."""
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
        """Clearing the panel should reset the URL bar."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            # Select a request
            _select_first_request(app)
            await pilot.pause()

            # Clear
            panel = app.query_one("#request-panel", RequestPanel)
            panel.clear_request()
            await pilot.pause()

            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "No request selected" in text

    @pytest.mark.asyncio
    async def test_clear_empties_headers(self) -> None:
        """Clearing the panel should empty the headers table."""
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
        """Clearing the panel should empty the body text."""
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
        """Selecting a different request should update all panel content."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)

            # Select first (GET)
            first = tree.root.children[0]
            tree.select_node(first)
            tree.action_select_cursor()
            await pilot.pause()
            assert app._selected_request is not None
            assert app._selected_request.method.value == "GET"

            # Select second (POST)
            second = tree.root.children[1]
            tree.select_node(second)
            tree.action_select_cursor()
            await pilot.pause()
            assert app._selected_request.method.value == "POST"

            url_bar = app.query_one("#url-bar", UrlBar)
            text = str(url_bar.render())
            assert "POST" in text


# ---------------------------------------------------------------------------
# CLI tui command
# ---------------------------------------------------------------------------


class TestTuiCliCommand:
    """Tests for the `fling tui` CLI command."""

    def test_tui_help(self) -> None:
        """The tui command should show help text."""
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the interactive TUI" in result.output

    def test_tui_listed_in_main_help(self) -> None:
        """The tui command should appear in the main help."""
        from click.testing import CliRunner

        from fling.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "tui" in result.output
