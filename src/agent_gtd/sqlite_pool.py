"""SQLite adapter mimicking the asyncpg Pool interface.

Provides fetch/fetchrow/execute/acquire with automatic $N -> ? placeholder
conversion so the same SQL works against both PostgreSQL and SQLite.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite


def _pg_to_sqlite(sql: str) -> str:
    """Convert PostgreSQL $1, $2, ... placeholders to SQLite ? placeholders."""
    return re.sub(r"\$\d+", "?", sql)


class _ConnectionWrapper:
    """Wraps an aiosqlite connection to expose an asyncpg-like execute()."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, *args: Any) -> None:
        """Execute a SQL statement."""
        await self._conn.execute(_pg_to_sqlite(sql), args if args else None)
        await self._conn.commit()


class SqlitePool:
    """Async SQLite pool mimicking the asyncpg.Pool interface.

    Args:
        path: Path to the SQLite database file, or ":memory:" for in-memory.
    """

    def __init__(self, path: str = ":memory:") -> None:
        """Initialize the pool with a database path."""
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._closed = False

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON")
            if self._path != ":memory:":
                await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.commit()
        return self._conn

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Fetch all rows matching the query."""
        conn = await self._get_conn()
        cursor = await conn.execute(_pg_to_sqlite(sql), args if args else None)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        """Fetch a single row, or None."""
        conn = await self._get_conn()
        cursor = await conn.execute(_pg_to_sqlite(sql), args if args else None)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute a SQL statement and return 'OK'."""
        conn = await self._get_conn()
        await conn.execute(_pg_to_sqlite(sql), args if args else None)
        await conn.commit()
        return "OK"

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_ConnectionWrapper]:
        """Acquire a connection wrapper (context manager)."""
        conn = await self._get_conn()
        yield _ConnectionWrapper(conn)

    async def close(self) -> None:
        """Close the underlying connection."""
        self._closed = True
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
