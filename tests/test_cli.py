"""Tests for the agent-gtd CLI (src/agent_gtd/cli.py)."""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_gtd.cli import (
    _cmd_rollout_status,
    _cmd_run_status,
    _do_add_item,
    _do_update_item,
    _fetch_rollout_status,
    _fetch_run_status,
    main,
)
from agent_gtd.exceptions import NotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_status_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the run-status subcommand with defaults."""
    defaults: dict[str, Any] = {
        "run_id": "test-run-id",
        "wait": False,
        "poll_interval": 30,
        "timeout": 0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _rollout_status_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the rollout-status subcommand with defaults."""
    defaults: dict[str, Any] = {
        "rollout_id": "test-rollout-id",
        "wait": False,
        "poll_interval": 30,
        "timeout": 0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


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
    """_cmd_run_status prints valid JSON with expected fields on stdout (no --wait)."""
    expected = _make_run()

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)

    _cmd_run_status(_run_status_args(run_id=expected["id"]))

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
        _cmd_run_status(_run_status_args(run_id="nonexistent-id"))

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
        _cmd_run_status(_run_status_args(run_id="some-run-id"))

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


# ---------------------------------------------------------------------------
# Helpers for rollout tests
# ---------------------------------------------------------------------------


def _make_rollout(**overrides: Any) -> dict[str, Any]:
    """Return a minimal rollout dict suitable for testing."""
    rollout: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "lead_user_id": "00000000-0000-0000-0000-000000000001",
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    rollout.update(overrides)
    return rollout


# ---------------------------------------------------------------------------
# Sync tests for _cmd_rollout_status
# These call asyncio.run() internally — must NOT be async.
# ---------------------------------------------------------------------------


def test_cmd_rollout_status_prints_json(monkeypatch, capsys):
    """_cmd_rollout_status prints JSON with expected fields on stdout (no --wait)."""
    expected = _make_rollout()

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)

    _cmd_rollout_status(_rollout_status_args(rollout_id=expected["id"]))

    captured = capsys.readouterr()
    assert captured.err == ""

    data = json.loads(captured.out)
    assert data["id"] == expected["id"]
    assert data["status"] == "running"
    assert data["project_id"] == expected["project_id"]
    assert "lead_user_id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_cmd_rollout_status_not_found_exits_nonzero(monkeypatch, capsys):
    """_cmd_rollout_status exits 1 and writes error to stderr when rollout not found."""

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        raise NotFoundError("Rollout", rollout_id)

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_rollout_status(_rollout_status_args(rollout_id="nonexistent-id"))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


def test_cmd_rollout_status_generic_error_exits_nonzero(monkeypatch, capsys):
    """_cmd_rollout_status exits 1 and writes error to stderr for any exception."""

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        raise RuntimeError("network failure")

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_rollout_status(_rollout_status_args(rollout_id="some-rollout-id"))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "network failure" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Sync tests for main() rollout-status dispatch
# These call _cmd_rollout_status -> asyncio.run() — must NOT be async.
# ---------------------------------------------------------------------------


def test_main_rollout_status_dispatches(monkeypatch, capsys):
    """main() with 'rollout-status <id>' subcommand outputs JSON to stdout."""
    expected = _make_rollout(status="completed")
    rollout_id = expected["id"]

    async def _fake_fetch(rid: str) -> dict[str, Any]:
        assert rid == rollout_id
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "rollout-status", rollout_id])

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"
    assert data["id"] == rollout_id


# ---------------------------------------------------------------------------
# Async tests for _fetch_rollout_status
# ---------------------------------------------------------------------------


async def test_fetch_rollout_status_local_success(monkeypatch):
    """_fetch_rollout_status returns a rollout dict from local DB in no-URL mode."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    rollout_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Insert a minimal project for FK reference.
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
    # Insert a minimal rollout row.
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        LOCAL_USER_ID,
        "running",
        now,
        now,
    )

    result = await _fetch_rollout_status(rollout_id)

    assert result["status"] == "running"
    assert result["id"] == rollout_id
    assert result["project_id"] == project_id
    assert result["lead_user_id"] == LOCAL_USER_ID


async def test_fetch_rollout_status_http_missing_api_key(monkeypatch):
    """Raises RuntimeError when AGENT_GTD_URL set but AGENT_GTD_API_KEY unset."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(RuntimeError, match="AGENT_GTD_API_KEY"):
        await _fetch_rollout_status("some-rollout-id")


async def test_fetch_rollout_status_http_success(monkeypatch):
    """_fetch_rollout_status returns rollout dict when HTTP backend authenticates."""
    expected = _make_rollout(status="completed")

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            assert api_key == "test-key"
            return {"user_id": "fake-user", "agent_name": agent_name}

        async def get_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
            assert user_id == "fake-user"
            return expected

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    result = await _fetch_rollout_status(expected["id"])

    assert result["id"] == expected["id"]
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# promote-admin
# ---------------------------------------------------------------------------


@pytest.fixture
def _keep_db_open(monkeypatch):
    """Keep the autouse test SQLite pool alive across _promote_admin's close_db()."""

    async def _noop():
        return None

    monkeypatch.setattr("agent_gtd.database.close_db", _noop)


async def test_promote_admin_success(_keep_db_open):
    """_promote_admin sets is_admin=1 on an existing user."""
    from agent_gtd.auth import register_user
    from agent_gtd.cli import _promote_admin
    from agent_gtd.database import get_db

    await register_user("alice@example.com", "pw1234567")

    msg = await _promote_admin("alice@example.com")

    assert "promoted" in msg
    db = await get_db()
    row = await db.fetchrow(
        "SELECT is_admin FROM users WHERE email = $1", "alice@example.com"
    )
    assert row is not None
    assert row["is_admin"] == 1


