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
