"""Tests for dispatch run CRUD API."""

from httpx import AsyncClient


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
    assert run["max_turns"] == 20


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


async def test_reconcile_orphans(client: AsyncClient, auth_headers: dict[str, str]):
    """Orphan reconciliation marks active runs as failed."""
    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import reconcile_orphans

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]
    assert res.json()["status"] == "pending"

    db = await get_db()
    count = await reconcile_orphans(db)
    assert count >= 1

    # Run should be failed now
    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "Server restarted" in res.json()["error_msg"]
