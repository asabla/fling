"""Main Textual TUI application for fling."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from fling.core.parser import parse_http_file
from fling.tui.widgets.collection_tree import CollectionTree
from fling.tui.widgets.request_panel import RequestPanel

if TYPE_CHECKING:
    from fling.core.models import HttpFile, HttpRequestDefinition


class ResponsePanel(Static):
    """Placeholder for the response panel (Task 4.3).

    Shows a message until execution support is added.
    """

    DEFAULT_CSS = """
    ResponsePanel {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
        border-top: solid $surface-lighten-2;
    }
    """

    def on_mount(self) -> None:
        self.update("[dim]Response will appear here after running a request (Ctrl+R)[/]")


class FlingApp(App[None]):
    """The main fling TUI application.

    A read-only runner for .http files with a collection tree sidebar,
    request detail panel, and response panel.
    """

    TITLE = "fling"
    SUB_TITLE = "HTTP API Testing"

    CSS_PATH = "styles/app.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+r", "run_request", "Run", show=True),
        Binding("ctrl+n", "next_request", "Next", show=True),
        Binding("ctrl+e", "select_env", "Env", show=True),
        Binding("r", "reload", "Reload", show=True),
    ]

    def __init__(
        self,
        file_path: str | None = None,
        env_name: str | None = None,
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._env_name = env_name
        self._http_file: HttpFile | None = None
        self._selected_request: HttpRequestDefinition | None = None

        if file_path:
            self._load_file(file_path)

    def _load_file(self, file_path: str) -> None:
        """Parse the .http file and store the result."""
        result = parse_http_file(file_path)
        if result.has_errors:
            self.notify(
                f"Parse errors in {file_path}",
                severity="error",
            )
        self._http_file = result.http_file

    def compose(self) -> ComposeResult:
        """Create the app layout."""
        yield Header()
        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield CollectionTree(
                    self._http_file,
                    id="collection-tree",
                )
            with Vertical(id="content"):
                yield RequestPanel(id="request-panel")
                yield ResponsePanel(id="response-panel")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the app after mounting."""
        if self._file_path:
            self.sub_title = Path(self._file_path).name
        else:
            request_panel = self.query_one("#request-panel", RequestPanel)
            request_panel.clear_request()

    def on_collection_tree_request_selected(
        self,
        event: CollectionTree.RequestSelected,
    ) -> None:
        """Handle request selection from the collection tree."""
        self._selected_request = event.request
        request_panel = self.query_one("#request-panel", RequestPanel)
        request_panel.update_request(event.request)

    def action_run_request(self) -> None:
        """Run the currently selected request (placeholder for Task 4.3)."""
        if self._selected_request:
            self.notify("Execution will be available in a future update", severity="warning")
        else:
            self.notify("No request selected", severity="warning")

    def action_next_request(self) -> None:
        """Move to the next request in the tree."""
        tree = self.query_one("#collection-tree", CollectionTree)
        tree.action_cursor_down()
        tree.action_select_cursor()

    def action_select_env(self) -> None:
        """Select an environment (placeholder for Task 4.3)."""
        self.notify("Environment selection will be available in a future update", severity="warning")

    def action_reload(self) -> None:
        """Reload the current .http file."""
        if self._file_path:
            self._load_file(self._file_path)
            tree = self.query_one("#collection-tree", CollectionTree)
            tree.load_file(self._http_file)  # type: ignore[arg-type]
            request_panel = self.query_one("#request-panel", RequestPanel)
            request_panel.clear_request()
            self._selected_request = None
            self.notify("File reloaded")
        else:
            self.notify("No file to reload", severity="warning")
