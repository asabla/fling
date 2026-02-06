"""Response comparison and diff utilities.

Provides functions for computing text diffs and structured JSON diffs
between two execution results.  Uses the stdlib :mod:`difflib` module
for line-by-line comparison and a custom JSON walker for structural diffs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DiffKind(StrEnum):
    """Classification of a diff line."""

    EQUAL = "equal"
    ADD = "add"
    REMOVE = "remove"
    CHANGE = "change"


@dataclass(frozen=True)
class DiffLine:
    """A single line in a unified-style diff."""

    kind: DiffKind
    left_lineno: int | None = None
    right_lineno: int | None = None
    left_text: str = ""
    right_text: str = ""


@dataclass
class DiffResult:
    """The result of comparing two text blobs."""

    lines: list[DiffLine] = field(default_factory=list)
    left_total: int = 0
    right_total: int = 0
    changes: int = 0

    @property
    def identical(self) -> bool:
        """True if there are no changes."""
        return self.changes == 0


@dataclass(frozen=True)
class JsonDiffEntry:
    """A single difference found when comparing two JSON values."""

    path: str
    kind: DiffKind
    left_value: Any = None
    right_value: Any = None


@dataclass
class JsonDiffResult:
    """The result of a structural JSON comparison."""

    entries: list[JsonDiffEntry] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """True if the two JSON values are structurally identical."""
        return len(self.entries) == 0


# ---------------------------------------------------------------------------
# Text diff
# ---------------------------------------------------------------------------


def text_diff(left: str, right: str) -> DiffResult:
    """Compute a line-by-line diff between two text strings.

    Uses :func:`difflib.SequenceMatcher` for efficient alignment.

    Args:
        left: The "before" text.
        right: The "after" text.

    Returns:
        A :class:`DiffResult` with per-line annotations.
    """
    import difflib

    left_lines = left.splitlines(keepends=True)
    right_lines = right.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
    result = DiffResult(left_total=len(left_lines), right_total=len(right_lines))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for li, ri in zip(range(i1, i2), range(j1, j2), strict=True):
                result.lines.append(
                    DiffLine(
                        kind=DiffKind.EQUAL,
                        left_lineno=li + 1,
                        right_lineno=ri + 1,
                        left_text=left_lines[li].rstrip("\n\r"),
                        right_text=right_lines[ri].rstrip("\n\r"),
                    )
                )
        elif tag == "replace":
            result.changes += max(i2 - i1, j2 - j1)
            max_len = max(i2 - i1, j2 - j1)
            for k in range(max_len):
                left_idx: int | None = i1 + k if i1 + k < i2 else None
                right_idx: int | None = j1 + k if j1 + k < j2 else None
                result.lines.append(
                    DiffLine(
                        kind=DiffKind.CHANGE,
                        left_lineno=(left_idx + 1) if left_idx is not None else None,
                        right_lineno=(right_idx + 1) if right_idx is not None else None,
                        left_text=left_lines[left_idx].rstrip("\n\r") if left_idx is not None else "",
                        right_text=right_lines[right_idx].rstrip("\n\r") if right_idx is not None else "",
                    )
                )
        elif tag == "delete":
            result.changes += i2 - i1
            for li in range(i1, i2):
                result.lines.append(
                    DiffLine(
                        kind=DiffKind.REMOVE,
                        left_lineno=li + 1,
                        left_text=left_lines[li].rstrip("\n\r"),
                    )
                )
        elif tag == "insert":
            result.changes += j2 - j1
            for ri in range(j1, j2):
                result.lines.append(
                    DiffLine(
                        kind=DiffKind.ADD,
                        right_lineno=ri + 1,
                        right_text=right_lines[ri].rstrip("\n\r"),
                    )
                )

    return result


# ---------------------------------------------------------------------------
# JSON structural diff
# ---------------------------------------------------------------------------


def json_diff(left: str, right: str) -> JsonDiffResult:
    """Compute a structural diff between two JSON strings.

    Walks both JSON values recursively and reports added, removed, and
    changed paths.

    Args:
        left: The "before" JSON string.
        right: The "after" JSON string.

    Returns:
        A :class:`JsonDiffResult` listing all structural differences.

    Raises:
        ValueError: If either string is not valid JSON.
    """
    try:
        left_val = json.loads(left)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Left value is not valid JSON: {exc}") from exc

    try:
        right_val = json.loads(right)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Right value is not valid JSON: {exc}") from exc

    result = JsonDiffResult()
    _walk_json("$", left_val, right_val, result)
    return result


def _walk_json(path: str, left: Any, right: Any, result: JsonDiffResult) -> None:
    """Recursively compare two JSON values and populate *result*."""
    if type(left) is not type(right):
        result.entries.append(JsonDiffEntry(path=path, kind=DiffKind.CHANGE, left_value=left, right_value=right))
        return

    if isinstance(left, dict):
        all_keys = sorted(set(left.keys()) | set(right.keys()))
        for key in all_keys:
            child_path = f"{path}.{key}"
            if key not in left:
                result.entries.append(JsonDiffEntry(path=child_path, kind=DiffKind.ADD, right_value=right[key]))
            elif key not in right:
                result.entries.append(JsonDiffEntry(path=child_path, kind=DiffKind.REMOVE, left_value=left[key]))
            else:
                _walk_json(child_path, left[key], right[key], result)

    elif isinstance(left, list):
        max_len = max(len(left), len(right))
        for i in range(max_len):
            child_path = f"{path}[{i}]"
            if i >= len(left):
                result.entries.append(JsonDiffEntry(path=child_path, kind=DiffKind.ADD, right_value=right[i]))
            elif i >= len(right):
                result.entries.append(JsonDiffEntry(path=child_path, kind=DiffKind.REMOVE, left_value=left[i]))
            else:
                _walk_json(child_path, left[i], right[i], result)

    elif left != right:
        result.entries.append(JsonDiffEntry(path=path, kind=DiffKind.CHANGE, left_value=left, right_value=right))