async def test_promote_admin_idempotent(_keep_db_open):
    """Promoting an already-admin user reports the no-op without erroring."""
    from agent_gtd.auth import register_user
    from agent_gtd.cli import _promote_admin

    await register_user("bob@example.com", "pw1234567")
    await _promote_admin("bob@example.com")

    msg = await _promote_admin("bob@example.com")

    assert "already" in msg


async def test_promote_admin_unknown_email_raises(_keep_db_open):
    """_promote_admin raises ValueError if no user matches the email."""
    from agent_gtd.cli import _promote_admin

    with pytest.raises(ValueError, match="no user found"):
        await _promote_admin("ghost@example.com")


def test_main_promote_admin_dispatches(monkeypatch, capsys):
    """main() with 'promote-admin <email>' invokes _cmd_promote_admin."""
    called: dict[str, str] = {}

    def _fake(email: str) -> None:
        called["email"] = email

    monkeypatch.setattr("agent_gtd.cli._cmd_promote_admin", _fake)
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "promote-admin", "x@y.z"])

    main()

    assert called["email"] == "x@y.z"


def test_cmd_promote_admin_prints_message(monkeypatch, capsys):
    """_cmd_promote_admin prints the success message to stdout."""
    from agent_gtd.cli import _cmd_promote_admin

    async def _fake(email: str) -> str:
        return f"promoted {email} to admin"

    monkeypatch.setattr("agent_gtd.cli._promote_admin", _fake)

    _cmd_promote_admin("alice@example.com")

    captured = capsys.readouterr()
    assert "promoted alice@example.com" in captured.out


def test_cmd_promote_admin_error_exits_nonzero(monkeypatch, capsys):
    """_cmd_promote_admin prints to stderr and exits non-zero on failure."""
    from agent_gtd.cli import _cmd_promote_admin

    async def _fake(email: str) -> str:
        raise ValueError("no user found")

    monkeypatch.setattr("agent_gtd.cli._promote_admin", _fake)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_promote_admin("ghost@example.com")

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# update-item and add-item — helpers
# ---------------------------------------------------------------------------


def _make_item(**overrides: Any) -> dict[str, Any]:
    """Return a minimal item dict for fake-backend testing."""
    item: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "user_id": "00000000-0000-0000-0000-000000000001",
        "title": "Test Item",
        "description": "",
        "status": "inbox",
        "priority": "normal",
        "labels": [],
        "version": 1,
        "acceptance_criteria": [],
        "files_to_modify": [],
        "scope_out": [],
        "build_engine": None,
        "project_id": None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# (a) update-item from --stdin updates fields and bumps version
# ---------------------------------------------------------------------------


