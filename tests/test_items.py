"""Tests for items CRUD API."""

import json
import logging
import uuid

import pytest
from httpx import AsyncClient

_PLAN_RUN_ID = "11111111-2222-3333-4444-555555555555"


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
    data = res.json()
    assert data["title"] == "Task"
    assert data["blockers"] == []


async def test_get_item_includes_blockers(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Single-item GET should return the blockers array populated."""
    # Create two items
    res = await client.post(
        "/api/items", json={"title": "Blocked"}, headers=auth_headers
    )
    assert res.status_code == 201
    item_id = res.json()["id"]

    res = await client.post(
        "/api/items", json={"title": "Blocker"}, headers=auth_headers
    )
    assert res.status_code == 201
    blocker_id = res.json()["id"]

    # Add blocker relationship
    res = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res.status_code == 201

    # Single-item GET should return populated blockers
    res = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["blockers"]) == 1
    assert data["blockers"][0]["id"] == blocker_id
    assert data["blockers"][0]["title"] == "Blocker"
    assert data["blockers"][0]["status"] == "inbox"
    assert data["blockers"][0]["project_id"] is None


async def test_list_items_blockers_empty(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """List endpoint should return blockers: [] (no N+1 join)."""
    res = await client.post(
        "/api/items", json={"title": "Item A"}, headers=auth_headers
    )
    assert res.status_code == 201
    item_id = res.json()["id"]

    res = await client.post(
        "/api/items", json={"title": "Item B"}, headers=auth_headers
    )
    assert res.status_code == 201
    blocker_id = res.json()["id"]

    # Add a blocker so it would show up if list was joining
    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    # List endpoint should return empty blockers (no N+1)
    res = await client.get("/api/items", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()
    for item in items:
        assert item["blockers"] == []


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


async def test_project_scoped_item_defaults_to_new(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Default status task"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["status"] == "new"


async def test_project_scoped_items_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.get("/api/projects/nonexistent/items", headers=auth_headers)
    assert res.status_code == 404


async def test_item_ownership_isolation(client: AsyncClient):
    from agent_gtd.auth import create_token, register_user

    # Create two users directly (bypass invite system)
    u1 = await register_user("user1@example.com", "pass123")
    headers1 = {"Authorization": f"Bearer {create_token(u1.id)}"}
    u2 = await register_user("user2@example.com", "pass123")
    headers2 = {"Authorization": f"Bearer {create_token(u2.id)}"}

    # User 1 creates an item
    res = await client.post("/api/items", json={"title": "Private"}, headers=headers1)
    iid = res.json()["id"]

    # User 2 cannot see it
    res = await client.get("/api/items", headers=headers2)
    assert len(res.json()) == 0

    res = await client.get(f"/api/items/{iid}", headers=headers2)
    assert res.status_code == 404


# --- assigned_to filter ---


async def test_filter_items_by_assigned_to(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await client.post(
        "/api/items",
        json={"title": "Claimed", "assigned_to": "agent-1", "status": "active"},
        headers=auth_headers,
    )
    await client.post(
        "/api/items",
        json={"title": "Unclaimed", "status": "active"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items", params={"assigned_to": "agent-1"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["title"] == "Claimed"


# --- created_by passthrough ---


async def test_create_item_with_created_by(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "Agent task", "created_by": "claude-code"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["created_by"] == "claude-code"


async def test_inbox_capture_with_created_by(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/inbox",
        json={"title": "Quick note", "created_by": "mcp-agent"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["created_by"] == "mcp-agent"


# --- Action endpoints: complete, claim, release ---


async def test_complete_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items",
        json={"title": "Do it", "status": "active"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    res = await client.post(f"/api/items/{item_id}/complete", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "done"
    assert res.json()["completed_at"] is not None


async def test_complete_item_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post("/api/items/nonexistent/complete", headers=auth_headers)
    assert res.status_code == 404


async def test_claim_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items",
        json={"title": "Claimable", "status": "active"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    res = await client.post(
        f"/api/items/{item_id}/claim",
        json={"agent_name": "test-agent"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["assigned_to"] == "test-agent"


async def test_claim_item_already_claimed(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "Contested", "status": "active"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    await client.post(
        f"/api/items/{item_id}/claim",
        json={"agent_name": "agent-1"},
        headers=auth_headers,
    )
    res = await client.post(
        f"/api/items/{item_id}/claim",
        json={"agent_name": "agent-2"},
        headers=auth_headers,
    )
    assert res.status_code == 409


async def test_release_item(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/items",
        json={"title": "Release me", "status": "active", "assigned_to": "agent-1"},
        headers=auth_headers,
    )
    item_id = res.json()["id"]

    res = await client.post(f"/api/items/{item_id}/release", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["assigned_to"] == ""


async def test_claim_item_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.post(
        f"/api/items/{fake_id}/claim",
        json={"agent_name": "test-agent"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_release_item_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.post(f"/api/items/{fake_id}/release", headers=auth_headers)
    assert res.status_code == 404


async def test_create_item_nonexistent_project(
    client: AsyncClient, auth_headers: dict[str, str]
):
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.post(
        f"/api/projects/{fake_id}/items",
        json={"title": "Orphan item"},
        headers=auth_headers,
    )
    assert res.status_code == 404


# --- build_engine field ---


async def test_create_item_with_build_engine(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        "/api/items",
        json={"title": "T", "project_id": project_id, "build_engine": "claude-code"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["build_engine"] == "claude-code"


async def test_create_item_build_engine_null_by_default(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["build_engine"] is None


async def test_create_item_invalid_build_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": "bad-value"},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_update_item_build_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "claude-code-ollama", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code-ollama"


@pytest.mark.parametrize(
    "engine", ["claude-code-sonnet", "claude-code-haiku", "talos-glm-flash"]
)
async def test_update_item_build_engine_new_tiers_accepted(
    client: AsyncClient, auth_headers: dict[str, str], engine: str
):
    """claude-code-sonnet and claude-code-haiku are valid BuildEngine values.

    Both were added to the dispatch service via item e261e681 and ALLOWED_BUILD_ENGINES
    via 38c19ee1.  The BuildEngine StrEnum (46ad731a) must include them — leaving them
    out causes 500s on any item read with these values (live regression caught
    2026-05-17 19:35 UTC).
    """
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": engine, "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == engine


@pytest.mark.parametrize(
    "engine",
    [
        "talos-haiku",
        "talos-sonnet",
        "talos-opus",
        "talos-qwen",
        "talos-glm",
        "talos-glm-flash",
    ],
)
async def test_create_item_talos_engines_accepted(
    client: AsyncClient, auth_headers: dict[str, str], engine: str
):
    """All five talos-* build_engine values are valid.

    Added via item 2f79463d to register the talos engine family in
    agent-gtd-dispatch. The BuildEngine StrEnum + ALLOWED_BUILD_ENGINES
    (frozenset(BuildEngine)) must include them so item.build_engine=talos-*
    round-trips through both create and update without ValidationError.
    """
    res = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": engine},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["build_engine"] == engine


async def test_update_item_rejects_unknown_talos_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A talos-* string outside the enum still 422s — the family is not open-ended."""
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "talos-bogus", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_item_response_carries_dispatch_consumed_fields():
    """Producer-side contract: ItemResponse.model_fields must include the fields
    the dispatch-side talos serializer consumes.

    The dispatch service does NOT depend on agent_gtd (cannot import
    ItemResponse), so the serialization contract is verified via a committed
    fixture on the dispatch side.  Renaming any of these here would silently
    drift the fixture — this test fails agent_gtd's OWN suite in that case,
    closing the drift window.  See item 2f79463d for the full rationale.
    """
    from agent_gtd.models import ItemResponse

    fields = set(ItemResponse.model_fields.keys())
    required = {"title", "description", "acceptance_criteria", "files_to_modify"}
    missing = required - fields
    assert not missing, (
        f"ItemResponse missing dispatch-consumed fields {missing}; "
        f"renaming here breaks the talos TaskSpec contract "
        f"(agent-gtd-dispatch/tests/fixtures/item_response.json)."
    )


@pytest.mark.parametrize(
    "engine",
    [
        "claude-code-sonnet",
        "claude-code-haiku",
        "claude-code-glm",
        "kiro",
        "talos-glm-flash",
    ],
)
async def test_create_item_settings_engines_now_valid(
    client: AsyncClient, auth_headers: dict[str, str], engine: str
):
    """Additional BuildEngine values (beyond the default) are accepted on items."""
    res = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": engine},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["build_engine"] == engine


async def test_create_item_rejects_legacy_claude_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Legacy 'claude' build_engine value is rejected — renamed to 'claude-code'."""
    res = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": "claude"},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_clear_item_build_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": "claude-code"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": None, "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] is None


# --- plan-mode build_engine override guard ---


def _run_headers(uid: str, mode: str, run_id: str = _PLAN_RUN_ID) -> dict[str, str]:
    """Authorization header for a run-scoped callback token."""
    from agent_gtd.auth import create_token

    token = create_token(uid, run_id=run_id, run_mode=mode)
    return {"Authorization": f"Bearer {token}"}


async def _make_item(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
    engine: str | None,
) -> dict:
    body: dict = {"title": "ORIGINAL", "project_id": project_id}
    if engine is not None:
        body["build_engine"] = engine
    res = await client.post("/api/items", json=body, headers=auth_headers)
    assert res.status_code == 201
    return res.json()


async def test_local_mode_patch_without_auth_header_succeeds(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
):
    """The optional run-context scheme must never reject a credential-less request.

    Local single-user mode (main.py overrides get_current_user with get_local_user)
    sends no Authorization header at all.
    """
    from agent_gtd.auth import get_current_user
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.main import app
    from agent_gtd.models import User

    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()

    db = await get_db()
    row = await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    assert row is not None
    user = User(**row_to_dict(row))

    async def _override() -> User:
        return user

    app.dependency_overrides[get_current_user] = _override
    try:
        res = await client.patch(
            f"/api/items/{item['id']}",
            json={"title": "local-mode-edit", "version": item["version"]},
        )
        assert res.status_code == 200
        assert res.json()["title"] == "local-mode-edit"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_plan_run_cannot_override_existing_build_engine(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """A plan-mode run PATCHing build_engine on an already-set item gets 403."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={
            "title": "CHANGED",
            "build_engine": "claude-code",
            "version": item["version"],
        },
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 403
    assert "may not change build_engine" in res.json()["detail"]

    after = await client.get(f"/api/items/{item['id']}", headers=auth_headers)
    assert after.status_code == 200
    data = after.json()
    assert data["build_engine"] == "claude-code-sonnet"
    assert data["title"] == "ORIGINAL"
    assert data["version"] == item["version"]


