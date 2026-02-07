"""Progress panel widget for the fling TUI.

Displays the progress of running all requests in a collection:
- Overall progress bar (X/N requests)
- Per-request status (pending, running, success, error, skipped)
- Elapsed time
- Summary after completion
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import DataTable, ProgressBar, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.widgets._data_table import RowKey

    from fling.core.models import ExecutionResult, HttpRequestDefinition


class RequestStatus(StrEnum):
    """Status of a request during a collection run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


_STATUS_STYLES: dict[RequestStatus, str] = {
    RequestStatus.PENDING: "dim",
    RequestStatus.RUNNING: "bold cyan",
    RequestStatus.SUCCESS: "bold green",
    RequestStatus.ERROR: "bold red",
    RequestStatus.SKIPPED: "dim yellow",
}


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds for display."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


class SummaryBar(Static):
    """Displays overall run summary: total, passed, failed, elapsed."""

    DEFAULT_CSS = """
    SummaryBar {
        height: 3;
        padding: 1 2 0 2;
        background: $surface;
    }
    """

    def show_idle(self) -> None:
        """Show idle state."""
        self.update("[dim]Press Ctrl+Shift+R to run all requests[/]")

    def show_running(self, completed: int, total: int, elapsed: float) -> None:
        """Show running progress."""
        elapsed_str = _format_elapsed(elapsed)
        self.update(f"[bold cyan]Running...[/]  [bold]{completed}[/]/{total}  [dim]{elapsed_str}[/]")

    def show_complete(
        self,
        total: int,
        passed: int,
        failed: int,
        skipped: int,
        elapsed: float,
    ) -> None:
        """Show completion summary."""
        elapsed_str = _format_elapsed(elapsed)
        parts: list[str] = [f"[bold]Done[/]  {total} requests"]
        if passed:
            parts.append(f"[green]{passed} passed[/]")
        if failed:
            parts.append(f"[red]{failed} failed[/]")
        if skipped:
            parts.append(f"[yellow]{skipped} skipped[/]")
        parts.append(f"[dim]{elapsed_str}[/]")
        self.update("  ".join(parts))


