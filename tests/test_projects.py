"""Tests for projects CRUD API."""

import pytest
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
    assert "dispatch_agent" not in data
    assert data["dispatch_max_turns"] is None
    assert data["plan_dispatch_agent"] is None
    assert data["build_dispatch_agent"] is None


async def test_update_project_dispatch_overrides(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Setting dispatch_max_turns persists correctly."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 50},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_max_turns"] == 50

    # Verify via GET
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.json()["dispatch_max_turns"] == 50


async def test_update_project_clear_dispatch_overrides(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Sending explicit null clears dispatch_max_turns back to NULL."""
    # First set it
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 50},
        headers=auth_headers,
    )

    # Now clear with explicit null
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": None},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_max_turns"] is None


async def test_update_project_absent_dispatch_fields_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Omitting dispatch fields leaves their existing values unchanged."""
    # First set dispatch_max_turns
    await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 75},
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


# ---------------------------------------------------------------------------
# Migration: dispatch_agent → plan_dispatch_agent / build_dispatch_agent
# ---------------------------------------------------------------------------


async def test_dispatch_agent_migration_populates_plan_and_build(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
):
    """The schema migration copies dispatch_agent into plan/build slots when NULL."""
    from agent_gtd.database import get_db, init_db

    db = await get_db()

    # Directly set dispatch_agent to 'foo' and ensure plan/build are NULL
    await db.execute(
        "UPDATE projects SET dispatch_agent = $1,"
        " plan_dispatch_agent = NULL, build_dispatch_agent = NULL"
        " WHERE id = $2",
        "foo",
        project_id,
    )

    # Re-run init_db (idempotent) to trigger the migration statements
    await init_db()

    row = await db.fetchrow(
        "SELECT plan_dispatch_agent, build_dispatch_agent FROM projects WHERE id = $1",
        project_id,
    )
    assert row is not None
    assert row["plan_dispatch_agent"] == "foo"
    assert row["build_dispatch_agent"] == "foo"


async def test_dispatch_agent_migration_does_not_overwrite_existing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
):
    """Migration does not overwrite plan/build slots that are already set."""
    from agent_gtd.database import get_db, init_db

    db = await get_db()

    # Set dispatch_agent and explicit plan/build agents
    await db.execute(
        "UPDATE projects SET dispatch_agent = $1,"
        " plan_dispatch_agent = $2, build_dispatch_agent = $3"
        " WHERE id = $4",
        "legacy",
        "plan-winner",
        "build-winner",
        project_id,
    )

    await init_db()

    row = await db.fetchrow(
        "SELECT plan_dispatch_agent, build_dispatch_agent FROM projects WHERE id = $1",
        project_id,
    )
    assert row is not None
    assert row["plan_dispatch_agent"] == "plan-winner"
    assert row["build_dispatch_agent"] == "build-winner"


# ---------------------------------------------------------------------------
# Dispatch-field ownership enforcement
# ---------------------------------------------------------------------------


async def _make_member(
    client: AsyncClient,
    owner_headers: dict[str, str],
    project_id: str,
) -> dict[str, str]:
    """Register a new user, add them as a project member, return their auth headers."""
    from datetime import UTC, datetime

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    user_b = await register_user("member@example.com", "memberpass")
    headers = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_b.id,
        datetime.now(UTC).isoformat(),
    )
    return headers


async def test_update_dispatch_fields_owner_allowed(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Project owner can update dispatch-only fields."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 42},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["dispatch_max_turns"] == 42


async def test_update_dispatch_fields_member_rejected(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Non-owner member gets 403 when patching dispatch_max_turns."""
    member_headers = await _make_member(client, auth_headers, project_id)
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"dispatch_max_turns": 42},
        headers=member_headers,
    )
    assert res.status_code == 403
    assert "dispatch settings" in res.json()["detail"].lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("dispatch_max_turns", 42),
        ("dispatch_timeout_minutes", 30),
        ("plan_dispatch_agent", "some-agent"),
        ("build_dispatch_agent", "some-agent"),
    ],
)
async def test_update_dispatch_fields_member_rejected_each_field(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
    field: str,
    value: object,
):
    """Each dispatch-only field triggers 403 when patched by a non-owner."""
    from datetime import UTC, datetime

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    user_b = await register_user(f"membx_{field}@example.com", "pass")
    member_headers = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_b.id,
        datetime.now(UTC).isoformat(),
    )

    res = await client.patch(
        f"/api/projects/{project_id}",
        json={field: value},
        headers=member_headers,
    )
    assert res.status_code == 403


async def test_update_non_dispatch_fields_member_allowed(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Non-owner member can update non-dispatch fields."""
    member_headers = await _make_member(client, auth_headers, project_id)
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Renamed by member", "description": "Updated", "area": "work"},
        headers=member_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Renamed by member"
    assert data["description"] == "Updated"


async def test_project_list_includes_is_owner_true(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Owner sees is_owner: true in list response."""
    res = await client.post(
        "/api/projects", json={"name": "Mine"}, headers=auth_headers
    )
    assert res.status_code == 201

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    assert projects[0]["is_owner"] is True


async def test_project_list_includes_is_owner_false(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Member sees is_owner: false and owner_email set for a shared project."""
    res = await client.post(
        "/api/projects", json={"name": "Shared"}, headers=auth_headers
    )
    pid = res.json()["id"]

    from datetime import UTC, datetime

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    user_b = await register_user("memberb@example.com", "passb")
    member_headers = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        pid,
        user_b.id,
        datetime.now(UTC).isoformat(),
    )

    res = await client.get("/api/projects", headers=member_headers)
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    p = projects[0]
    assert p["is_owner"] is False
    assert p["owner_email"] == "test@example.com"


async def test_project_list_includes_member_count(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with one member has member_count: 1."""
    res = await client.post(
        "/api/projects", json={"name": "WithMember"}, headers=auth_headers
    )
    pid = res.json()["id"]

    from datetime import UTC, datetime

    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db

    user_b = await register_user("memberc@example.com", "passc")
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        pid,
        user_b.id,
        datetime.now(UTC).isoformat(),
    )

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    project = next(p for p in res.json() if p["id"] == pid)
    assert project["member_count"] == 1