async def test_do_update_item_stdin_updates_fields_and_bumps_version(monkeypatch):
    """(a) update-item payload updates fields and the version is bumped."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Original", status="inbox"
    )
    item_id = str(row["id"])

    # Simulate what _load_json_payload returns when --stdin is used
    payload = {"acceptance_criteria": ["step 1", "step 2"], "title": "Updated"}
    await _do_update_item(
        item_id, payload, status="ready", build_engine=None, explicit_version=1
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["title"] == "Updated"
    assert updated["status"] == "ready"
    assert updated["version"] == 2


def test_cmd_update_item_reads_stdin(monkeypatch, capsys):
    """(a) _cmd_update_item parses JSON from stdin and forwards it."""
    import io

    called: dict[str, Any] = {}

    async def _fake_do(  # type: ignore[misc]
        item_id: str, payload: Any, status: Any, be: Any, ver: Any
    ) -> None:
        called["payload"] = payload
        called["status"] = status

    monkeypatch.setattr("agent_gtd.cli._do_update_item", _fake_do)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"acceptance_criteria": ["x"]}))
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--stdin", "--status", "ready"],
    )

    main()

    assert called["payload"] == {"acceptance_criteria": ["x"]}
    assert called["status"] == "ready"


# ---------------------------------------------------------------------------
# (b) update-item auto-fetches version when --version omitted
# ---------------------------------------------------------------------------


async def test_do_update_item_auto_fetches_version(monkeypatch):
    """(b) update-item auto-fetches current version when --version is omitted."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(db, LOCAL_USER_ID, title="Auto-fetch test")
    item_id = str(row["id"])
    assert row["version"] == 1

    # explicit_version=None → auto-fetch; should succeed without error
    await _do_update_item(
        item_id,
        {"title": "Auto-fetched"},
        status=None,
        build_engine=None,
        explicit_version=None,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["title"] == "Auto-fetched"
    assert updated["version"] == 2


# ---------------------------------------------------------------------------
# (c) update-item retries once on conflict then succeeds
# ---------------------------------------------------------------------------


async def test_do_update_item_retries_once_on_conflict(monkeypatch):
    """(c) update-item retries exactly once on a version conflict then succeeds."""
    from fastmcp.exceptions import ToolError

    get_item_calls: list[int] = []
    update_calls: list[int] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            call_n = len(get_item_calls) + 1
            get_item_calls.append(call_n)
            return _make_item(id=item_id, version=call_n)

        async def update_item(
            self,
            user_id: str,
            item_id: str,
            *,
            version: int,
            **kwargs: Any,
        ) -> dict[str, Any]:
            call_n = len(update_calls) + 1
            update_calls.append(call_n)
            if call_n == 1:
                raise ToolError(
                    f"Version conflict on Item {item_id}: expected {version},"
                    f" got {version + 1}"
                )
            return _make_item(id=item_id, version=version + 1)

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    # Should complete without raising — first attempt conflicts, retry succeeds.
    await _do_update_item(
        "item-uuid",
        {"title": "New Title"},
        status=None,
        build_engine=None,
        explicit_version=None,
    )

    assert len(update_calls) == 2, "expected exactly two update_item calls"
    assert len(get_item_calls) == 2, "expected two get_item fetches (initial + retry)"


# ---------------------------------------------------------------------------
# (d) update-item with stale --version exits non-zero, NO retry
# ---------------------------------------------------------------------------


async def test_do_update_item_explicit_version_no_retry_on_conflict(monkeypatch):
    """(d) explicit --version conflicts immediately, no retry, non-zero exit."""
    from fastmcp.exceptions import ToolError

    update_calls: list[int] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def update_item(
            self,
            user_id: str,
            item_id: str,
            *,
            version: int,
            **kwargs: Any,
        ) -> dict[str, Any]:
            update_calls.append(version)
            raise ToolError(
                f"Version conflict on Item {item_id}: expected {version},"
                f" got {version + 1}"
            )

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    with pytest.raises(ToolError, match="Version conflict"):
        await _do_update_item(
            "item-uuid",
            {"title": "X"},
            status=None,
            build_engine=None,
            explicit_version=1,
        )

    assert len(update_calls) == 1, "explicit-version path must NOT retry"


def test_cmd_update_item_explicit_version_conflict_exits_nonzero(monkeypatch, capsys):
    """(d) _cmd_update_item exits 1 when explicit --version conflicts."""
    from fastmcp.exceptions import ToolError

    async def _fake_do(  # type: ignore[misc]
        item_id: str, payload: Any, status: Any, be: Any, ver: Any
    ) -> None:
        raise ToolError("Version conflict on Item x: expected 1, got 2")

    monkeypatch.setattr("agent_gtd.cli._do_update_item", _fake_do)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--status", "ready", "--version", "1"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Version conflict" in captured.err


# ---------------------------------------------------------------------------
# (e) update-item with acceptance_criteria=[] clears field, title unchanged
# ---------------------------------------------------------------------------


async def test_do_update_item_empty_list_clears_acceptance_criteria(monkeypatch):
    """(e) acceptance_criteria=[] clears the column; title stays unchanged."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db,
        LOCAL_USER_ID,
        title="Keep This Title",
        status="inbox",
        acceptance_criteria=["step 1", "step 2"],
    )
    item_id = str(row["id"])

    # Pass empty list — should CLEAR acceptance_criteria
    await _do_update_item(
        item_id,
        {"acceptance_criteria": []},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert json.loads(updated["acceptance_criteria"]) == []
    assert updated["title"] == "Keep This Title"  # unchanged


# ---------------------------------------------------------------------------
# (f) update-item with invalid --build-engine exits non-zero with Error:
# ---------------------------------------------------------------------------


async def test_do_update_item_invalid_build_engine_raises(monkeypatch):
    """(f) _do_update_item raises ValidationError for invalid build_engine."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Test", status="inbox"
    )
    item_id = str(row["id"])

    with pytest.raises(ValidationError, match="build_engine"):
        await _do_update_item(
            item_id, {}, status=None, build_engine="gpt-4", explicit_version=1
        )


def test_cmd_update_item_invalid_build_engine_exits_nonzero(monkeypatch, capsys):
    """(f) _cmd_update_item exits 1 with Error: on stderr for invalid build-engine."""
    from agent_gtd.exceptions import ValidationError

    async def _fake_do(  # type: ignore[misc]
        item_id: str, payload: Any, status: Any, be: Any, ver: Any
    ) -> None:
        raise ValidationError("build_engine must be one of [...]")

    monkeypatch.setattr("agent_gtd.cli._do_update_item", _fake_do)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--build-engine", "gpt-4"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# (f2) build_engine via JSON payload persists + invalid value errors
# ---------------------------------------------------------------------------


async def test_do_update_item_build_engine_via_json_persists(monkeypatch):
    """(f2) build_engine in JSON payload is forwarded with build_engine_set=True."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="BE Test", status="inbox"
    )
    item_id = str(row["id"])

    # No --build-engine flag; value comes from JSON payload.
    await _do_update_item(
        item_id,
        {"build_engine": "claude-code-sonnet"},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["build_engine"] == "claude-code-sonnet"


async def test_do_update_item_invalid_build_engine_via_json_raises(monkeypatch):
    """(f2) invalid build_engine in JSON payload raises ValidationError."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="BE Invalid", status="inbox"
    )
    item_id = str(row["id"])

    with pytest.raises(ValidationError, match="build_engine must be one of"):
        await _do_update_item(
            item_id,
            {"build_engine": "bogus"},
            status=None,
            build_engine=None,
            explicit_version=1,
        )


def test_cmd_update_item_invalid_build_engine_via_json_exits_nonzero(
    monkeypatch, capsys
):
    """(f2) _cmd_update_item exits 1 with 'build_engine must be one of'."""
    from agent_gtd.exceptions import ValidationError

    async def _fake_do(  # type: ignore[misc]
        item_id: str, payload: Any, status: Any, be: Any, ver: Any
    ) -> None:
        raise ValidationError("build_engine must be one of [...]")

    monkeypatch.setattr("agent_gtd.cli._do_update_item", _fake_do)
    import io

    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"build_engine": "bogus"}))
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--stdin"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "build_engine must be one of" in captured.err


# ---------------------------------------------------------------------------
# (f3) unknown payload key errors loudly, no write
# ---------------------------------------------------------------------------


