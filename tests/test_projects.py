"""Tests for projects CRUD API."""

from httpx import AsyncClient


async def test_create_project(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/projects",
        json={"name": "My Project", "description": "Desc", "area": "work"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "My Project"
    assert data["description"] == "Desc"
    assert data["status"] == "active"
    assert data["area"] == "work"
    assert "id" in data
    assert "created_at" in data


async def test_list_projects(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/projects", json={"name": "P1"}, headers=auth_headers)
    await client.post("/api/projects", json={"name": "P2"}, headers=auth_headers)

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2


async def test_filter_projects_by_status(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await client.post("/api/projects", json={"name": "Active"}, headers=auth_headers)
    res = await client.post(
        "/api/projects",
        json={"name": "On Hold", "status": "on_hold"},
        headers=auth_headers,
    )
    assert res.status_code == 201

    res = await client.get(
        "/api/projects", params={"status": "active"}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "Active"

    res = await client.get(
        "/api/projects", params={"status": "on_hold"}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "On Hold"


async def test_filter_projects_by_area(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await client.post(
        "/api/projects", json={"name": "Work", "area": "work"}, headers=auth_headers
    )
    await client.post(
        "/api/projects",
        json={"name": "Personal", "area": "personal"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/projects", params={"area": "work"}, headers=auth_headers
    )
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "Work"


async def test_get_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == project_id


async def test_get_project_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.get("/api/projects/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_update_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Renamed", "status": "completed"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Renamed"
    assert data["status"] == "completed"


async def test_update_project_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.patch(
        "/api/projects/nonexistent",
        json={"name": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_delete_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.delete(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 204

    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_delete_project_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.delete("/api/projects/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_project_ownership_isolation(client: AsyncClient):
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

    # User 1 creates a project
    res = await client.post("/api/projects", json={"name": "Private"}, headers=headers1)
    pid = res.json()["id"]

    # User 2 cannot see it
    res = await client.get("/api/projects", headers=headers2)
    assert len(res.json()) == 0

    # User 2 cannot access it directly
    res = await client.get(f"/api/projects/{pid}", headers=headers2)
    assert res.status_code == 404
