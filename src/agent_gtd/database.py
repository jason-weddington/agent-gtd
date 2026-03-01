"""Async PostgreSQL database with connection pool."""

import json
import os
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None

# Each statement must be executed individually (asyncpg has no executescript).
_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        area TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)",
    """
    CREATE TABLE IF NOT EXISTS items (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id),
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'inbox',
        priority TEXT NOT NULL DEFAULT 'normal',
        due_date TEXT,
        completed_at TEXT,
        created_by TEXT NOT NULL DEFAULT 'human',
        assigned_to TEXT NOT NULL DEFAULT '',
        waiting_on TEXT NOT NULL DEFAULT '',
        sort_order DOUBLE PRECISION NOT NULL DEFAULT 0,
        labels TEXT NOT NULL DEFAULT '[]',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_project_id ON items(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)",
    """
    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id),
        title TEXT NOT NULL DEFAULT '',
        content_markdown TEXT NOT NULL DEFAULT '',
        labels TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_notes_project_id ON notes(project_id)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        project_id TEXT,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """CREATE INDEX IF NOT EXISTS idx_events_user_created
    ON events (user_id, created_at)""",
]


async def get_db() -> asyncpg.Pool:
    """Return the connection pool, creating it lazily if needed."""
    global _pool
    if _pool is None:
        dsn = os.environ.get("AGENT_GTD_DATABASE_URL")
        if not dsn:
            msg = "AGENT_GTD_DATABASE_URL environment variable is not set"
            raise RuntimeError(msg)
        _pool = await asyncpg.create_pool(dsn)
    return _pool


async def init_db() -> None:
    """Create tables if they don't exist."""
    pool = await get_db()
    async with pool.acquire() as conn:
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)


async def close_db() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a Record to a plain dict."""
    return dict(row)


def encode_json_list(items: list[str]) -> str:
    """Encode a list as JSON text for storage."""
    return json.dumps(items)


def decode_json_list(text: str) -> list[str]:
    """Decode JSON text back to a list."""
    result: list[str] = json.loads(text)
    return result
