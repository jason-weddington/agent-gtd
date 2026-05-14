"""MCP tool tests using FastMCP's in-memory Client."""

import json
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_gtd.auth import generate_api_key, hash_api_key, register_user
from agent_gtd.database import get_db
from agent_gtd.mcp_backend import LocalBackend
from agent_gtd.mcp_server import _show_login, mcp
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


@pytest.fixture(autouse=True)
def _force_local_backend(monkeypatch):
    """Ensure MCP tools use LocalBackend regardless of env vars."""
    import agent_gtd.database as db_mod
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    # Clear env API key so auto-auth doesn't use the real key against the test DB
    monkeypatch.setattr(srv, "_ENV_API_KEY", "")
    # Prevent local-mode auto-session so tests must authenticate explicitly
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: False)


@pytest.fixture
async def mcp_client():
    async with Client(mcp) as c:
        yield c


# --- Login ---

# The login tool is only registered when _show_login is True
# (no AGENT_GTD_API_KEY at import time). Skip these tests when hidden.
_needs_login_tools = pytest.mark.skipif(
    not _show_login, reason="login tool not registered (API key in env)"
)


@_needs_login_tools
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


@_needs_login_tools
async def test_login_invalid_key(mcp_client):
    with pytest.raises(ToolError, match="Invalid API key"):
        await mcp_client.call_tool(
            "login",
            {
                "api_key": "agtd_bogus_key_here",
                "agent_name": "test-agent",
            },
        )


async def test_tool_without_login(monkeypatch):
    import agent_gtd.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_ENV_API_KEY", "")
    # Force HTTP mode so local-mode auto-session doesn't kick in
    monkeypatch.setattr(mcp_mod, "_HTTP_MODE", True)
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
        # list_items now returns {"items": [...], "inbox_pending_count": N}
        assert isinstance(data, dict)
        assert "items" in data


async def test_login_tools_hidden_when_api_key_set():
    """When AGENT_GTD_API_KEY is set at import, login tool is not registered."""
    from agent_gtd.mcp_server import _ENV_API_KEY

    if not _ENV_API_KEY:
        pytest.skip("AGENT_GTD_API_KEY not set in environment")
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "login" not in tool_names


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
async def registered_client(mcp_client, api_key, project_id, monkeypatch):
    import agent_gtd.mcp_server as srv

    if _show_login:
        await mcp_client.call_tool(
            "login",
            {"api_key": api_key, "agent_name": "test-agent"},
        )
    else:
        # Auto-auth via env var — set key and agent name so _get_session picks them up
        monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)
        monkeypatch.setattr(srv, "_ENV_AGENT_NAME", "test-agent")
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
    items = data["items"]
    assert len(items) == 2
    titles = {d["title"] for d in items}
    assert titles == {"Idea A", "Idea B"}
    assert all(d["project_id"] is None for d in items)


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
    assert data["status"] == "new"
    # Default status is "new" -> project-less, no project_name
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
    assert len(data["items"]) == 2


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
    items = data["items"]
    assert len(items) == 1
    assert items[0]["title"] == "In Project"


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
    items = data["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Active"


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


async def test_add_item_with_due_date(registered_client):
    """add_item stores a due_date when provided."""
    result = await registered_client.call_tool(
        "add_item",
        {
            "title": "Dated Task",
            "due_date": "2026-12-01",
        },
    )
    data = _parse_result(result)
    assert data["due_date"] == "2026-12-01"


async def test_add_item_without_due_date(registered_client):
    """add_item omitting due_date stores null."""
    result = await registered_client.call_tool(
        "add_item",
        {"title": "Undated Task"},
    )
    data = _parse_result(result)
    assert data["due_date"] is None


async def test_update_item_set_due_date(registered_client):
    """update_item with a date string sets the due_date."""
    created = await registered_client.call_tool("add_item", {"title": "No Due Date"})
    item = _parse_result(created)
    assert item["due_date"] is None

    result = await registered_client.call_tool(
        "update_item",
        {
            "item_id": item["id"],
            "version": item["version"],
            "due_date": "2027-01-15",
        },
    )
    data = _parse_result(result)
    assert data["due_date"] == "2027-01-15"


async def test_update_item_clear_due_date(registered_client):
    """update_item with due_date="" clears the due date."""
    created = await registered_client.call_tool(
        "add_item",
        {"title": "Has Due Date", "due_date": "2027-06-01"},
    )
    item = _parse_result(created)
    assert item["due_date"] == "2027-06-01"

    result = await registered_client.call_tool(
        "update_item",
        {
            "item_id": item["id"],
            "version": item["version"],
            "due_date": "",
        },
    )
    data = _parse_result(result)
    assert data["due_date"] is None


async def test_update_item_due_date_unchanged_when_omitted(registered_client):
    """update_item omitting due_date leaves the existing value unchanged."""
    created = await registered_client.call_tool(
        "add_item",
        {"title": "Sticky Due Date", "due_date": "2028-03-10"},
    )
    item = _parse_result(created)

    result = await registered_client.call_tool(
        "update_item",
        {
            "item_id": item["id"],
            "version": item["version"],
            "title": "Renamed",
        },
    )
    data = _parse_result(result)
    assert data["title"] == "Renamed"
    assert data["due_date"] == "2028-03-10"


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


async def test_delete_item(registered_client):
    created = await registered_client.call_tool("add_item", {"title": "Delete Me"})
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "delete_item",
        {
            "item_id": item_id,
        },
    )
    data = _parse_result(result)
    assert data["status"] == "deleted"
    assert data["item_id"] == item_id

    # Verify the item is gone
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool("get_item", {"item_id": item_id})


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


