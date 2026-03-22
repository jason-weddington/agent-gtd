"""MCP tool tests using FastMCP's in-memory Client."""

import json
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_gtd.auth import generate_api_key, hash_api_key, register_user
from agent_gtd.database import get_db
from agent_gtd.mcp_server import mcp
from agent_gtd.services import project_service


def _parse_result(result: Any) -> Any:
    """Parse a CallToolResult into Python data.

    For single dicts, result.data works fine. For lists, fastmcp's structured
    deserialization produces opaque Root objects, so we fall back to parsing
    the raw JSON text from content.
    """
    if isinstance(result.data, dict):
        return result.data
    # For lists (and anything else), parse from content text
    if result.content and hasattr(result.content[0], "text"):
        return json.loads(result.content[0].text)
    return result.data


@pytest.fixture
async def user():
    return await register_user("mcp@example.com", "testpass123")


@pytest.fixture
async def user_id(user):
    return user.id


@pytest.fixture
async def api_key(user_id):
    """Create an API key for the test user and return the plaintext key."""
    import uuid
    from datetime import UTC, datetime

    db = await get_db()
    key = generate_api_key()
    h = hash_api_key(key)
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        str(uuid.uuid4()),
        user_id,
        h,
        "test-key",
        now,
    )
    return key


@pytest.fixture
async def project(user_id):
    db = await get_db()
    return await project_service.create_project(db, user_id, name="MCP Project")


@pytest.fixture
async def project_id(project):
    return project["id"]


@pytest.fixture
async def mcp_client():
    async with Client(mcp) as c:
        yield c


# --- Login ---


async def test_login(mcp_client, api_key):
    result = await mcp_client.call_tool(
        "login",
        {
            "api_key": api_key,
            "agent_name": "test-agent",
        },
    )
    data = _parse_result(result)
    assert data["status"] == "logged_in"
    assert data["user_email"] == "mcp@example.com"
    assert data["agent_name"] == "test-agent"


async def test_login_invalid_key(mcp_client):
    with pytest.raises(ToolError, match="Invalid API key"):
        await mcp_client.call_tool(
            "login",
            {
                "api_key": "agtd_bogus_key_here",
                "agent_name": "test-agent",
            },
        )


async def test_switch_project(mcp_client, api_key, user_id, project_id):
    await mcp_client.call_tool(
        "login",
        {"api_key": api_key, "agent_name": "test-agent"},
    )

    db = await get_db()
    p2 = await project_service.create_project(db, user_id, name="Project 2")

    result = await mcp_client.call_tool(
        "switch_project",
        {"project_id": p2["id"]},
    )
    data = _parse_result(result)
    assert data["status"] == "switched"
    assert data["project_id"] == p2["id"]
    assert data["project_name"] == "Project 2"


async def test_switch_project_without_login(monkeypatch, project_id):
    import agent_gtd.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_ENV_API_KEY", "")
    async with Client(mcp) as c:
        with pytest.raises(ToolError, match="Not logged in"):
            await c.call_tool(
                "switch_project",
                {"project_id": project_id},
            )


async def test_tool_without_login(monkeypatch):
    import agent_gtd.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_ENV_API_KEY", "")
    async with Client(mcp) as c:
        with pytest.raises(ToolError, match="Not logged in"):
            await c.call_tool("list_items")


async def test_env_var_auto_login(api_key, monkeypatch):
    """AGENT_GTD_API_KEY env var auto-authenticates without explicit login."""
    import agent_gtd.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_ENV_API_KEY", api_key)

    async with Client(mcp) as c:
        # Should work without calling login first
        result = await c.call_tool("list_items")
        data = _parse_result(result)
        assert isinstance(data, list)


# --- Discovery (requires session for user_id) ---


async def test_list_projects(registered_client, project_id):
    result = await registered_client.call_tool("list_projects")
    data = _parse_result(result)
    assert len(data) == 1
    assert data[0]["id"] == project_id


async def test_list_projects_with_status_filter(registered_client, project_id):
    result = await registered_client.call_tool(
        "list_projects",
        {"status": "completed"},
    )
    data = _parse_result(result)
    assert len(data) == 0


# --- Helper to login for the remaining tests ---


