"""Tests for the TUI app scaffold and collection tree widget."""

from __future__ import annotations

from pathlib import Path

import pytest

from fling.tui.app import FlingApp, RequestDetail, ResponsePanel
from fling.tui.widgets.collection_tree import CollectionTree

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MULTIPLE_FILE = str(FIXTURES_DIR / "multiple.http")
SIMPLE_FILE = str(FIXTURES_DIR / "simple.http")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(file_path: str | None = None) -> FlingApp:
    """Create a FlingApp instance for testing."""
    return FlingApp(file_path=file_path)


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
    async def test_app_has_request_detail(self) -> None:
        """App should contain a RequestDetail widget."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test():
            detail = app.query_one("#request-detail", RequestDetail)
            assert detail is not None

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
    async def test_selecting_request_updates_detail(self) -> None:
        """Clicking a request in the tree should update RequestDetail."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)
            # Select the first leaf node (first request)
            first_child = tree.root.children[0]
            tree.select_node(first_child)
            tree.action_select_cursor()
            await pilot.pause()

            detail = app.query_one("#request-detail", RequestDetail)
            rendered = detail.render()
            rendered_text = str(rendered)
            assert "GET" in rendered_text

    @pytest.mark.asyncio
    async def test_selected_request_stored_on_app(self) -> None:
        """After selection, _selected_request should be set."""
        app = _make_app(MULTIPLE_FILE)
        async with app.run_test() as pilot:
            tree = app.query_one("#collection-tree", CollectionTree)
            first_child = tree.root.children[0]
            tree.select_node(first_child)
            tree.action_select_cursor()
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
            tree = app.query_one("#collection-tree", CollectionTree)
            first_child = tree.root.children[0]
            tree.select_node(first_child)
            tree.action_select_cursor()
            await pilot.pause()
            assert app._selected_request is not None

            # Reload
            await pilot.press("r")
            await pilot.pause()
            assert app._selected_request is None


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