def test_do_update_item_unknown_key_raises_before_write(monkeypatch):
    """(f3) unknown payload key raises ValueError, backend.update_item not called."""
    update_calls: list[Any] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            return _make_item(id=item_id, version=1)

        async def update_item(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            update_calls.append(kwargs)
            return _make_item(id="item-uuid", version=2)

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    with pytest.raises(ValueError, match="unknown field\\(s\\): bogus_field"):
        import asyncio

        asyncio.run(
            _do_update_item(
                "item-uuid",
                {"title": "x", "bogus_field": 1},
                status=None,
                build_engine=None,
                explicit_version=1,
            )
        )

    assert len(update_calls) == 0, "backend.update_item must NOT be called"


def test_cmd_update_item_unknown_key_exits_nonzero(monkeypatch, capsys):
    """(f3) _cmd_update_item exits 1 with 'unknown field(s)' error for unknown key."""
    import io

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"title": "x", "bogus_field": 1})),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--stdin"],
    )
    # We need _do_update_item to actually run (not mocked) to test the ValueError path,
    # but we need the backend mock to avoid real DB calls.
    update_calls: list[Any] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            return _make_item(id="item-id", version=1)

        async def update_item(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            update_calls.append(kwargs)
            return _make_item(id="item-id", version=2)

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "unknown field(s): bogus_field" in captured.err
    assert len(update_calls) == 0, "backend.update_item must NOT be called"


def test_cmd_update_item_version_in_payload_rejected(monkeypatch, capsys):
    """(f3) `version` in payload is rejected as an unknown field."""
    import io

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"title": "x", "version": 2})),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--stdin"],
    )
    update_calls: list[Any] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            return _make_item(id="item-id", version=1)

        async def update_item(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            update_calls.append(kwargs)
            return _make_item(id="item-id", version=2)

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "unknown field(s): version" in captured.err
    assert len(update_calls) == 0, "backend.update_item must NOT be called"


# ---------------------------------------------------------------------------
# (f4) previously-dropped fields now forward correctly
# ---------------------------------------------------------------------------


async def test_do_update_item_previously_dropped_fields_forward(monkeypatch):
    """(f4) status, priority, assigned_to, due_date now reach backend.update_item."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Dropped Fields", status="inbox"
    )
    item_id = str(row["id"])

    await _do_update_item(
        item_id,
        {
            "status": "ready",
            "priority": "high",
            "assigned_to": "alice",
            "due_date": "2026-12-31",
        },
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["status"] == "ready"
    assert updated["priority"] == "high"
    assert updated["assigned_to"] == "alice"
    assert updated["due_date"] is not None  # date was set


async def test_do_update_item_due_date_clear_sentinel(monkeypatch):
    """(f4) due_date="" clears the field (due_date_set=True, due_date=None)."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    # Create item with a due_date set.
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Due Date Clear", status="inbox", due_date="2026-06-01"
    )
    item_id = str(row["id"])
    assert row["due_date"] is not None

    # Empty string clears the due_date.
    await _do_update_item(
        item_id,
        {"due_date": ""},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["due_date"] is None


async def test_do_update_item_project_id_detach_sentinel(monkeypatch):
    """(f4) project_id="" detaches item from project (project_id_set=True)."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service, project_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    project = await project_service.create_project(
        db, LOCAL_USER_ID, name="Test Project"
    )
    project_id = str(project["id"])
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Attached Item", status="inbox", project_id=project_id
    )
    item_id = str(row["id"])
    assert row["project_id"] is not None

    # Empty string detaches the item.
    await _do_update_item(
        item_id,
        {"project_id": ""},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["project_id"] is None


async def test_do_update_item_build_engine_clear_sentinel(monkeypatch):
    """(f4) build_engine="" clears the field (build_engine_set=True)."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db,
        LOCAL_USER_ID,
        title="BE Clear",
        status="inbox",
        build_engine="claude-code",
    )
    item_id = str(row["id"])
    assert row["build_engine"] == "claude-code"

    # Empty string clears the build_engine.
    await _do_update_item(
        item_id,
        {"build_engine": ""},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["build_engine"] is None


async def test_do_update_item_project_id_move_sentinel(monkeypatch):
    """(f4) project_id=<uuid> moves item to that project (project_id_set=True)."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service, project_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    project = await project_service.create_project(
        db, LOCAL_USER_ID, name="Target Project"
    )
    project_id = str(project["id"])
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Unattached Item", status="inbox"
    )
    item_id = str(row["id"])
    assert row["project_id"] is None

    # Non-empty UUID moves the item to the project.
    await _do_update_item(
        item_id,
        {"project_id": project_id},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert str(updated["project_id"]) == project_id


# ---------------------------------------------------------------------------
# (f5) JSON null = unchanged
# ---------------------------------------------------------------------------


async def test_do_update_item_json_null_means_unchanged(monkeypatch):
    """(f5) JSON null values are treated identically to absent keys (unchanged)."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db,
        LOCAL_USER_ID,
        title="Null Test",
        status="inbox",
        due_date="2026-06-01",
    )
    item_id = str(row["id"])

    # Both null values should leave the fields unchanged.
    await _do_update_item(
        item_id,
        {"due_date": None, "title": None},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    # title should remain "Null Test" (null → unchanged)
    assert updated["title"] == "Null Test"
    # due_date should remain set (null → due_date_set=False → unchanged)
    assert updated["due_date"] is not None


# ---------------------------------------------------------------------------
# (f6) flag wins over payload
# ---------------------------------------------------------------------------


async def test_do_update_item_flag_status_wins_over_payload(monkeypatch):
    """(f6) --status flag takes precedence over payload['status']."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Flag Wins", status="inbox"
    )
    item_id = str(row["id"])

    # Flag status="done" wins over payload status="ready".
    await _do_update_item(
        item_id,
        {"status": "ready"},
        status="done",
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["status"] == "done"


async def test_do_update_item_flag_build_engine_wins_over_payload(monkeypatch):
    """(f6) --build-engine flag takes precedence over payload['build_engine']."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="BE Flag Wins", status="inbox"
    )
    item_id = str(row["id"])

    # Flag build_engine="claude-code" wins over payload build_engine="kiro".
    await _do_update_item(
        item_id,
        {"build_engine": "kiro"},
        status=None,
        build_engine="claude-code",
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["build_engine"] == "claude-code"


async def test_do_update_item_no_flag_payload_status_used(monkeypatch):
    """(f6) When flag is absent (None), payload['status'] is forwarded."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import item_service

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()
    row = await item_service.create_item(
        db, LOCAL_USER_ID, title="Payload Status", status="inbox"
    )
    item_id = str(row["id"])

    # No flag (None) → payload status is used.
    await _do_update_item(
        item_id,
        {"status": "ready"},
        status=None,
        build_engine=None,
        explicit_version=1,
    )

    updated = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert updated is not None
    assert updated["status"] == "ready"


# ---------------------------------------------------------------------------
# (g) add-item prints new UUID to stdout and persists heavy fields
# ---------------------------------------------------------------------------


async def test_do_add_item_returns_uuid_and_persists_heavy_fields(monkeypatch):
    """(g) _do_add_item returns a valid UUID and persists all heavy fields."""
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    db = await get_db()

    ac = ["criterion 1", "criterion 2"]
    ftm = [{"path": "src/foo.py", "change": "add stuff"}]
    so = ["not this part"]

    new_id = await _do_add_item(
        project_id=None,
        payload={
            "title": "New Item",
            "description": "A description",
            "acceptance_criteria": ac,
            "files_to_modify": ftm,
            "scope_out": so,
        },
        status="next_action",
        labels_cli=None,
    )

    # Must be a valid UUID
    uuid.UUID(new_id)

    row = await db.fetchrow("SELECT * FROM items WHERE id = $1", new_id)
    assert row is not None
    assert row["title"] == "New Item"
    assert row["status"] == "next_action"
    assert json.loads(row["acceptance_criteria"]) == ac
    assert json.loads(row["files_to_modify"]) == ftm
    assert json.loads(row["scope_out"]) == so


def test_cmd_add_item_prints_uuid_only_to_stdout(monkeypatch, capsys):
    """(g) _cmd_add_item prints ONLY the UUID to stdout, nothing else."""
    import io

    fake_id = str(uuid.uuid4())

    async def _fake_do(
        project_id: Any, payload: Any, status: Any, labels_cli: Any
    ) -> str:
        return fake_id

    monkeypatch.setattr("agent_gtd.cli._do_add_item", _fake_do)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"title": "Test"})))
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "add-item", "--stdin"])

    main()

    captured = capsys.readouterr()
    assert captured.out == f"{fake_id}\n"
    assert captured.err == ""


# ---------------------------------------------------------------------------
# (h) add-item with invalid build_engine in JSON exits non-zero with Error:
# ---------------------------------------------------------------------------


async def test_do_add_item_invalid_build_engine_raises(monkeypatch):
    """(h) _do_add_item raises ValidationError for invalid build_engine in JSON."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(ValidationError, match="build_engine"):
        await _do_add_item(
            project_id=None,
            payload={"title": "Test", "build_engine": "gpt-4"},
            status=None,
            labels_cli=None,
        )


def test_cmd_add_item_invalid_build_engine_exits_nonzero(monkeypatch, capsys):
    """(h) _cmd_add_item exits 1 with Error: on stderr for invalid build_engine."""
    import io

    from agent_gtd.exceptions import ValidationError

    async def _fake_do(
        project_id: Any, payload: Any, status: Any, labels_cli: Any
    ) -> str:
        raise ValidationError("build_engine must be one of [...]")

    monkeypatch.setattr("agent_gtd.cli._do_add_item", _fake_do)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"title": "Test", "build_engine": "gpt-4"})),
    )
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "add-item", "--stdin"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# (i) add-item with JSON missing 'title' exits non-zero
# ---------------------------------------------------------------------------