async def test_plan_run_override_block_logs_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
    user_id: str,
    caplog,
):
    """The blocked branch emits exactly one WARNING naming both engines."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    with caplog.at_level(logging.WARNING, logger="agent_gtd.services.item_service"):
        res = await client.patch(
            f"/api/items/{item['id']}",
            json={
                "title": "CHANGED",
                "build_engine": "claude-code",
                "version": item["version"],
            },
            headers=_run_headers(user_id, "plan"),
        )
    assert res.status_code == 403
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "agent_gtd.services.item_service"
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert item["id"] in msg
    assert "claude-code-sonnet" in msg
    assert "claude-code" in msg


async def test_plan_run_override_block_publishes_event(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """The blocked branch records an item_engine_override_blocked event."""
    from agent_gtd.database import get_db

    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "claude-code", "version": item["version"]},
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 403

    db = await get_db()
    rows = await db.fetch(
        "SELECT * FROM events WHERE event_type = 'item_engine_override_blocked'"
    )
    assert len(rows) == 1
    payload = json.loads(str(rows[0]["payload"]))
    assert payload["run_id"] == _PLAN_RUN_ID
    assert payload["current_engine"] == "claude-code-sonnet"
    assert payload["attempted_engine"] == "claude-code"


async def test_plan_run_clearing_build_engine_is_blocked(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """build_engine=null from a plan run is rejected, rendering 'attempted: null'."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": None, "version": item["version"]},
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 403
    assert "attempted: null" in res.json()["detail"]


