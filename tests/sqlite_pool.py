"""In-memory SQLite adapter mimicking the asyncpg Pool interface.

Provides fetch/fetchrow/execute/acquire with automatic $N -> ? placeholder
conversion so the same SQL works against both PostgreSQL and SQLite.
"""

import re
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
        await self._conn.execute(_pg_to_sqlite(sql), args if args else None)
        await self._conn.commit()


class SqlitePool:
    """Async in-memory SQLite pool mimicking the asyncpg.Pool interface."""

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._closed = False

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(":memory:")
            self._conn.row_factory = aiosqlite.Row  # type: ignore[assignment]
            await self._conn.execute("PRAGMA foreign_keys = ON")
            await self._conn.commit()
        return self._conn

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        conn = await self._get_conn()
        cursor = await conn.execute(_pg_to_sqlite(sql), args if args else None)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]  # type: ignore[arg-type]

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        conn = await self._get_conn()
        cursor = await conn.execute(_pg_to_sqlite(sql), args if args else None)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)  # type: ignore[arg-type]

    async def execute(self, sql: str, *args: Any) -> str:
        conn = await self._get_conn()
        await conn.execute(_pg_to_sqlite(sql), args if args else None)
        await conn.commit()
        return "OK"

    @asynccontextmanager
    async def acquire(self):
        conn = await self._get_conn()
        yield _ConnectionWrapper(conn)

    async def close(self) -> None:
        self._closed = True
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