async def test_do_add_item_missing_title_raises(monkeypatch):
    """(i) _do_add_item raises ValueError when 'title' is absent from payload."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(ValueError, match="title"):
        await _do_add_item(
            project_id=None,
            payload={"acceptance_criteria": ["step 1"]},  # no title
            status=None,
            labels_cli=None,
        )


def test_cmd_add_item_missing_title_exits_nonzero(monkeypatch, capsys):
    """(i) _cmd_add_item exits 1 when payload has no 'title'."""
    import io

    async def _fake_do(
        project_id: Any, payload: Any, status: Any, labels_cli: Any
    ) -> str:
        raise ValueError("JSON payload must include 'title'")

    monkeypatch.setattr("agent_gtd.cli._do_add_item", _fake_do)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"acceptance_criteria": ["x"]}))
    )
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "add-item", "--stdin"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "title" in captured.err


# ---------------------------------------------------------------------------
# (j) main() dispatches both new subcommands
# ---------------------------------------------------------------------------


def test_main_update_item_dispatches(monkeypatch, capsys):
    """(j) main() with 'update-item' dispatches to _cmd_update_item."""
    called: dict[str, Any] = {}

    def _fake_cmd(args: Any) -> None:
        called["item_id"] = args.item_id
        called["status"] = args.status

    monkeypatch.setattr("agent_gtd.cli._cmd_update_item", _fake_cmd)
    monkeypatch.setattr(
        sys, "argv", ["agent-gtd", "update-item", "some-uuid", "--status", "ready"]
    )

    main()

    assert called["item_id"] == "some-uuid"
    assert called["status"] == "ready"


def test_main_add_item_dispatches(monkeypatch, capsys):
    """(j) main() with 'add-item' dispatches to _cmd_add_item."""
    called: dict[str, Any] = {}

    def _fake_cmd(args: Any) -> None:
        called["project"] = args.project
        called["status"] = args.status

    monkeypatch.setattr("agent_gtd.cli._cmd_add_item", _fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "add-item", "--project", "proj-uuid", "--status", "inbox"],
    )

    main()

    assert called["project"] == "proj-uuid"
    assert called["status"] == "inbox"


# ---------------------------------------------------------------------------
# Additional coverage tests — uncovered paths in cli.py
# ---------------------------------------------------------------------------


def test_load_json_payload_from_file(tmp_path):
    """_load_json_payload reads JSON from a file path."""
    from agent_gtd.cli import _load_json_payload

    f = tmp_path / "payload.json"
    f.write_text(json.dumps({"title": "Hello", "acceptance_criteria": ["step 1"]}))

    result = _load_json_payload(str(f), use_stdin=False)

    assert result["title"] == "Hello"
    assert result["acceptance_criteria"] == ["step 1"]


def test_load_json_payload_non_dict_raises_from_stdin(monkeypatch):
    """_load_json_payload raises ValueError when stdin JSON is an array."""
    import io

    from agent_gtd.cli import _load_json_payload

    monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2, 3]"))

    with pytest.raises(ValueError, match="list"):
        _load_json_payload(None, use_stdin=True)


def test_cmd_update_item_no_source_exits_nonzero(monkeypatch, capsys):
    """_cmd_update_item exits 1 when no --from-json/--stdin/--status/--build-engine."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_cmd_update_item_bad_json_exits_nonzero(monkeypatch, capsys):
    """_cmd_update_item exits 1 when stdin JSON is invalid."""
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("not-json{{{"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "update-item", "item-id", "--stdin"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


async def test_do_update_item_non_conflict_toolerror_propagates(monkeypatch):
    """_do_update_item re-raises non-conflict ToolError without retrying."""
    from fastmcp.exceptions import ToolError

    get_item_calls: list[int] = []

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            get_item_calls.append(1)
            return _make_item(id=item_id, version=1)

        async def update_item(
            self,
            user_id: str,
            item_id: str,
            *,
            version: int,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise ToolError(
                f"Item {item_id} is locked by rollout abc — dispatch is blocked"
            )

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())

    with pytest.raises(ToolError, match="locked by rollout"):
        await _do_update_item(
            "item-uuid",
            {"title": "X"},
            status=None,
            build_engine=None,
            explicit_version=None,
        )

    # get_item called once for initial version fetch; NOT again (no retry)
    assert len(get_item_calls) == 1


async def test_do_add_item_http_mode(monkeypatch):
    """_do_add_item uses HTTP path when AGENT_GTD_URL is set."""
    fake_id = str(uuid.uuid4())
    http_called: dict[str, Any] = {}

    async def _fake_http_post(
        base_url: str,
        api_key: str,
        *,
        title: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        http_called["base_url"] = base_url
        http_called["title"] = title
        http_called["kwargs"] = kwargs
        return {"id": fake_id}

    class _FakeBackend:
        async def login(self, api_key: str, agent_name: str) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-key")
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _FakeBackend())
    monkeypatch.setattr("agent_gtd.cli._http_post_create_item", _fake_http_post)

    result_id = await _do_add_item(
        project_id=None,
        payload={
            "title": "HTTP Item",
            "acceptance_criteria": ["ac1"],
        },
        status="ready",
        labels_cli=None,
    )

    assert result_id == fake_id
    assert http_called["title"] == "HTTP Item"
    assert http_called["kwargs"]["acceptance_criteria"] == ["ac1"]
    assert http_called["kwargs"]["status"] == "ready"


def test_cmd_add_item_with_labels_cli(monkeypatch, capsys):
    """_cmd_add_item passes comma-separated --labels to _do_add_item."""
    import io

    captured_labels: dict[str, Any] = {}
    fake_id = str(uuid.uuid4())

    async def _fake_do(
        project_id: Any, payload: Any, status: Any, labels_cli: Any
    ) -> str:
        captured_labels["labels"] = labels_cli
        return fake_id

    monkeypatch.setattr("agent_gtd.cli._do_add_item", _fake_do)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"title": "T"})))
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "add-item", "--stdin", "--labels", "foo,bar", "--labels", "baz"],
    )

    main()

    assert captured_labels["labels"] == ["foo", "bar", "baz"]
    captured = capsys.readouterr()
    assert fake_id in captured.out


