"""Tests for MCP HttpBackend — full roundtrip via ASGI transport."""

import pytest
from fastmcp.exceptions import ToolError
from httpx import ASGITransport

from agent_gtd.main import app
from agent_gtd.mcp_backend import HttpBackend


@pytest.fixture
async def backend():
    """HttpBackend wired to the FastAPI app via ASGI transport."""
    transport = ASGITransport(app=app)
    be = HttpBackend(base_url="http://test")
    be._client = be._client.__class__(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    )
    yield be
    await be.close()


@pytest.fixture
async def authed_backend(backend: HttpBackend):
    """HttpBackend with a registered user and API key."""

    # Register a user directly via HTTP
    resp = await backend._client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create an API key
    resp = await backend._client.post(
        "/api/auth/api-keys",
        json={"name": "test-key"},
        headers=headers,
    )
    api_key = resp.json()["api_key"]

    # Login via backend
    await backend.login(api_key, "test-agent")
    return backend


@pytest.fixture
async def project_id(authed_backend: HttpBackend):
    """Create a test project and return its ID."""
    result = await authed_backend.create_project(
        "", name="Test Project", description="A test project"
    )
    return result["id"]


# --- Login ---


async def test_login(backend: HttpBackend):
    """Login validates API key and returns session info."""
    # Register user and create API key
    resp = await backend._client.post(
        "/api/auth/register",
        json={"email": "login@example.com", "password": "pass123"},
    )
    token = resp.json()["token"]
    resp = await backend._client.post(
        "/api/auth/api-keys",
        json={"name": "key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    api_key = resp.json()["api_key"]

    result = await backend.login(api_key, "my-agent")
    assert result["agent_name"] == "my-agent"
    assert result["email"] == "login@example.com"
    assert "user_id" in result


async def test_login_invalid_key(backend: HttpBackend):
    with pytest.raises(ToolError):
        await backend.login("agtd_bogus_key", "agent")


# --- Projects ---


async def test_list_projects(authed_backend: HttpBackend, project_id: str):
    projects = await authed_backend.list_projects("")
    assert len(projects) == 1
    assert projects[0]["id"] == project_id


async def test_get_project(authed_backend: HttpBackend, project_id: str):
    project = await authed_backend.get_project("", project_id)
    assert project["name"] == "Test Project"


async def test_create_project(authed_backend: HttpBackend):
    result = await authed_backend.create_project(
        "", name="New", description="desc", area="work"
    )
    assert result["name"] == "New"
    assert result["area"] == "work"


# --- Items ---


async def test_create_and_get_item(authed_backend: HttpBackend, project_id: str):
    item = await authed_backend.create_item(
        "",
        title="Do something",
        status="active",
        project_id=project_id,
        created_by="test-agent",
    )
    assert item["title"] == "Do something"
    assert item["created_by"] == "test-agent"
    assert item["project_name"] == "Test Project"

    fetched = await authed_backend.get_item("", item["id"])
    assert fetched["id"] == item["id"]


async def test_list_items_with_filters(authed_backend: HttpBackend, project_id: str):
    await authed_backend.create_item(
        "", title="Active", status="active", project_id=project_id
    )
    await authed_backend.create_item("", title="Inbox", status="inbox")

    active = await authed_backend.list_items("", status="active")
    assert len(active) == 1
    assert active[0]["title"] == "Active"


async def test_update_item(authed_backend: HttpBackend):
    item = await authed_backend.create_item("", title="Original", status="active")
    updated = await authed_backend.update_item(
        "", item["id"], version=item["version"], title="Updated"
    )
    assert updated["title"] == "Updated"
    assert updated["version"] == item["version"] + 1


async def test_complete_item(authed_backend: HttpBackend):
    item = await authed_backend.create_item("", title="Finish me", status="active")
    done = await authed_backend.complete_item("", item["id"])
    assert done["status"] == "done"
    assert done["completed_at"] is not None


async def test_claim_and_release_item(authed_backend: HttpBackend):
    item = await authed_backend.create_item("", title="Claimable", status="active")
    claimed = await authed_backend.claim_item("", item["id"], "agent-1")
    assert claimed["assigned_to"] == "agent-1"

    released = await authed_backend.release_item("", item["id"])
    assert released["assigned_to"] == ""


async def test_claim_already_claimed(authed_backend: HttpBackend):
    item = await authed_backend.create_item("", title="Contested", status="active")
    await authed_backend.claim_item("", item["id"], "agent-1")
    with pytest.raises(ToolError):
        await authed_backend.claim_item("", item["id"], "agent-2")


async def test_inbox_capture(authed_backend: HttpBackend):
    item = await authed_backend.inbox_capture(
        "", "Quick thought", created_by="mcp-agent"
    )
    assert item["title"] == "Quick thought"
    assert item["status"] == "inbox"
    assert item["created_by"] == "mcp-agent"


# --- Notes ---


async def test_create_and_get_note(authed_backend: HttpBackend, project_id: str):
    note = await authed_backend.create_note(
        "", project_id, title="My note", content_markdown="# Hello"
    )
    assert note["title"] == "My note"
    assert note["project_name"] == "Test Project"

    fetched = await authed_backend.get_note("", note["id"])
    assert fetched["content_markdown"] == "# Hello"


async def test_list_notes(authed_backend: HttpBackend, project_id: str):
    await authed_backend.create_note("", project_id, title="Note 1")
    await authed_backend.create_note("", project_id, title="Note 2")

    notes = await authed_backend.list_notes("")
    assert len(notes) == 2

    filtered = await authed_backend.list_notes("", project_id=project_id)
    assert len(filtered) == 2


async def test_update_note(authed_backend: HttpBackend, project_id: str):
    note = await authed_backend.create_note("", project_id, title="Old")
    updated = await authed_backend.update_note(
        "", note["id"], title="New", content_markdown="Updated"
    )
    assert updated["title"] == "New"
    assert updated["content_markdown"] == "Updated"


# --- Error handling ---


async def test_not_logged_in(backend: HttpBackend):
    with pytest.raises(ToolError, match="Not logged in"):
        await backend.list_items("")


async def test_item_not_found(authed_backend: HttpBackend):
    with pytest.raises(ToolError):
        await authed_backend.get_item("", "nonexistent")


async def test_note_not_found(authed_backend: HttpBackend):
    with pytest.raises(ToolError):
        await authed_backend.get_note("", "nonexistent")
