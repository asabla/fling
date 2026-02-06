"""Main Textual TUI application for fling."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Select

from fling.core.environment import list_environments, load_environment
from fling.core.models import HttpFile as HttpFileModel
from fling.core.parser import parse_http_file
from fling.core.runner import HttpRunner
from fling.tui.widgets.collection_tree import CollectionTree
from fling.tui.widgets.request_panel import RequestPanel
from fling.tui.widgets.response_panel import ResponsePanel

if TYPE_CHECKING:
    from fling.core.models import ExecutionResult, HttpFile, HttpRequestDefinition


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
        self._environments: list[str] = []

        if file_path:
            self._load_file(file_path)
            self._load_environments(file_path)

    def _load_file(self, file_path: str) -> None:
        """Parse the .http file and store the result."""
        result = parse_http_file(file_path)
        if result.has_errors:
            self.notify(
                f"Parse errors in {file_path}",
                severity="error",
            )
        self._http_file = result.http_file

    def _load_environments(self, file_path: str) -> None:
        """Load available environments from the file's directory."""
        env_dir = Path(file_path).parent
        env_config = load_environment(str(env_dir))
        if env_config:
            self._environments = sorted(list_environments(env_config))

    def compose(self) -> ComposeResult:
        """Create the app layout."""
        yield Header()
        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield CollectionTree(
                    self._http_file,
                    id="collection-tree",
                )
                yield Select[str](
                    self._build_env_options(),
                    prompt="Environment",
                    id="env-select",
                    allow_blank=True,
                )
            with Vertical(id="content"):
                yield RequestPanel(id="request-panel")
                yield ResponsePanel(id="response-panel")
        yield Footer()

    def _build_env_options(self) -> list[tuple[str, str]]:
        """Build options for the environment selector."""
        return [(name, name) for name in self._environments]

    def on_mount(self) -> None:
        """Set up the app after mounting."""
        if self._file_path:
            self.sub_title = Path(self._file_path).name
        else:
            request_panel = self.query_one("#request-panel", RequestPanel)
            request_panel.clear_request()

        # Set initial env selection if provided
        if self._env_name and self._env_name in self._environments:
            env_select = self.query_one("#env-select", Select)
            env_select.value = self._env_name

    def on_collection_tree_request_selected(
        self,
        event: CollectionTree.RequestSelected,
    ) -> None:
        """Handle request selection from the collection tree."""
        self._selected_request = event.request
        request_panel = self.query_one("#request-panel", RequestPanel)
        request_panel.update_request(event.request)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle environment selection change."""
        if event.select.id == "env-select":
            self._env_name = str(event.value) if event.value != Select.BLANK else None
            env_label = self._env_name or "none"
            self.notify(f"Environment: {env_label}")

    def action_run_request(self) -> None:
        """Run the currently selected request."""
        if not self._selected_request:
            self.notify("No request selected", severity="warning")
            return
        if not self._http_file:
            self.notify("No file loaded", severity="warning")
            return

        response_panel = self.query_one("#response-panel", ResponsePanel)
        response_panel.show_loading()
        self._execute_request(self._selected_request)

    @work(exclusive=True, thread=False)
    async def _execute_request(self, request: HttpRequestDefinition) -> None:
        """Execute the request in a background worker.

        Uses @work(exclusive=True) to cancel any previous execution.
        """
        assert self._http_file is not None

        env_dir = Path(self._file_path).parent if self._file_path else Path(".")
        env_config = load_environment(str(env_dir))

        runner = HttpRunner(
            env_file=env_config,
            env_name=self._env_name,
        )

        response_panel = self.query_one("#response-panel", ResponsePanel)

        # Build a single-request HttpFile
        single_file = HttpFileModel(
            file_path=self._http_file.file_path,
            variables=self._http_file.variables,
            requests=[request],
        )

        result: ExecutionResult | None = None
        if request.metadata.name:
            async for _req, res in runner.run_single(self._http_file, request.metadata.name):
                result = res
        else:
            async for _req, res in runner.run_all(single_file):
                result = res

        if result:
            response_panel.show_result(result)
        else:
            self.notify("No result returned", severity="warning")

    def action_next_request(self) -> None:
        """Move to the next request in the tree."""
        tree = self.query_one("#collection-tree", CollectionTree)
        tree.action_cursor_down()
        tree.action_select_cursor()

    def action_select_env(self) -> None:
        """Focus the environment selector."""
        env_select = self.query_one("#env-select", Select)
        env_select.focus()

    def action_reload(self) -> None:
        """Reload the current .http file."""
        if self._file_path:
            self._load_file(self._file_path)
            self._load_environments(self._file_path)
            tree = self.query_one("#collection-tree", CollectionTree)
            tree.load_file(self._http_file)  # type: ignore[arg-type]
            request_panel = self.query_one("#request-panel", RequestPanel)
            request_panel.clear_request()
            response_panel = self.query_one("#response-panel", ResponsePanel)
            response_panel.clear_result()
            self._selected_request = None

            # Refresh env selector
            env_select = self.query_one("#env-select", Select)
            env_select.set_options(self._build_env_options())

            self.notify("File reloaded")
        else:
            self.notify("No file to reload", severity="warning")
