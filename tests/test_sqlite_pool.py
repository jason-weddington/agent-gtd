"""Unit tests for the in-memory SQLite pool adapter."""

from sqlite_pool import SqlitePool, _pg_to_sqlite


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