async def test_delete_note(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_note", {"project_id": project_id, "title": "Delete Me"}
    )
    note_id = _parse_result(created)["id"]

    result = await registered_client.call_tool("delete_note", {"note_id": note_id})
    data = _parse_result(result)
    assert data["deleted"] is True
    assert data["note_id"] == note_id

    # Verify the note is gone
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool("get_note", {"note_id": note_id})


# --- update_project ---


async def test_update_project(registered_client, project_id):
    result = await registered_client.call_tool(
        "update_project",
        {
            "project_id": project_id,
            "name": "Renamed Project",
            "description": "Updated desc",
        },
    )
    data = _parse_result(result)
    assert data["name"] == "Renamed Project"
    assert data["description"] == "Updated desc"
    assert data["id"] == project_id


async def test_update_project_partial(registered_client, project_id):
    """Updating only one field leaves others unchanged."""
    # Get original state
    orig = _parse_result(await registered_client.call_tool("list_projects"))
    orig_project = next(p for p in orig if p["id"] == project_id)

    result = await registered_client.call_tool(
        "update_project",
        {
            "project_id": project_id,
            "status": "on_hold",
        },
    )
    data = _parse_result(result)
    assert data["status"] == "on_hold"
    assert data["name"] == orig_project["name"]


# --- Error branches for coverage ---


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


async def test_delete_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "delete_item",
            {
                "item_id": "nonexistent",
            },
        )


async def test_delete_note_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "delete_note",
            {
                "note_id": "nonexistent",
            },
        )


async def test_update_project_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "update_project",
            {
                "project_id": "nonexistent",
                "name": "Nope",
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


async def test_session_isolation(user_id, api_key, monkeypatch):
    """Two clients with different project_id filters see different items."""
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)

    db = await get_db()
    p1 = await project_service.create_project(db, user_id, name="Project A")
    p2 = await project_service.create_project(db, user_id, name="Project B")

    async with Client(mcp) as client1, Client(mcp) as client2:
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

        assert len(r1["items"]) == 1
        assert r1["items"][0]["title"] == "P1 Item"
        assert len(r2["items"]) == 1
        assert r2["items"][0]["title"] == "P2 Item"

        # Without project_id filter, both see all items
        r_all = _parse_result(await client1.call_tool("list_items"))
        assert len(r_all["items"]) == 2


