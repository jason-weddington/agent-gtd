"""Tests for the agent-gtd CLI (src/agent_gtd/cli.py)."""

import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_gtd.cli import _cmd_run_status, _fetch_run_status, main
from agent_gtd.exceptions import NotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(**overrides: Any) -> dict[str, Any]:
    """Return a minimal run dict suitable for testing."""
    run: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "item_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "user_id": "00000000-0000-0000-0000-000000000001",
        "status": "success",
        "feature_branch": "feat/test",
        "workspace_dir": "",
        "max_turns": 50,
        "mode": "build",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "error_msg": "",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    run.update(overrides)
    return run


# ---------------------------------------------------------------------------
# Sync tests for _cmd_run_status
# These call asyncio.run() internally — must NOT be async.
# ---------------------------------------------------------------------------


def test_cmd_run_status_prints_json(monkeypatch, capsys):
    """_cmd_run_status prints valid JSON with expected fields on stdout."""
    expected = _make_run()

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)

    _cmd_run_status(expected["id"])

    captured = capsys.readouterr()
    assert captured.err == ""

    data = json.loads(captured.out)
    assert data["id"] == expected["id"]
    assert data["status"] == "success"
    assert data["feature_branch"] == "feat/test"
    assert "item_id" in data
    assert "started_at" in data
    assert "finished_at" in data
    assert "error_msg" in data


def test_cmd_run_status_not_found_exits_nonzero(monkeypatch, capsys):
    """_cmd_run_status exits 1 and writes error to stderr when run not found."""

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        raise NotFoundError("Run", run_id)

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status("nonexistent-id")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


def test_cmd_run_status_generic_error_exits_nonzero(monkeypatch, capsys):
    """_cmd_run_status exits 1 and writes error to stderr for any exception."""

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        raise RuntimeError("network failure")

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status("some-run-id")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "network failure" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Sync tests for main()
# These call _cmd_run_status -> asyncio.run() — must NOT be async.
# ---------------------------------------------------------------------------


def test_main_run_status_dispatches(monkeypatch, capsys):
    """main() with 'run-status <id>' subcommand outputs JSON to stdout."""
    expected = _make_run(status="running")
    run_id = expected["id"]

    async def _fake_fetch(rid: str) -> dict[str, Any]:
        assert rid == run_id
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "run-status", run_id])

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "running"
    assert data["id"] == run_id


def test_main_no_subcommand_exits_nonzero(monkeypatch, capsys):
    """main() with no subcommand prints help to stderr and exits non-zero."""
    monkeypatch.setattr(sys, "argv", ["agent-gtd"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    # Help goes to stderr
    assert "usage" in captured.err.lower() or "agent-gtd" in captured.err


# ---------------------------------------------------------------------------
# Async test for _fetch_run_status (uses in-memory SQLite via autouse fixture)
# ---------------------------------------------------------------------------


async def test_fetch_run_status_local_success(monkeypatch):
    """_fetch_run_status returns a run dict from local SQLite in no-URL mode."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend

    # Ensure AGENT_GTD_URL is not set so local mode branch is taken in cli.py
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    # Patch create_backend so it returns LocalBackend regardless of the
    # module-level _AGENT_GTD_URL variable (which may have been set at import time)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    run_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # The local user and a placeholder project/item must exist for FK constraints.
    # _setup_db already called init_db() which runs ensure_local_user().
    # Insert a minimal project and item for FK references.
    await db.execute(
        "INSERT INTO projects (id, user_id, name, description, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        project_id,
        LOCAL_USER_ID,
        "Test Project",
        "",
        now,
        now,
    )
    await db.execute(
        "INSERT INTO items"
        " (id, user_id, project_id, title, status, priority,"
        "  labels, created_at, updated_at, version)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        item_id,
        LOCAL_USER_ID,
        project_id,
        "Test Item",
        "next_action",
        "medium",
        "[]",
        now,
        now,
        1,
    )
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, user_id, item_id, project_id, status, feature_branch,"
        "  workspace_dir, max_turns, mode, started_at, finished_at,"
        "  error_msg, created_at, updated_at)"
        " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
        run_id,
        LOCAL_USER_ID,
        item_id,
        project_id,
        "success",
        "feat/test",
        "",
        50,
        "build",
        now,
        now,
        "",
        now,
        now,
    )

    result = await _fetch_run_status(run_id)

    assert result["status"] == "success"
    assert result["id"] == run_id
    assert result["item_id"] == item_id
    assert result["feature_branch"] == "feat/test"


async def test_fetch_run_status_http_missing_api_key(monkeypatch):
    """_fetch_run_status raises RuntimeError when AGENT_GTD_URL set but no API key."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)
    # Use LocalBackend so we don't hit the network, but env check still fires
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(RuntimeError, match="AGENT_GTD_API_KEY"):
        await _fetch_run_status("some-run-id")


async def test_fetch_run_status_http_success(monkeypatch):
    """_fetch_run_status returns run dict when HTTP backend authenticates."""
    expected = _make_run(status="running")

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            assert api_key == "test-key"
            return {"user_id": "fake-user", "agent_name": agent_name}

        async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]:
            assert user_id == "fake-user"
            return expected

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    result = await _fetch_run_status(expected["id"])

    assert result["id"] == expected["id"]
    assert result["status"] == "running"
