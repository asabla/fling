"""Tests for the response comparison web routes."""

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
    response_body: str = "",
) -> ExecutionResult:
    """Create a minimal ExecutionResult for testing."""
    return ExecutionResult(
        request=HttpRequestDefinition(url=url, location=_LOC),
        resolved_url=url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        error=error,
        response_body=response_body,
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
    response_body: str = "",
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
            response_body=response_body,
        ),
    }
    if record_id is not None:
        kwargs["id"] = record_id
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return ExecutionRecord(**kwargs)  # type: ignore[arg-type]


def _create_app_with_history(tmp_path: Path) -> object:
    """Create a test app with a writable project directory and history DB."""
    http_file = tmp_path / "test.http"
    http_file.write_text("GET https://example.com\n", encoding="utf-8")

    env_path = tmp_path / PUBLIC_ENV_FILENAME
    env_path.write_text(json.dumps({"_shared": {}}), encoding="utf-8")

    return create_app(directory=str(tmp_path), watch=False)


def _seed_two_records(
    tmp_path: Path,
    *,
    left_body: str = '{"status": "ok"}',
    right_body: str = '{"status": "ok"}',
    left_id: str = "left-001",
    right_id: str = "right-002",
) -> tuple[str, str]:
    """Seed two history records and return their IDs."""
    conn = init_db(tmp_path)
    try:
        ts1 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        ts2 = datetime(2025, 6, 1, 10, 1, 0, tzinfo=UTC)
        save_record(
            conn,
            _make_record(
                record_id=left_id,
                env_name="dev",
                file_key="test.http",
                request_name="left_request",
                url="https://example.com/api/1",
                response_body=left_body,
                timestamp=ts1,
            ),
        )
        save_record(
            conn,
            _make_record(
                record_id=right_id,
                env_name="dev",
                file_key="test.http",
                request_name="right_request",
                url="https://example.com/api/2",
                response_body=right_body,
                timestamp=ts2,
            ),
        )
    finally:
        conn.close()
    return left_id, right_id


# ---------------------------------------------------------------------------
# GET /compare — basic behaviour
# ---------------------------------------------------------------------------


class TestCompareRoute:
    """Tests for GET /compare."""

    async def test_compare_returns_200(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200

    async def test_compare_shows_both_urls(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert "https://example.com/api/1" in resp.text
        assert "https://example.com/api/2" in resp.text

    async def test_compare_identical_bodies(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body='{"data": 1}',
            right_body='{"data": 1}',
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        assert "identical" in resp.text.lower()

    async def test_compare_different_bodies_shows_diff(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body='{"status": "ok"}',
            right_body='{"status": "error"}',
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        # Should not say identical
        assert "bodies are identical" not in resp.text.lower()
        # Should show changed line count
        assert "changed" in resp.text.lower()

    async def test_compare_shows_json_structural_diff(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body='{"a": 1, "b": 2}',
            right_body='{"a": 1, "b": 99, "c": 3}',
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        # Should show structural differences section
        assert "structural difference" in resp.text.lower()

    async def test_compare_non_json_bodies_no_json_section(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body="plain text left",
            right_body="plain text right",
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        # Should not show JSON structural diff section
        assert "structural difference" not in resp.text.lower()

    async def test_compare_shows_baseline_and_comparison_labels(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert "Baseline" in resp.text
        assert "Comparison" in resp.text

    async def test_compare_has_comparison_view_id(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert 'id="comparison-view"' in resp.text


# ---------------------------------------------------------------------------
# GET /compare — error cases
# ---------------------------------------------------------------------------


class TestCompareErrors:
    """Tests for compare route error handling."""

    async def test_left_record_not_found(self, tmp_path: Path) -> None:
        _, right_id = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": "nonexistent", "right": right_id})
        assert resp.status_code == 404

    async def test_right_record_not_found(self, tmp_path: Path) -> None:
        left_id, _ = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": "nonexistent"})
        assert resp.status_code == 404

    async def test_both_records_not_found(self, tmp_path: Path) -> None:
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": "nope", "right": "nah"})
        # Should 404 on the first missing record (left)
        assert resp.status_code == 404

    async def test_no_history_conn(self) -> None:
        """Without a directory, history is not available."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": "a", "right": "b"})
        assert resp.status_code == 400

    async def test_missing_query_params(self, tmp_path: Path) -> None:
        """Missing left/right params should return 422."""
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCompareEdgeCases:
    """Edge case tests for comparison."""

    async def test_compare_empty_bodies(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body="",
            right_body="",
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        assert "identical" in resp.text.lower()

    async def test_compare_one_empty_body(self, tmp_path: Path) -> None:
        left_id, right_id = _seed_two_records(
            tmp_path,
            left_body="some content\n",
            right_body="",
        )
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": right_id})
        assert resp.status_code == 200
        assert "changed" in resp.text.lower()

    async def test_compare_same_record_id(self, tmp_path: Path) -> None:
        """Comparing a record with itself should show identical."""
        left_id, _ = _seed_two_records(tmp_path)
        app = _create_app_with_history(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/compare", params={"left": left_id, "right": left_id})
        assert resp.status_code == 200
        assert "identical" in resp.text.lower()