@pytest.fixture
async def registered_client(mcp_client, api_key, project_id):
    await mcp_client.call_tool(
        "login",
        {"api_key": api_key, "agent_name": "test-agent"},
    )
    return mcp_client


# --- Projects ---


async def test_add_project(registered_client):
    result = await registered_client.call_tool(
        "add_project",
        {
            "name": "New Project",
            "description": "A test project",
            "area": "work",
        },
    )
    data = _parse_result(result)
    assert data["name"] == "New Project"
    assert data["description"] == "A test project"
    assert data["area"] == "work"
    assert data["status"] == "active"


async def test_add_project_then_list(registered_client):
    await registered_client.call_tool("add_project", {"name": "Extra Project"})
    result = await registered_client.call_tool("list_projects")
    data = _parse_result(result)
    # Original project + new one
    assert len(data) == 2
    names = {d["name"] for d in data}
    assert "Extra Project" in names


# --- Items ---


async def test_inbox_capture(registered_client):
    result = await registered_client.call_tool(
        "inbox_capture",
        {
            "title": "Quick thought",
        },
    )
    data = _parse_result(result)
    assert data["title"] == "Quick thought"
    assert data["status"] == "inbox"
    assert data["project_id"] is None
    assert "project_name" not in data
    assert data["created_by"] == "test-agent"


async def test_inbox_capture_then_list(registered_client):
    """Inbox items are project-less and visible via list_items(status='inbox')."""
    await registered_client.call_tool("inbox_capture", {"title": "Idea A"})
    await registered_client.call_tool("inbox_capture", {"title": "Idea B"})

    result = await registered_client.call_tool("list_items", {"status": "inbox"})
    data = _parse_result(result)
    assert len(data) == 2
    titles = {d["title"] for d in data}
    assert titles == {"Idea A", "Idea B"}
    assert all(d["project_id"] is None for d in data)


async def test_add_item_inbox_is_projectless(registered_client):
    """add_item with status='inbox' creates a project-less item."""
    result = await registered_client.call_tool(
        "add_item",
        {"title": "Inbox via add_item", "status": "inbox"},
    )
    data = _parse_result(result)
    assert data["project_id"] is None
    assert data["status"] == "inbox"


async def test_add_item(registered_client):
    result = await registered_client.call_tool(
        "add_item",
        {
            "title": "New Task",
            "description": "Do this thing",
            "priority": "high",
            "labels": ["urgent"],
        },
    )
    data = _parse_result(result)
    assert data["title"] == "New Task"
    assert data["priority"] == "high"
    assert data["labels"] == ["urgent"]
    assert data["created_by"] == "test-agent"
    # Default status is "inbox" -> project-less, no project_name
    assert "project_name" not in data


async def test_add_item_with_project(registered_client, project_id):
    """add_item with explicit project_id assigns to that project."""
    result = await registered_client.call_tool(
        "add_item",
        {
            "title": "Project Task",
            "status": "next_action",
            "project_id": project_id,
        },
    )
    data = _parse_result(result)
    assert data["project_id"] == project_id
    assert data["status"] == "next_action"


async def test_add_item_no_project(registered_client):
    """add_item with non-inbox status but no project_id creates project-less item."""
    result = await registered_client.call_tool(
        "add_item",
        {
            "title": "Floating Task",
            "status": "next_action",
        },
    )
    data = _parse_result(result)
    assert data["project_id"] is None
    assert data["status"] == "next_action"


async def test_list_items_cross_project(registered_client, project_id):
    """list_items without project_id returns items across all projects."""
    await registered_client.call_tool(
        "add_item",
        {"title": "Item 1", "status": "next_action", "project_id": project_id},
    )
    await registered_client.call_tool(
        "add_item",
        {"title": "Item 2", "status": "next_action"},
    )

    result = await registered_client.call_tool("list_items", {"status": "next_action"})
    data = _parse_result(result)
    assert len(data) == 2


