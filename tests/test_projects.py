"""Tests for projects CRUD API."""

import pytest
from httpx import AsyncClient

from agent_gtd.services.project_service import workspace_repo_dir


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
        ("gate_command", "uv run pytest"),
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


# ---------------------------------------------------------------------------
# total_items
# ---------------------------------------------------------------------------


async def test_get_project_total_items_nonzero(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """GET /api/projects/{id} returns total_items equal to the item count."""
    # Create 3 items in the project
    for i in range(3):
        res = await client.post(
            "/api/items",
            json={"title": f"Item {i}", "project_id": project_id},
            headers=auth_headers,
        )
        assert res.status_code == 201

    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total_items"] == 3


async def test_list_projects_total_items_nonzero(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """GET /api/projects returns total_items equal to the item count per project."""
    # Create 2 items in the project
    for i in range(2):
        res = await client.post(
            "/api/items",
            json={"title": f"Task {i}", "project_id": project_id},
            headers=auth_headers,
        )
        assert res.status_code == 201

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    project = next(p for p in res.json() if p["id"] == project_id)
    assert project["total_items"] == 2


async def test_project_total_items_zero_when_no_items(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """A project with no items returns total_items: 0 from both GET and list."""
    # No items created — verify both endpoints return 0
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total_items"] == 0

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    project = next(p for p in res.json() if p["id"] == project_id)
    assert project["total_items"] == 0


async def test_get_project_total_items_excludes_done(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """GET /api/projects/{id} total_items excludes items with status='done'."""
    # Create 2 open items (default status 'inbox') + 1 done item
    for i in range(2):
        res = await client.post(
            "/api/items",
            json={"title": f"Open item {i}", "project_id": project_id},
            headers=auth_headers,
        )
        assert res.status_code == 201

    res = await client.post(
        "/api/items",
        json={"title": "Done item", "project_id": project_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    done_item_id = res.json()["id"]

    # Mark the third item as done
    res = await client.patch(
        f"/api/items/{done_item_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert res.status_code == 200

    # total_items should be 2 (the done item is excluded)
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total_items"] == 2


async def test_list_projects_total_items_excludes_done(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """GET /api/projects total_items per project excludes items with status='done'."""
    # Create 2 open items (default status 'inbox') + 1 done item
    for i in range(2):
        res = await client.post(
            "/api/items",
            json={"title": f"Open task {i}", "project_id": project_id},
            headers=auth_headers,
        )
        assert res.status_code == 201

    res = await client.post(
        "/api/items",
        json={"title": "Completed task", "project_id": project_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    done_item_id = res.json()["id"]

    # Mark the third item as done
    res = await client.patch(
        f"/api/items/{done_item_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert res.status_code == 200

    # total_items should be 2 (the done item is excluded)
    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    project = next(p for p in res.json() if p["id"] == project_id)
    assert project["total_items"] == 2


# ---------------------------------------------------------------------------
# description_preview — pure helper unit tests
# ---------------------------------------------------------------------------


def test_description_preview_helper_multiline():
    """First non-empty line of a multi-line description is returned."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview("Line one\nLine two\nLine three") == "Line one"


def test_description_preview_helper_leading_blank_lines():
    """Blank leading lines are skipped; first non-empty line is returned."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview("\n\nActual content\nMore text") == "Actual content"


def test_description_preview_helper_leading_whitespace_line():
    """A line with only whitespace is skipped; next non-empty line is returned."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview("   \nHello world") == "Hello world"


def test_description_preview_helper_truncates_to_80_chars():
    """First line longer than 80 chars is truncated to exactly 80."""
    from agent_gtd.services.project_service import _description_preview

    long_line = "x" * 100
    result = _description_preview(long_line)
    assert result == "x" * 80
    assert len(result) == 80  # type: ignore[arg-type]


def test_description_preview_helper_empty_string():
    """Empty description returns None."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview("") is None


def test_description_preview_helper_none():
    """None description returns None."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview(None) is None


def test_description_preview_helper_whitespace_only():
    """Description with only whitespace/blank lines returns None."""
    from agent_gtd.services.project_service import _description_preview

    assert _description_preview("   \n\t\n  ") is None


# ---------------------------------------------------------------------------
# description_preview — integration tests via API
# ---------------------------------------------------------------------------


async def test_description_preview_multiline_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with multi-line description → preview is first non-empty line."""
    res = await client.post(
        "/api/projects",
        json={"name": "Multi", "description": "First line\nSecond line\nThird"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    pid = res.json()["id"]

    # Verify via GET
    res = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["description_preview"] == "First line"

    # Verify via LIST
    res = await client.get("/api/projects", headers=auth_headers)
    project = next(p for p in res.json() if p["id"] == pid)
    assert project["description_preview"] == "First line"


async def test_description_preview_leading_whitespace_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with leading-whitespace description still computes preview correctly."""
    res = await client.post(
        "/api/projects",
        json={"name": "Ws", "description": "\n\n  Indented first\nSecond"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    pid = res.json()["id"]

    res = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    assert res.json()["description_preview"] == "Indented first"


async def test_description_preview_truncated_to_80_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with description longer than 80 chars → preview is truncated to 80."""
    long_desc = "a" * 120
    res = await client.post(
        "/api/projects",
        json={"name": "Long", "description": long_desc},
        headers=auth_headers,
    )
    assert res.status_code == 201
    pid = res.json()["id"]

    res = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    preview = res.json()["description_preview"]
    assert preview == "a" * 80
    assert len(preview) == 80


async def test_description_preview_empty_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with empty description → preview is None."""
    res = await client.post(
        "/api/projects",
        json={"name": "Empty desc", "description": ""},
        headers=auth_headers,
    )
    assert res.status_code == 201
    pid = res.json()["id"]

    res = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    assert res.json()["description_preview"] is None

    res = await client.get("/api/projects", headers=auth_headers)
    project = next(p for p in res.json() if p["id"] == pid)
    assert project["description_preview"] is None


async def test_description_preview_whitespace_only_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Project with whitespace-only description → preview is None."""
    res = await client.post(
        "/api/projects",
        json={"name": "Ws only", "description": "   \n\t\n  "},
        headers=auth_headers,
    )
    assert res.status_code == 201
    pid = res.json()["id"]

    res = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    assert res.json()["description_preview"] is None


# ---------------------------------------------------------------------------
# workspace_repo_dir unit tests
# ---------------------------------------------------------------------------


def test_workspace_repo_dir_https():
    assert workspace_repo_dir("https://github.com/org/repo.git") == "repo"


def test_workspace_repo_dir_https_no_git_suffix():
    assert workspace_repo_dir("https://github.com/org/repo") == "repo"


def test_workspace_repo_dir_scp_style():
    assert workspace_repo_dir("git@github.com:org/repo.git") == "repo"


def test_workspace_repo_dir_trailing_slash():
    assert workspace_repo_dir("https://github.com/org/repo/") == "repo"


def test_workspace_repo_dir_scp_no_git_suffix():
    assert workspace_repo_dir("git@github.com:org/myrepo") == "myrepo"


def test_workspace_repo_dir_pathological_empty():
    """A URL ending in /.git yields an empty checkout directory name."""
    assert workspace_repo_dir("https://example.com/.git") == ""


# ---------------------------------------------------------------------------
# Workspace fields via REST — POST / PATCH / GET round-trips
# ---------------------------------------------------------------------------


async def test_create_project_workspace_defaults(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """New projects default to monorepo mode with empty workspace_repos."""
    res = await client.post("/api/projects", json={"name": "P"}, headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["repo_mode"] == "monorepo"
    assert data["workspace_repos"] == []


async def test_create_project_workspace_mode(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Creating a workspace project stores repo_mode and workspace_repos."""
    res = await client.post(
        "/api/projects",
        json={
            "name": "Workspace P",
            "repo_mode": "workspace",
            "workspace_repos": [
                "https://github.com/org/repo-a.git",
                "https://github.com/org/repo-b.git",
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["repo_mode"] == "workspace"
    assert data["workspace_repos"] == [
        "https://github.com/org/repo-a.git",
        "https://github.com/org/repo-b.git",
    ]


async def test_create_project_workspace_strips_urls(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Whitespace in URLs is stripped before storage."""
    res = await client.post(
        "/api/projects",
        json={
            "name": "P",
            "repo_mode": "workspace",
            "workspace_repos": ["  https://github.com/org/repo.git  "],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["workspace_repos"] == ["https://github.com/org/repo.git"]


async def test_create_workspace_project_requires_at_least_one_url(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Workspace mode with empty workspace_repos returns 400."""
    res = await client.post(
        "/api/projects",
        json={"name": "P", "repo_mode": "workspace", "workspace_repos": []},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "at least one repository URL" in res.json()["detail"]


async def test_create_workspace_project_missing_repos_400(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Workspace mode with workspace_repos omitted returns 400."""
    res = await client.post(
        "/api/projects",
        json={"name": "P", "repo_mode": "workspace"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "at least one repository URL" in res.json()["detail"]


async def test_create_project_blank_url_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Blank URL element in workspace_repos is rejected even for monorepo."""
    res = await client.post(
        "/api/projects",
        json={"name": "P", "workspace_repos": ["  "]},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_create_project_invalid_repo_mode_422(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Invalid repo_mode value is rejected with 422 by Pydantic."""
    res = await client.post(
        "/api/projects",
        json={"name": "P", "repo_mode": "bogus"},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_create_workspace_duplicate_dir_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Two URLs deriving the same checkout dir return 400."""
    res = await client.post(
        "/api/projects",
        json={
            "name": "P",
            "repo_mode": "workspace",
            "workspace_repos": [
                "https://github.com/org/repo.git",
                "https://github.com/other-org/repo.git",
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "duplicate checkout directory" in res.json()["detail"]


async def test_create_workspace_empty_dir_url_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """URL that yields empty checkout dir is rejected."""
    # "https://example.com/.git" → workspace_repo_dir → ""
    res = await client.post(
        "/api/projects",
        json={
            "name": "P",
            "repo_mode": "workspace",
            "workspace_repos": ["https://example.com/.git"],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "empty checkout directory" in res.json()["detail"]


async def test_update_project_workspace_fields(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """PATCH stores and returns repo_mode + workspace_repos correctly."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["repo_mode"] == "workspace"
    assert data["workspace_repos"] == ["https://github.com/org/repo.git"]

    # Verify via GET
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert res.json()["repo_mode"] == "workspace"
    assert res.json()["workspace_repos"] == ["https://github.com/org/repo.git"]


async def test_update_project_workspace_repos_returned_as_list(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """GET response returns workspace_repos as a JSON array, not raw JSON text."""
    await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/a.git"],
        },
        headers=auth_headers,
    )
    res = await client.get(f"/api/projects/{project_id}", headers=auth_headers)
    assert isinstance(res.json()["workspace_repos"], list)


async def test_update_project_absent_workspace_fields_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Omitting workspace fields leaves them unchanged."""
    await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=auth_headers,
    )
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "New Name"
    assert data["repo_mode"] == "workspace"
    assert data["workspace_repos"] == ["https://github.com/org/repo.git"]


async def test_update_workspace_to_monorepo(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Switching workspace → monorepo is allowed."""
    await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=auth_headers,
    )
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"repo_mode": "monorepo"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["repo_mode"] == "monorepo"


async def test_update_project_switch_to_workspace_needs_repos(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Switching mode to workspace when stored repos is [] returns 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"repo_mode": "workspace"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "at least one repository URL" in res.json()["detail"]


async def test_update_project_empty_repos_while_workspace_rejected(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Clearing workspace_repos while mode is workspace returns 400."""
    await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=auth_headers,
    )
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"workspace_repos": []},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "at least one repository URL" in res.json()["detail"]


async def test_update_project_monorepo_with_empty_list_succeeds(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Sending workspace_repos=[] while mode is monorepo is fine."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"workspace_repos": []},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["workspace_repos"] == []


async def test_update_project_monorepo_blank_element_rejected(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """workspace_repos with blank element is rejected even in monorepo mode."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"workspace_repos": ["  "]},
        headers=auth_headers,
    )
    assert res.status_code == 400


async def test_update_project_invalid_repo_mode_422(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Invalid repo_mode string is rejected with 422 by Pydantic."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"repo_mode": "bogus"},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_update_workspace_duplicate_dir_rejected(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Two URLs deriving same checkout dir in PATCH return 400."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": [
                "https://github.com/org-a/repo.git",
                "https://github.com/org-b/repo.git",
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "duplicate checkout directory" in res.json()["detail"]


async def test_legacy_project_response_defaults(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Projects without workspace fields in the body default to monorepo/[]."""
    res = await client.post(
        "/api/projects",
        json={"name": "Legacy"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["repo_mode"] == "monorepo"
    assert data["workspace_repos"] == []


async def test_service_create_project_bogus_repo_mode(client: AsyncClient):
    """Service-layer bogus repo_mode raises ValidationError (bypasses Pydantic)."""
    from agent_gtd.database import get_db
    from agent_gtd.exceptions import ValidationError as GtdValidationError
    from agent_gtd.services import project_service

    db = await get_db()
    with pytest.raises(GtdValidationError, match=r"monorepo|workspace"):
        await project_service.create_project(
            db, "00000000-0000-0000-0000-000000000001", name="P", repo_mode="bogus"
        )


async def test_service_update_project_bogus_repo_mode(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Service-layer bogus repo_mode on update raises ValidationError."""
    from agent_gtd.database import get_db
    from agent_gtd.exceptions import ValidationError as GtdValidationError
    from agent_gtd.services import project_service

    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]

    db = await get_db()
    with pytest.raises(GtdValidationError, match=r"monorepo|workspace"):
        await project_service.update_project(db, uid, project_id, repo_mode="bogus")


async def test_workspace_repos_decoded_in_service_return(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Service returns workspace_repos as list[str], not raw JSON text."""
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]
    db = await get_db()

    result = await project_service.update_project(
        db,
        uid,
        project_id,
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/repo.git"],
    )
    assert isinstance(result["workspace_repos"], list)
    assert result["workspace_repos"] == ["https://github.com/org/repo.git"]


async def _make_owner_and_member(client: AsyncClient):
    """Helper: register owner + member, create project, add member.

    Returns (pid, owner_headers, member_headers).
    """
    from agent_gtd.auth import create_token, register_user

    owner = await register_user("owner_ws2@example.com", "pass123")
    owner_headers = {"Authorization": f"Bearer {create_token(owner.id)}"}

    member = await register_user("member_ws2@example.com", "pass123")
    member_headers = {"Authorization": f"Bearer {create_token(member.id)}"}

    res = await client.post(
        "/api/projects",
        json={"name": "Shared"},
        headers=owner_headers,
    )
    pid = res.json()["id"]
    await client.post(
        f"/api/projects/{pid}/members",
        json={"email": "member_ws2@example.com"},
        headers=owner_headers,
    )
    return pid, owner_headers, member_headers


async def test_non_owner_member_patch_repo_mode_gets_403(client: AsyncClient):
    """A non-owner member PATCHing repo_mode (owner-only) gets 403."""
    pid, _owner_headers, member_headers = await _make_owner_and_member(client)

    res = await client.patch(
        f"/api/projects/{pid}",
        json={
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=member_headers,
    )
    assert res.status_code == 403


async def test_non_owner_member_patch_git_origin_gets_403(client: AsyncClient):
    """A non-owner member PATCHing git_origin (owner-only) gets 403."""
    pid, _owner_headers, member_headers = await _make_owner_and_member(client)

    res = await client.patch(
        f"/api/projects/{pid}",
        json={"git_origin": "https://github.com/org/repo.git"},
        headers=member_headers,
    )
    assert res.status_code == 403


async def test_non_owner_member_patch_workspace_repos_gets_403(client: AsyncClient):
    """A non-owner member PATCHing workspace_repos (owner-only) gets 403."""
    pid, _owner_headers, member_headers = await _make_owner_and_member(client)

    res = await client.patch(
        f"/api/projects/{pid}",
        json={"workspace_repos": ["https://github.com/org/repo.git"]},
        headers=member_headers,
    )
    assert res.status_code == 403


async def test_non_owner_member_patch_name_description_succeeds(client: AsyncClient):
    """A non-owner member PATCHing only name/description succeeds.

    None of the owner-only fields are present in the body.
    """
    pid, _owner_headers, member_headers = await _make_owner_and_member(client)

    res = await client.patch(
        f"/api/projects/{pid}",
        json={"name": "Updated by member"},
        headers=member_headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated by member"


async def test_owner_patch_all_clone_target_fields_succeeds(client: AsyncClient):
    """The project owner can PATCH git_origin, repo_mode, and workspace_repos."""
    pid, owner_headers, _member_headers = await _make_owner_and_member(client)

    res = await client.patch(
        f"/api/projects/{pid}",
        json={
            "git_origin": "https://github.com/org/meta.git",
            "repo_mode": "workspace",
            "workspace_repos": ["https://github.com/org/repo.git"],
        },
        headers=owner_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["git_origin"] == "https://github.com/org/meta.git"
    assert data["repo_mode"] == "workspace"
    assert data["workspace_repos"] == ["https://github.com/org/repo.git"]


# --- Unit tests for _decode_project_workspace_repos ---


def test_decode_project_workspace_repos_already_list():
    """No-op when workspace_repos is already a Python list (pre-decoded)."""
    from agent_gtd.services.project_service import _decode_project_workspace_repos

    data = {"workspace_repos": ["https://github.com/org/a.git"]}
    out = _decode_project_workspace_repos(data)
    assert out["workspace_repos"] == ["https://github.com/org/a.git"]


def test_decode_project_workspace_repos_none_becomes_empty_list():
    """Sets workspace_repos to [] when value is None (absent/legacy row)."""
    from agent_gtd.services.project_service import _decode_project_workspace_repos

    data = {"workspace_repos": None}
    out = _decode_project_workspace_repos(data)
    assert out["workspace_repos"] == []


# ---------------------------------------------------------------------------
# gate_command — model defaults
# ---------------------------------------------------------------------------


def test_project_model_gate_command_defaults_to_none():
    """Project domain model defaults gate_command to None."""
    from datetime import UTC, datetime

    from agent_gtd.models import Project

    p = Project(
        id="pid",
        user_id="uid",
        name="P",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert p.gate_command is None


def test_update_project_request_gate_command_defaults_to_none():
    """UpdateProjectRequest defaults gate_command to None."""
    from agent_gtd.models import UpdateProjectRequest

    req = UpdateProjectRequest()
    assert req.gate_command is None


# ---------------------------------------------------------------------------
# gate_command — service round-trip (create / update / clear)
# ---------------------------------------------------------------------------


async def test_service_create_project_with_gate_command(client: AsyncClient):
    """create_project stores gate_command and returns it."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    user = await register_user("gate_create@example.com", "pass")
    db = await get_db()

    result = await project_service.create_project(
        db, user.id, name="Gate Project", gate_command="uv run pytest"
    )
    assert result["gate_command"] == "uv run pytest"

    # Verify via get
    got = await project_service.get_project(db, user.id, result["id"])
    assert got["gate_command"] == "uv run pytest"


async def test_service_update_project_gate_command(client: AsyncClient):
    """update_project sets and clears gate_command correctly."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    user = await register_user("gate_update@example.com", "pass")
    db = await get_db()

    row = await project_service.create_project(db, user.id, name="Gate Upd")
    pid = row["id"]

    # Set gate_command
    updated = await project_service.update_project(
        db, user.id, pid, gate_command="cargo test"
    )
    assert updated["gate_command"] == "cargo test"

    # Clear gate_command
    cleared = await project_service.update_project(
        db, user.id, pid, clear_gate_command=True
    )
    assert cleared["gate_command"] is None


# ---------------------------------------------------------------------------
# gate_command — REST API round-trip and owner-only guard
# ---------------------------------------------------------------------------


async def test_create_project_gate_command_via_api(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """POST /api/projects with gate_command stores and returns it."""
    res = await client.post(
        "/api/projects",
        json={"name": "GC API", "gate_command": "uv run pytest"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["gate_command"] == "uv run pytest"

    # Verify via GET
    res2 = await client.get(f"/api/projects/{data['id']}", headers=auth_headers)
    assert res2.json()["gate_command"] == "uv run pytest"


async def test_update_project_gate_command_via_api(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """PATCH /api/projects sets and clears gate_command."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"gate_command": "make test"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["gate_command"] == "make test"

    # Clear with explicit null
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"gate_command": None},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["gate_command"] is None


async def test_gate_command_member_patch_gets_403(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Non-owner member PATCHing gate_command receives 403."""
    member_headers = await _make_member(client, auth_headers, project_id)
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"gate_command": "uv run pytest"},
        headers=member_headers,
    )
    assert res.status_code == 403
    assert "dispatch settings" in res.json()["detail"].lower()


async def test_gate_command_owner_patch_succeeds(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Project owner can PATCH gate_command."""
    res = await client.patch(
        f"/api/projects/{project_id}",
        json={"gate_command": "npm test"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["gate_command"] == "npm test"
