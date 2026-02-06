"""Live file watcher for the fling web interface.

Monitors a directory for ``.http`` file changes and notifies connected
SSE clients so the UI can hot-reload the sidebar and request panels.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fling.core.models import HttpFile

logger = logging.getLogger(__name__)


class FileChangeEvent:
    """Describes a single file-system change to an ``.http`` file."""

    __slots__ = ("change_type", "file_key", "file_path")

    def __init__(self, change_type: str, file_key: str, file_path: str) -> None:
        self.change_type = change_type  # "added" | "modified" | "deleted"
        self.file_key = file_key
        self.file_path = file_path

    def __repr__(self) -> str:  # pragma: no cover
        return f"FileChangeEvent({self.change_type!r}, {self.file_key!r})"


class FileWatcher:
    """Watches a directory for ``.http`` file changes.

    On each change the watcher:

    1. Re-parses the affected file (or removes it from the file map on
       deletion).
    2. Pushes a :class:`FileChangeEvent` to all connected SSE subscribers.

    The watcher is started as an ``asyncio`` background task via
    :meth:`start` and cleanly cancelled via :meth:`stop`.
    """

    def __init__(self, directory: str | Path, files: dict[str, HttpFile]) -> None:
        self._directory = Path(directory).resolve()
        self._files = files
        self._subscribers: set[asyncio.Queue[FileChangeEvent | None]] = set()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[FileChangeEvent | None]:
        """Create a new subscriber queue.

        Returns an :class:`asyncio.Queue` that receives
        :class:`FileChangeEvent` objects whenever a file changes, or
        ``None`` when the watcher is shutting down.
        """
        queue: asyncio.Queue[FileChangeEvent | None] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[FileChangeEvent | None]) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(queue)

    def _broadcast(self, event: FileChangeEvent) -> None:
        """Push *event* to every subscriber queue."""
        for queue in self._subscribers:
            queue.put_nowait(event)

    # ------------------------------------------------------------------
    # File parsing helpers
    # ------------------------------------------------------------------

    def _relative_key(self, path: Path) -> str:
        """Compute the file key (relative path) for *path*."""
        return str(path.relative_to(self._directory))

    def _parse_file(self, abs_path: Path) -> HttpFile | None:
        """Parse a single ``.http`` file, returning ``None`` on failure."""
        from fling.core.parser import parse_http_file

        try:
            result = parse_http_file(str(abs_path))
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Watcher: failed to read %s: %s", abs_path, exc)
            return None

        if result.has_errors or not result.http_file:
            logger.warning("Watcher: parse errors in %s, skipping", abs_path)
            return None

        return result.http_file

    # ------------------------------------------------------------------
    # Core watch loop
    # ------------------------------------------------------------------

    async def _watch(self) -> None:
        """Run the ``watchfiles`` async watcher until cancelled."""
        from watchfiles import awatch

        logger.info("Watcher: monitoring %s for .http changes", self._directory)

        try:
            async for changes in awatch(
                self._directory,
                watch_filter=_http_file_filter,
                step=300,  # poll interval in ms
            ):
                await self._handle_changes(changes)
        except asyncio.CancelledError:
            logger.debug("Watcher: cancelled")

    async def _handle_changes(self, changes: set[tuple[Any, str]]) -> None:
        """Process a batch of file-system changes."""
        from watchfiles import Change

        for change_type, raw_path in changes:
            path = Path(raw_path).resolve()

            if not str(path).endswith(".http"):
                continue

            try:
                key = self._relative_key(path)
            except ValueError:
                # Path is outside our root — ignore
                continue

            if change_type == Change.deleted:
                removed = self._files.pop(key, None)
                if removed is not None:
                    logger.info("Watcher: deleted %s", key)
                    self._broadcast(FileChangeEvent("deleted", key, str(path)))

            elif change_type in (Change.added, Change.modified):
                http_file = self._parse_file(path)
                if http_file is not None:
                    existed = key in self._files
                    self._files[key] = http_file
                    event_type = "modified" if existed else "added"
                    logger.info("Watcher: %s %s", event_type, key)
                    self._broadcast(FileChangeEvent(event_type, key, str(path)))
                elif change_type == Change.added:
                    # New file that failed to parse — ignore silently
                    logger.debug("Watcher: new file %s failed to parse", key)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watcher task.

        Must be called from within a running event loop (e.g. in a
        FastAPI ``lifespan`` or ``on_event("startup")`` handler).
        """
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._watch(), name="fling-file-watcher")

    async def stop(self) -> None:
        """Cancel the background watcher and notify subscribers."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

        # Signal subscribers to close
        for queue in self._subscribers:
            queue.put_nowait(None)
        self._subscribers.clear()

    @property
    def running(self) -> bool:
        """Return ``True`` if the watcher task is active."""
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Bulk reload
    # ------------------------------------------------------------------

    def reload_all(self) -> list[FileChangeEvent]:
        """Re-scan the directory and update the file map.

        Returns a list of :class:`FileChangeEvent` objects describing
        what changed.  Useful for the ``/reload`` endpoint.
        """
        from fling.web.scanner import scan_directory

        new_files = scan_directory(str(self._directory))
        events: list[FileChangeEvent] = []

        old_keys = set(self._files.keys())
        new_keys = set(new_files.keys())

        # Deleted
        for key in old_keys - new_keys:
            del self._files[key]
            events.append(FileChangeEvent("deleted", key, ""))

        # Added
        for key in new_keys - old_keys:
            self._files[key] = new_files[key]
            events.append(FileChangeEvent("added", key, ""))

        # Modified (content may have changed)
        for key in old_keys & new_keys:
            self._files[key] = new_files[key]
            events.append(FileChangeEvent("modified", key, ""))

        for event in events:
            self._broadcast(event)

        return events


def _http_file_filter(change: Any, path: str) -> bool:
    """``watchfiles`` filter that only accepts ``.http`` files."""
    return path.endswith(".http")


async def watch_events(watcher: FileWatcher) -> AsyncGenerator[FileChangeEvent, None]:
    """Async generator that yields events from a watcher subscription.

    Yields :class:`FileChangeEvent` objects until the watcher stops
    (signalled by ``None`` on the queue).  Automatically unsubscribes
    on exit.
    """
    queue = watcher.subscribe()
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        watcher.unsubscribe(queue)
