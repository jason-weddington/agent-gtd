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


async def test_create_project_dispatch_fields_are_null(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """New projects have null dispatch overrides by default."""
    res = await client.post(
        "/api/projects",
        json={"name": "Dispatch Project"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["dispatch_agent"] is None
    assert data["dispatch_max_turns"] is None


async def test_update_project_dispatch_overrides(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Setting dispatch_agent and dispatch_max_turns persists correctly."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_agent": "planner", "dispatch_max_turns": 50},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_agent"] == "planner"
    assert data["dispatch_max_turns"] == 50

    # Verify via GET
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.json()["dispatch_agent"] == "planner"
    assert res.json()["dispatch_max_turns"] == 50


async def test_update_project_clear_dispatch_overrides(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Sending explicit null clears dispatch overrides back to NULL."""
    # First set them
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_agent": "planner", "dispatch_max_turns": 50},
        headers=auth_headers,
    )

    # Now clear with explicit null
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_agent": None, "dispatch_max_turns": None},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_agent"] is None
    assert data["dispatch_max_turns"] is None


async def test_update_project_absent_dispatch_fields_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Omitting dispatch fields leaves their existing values unchanged."""
    # First set them
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_agent": "builder", "dispatch_max_turns": 75},
        headers=auth_headers,
    )

    # Update only name — dispatch fields should be unchanged
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "New Name"
    assert data["dispatch_agent"] == "builder"
    assert data["dispatch_max_turns"] == 75


async def test_update_project_dispatch_max_turns_too_low(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_max_turns below minimum is rejected with 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 5},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_update_project_dispatch_max_turns_too_high(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_max_turns above maximum is rejected with 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 9999},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_update_project_dispatch_max_turns_boundary_values(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_max_turns accepts boundary values 10 and 500."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_max_turns"] == 10

    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 500},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_max_turns"] == 500


async def test_update_project_dispatch_timeout_minutes(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Setting dispatch_timeout_minutes persists correctly."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 60},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_timeout_minutes"] == 60

    # Verify via GET
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.json()["dispatch_timeout_minutes"] == 60


async def test_update_project_clear_dispatch_timeout_minutes(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Sending explicit null clears dispatch_timeout_minutes back to NULL."""
    # First set it
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 120},
        headers=auth_headers,
    )

    # Now clear with explicit null
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": None},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_timeout_minutes"] is None


async def test_update_project_absent_dispatch_timeout_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Omitting dispatch_timeout_minutes leaves it unchanged."""
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 90},
        headers=auth_headers,
    )

    # Update only name — timeout should be unchanged
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "New Name"
    assert data["dispatch_timeout_minutes"] == 90


async def test_update_project_dispatch_timeout_minutes_too_low(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_timeout_minutes below minimum is rejected with 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 4},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_update_project_dispatch_timeout_minutes_too_high(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_timeout_minutes above maximum is rejected with 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 481},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_update_project_dispatch_timeout_minutes_boundary_values(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """dispatch_timeout_minutes accepts boundary values 5 and 480."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 5},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_timeout_minutes"] == 5

    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_timeout_minutes": 480},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_timeout_minutes"] == 480


async def test_project_ownership_isolation(client: AsyncClient):
    from agent_gtd.auth import create_token, register_user

    # Create two users directly (bypass invite system)
    u1 = await register_user("user1@example.com", "pass123")
    headers1 = {"Authorization": f"Bearer {create_token(u1.id)}"}
    u2 = await register_user("user2@example.com", "pass123")
    headers2 = {"Authorization": f"Bearer {create_token(u2.id)}"}

    # User 1 creates a project
    res = await client.post("/api/projects", json={"name": "Private"}, headers=headers1)
    pid = res.json()["id"]

    # User 2 cannot see it
    res = await client.get("/api/projects", headers=headers2)
    assert len(res.json()) == 0

    # User 2 cannot access it directly
    res = await client.get(f"/api/projects/{pid}", headers=headers2)
    assert res.status_code == 404