async def test_plan_run_empty_string_build_engine_is_422(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """An empty-string build_engine fails request validation before the guard."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "", "version": item["version"]},
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 422


async def test_plan_run_may_set_build_engine_when_unset(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """A plan run may still SET an engine on an item that has none."""
    item = await _make_item(client, auth_headers, project_id, None)
    assert item["build_engine"] is None
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "claude-code", "version": item["version"]},
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code"


async def test_plan_run_idempotent_rewrite_is_allowed(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str, user_id: str
):
    """Re-writing the same engine is a no-op and the rest of the body applies."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={
            "title": "CHANGED",
            "build_engine": "claude-code-sonnet",
            "version": item["version"],
        },
        headers=_run_headers(user_id, "plan"),
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code-sonnet"
    assert res.json()["title"] == "CHANGED"


@pytest.mark.parametrize("mode", ["build", "manage"])
async def test_non_plan_runs_may_change_build_engine(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
    user_id: str,
    mode: str,
):
    """The guard keys strictly on plan mode — build and manage runs are unaffected."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "claude-code", "version": item["version"]},
        headers=_run_headers(user_id, mode),
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code"


async def test_human_jwt_may_change_build_engine(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """The lead's own (claimless) JWT keeps full control of build_engine."""
    item = await _make_item(client, auth_headers, project_id, "claude-code-sonnet")
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "claude-code", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code"


