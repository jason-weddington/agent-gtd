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


async def test_cancel_run_with_pid(client: AsyncClient, auth_headers: dict[str, str]):
    """Cancel a run that has a PID — kill attempt should be made."""
    from agent_gtd.database import get_db

    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    # Manually set a PID (non-existent process)
    db = await get_db()
    await db.execute("UPDATE claude_runs SET pid = $1 WHERE id = $2", 999999, run_id)

    # Cancel should succeed (killpg fails silently for non-existent PID)
    res = await client.delete(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.status_code == 204


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


# --- Worker execute_run tests ---


async def test_execute_run_clone_failure(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """execute_run marks run as failed when clone fails."""
    from agent_gtd.database import get_db
    from agent_gtd.dispatch_worker import execute_run

    project_id = await _create_project_with_origin(
        client, auth_headers, git_origin="git@nonexistent:bad/repo.git"
    )
    item_id = await _create_item_in_project(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={},
        headers=auth_headers,
    )
    run_id = res.json()["id"]

    db = await get_db()
    from agent_gtd.database import row_to_dict

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "Clone failed" in res.json()["error_msg"]


async def test_execute_run_claude_not_found(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch, tmp_path
):
    """execute_run marks run as failed when claude CLI is not found."""
    from agent_gtd.database import get_db
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
    from agent_gtd.database import row_to_dict

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Mock _prepare_workspace to return a temp dir (skip real clone)
    import agent_gtd.dispatch_worker as dw

    monkeypatch.setattr(dw, "_prepare_workspace", lambda *a: tmp_path)
    # Set PATH to empty so 'claude' won't be found
    monkeypatch.setattr(dw, "_build_env", lambda: {"PATH": "", "HOME": str(tmp_path)})

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "failed"
    assert "claude" in res.json()["error_msg"].lower()


async def test_execute_run_success(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch, tmp_path
):
    """execute_run marks run as success when subprocess exits 0."""
    from agent_gtd.database import get_db
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
    from agent_gtd.database import row_to_dict

    run_row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    run = row_to_dict(run_row)
    item_row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    item = row_to_dict(item_row)
    proj_row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    project = row_to_dict(proj_row)

    # Mock workspace and replace claude with 'true' (exits 0)
    import asyncio

    import agent_gtd.dispatch_worker as dw

    monkeypatch.setattr(dw, "_prepare_workspace", lambda *a: tmp_path)
    monkeypatch.setattr(
        dw,
        "_build_env",
        lambda: {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    # Save the real create_subprocess_exec and patch to replace command
    _real_exec = asyncio.create_subprocess_exec

    async def mock_exec(*args, **kwargs):
        return await _real_exec(
            "true",
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)

    await execute_run(db, run, item, project)

    res = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert res.json()["status"] == "success"
    assert res.json()["finished_at"] is not None