def test_cmd_add_item_bad_json_exits_nonzero(monkeypatch, capsys):
    """_cmd_add_item exits 1 when stdin JSON is invalid."""
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("not-json"))
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "add-item", "--stdin"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


async def test_do_update_item_http_missing_api_key(monkeypatch):
    """_do_update_item raises RuntimeError when URL set but API key missing."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(RuntimeError, match="AGENT_GTD_API_KEY"):
        await _do_update_item(
            "item-id", {}, status="ready", build_engine=None, explicit_version=1
        )


async def test_do_add_item_http_missing_api_key(monkeypatch):
    """_do_add_item raises RuntimeError when URL set but API key missing."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.setenv("AGENT_GTD_URL", "http://example.com")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: LocalBackend())

    with pytest.raises(RuntimeError, match="AGENT_GTD_API_KEY"):
        await _do_add_item(
            project_id=None,
            payload={"title": "Test"},
            status=None,
            labels_cli=None,
        )


async def test_http_post_create_item_success():
    """_http_post_create_item posts to /api/items and returns the item dict."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from agent_gtd.cli import _http_post_create_item

    fake_item = {"id": str(uuid.uuid4()), "title": "Test Item"}

    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = fake_item

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _http_post_create_item(
            "http://example.com",
            "api-key",
            title="Test Item",
            acceptance_criteria=["step 1"],
            files_to_modify=[{"path": "a.py", "change": "add x"}],
            scope_out=["not this"],
            labels=["foo"],
            project_id="proj-id",
            build_engine="claude-code",
        )

    assert result == fake_item
    mock_client.post.assert_called_once()
    body = mock_client.post.call_args.kwargs["json"]
    assert body["title"] == "Test Item"
    assert body["acceptance_criteria"] == ["step 1"]
    assert body["build_engine"] == "claude-code"
    assert body["labels"] == ["foo"]


async def test_http_post_create_item_error():
    """_http_post_create_item raises ToolError on non-2xx response."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastmcp.exceptions import ToolError

    from agent_gtd.cli import _http_post_create_item

    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.json.return_value = {"detail": "Unauthorized"}
    mock_resp.text = "Unauthorized"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ToolError, match="Unauthorized"),
    ):
        await _http_post_create_item(
            "http://example.com",
            "api-key",
            title="Test",
        )


