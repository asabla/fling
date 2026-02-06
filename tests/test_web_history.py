"""Tests for the execution history SQLite storage module."""

from __future__ import annotations

from datetime import UTC, datetime

from fling.core.models import (
    ExecutionRecord,
    ExecutionResult,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.web.history import (
    DEFAULT_MAX_RECORDS,
    count_records,
    delete_record,
    get_record,
    init_db,
    list_records,
    prune_old,
    save_record,
)

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_result(
    url: str = "https://example.com",
    status_code: int = 200,
    elapsed_ms: float = 42.0,
    error: str | None = None,
) -> ExecutionResult:
    """Create a minimal ExecutionResult for testing."""
    return ExecutionResult(
        request=HttpRequestDefinition(url=url, location=_LOC),
        resolved_url=url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        error=error,
    )


def _make_record(
    *,
    record_id: str | None = None,
    env_name: str | None = None,
    file_key: str | None = None,
    request_index: int = 0,
    request_name: str | None = None,
    url: str = "https://example.com",
    status_code: int = 200,
    elapsed_ms: float = 42.0,
    error: str | None = None,
    timestamp: datetime | None = None,
) -> ExecutionRecord:
    """Create an ExecutionRecord with optional overrides."""
    kwargs: dict[str, object] = {
        "env_name": env_name,
        "file_key": file_key,
        "request_index": request_index,
        "request_name": request_name,
        "result": _make_result(
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            error=error,
        ),
    }
    if record_id is not None:
        kwargs["id"] = record_id
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return ExecutionRecord(**kwargs)  # type: ignore[arg-type]


class TestInitDb:
    """Tests for init_db."""

    def test_creates_database_file(self, tmp_path: object) -> None:
        from pathlib import Path

        d = Path(str(tmp_path))
        conn = init_db(d)
        try:
            db_file = d / ".fling" / "history.db"
            assert db_file.exists()
        finally:
            conn.close()

    def test_creates_fling_directory(self, tmp_path: object) -> None:
        from pathlib import Path

        d = Path(str(tmp_path))
        conn = init_db(d)
        try:
            assert (d / ".fling").is_dir()
        finally:
            conn.close()

    def test_idempotent_on_repeated_calls(self, tmp_path: object) -> None:
        from pathlib import Path

        d = Path(str(tmp_path))
        conn1 = init_db(d)
        conn1.close()
        # Second call should not raise
        conn2 = init_db(d)
        conn2.close()

    def test_schema_has_records_table(self, tmp_path: object) -> None:
        from pathlib import Path

        d = Path(str(tmp_path))
        conn = init_db(d)
        try:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='records'").fetchall()
            assert len(rows) == 1
        finally:
            conn.close()


class TestSaveRecord:
    """Tests for save_record."""

    def test_save_and_retrieve(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            record = _make_record(env_name="dev", file_key="api/users.http")
            save_record(conn, record)

            got = get_record(conn, record.id)
            assert got is not None
            assert got.id == record.id
            assert got.env_name == "dev"
            assert got.file_key == "api/users.http"
            assert got.result.status_code == 200
        finally:
            conn.close()

    def test_save_replaces_existing(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            record = _make_record(record_id="abc123", status_code=200)
            save_record(conn, record)

            updated = _make_record(record_id="abc123", status_code=404)
            save_record(conn, updated)

            got = get_record(conn, "abc123")
            assert got is not None
            assert got.result.status_code == 404
            assert count_records(conn) == 1
        finally:
            conn.close()

    def test_save_record_with_error(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            record = _make_record(error="Connection refused", status_code=0)
            save_record(conn, record)

            got = get_record(conn, record.id)
            assert got is not None
            assert got.result.error == "Connection refused"
            assert got.result.status_code == 0
        finally:
            conn.close()

    def test_save_record_with_all_fields(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
            record = _make_record(
                record_id="full-record",
                env_name="production",
                file_key="orders/create.http",
                request_index=3,
                request_name="createOrder",
                url="https://api.example.com/orders",
                status_code=201,
                elapsed_ms=123.45,
                timestamp=ts,
            )
            save_record(conn, record)

            got = get_record(conn, "full-record")
            assert got is not None
            assert got.env_name == "production"
            assert got.file_key == "orders/create.http"
            assert got.request_index == 3
            assert got.request_name == "createOrder"
            assert got.result.resolved_url == "https://api.example.com/orders"
            assert got.result.status_code == 201
            assert got.result.elapsed_ms == 123.45
            assert got.timestamp == ts
        finally:
            conn.close()


class TestGetRecord:
    """Tests for get_record."""

    def test_returns_none_for_missing(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            assert get_record(conn, "nonexistent") is None
        finally:
            conn.close()

    def test_returns_correct_record(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            r1 = _make_record(record_id="aaa")
            r2 = _make_record(record_id="bbb")
            save_record(conn, r1)
            save_record(conn, r2)

            got = get_record(conn, "bbb")
            assert got is not None
            assert got.id == "bbb"
        finally:
            conn.close()


class TestListRecords:
    """Tests for list_records."""

    def test_empty_database(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            results = list_records(conn)
            assert results == []
        finally:
            conn.close()

    def test_returns_newest_first(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            ts1 = datetime(2025, 1, 1, tzinfo=UTC)
            ts2 = datetime(2025, 6, 1, tzinfo=UTC)
            ts3 = datetime(2025, 12, 1, tzinfo=UTC)

            r1 = _make_record(record_id="old", timestamp=ts1)
            r2 = _make_record(record_id="mid", timestamp=ts2)
            r3 = _make_record(record_id="new", timestamp=ts3)

            # Insert out of order
            save_record(conn, r2)
            save_record(conn, r1)
            save_record(conn, r3)

            results = list_records(conn)
            ids = [r.id for r in results]
            assert ids == ["new", "mid", "old"]
        finally:
            conn.close()

    def test_filter_by_file_key(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            r1 = _make_record(record_id="a", file_key="api/users.http")
            r2 = _make_record(record_id="b", file_key="api/orders.http")
            r3 = _make_record(record_id="c", file_key="api/users.http")

            save_record(conn, r1)
            save_record(conn, r2)
            save_record(conn, r3)

            results = list_records(conn, file_key="api/users.http")
            ids = {r.id for r in results}
            assert ids == {"a", "c"}
        finally:
            conn.close()

    def test_limit(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(10):
                ts = datetime(2025, 1, 1 + i, tzinfo=UTC)
                save_record(conn, _make_record(record_id=f"r{i}", timestamp=ts))

            results = list_records(conn, limit=3)
            assert len(results) == 3
        finally:
            conn.close()

    def test_offset(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(5):
                ts = datetime(2025, 1, 1 + i, tzinfo=UTC)
                save_record(conn, _make_record(record_id=f"r{i}", timestamp=ts))

            results = list_records(conn, offset=2, limit=10)
            assert len(results) == 3
            # Newest first: r4, r3, r2, r1, r0 -> skip 2 -> r2, r1, r0
            ids = [r.id for r in results]
            assert ids == ["r2", "r1", "r0"]
        finally:
            conn.close()

    def test_limit_and_offset_combined(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(10):
                ts = datetime(2025, 1, 1 + i, tzinfo=UTC)
                save_record(conn, _make_record(record_id=f"r{i}", timestamp=ts))

            results = list_records(conn, limit=2, offset=3)
            assert len(results) == 2
            # Newest first: r9,r8,r7,r6,r5,r4,r3,r2,r1,r0 -> skip 3 -> r6,r5
            ids = [r.id for r in results]
            assert ids == ["r6", "r5"]
        finally:
            conn.close()


class TestDeleteRecord:
    """Tests for delete_record."""

    def test_delete_existing(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            record = _make_record(record_id="del-me")
            save_record(conn, record)
            assert count_records(conn) == 1

            assert delete_record(conn, "del-me") is True
            assert count_records(conn) == 0
            assert get_record(conn, "del-me") is None
        finally:
            conn.close()

    def test_delete_nonexistent(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            assert delete_record(conn, "ghost") is False
        finally:
            conn.close()

    def test_delete_only_target(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            save_record(conn, _make_record(record_id="keep"))
            save_record(conn, _make_record(record_id="remove"))

            delete_record(conn, "remove")
            assert count_records(conn) == 1
            assert get_record(conn, "keep") is not None
        finally:
            conn.close()


class TestCountRecords:
    """Tests for count_records."""

    def test_empty(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            assert count_records(conn) == 0
        finally:
            conn.close()

    def test_after_inserts(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(5):
                save_record(conn, _make_record(record_id=f"r{i}"))
            assert count_records(conn) == 5
        finally:
            conn.close()


class TestPruneOld:
    """Tests for prune_old."""

    def test_no_pruning_when_under_limit(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            save_record(conn, _make_record(record_id="r1"))
            assert prune_old(conn, max_records=10) == 0
            assert count_records(conn) == 1
        finally:
            conn.close()

    def test_no_pruning_at_exact_limit(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(5):
                save_record(conn, _make_record(record_id=f"r{i}"))
            assert prune_old(conn, max_records=5) == 0
            assert count_records(conn) == 5
        finally:
            conn.close()

    def test_prunes_oldest_records(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(10):
                ts = datetime(2025, 1, 1 + i, tzinfo=UTC)
                save_record(conn, _make_record(record_id=f"r{i}", timestamp=ts))

            deleted = prune_old(conn, max_records=3)
            assert deleted == 7
            assert count_records(conn) == 3

            # Should keep the 3 newest: r9, r8, r7
            results = list_records(conn)
            ids = {r.id for r in results}
            assert ids == {"r7", "r8", "r9"}
        finally:
            conn.close()

    def test_prune_returns_correct_deleted_count(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(20):
                ts = datetime(2025, 1, 1, i, tzinfo=UTC)
                save_record(conn, _make_record(record_id=f"r{i}", timestamp=ts))

            deleted = prune_old(conn, max_records=15)
            assert deleted == 5
            assert count_records(conn) == 15
        finally:
            conn.close()

    def test_default_max_records(self) -> None:
        """The default max is 1000."""
        assert DEFAULT_MAX_RECORDS == 1000


class TestRoundTrip:
    """Integration tests for full save/retrieve cycles."""

    def test_full_serialization_roundtrip(self, tmp_path: object) -> None:
        """ExecutionRecord survives JSON serialization through SQLite."""
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
            original = _make_record(
                record_id="roundtrip",
                env_name="staging",
                file_key="test/api.http",
                request_index=2,
                request_name="getUser",
                url="https://api.test.com/users/1",
                status_code=200,
                elapsed_ms=55.5,
                timestamp=ts,
            )
            save_record(conn, original)

            restored = get_record(conn, "roundtrip")
            assert restored is not None
            assert restored.id == original.id
            assert restored.timestamp == original.timestamp
            assert restored.env_name == original.env_name
            assert restored.file_key == original.file_key
            assert restored.request_index == original.request_index
            assert restored.request_name == original.request_name
            assert restored.result.resolved_url == original.result.resolved_url
            assert restored.result.status_code == original.result.status_code
            assert restored.result.elapsed_ms == original.result.elapsed_ms
            assert restored.result.error is None
        finally:
            conn.close()

    def test_list_after_delete(self, tmp_path: object) -> None:
        from pathlib import Path

        conn = init_db(Path(str(tmp_path)))
        try:
            for i in range(5):
                save_record(conn, _make_record(record_id=f"r{i}"))

            delete_record(conn, "r2")
            results = list_records(conn)
            ids = {r.id for r in results}
            assert "r2" not in ids
            assert len(results) == 4
        finally:
            conn.close()