async def test_update_item_invalid_build_engine(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"build_engine": "bad-engine", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 422


async def test_update_item_build_engine_unchanged_when_omitted(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """PATCH without build_engine field leaves existing value unchanged."""
    create = await client.post(
        "/api/items",
        json={"title": "T", "build_engine": "claude-code"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"title": "Updated", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["build_engine"] == "claude-code"


# --- acceptance_criteria field ---


async def test_create_item_with_acceptance_criteria(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T", "acceptance_criteria": ["AC-1: Does X", "AC-2: Does Y"]},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["acceptance_criteria"] == ["AC-1: Does X", "AC-2: Does Y"]


async def test_create_item_acceptance_criteria_empty_by_default(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["acceptance_criteria"] == []


async def test_update_item_acceptance_criteria(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={
            "acceptance_criteria": ["AC-1: New criterion"],
            "version": item["version"],
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["acceptance_criteria"] == ["AC-1: New criterion"]


async def test_update_item_acceptance_criteria_clear(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post(
        "/api/items",
        json={"title": "T", "acceptance_criteria": ["AC-1"]},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"acceptance_criteria": [], "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["acceptance_criteria"] == []


async def test_update_item_acceptance_criteria_unchanged_when_omitted(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """PATCH without acceptance_criteria leaves existing value unchanged."""
    create = await client.post(
        "/api/items",
        json={"title": "T", "acceptance_criteria": ["AC-1"]},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"title": "Updated", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["acceptance_criteria"] == ["AC-1"]


# --- files_to_modify field ---


async def test_create_item_with_files_to_modify(
    client: AsyncClient, auth_headers: dict[str, str]
):
    specs = [
        {"path": "src/foo.py", "change": "Add function"},
        {"path": "tests/test_foo.py", "change": "Add test"},
    ]
    res = await client.post(
        "/api/items",
        json={"title": "T", "files_to_modify": specs},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["files_to_modify"] == specs


async def test_create_item_files_to_modify_empty_by_default(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["files_to_modify"] == []


async def test_update_item_files_to_modify(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    specs = [{"path": "src/bar.py", "change": "Update logic"}]
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"files_to_modify": specs, "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["files_to_modify"] == specs


async def test_update_item_files_to_modify_clear(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post(
        "/api/items",
        json={"title": "T", "files_to_modify": [{"path": "src/foo.py", "change": "X"}]},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"files_to_modify": [], "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["files_to_modify"] == []


async def test_update_item_files_to_modify_unchanged_when_omitted(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """PATCH without files_to_modify leaves existing value unchanged."""
    specs = [{"path": "src/main.py", "change": "Update"}]
    create = await client.post(
        "/api/items",
        json={"title": "T", "files_to_modify": specs},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"title": "Updated", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["files_to_modify"] == specs


# --- scope_out field ---


async def test_create_item_with_scope_out(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T", "scope_out": ["Mobile app", "i18n"]},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["scope_out"] == ["Mobile app", "i18n"]


async def test_create_item_scope_out_empty_by_default(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items",
        json={"title": "T"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["scope_out"] == []


async def test_update_item_scope_out(client: AsyncClient, auth_headers: dict[str, str]):
    create = await client.post("/api/items", json={"title": "T"}, headers=auth_headers)
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"scope_out": ["Not this sprint"], "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["scope_out"] == ["Not this sprint"]


async def test_update_item_scope_out_clear(
    client: AsyncClient, auth_headers: dict[str, str]
):
    create = await client.post(
        "/api/items",
        json={"title": "T", "scope_out": ["Out of scope item"]},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"scope_out": [], "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["scope_out"] == []


async def test_update_item_scope_out_unchanged_when_omitted(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """PATCH without scope_out leaves existing value unchanged."""
    create = await client.post(
        "/api/items",
        json={"title": "T", "scope_out": ["Not now"]},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"title": "Updated", "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["scope_out"] == ["Not now"]


# --- project_id move (AC-6, AC-7, AC-8, AC-9) ---


async def test_move_item_between_projects(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Happy path: move item from project A to project B."""
    # Create two projects
    res_a = await client.post(
        "/api/projects",
        json={"name": "Project A"},
        headers=auth_headers,
    )
    assert res_a.status_code == 201
    project_a = res_a.json()["id"]

    res_b = await client.post(
        "/api/projects",
        json={"name": "Project B"},
        headers=auth_headers,
    )
    assert res_b.status_code == 201
    project_b = res_b.json()["id"]

    # Create item in project A with extra fields to verify they're preserved
    create = await client.post(
        "/api/items",
        json={
            "title": "Moveable task",
            "description": "Some description",
            "project_id": project_a,
            "acceptance_criteria": ["AC-1: Works"],
            "scope_out": ["Not now"],
        },
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()
    assert item["project_id"] == project_a
    initial_version = item["version"]

    # Move item to project B
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"project_id": project_b, "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    updated = res.json()

    # project_id updated, version incremented
    assert updated["project_id"] == project_b
    assert updated["version"] == initial_version + 1

    # Other fields preserved
    assert updated["title"] == "Moveable task"
    assert updated["description"] == "Some description"
    assert updated["acceptance_criteria"] == ["AC-1: Works"]
    assert updated["scope_out"] == ["Not now"]


async def test_move_item_to_inaccessible_project(client: AsyncClient):
    """Moving an item to another user's project returns 404."""
    from agent_gtd.auth import create_token, register_user

    # Create two users
    u1 = await register_user("mover@example.com", "pass123")
    headers1 = {"Authorization": f"Bearer {create_token(u1.id)}"}
    u2 = await register_user("owner@example.com", "pass123")
    headers2 = {"Authorization": f"Bearer {create_token(u2.id)}"}

    # User 1 creates an item in their own project
    res = await client.post(
        "/api/projects", json={"name": "User1 Project"}, headers=headers1
    )
    assert res.status_code == 201
    project1 = res.json()["id"]

    create = await client.post(
        "/api/items",
        json={"title": "User1 item", "project_id": project1},
        headers=headers1,
    )
    assert create.status_code == 201
    item = create.json()

    # User 2 creates their own project
    res = await client.post(
        "/api/projects", json={"name": "User2 Project"}, headers=headers2
    )
    assert res.status_code == 201
    project2 = res.json()["id"]

    # User 1 tries to move their item to user 2's project — should 404
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"project_id": project2, "version": item["version"]},
        headers=headers1,
    )
    assert res.status_code == 404


async def test_move_locked_item_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Moving an item locked by a rollout returns HTTP 409."""
    from agent_gtd.database import get_db

    # Create two projects and an item in project A
    res_a = await client.post(
        "/api/projects", json={"name": "Lock Project A"}, headers=auth_headers
    )
    assert res_a.status_code == 201
    project_a = res_a.json()["id"]

    res_b = await client.post(
        "/api/projects", json={"name": "Lock Project B"}, headers=auth_headers
    )
    assert res_b.status_code == 201
    project_b = res_b.json()["id"]

    create = await client.post(
        "/api/items",
        json={"title": "Locked item", "project_id": project_a},
        headers=auth_headers,
    )
    assert create.status_code == 201
    item = create.json()

    # Directly lock the item via DB (simulating a rollout lock)
    rollout_id = str(uuid.uuid4())
    db = await get_db()
    await db.execute(
        "UPDATE items SET locked_by_rollout_id = $1 WHERE id = $2",
        rollout_id,
        item["id"],
    )

    # Attempt to move the locked item — should 409
    res = await client.patch(
        f"/api/items/{item['id']}",
        json={"project_id": project_b, "version": item["version"]},
        headers=auth_headers,
    )
    assert res.status_code == 409