async def test_http_post_create_item_error_non_json_body():
    """_http_post_create_item uses resp.text when error body is not JSON."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastmcp.exceptions import ToolError

    from agent_gtd.cli import _http_post_create_item

    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.json.side_effect = ValueError("not JSON")
    mock_resp.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ToolError, match="Internal Server Error"),
    ):
        await _http_post_create_item(
            "http://example.com",
            "api-key",
            title="Test",
        )


# ---------------------------------------------------------------------------
# --wait flag tests for run-status and rollout-status
# ---------------------------------------------------------------------------


def test_cmd_run_status_no_wait_unchanged(monkeypatch, capsys):
    """Explicit regression: without --wait, run-status behaves exactly as before."""
    expected = _make_run(status="running")

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)

    # No SystemExit expected for non-wait success.
    _cmd_run_status(_run_status_args(run_id=expected["id"], wait=False))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "running"
    assert data["id"] == expected["id"]


def test_cmd_run_status_wait_running_then_success(monkeypatch, capsys):
    """--wait: running → running → success yields exit 0 and terminal JSON on stdout."""
    results = [
        _make_run(status="running"),
        _make_run(status="running"),
        _make_run(status="success"),
    ]
    call_count = 0

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        nonlocal call_count
        r = results[min(call_count, len(results) - 1)]
        call_count += 1
        return r

    async def _no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(_run_status_args(run_id="run-1", wait=True, poll_interval=0))

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "success"


def test_cmd_run_status_wait_to_failed(monkeypatch, capsys):
    """--wait: failed terminal state yields exit 2 and final JSON on stdout."""
    terminal = _make_run(status="failed")

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return terminal

    async def _no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(_run_status_args(run_id="run-1", wait=True, poll_interval=0))

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "failed"


def test_cmd_run_status_wait_exit_codes_non_success(monkeypatch, capsys):
    """--wait: each non-success terminal run state maps to exit 2."""
    for terminal_status in ("failed", "cancelled", "error", "timeout"):

        async def _fake_fetch(run_id: str, _s: str = terminal_status) -> dict[str, Any]:
            return _make_run(status=_s)

        async def _no_sleep(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        with pytest.raises(SystemExit) as exc_info:
            _cmd_run_status(
                _run_status_args(run_id="run-x", wait=True, poll_interval=0)
            )

        assert exc_info.value.code == 2, f"expected 2 for status={terminal_status}"


def test_cmd_run_status_wait_timeout_exit_124(monkeypatch, capsys):
    """--wait --timeout: exceeding client timeout exits 124 with last JSON on stderr."""
    # Use a near-zero timeout so the deadline is guaranteed to expire after the
    # first fetch (asyncio.sleep is patched to be instant).
    running = _make_run(status="running")

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return running

    async def _advancing_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        pass  # instant — real time passes, expiring the near-zero deadline

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _advancing_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(
            _run_status_args(
                run_id="run-1",
                wait=True,
                poll_interval=0,
                timeout=1e-9,  # nearly zero — expires immediately after first fetch
            )
        )

    assert exc_info.value.code == 124
    captured = capsys.readouterr()
    assert captured.out == ""
    # Last-fetched JSON must appear on stderr
    assert captured.err.strip()
    stderr_data = json.loads(captured.err.strip())
    assert stderr_data["status"] == "running"


def test_cmd_run_status_wait_transient_error_retried(monkeypatch, capsys):
    """--wait: a single transient fetch error is retried; wait continues to terminal."""
    results: list[Any] = [
        RuntimeError("connection reset"),  # transient error on first poll
        _make_run(status="success"),  # terminal on second poll
    ]
    call_count = 0

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        nonlocal call_count
        r = results[min(call_count, len(results) - 1)]
        call_count += 1
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]

    async def _no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(_run_status_args(run_id="run-1", wait=True, poll_interval=0))

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # Transient error message goes to stderr, final JSON to stdout.
    assert "transient" in captured.err.lower()
    data = json.loads(captured.out)
    assert data["status"] == "success"


def test_cmd_run_status_wait_not_found_aborts(monkeypatch, capsys):
    """--wait: a NotFoundError in the wait loop aborts with exit 1."""

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        raise NotFoundError("Run", run_id)

    async def _no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(_run_status_args(run_id="missing", wait=True, poll_interval=0))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


def test_cmd_rollout_status_no_wait_unchanged(monkeypatch, capsys):
    """Explicit regression: without --wait, rollout-status behaves exactly as before."""
    expected = _make_rollout(status="running")

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)

    _cmd_rollout_status(_rollout_status_args(rollout_id=expected["id"], wait=False))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "running"
    assert data["id"] == expected["id"]


def test_cmd_rollout_status_wait_running_then_completed(monkeypatch, capsys):
    """--wait: running → planning → completed yields exit 0 and terminal JSON."""
    results = [
        _make_rollout(status="running"),
        _make_rollout(status="planning"),
        _make_rollout(status="completed"),
    ]
    call_count = 0

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        nonlocal call_count
        r = results[min(call_count, len(results) - 1)]
        call_count += 1
        return r

    async def _no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_rollout_status(
            _rollout_status_args(rollout_id="rollout-1", wait=True, poll_interval=0)
        )

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "completed"


def test_cmd_rollout_status_wait_exit_codes_non_success(monkeypatch, capsys):
    """--wait: each non-success terminal rollout state maps to exit 2."""
    for terminal_status in ("failed", "halted", "cancelled"):

        async def _fake_fetch(
            rollout_id: str, _s: str = terminal_status
        ) -> dict[str, Any]:
            return _make_rollout(status=_s)

        async def _no_sleep(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)
        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        with pytest.raises(SystemExit) as exc_info:
            _cmd_rollout_status(
                _rollout_status_args(rollout_id="rollout-x", wait=True, poll_interval=0)
            )

        assert exc_info.value.code == 2, f"expected 2 for status={terminal_status}"


def test_cmd_rollout_status_wait_timeout_exit_124(monkeypatch, capsys):
    """--wait --timeout: exceeding client timeout exits 124 with last JSON on stderr."""
    pending = _make_rollout(status="running")

    async def _fake_fetch(rollout_id: str) -> dict[str, Any]:
        return pending

    async def _advancing_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        pass  # instant

    monkeypatch.setattr("agent_gtd.cli._fetch_rollout_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _advancing_sleep)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_rollout_status(
            _rollout_status_args(
                rollout_id="rollout-1",
                wait=True,
                poll_interval=0,
                timeout=1e-9,
            )
        )

    assert exc_info.value.code == 124
    captured = capsys.readouterr()
    assert captured.out == ""
    stderr_data = json.loads(captured.err.strip())
    assert stderr_data["status"] == "running"


def test_main_run_status_wait_flag_dispatches(monkeypatch, capsys):
    """main() with 'run-status <id> --wait' passes wait=True to _cmd_run_status."""
    called: dict[str, Any] = {}

    def _fake_cmd(args: argparse.Namespace) -> None:
        called["run_id"] = args.run_id
        called["wait"] = args.wait
        called["poll_interval"] = args.poll_interval
        called["timeout"] = args.timeout

    monkeypatch.setattr("agent_gtd.cli._cmd_run_status", _fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-gtd",
            "run-status",
            "my-run-id",
            "--wait",
            "--poll-interval",
            "60",
            "--timeout",
            "300",
        ],
    )

    main()

    assert called["run_id"] == "my-run-id"
    assert called["wait"] is True
    assert called["poll_interval"] == 60
    assert called["timeout"] == 300


def test_main_rollout_status_wait_flag_dispatches(monkeypatch, capsys):
    """main() with 'rollout-status --wait' passes wait=True to _cmd_rollout_status."""
    called: dict[str, Any] = {}

    def _fake_cmd(args: argparse.Namespace) -> None:
        called["rollout_id"] = args.rollout_id
        called["wait"] = args.wait

    monkeypatch.setattr("agent_gtd.cli._cmd_rollout_status", _fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "rollout-status", "my-rollout-id", "--wait"],
    )

    main()

    assert called["rollout_id"] == "my-rollout-id"
    assert called["wait"] is True


def test_poll_interval_floor_clamped_to_five(monkeypatch, capsys):
    """poll_interval values below 5 are clamped up to 5 inside _cmd_run_status."""
    # We verify the clamping by checking the sleep duration passed to asyncio.sleep.
    sleep_durations: list[float] = []
    terminal = _make_run(status="success")

    async def _fake_fetch(run_id: str) -> dict[str, Any]:
        return terminal

    async def _record_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        sleep_durations.append(delay)

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr("asyncio.sleep", _record_sleep)

    # The first fetch is terminal, so asyncio.sleep is never called.  Use a
    # non-terminal first result to force one sleep cycle.
    results = [_make_run(status="running"), _make_run(status="success")]
    call_count = 0

    async def _two_shot_fetch(run_id: str) -> dict[str, Any]:
        nonlocal call_count
        r = results[min(call_count, len(results) - 1)]
        call_count += 1
        return r

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _two_shot_fetch)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_run_status(
            _run_status_args(run_id="run-1", wait=True, poll_interval=1)
        )  # 1 < 5 → clamped to 5

    assert exc_info.value.code == 0
    # asyncio.sleep must have been called with ≥ 5 (clamped floor).
    assert sleep_durations, "asyncio.sleep should have been called at least once"
    assert all(d >= 5.0 for d in sleep_durations), (
        f"expected all sleep durations ≥ 5, got {sleep_durations}"
    )