# --- Comments ---


async def test_add_project_comment(registered_client, project_id):
    result = await registered_client.call_tool(
        "add_comment",
        {
            "content_markdown": "Project looks great",
            "project_id": project_id,
        },
    )
    data = _parse_result(result)
    assert data["content_markdown"] == "Project looks great"
    assert data["project_id"] == project_id
    assert data["item_id"] is None
    assert data["created_by"] == "test-agent"


async def test_add_item_comment(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_item",
        {"title": "Commentable", "status": "next_action", "project_id": project_id},
    )
    item_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "add_comment",
        {
            "content_markdown": "Working on it",
            "item_id": item_id,
        },
    )
    data = _parse_result(result)
    assert data["content_markdown"] == "Working on it"
    assert data["item_id"] == item_id
    assert data["project_id"] is None


async def test_add_comment_requires_parent(registered_client):
    with pytest.raises(ToolError, match="Either project_id or item_id"):
        await registered_client.call_tool(
            "add_comment",
            {"content_markdown": "Orphan"},
        )


async def test_add_comment_exclusive_parent(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_item",
        {"title": "Item", "status": "next_action", "project_id": project_id},
    )
    item_id = _parse_result(created)["id"]

    with pytest.raises(ToolError, match="only one"):
        await registered_client.call_tool(
            "add_comment",
            {
                "content_markdown": "Both",
                "project_id": project_id,
                "item_id": item_id,
            },
        )


async def test_list_comments(registered_client, project_id):
    await registered_client.call_tool(
        "add_comment",
        {"content_markdown": "Comment 1", "project_id": project_id},
    )
    await registered_client.call_tool(
        "add_comment",
        {"content_markdown": "Comment 2", "project_id": project_id},
    )

    result = await registered_client.call_tool(
        "list_comments", {"project_id": project_id}
    )
    data = _parse_result(result)
    assert len(data) == 2


async def test_update_comment(registered_client, project_id):
    created = await registered_client.call_tool(
        "add_comment",
        {"content_markdown": "Original", "project_id": project_id},
    )
    comment_id = _parse_result(created)["id"]

    result = await registered_client.call_tool(
        "update_comment",
        {"comment_id": comment_id, "content_markdown": "Edited"},
    )
    data = _parse_result(result)
    assert data["content_markdown"] == "Edited"


async def test_update_comment_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "update_comment",
            {"comment_id": "nonexistent", "content_markdown": "Nope"},
        )


async def test_comment_attribution_build_agent(api_key, project_id, monkeypatch):
    """Build-agent attribution flows through to comment created_by."""
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)
    monkeypatch.setattr(srv, "_ENV_AGENT_NAME", "claude-build-abc12345")

    async with Client(mcp) as c:
        result = await c.call_tool(
            "add_comment",
            {"content_markdown": "Build agent comment", "project_id": project_id},
        )
    data = _parse_result(result)
    assert data["created_by"] == "claude-build-abc12345"


async def test_comment_attribution_lead_derived(api_key, project_id, monkeypatch):
    """When AGENT_GTD_AGENT_NAME is absent, lead identity is derived from user_id."""
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)
    monkeypatch.setattr(srv, "_ENV_AGENT_NAME", None)

    async with Client(mcp) as c:
        result = await c.call_tool(
            "add_comment",
            {"content_markdown": "Lead comment", "project_id": project_id},
        )
    data = _parse_result(result)
    assert data["created_by"].startswith("claude-lead-")
    assert len(data["created_by"]) == len("claude-lead-") + 8


# --- Blockers ---


