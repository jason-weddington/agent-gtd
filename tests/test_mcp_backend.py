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
    from agent_gtd.auth import create_token, register_user

    # Create user directly (bypass invite system)
    user = await register_user("test@example.com", "testpass123")
    token = create_token(user.id)
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
    from agent_gtd.auth import create_token, register_user

    # Create user directly (bypass invite system)
    user = await register_user("login@example.com", "pass123")
    token = create_token(user.id)
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

    result = await authed_backend.list_items("", status="active")
    active = result["items"]
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


async def test_delete_item(authed_backend: HttpBackend):
    item = await authed_backend.create_item("", title="To be deleted", status="active")
    result = await authed_backend.delete_item("", item["id"])
    assert result == {"status": "deleted", "item_id": item["id"]}
    with pytest.raises(ToolError):
        await authed_backend.get_item("", item["id"])


async def test_delete_item_not_found(authed_backend: HttpBackend):
    with pytest.raises(ToolError):
        await authed_backend.delete_item("", "nonexistent")


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


async def test_delete_note(authed_backend: HttpBackend, project_id: str):
    note = await authed_backend.create_note("", project_id, title="Bye")
    result = await authed_backend.delete_note("", note["id"])
    assert result["deleted"] is True
    assert result["note_id"] == note["id"]

    with pytest.raises(ToolError):
        await authed_backend.get_note("", note["id"])


async def test_update_project(authed_backend: HttpBackend, project_id: str):
    updated = await authed_backend.update_project(
        "", project_id, name="Renamed", status="on_hold"
    )
    assert updated["name"] == "Renamed"
    assert updated["status"] == "on_hold"


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


# --- Comments ---


async def test_create_project_comment(authed_backend: HttpBackend, project_id: str):
    comment = await authed_backend.create_comment(
        "",
        project_id=project_id,
        content_markdown="A project comment",
        created_by="human",
    )
    assert comment["content_markdown"] == "A project comment"
    assert comment["created_by"] == "human"
    assert comment["project_id"] == project_id


async def test_create_item_comment(authed_backend: HttpBackend, project_id: str):
    item = await authed_backend.create_item(
        "", title="Commented Item", status="active", project_id=project_id
    )
    comment = await authed_backend.create_comment(
        "",
        item_id=item["id"],
        content_markdown="An item comment",
        created_by="agent",
    )
    assert comment["content_markdown"] == "An item comment"
    assert comment["created_by"] == "agent"
    assert comment["item_id"] == item["id"]


async def test_list_comments(authed_backend: HttpBackend, project_id: str):
    await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="First"
    )
    await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="Second"
    )
    comments = await authed_backend.list_comments("", project_id=project_id)
    assert len(comments) == 2


async def test_list_comments_by_item(authed_backend: HttpBackend, project_id: str):
    item = await authed_backend.create_item(
        "", title="Item for comments", status="active", project_id=project_id
    )
    await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="Project comment"
    )
    await authed_backend.create_comment(
        "", item_id=item["id"], content_markdown="Item comment"
    )
    item_comments = await authed_backend.list_comments("", item_id=item["id"])
    assert len(item_comments) == 1
    assert item_comments[0]["content_markdown"] == "Item comment"


async def test_update_comment(authed_backend: HttpBackend, project_id: str):
    comment = await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="Original content"
    )
    updated = await authed_backend.update_comment(
        "", comment["id"], content_markdown="Updated content"
    )
    assert updated["content_markdown"] == "Updated content"
    assert updated["id"] == comment["id"]


async def test_delete_comment(authed_backend: HttpBackend, project_id: str):
    comment = await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="To be deleted"
    )
    result = await authed_backend.delete_comment("", comment["id"])
    assert result is None
    comments = await authed_backend.list_comments("", project_id=project_id)
    assert len(comments) == 0


async def test_create_comment_no_parent(authed_backend: HttpBackend):
    with pytest.raises(ToolError):
        await authed_backend.create_comment("", content_markdown="Orphan comment")


# --- Dispatch ---


@pytest.fixture(autouse=True)
def _mock_dispatch_preflight():
    """Skip the dispatch service health check in dispatch tests."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
    ):
        yield


async def _dispatch_project_and_item(
    authed_backend: HttpBackend,
) -> tuple[str, str]:
    """Create a project with git_origin and an item in it."""
    project = await authed_backend.create_project(
        "", name="Dispatch Project", git_origin="git@github.com:test/repo.git"
    )
    item = await authed_backend.create_item(
        "", title="Dispatch task", project_id=project["id"]
    )
    return project["id"], item["id"]


async def test_dispatch_item_backend(authed_backend: HttpBackend):
    _, item_id = await _dispatch_project_and_item(authed_backend)
    run = await authed_backend.dispatch_item("", item_id)
    assert run["item_id"] == item_id
    assert run["status"] == "pending"


async def test_get_run_backend(authed_backend: HttpBackend):
    _, item_id = await _dispatch_project_and_item(authed_backend)
    run = await authed_backend.dispatch_item("", item_id)
    fetched = await authed_backend.get_run("", run["id"])
    assert fetched["id"] == run["id"]


async def test_list_runs_backend(authed_backend: HttpBackend):
    _, item_id = await _dispatch_project_and_item(authed_backend)
    await authed_backend.dispatch_item("", item_id)
    runs = await authed_backend.list_runs("")
    assert len(runs) == 1
    assert runs[0]["item_id"] == item_id


async def test_list_runs_filter_item(authed_backend: HttpBackend):
    project = await authed_backend.create_project(
        "", name="Multi Project", git_origin="git@github.com:test/repo.git"
    )
    item_a = await authed_backend.create_item(
        "", title="Task A", project_id=project["id"]
    )
    item_b = await authed_backend.create_item(
        "", title="Task B", project_id=project["id"]
    )
    await authed_backend.dispatch_item("", item_a["id"])
    await authed_backend.dispatch_item("", item_b["id"])

    runs = await authed_backend.list_runs("", item_id=item_a["id"])
    assert len(runs) == 1
    assert runs[0]["item_id"] == item_a["id"]
