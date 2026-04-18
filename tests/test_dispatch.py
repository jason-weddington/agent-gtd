"""Tests for dispatch run CRUD API and remote dispatch worker."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _mock_dispatch_preflight():
    """Skip the dispatch service health check in all tests."""
    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
    ):
        yield


# ---------------------------------------------------------------------------
# Helper: configure per-user dispatch settings in the DB
# ---------------------------------------------------------------------------


async def _configure_dispatch(
    client: AsyncClient,
    headers: dict[str, str],
    url: str = "http://fake:8100",
    api_key: str = "test-key",
) -> None:
    """Configure dispatch settings for the authenticated user via the API."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"service_url": url, "service_api_key": api_key},
        headers=headers,
    )
    assert res.status_code == 200


async def _create_project_with_origin(
    client: AsyncClient,
    headers: dict[str, str],
    name: str = "Dispatch Project",
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


async def _create_item_in_project(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    title: str = "Test task",
) -> str:
    """Create an item in a project and return its ID."""
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": title},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


# --- Dispatch creation ---


async def test_dispatch_item(client: AsyncClient, auth_headers: dict[str, str]):
    """Dispatching an item creates a pending run."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    run = res.json()
    assert run["status"] == "pending"
    assert run["item_id"] == item_id
    assert run["project_id"] == project_id
    assert run["feature_branch"].startswith("feat/")
    assert run["max_turns"] == 100
    assert run["mode"] == "build"  # default mode


async def test_dispatch_sets_item_status_active(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatching an item sets the item status to active."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Verify initial status is not active
    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] != "active"

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201

    # Item status should now be active
    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "active"


async def test_dispatch_plan_mode(client: AsyncClient, auth_headers: dict[str, str]):
    """Dispatching with mode=plan stores and returns plan mode."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "plan"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    run = res.json()
    assert run["mode"] == "plan"


async def test_dispatch_custom_turns(client: AsyncClient, auth_headers: dict[str, str]):
    """Can specify custom max_turns."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"max_turns": 50},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 50


async def test_dispatch_duplicate_blocked(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Cannot dispatch the same item twice while a run is active."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 409


async def test_dispatch_no_git_origin(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatch fails if project has no git_origin."""
    res = await client.post(
        "/api/projects",
        json={"name": "No Git"},
        headers=auth_headers,
    )
    project_id = res.json()["id"]
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_dispatch_no_project(client: AsyncClient, auth_headers: dict[str, str]):
    """Dispatch fails if item has no project."""
    # Create item without project (inbox)
    res = await client.post(
        "/api/inbox",
        json={"title": "Orphan task"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 404


# --- Owner-only dispatch guard ---


async def test_dispatch_owner_can_dispatch(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project owner can dispatch agents on their own items."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201


async def test_dispatch_member_cannot_dispatch(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project member (non-owner) gets 403 when attempting dispatch."""
    # User A creates project and item
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Register User B
    res_b = await client.post(
        "/api/auth/register",
        json={"email": "userb@example.com", "password": "passb"},
    )
    assert res_b.status_code == 201
    user_b_headers = {"Authorization": f"Bearer {res_b.json()['token']}"}
    user_b_id = res_b.json()["user"]["id"]

    # Add User B as a project member
    from datetime import UTC, datetime

    from agent_gtd.database import get_db

    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_b_id,
        datetime.now(UTC).isoformat(),
    )

    # User B attempts to dispatch → 403
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=user_b_headers,
    )
    assert res.status_code == 403
    assert "owner" in res.json()["detail"].lower()


# --- Run listing ---


async def test_list_item_runs(client: AsyncClient, auth_headers: dict[str, str]):
    """List runs for an item."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # No runs yet
    res = await client.get(f"/api/items/{item_id}/runs", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []

    # Create one
    await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )

    res = await client.get(f"/api/items/{item_id}/runs", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1


async def test_list_runs_multi_status(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """GET /api/runs?status=pending,running returns runs with either status."""
    from agent_gtd.database import get_db

    project_id = await _create_project_with_origin(client, auth_headers)
    item_a = await _create_item_in_project(client, auth_headers, project_id, "Task A")
    item_b = await _create_item_in_project(client, auth_headers, project_id, "Task B")

    # Dispatch both — they start as pending
    res_a = await client.post(
        f"/api/items/{item_a}/dispatch", json={}, headers=auth_headers
    )
    run_a_id = res_a.json()["id"]

    res_b = await client.post(
        f"/api/items/{item_b}/dispatch", json={}, headers=auth_headers
    )
    run_b_id = res_b.json()["id"]

    # Manually advance run_b to "running"
    db = await get_db()
    from datetime import UTC, datetime

    await db.execute(
        "UPDATE claude_runs SET status = 'running', started_at = $1 WHERE id = $2",
        datetime.now(UTC).isoformat(),
        run_b_id,
    )

    # CSV filter should return both
    res = await client.get(
        "/api/runs", params={"status": "pending,running"}, headers=auth_headers
    )
    assert res.status_code == 200
    run_ids = {r["id"] for r in res.json()}
    assert run_a_id in run_ids
    assert run_b_id in run_ids

    # Single-status filter still works
    res = await client.get(
        "/api/runs", params={"status": "pending"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert all(r["status"] == "pending" for r in res.json())

    res = await client.get(
        "/api/runs", params={"status": "running"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert all(r["status"] == "running" for r in res.json())


async def test_list_runs_cross_item(client: AsyncClient, auth_headers: dict[str, str]):
    """GET /api/runs lists runs across all items."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_a = await _create_item_in_project(client, auth_headers, project_id, "Task A")
    item_b = await _create_item_in_project(client, auth_headers, project_id, "Task B")

    # Dispatch both
    await client.post(f"/api/items/{item_a}/dispatch", json={}, headers=auth_headers)
    await client.post(f"/api/items/{item_b}/dispatch", json={}, headers=auth_headers)

    # Cross-item list
    res = await client.get("/api/runs", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2

    # Filter by item
    res = await client.get(
        "/api/runs", params={"item_id": item_a}, headers=auth_headers
    )
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 1
    assert runs[0]["item_id"] == item_a


async def test_list_runs_by_project_id(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """GET /api/runs?project_id=X returns only runs for that project."""
    project_a = await _create_project_with_origin(client, auth_headers, "Project A")
    project_b = await _create_project_with_origin(client, auth_headers, "Project B")

    item_a = await _create_item_in_project(client, auth_headers, project_a, "Task in A")
    item_b = await _create_item_in_project(client, auth_headers, project_b, "Task in B")

    # Dispatch one item per project
    await client.post(f"/api/items/{item_a}/dispatch", json={}, headers=auth_headers)
    await client.post(f"/api/items/{item_b}/dispatch", json={}, headers=auth_headers)

    # Filter by project A — should only see the run for item_a
    res = await client.get(
        "/api/runs", params={"project_id": project_a}, headers=auth_headers
    )
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 1
    assert runs[0]["project_id"] == project_a
    assert runs[0]["item_id"] == item_a

    # Filter by project B — should only see the run for item_b
    res = await client.get(
        "/api/runs", params={"project_id": project_b}, headers=auth_headers
    )
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 1
    assert runs[0]["project_id"] == project_b
    assert runs[0]["item_id"] == item_b


# --- Get single run ---


async def test_get_run(client: AsyncClient, auth_headers: dict[str, str]):
    """Get a single run by ID."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == run_id


async def test_get_run_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    """404 for nonexistent run."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.get(f"/api/runs/{fake_id}", headers=auth_headers)
    assert res.status_code == 404


# --- Cancel ---


async def test_cancel_run(client: AsyncClient, auth_headers: dict[str, str]):
    """Cancel an active run."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    res = await client.delete(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.status_code == 204

    # Verify it's cancelled
    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "cancelled"

    # Can dispatch again after cancel
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201


async def test_cancel_nonexistent_run(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """404 for cancelling nonexistent run."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.delete(f"/api/runs/{fake_id}", headers=auth_headers)
    assert res.status_code == 404


# --- Reconciliation ---


async def test_reconcile_no_remote_id(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Runs without remote_run_id are marked failed on reconciliation."""
    from agent_gtd.dispatch_worker import reconcile_active_runs

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]
    assert res.json()["status"] == "pending"

    count = await reconcile_active_runs()
    assert count >= 1

    # No remote_run_id → never reached the dispatch service
    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "before dispatch completed" in res.json()["error_msg"]


async def test_reconcile_remote_terminal(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    monkeypatch,
):
    """Runs with a remote_run_id that finished are synced to the terminal status."""
    import agent_gtd.dispatch_worker as dw
    from agent_gtd.database import get_db
    from agent_gtd.dispatch_worker import reconcile_active_runs
    from agent_gtd.services.settings_service import set_user_setting

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    # Simulate: run was dispatched and has a remote_run_id, status is "running"
    db = await get_db()
    await db.execute(
        "UPDATE claude_runs SET status = 'running', remote_run_id = 'remote-123'"
        " WHERE id = $1",
        run_id,
    )

    # Set up dispatch config for the test user so reconcile can poll
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Mock the remote poll to return "succeeded"
    async def mock_poll(client, remote_id, *, url, api_key):
        return {"status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    count = await reconcile_active_runs()
    assert count >= 1

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "success"


async def test_reconcile_remote_still_running(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    monkeypatch,
):
    """Runs still active on remote are resumed (not marked failed)."""
    import agent_gtd.dispatch_worker as dw
    from agent_gtd.database import get_db
    from agent_gtd.dispatch_worker import reconcile_active_runs
    from agent_gtd.services.settings_service import set_user_setting

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    # Simulate: run was dispatched and is running remotely
    db = await get_db()
    await db.execute(
        "UPDATE claude_runs SET status = 'running', remote_run_id = 'remote-456'"
        " WHERE id = $1",
        run_id,
    )

    # Set up dispatch config for the test user
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Mock the remote poll to return "running"
    async def mock_poll(client, remote_id, *, url, api_key):
        return {"status": "running"}

    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    # Patch _resume_polling to just record the call (don't actually poll forever)
    resumed = []

    async def mock_resume(db, run, remote_run_id, *, url, api_key):
        resumed.append(remote_run_id)

    monkeypatch.setattr(dw, "_resume_polling", mock_resume)

    count = await reconcile_active_runs()
    assert count >= 1

    # Run should still be "running" — not marked as failed
    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "running"

    # Resume polling was called
    assert "remote-456" in resumed


# --- Worker execute_run tests (remote dispatch) ---


async def test_execute_run_no_dispatch_config(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """execute_run fails gracefully when user has no dispatch config."""
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # No dispatch config in DB — execute_run should fail immediately
    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "not configured" in res.json()["error_msg"].lower()


async def test_execute_run_remote_dispatch_fails(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
):
    """execute_run marks run as failed when remote dispatch service errors."""
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_user_setting

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()

    # Configure dispatch to an unreachable URL
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:9999")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "dispatch service" in res.json()["error_msg"].lower()


async def test_execute_run_success(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """execute_run marks run as success when remote dispatch succeeds."""
    import agent_gtd.dispatch_worker as dw
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)  # fast polling for tests

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()

    # Configure dispatch config for the test user
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Mock the remote dispatch functions directly
    poll_count = 0

    async def mock_dispatch_to_remote(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude",
        agent_name="",
    ):
        return {"id": "remote-123", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        nonlocal poll_count
        poll_count += 1
        if poll_count >= 2:
            return {"id": "remote-123", "status": "succeeded", "error": None}
        return {"id": "remote-123", "status": "running", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch_to_remote)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "success"
    assert res.json()["finished_at"] is not None
    assert res.json()["mode"] == "build"


async def test_execute_run_remote_failure(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """execute_run maps remote failure to local failed status."""
    import agent_gtd.dispatch_worker as dw
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()

    # Configure dispatch config for the test user
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    async def mock_dispatch_to_remote(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude",
        agent_name="",
    ):
        return {"id": "remote-456", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return {
            "id": "remote-456",
            "status": "failed",
            "error": "Reached max turns (50)",
        }

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch_to_remote)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "max turns" in res.json()["error_msg"].lower()


# --- Preflight check tests ---


async def test_dispatch_service_unreachable(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """503 when dispatch service is unreachable."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        side_effect=HTTPException(
            status_code=503, detail="Dispatch service is unreachable"
        ),
    ):
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={},
            headers=auth_headers,
        )
    assert res.status_code == 503
    assert "unreachable" in res.json()["detail"].lower()


async def test_dispatch_service_not_configured(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """503 when user has no dispatch config."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        side_effect=HTTPException(
            status_code=503, detail="Dispatch service not configured"
        ),
    ):
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={},
            headers=auth_headers,
        )
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()


# --- Per-user dispatch config integration ---


async def test_dispatch_no_config_marks_run_failed(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """User with no dispatch config gets run marked failed immediately."""
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()
    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # No dispatch config — run should be marked failed with a clear message
    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    data = res.json()
    assert data["status"] == "failed"
    assert "dispatch" in data["error_msg"].lower()
    assert "not configured" in data["error_msg"].lower()


async def test_configure_and_dispatch(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """User A configures dispatch via PATCH, then dispatches successfully."""
    import agent_gtd.dispatch_worker as dw
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    # Configure dispatch via the settings API
    await _configure_dispatch(client, auth_headers)

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    run_id = res.json()["id"]

    db = await get_db()
    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Mock remote dispatch to return success
    async def mock_dispatch(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude",
        agent_name="",
    ):
        return {"id": "remote-ok", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return {"id": "remote-ok", "status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "success"
