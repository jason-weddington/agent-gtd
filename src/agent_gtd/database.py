"""Async database with connection pool (PostgreSQL or SQLite fallback)."""

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_gtd.db_types import DbPool

logger = logging.getLogger(__name__)

_pool: DbPool | None = None

# Well-known IDs for local single-user mode.
LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
LOCAL_PROJECT_ID = "00000000-0000-0000-0000-000000000002"
LOCAL_EMAIL = "local@localhost"

# Each statement must be executed individually (asyncpg has no executescript).
_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
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
        git_origin TEXT NOT NULL DEFAULT '',
        kb_project_ref TEXT NOT NULL DEFAULT '',
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
    """
    CREATE TABLE IF NOT EXISTS comments (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        item_id TEXT REFERENCES items(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id),
        content_markdown TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT 'human',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (
            (project_id IS NOT NULL AND item_id IS NULL)
            OR (project_id IS NULL AND item_id IS NOT NULL)
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_comments_project_id ON comments(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_item_id ON comments(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_user_id ON comments(user_id)",
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        key_hash TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)",
    """
    CREATE TABLE IF NOT EXISTS claude_runs (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'pending',
        feature_branch TEXT NOT NULL DEFAULT '',
        workspace_dir TEXT NOT NULL DEFAULT '',
        pid INTEGER,
        max_turns INTEGER NOT NULL DEFAULT 100,
        mode TEXT NOT NULL DEFAULT 'build',
        started_at TEXT,
        finished_at TEXT,
        remote_run_id TEXT NOT NULL DEFAULT '',
        error_msg TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_claude_runs_user_id ON claude_runs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_claude_runs_item_id ON claude_runs(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_claude_runs_status ON claude_runs(status)",
    """
    CREATE TABLE IF NOT EXISTS item_dependencies (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        blocker_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        UNIQUE (item_id, blocker_item_id),
        CHECK (item_id <> blocker_item_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_item_dependencies_item "
    "ON item_dependencies(item_id)",
    "CREATE INDEX IF NOT EXISTS ix_item_dependencies_blocker "
    "ON item_dependencies(blocker_item_id)",
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_members (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        added_at TEXT NOT NULL,
        PRIMARY KEY (project_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_project_members_user ON project_members(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_project_members_project "
    "ON project_members(project_id)",
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_user_settings_user ON user_settings(user_id)",
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_attachments_item_id ON attachments(item_id)",
    """
    CREATE TABLE IF NOT EXISTS invites (
        token TEXT PRIMARY KEY,
        issued_by TEXT NOT NULL REFERENCES users(id),
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        used_at TEXT,
        used_by TEXT REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    )
    """,
]

# Idempotent column additions for existing databases.
# These run after CREATE TABLE IF NOT EXISTS, so they only matter
# when the table already existed without the new column.
_MIGRATIONS: list[str] = [
    "ALTER TABLE projects ADD COLUMN git_origin TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN kb_project_ref TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE claude_runs ADD COLUMN remote_run_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE claude_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'build'",
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_members (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        added_at TEXT NOT NULL,
        PRIMARY KEY (project_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_project_members_user ON project_members(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_project_members_project "
    "ON project_members(project_id)",
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_user_settings_user ON user_settings(user_id)",
    "ALTER TABLE projects ADD COLUMN dispatch_agent TEXT",
    "ALTER TABLE projects ADD COLUMN dispatch_max_turns INTEGER",
    "ALTER TABLE projects ADD COLUMN dispatch_timeout_minutes INTEGER",
    "ALTER TABLE projects ADD COLUMN plan_dispatch_agent TEXT",
    "ALTER TABLE projects ADD COLUMN build_dispatch_agent TEXT",
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_attachments_item_id ON attachments(item_id)",
    "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
    """
    CREATE TABLE IF NOT EXISTS invites (
        token TEXT PRIMARY KEY,
        issued_by TEXT NOT NULL REFERENCES users(id),
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        used_at TEXT,
        used_by TEXT REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    )
    """,
]


def is_local_mode() -> bool:
    """Return True when AGENT_GTD_DATABASE_URL is not set (SQLite fallback)."""
    return not os.environ.get("AGENT_GTD_DATABASE_URL")


def _get_sqlite_path() -> str:
    """Return the path to the local SQLite database file.

    Uses $XDG_DATA_HOME/agent_gtd/gtd.db, falling back to
    ~/.local/share/agent_gtd/gtd.db. Creates parent directories.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    db_dir = base / "agent_gtd"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "gtd.db")


async def get_db() -> DbPool:
    """Return the connection pool, creating it lazily if needed."""
    global _pool
    if _pool is None:
        dsn = os.environ.get("AGENT_GTD_DATABASE_URL")
        if dsn:
            import asyncpg

            _pool = await asyncpg.create_pool(dsn)
        else:
            from agent_gtd.sqlite_pool import SqlitePool

            _pool = SqlitePool(path=_get_sqlite_path())
    return _pool


async def ensure_local_user(db: DbPool) -> None:
    """Create the local user and default project if they don't exist.

    Idempotent — safe to call on every startup.
    """
    row = await db.fetchrow("SELECT id FROM users WHERE id = $1", LOCAL_USER_ID)
    if row is not None:
        return

    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        LOCAL_USER_ID,
        LOCAL_EMAIL,
        "local-no-password",
        now,
    )
    await db.execute(
        "INSERT INTO projects "
        "(id, user_id, name, description, status, area, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        LOCAL_PROJECT_ID,
        LOCAL_USER_ID,
        "Default",
        "Default project for local mode",
        "active",
        "",
        now,
        now,
    )


async def _sweep_cross_project_blockers(pool: DbPool) -> None:
    """One-time defensive cleanup: remove blocker edges that cross project boundaries.

    Before the same-project invariant was introduced, ``add_blocker`` allowed
    edges between items in different projects.  This migration finds any such
    rows and deletes them so that sharing a project cannot accidentally expose
    private item titles through leftover dependency edges.

    The migration is idempotent: after the first run there are no cross-project
    edges left, so subsequent runs query and find nothing to delete.
    """
    rows = await pool.fetch(
        """
        SELECT id.id
        FROM item_dependencies id
        JOIN items a ON id.item_id = a.id
        JOIN items b ON id.blocker_item_id = b.id
        WHERE COALESCE(a.project_id, '') <> COALESCE(b.project_id, '')
        """
    )
    count = len(rows)
    if count > 0:
        for row in rows:
            await pool.execute(
                "DELETE FROM item_dependencies WHERE id = $1",
                str(row["id"]),
            )
        logger.info("Startup migration: purged %d cross-project blocker edge(s)", count)


async def init_db() -> None:
    """Create tables if they don't exist."""
    pool = await get_db()
    async with pool.acquire() as conn:
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)
        for stmt in _MIGRATIONS:
            with contextlib.suppress(Exception):
                await conn.execute(stmt)

    await _sweep_cross_project_blockers(pool)

    if is_local_mode():
        await ensure_local_user(pool)


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