async def test_add_blocker(registered_client):
    task = await registered_client.call_tool("add_item", {"title": "Task"})
    task_id = _parse_result(task)["id"]
    blocker = await registered_client.call_tool("add_item", {"title": "Blocker"})
    blocker_id = _parse_result(blocker)["id"]

    result = await registered_client.call_tool(
        "add_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )
    data = _parse_result(result)
    assert data["id"] == blocker_id
    assert data["title"] == "Blocker"
    assert "status" in data
    assert "project_id" in data


async def test_add_blocker_idempotent(registered_client):
    """Adding the same blocker twice returns the same result without error."""
    task = await registered_client.call_tool("add_item", {"title": "Task"})
    task_id = _parse_result(task)["id"]
    blocker = await registered_client.call_tool("add_item", {"title": "Blocker"})
    blocker_id = _parse_result(blocker)["id"]

    await registered_client.call_tool(
        "add_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )
    result = await registered_client.call_tool(
        "add_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )
    data = _parse_result(result)
    assert data["id"] == blocker_id


async def test_add_blocker_self_block(registered_client):
    task = await registered_client.call_tool("add_item", {"title": "Self"})
    task_id = _parse_result(task)["id"]

    with pytest.raises(ToolError, match="cannot block itself"):
        await registered_client.call_tool(
            "add_blocker",
            {"item_id": task_id, "blocker_item_id": task_id},
        )


async def test_add_blocker_cycle(registered_client):
    """Adding a blocker that would create a cycle raises ToolError."""
    a = await registered_client.call_tool("add_item", {"title": "A"})
    a_id = _parse_result(a)["id"]
    b = await registered_client.call_tool("add_item", {"title": "B"})
    b_id = _parse_result(b)["id"]

    # A is blocked by B
    await registered_client.call_tool(
        "add_blocker",
        {"item_id": a_id, "blocker_item_id": b_id},
    )
    # B blocked by A would create a cycle
    with pytest.raises(ToolError, match="cycle"):
        await registered_client.call_tool(
            "add_blocker",
            {"item_id": b_id, "blocker_item_id": a_id},
        )


async def test_add_blocker_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "add_blocker",
            {"item_id": "nonexistent", "blocker_item_id": "also-nonexistent"},
        )


async def test_list_blockers(registered_client):
    task = await registered_client.call_tool("add_item", {"title": "Task"})
    task_id = _parse_result(task)["id"]
    blocker = await registered_client.call_tool("add_item", {"title": "Blocker"})
    blocker_id = _parse_result(blocker)["id"]

    await registered_client.call_tool(
        "add_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )

    result = await registered_client.call_tool("list_blockers", {"item_id": task_id})
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == blocker_id
    assert data[0]["title"] == "Blocker"
    assert "status" in data[0]
    assert "project_id" in data[0]


async def test_list_blockers_empty(registered_client):
    task = await registered_client.call_tool("add_item", {"title": "No Blockers"})
    task_id = _parse_result(task)["id"]

    result = await registered_client.call_tool("list_blockers", {"item_id": task_id})
    data = _parse_result(result)
    assert data == []


async def test_list_blockers_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool("list_blockers", {"item_id": "nonexistent"})


async def test_remove_blocker(registered_client):
    task = await registered_client.call_tool("add_item", {"title": "Task"})
    task_id = _parse_result(task)["id"]
    blocker = await registered_client.call_tool("add_item", {"title": "Blocker"})
    blocker_id = _parse_result(blocker)["id"]

    await registered_client.call_tool(
        "add_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )

    result = await registered_client.call_tool(
        "remove_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )
    data = _parse_result(result)
    assert data["ok"] is True

    # Verify gone
    blockers = _parse_result(
        await registered_client.call_tool("list_blockers", {"item_id": task_id})
    )
    assert blockers == []


async def test_remove_blocker_noop(registered_client):
    """Removing a non-existent blocker relationship is a no-op (returns ok)."""
    task = await registered_client.call_tool("add_item", {"title": "Task"})
    task_id = _parse_result(task)["id"]
    blocker = await registered_client.call_tool("add_item", {"title": "Blocker"})
    blocker_id = _parse_result(blocker)["id"]

    result = await registered_client.call_tool(
        "remove_blocker",
        {"item_id": task_id, "blocker_item_id": blocker_id},
    )
    data = _parse_result(result)
    assert data["ok"] is True


async def test_remove_blocker_item_not_found(registered_client):
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "remove_blocker",
            {"item_id": "nonexistent", "blocker_item_id": "also-nonexistent"},
        )


# --- Sharing (member management) ---


@pytest.fixture
async def other_user(user_id):
    """A second user to add as project member."""
    return await register_user("member_mcp@example.com", "testpass123")


async def test_share_project(registered_client, project_id, other_user):
    """share_project adds a member and returns member summary."""
    result = await registered_client.call_tool(
        "share_project",
        {"project_id": project_id, "email": "member_mcp@example.com"},
    )
    data = _parse_result(result)
    assert data["email"] == "member_mcp@example.com"
    assert "user_id" in data
    assert "added_at" in data


async def test_share_project_not_found(registered_client):
    """share_project raises ToolError when project doesn't exist."""
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "share_project",
            {"project_id": "nonexistent", "email": "member_mcp@example.com"},
        )


async def test_share_project_unknown_email(registered_client, project_id):
    """share_project raises ToolError when email doesn't match any user."""
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "share_project",
            {"project_id": project_id, "email": "nobody@example.com"},
        )


async def test_share_project_idempotent(registered_client, project_id, other_user):
    """share_project is idempotent — second call returns existing membership."""
    first = _parse_result(
        await registered_client.call_tool(
            "share_project",
            {"project_id": project_id, "email": "member_mcp@example.com"},
        )
    )
    second = _parse_result(
        await registered_client.call_tool(
            "share_project",
            {"project_id": project_id, "email": "member_mcp@example.com"},
        )
    )
    assert first["user_id"] == second["user_id"]
    assert first["added_at"] == second["added_at"]


async def test_list_project_members_empty(registered_client, project_id):
    """list_project_members returns empty list when no members."""
    result = await registered_client.call_tool(
        "list_project_members",
        {"project_id": project_id},
    )
    data = _parse_result(result)
    assert data == []


async def test_list_project_members(registered_client, project_id, other_user):
    """list_project_members returns members after share_project."""
    await registered_client.call_tool(
        "share_project",
        {"project_id": project_id, "email": "member_mcp@example.com"},
    )
    result = await registered_client.call_tool(
        "list_project_members",
        {"project_id": project_id},
    )
    data = _parse_result(result)
    assert len(data) == 1
    assert data[0]["email"] == "member_mcp@example.com"


async def test_list_project_members_not_found(registered_client):
    """list_project_members raises ToolError for nonexistent project."""
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "list_project_members",
            {"project_id": "nonexistent"},
        )


async def test_unshare_project(registered_client, project_id, other_user):
    """unshare_project removes a member and returns {ok: true}."""
    await registered_client.call_tool(
        "share_project",
        {"project_id": project_id, "email": "member_mcp@example.com"},
    )

    result = await registered_client.call_tool(
        "unshare_project",
        {"project_id": project_id, "email": "member_mcp@example.com"},
    )
    data = _parse_result(result)
    assert data["ok"] is True

    # Member is gone
    members = _parse_result(
        await registered_client.call_tool(
            "list_project_members",
            {"project_id": project_id},
        )
    )
    assert members == []


async def test_unshare_project_noop(registered_client, project_id, other_user):
    """unshare_project is a no-op when user is not a member."""
    result = await registered_client.call_tool(
        "unshare_project",
        {"project_id": project_id, "email": "member_mcp@example.com"},
    )
    data = _parse_result(result)
    assert data["ok"] is True


async def test_unshare_project_not_found(registered_client):
    """unshare_project raises ToolError for nonexistent project."""
    with pytest.raises(ToolError, match="not found"):
        await registered_client.call_tool(
            "unshare_project",
            {"project_id": "nonexistent", "email": "member_mcp@example.com"},
        )


# ---------------------------------------------------------------------------
# Blocker enforcement — MCP tools
# ---------------------------------------------------------------------------


async def test_update_item_blocked_status_active(registered_client):
    """MCP update_item(status=active) with unresolved blocker raises ToolError."""
    # Create two inbox items and add a blocker relationship
    item_result = await registered_client.call_tool(
        "add_item",
        {"title": "Blocked task", "status": "new"},
    )
    item_id = _parse_result(item_result)["id"]

    blocker_result = await registered_client.call_tool(
        "add_item",
        {"title": "Unresolved blocker", "status": "new"},
    )
    blocker_id = _parse_result(blocker_result)["id"]

    await registered_client.call_tool(
        "add_blocker",
        {"item_id": item_id, "blocker_item_id": blocker_id},
    )

    # Get the item to retrieve its current version
    item_data = _parse_result(
        await registered_client.call_tool("get_item", {"item_id": item_id})
    )

    with pytest.raises(ToolError, match="unresolved blocker"):
        await registered_client.call_tool(
            "update_item",
            {"item_id": item_id, "version": item_data["version"], "status": "active"},
        )


async def test_dispatch_item_blocked(registered_client, user_id):
    """MCP dispatch_item with unresolved blocker raises ToolError."""
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    # Create a project with git_origin (required for dispatch)
    db = await get_db()
    project = await project_service.create_project(
        db,
        user_id,
        name="Dispatch Test Project",
        git_origin="git@github.com:test/repo.git",
    )
    proj_id = project["id"]

    # Create item and blocker in the same project
    item_result = await registered_client.call_tool(
        "add_item",
        {"title": "Task to dispatch", "project_id": proj_id, "status": "new"},
    )
    item_id = _parse_result(item_result)["id"]

    blocker_result = await registered_client.call_tool(
        "add_item",
        {"title": "Must finish first", "project_id": proj_id, "status": "new"},
    )
    blocker_id = _parse_result(blocker_result)["id"]

    await registered_client.call_tool(
        "add_blocker",
        {"item_id": item_id, "blocker_item_id": blocker_id},
    )

    with pytest.raises(ToolError, match="unresolved blocker"):
        await registered_client.call_tool(
            "dispatch_item",
            {"item_id": item_id},
        )


async def test_dispatch_item_manage_mode_requires_rollout_id(
    registered_client, user_id
):
    """dispatch_item raises ToolError when mode='manage' and rollout_id is missing."""
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    db = await get_db()
    project = await project_service.create_project(
        db,
        user_id,
        name="Manage Test Project",
        git_origin="git@github.com:test/manage-repo.git",
    )
    item_result = await registered_client.call_tool(
        "add_item",
        {"title": "Manager task", "project_id": project["id"], "status": "new"},
    )
    item_id = _parse_result(item_result)["id"]

    with pytest.raises(ToolError, match="rollout_id is required"):
        await registered_client.call_tool(
            "dispatch_item",
            {"item_id": item_id, "mode": "manage"},
        )


async def test_dispatch_item_manage_mode_passes_rollout_id_to_backend(
    registered_client, user_id, monkeypatch
):
    """dispatch_item with mode='manage' forwards rollout_id to the backend."""
    import uuid

    import agent_gtd.mcp_server as srv
    from agent_gtd.mcp_backend import LocalBackend

    captured: dict = {}

    class _CapturingBackend(LocalBackend):
        async def dispatch_item(
            self,
            backend_user_id,
            backend_item_id,
            *,
            max_turns=None,
            mode="build",
            rollout_id=None,
        ):
            captured["mode"] = mode
            captured["rollout_id"] = rollout_id
            # Return a minimal run dict to avoid DB interaction
            raise RuntimeError("captured")

    monkeypatch.setattr(srv, "_backend", _CapturingBackend())

    from agent_gtd.database import get_db
    from agent_gtd.services import project_service

    db = await get_db()
    project = await project_service.create_project(
        db,
        user_id,
        name="Manage Capture Project",
        git_origin="git@github.com:test/capture-repo.git",
    )
    item_result = await registered_client.call_tool(
        "add_item",
        {"title": "Capture task", "project_id": project["id"], "status": "new"},
    )
    item_id = _parse_result(item_result)["id"]
    fake_wave_id = str(uuid.uuid4())

    with pytest.raises(ToolError):
        await registered_client.call_tool(
            "dispatch_item",
            {"item_id": item_id, "mode": "manage", "rollout_id": fake_wave_id},
        )

    assert captured.get("mode") == "manage"
    assert captured.get("rollout_id") == fake_wave_id


# --- Dispatch config via MCP ---


async def test_update_project_git_origin(registered_client, project_id):
    """update_project can set git_origin on an existing project."""
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "git_origin": "git@github.com:test/repo.git"},
    )
    data = _parse_result(result)
    assert data["git_origin"] == "git@github.com:test/repo.git"


