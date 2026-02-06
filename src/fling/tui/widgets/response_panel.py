"""Response panel widget for the fling TUI.

Displays the result of executing an HTTP request:
- Status bar with status code (color-coded), elapsed time, and response size
- Tabbed content: Body (RichLog with syntax highlighting), Headers (DataTable)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.widgets import DataTable, RichLog, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from fling.core.models import ExecutionResult


def _status_style(code: int) -> str:
    """Return a Rich style for an HTTP status code."""
    if code < 300:
        return "bold green"
    if code < 400:
        return "bold yellow"
    return "bold red"


def _format_elapsed(ms: float) -> str:
    """Format elapsed time for display."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _format_size(body: str) -> str:
    """Format response body size for display."""
    size = len(body.encode("utf-8"))
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


class StatusBar(Static):
    """Displays HTTP status code, elapsed time, and response size."""

    DEFAULT_CSS = """
    StatusBar {
        height: 3;
        padding: 1 2 0 2;
        background: $surface;
    }
    """

    def show_result(self, result: ExecutionResult) -> None:
        """Update the status bar with execution result."""
        if result.error:
            self.update(f"[bold red]ERROR[/]  {result.error}")
            return

        style = _status_style(result.status_code)
        elapsed = _format_elapsed(result.elapsed_ms)
        size = _format_size(result.response_body)
        self.update(f"[{style}]{result.status_code}[/]  [dim]{elapsed}[/]  [dim]{size}[/]")

    def show_loading(self) -> None:
        """Show a loading indicator."""
        self.update("[bold cyan]Running...[/]")

    def clear(self) -> None:
        """Reset to empty state."""
        self.update("[dim]Run a request with Ctrl+R to see the response[/]")


class ResponsePanel(Vertical):
    """Panel showing the response from executing an HTTP request.

    Contains a status bar at the top and tabbed content below with
    Body and Headers tabs.
    """

    DEFAULT_CSS = """
    ResponsePanel {
        height: 1fr;
        width: 1fr;
        border-top: solid $surface-lighten-2;
    }
    """

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with TabbedContent(id="response-tabs"):
            with TabPane("Body", id="tab-response-body"):
                yield RichLog(id="response-body", wrap=True, highlight=True)
            with TabPane("Headers", id="tab-response-headers"):
                yield DataTable(id="response-headers-table")

    def on_mount(self) -> None:
        """Set up the response headers table."""
        table = self.query_one("#response-headers-table", DataTable)
        table.add_columns("Header", "Value")
        table.cursor_type = "row"
        table.zebra_stripes = True

        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.clear()

    def show_loading(self) -> None:
        """Show loading state."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.show_loading()

        body_log = self.query_one("#response-body", RichLog)
        body_log.clear()
        body_log.write("[dim]Executing request...[/]")

    def show_result(self, result: ExecutionResult) -> None:
        """Display the execution result."""
        # Status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.show_result(result)

        # Body
        self._update_body(result)

        # Headers
        self._update_headers(result)

    def clear_result(self) -> None:
        """Reset to empty state."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.clear()

        body_log = self.query_one("#response-body", RichLog)
        body_log.clear()

        table = self.query_one("#response-headers-table", DataTable)
        table.clear()

    def _update_body(self, result: ExecutionResult) -> None:
        """Populate the response body RichLog."""
        body_log = self.query_one("#response-body", RichLog)
        body_log.clear()

        if result.error:
            body_log.write(f"[bold red]Error:[/] {result.error}")
            return

        body = result.response_body
        if not body:
            body_log.write("[dim]Empty response body[/]")
            return

        # Try to pretty-print JSON
        content_types = result.response_headers.get("content-type", [])
        is_json = any("json" in ct for ct in content_types) or _looks_like_json(body)

        if is_json:
            try:
                parsed = json.loads(body)
                formatted = json.dumps(parsed, indent=2)
                from rich.syntax import Syntax

                syntax = Syntax(formatted, "json", theme="monokai", word_wrap=True)
                body_log.write(syntax)
            except (json.JSONDecodeError, ValueError):
                body_log.write(body)
        else:
            is_xml = any("xml" in ct or "html" in ct for ct in content_types)
            if is_xml:
                from rich.syntax import Syntax

                syntax = Syntax(body, "xml", theme="monokai", word_wrap=True)
                body_log.write(syntax)
            else:
                body_log.write(body)

    def _update_headers(self, result: ExecutionResult) -> None:
        """Populate the response headers DataTable."""
        table = self.query_one("#response-headers-table", DataTable)
        table.clear()

        for header_name, values in result.response_headers.items():
            for val in values:
                table.add_row(header_name, val)


def _looks_like_json(text: str) -> bool:
    """Quick heuristic: does the text look like JSON?"""
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )
