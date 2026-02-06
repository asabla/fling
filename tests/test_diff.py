"""Tests for the response comparison diff engine."""

from __future__ import annotations

import pytest

from fling.web.diff import (
    DiffKind,
    DiffResult,
    JsonDiffResult,
    json_diff,
    text_diff,
)

# ---------------------------------------------------------------------------
# text_diff
# ---------------------------------------------------------------------------


class TestTextDiff:
    """Tests for the text_diff() function."""

    def test_identical_strings(self) -> None:
        result = text_diff("hello\n", "hello\n")
        assert result.identical
        assert result.changes == 0
        assert len(result.lines) == 1
        assert result.lines[0].kind == DiffKind.EQUAL
        assert result.lines[0].left_text == "hello"
        assert result.lines[0].right_text == "hello"

    def test_both_empty(self) -> None:
        result = text_diff("", "")
        assert result.identical
        assert result.changes == 0
        assert result.lines == []
        assert result.left_total == 0
        assert result.right_total == 0

    def test_single_line_change(self) -> None:
        result = text_diff("old\n", "new\n")
        assert not result.identical
        assert result.changes == 1
        assert len(result.lines) == 1
        assert result.lines[0].kind == DiffKind.CHANGE
        assert result.lines[0].left_text == "old"
        assert result.lines[0].right_text == "new"

    def test_multi_line_change(self) -> None:
        result = text_diff("a\nb\n", "a\nc\n")
        assert not result.identical
        assert result.changes == 1
        # First line equal, second changed
        assert result.lines[0].kind == DiffKind.EQUAL
        assert result.lines[0].left_text == "a"
        assert result.lines[1].kind == DiffKind.CHANGE
        assert result.lines[1].left_text == "b"
        assert result.lines[1].right_text == "c"

    def test_line_added(self) -> None:
        result = text_diff("a\n", "a\nb\n")
        assert not result.identical
        assert result.changes >= 1
        # There should be an ADD line for "b"
        add_lines = [dl for dl in result.lines if dl.kind == DiffKind.ADD]
        assert len(add_lines) >= 1
        assert any(dl.right_text == "b" for dl in add_lines)

    def test_line_removed(self) -> None:
        result = text_diff("a\nb\n", "a\n")
        assert not result.identical
        assert result.changes >= 1
        remove_lines = [dl for dl in result.lines if dl.kind == DiffKind.REMOVE]
        assert len(remove_lines) >= 1
        assert any(dl.left_text == "b" for dl in remove_lines)

    def test_add_to_empty(self) -> None:
        result = text_diff("", "hello\n")
        assert not result.identical
        assert result.changes == 1
        assert result.left_total == 0
        assert result.right_total == 1

    def test_remove_all(self) -> None:
        result = text_diff("hello\nworld\n", "")
        assert not result.identical
        assert result.changes == 2
        assert result.left_total == 2
        assert result.right_total == 0

    def test_line_numbers_sequential(self) -> None:
        result = text_diff("a\nb\nc\n", "a\nb\nc\n")
        assert result.identical
        for i, line in enumerate(result.lines):
            assert line.left_lineno == i + 1
            assert line.right_lineno == i + 1

    def test_mixed_operations(self) -> None:
        left = "line1\nline2\nline3\nline4\n"
        right = "line1\nmodified\nline3\nline4\nextra\n"
        result = text_diff(left, right)
        assert not result.identical
        # Should have some equal, some changed/added lines
        kinds = {dl.kind for dl in result.lines}
        assert DiffKind.EQUAL in kinds

    def test_strips_trailing_newlines(self) -> None:
        """Line text should have trailing newlines stripped."""
        result = text_diff("hello\n", "hello\n")
        assert result.lines[0].left_text == "hello"
        assert result.lines[0].right_text == "hello"

    def test_left_total_right_total(self) -> None:
        result = text_diff("a\nb\nc\n", "x\ny\n")
        assert result.left_total == 3
        assert result.right_total == 2


# ---------------------------------------------------------------------------
# DiffResult
# ---------------------------------------------------------------------------


class TestDiffResult:
    """Tests for DiffResult properties."""

    def test_identical_property_true(self) -> None:
        r = DiffResult(changes=0)
        assert r.identical is True

    def test_identical_property_false(self) -> None:
        r = DiffResult(changes=5)
        assert r.identical is False


# ---------------------------------------------------------------------------
# json_diff
# ---------------------------------------------------------------------------


class TestJsonDiff:
    """Tests for the json_diff() function."""

    def test_identical_objects(self) -> None:
        result = json_diff('{"a": 1}', '{"a": 1}')
        assert result.identical
        assert result.entries == []

    def test_identical_arrays(self) -> None:
        result = json_diff("[1, 2, 3]", "[1, 2, 3]")
        assert result.identical

    def test_identical_scalars(self) -> None:
        result = json_diff("42", "42")
        assert result.identical

    def test_key_added(self) -> None:
        result = json_diff('{"a": 1}', '{"a": 1, "b": 2}')
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$.b"
        assert entry.kind == DiffKind.ADD
        assert entry.right_value == 2

    def test_key_removed(self) -> None:
        result = json_diff('{"a": 1, "b": 2}', '{"a": 1}')
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$.b"
        assert entry.kind == DiffKind.REMOVE
        assert entry.left_value == 2

    def test_value_changed(self) -> None:
        result = json_diff('{"a": 1}', '{"a": 2}')
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$.a"
        assert entry.kind == DiffKind.CHANGE
        assert entry.left_value == 1
        assert entry.right_value == 2

    def test_nested_change(self) -> None:
        result = json_diff('{"a": {"b": 1}}', '{"a": {"b": 2}}')
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$.a.b"
        assert entry.kind == DiffKind.CHANGE
        assert entry.left_value == 1
        assert entry.right_value == 2

    def test_array_element_added(self) -> None:
        result = json_diff("[1, 2]", "[1, 2, 3]")
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$[2]"
        assert entry.kind == DiffKind.ADD
        assert entry.right_value == 3

    def test_array_element_removed(self) -> None:
        result = json_diff("[1, 2, 3]", "[1, 2]")
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$[2]"
        assert entry.kind == DiffKind.REMOVE
        assert entry.left_value == 3

    def test_array_element_changed(self) -> None:
        result = json_diff("[1, 2, 3]", "[1, 99, 3]")
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$[1]"
        assert entry.kind == DiffKind.CHANGE
        assert entry.left_value == 2
        assert entry.right_value == 99

    def test_type_mismatch_at_root(self) -> None:
        result = json_diff('{"a": 1}', "[1]")
        assert not result.identical
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.path == "$"
        assert entry.kind == DiffKind.CHANGE

    def test_type_mismatch_nested(self) -> None:
        result = json_diff('{"a": [1]}', '{"a": "string"}')
        assert not result.identical
        entry = result.entries[0]
        assert entry.path == "$.a"
        assert entry.kind == DiffKind.CHANGE

    def test_invalid_left_json(self) -> None:
        with pytest.raises(ValueError, match="Left value is not valid JSON"):
            json_diff("not json", "{}")

    def test_invalid_right_json(self) -> None:
        with pytest.raises(ValueError, match="Right value is not valid JSON"):
            json_diff("{}", "not json")

    def test_both_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="Left value is not valid JSON"):
            json_diff("nope", "nah")

    def test_deeply_nested_change(self) -> None:
        left = '{"a": {"b": {"c": {"d": 1}}}}'
        right = '{"a": {"b": {"c": {"d": 2}}}}'
        result = json_diff(left, right)
        assert len(result.entries) == 1
        assert result.entries[0].path == "$.a.b.c.d"

    def test_multiple_changes(self) -> None:
        left = '{"a": 1, "b": 2, "c": 3}'
        right = '{"a": 1, "b": 99, "c": 3, "d": 4}'
        result = json_diff(left, right)
        assert not result.identical
        paths = {e.path for e in result.entries}
        assert "$.b" in paths  # changed
        assert "$.d" in paths  # added
        assert len(result.entries) == 2

    def test_empty_objects(self) -> None:
        result = json_diff("{}", "{}")
        assert result.identical

    def test_empty_arrays(self) -> None:
        result = json_diff("[]", "[]")
        assert result.identical

    def test_null_values(self) -> None:
        result = json_diff('{"a": null}', '{"a": null}')
        assert result.identical

    def test_null_to_value(self) -> None:
        result = json_diff('{"a": null}', '{"a": 1}')
        assert not result.identical
        # null (NoneType) vs int → type mismatch → CHANGE
        assert result.entries[0].kind == DiffKind.CHANGE

    def test_boolean_values(self) -> None:
        result = json_diff('{"flag": true}', '{"flag": false}')
        assert not result.identical
        assert result.entries[0].kind == DiffKind.CHANGE
        assert result.entries[0].left_value is True
        assert result.entries[0].right_value is False

    def test_keys_sorted_deterministically(self) -> None:
        """Entries should appear in sorted key order."""
        left = '{"c": 1, "a": 1, "b": 1}'
        right = '{"c": 2, "a": 2, "b": 2}'
        result = json_diff(left, right)
        paths = [e.path for e in result.entries]
        assert paths == ["$.a", "$.b", "$.c"]


# ---------------------------------------------------------------------------
# JsonDiffResult
# ---------------------------------------------------------------------------


class TestJsonDiffResult:
    """Tests for JsonDiffResult properties."""

    def test_identical_property_true(self) -> None:
        r = JsonDiffResult()
        assert r.identical is True

    def test_identical_property_false(self) -> None:
        r = JsonDiffResult()
        from fling.web.diff import JsonDiffEntry

        r.entries.append(JsonDiffEntry(path="$.x", kind=DiffKind.ADD, right_value=1))
        assert r.identical is False