async def test_update_project_kb_project_ref(registered_client, project_id):
    """update_project can set kb_project_ref on an existing project."""
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "kb_project_ref": "my-kb-ref"},
    )
    data = _parse_result(result)
    assert data["kb_project_ref"] == "my-kb-ref"


async def test_update_project_dispatch_max_turns(registered_client, project_id):
    """update_project can set and clear dispatch_max_turns."""
    # Set it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "dispatch_max_turns": 50},
    )
    data = _parse_result(result)
    assert data["dispatch_max_turns"] == 50

    # Clear it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "clear_dispatch_max_turns": True},
    )
    data = _parse_result(result)
    assert data["dispatch_max_turns"] is None


async def test_update_project_dispatch_timeout_minutes(registered_client, project_id):
    """update_project can set and clear dispatch_timeout_minutes."""
    # Set it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "dispatch_timeout_minutes": 60},
    )
    data = _parse_result(result)
    assert data["dispatch_timeout_minutes"] == 60

    # Clear it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "clear_dispatch_timeout_minutes": True},
    )
    data = _parse_result(result)
    assert data["dispatch_timeout_minutes"] is None


async def test_update_project_plan_dispatch_agent(registered_client, project_id):
    """update_project can set and clear plan_dispatch_agent."""
    # Set it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "plan_dispatch_agent": "claude-opus-4-5"},
    )
    data = _parse_result(result)
    assert data["plan_dispatch_agent"] == "claude-opus-4-5"

    # Clear it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "clear_plan_dispatch_agent": True},
    )
    data = _parse_result(result)
    assert data["plan_dispatch_agent"] is None


