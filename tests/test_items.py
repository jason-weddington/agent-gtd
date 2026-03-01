"""Tests for items CRUD API."""

from httpx import AsyncClient


async def test_create_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items",
        json={"title": "Buy milk", "priority": "high"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Buy milk"
    assert data["priority"] == "high"
    assert data["status"] == "inbox"
    assert data["version"] == 1
    assert data["created_by"] == "human"


async def test_create_item_with_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        "/api/items",
        json={"title": "Task", "project_id": project_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["project_id"] == project_id


async def test_create_item_invalid_project(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "Task", "project_id": "nonexistent"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_list_items(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/items", json={"title": "A"}, headers=auth_headers)
    await client.post("/api/items", json={"title": "B"}, headers=auth_headers)

    res = await client.get("/api/items", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2


async def test_filter_items_by_status(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await client.post("/api/items", json={"title": "Inbox item"}, headers=auth_headers)
    await client.post(
        "/api/items",
        json={"title": "Active item", "status": "active"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items", params={"status": "inbox"}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["title"] == "Inbox item"


async def test_filter_items_by_priority(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await client.post(
        "/api/items",
        json={"title": "Urgent", "priority": "urgent"},
        headers=auth_headers,
    )
    await client.post("/api/items", json={"title": "Normal"}, headers=auth_headers)

    res = await client.get(
        "/api/items", params={"priority": "urgent"}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["title"] == "Urgent"


async def test_filter_items_by_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    await client.post(
        "/api/items",
        json={"title": "In project", "project_id": project_id},
        headers=auth_headers,
    )
    await client.post("/api/items", json={"title": "No project"}, headers=auth_headers)

    res = await client.get(
        "/api/items", params={"project_id": project_id}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["title"] == "In project"


async def test_get_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post("/api/items", json={"title": "Task"}, headers=auth_headers)
    item_id = res.json()["id"]

    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["title"] == "Task"


async def test_get_item_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.get("/api/items/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_update_item_basic(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items", json={"title": "Original"}, headers=auth_headers
    )
    item_id = res.json()["id"]

    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "Updated", "priority": "high"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Updated"
    assert data["priority"] == "high"
    assert data["version"] == 2


async def test_update_item_version_increments(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post("/api/items", json={"title": "Task"}, headers=auth_headers)
    item_id = res.json()["id"]
    assert res.json()["version"] == 1

    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "V2"},
        headers=auth_headers,
    )
    assert res.json()["version"] == 2

    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "V3"},
        headers=auth_headers,
    )
    assert res.json()["version"] == 3


async def test_update_item_auto_completed_at(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post("/api/items", json={"title": "Task"}, headers=auth_headers)
    item_id = res.json()["id"]
    assert res.json()["completed_at"] is None

    # Mark as done — completed_at should be set
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert res.json()["completed_at"] is not None

    # Move away from done — completed_at should clear
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"status": "active"},
        headers=auth_headers,
    )
    assert res.json()["completed_at"] is None


async def test_update_item_assign_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        "/api/items", json={"title": "Orphan"}, headers=auth_headers
    )
    item_id = res.json()["id"]
    assert res.json()["project_id"] is None

    # Assign to project
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"project_id": project_id},
        headers=auth_headers,
    )
    assert res.json()["project_id"] == project_id

    # Unassign from project (send null)
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"project_id": None},
        headers=auth_headers,
    )
    assert res.json()["project_id"] is None


async def test_update_item_invalid_project(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post("/api/items", json={"title": "Task"}, headers=auth_headers)
    item_id = res.json()["id"]

    res = await client.patch(
        f"/api/items/{item_id}",
        json={"project_id": "nonexistent"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_update_item_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.patch(
        "/api/items/nonexistent",
        json={"title": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_delete_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items", json={"title": "To delete"}, headers=auth_headers
    )
    item_id = res.json()["id"]

    res = await client.delete(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 204

    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_delete_item_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.delete("/api/items/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_inbox_capture(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/inbox",
        json={"title": "Quick thought"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Quick thought"
    assert data["status"] == "inbox"
    assert data["priority"] == "normal"
    assert data["created_by"] == "human"
    assert data["project_id"] is None


async def test_inbox_list(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/inbox", json={"title": "Inbox 1"}, headers=auth_headers)
    await client.post(
        "/api/items",
        json={"title": "Not inbox", "status": "active"},
        headers=auth_headers,
    )

    res = await client.get("/api/inbox", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["title"] == "Inbox 1"


async def test_project_scoped_items(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    # Create via project-scoped endpoint
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Project task"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["project_id"] == project_id

    # List via project-scoped endpoint
    res = await client.get(f"/api/projects/{project_id}/items", headers=auth_headers)
    assert len(res.json()) == 1
    assert res.json()[0]["title"] == "Project task"


async def test_project_scoped_items_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.get("/api/projects/nonexistent/items", headers=auth_headers)
    assert res.status_code == 404


async def test_item_ownership_isolation(client: AsyncClient):
    # Register two users
    res1 = await client.post(
        "/api/auth/register",
        json={"email": "user1@example.com", "password": "pass123"},
    )
    headers1 = {"Authorization": f"Bearer {res1.json()['token']}"}

    res2 = await client.post(
        "/api/auth/register",
        json={"email": "user2@example.com", "password": "pass123"},
    )
    headers2 = {"Authorization": f"Bearer {res2.json()['token']}"}

    # User 1 creates an item
    res = await client.post("/api/items", json={"title": "Private"}, headers=headers1)
    iid = res.json()["id"]

    # User 2 cannot see it
    res = await client.get("/api/items", headers=headers2)
    assert len(res.json()) == 0

    res = await client.get(f"/api/items/{iid}", headers=headers2)
    assert res.status_code == 404
