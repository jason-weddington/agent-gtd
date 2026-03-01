"""Smoke tests for Agent GTD API."""

from httpx import AsyncClient


async def test_health(client: AsyncClient):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_register_and_login(client: AsyncClient):
    # Register
    res = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "test@example.com"

    # Login with same credentials
    res = await client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert res.status_code == 200
    assert "token" in res.json()


async def test_projects_crud(client: AsyncClient, auth_headers: dict[str, str]):
    # Create a project
    res = await client.post(
        "/api/projects",
        json={"name": "My Project", "description": "Test project"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    project = res.json()
    assert project["name"] == "My Project"
    project_id = project["id"]

    # List projects
    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1

    # Update the project
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Updated Project"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Project"

    # Delete the project
    res = await client.delete(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 204

    # Verify deletion
    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 0


async def test_items_inbox_and_triage(
    client: AsyncClient, auth_headers: dict[str, str]
):
    # Create a project for triage
    res = await client.post(
        "/api/projects",
        json={"name": "Triage Target"},
        headers=auth_headers,
    )
    project_id = res.json()["id"]

    # Quick capture to inbox
    res = await client.post(
        "/api/inbox",
        json={"title": "Buy groceries"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    item = res.json()
    assert item["status"] == "inbox"
    assert item["created_by"] == "human"
    item_id = item["id"]

    # Verify inbox listing
    res = await client.get("/api/inbox", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1

    # Triage: assign to project and set status
    res = await client.patch(
        f"/api/items/{item_id}",
        json={
            "project_id": project_id,
            "status": "next_action",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["project_id"] == project_id
    assert res.json()["status"] == "next_action"
    assert res.json()["version"] == 2

    # Inbox should be empty now
    res = await client.get("/api/inbox", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 0

    # Mark as done — should set completed_at
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["completed_at"] is not None
    assert res.json()["version"] == 3


async def test_project_cascade_delete(
    client: AsyncClient, auth_headers: dict[str, str]
):
    # Create project
    res = await client.post(
        "/api/projects",
        json={"name": "Cascade Test"},
        headers=auth_headers,
    )
    project_id = res.json()["id"]

    # Add an item to the project
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Task in project"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    # Add a note to the project
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Note in project", "content_markdown": "Some content"},
        headers=auth_headers,
    )
    note_id = res.json()["id"]

    # Delete the project
    res = await client.delete(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 204

    # Item and note should be gone
    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 404

    res = await client.get(f"/api/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 404