async def test_update_project_build_dispatch_agent(registered_client, project_id):
    """update_project can set and clear build_dispatch_agent."""
    # Set it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "build_dispatch_agent": "claude-sonnet-4-5"},
    )
    data = _parse_result(result)
    assert data["build_dispatch_agent"] == "claude-sonnet-4-5"

    # Clear it
    result = await registered_client.call_tool(
        "update_project",
        {"project_id": project_id, "clear_build_dispatch_agent": True},
    )
    data = _parse_result(result)
    assert data["build_dispatch_agent"] is None


async def test_add_project_with_dispatch_overrides(registered_client):
    """add_project can set dispatch overrides at creation time."""
    result = await registered_client.call_tool(
        "add_project",
        {
            "name": "Dispatch Project",
            "git_origin": "git@github.com:test/repo.git",
            "dispatch_max_turns": 100,
            "dispatch_timeout_minutes": 30,
            "plan_dispatch_agent": "claude-opus-4-5",
            "build_dispatch_agent": "claude-sonnet-4-5",
        },
    )
    data = _parse_result(result)
    assert data["name"] == "Dispatch Project"
    assert data["git_origin"] == "git@github.com:test/repo.git"
    assert data["dispatch_max_turns"] == 100
    assert data["dispatch_timeout_minutes"] == 30
    assert data["plan_dispatch_agent"] == "claude-opus-4-5"
    assert data["build_dispatch_agent"] == "claude-sonnet-4-5"


