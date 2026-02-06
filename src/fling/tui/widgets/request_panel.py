"""Request panel widget for the fling TUI.

Displays details of the selected HTTP request in a tabbed layout:
- URL bar with method and URL
- Headers tab (DataTable)
- Body tab (TextArea, read-only, syntax-highlighted)
- Info tab (metadata: name, notes, flags)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Static, TabbedContent, TabPane, TextArea

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from fling.core.models import HttpRequestDefinition

# Method -> color for URL bar styling
_METHOD_COLORS: dict[str, str] = {
    "GET": "green",
    "POST": "yellow",
    "PUT": "blue",
    "PATCH": "cyan",
    "DELETE": "red",
    "HEAD": "magenta",
    "OPTIONS": "dim white",
}


class UrlBar(Static):
    """Displays the HTTP method and URL of the selected request."""

    DEFAULT_CSS = """
    UrlBar {
        height: 3;
        padding: 1 2 0 2;
        background: $surface;
    }
    """

    def set_request(self, request: HttpRequestDefinition) -> None:
        """Update the URL bar with the given request."""
        method = request.method.value
        color = _METHOD_COLORS.get(method, "white")
        url = request.url
        name = request.metadata.name
        name_part = f"  [dim]# {name}[/]" if name else ""
        self.update(f"[bold {color}]{method}[/] {url}{name_part}")

    def clear(self) -> None:
        """Clear the URL bar."""
        self.update("[dim]No request selected[/]")


class RequestPanel(Vertical):
    """Panel showing full details of the currently selected request.

    Contains a URL bar at the top and tabbed content below with
    Headers, Body, and Info tabs.
    """

    DEFAULT_CSS = """
    RequestPanel {
        height: 1fr;
        width: 1fr;
    }
    """

    _request: reactive[HttpRequestDefinition | None] = reactive(None)

    COMPONENT_CLASSES: ClassVar[set[str]] = {"request-panel--empty"}

    def compose(self) -> ComposeResult:
        yield UrlBar(id="url-bar")
        with TabbedContent(id="request-tabs"):
            with TabPane("Headers", id="tab-headers"):
                yield DataTable(id="headers-table")
            with TabPane("Body", id="tab-body"):
                yield TextArea(id="body-text", read_only=True)
            with TabPane("Info", id="tab-info"):
                yield Static(id="info-text")

    def on_mount(self) -> None:
        """Set up the data table columns."""
        table = self.query_one("#headers-table", DataTable)
        table.add_columns("Header", "Value")
        table.cursor_type = "row"
        table.zebra_stripes = True

        # Start empty
        self._show_empty()

    def update_request(self, request: HttpRequestDefinition) -> None:
        """Update all sub-widgets with the given request."""
        self._request = request

        # URL bar
        url_bar = self.query_one("#url-bar", UrlBar)
        url_bar.set_request(request)

        # Headers table
        self._update_headers(request)

        # Body text
        self._update_body(request)

        # Info tab
        self._update_info(request)

    def clear_request(self) -> None:
        """Reset to empty state."""
        self._request = None
        self._show_empty()

    def _show_empty(self) -> None:
        """Display the empty/placeholder state."""
        url_bar = self.query_one("#url-bar", UrlBar)
        url_bar.clear()

        table = self.query_one("#headers-table", DataTable)
        table.clear()

        body_area = self.query_one("#body-text", TextArea)
        body_area.load_text("")

        info = self.query_one("#info-text", Static)
        info.update("[dim]Select a request to view details[/]")

    def _update_headers(self, request: HttpRequestDefinition) -> None:
        """Populate the headers DataTable."""
        table = self.query_one("#headers-table", DataTable)
        table.clear()

        if request.headers:
            for header in request.headers:
                table.add_row(header.name, header.value)

    def _update_body(self, request: HttpRequestDefinition) -> None:
        """Populate the body TextArea."""
        body_area = self.query_one("#body-text", TextArea)

        if request.body and request.body.file_ref:
            body_area.load_text(f"< {request.body.file_ref}")
            body_area.language = None
        elif request.body and request.body.content:
            content = request.body.content
            # Detect language for syntax highlighting
            language = _detect_body_language(request)
            body_area.language = language
            body_area.load_text(content)
        else:
            body_area.load_text("")
            body_area.language = None

    def _update_info(self, request: HttpRequestDefinition) -> None:
        """Populate the info tab with metadata."""
        lines: list[str] = []
        meta = request.metadata

        if meta.name:
            lines.append(f"[bold]Name:[/] {meta.name}")
        if meta.note:
            lines.append(f"[bold]Note:[/] {meta.note}")
        if request.http_version:
            lines.append(f"[bold]HTTP Version:[/] {request.http_version}")

        # Flags
        flags: list[str] = []
        if meta.disabled:
            flags.append("disabled")
        if meta.no_redirect:
            flags.append("no-redirect")
        if meta.no_cookie_jar:
            flags.append("no-cookie-jar")
        if meta.timeout_ms is not None:
            flags.append(f"timeout: {meta.timeout_ms}ms")
        if flags:
            lines.append(f"[bold]Flags:[/] {', '.join(flags)}")

        # Refs
        if meta.refs:
            lines.append(f"[bold]Dependencies:[/] {', '.join(meta.refs)}")

        # Prompt variables
        if meta.prompt_vars:
            lines.append("[bold]Prompt Variables:[/]")
            for var_name, description in meta.prompt_vars.items():
                desc = description or "(no description)"
                lines.append(f"  {var_name}: {desc}")

        # Response handler
        if request.response_handler:
            if request.response_handler.inline_script:
                lines.append("[bold]Response Handler:[/] inline script")
            elif request.response_handler.file_ref:
                lines.append(f"[bold]Response Handler:[/] {request.response_handler.file_ref}")

        # Response save
        if request.response_save_path:
            lines.append(f"[bold]Save Response:[/] {request.response_save_path}")

        # Pre-request script
        if request.pre_request_script:
            lines.append("[bold]Pre-request Script:[/] yes")

        if not lines:
            lines.append("[dim]No additional metadata[/]")

        info = self.query_one("#info-text", Static)
        info.update("\n".join(lines))


def _detect_body_language(request: HttpRequestDefinition) -> str | None:
    """Detect the body language from Content-Type header for syntax highlighting."""
    content_type = ""
    for header in request.headers:
        if header.name.lower() == "content-type":
            content_type = header.value.lower()
            break

    if "json" in content_type:
        return "json"
    if "xml" in content_type or "html" in content_type:
        return "xml"
    if "yaml" in content_type or "yml" in content_type:
        return "yaml"

    # Fallback: try to detect from body content
    if request.body and request.body.content:
        body = request.body.content.strip()
        if (body.startswith("{") and body.endswith("}")) or (body.startswith("[") and body.endswith("]")):
            return "json"
        if body.startswith("<"):
            return "xml"

    if request.body and request.body.is_graphql:
        return None  # No built-in GraphQL language in TextArea

    return None
