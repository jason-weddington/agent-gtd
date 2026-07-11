"""Tests for database module local-mode helpers."""

import os

import agent_gtd.database as db_mod
from agent_gtd.database import (
    LOCAL_EMAIL,
    LOCAL_PROJECT_ID,
    LOCAL_USER_ID,
    _get_sqlite_path,
    ensure_local_user,
    is_local_mode,
)


def test_is_local_mode_true(monkeypatch):
    monkeypatch.delenv("AGENT_GTD_DATABASE_URL", raising=False)
    assert is_local_mode() is True


def test_is_local_mode_false(monkeypatch):
    monkeypatch.setenv("AGENT_GTD_DATABASE_URL", "postgresql://localhost/test")
    assert is_local_mode() is False


def test_get_sqlite_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    path = _get_sqlite_path()
    assert path == str(tmp_path / ".local" / "share" / "agent_gtd" / "gtd.db")
    assert os.path.isdir(tmp_path / ".local" / "share" / "agent_gtd")


def test_get_sqlite_path_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    path = _get_sqlite_path()
    assert path == str(tmp_path / "xdg_data" / "agent_gtd" / "gtd.db")
    assert os.path.isdir(tmp_path / "xdg_data" / "agent_gtd")


async def test_ensure_local_user_creates_user_and_project():
    from agent_gtd.sqlite_pool import SqlitePool

    pool = SqlitePool()
    # Create schema
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)

    await ensure_local_user(pool)

    user = await pool.fetchrow("SELECT * FROM users WHERE id = $1", LOCAL_USER_ID)
    assert user is not None
    assert user["email"] == LOCAL_EMAIL

    project = await pool.fetchrow(
        "SELECT * FROM projects WHERE id = $1", LOCAL_PROJECT_ID
    )
    assert project is not None
    assert project["user_id"] == LOCAL_USER_ID
    assert project["name"] == "Default"

    await pool.close()


async def test_item_dependencies_table_exists():
    """item_dependencies table and indexes are created by _SCHEMA_STATEMENTS."""
    from agent_gtd.sqlite_pool import SqlitePool

    pool = SqlitePool()
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)

    # Table is queryable (proves it exists).
    rows = await pool.fetch("SELECT * FROM item_dependencies")
    assert rows == []

    # Confirm the table name appears in sqlite_master.
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='item_dependencies'"
    )
    assert len(tables) == 1
    assert tables[0]["name"] == "item_dependencies"

    await pool.close()


async def test_item_dependencies_constraints():
    """UNIQUE and CHECK constraints on item_dependencies are enforced."""
    import uuid

    from agent_gtd.sqlite_pool import SqlitePool

    pool = SqlitePool()
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)

    now = "2026-01-01T00:00:00+00:00"
    user_id = str(uuid.uuid4())
    item_a = str(uuid.uuid4())
    item_b = str(uuid.uuid4())

    # Seed a user so FK constraints pass.
    await pool.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        "u@test.com",
        "x",
        now,
    )
    # Seed two items (project_id nullable).
    for item_id in (item_a, item_b):
        await pool.execute(
            "INSERT INTO items "
            "(id, project_id, user_id, title, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            item_id,
            None,
            user_id,
            "t",
            now,
            now,
        )

    dep_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at) "
        "VALUES ($1, $2, $3, $4)",
        dep_id,
        item_a,
        item_b,
        now,
    )

    # UNIQUE: duplicate (item_a, item_b) must fail.
    import pytest

    # Use a broad catch: sqlite raises IntegrityError, asyncpg raises
    # UniqueViolationError — both subclass Exception.
    with pytest.raises(Exception):  # noqa: B017
        await pool.execute(
            "INSERT INTO item_dependencies "
            "(id, item_id, blocker_item_id, created_at) "
            "VALUES ($1, $2, $3, $4)",
            str(uuid.uuid4()),
            item_a,
            item_b,
            now,
        )

    # CHECK: self-block must fail.
    with pytest.raises(Exception):  # noqa: B017
        await pool.execute(
            "INSERT INTO item_dependencies "
            "(id, item_id, blocker_item_id, created_at) "
            "VALUES ($1, $2, $3, $4)",
            str(uuid.uuid4()),
            item_a,
            item_a,
            now,
        )

    await pool.close()


async def test_project_members_table_exists():
    """project_members table and indexes are created by _SCHEMA_STATEMENTS."""
    from agent_gtd.sqlite_pool import SqlitePool

    pool = SqlitePool()
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)

    # Table is queryable (proves it exists).
    rows = await pool.fetch("SELECT * FROM project_members")
    assert rows == []

    # Confirm the table name appears in sqlite_master.
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='project_members'"
    )
    assert len(tables) == 1
    assert tables[0]["name"] == "project_members"

    # Confirm both indexes exist in sqlite_master.
    indexes = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='project_members' "
        "AND name IN ('ix_project_members_user', 'ix_project_members_project')"
    )
    index_names = {row["name"] for row in indexes}
    assert "ix_project_members_user" in index_names
    assert "ix_project_members_project" in index_names

    await pool.close()


async def test_ensure_local_user_idempotent():
    from agent_gtd.sqlite_pool import SqlitePool

    pool = SqlitePool()
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)

    await ensure_local_user(pool)
    await ensure_local_user(pool)  # Should not raise

    rows = await pool.fetch("SELECT * FROM users WHERE id = $1", LOCAL_USER_ID)
    assert len(rows) == 1

    await pool.close()


async def test_failing_migration_is_logged_and_loop_continues(monkeypatch, caplog):
    """Failing migration logs a WARNING; subsequent migrations still run.

    Regression guard for item 1b1b79de: suppress must log, not swallow silently.
    """
    import logging

    from agent_gtd.database import get_db, init_db

    bad_stmt = "INVALID SQL THAT WILL DEFINITELY FAIL"
    sentinel_col = "_test_migration_sentinel_col"
    good_stmt = f"ALTER TABLE items ADD COLUMN {sentinel_col} TEXT"

    monkeypatch.setattr(db_mod, "_MIGRATIONS", [bad_stmt, good_stmt])

    with caplog.at_level(logging.WARNING, logger="agent_gtd.database"):
        await init_db()

    # The bad statement must appear in a WARNING record from agent_gtd.database.
    warnings = [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and r.name == "agent_gtd.database"
    ]
    assert warnings, "Expected at least one WARNING from the failing migration"
    assert bad_stmt in warnings[0].getMessage()

    # The loop must have continued — sentinel column was added by the good statement.
    pool = await get_db()
    rows = await pool.fetch(f"SELECT {sentinel_col} FROM items LIMIT 1")  # noqa: S608
    assert rows is not None  # query did not raise → column exists