class ProgressPanel(Vertical):
    """Panel showing the progress of running all requests.

    Contains a summary bar, progress bar, and a per-request status table.
    """

    DEFAULT_CSS = """
    ProgressPanel {
        height: 1fr;
        width: 1fr;
        border-top: solid $surface-lighten-2;
        display: none;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._total = 0
        self._completed = 0
        self._passed = 0
        self._failed = 0
        self._skipped = 0
        self._start_time: float | None = None
        self._request_rows: dict[str, RowKey] = {}  # request name -> RowKey

    def compose(self) -> ComposeResult:
        yield SummaryBar(id="summary-bar")
        yield ProgressBar(id="run-progress-bar", total=100, show_eta=False)
        yield DataTable(id="request-status-table")

    def on_mount(self) -> None:
        """Set up the request status table."""
        table = self.query_one("#request-status-table", DataTable)
        table.add_columns("Status", "Method", "Request", "Time", "Code")
        table.cursor_type = "row"
        table.zebra_stripes = True

        summary_bar = self.query_one("#summary-bar", SummaryBar)
        summary_bar.show_idle()

    def start_run(self, requests: list[HttpRequestDefinition]) -> None:
        """Initialize a new collection run.

        Args:
            requests: List of requests that will be executed.
        """
        self._total = len(requests)
        self._completed = 0
        self._passed = 0
        self._failed = 0
        self._skipped = 0
        self._start_time = time.monotonic()
        self._request_rows.clear()

        # Show the panel
        self.display = True

        # Reset progress bar
        progress_bar = self.query_one("#run-progress-bar", ProgressBar)
        progress_bar.update(total=self._total, progress=0)

        # Reset table
        table = self.query_one("#request-status-table", DataTable)
        table.clear()

        # Add a row for each request as "pending"
        for request in requests:
            name = request.metadata.name or request.url
            method = request.method.value
            row_key = table.add_row(
                self._status_text(RequestStatus.PENDING),
                method,
                name,
                "",
                "",
            )
            self._request_rows[name] = row_key

        # Update summary
        summary_bar = self.query_one("#summary-bar", SummaryBar)
        summary_bar.show_running(0, self._total, 0.0)

    def update_request_running(self, request: HttpRequestDefinition) -> None:
        """Mark a request as currently running.

        Args:
            request: The request that started executing.
        """
        name = request.metadata.name or request.url
        table = self.query_one("#request-status-table", DataTable)

        row_key = self._request_rows.get(name)
        if row_key is not None:
            # Update status column using coordinate-based update
            self._update_row_status(table, row_key, RequestStatus.RUNNING)

    def update_request_complete(
        self,
        request: HttpRequestDefinition,
        result: ExecutionResult,
    ) -> None:
        """Mark a request as completed with its result.

        Args:
            request: The completed request.
            result: The execution result.
        """
        self._completed += 1
        name = request.metadata.name or request.url

        if result.error:
            status = RequestStatus.ERROR
            self._failed += 1
        else:
            status = RequestStatus.SUCCESS
            self._passed += 1

        table = self.query_one("#request-status-table", DataTable)
        row_key = self._request_rows.get(name)
        if row_key is not None:
            self._update_row_status(table, row_key, status)
            self._update_row_result(table, row_key, result)

        # Update progress bar
        progress_bar = self.query_one("#run-progress-bar", ProgressBar)
        progress_bar.update(progress=self._completed)

        # Update summary
        elapsed = time.monotonic() - (self._start_time or time.monotonic())
        summary_bar = self.query_one("#summary-bar", SummaryBar)
        summary_bar.show_running(self._completed, self._total, elapsed)

    def finish_run(self) -> None:
        """Mark the run as complete and show summary."""
        elapsed = time.monotonic() - (self._start_time or time.monotonic())
        summary_bar = self.query_one("#summary-bar", SummaryBar)
        summary_bar.show_complete(
            total=self._total,
            passed=self._passed,
            failed=self._failed,
            skipped=self._skipped,
            elapsed=elapsed,
        )

    def reset(self) -> None:
        """Reset and hide the progress panel."""
        self.display = False
        self._total = 0
        self._completed = 0
        self._passed = 0
        self._failed = 0
        self._skipped = 0
        self._start_time = None
        self._request_rows.clear()

        table = self.query_one("#request-status-table", DataTable)
        table.clear()

        progress_bar = self.query_one("#run-progress-bar", ProgressBar)
        progress_bar.update(total=100, progress=0)

        summary_bar = self.query_one("#summary-bar", SummaryBar)
        summary_bar.show_idle()

    @staticmethod
    def _status_text(status: RequestStatus) -> Text:
        """Create a styled Rich Text for a request status."""
        style = _STATUS_STYLES.get(status, "")
        return Text(status.value.upper(), style=style)

    def _update_row_status(
        self,
        table: DataTable[str],
        row_key: RowKey,
        status: RequestStatus,
    ) -> None:
        """Update the status cell for a row."""
        status_col_key = next(iter(table.columns.keys()))
        table.update_cell(row_key, status_col_key, self._status_text(status))  # type: ignore[arg-type]

    def _update_row_result(
        self,
        table: DataTable[str],
        row_key: RowKey,
        result: ExecutionResult,
    ) -> None:
        """Update the time and status code cells for a row."""
        columns = list(table.columns.keys())
        time_col_key = columns[3]  # "Time" column
        code_col_key = columns[4]  # "Code" column

        elapsed_str = f"{result.elapsed_ms:.0f}ms" if result.elapsed_ms else ""
        code_str = str(result.status_code) if result.status_code else ""

        if result.error:
            code_str = Text("ERR", style="bold red")  # type: ignore[assignment]

        table.update_cell(row_key, time_col_key, elapsed_str)
        table.update_cell(row_key, code_col_key, code_str)

    @property
    def total(self) -> int:
        """Total number of requests in the run."""
        return self._total

    @property
    def completed(self) -> int:
        """Number of completed requests."""
        return self._completed

    @property
    def is_running(self) -> bool:
        """Whether a run is in progress."""
        return self._start_time is not None and self._completed < self._total
