"""Integration tests for the dispatch_rollout route and manage-mode worker flow.

Covers:
- POST /api/rollouts/{id}/dispatch → 201 RunResponse with item_id=null
- Rollout transitions pending → running on dispatch
- 409 when rollout is not pending
- _process_run skips svc_get_item for manage-mode runs
- execute_run omits item_id from the outgoing /dispatch payload for manage-mode
- execute_run includes item_id for build-mode (regression guard)
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _create_project_with_origin(
    client: AsyncClient,
    headers: dict[str, str],
    name: str = "Dispatch Rollout Project",
    git_origin: str = "git@github.com:test/repo.git",
) -> str:
    """Create a project with git_origin and return its ID."""
    res = await client.post(
        "/api/projects",
        json={"name": name, "git_origin": git_origin},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _insert_pending_rollout(db: Any, user_id: str, project_id: str) -> str:
    """Directly insert an autonomous_rollout row with status='pending'."""
    rollout_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        user_id,
        "pending",
        now,
        now,
    )
    return rollout_id


# ---------------------------------------------------------------------------
# HTTP integration tests — POST /api/rollouts/{id}/dispatch
# ---------------------------------------------------------------------------


async def test_dispatch_rollout_returns_201_with_null_item_id(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """POST /api/rollouts/{id}/dispatch returns 201 with item_id=null (Bug 1 fix)."""
    from agent_gtd.database import get_db

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)
    rollout_id = await _insert_pending_rollout(db, user_id, project_id)

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )

    assert res.status_code == 201, res.text
    run = res.json()
    assert run["item_id"] is None
    assert run["status"] == "pending"
    assert run["mode"] == "manage"
    assert run["rollout_id"] == rollout_id
    assert run["project_id"] == project_id


async def test_dispatch_rollout_transitions_to_running(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """Rollout transitions from pending → running after dispatch."""
    from agent_gtd.database import get_db

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)
    rollout_id = await _insert_pending_rollout(db, user_id, project_id)

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    assert row["status"] == "running"


async def test_dispatch_rollout_409_when_not_pending(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """Returns 409 when rollout is already running (not pending)."""
    from agent_gtd.database import get_db

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)

    rollout_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        user_id,
        "running",  # already running — not dispatchable
        now,
        now,
    )

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 409


async def test_dispatch_rollout_404_when_missing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Returns 404 when rollout does not exist."""
    res = await client.post(
        f"/api/rollouts/{uuid.uuid4()}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_dispatch_rollout_creates_run_row(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """A claude_runs row with item_id=NULL is created on dispatch (Bug 2 fix)."""
    from agent_gtd.database import get_db

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)
    rollout_id = await _insert_pending_rollout(db, user_id, project_id)

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 201

    run_id = res.json()["id"]
    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None
    assert row["item_id"] is None
    assert row["mode"] == "manage"
    assert str(row["rollout_id"]) == rollout_id


async def test_dispatch_rollout_workspace_project_succeeds(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """dispatch_rollout_run on a workspace project returns 201 (guard removed).

    Creates a workspace project via API, inserts a pending rollout, dispatches,
    and asserts the manage-mode run row and rollout transition.
    """
    from agent_gtd.database import get_db

    db = await get_db()

    # Create a workspace project via API (requires non-empty repos, git_origin absent)
    res = await client.post(
        "/api/projects",
        json={
            "name": "Workspace Rollout Project",
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/example/repo-a.git"],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    project_id = res.json()["id"]

    rollout_id = await _insert_pending_rollout(db, user_id, project_id)

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    # claude_runs row: item_id is None, mode is manage, rollout_id matches
    run_id = res.json()["id"]
    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert run_row is not None
    assert run_row["item_id"] is None
    assert run_row["mode"] == "manage"
    assert str(run_row["rollout_id"]) == rollout_id

    # Rollout transitions to running
    rollout_row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout_row is not None
    assert rollout_row["status"] == "running"


async def test_dispatch_rollout_workspace_empty_repos_raises(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """dispatch_rollout_run on a workspace project with empty repos returns 404.

    Inserts the project directly into the DB (bypassing API validation that
    requires non-empty repos) to exercise the NotFoundError guard.
    """
    import uuid as _uuid

    from agent_gtd.database import encode_json_list, get_db

    db = await get_db()

    # Insert workspace project with empty workspace_repos directly — bypasses
    # the API-level validation so we can test the service-level guard.
    project_id = str(_uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO projects"
        " (id, user_id, name, repo_mode, workspace_repos, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        project_id,
        user_id,
        "Empty Workspace Project",
        "workspace",
        encode_json_list([]),
        now,
        now,
    )

    rollout_id = await _insert_pending_rollout(db, user_id, project_id)

    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert "has no repos configured" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Worker unit tests — _process_run manage-mode skips svc_get_item (Bug 3 fix)
# ---------------------------------------------------------------------------


def _make_db_mock_for_process_run(run_dict: dict[str, Any]) -> MagicMock:
    """DB mock that returns run_dict from fetchrow and no-ops execute."""
    db = MagicMock()

    async def fetchrow(sql: str, *args: object) -> dict[str, object] | None:
        if "claude_runs" in sql:
            return run_dict
        if "FROM projects" in sql:
            return {"user_id": run_dict.get("user_id", "owner-id")}
        return None

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    return db


@pytest.mark.asyncio
async def test_process_run_manage_mode_skips_item_fetch() -> None:
    """_process_run passes item=None to execute_run for manage-mode (Bug 3 fix)."""
    rollout_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    run_dict = {
        "id": run_id,
        "item_id": None,
        "project_id": project_id,
        "user_id": user_id,
        "status": "pending",
        "mode": "manage",
        "max_turns": 100,
        "rollout_id": rollout_id,
        "feature_branch": f"manage/{rollout_id[:8]}",
        "workspace_dir": "",
        "error_msg": "",
        "started_at": None,
        "finished_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    }

    fake_db = _make_db_mock_for_process_run(run_dict)

    execute_run_calls: list[tuple[Any, ...]] = []

    async def fake_execute_run(
        db: Any,
        run: dict[str, Any],
        item: dict[str, Any] | None,
        project: dict[str, Any],
    ) -> None:
        execute_run_calls.append((run, item, project))

    svc_get_item_calls: list[Any] = []

    async def fake_svc_get_item(db: Any, user_id: str, item_id: str) -> dict:
        svc_get_item_calls.append(item_id)
        return {}

    async def fake_svc_get_project(db: Any, user_id: str, project_id: str) -> dict:
        return {"id": project_id}

    # _process_run uses local imports inside the function, so we must patch
    # the names in the modules where they are defined (not in dispatch_worker).
    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=fake_db)),
        patch("agent_gtd.database.row_to_dict", side_effect=lambda r: r),
        patch("agent_gtd.services.item_service.get_item", new=fake_svc_get_item),
        patch(
            "agent_gtd.services.project_service.get_project",
            new=fake_svc_get_project,
        ),
        patch("agent_gtd.dispatch_worker.execute_run", new=fake_execute_run),
    ):
        from agent_gtd.dispatch_worker import _process_run

        await _process_run(run_id)

    # execute_run was called with item=None
    assert len(execute_run_calls) == 1
    _called_run, called_item, _called_project = execute_run_calls[0]
    assert called_item is None
    # svc_get_item was NOT called
    assert len(svc_get_item_calls) == 0


# ---------------------------------------------------------------------------
# Worker unit tests — execute_run dispatch payload (Bug 3 fix, wire contract)
# ---------------------------------------------------------------------------


def _make_db_mock_for_execute(project_owner_id: str) -> MagicMock:
    """Minimal DB mock for execute_run tests."""
    db = MagicMock()

    async def fetchrow(sql: str, *args: object) -> dict[str, object] | None:
        if "FROM projects" in sql:
            return {"user_id": project_owner_id}
        return None

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    return db


def _make_settings_mock() -> tuple[Any, Any, Any]:
    """Return (fake_get_dispatch_hosts, fake_pick_dispatch_host, fake_get_setting)."""

    async def fake_get_dispatch_hosts(db_arg: Any, uid: str) -> list[dict[str, Any]]:
        return [{"url": "http://fake:8100", "api_key": "test-key", "label": "default"}]

    async def fake_pick_dispatch_host(
        hosts: list[dict[str, Any]],
        *,
        engine: str,
        agent_name: Any,
        target_host_id: str | None = None,
        exclude_urls: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        return {"url": "http://fake:8100", "api_key": "test-key"}

    async def fake_get_setting(db_arg: Any, key: str) -> str | None:
        return {"dispatch.engine": "claude-code"}.get(key)

    return fake_get_dispatch_hosts, fake_pick_dispatch_host, fake_get_setting


@pytest.mark.asyncio
async def test_execute_run_manage_mode_omits_item_id_from_dispatch() -> None:
    """manage-mode execute_run omits item_id from the outgoing /dispatch payload."""
    from agent_gtd.dispatch_worker import execute_run

    rollout_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())

    run = {
        "id": run_id,
        "item_id": None,
        "project_id": "proj-manage",
        "user_id": "caller-id",
        "max_turns": 50,
        "mode": "manage",
        "rollout_id": rollout_id,
    }
    db = _make_db_mock_for_execute(owner_id)

    # Capture the args passed to _dispatch_to_remote
    captured_calls: list[tuple[Any, ...]] = []

    async def capture_dispatch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured_calls.append((args, kwargs))
        return {"id": "remote-run-manage"}

    (
        fake_get_dispatch_hosts,
        fake_pick_dispatch_host,
        fake_get_setting,
    ) = _make_settings_mock()

    with (
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=fake_get_dispatch_hosts,
        ),
        patch(
            "agent_gtd.services.dispatch_router.pick_dispatch_host",
            new=fake_pick_dispatch_host,
        ),
        patch(
            "agent_gtd.services.settings_service.get_setting",
            new=fake_get_setting,
        ),
        patch(
            "agent_gtd.dispatch_worker._dispatch_to_remote",
            new=AsyncMock(side_effect=capture_dispatch),
        ),
        # Immediately return terminal status so the poll loop exits on first iteration
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(return_value={"status": "succeeded"}),
        ),
        patch("asyncio.sleep", new=AsyncMock()),  # skip POLL_INTERVAL wait
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        await execute_run(db, run, item=None, project={})

    # _dispatch_to_remote was called once
    assert len(captured_calls) == 1
    call_args, call_kwargs = captured_calls[0]
    # item_id is the 2nd positional arg (after client)
    dispatched_item_id = (
        call_args[1] if len(call_args) > 1 else call_kwargs.get("item_id")
    )
    assert dispatched_item_id is None, (
        f"manage-mode should pass item_id=None, got: {dispatched_item_id}"
    )
    assert call_kwargs.get("rollout_id") == rollout_id
    assert call_args[3] == "manage"  # mode positional arg


@pytest.mark.asyncio
async def test_execute_run_build_mode_includes_item_id() -> None:
    """build-mode execute_run still sends item_id in the outgoing payload."""
    from agent_gtd.dispatch_worker import execute_run

    item_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())

    run = {
        "id": run_id,
        "item_id": item_id,
        "project_id": "proj-build",
        "user_id": "caller-id",
        "max_turns": 50,
        "mode": "build",
        "rollout_id": None,
    }
    db = _make_db_mock_for_execute(owner_id)

    captured_calls: list[tuple[Any, ...]] = []

    async def capture_dispatch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured_calls.append((args, kwargs))
        return {"id": "remote-run-build"}

    (
        fake_get_dispatch_hosts,
        fake_pick_dispatch_host,
        fake_get_setting,
    ) = _make_settings_mock()

    with (
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=fake_get_dispatch_hosts,
        ),
        patch(
            "agent_gtd.services.dispatch_router.pick_dispatch_host",
            new=fake_pick_dispatch_host,
        ),
        patch(
            "agent_gtd.services.settings_service.get_setting",
            new=fake_get_setting,
        ),
        patch(
            "agent_gtd.dispatch_worker._dispatch_to_remote",
            new=AsyncMock(side_effect=capture_dispatch),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(return_value={"status": "succeeded"}),
        ),
        patch("asyncio.sleep", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        await execute_run(db, run, item={}, project={})

    assert len(captured_calls) == 1
    call_args, call_kwargs = captured_calls[0]
    dispatched_item_id = (
        call_args[1] if len(call_args) > 1 else call_kwargs.get("item_id")
    )
    assert dispatched_item_id == item_id, (
        f"build-mode should pass item_id={item_id}, got: {dispatched_item_id}"
    )
