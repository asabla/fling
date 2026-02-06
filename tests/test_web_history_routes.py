"""Tests for execution history web routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from fling.core.environment import PUBLIC_ENV_FILENAME
from fling.core.models import (
    ExecutionRecord,
    ExecutionResult,
    HttpRequestDefinition,
    SourceLocation,
)
from fling.web.app import create_app
from fling.web.history import init_db, save_record

if TYPE_CHECKING:
    from pathlib import Path

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


def _create_app_with_history(tmp_path: Path) -> object:
    """Create a test app with a writable project directory and history DB."""
    # Write a minimal .http file so the app has a valid directory to scan
    http_file = tmp_path / "test.http"
    http_file.write_text("GET https://example.com\n", encoding="utf-8")

    # Write a minimal env file
    env_path = tmp_path / PUBLIC_ENV_FILENAME
    env_path.write_text(json.dumps({"_shared": {}}), encoding="utf-8")

    return create_app(directory=str(tmp_path), watch=False)


def _seed_records(tmp_path: Path, count: int = 5) -> list[str]:
    """Seed the history database with test records. Returns record IDs."""
    conn = init_db(tmp_path)
    ids = []
    try:
        for i in range(count):
            ts = datetime(2025, 6, 1, 10, 0, i, tzinfo=UTC)
            r = _make_record(
                record_id=f"test-{i}",
                env_name="dev",
                file_key="test.http",
                request_index=i,
                request_name=f"request_{i}",
                url=f"https://example.com/api/{i}",
                status_code=200,
                elapsed_ms=float(10 + i * 5),
                timestamp=ts,
            )
            save_record(conn, r)
            ids.append(r.id)
    finally:
        conn.close()
    return ids


# ---------------------------------------------------------------------------
# GET /history — list
# ---------------------------------------------------------------------------


class TestHistoryList:
    """Tests for GET /history."""

    async def test_list_returns_200(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert resp.status_code == 200

    async def test_list_empty_shows_message(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert "No execution history yet" in resp.text

    async def test_list_shows_records(self, tmp_path: Path) -> None:
        _seed_records(tmp_path, count=3)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert resp.status_code == 200
        assert "request_0" in resp.text
        assert "request_1" in resp.text
        assert "request_2" in resp.text

    async def test_list_shows_status_codes(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(conn, _make_record(record_id="ok", status_code=200))
            save_record(conn, _make_record(record_id="err", status_code=500))
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert "200" in resp.text
        assert "500" in resp.text

    async def test_list_filter_by_file_key(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(conn, _make_record(record_id="a", file_key="api.http", request_name="api_req"))
            save_record(conn, _make_record(record_id="b", file_key="other.http", request_name="other_req"))
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history", params={"file_key": "api.http"})
        assert resp.status_code == 200
        assert "api_req" in resp.text
        assert "other_req" not in resp.text

    async def test_list_pagination(self, tmp_path: Path) -> None:
        _seed_records(tmp_path, count=10)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history", params={"per_page": 3, "page": 1})
        assert resp.status_code == 200
        # Should show pagination controls
        assert "Next" in resp.text

    async def test_list_no_history_conn(self) -> None:
        """Without a directory, history is not available."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert resp.status_code == 400

    async def test_list_shows_total_count(self, tmp_path: Path) -> None:
        _seed_records(tmp_path, count=7)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history")
        assert "(7)" in resp.text


# ---------------------------------------------------------------------------
# GET /history/{record_id} — detail
# ---------------------------------------------------------------------------


class TestHistoryDetail:
    """Tests for GET /history/{record_id}."""

    async def test_detail_returns_200(self, tmp_path: Path) -> None:
        ids = _seed_records(tmp_path, count=1)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/history/{ids[0]}")
        assert resp.status_code == 200

    async def test_detail_shows_request_info(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(
                conn,
                _make_record(
                    record_id="detail-test",
                    env_name="staging",
                    file_key="users.http",
                    request_name="getUser",
                    url="https://api.example.com/users/1",
                    status_code=200,
                    elapsed_ms=55.5,
                ),
            )
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history/detail-test")
        assert resp.status_code == 200
        assert "https://api.example.com/users/1" in resp.text
        assert "getUser" in resp.text
        assert "staging" in resp.text
        assert "users.http" in resp.text

    async def test_detail_shows_status_code(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(conn, _make_record(record_id="sc-test", status_code=201))
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history/sc-test")
        assert "201" in resp.text

    async def test_detail_shows_error(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(conn, _make_record(record_id="err-test", error="Connection refused", status_code=0))
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history/err-test")
        assert "Connection refused" in resp.text

    async def test_detail_not_found(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/history/nonexistent")
        assert resp.status_code == 404

    async def test_detail_has_back_link(self, tmp_path: Path) -> None:
        ids = _seed_records(tmp_path, count=1)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/history/{ids[0]}")
        assert "Back to list" in resp.text


# ---------------------------------------------------------------------------
# DELETE /history/{record_id}
# ---------------------------------------------------------------------------


class TestHistoryDelete:
    """Tests for DELETE /history/{record_id}."""

    async def test_delete_returns_200(self, tmp_path: Path) -> None:
        ids = _seed_records(tmp_path, count=3)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/history/{ids[0]}")
        assert resp.status_code == 200

    async def test_delete_removes_record(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path)
        try:
            save_record(conn, _make_record(record_id="del-me", request_name="toDelete"))
            save_record(conn, _make_record(record_id="keep-me", request_name="toKeep"))
        finally:
            conn.close()
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/history/del-me")
        assert resp.status_code == 200
        # The returned list should not contain the deleted record
        assert "toDelete" not in resp.text
        assert "toKeep" in resp.text

    async def test_delete_not_found(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/history/ghost")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Index page — History button
# ---------------------------------------------------------------------------


class TestHistoryButton:
    """Tests for the History button in the index page."""

    async def test_index_has_history_button(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        assert "history-btn" in resp.text
        assert "history-modal" in resp.text