async def test_update_project_dispatch_max_turns_out_of_bounds(
    registered_client, project_id
):
    """update_project raises ToolError when dispatch_max_turns is out of bounds."""
    with pytest.raises(ToolError, match="dispatch_max_turns must be between"):
        await registered_client.call_tool(
            "update_project",
            {"project_id": project_id, "dispatch_max_turns": 9},
        )
    with pytest.raises(ToolError, match="dispatch_max_turns must be between"):
        await registered_client.call_tool(
            "update_project",
            {"project_id": project_id, "dispatch_max_turns": 501},
        )


async def test_update_project_dispatch_timeout_out_of_bounds(
    registered_client, project_id
):
    """update_project raises ToolError when dispatch_timeout_minutes out of bounds."""
    with pytest.raises(ToolError, match="dispatch_timeout_minutes must be between"):
        await registered_client.call_tool(
            "update_project",
            {"project_id": project_id, "dispatch_timeout_minutes": 4},
        )
    with pytest.raises(ToolError, match="dispatch_timeout_minutes must be between"):
        await registered_client.call_tool(
            "update_project",
            {"project_id": project_id, "dispatch_timeout_minutes": 481},
        )


async def test_add_project_dispatch_max_turns_out_of_bounds(registered_client):
    """add_project raises ToolError when dispatch_max_turns is out of bounds."""
    with pytest.raises(ToolError, match="dispatch_max_turns must be between"):
        await registered_client.call_tool(
            "add_project",
            {"name": "Bad Project", "dispatch_max_turns": 5},
        )


