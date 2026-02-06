"""Execution history storage backed by SQLite.

Provides functions for persisting and querying :class:`ExecutionRecord`
instances in a lightweight SQLite database.  The database is stored in a
``.fling/`` directory next to the project files.

All public functions are **synchronous** since SQLite operations are fast
enough for the expected workload (< 1 ms per operation) and the stdlib
``sqlite3`` module does not support async.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fling.core.models import ExecutionRecord

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS records (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    env_name    TEXT,
    file_key    TEXT,
    request_index INTEGER NOT NULL DEFAULT 0,
    request_name TEXT,
    status_code INTEGER NOT NULL DEFAULT 0,
    elapsed_ms  REAL NOT NULL DEFAULT 0,
    error       TEXT,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_records_file_key ON records (file_key);
"""

DEFAULT_MAX_RECORDS = 1000


def _db_path(directory: str | Path) -> Path:
    """Return the path to the history database file."""
    return Path(directory) / ".fling" / "history.db"


def init_db(directory: str | Path) -> sqlite3.Connection:
    """Initialise (or open) the history database.

    Creates the ``.fling/`` directory and ``history.db`` file if they do
    not exist.  The schema is applied idempotently using
    ``CREATE TABLE IF NOT EXISTS``.

    Args:
        directory: Project root directory.

    Returns:
        An open :class:`sqlite3.Connection`.
    """
    db_file = _db_path(directory)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_SCHEMA)
    logger.debug("History database initialised at %s", db_file)
    return conn


def save_record(conn: sqlite3.Connection, record: ExecutionRecord) -> None:
    """Persist a single execution record.

    Args:
        conn: Open database connection.
        record: The record to save.
    """
    data = record.model_dump_json()
    conn.execute(
        """\
        INSERT OR REPLACE INTO records
            (id, timestamp, env_name, file_key, request_index,
             request_name, status_code, elapsed_ms, error, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.id,
            record.timestamp.isoformat(),
            record.env_name,
            record.file_key,
            record.request_index,
            record.request_name,
            record.result.status_code,
            record.result.elapsed_ms,
            record.result.error,
            data,
        ),
    )
    conn.commit()


def list_records(
    conn: sqlite3.Connection,
    *,
    file_key: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ExecutionRecord]:
    """List execution records, newest first.

    Args:
        conn: Open database connection.
        file_key: If given, only return records for this file.
        limit: Maximum number of records to return.
        offset: Number of records to skip (for pagination).

    Returns:
        List of :class:`ExecutionRecord` instances.
    """
    if file_key is not None:
        rows = conn.execute(
            "SELECT data FROM records WHERE file_key = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (file_key, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT data FROM records ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    return [ExecutionRecord.model_validate_json(row[0]) for row in rows]


def get_record(conn: sqlite3.Connection, record_id: str) -> ExecutionRecord | None:
    """Retrieve a single record by ID.

    Args:
        conn: Open database connection.
        record_id: The unique record identifier.

    Returns:
        The record, or ``None`` if not found.
    """
    row = conn.execute("SELECT data FROM records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        return None
    return ExecutionRecord.model_validate_json(row[0])


def delete_record(conn: sqlite3.Connection, record_id: str) -> bool:
    """Delete a single record.

    Args:
        conn: Open database connection.
        record_id: The unique record identifier.

    Returns:
        ``True`` if a record was deleted, ``False`` if not found.
    """
    cursor = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    return cursor.rowcount > 0


def count_records(conn: sqlite3.Connection) -> int:
    """Return the total number of records in the database."""
    row = conn.execute("SELECT COUNT(*) FROM records").fetchone()
    return row[0] if row else 0


def prune_old(
    conn: sqlite3.Connection,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> int:
    """Delete the oldest records beyond *max_records*.

    Args:
        conn: Open database connection.
        max_records: Maximum number of records to keep.

    Returns:
        Number of records deleted.
    """
    total = count_records(conn)
    if total <= max_records:
        return 0

    excess = total - max_records
    cursor = conn.execute(
        """\
        DELETE FROM records WHERE id IN (
            SELECT id FROM records ORDER BY timestamp ASC LIMIT ?
        )
        """,
        (excess,),
    )
    conn.commit()
    deleted = cursor.rowcount
    logger.info("Pruned %d old history records (kept %d)", deleted, max_records)
    return deleted