async def test_list_items_filter_project(registered_client, project_id):
    """list_items with project_id only returns that project's items."""
    await registered_client.call_tool(
        "add_item",
        {"title": "In Project", "status": "next_action", "project_id": project_id},
    )
    await registered_client.call_tool(
        "add_item",
        {"title": "No Project", "status": "next_action"},
    )

    result = await registered_client.call_tool(
        "list_items", {"status": "next_action", "project_id": project_id}
    )
    data = _parse_result(result)
    assert len(data) == 1
    assert data[0]["title"] == "In Project"


async def test_list_items_filter_status(registered_client, project_id):
    await registered_client.call_tool(
        "add_item",
        {
            "title": "Active",
            "status": "active",
            "project_id": project_id,
        },
    )
    await registered_client.call_tool(
        "add_item",
        {
            "title": "Next",
            "status": "next_action",
            "project_id": project_id,
        },
    )

    result = await registered_client.call_tool("list_items", {"status": "active"})
    data = _parse_result(result)
    assert len(data) == 1
    assert data[0]["title"] == "Active"


async def test_get_item(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "Fetch Me"})
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool("get_item", {"item_id": item_id})
    data = _parse_result(result)
    assert data["title"] == "Fetch Me"


async def test_update_item_with_version(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "V1"})
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "update_item",
        {
            "item_id": item_id,
            "version": 1,
            "title": "V2",
        },
    )
    data = _parse_result(result)
    assert data["title"] == "V2"
    assert data["version"] == 2


async def test_update_item_version_conflict(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "V1"})
    item_id = _parse_result(created)["id"]

    with pytest.raises(ToolError, match="Version conflict"):
        await registered_client.call_tool(
            "update_item",
            {
                "item_id": item_id,
                "version": 99,
                "title": "Should Fail",
            },
        )


async def test_complete_item(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "To Do"})
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "complete_item",
        {
            "item_id": item_id,
        },
    )
    data = _parse_result(result)
    assert data["status"] == "done"
    assert data["completed_at"] is not None


async def test_claim_item(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "Claim Me"})
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "claim_item",
        {
            "item_id": item_id,
        },
    )
    data = _parse_result(result)
    assert data["assigned_to"] == "test-agent"


async def test_claim_item_idempotent(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "Claim Me"})
    item_id = _parse_result(created)["id"]

    await registered_client.call_tool("claim_item", {"item_id": item_id})
    result = await registered_client.call_tool("claim_item", {"item_id": item_id})
    data = _parse_result(result)
    assert data["assigned_to"] == "test-agent"


async def test_claim_item_already_claimed(registered_client, user_id, project_id):
    db = await get_db()
    from agent_gtd.services import item_service

    row = await item_service.create_item(
        db, user_id, title="Contested", project_id=project_id
    )
    await item_service.claim_item(db, user_id, row["id"], "other-agent")

    with pytest.raises(ToolError, match="already claimed"):
        await registered_client.call_tool(
            "claim_item",
            {
                "item_id": row["id"],
            },
        )


async def test_release_item(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "Release Me"})
    item_id = _parse_result(created)["id"]

    await registered_client.call_tool("claim_item", {"item_id": item_id})
    result = await registered_client.call_tool("release_item", {"item_id": item_id})
    data = _parse_result(result)
    assert data["assigned_to"] == ""


# --- Project name resolution ---


async def test_item_project_name_resolution(registered_client, project):
    """Project-scoped items include project_name matching the project."""
    result = await registered_client.call_tool(
        "add_item",
        {
            "title": "Named Project Item",
            "status": "next_action",
            "project_id": project["id"],
        },
    )
    data = _parse_result(result)
    assert data["project_name"] == project["name"]
    assert data["project_id"] == project["id"]


async def test_note_project_name_resolution(registered_client, project):
    """Notes include project_name matching the project."""
    result = await registered_client.call_tool(
        "add_note",
        {"title": "Named Project Note", "project_id": project["id"]},
    )
    data = _parse_result(result)
    assert data["project_name"] == project["name"]
    assert data["project_id"] == project["id"]


# --- Notes ---


async def test_add_note(registered_client, project_id):
    result = await registered_client.call_tool(
        "add_note",
        {
            "project_id": project_id,
            "title": "Meeting Notes",
            "content_markdown": "# Agenda\n- Item 1",
            "labels": ["meeting"],
        },
    )
    data = _parse_result(result)
    assert data["title"] == "Meeting Notes"
    assert data["labels"] == ["meeting"]


