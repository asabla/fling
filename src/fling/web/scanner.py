"""Directory scanner for .http files.

Recursively discovers .http files within a directory tree and returns
them as a sorted mapping of relative paths to parsed HttpFile objects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fling.core.models import HttpFile

logger = logging.getLogger(__name__)


def scan_directory(directory: str | Path) -> dict[str, HttpFile]:
    """Recursively scan a directory for .http files and parse them.

    Args:
        directory: Root directory to scan.

    Returns:
        Dict mapping relative paths (e.g. ``"api/users.http"``) to parsed
        :class:`HttpFile` objects.  Files that fail to parse are logged and
        skipped.
    """
    from fling.core.parser import parse_http_file

    root = Path(directory).resolve()
    if not root.is_dir():
        logger.warning("Not a directory: %s", root)
        return {}

    files: dict[str, HttpFile] = {}

    for path in sorted(root.rglob("*.http")):
        rel = str(path.relative_to(root))
        try:
            result = parse_http_file(str(path))
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Failed to read %s: %s", rel, exc)
            continue

        if result.has_errors:
            logger.warning("Parse errors in %s, skipping", rel)
            continue

        if result.http_file:
            files[rel] = result.http_file

    return files


def scan_single_file(file_path: str | Path) -> dict[str, HttpFile]:
    """Parse a single .http file and return it as a one-element mapping.

    The key is the filename (basename only), matching the convention used
    when scanning directories.

    Args:
        file_path: Path to the .http file.

    Returns:
        Dict with a single entry, or empty dict if parsing fails.
    """
    from fling.core.parser import parse_http_file

    path = Path(file_path).resolve()
    try:
        result = parse_http_file(str(path))
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}

    if result.has_errors or not result.http_file:
        return {}

    return {path.name: result.http_file}