async def test_add_project_dispatch_timeout_out_of_bounds(registered_client):
    """add_project raises ToolError when dispatch_timeout_minutes is out of bounds."""
    with pytest.raises(ToolError, match="dispatch_timeout_minutes must be between"):
        await registered_client.call_tool(
            "add_project",
            {"name": "Bad Project", "dispatch_timeout_minutes": 1000},
        )


async def test_update_project_dispatch_non_owner_rejected(
    registered_client, user_id, project_id, monkeypatch
):
    """Non-owner project member cannot change dispatch-only fields."""
    import uuid
    from datetime import UTC, datetime

    import agent_gtd.mcp_server as srv
    from agent_gtd.auth import generate_api_key, hash_api_key, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services import project_service as ps

    # Register a second user and add them as a member of the project
    other_user = await register_user("other-dispatch@example.com", "otherpass123")
    db = await get_db()
    await ps.add_project_member(db, user_id, project_id, "other-dispatch@example.com")

    # Create an API key for the second user
    other_key = generate_api_key()
    h = hash_api_key(other_key)
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        str(uuid.uuid4()),
        other_user.id,
        h,
        "other-key",
        now,
    )

    # Authenticate the second user and attempt to change a dispatch-only field
    async with Client(mcp) as other_client:
        if _show_login:
            await other_client.call_tool(
                "login",
                {"api_key": other_key, "agent_name": "other-agent"},
            )
        else:
            # Auto-auth: temporarily point env key at the second user's key
            monkeypatch.setattr(srv, "_ENV_API_KEY", other_key)
            monkeypatch.setattr(srv, "_ENV_AGENT_NAME", "other-agent")

        with pytest.raises(
            ToolError, match="Only the project owner can edit dispatch settings"
        ):
            await other_client.call_tool(
                "update_project",
                {"project_id": project_id, "dispatch_max_turns": 100},
            )