async def test_update_note(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Original"}
    )
    note_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "update_note",
        {
            "note_id": note_id,
            "title": "Updated",
        },
    )
    data = _parse_result(result)
    assert data["title"] == "Updated"


async def test_list_notes(registered_client, project_id):
    await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Note 1"}
    )
    await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Note 2"}
    )

    result = await registered_client.call_tool("list_notes")
    data = _parse_result(result)
    assert len(data) == 2


async def test_list_notes_filter_project(registered_client, user_id, project_id):
    """list_notes with project_id only returns that project's notes."""
    db = await get_db()
    p2 = await project_service.create_project(db, user_id, name="Other Project")

    await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Note in P1"}
    )
    await registered_client.call_tool(
        "add_note", {"project_id": p2["id"], "title": "Note in P2"}
    )

    result = await registered_client.call_tool("list_notes", {"project_id": project_id})
    data = _parse_result(result)
    assert len(data) == 1
    assert data[0]["title"] == "Note in P1"


async def test_list_notes_cross_project(registered_client, user_id, project_id):
    """list_notes without project_id returns notes across all projects."""
    db = await get_db()
    p2 = await project_service.create_project(db, user_id, name="Other Project")

    await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Note in P1"}
    )
    await registered_client.call_tool(
        "add_note", {"project_id": p2["id"], "title": "Note in P2"}
    )

    result = await registered_client.call_tool("list_notes")
    data = _parse_result(result)
    assert len(data) == 2


async def test_get_note(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Fetch Me"}
    )
    note_id = _parse_result(created)["id"]

    result = await registered_client.call_tool("get_note", {"note_id": note_id})
    data = _parse_result(result)
    assert data["title"] == "Fetch Me"


# --- Error branches for coverage ---


async def test_switch_project_invalid(registered_client):
    with pytest.raises(ToolError, match="Project not found"):
        await registered_client.call_tool(
            "switch_project",
            {
                "project_id": "nonexistent",
            },
        )


async def test_get_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool("get_item", {"item_id": "nonexistent"})


async def test_update_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "update_item",
            {
                "item_id": "nonexistent",
                "version": 1,
                "title": "Nope",
            },
        )


async def test_complete_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "complete_item",
            {
                "item_id": "nonexistent",
            },
        )


async def test_claim_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "claim_item",
            {
                "item_id": "nonexistent",
            },
        )


async def test_release_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "release_item",
            {
                "item_id": "nonexistent",
            },
        )


async def test_update_note_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "update_note",
            {
                "note_id": "nonexistent",
                "title": "Nope",
            },
        )


async def test_get_note_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "get_note",
            {
                "note_id": "nonexistent",
            },
        )


# --- Session isolation ---


async def test_session_isolation(user_id, api_key):
    """Two clients with different project_id filters see different items."""
    db = await get_db()
    p1 = await project_service.create_project(db, user_id, name="Project A")
    p2 = await project_service.create_project(db, user_id, name="Project B")

    async with Client(mcp) as client1, Client(mcp) as client2:
        await client1.call_tool(
            "login",
            {"api_key": api_key, "agent_name": "agent-1"},
        )
        await client2.call_tool(
            "login",
            {"api_key": api_key, "agent_name": "agent-2"},
        )

        await client1.call_tool(
            "add_item",
            {"title": "P1 Item", "status": "next_action", "project_id": p1["id"]},
        )
        await client2.call_tool(
            "add_item",
            {"title": "P2 Item", "status": "next_action", "project_id": p2["id"]},
        )

        # With project_id filter, each sees only their project's items
        r1 = _parse_result(
            await client1.call_tool("list_items", {"project_id": p1["id"]})
        )
        r2 = _parse_result(
            await client2.call_tool("list_items", {"project_id": p2["id"]})
        )

        assert len(r1) == 1
        assert r1[0]["title"] == "P1 Item"
        assert len(r2) == 1
        assert r2[0]["title"] == "P2 Item"

        # Without project_id filter, both see all items
        r_all = _parse_result(await client1.call_tool("list_items"))
        assert len(r_all) == 2
