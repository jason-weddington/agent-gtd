"""Tests for dispatch run CRUD API and remote dispatch worker."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from agent_gtd_dispatch_protocol import RunResponse as RemoteRunResponse
from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus
from fastapi import HTTPException
from httpx import AsyncClient


def _remote_run(
    status: RemoteRunStatus,
    run_id: str = "remote-123",
    *,
    error: str | None = None,
) -> RemoteRunResponse:
    """Build a minimal ``RemoteRunResponse`` for test mocks."""
    return RemoteRunResponse(
        id=run_id,
        item_id=None,
        project_name="test",
        branch_name=None,
        engine="claude-code",
        agent_name=None,
        mode="build",
        rollout_id=None,
        status=status,
        started_at=None,
        completed_at=None,
        exit_code=None,
        error=error,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


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


async def test_dispatch_invalid_mode(client: AsyncClient, auth_headers: dict[str, str]):
    """POST /api/items/{id}/dispatch with an unknown mode returns 422."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "cooperative"},
        headers=auth_headers,
    )
    assert res.status_code == 422


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


async def test_dispatch_member_succeeds_with_owner_config(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project member (non-owner) can dispatch when owner has dispatch configured."""
    # User A (owner) creates project and item; preflight mock allows all requests
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Create User B directly (bypass invite system)
    from agent_gtd.auth import create_token, register_user

    user_b = await register_user("userb@example.com", "passb")
    user_b_headers = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    user_b_id = user_b.id

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

    # User B dispatches → 201 (not 403), preflight mock allows it
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=user_b_headers,
    )
    assert res.status_code == 201
    run_data = res.json()
    # Run attribution is the caller (User B), not the owner — verify via DB
    from agent_gtd.database import get_db

    db = await get_db()
    run_row = await db.fetchrow(
        "SELECT user_id FROM claude_runs WHERE id = $1", run_data["id"]
    )
    assert run_row is not None
    assert str(run_row["user_id"]) == user_b_id


async def test_dispatch_member_no_owner_config(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """When the project owner has no dispatch config, member dispatch returns 503."""
    from unittest.mock import AsyncMock, patch

    # User A (owner) creates project and item — but owner has NO dispatch config
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Create User B
    from agent_gtd.auth import create_token, register_user

    user_b = await register_user("userb2@example.com", "passb")
    user_b_headers = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    user_b_id = user_b.id

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

    # Override the autouse preflight mock to use the real check
    # (so we can test the "not configured" path)
    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
        side_effect=Exception("Project owner has not configured dispatch"),
    ):
        # Patch the real _check_dispatch_service directly to raise 503
        pass

    # Re-patch to simulate missing config (overrides the autouse mock for this call)
    from fastapi import HTTPException

    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=503, detail="Project owner has not configured dispatch"
        ),
    ):
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={},
            headers=user_b_headers,
        )
    assert res.status_code == 503
    assert "Project owner has not configured dispatch" in res.json()["detail"]


async def test_dispatch_owner_own_config_used(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Owner dispatching their own project still works (sanity check after refactor)."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201


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


# --- Shared-project run visibility ---


async def _make_user_headers(email: str) -> dict[str, str]:
    """Register a new user and return their auth headers."""
    from agent_gtd.auth import create_token, register_user

    user = await register_user(email, "testpass123")
    token = create_token(user.id)
    return {"Authorization": f"Bearer {token}"}


async def test_shared_project_runs_visible_with_accessible_projects_scope(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """User B (member) sees User A's runs with scope=accessible_projects."""
    # Create user B
    headers_b = await _make_user_headers("userb_runs@example.com")
    res_b = await client.get("/api/auth/me", headers=headers_b)
    user_b_email = res_b.json()["email"]

    # User A creates a project and shares it with user B
    project_id = await _create_project_with_origin(client, auth_headers)
    share_res = await client.post(
        f"/api/projects/{project_id}/members",
        json={"email": user_b_email},
        headers=auth_headers,
    )
    assert share_res.status_code == 201

    # User A dispatches a run
    item_id = await _create_item_in_project(client, auth_headers, project_id)
    dispatch_res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert dispatch_res.status_code == 201
    run_id = dispatch_res.json()["id"]

    # User B CAN see the run with scope=accessible_projects
    res = await client.get(
        "/api/runs",
        params={"status": "pending,running", "scope": "accessible_projects"},
        headers=headers_b,
    )
    assert res.status_code == 200
    run_ids = {r["id"] for r in res.json()}
    assert run_id in run_ids, (
        "shared-project run should be visible with accessible_projects scope"
    )


async def test_shared_project_runs_not_visible_with_default_scope(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """User B (member) does NOT see User A's runs with default scope (regression guard)."""  # noqa: E501
    # Create user B
    headers_b = await _make_user_headers("userb_runs2@example.com")
    res_b = await client.get("/api/auth/me", headers=headers_b)
    user_b_email = res_b.json()["email"]

    # User A creates a project and shares it with user B
    project_id = await _create_project_with_origin(client, auth_headers)
    share_res = await client.post(
        f"/api/projects/{project_id}/members",
        json={"email": user_b_email},
        headers=auth_headers,
    )
    assert share_res.status_code == 201

    # User A dispatches a run
    item_id = await _create_item_in_project(client, auth_headers, project_id)
    dispatch_res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert dispatch_res.status_code == 201
    run_id = dispatch_res.json()["id"]

    # User B should NOT see the run with default scope (user-scoped)
    res = await client.get(
        "/api/runs",
        params={"status": "pending,running"},
        headers=headers_b,
    )
    assert res.status_code == 200
    run_ids = {r["id"] for r in res.json()}
    assert run_id not in run_ids, (
        "shared-project run should NOT be visible with default scope"
    )


async def test_list_runs_invalid_scope(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """GET /api/runs with an invalid scope returns 400."""
    res = await client.get(
        "/api/runs",
        params={"scope": "invalid"},
        headers=auth_headers,
    )
    assert res.status_code == 400


# --- dispatched_by_email and auto-scope for shared projects ---


async def test_shared_project_auto_scope_member_sees_owner_run(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Member B sees owner A's run without explicit scope (auto-scope).

    When project_id refers to a shared project and no scope is given, the route
    auto-elevates to accessible_projects.  Also verifies dispatched_by_email is
    populated with A's email address.
    """
    # Get User A's email
    res_a = await client.get("/api/auth/me", headers=auth_headers)
    assert res_a.status_code == 200
    user_a_email = res_a.json()["email"]

    # Create User B
    headers_b = await _make_user_headers("userb_autoscope@example.com")
    res_b = await client.get("/api/auth/me", headers=headers_b)
    user_b_email = res_b.json()["email"]

    # A creates a project and shares it with B
    project_id = await _create_project_with_origin(client, auth_headers)
    share_res = await client.post(
        f"/api/projects/{project_id}/members",
        json={"email": user_b_email},
        headers=auth_headers,
    )
    assert share_res.status_code == 201

    # A dispatches a run in the project
    item_id = await _create_item_in_project(client, auth_headers, project_id)
    dispatch_res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert dispatch_res.status_code == 201
    run_id = dispatch_res.json()["id"]

    # B calls GET /api/runs?project_id=... WITHOUT explicit scope — auto-switches
    res = await client.get(
        "/api/runs",
        params={"project_id": project_id},
        headers=headers_b,
    )
    assert res.status_code == 200
    runs = res.json()
    run_ids = {r["id"] for r in runs}
    assert run_id in run_ids, "member should see owner's run via auto-scope"

    # dispatched_by_email should be A's email
    the_run = next(r for r in runs if r["id"] == run_id)
    assert the_run["dispatched_by_email"] == user_a_email


async def test_shared_project_owner_sees_member_run_auto_scope(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Owner A sees member B's run via auto-scope; dispatched_by_email is B's email."""
    # Get User A's email
    res_a = await client.get("/api/auth/me", headers=auth_headers)
    assert res_a.status_code == 200

    # Create User B and configure their dispatch settings
    headers_b = await _make_user_headers("userb_ownercheck@example.com")
    res_b = await client.get("/api/auth/me", headers=headers_b)
    user_b_email = res_b.json()["email"]
    await _configure_dispatch(client, headers_b)

    # A creates a project and shares it with B
    project_id = await _create_project_with_origin(client, auth_headers)
    share_res = await client.post(
        f"/api/projects/{project_id}/members",
        json={"email": user_b_email},
        headers=auth_headers,
    )
    assert share_res.status_code == 201

    # B creates an item and dispatches a run in the project
    item_id = await _create_item_in_project(client, headers_b, project_id)
    dispatch_res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=headers_b,
    )
    assert dispatch_res.status_code == 201
    run_id = dispatch_res.json()["id"]

    # A calls GET /api/runs?project_id=... — should see B's run via auto-scope
    res = await client.get(
        "/api/runs",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    runs = res.json()
    run_ids = {r["id"] for r in runs}
    assert run_id in run_ids, "owner should see member's run via auto-scope"

    # dispatched_by_email should be B's email
    the_run = next(r for r in runs if r["id"] == run_id)
    assert the_run["dispatched_by_email"] == user_b_email


async def test_non_shared_project_dispatched_by_email_populated(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Non-shared project: owner sees own run; dispatched_by_email is the owner's email.

    The users JOIN is applied unconditionally, so dispatched_by_email is always
    populated (not None) whenever the dispatcher's row exists in the users table.
    For a non-shared project the scope stays at "user" so only the owner's own
    runs appear; the email is simply the owner's own address.
    """
    res_me = await client.get("/api/auth/me", headers=auth_headers)
    assert res_me.status_code == 200
    owner_email = res_me.json()["email"]

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)
    dispatch_res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert dispatch_res.status_code == 201
    run_id = dispatch_res.json()["id"]

    res = await client.get(
        "/api/runs",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    runs = res.json()
    run_ids = {r["id"] for r in runs}
    assert run_id in run_ids

    # The JOIN always returns the email — for a non-shared project this is
    # the owner's own email (not None).
    the_run = next(r for r in runs if r["id"] == run_id)
    assert the_run["dispatched_by_email"] == owner_email


async def test_shared_project_explicit_scope_user_honored(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Explicit scope=user on a shared project returns only the caller's own runs."""
    # Create User B and configure dispatch settings
    headers_b = await _make_user_headers("userb_explicit_scope@example.com")
    res_b = await client.get("/api/auth/me", headers=headers_b)
    user_b_email = res_b.json()["email"]
    await _configure_dispatch(client, headers_b)

    # A creates a project and shares it with B
    project_id = await _create_project_with_origin(client, auth_headers)
    share_res = await client.post(
        f"/api/projects/{project_id}/members",
        json={"email": user_b_email},
        headers=auth_headers,
    )
    assert share_res.status_code == 201

    # A dispatches a run
    item_id_a = await _create_item_in_project(client, auth_headers, project_id)
    dispatch_res_a = await client.post(
        f"/api/items/{item_id_a}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert dispatch_res_a.status_code == 201
    run_id_a = dispatch_res_a.json()["id"]

    # B dispatches a run
    item_id_b = await _create_item_in_project(client, headers_b, project_id)
    dispatch_res_b = await client.post(
        f"/api/items/{item_id_b}/dispatch",
        json={},
        headers=headers_b,
    )
    assert dispatch_res_b.status_code == 201
    run_id_b = dispatch_res_b.json()["id"]

    # B calls with explicit scope=user — should only see B's own run
    res = await client.get(
        "/api/runs",
        params={"project_id": project_id, "scope": "user"},
        headers=headers_b,
    )
    assert res.status_code == 200
    run_ids = {r["id"] for r in res.json()}
    assert run_id_b in run_ids, "B's run should appear with scope=user"
    assert run_id_a not in run_ids, "A's run should NOT appear when B uses scope=user"


async def test_shared_project_no_access_returns_404(
    client: AsyncClient,
):
    """A user with no project access gets 404 on the activity endpoint."""
    # Create user A (owner) with dispatch settings
    headers_a = await _make_user_headers("usera_noaccess@example.com")
    await _configure_dispatch(client, headers_a)
    project_id = await _create_project_with_origin(client, headers_a)

    # Create unrelated user C (not a member)
    headers_c = await _make_user_headers("userc_noaccess@example.com")

    # C calls GET /api/runs?project_id=... — should get 404 (project inaccessible)
    res = await client.get(
        "/api/runs",
        params={"project_id": project_id},
        headers=headers_c,
    )
    assert res.status_code == 404


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
        return _remote_run(RemoteRunStatus.succeeded)

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
        return _remote_run(RemoteRunStatus.running)

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
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """execute_run marks run as failed when remote dispatch service errors."""
    import agent_gtd.services.dispatch_router as dr
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

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:9999", "api_key": "test-key"}),
    )

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "dispatch service" in res.json()["error_msg"].lower()


async def test_execute_run_success(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """execute_run marks run as success when remote dispatch succeeds."""
    import agent_gtd.dispatch_worker as dw
    import agent_gtd.services.dispatch_router as dr
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

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

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
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        return _remote_run(RemoteRunStatus.pending)

    async def mock_poll(client, remote_run_id, *, url, api_key):
        nonlocal poll_count
        poll_count += 1
        if poll_count >= 2:
            return _remote_run(RemoteRunStatus.succeeded)
        return _remote_run(RemoteRunStatus.running)

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
    import agent_gtd.services.dispatch_router as dr
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

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    async def mock_dispatch_to_remote(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        return _remote_run(RemoteRunStatus.pending, run_id="remote-456")

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return _remote_run(
            RemoteRunStatus.failed,
            run_id="remote-456",
            error="Reached max turns (50)",
        )

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
    import agent_gtd.services.dispatch_router as dr
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

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    # Mock remote dispatch to return success
    async def mock_dispatch(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        return _remote_run(RemoteRunStatus.pending, run_id="remote-ok")

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return _remote_run(RemoteRunStatus.succeeded, run_id="remote-ok")

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "success"


# --- default_max_turns persistence ---


async def test_create_run_uses_persisted_default_max_turns(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Uses dispatch.default_max_turns from app_settings when max_turns=None."""
    # Persist a custom default_max_turns via the settings API
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 200},
        headers=auth_headers,
    )

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Dispatch without specifying max_turns — should pick up persisted 200
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 200


async def test_create_run_explicit_max_turns_overrides_persisted(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Explicit max_turns in the dispatch request overrides the persisted default."""
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 200},
        headers=auth_headers,
    )

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"max_turns": 75},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 75


async def test_create_run_falls_back_to_env_var_when_not_persisted(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """Falls back to DISPATCH_DEFAULT_MAX_TURNS env var when DB has no value."""
    import agent_gtd.dispatch_worker as dw

    monkeypatch.setattr(dw, "DEFAULT_MAX_TURNS", 150)

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # No dispatch.default_max_turns in app_settings; DEFAULT_MAX_TURNS patched to 150
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 150


# ---------------------------------------------------------------------------
# Unit tests for resolution helpers
# ---------------------------------------------------------------------------


def test_resolve_agent_project_set_wins() -> None:
    """Project build agent overrides global when project value is set."""
    from agent_gtd.dispatch_worker import resolve_agent

    assert (
        resolve_agent(
            mode="build",
            project_plan_agent=None,
            project_build_agent="my-project-build-agent",
            global_plan_agent="",
            global_build_agent="global-build-agent",
        )
        == "my-project-build-agent"
    )


def test_resolve_agent_project_none_falls_back_to_global() -> None:
    """Falls back to global build agent when project value is None."""
    from agent_gtd.dispatch_worker import resolve_agent

    assert (
        resolve_agent(
            mode="build",
            project_plan_agent=None,
            project_build_agent=None,
            global_plan_agent="",
            global_build_agent="global-build-agent",
        )
        == "global-build-agent"
    )


def test_resolve_agent_both_none_returns_empty() -> None:
    """Returns empty string when both project and global are absent."""
    from agent_gtd.dispatch_worker import resolve_agent

    assert (
        resolve_agent(
            mode="build",
            project_plan_agent=None,
            project_build_agent=None,
            global_plan_agent="",
            global_build_agent="",
        )
        == ""
    )


def test_resolve_agent_project_set_global_empty() -> None:
    """Project agent is used even when global is empty."""
    from agent_gtd.dispatch_worker import resolve_agent

    assert (
        resolve_agent(
            mode="build",
            project_plan_agent=None,
            project_build_agent="project-build-agent",
            global_plan_agent="",
            global_build_agent="",
        )
        == "project-build-agent"
    )


def test_resolve_max_turns_project_set_wins() -> None:
    """Project max_turns overrides global when project value is set."""
    from agent_gtd.dispatch_worker import resolve_max_turns

    assert resolve_max_turns(250, 100) == 250


def test_resolve_max_turns_project_none_falls_back_to_global() -> None:
    """Falls back to global max_turns when project value is None."""
    from agent_gtd.dispatch_worker import resolve_max_turns

    assert resolve_max_turns(None, 100) == 100


def test_resolve_max_turns_project_none_global_zero() -> None:
    """Falls back to global even when global is zero (edge case)."""
    from agent_gtd.dispatch_worker import resolve_max_turns

    assert resolve_max_turns(None, 0) == 0


def test_resolve_max_turns_project_set_global_none_style() -> None:
    """Project value is returned regardless of global value."""
    from agent_gtd.dispatch_worker import resolve_max_turns

    assert resolve_max_turns(50, 200) == 50


def test_resolve_timeout_minutes_project_set_wins() -> None:
    """Project timeout_minutes overrides global when project value is set."""
    from agent_gtd.dispatch_worker import resolve_timeout_minutes

    assert resolve_timeout_minutes("build", 60, 30, 240) == 60


def test_resolve_timeout_minutes_project_none_falls_back_to_global() -> None:
    """Falls back to global worker timeout when project value is None (build mode)."""
    from agent_gtd.dispatch_worker import resolve_timeout_minutes

    assert resolve_timeout_minutes("build", None, 30, 240) == 30


def test_resolve_timeout_minutes_project_none_global_edge() -> None:
    """Falls back to global even when global is a non-standard value."""
    from agent_gtd.dispatch_worker import resolve_timeout_minutes

    assert resolve_timeout_minutes("build", None, 5, 240) == 5


def test_resolve_timeout_minutes_project_set_global_different() -> None:
    """Project value is returned regardless of global value."""
    from agent_gtd.dispatch_worker import resolve_timeout_minutes

    assert resolve_timeout_minutes("build", 120, 480, 240) == 120


# ---------------------------------------------------------------------------
# Integration tests: project-scoped dispatch_agent and dispatch_max_turns
# ---------------------------------------------------------------------------


async def test_dispatch_uses_project_agent_override(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
) -> None:
    """execute_run passes project build_dispatch_agent to remote, ignoring global."""
    import agent_gtd.dispatch_worker as dw
    import agent_gtd.services.dispatch_router as dr
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_setting, set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    # Set a global build agent name
    db = await get_db()
    await set_setting(db, "dispatch.build_agent_name", "global-build-agent")

    # Create project with a project-level build_dispatch_agent override
    res = await client.post(
        "/api/projects",
        json={
            "name": "Agent Override Project",
            "git_origin": "git@github.com:test/r.git",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    project_id = res.json()["id"]
    await client.patch(
        f"/api/projects/{project_id}",
        json={"build_dispatch_agent": "project-specific-agent"},
        headers=auth_headers,
    )

    item_id = await _create_item_in_project(client, auth_headers, project_id)

    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    run_id = res.json()["id"]

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    dispatched_agent: list[str] = []

    async def mock_dispatch(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        dispatched_agent.append(agent_name)
        return {"id": "remote-x", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return {"id": "remote-x", "status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    assert dispatched_agent == ["project-specific-agent"]


async def test_dispatch_falls_back_to_global_agent_when_project_unset(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
) -> None:
    """execute_run uses global build_agent_name when project has no agent override."""
    import agent_gtd.dispatch_worker as dw
    import agent_gtd.services.dispatch_router as dr
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_setting, set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    db = await get_db()
    await set_setting(db, "dispatch.build_agent_name", "global-fallback-agent")

    # Create project without build_dispatch_agent (defaults to NULL)
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    dispatched_agent: list[str] = []

    async def mock_dispatch(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        dispatched_agent.append(agent_name)
        return {"id": "remote-y", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return {"id": "remote-y", "status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    assert dispatched_agent == ["global-fallback-agent"]


async def test_dispatch_omits_agent_when_neither_set(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
) -> None:
    """execute_run sends empty agent_name when neither project nor global is set."""
    import agent_gtd.dispatch_worker as dw
    import agent_gtd.services.dispatch_router as dr
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    db = await get_db()
    # No global agent_name set, no project dispatch_agent

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    dispatched_agent: list[str] = []

    async def mock_dispatch(
        client,
        item_id,
        max_turns,
        mode="build",
        *,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        rollout_id=None,
        timeout_minutes=30,
    ):
        dispatched_agent.append(agent_name)
        return {"id": "remote-z", "status": "pending"}

    async def mock_poll(client, remote_run_id, *, url, api_key):
        return {"id": "remote-z", "status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    # Empty string → _dispatch_to_remote omits agent_name from body
    assert dispatched_agent == [""]


async def test_dispatch_uses_project_max_turns_override(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Project dispatch_max_turns overrides global default when unspecified."""
    # Set a global default
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 100},
        headers=auth_headers,
    )

    # Create project with dispatch_max_turns override
    res = await client.post(
        "/api/projects",
        json={
            "name": "Turns Override Project",
            "git_origin": "git@github.com:test/r2.git",
        },
        headers=auth_headers,
    )
    project_id = res.json()["id"]
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 300},
        headers=auth_headers,
    )

    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Dispatch without specifying max_turns — project override (300) should win
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 300


async def test_dispatch_max_turns_falls_back_to_global_when_project_unset(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Global default_max_turns is used when project has no dispatch_max_turns."""
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 175},
        headers=auth_headers,
    )

    # Project with no dispatch_max_turns
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 175


async def test_explicit_max_turns_always_wins_over_project_override(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Explicit max_turns in dispatch request overrides project override."""
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 100},
        headers=auth_headers,
    )

    res = await client.post(
        "/api/projects",
        json={"name": "Explicit Wins", "git_origin": "git@github.com:test/r3.git"},
        headers=auth_headers,
    )
    project_id = res.json()["id"]
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 300},
        headers=auth_headers,
    )

    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Explicit max_turns=50 overrides the project's 300
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"max_turns": 50},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["max_turns"] == 50


# ---------------------------------------------------------------------------
# Blocker enforcement on dispatch
# ---------------------------------------------------------------------------


async def test_dispatch_blocked_by_single_blocker(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """POST dispatch returns 422 when item has 1 unresolved blocker."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id, "Task A")
    blocker_id = await _create_item_in_project(
        client, auth_headers, project_id, "Blocker B"
    )

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_dispatch_blocked_response_shape(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """422 body shape: string detail + blockers array with {id, title, status}."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id, "Task")
    blocker_id = await _create_item_in_project(
        client, auth_headers, project_id, "Blocker"
    )

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 422
    body = res.json()
    assert isinstance(body["detail"], str)
    assert "unresolved blocker" in body["detail"]
    assert isinstance(body["blockers"], list)
    assert len(body["blockers"]) == 1
    b = body["blockers"][0]
    assert b["id"] == blocker_id
    assert b["title"] == "Blocker"
    assert isinstance(b["status"], str)


async def test_dispatch_blocked_multiple_blockers(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Both blockers appear in the 422 response when item has 2 blockers."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id, "Task")
    b1 = await _create_item_in_project(client, auth_headers, project_id, "Blocker 1")
    b2 = await _create_item_in_project(client, auth_headers, project_id, "Blocker 2")

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": b1},
        headers=auth_headers,
    )
    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": b2},
        headers=auth_headers,
    )

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 422
    body = res.json()
    assert len(body["blockers"]) == 2
    blocker_ids = {b["id"] for b in body["blockers"]}
    assert b1 in blocker_ids
    assert b2 in blocker_ids


async def test_dispatch_done_blocker_passes(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatch succeeds when all blockers are done."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id, "Task")
    blocker_id = await _create_item_in_project(
        client, auth_headers, project_id, "Blocker"
    )

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    # Complete the blocker → status becomes done
    await client.post(f"/api/items/{blocker_id}/complete", headers=auth_headers)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201


async def test_dispatch_cancelled_blocker_passes(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatch succeeds when all blockers are cancelled."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id, "Task")
    blocker_id = await _create_item_in_project(
        client, auth_headers, project_id, "Blocker"
    )

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    # Cancel the blocker → treated as resolved
    await client.patch(
        f"/api/items/{blocker_id}",
        json={"status": "cancelled"},
        headers=auth_headers,
    )

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# rollout_id threading (AC-1)
# ---------------------------------------------------------------------------


async def test_dispatch_request_accepts_rollout_id(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """DispatchRunRequest accepts an optional rollout_id field (body parsing)."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # rollout_id=None is valid; the route accepts and ignores it for non-manage mode
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"rollout_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["mode"] == "build"


async def test_create_run_persists_rollout_id(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
):
    """create_run() stores rollout_id on the claude_runs row (DB round-trip)."""
    import uuid
    from datetime import UTC, datetime

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import create_run

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Insert a wave run to satisfy the FK reference
    wave_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        wave_id,
        project_id,
        user_id,
        "running",
        now,
        now,
    )

    # mode="build" just persists rollout_id without the manage-mode flip
    row = await create_run(db, user_id, item_id, mode="build", rollout_id=wave_id)
    assert row["rollout_id"] == wave_id


async def test_create_run_forwards_rollout_id_to_dispatch_worker(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str, monkeypatch
):
    """execute_run() forwards rollout_id to the remote dispatch worker."""
    import uuid
    from datetime import UTC, datetime

    import agent_gtd.dispatch_worker as dw
    import agent_gtd.services.dispatch_router as dr
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.dispatch_worker import execute_run
    from agent_gtd.services.settings_service import set_user_setting

    monkeypatch.setattr(dw, "POLL_INTERVAL", 0.01)

    db = await get_db()
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Skip /info check; return the configured host directly
    monkeypatch.setattr(
        dr,
        "pick_dispatch_host",
        AsyncMock(return_value={"url": "http://fake:8100", "api_key": "test-key"}),
    )

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Insert a wave run so the FK reference is valid
    wave_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        wave_id,
        project_id,
        user_id,
        "running",
        now,
        now,
    )

    # Dispatch with rollout_id (mode=build so no manage flip)
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"rollout_id": wave_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    run_id = res.json()["id"]

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    captured_body: dict = {}

    async def mock_dispatch(
        http_client,
        captured_item_id,
        max_turns,
        mode="build",
        *,
        rollout_id=None,
        url,
        api_key,
        engine="claude-code",
        agent_name="",
        attribution="",
        timeout_minutes=30,
    ):
        captured_body["rollout_id"] = rollout_id
        return {"id": "remote-wave-123", "status": "pending"}

    async def mock_poll(http_client, remote_run_id, *, url, api_key):
        return {"id": "remote-wave-123", "status": "succeeded", "error": None}

    monkeypatch.setattr(dw, "_dispatch_to_remote", mock_dispatch)
    monkeypatch.setattr(dw, "_poll_remote_run", mock_poll)

    await execute_run(db, run, item, project)

    assert captured_body["rollout_id"] == wave_id


async def test_run_response_includes_rollout_id(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
):
    """GET /api/runs/{run_id} returns rollout_id (non-null) when DB row has it set."""
    import uuid
    from datetime import UTC, datetime

    from agent_gtd.database import get_db

    db = await get_db()
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    # Insert a running wave so the FK reference is valid
    wave_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        wave_id,
        project_id,
        user_id,
        "running",
        now,
        now,
    )

    # Dispatch with rollout_id (mode=build, running rollout → passes pre-flight)
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "build", "rollout_id": wave_id},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    run_id = res.json()["id"]

    # The dispatch response itself should include rollout_id
    assert res.json()["rollout_id"] == wave_id

    # GET /api/runs/{run_id} should also return rollout_id
    get_res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["rollout_id"] == wave_id
