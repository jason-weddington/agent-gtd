"""Unit tests for the SQLite pool adapter."""

import os

from agent_gtd.sqlite_pool import SqlitePool, _pg_to_sqlite


def test_pg_to_sqlite_placeholder_conversion():
    assert (
        _pg_to_sqlite("SELECT * FROM t WHERE a = $1") == "SELECT * FROM t WHERE a = ?"
    )
    assert _pg_to_sqlite("$1, $2, $10") == "?, ?, ?"
    assert _pg_to_sqlite("no placeholders") == "no placeholders"


async def test_crud_roundtrip():
    pool = SqlitePool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, val TEXT)")
    await pool.execute("INSERT INTO t (id, val) VALUES ($1, $2)", "a", "hello")
    row = await pool.fetchrow("SELECT * FROM t WHERE id = $1", "a")
    assert row == {"id": "a", "val": "hello"}
    rows = await pool.fetch("SELECT * FROM t")
    assert len(rows) == 1
    await pool.close()
    assert pool._closed is True


async def test_fetchrow_returns_none():
    pool = SqlitePool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    result = await pool.fetchrow("SELECT * FROM t WHERE id = $1", "missing")
    assert result is None
    await pool.close()


async def test_file_backed_sqlite(tmp_path):
    db_path = str(tmp_path / "test.db")
    pool = SqlitePool(path=db_path)
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, val TEXT)")
    await pool.execute("INSERT INTO t (id, val) VALUES ($1, $2)", "a", "hello")
    row = await pool.fetchrow("SELECT * FROM t WHERE id = $1", "a")
    assert row == {"id": "a", "val": "hello"}
    await pool.close()

    # Re-open — data persists
    pool2 = SqlitePool(path=db_path)
    row = await pool2.fetchrow("SELECT * FROM t WHERE id = $1", "a")
    assert row == {"id": "a", "val": "hello"}
    await pool2.close()

    assert os.path.exists(db_path)


async def test_wal_mode_for_file_backed(tmp_path):
    db_path = str(tmp_path / "wal_test.db")
    pool = SqlitePool(path=db_path)
    # Force connection init
    result = await pool.fetchrow(
        "PRAGMA journal_mode",
    )
    assert result is not None
    assert result["journal_mode"] == "wal"
    await pool.close()


async def test_memory_mode_no_wal():
    pool = SqlitePool()
    result = await pool.fetchrow(
        "PRAGMA journal_mode",
    )
    assert result is not None
    # In-memory defaults to "memory" journal mode
    assert result["journal_mode"] != "wal"
    await pool.close()
