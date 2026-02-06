"""Collection tree widget for the fling TUI.

Displays the requests from an .http file in a tree structure,
allowing the user to select individual requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message
from textual.widgets import Tree

if TYPE_CHECKING:
    from textual.widgets.tree import TreeNode

    from fling.core.models import HttpFile, HttpRequestDefinition


# Method → color mapping for Rich Text styling
_METHOD_COLORS: dict[str, str] = {
    "GET": "green",
    "POST": "yellow",
    "PUT": "blue",
    "PATCH": "cyan",
    "DELETE": "red",
    "HEAD": "magenta",
    "OPTIONS": "dim",
}


class CollectionTree(Tree[object]):
    """A tree widget that displays requests from an .http file.

    Each request is shown as a leaf node with its HTTP method and name.
    Selecting a node emits a `RequestSelected` message.
    """

    class RequestSelected(Message):
        """Posted when a request is selected in the tree."""

        def __init__(self, request: HttpRequestDefinition) -> None:
            super().__init__()
            self.request = request

    def __init__(
        self,
        http_file: HttpFile | None = None,
        *,
        id: str | None = None,
    ) -> None:
        label = http_file.file_path if http_file else "No file loaded"
        super().__init__(label, id=id)
        self._http_file = http_file
        self.show_root = True
        self.guide_depth = 3

    def on_mount(self) -> None:
        """Populate the tree when mounted."""
        if self._http_file:
            self._build_tree()
            self.root.expand()

    def _build_tree(self) -> None:
        """Build tree nodes from the HTTP file's requests."""
        if not self._http_file:
            return

        for request in self._http_file.requests:
            method = request.method.value
            name = request.metadata.name or request.url
            color = _METHOD_COLORS.get(method, "white")

            label = Text()
            label.append(f"{method:7s} ", style=f"bold {color}")
            label.append(name)

            if request.metadata.disabled:
                label.stylize("dim strike")

            node = self.root.add_leaf(label, data=request)
            # Store the request on the node for later retrieval
            node.data = request

    def load_file(self, http_file: HttpFile) -> None:
        """Load a new HTTP file into the tree, replacing existing content."""
        self._http_file = http_file
        self.clear()
        self.root.set_label(http_file.file_path)
        self._build_tree()
        self.root.expand()

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        """Handle node selection — emit RequestSelected for leaf nodes."""
        node: TreeNode[object] = event.node
        if node.data is not None and not node.allow_expand:
            # It's a leaf (request) node
            self.post_message(self.RequestSelected(node.data))  # type: ignore[arg-type]

    @property
    def request_count(self) -> int:
        """Return the number of requests in the tree."""
        if not self._http_file:
            return 0
        return len(self._http_file.requests)
