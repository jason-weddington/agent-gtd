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
    # The MCP list_runs passthrough surfaces engine + engine_actual verbatim;
    # a freshly dispatched run has engine_actual unset -> null.
    assert "engine" in runs[0]
    assert "engine_actual" in runs[0]
    assert runs[0]["engine_actual"] is None


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


async def test_list_dispatch_hosts_backend(authed_backend: HttpBackend):
    """HttpBackend.list_dispatch_hosts returns id/label/url with no secrets."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    db = await get_db()
    row = await db.fetchrow("SELECT id FROM users WHERE email = $1", "test@example.com")
    user_id = row["id"]
    host = await settings_service.add_dispatch_host(
        db,
        user_id,
        "pironman01",
        "https://dispatch.example.com",
        "super-secret-key",
    )

    hosts = await authed_backend.list_dispatch_hosts("")
    assert len(hosts) == 1
    returned = hosts[0]
    assert returned["id"] == host["id"]
    assert returned["label"] == "pironman01"
    assert returned["url"] == "https://dispatch.example.com"
    # Critical: no secret material — not even the masked preview.
    assert "api_key" not in returned
    assert "api_key_preview" not in returned
    assert set(returned.keys()) == {"id", "label", "url"}


# --- Workspace project fields (LocalBackend via HttpBackend) ---


async def test_create_project_workspace_mode(authed_backend: HttpBackend):
    """HttpBackend passes workspace fields through to the REST API."""
    result = await authed_backend.create_project(
        "",
        name="WS Project",
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/repo.git"],
    )
    assert result["repo_mode"] == "workspace"
    assert result["workspace_repos"] == ["https://github.com/org/repo.git"]


async def test_create_project_default_monorepo(authed_backend: HttpBackend):
    """HttpBackend defaults to monorepo when workspace fields omitted."""
    result = await authed_backend.create_project("", name="Mono")
    assert result["repo_mode"] == "monorepo"
    assert result["workspace_repos"] == []


async def test_update_project_workspace_fields(
    authed_backend: HttpBackend, project_id: str
):
    """HttpBackend update_project passes workspace fields."""
    result = await authed_backend.update_project(
        "",
        project_id,
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/repo.git"],
    )
    assert result["repo_mode"] == "workspace"
    assert result["workspace_repos"] == ["https://github.com/org/repo.git"]


# --- LocalBackend dispatch_only_touched guard for clone-target fields ---


async def test_local_backend_non_owner_repo_mode_raises():
    """LocalBackend: non-owner updating repo_mode raises ValidationError."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    owner = await register_user("lb_owner@example.com", "pass123")
    member = await register_user("lb_member@example.com", "pass123")

    db = await get_db()
    row = await project_service.create_project(db, owner.id, name="LB Test")
    pid = row["id"]
    await project_service.add_project_member(db, owner.id, pid, "lb_member@example.com")

    lb = LocalBackend()
    with pytest.raises(ValidationError, match="Only the project owner"):
        await lb.update_project(
            member.id,
            pid,
            repo_mode="workspace",
            workspace_repos=["https://github.com/org/r.git"],
        )


async def test_local_backend_owner_repo_mode_succeeds():
    """LocalBackend: owner updating repo_mode + workspace_repos succeeds."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    owner = await register_user("lb_owner2@example.com", "pass123")
    db = await get_db()
    row = await project_service.create_project(db, owner.id, name="LB Owner Test")
    pid = row["id"]

    lb = LocalBackend()
    result = await lb.update_project(
        owner.id,
        pid,
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/r.git"],
    )
    assert result["repo_mode"] == "workspace"
    assert result["workspace_repos"] == ["https://github.com/org/r.git"]


# --- list_items compact-by-default (HttpBackend) ---

_EXPECTED_COMPACT_KEYS = {
    "id",
    "title",
    "status",
    "priority",
    "build_engine",
    "project_id",
    "project_name",
    "project_repo_mode",
    "labels",
    "assigned_to",
    "created_by",
    "created_at",
    "updated_at",
    "ac_count",
    "files_count",
    "description_snippet",
}

_HEAVY_KEYS = {
    "description",
    "acceptance_criteria",
    "files_to_modify",
    "blockers",
    "user_id",
}


async def test_http_list_items_compact_keys(
    authed_backend: HttpBackend, project_id: str
):
    """Default list_items returns exactly the 16 compact keys."""
    await authed_backend.create_item(
        "", title="Compact item", status="active", project_id=project_id
    )
    result = await authed_backend.list_items("")
    items = result["items"]
    assert len(items) >= 1
    for item in items:
        assert set(item.keys()) == _EXPECTED_COMPACT_KEYS


async def test_http_list_items_compact_excludes_heavy_fields(
    authed_backend: HttpBackend, project_id: str
):
    """Compact list_items excludes heavy fields."""
    await authed_backend.create_item(
        "", title="Heavy item", status="active", project_id=project_id
    )
    result = await authed_backend.list_items("")
    items = result["items"]
    for item in items:
        for key in _HEAVY_KEYS:
            assert key not in item


async def test_http_list_items_ac_count_and_files_count(authed_backend: HttpBackend):
    """ac_count and files_count equal the source list lengths."""
    item = await authed_backend.create_item("", title="Counted", status="active")
    await authed_backend.update_item(
        "",
        item["id"],
        version=item["version"],
        acceptance_criteria=["AC one", "AC two"],
        files_to_modify=[{"path": "a.py", "change": "x"}],
    )
    result = await authed_backend.list_items("")
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["ac_count"] == 2
    assert found["files_count"] == 1


async def test_http_list_items_description_snippet_truncation(
    authed_backend: HttpBackend,
):
    """description_snippet truncates to 140 chars + ellipsis for long descriptions."""
    long_desc = "A" * 200
    item = await authed_backend.create_item(
        "", title="Long desc", status="active", description=long_desc
    )
    result = await authed_backend.list_items("")
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["description_snippet"] == "A" * 140 + "…"


async def test_http_list_items_description_snippet_short(authed_backend: HttpBackend):
    """description_snippet passes through short descriptions unchanged."""
    item = await authed_backend.create_item(
        "", title="Short desc", status="active", description="short"
    )
    result = await authed_backend.list_items("")
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["description_snippet"] == "short"


async def test_http_list_items_detail_true_returns_full_rows(
    authed_backend: HttpBackend, project_id: str
):
    """detail=True returns full rows including description/ac/files_to_modify."""
    item = await authed_backend.create_item(
        "",
        title="Full item",
        status="active",
        project_id=project_id,
        description="Full description",
    )
    await authed_backend.update_item(
        "",
        item["id"],
        version=item["version"],
        acceptance_criteria=["AC one"],
        files_to_modify=[{"path": "b.py", "change": "y"}],
    )
    result = await authed_backend.list_items("", detail=True)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert "description" in found
    assert "acceptance_criteria" in found
    assert "files_to_modify" in found


async def test_http_list_items_inbox_pending_count_compact(authed_backend: HttpBackend):
    """inbox_pending_count is present when project_id is None (compact mode)."""
    result = await authed_backend.list_items("")
    assert "inbox_pending_count" in result


async def test_http_list_items_inbox_pending_count_detail(authed_backend: HttpBackend):
    """inbox_pending_count is present when project_id is None (detail mode)."""
    result = await authed_backend.list_items("", detail=True)
    assert "inbox_pending_count" in result


async def test_http_list_items_projectless_item_project_name_none(
    authed_backend: HttpBackend,
):
    """A project-less item has project_name=None in compact mode with exact 16 keys."""
    await authed_backend.create_item("", title="Inbox item", status="inbox")
    result = await authed_backend.list_items("", status="inbox")
    items = result["items"]
    assert len(items) >= 1
    for item in items:
        assert item["project_id"] is None
        assert item["project_name"] is None
        assert set(item.keys()) == _EXPECTED_COMPACT_KEYS


# --- list_items compact-by-default (LocalBackend) ---


async def test_local_list_items_compact_keys():
    """LocalBackend default list_items returns exactly the 16 compact keys."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_compact@example.com", "pass123")
    lb = LocalBackend()
    await lb.create_item(user.id, title="LB Compact", status="active")
    result = await lb.list_items(user.id)
    items = result["items"]
    assert len(items) >= 1
    for item in items:
        assert set(item.keys()) == _EXPECTED_COMPACT_KEYS


async def test_local_list_items_compact_excludes_heavy_fields():
    """LocalBackend compact list_items excludes heavy fields including user_id."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_heavy@example.com", "pass123")
    lb = LocalBackend()
    await lb.create_item(user.id, title="LB Heavy", status="active")
    result = await lb.list_items(user.id)
    for item in result["items"]:
        for key in _HEAVY_KEYS:
            assert key not in item
        assert "user_id" not in item


async def test_local_list_items_ac_count_and_files_count():
    """LocalBackend ac_count and files_count correct when stored as raw JSON strings."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_counts@example.com", "pass123")
    lb = LocalBackend()

    # create_item does NOT accept acceptance_criteria; seed via update_item
    item = await lb.create_item(user.id, title="LB Counts", status="active")
    item_id = item["id"]
    await lb.update_item(
        user.id,
        item_id,
        version=1,
        acceptance_criteria=["AC one", "AC two"],
        files_to_modify=[{"path": "a.py", "change": "x"}],
    )

    result = await lb.list_items(user.id)
    found = next(i for i in result["items"] if i["id"] == item_id)
    assert found["ac_count"] == 2
    assert found["files_count"] == 1


async def test_local_list_items_description_snippet_truncation():
    """LocalBackend description_snippet truncates correctly."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_snippet@example.com", "pass123")
    lb = LocalBackend()
    long_desc = "B" * 200
    item = await lb.create_item(
        user.id, title="LB Snippet", status="active", description=long_desc
    )
    result = await lb.list_items(user.id)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["description_snippet"] == "B" * 140 + "…"


async def test_local_list_items_detail_true_returns_full_rows():
    """LocalBackend detail=True returns full rows including description."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_detail@example.com", "pass123")
    lb = LocalBackend()
    item = await lb.create_item(
        user.id, title="LB Detail", status="active", description="Full desc"
    )
    await lb.update_item(
        user.id,
        item["id"],
        version=1,
        acceptance_criteria=["AC one"],
    )
    result = await lb.list_items(user.id, detail=True)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert "description" in found
    assert "acceptance_criteria" in found


async def test_local_list_items_projectless_item_project_name_none():
    """LocalBackend project-less item has project_name=None with exact 16 keys."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_projectless@example.com", "pass123")
    lb = LocalBackend()
    await lb.create_item(user.id, title="LB Inbox", status="inbox")
    result = await lb.list_items(user.id, status="inbox")
    items = result["items"]
    assert len(items) >= 1
    for item in items:
        assert item["project_id"] is None
        assert item["project_name"] is None
        assert set(item.keys()) == _EXPECTED_COMPACT_KEYS


async def test_local_list_items_description_snippet_short():
    """LocalBackend description_snippet passes through short descriptions unchanged."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_snippet_short@example.com", "pass123")
    lb = LocalBackend()
    item = await lb.create_item(
        user.id, title="LB Short Snippet", status="active", description="short"
    )
    result = await lb.list_items(user.id)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["description_snippet"] == "short"


async def test_local_list_items_detail_true_files_to_modify():
    """LocalBackend detail=True includes files_to_modify as a parsed list."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_detail_files@example.com", "pass123")
    lb = LocalBackend()
    item = await lb.create_item(user.id, title="LB Detail Files", status="active")
    await lb.update_item(
        user.id,
        item["id"],
        version=1,
        files_to_modify=[{"path": "b.py", "change": "y"}],
    )
    result = await lb.list_items(user.id, detail=True)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["files_to_modify"] == [{"path": "b.py", "change": "y"}]


async def test_local_get_item_json_list_fields_parsed():
    """LocalBackend.get_item returns JSON-list fields as parsed lists."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_get_item_parity@example.com", "pass123")
    lb = LocalBackend()
    # create_item does NOT accept acceptance_criteria; seed via update_item
    item = await lb.create_item(user.id, title="LB Get Item Parity", status="active")
    await lb.update_item(
        user.id,
        item["id"],
        version=1,
        acceptance_criteria=["AC one", "AC two"],
        files_to_modify=[{"path": "a.py", "change": "x"}],
        scope_out=["drop this"],
    )
    found = await lb.get_item(user.id, item["id"])
    assert found["acceptance_criteria"] == ["AC one", "AC two"]
    assert found["files_to_modify"] == [{"path": "a.py", "change": "x"}]
    assert found["scope_out"] == ["drop this"]


async def test_local_list_items_detail_json_list_fields_parsed():
    """LocalBackend list_items(detail=True) returns JSON-list fields as parsed lists."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_detail_parity@example.com", "pass123")
    lb = LocalBackend()
    # create_item does NOT accept acceptance_criteria; seed via update_item
    item = await lb.create_item(user.id, title="LB Detail Parity", status="active")
    await lb.update_item(
        user.id,
        item["id"],
        version=1,
        acceptance_criteria=["AC one", "AC two"],
        files_to_modify=[{"path": "a.py", "change": "x"}],
        scope_out=["drop this"],
    )
    result = await lb.list_items(user.id, detail=True)
    found = next(i for i in result["items"] if i["id"] == item["id"])
    assert found["acceptance_criteria"] == ["AC one", "AC two"]
    assert found["files_to_modify"] == [{"path": "a.py", "change": "x"}]
    assert found["scope_out"] == ["drop this"]


async def test_local_list_items_inbox_pending_count_compact():
    """LocalBackend inbox_pending_count present when project_id is None (compact)."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_inbox_count_compact@example.com", "pass123")
    lb = LocalBackend()
    result = await lb.list_items(user.id)
    assert "inbox_pending_count" in result


async def test_local_list_items_inbox_pending_count_detail():
    """LocalBackend inbox_pending_count present when project_id is None (detail)."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_inbox_count_detail@example.com", "pass123")
    lb = LocalBackend()
    result = await lb.list_items(user.id, detail=True)
    assert "inbox_pending_count" in result


# --- project_repo_mode / workspace_repos (HttpBackend) ---


async def test_http_get_item_monorepo_project_repo_mode(
    authed_backend: HttpBackend, project_id: str
):
    """HttpBackend get_item mono: project_repo_mode='monorepo', no workspace_repos."""
    item = await authed_backend.create_item(
        "", title="Mono item", status="active", project_id=project_id
    )
    fetched = await authed_backend.get_item("", item["id"])
    assert fetched["project_repo_mode"] == "monorepo"
    assert "workspace_repos" not in fetched


async def test_http_get_item_workspace_project_repo_mode(authed_backend: HttpBackend):
    """HttpBackend get_item ws: project_repo_mode='workspace' + workspace_repos."""
    project = await authed_backend.create_project(
        "",
        name="WS Item Project",
        repo_mode="workspace",
        workspace_repos=[
            "https://github.com/org/a.git",
            "https://github.com/org/b.git",
        ],
    )
    item = await authed_backend.create_item(
        "", title="WS item", status="active", project_id=project["id"]
    )
    fetched = await authed_backend.get_item("", item["id"])
    assert fetched["project_repo_mode"] == "workspace"
    assert fetched["workspace_repos"] == [
        "https://github.com/org/a.git",
        "https://github.com/org/b.git",
    ]


async def test_http_get_item_projectless_repo_mode_none(authed_backend: HttpBackend):
    """HttpBackend get_item projectless: project_repo_mode None, no workspace_repos."""
    item = await authed_backend.create_item("", title="Inbox", status="inbox")
    fetched = await authed_backend.get_item("", item["id"])
    assert fetched["project_repo_mode"] is None
    assert "workspace_repos" not in fetched


async def test_http_list_items_compact_carries_project_repo_mode(
    authed_backend: HttpBackend, project_id: str
):
    """HttpBackend compact list_items carries project_repo_mode for mono/ws/None."""
    ws = await authed_backend.create_project(
        "",
        name="WS Compact Project",
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/x.git"],
    )
    await authed_backend.create_item(
        "", title="Mono item", status="active", project_id=project_id
    )
    await authed_backend.create_item(
        "", title="WS item", status="active", project_id=ws["id"]
    )
    await authed_backend.create_item("", title="Floater", status="inbox")

    result = await authed_backend.list_items("")
    by_title = {i["title"]: i for i in result["items"]}
    assert by_title["Mono item"]["project_repo_mode"] == "monorepo"
    assert by_title["WS item"]["project_repo_mode"] == "workspace"
    assert by_title["Floater"]["project_repo_mode"] is None
    # workspace_repos never lands on list rows — get_item only.
    for item in result["items"]:
        assert "workspace_repos" not in item


async def test_http_list_items_detail_has_repo_mode_no_workspace_repos(
    authed_backend: HttpBackend,
):
    """HttpBackend detail=True rows carry project_repo_mode but not workspace_repos."""
    ws = await authed_backend.create_project(
        "",
        name="WS Detail Project",
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/y.git"],
    )
    await authed_backend.create_item(
        "", title="WS detail item", status="active", project_id=ws["id"]
    )
    result = await authed_backend.list_items("", detail=True)
    found = next(i for i in result["items"] if i["title"] == "WS detail item")
    assert found["project_repo_mode"] == "workspace"
    assert "workspace_repos" not in found


# --- project_repo_mode / workspace_repos (LocalBackend) ---


async def test_local_get_item_monorepo_project_repo_mode():
    """LocalBackend get_item mono: project_repo_mode='monorepo', no workspace_repos."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    user = await register_user("lb_mono_get@example.com", "pass123")
    db = await get_db()
    proj = await project_service.create_project(db, user.id, name="LB Mono")

    lb = LocalBackend()
    item = await lb.create_item(
        user.id, title="LB mono item", status="active", project_id=proj["id"]
    )
    fetched = await lb.get_item(user.id, item["id"])
    assert fetched["project_repo_mode"] == "monorepo"
    assert "workspace_repos" not in fetched


async def test_local_get_item_workspace_project_repo_mode():
    """LocalBackend get_item ws: project_repo_mode='workspace' + workspace_repos."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    user = await register_user("lb_ws_get@example.com", "pass123")
    db = await get_db()
    proj = await project_service.create_project(
        db,
        user.id,
        name="LB WS",
        repo_mode="workspace",
        workspace_repos=[
            "https://github.com/org/a.git",
            "https://github.com/org/b.git",
        ],
    )

    lb = LocalBackend()
    item = await lb.create_item(
        user.id, title="LB ws item", status="active", project_id=proj["id"]
    )
    fetched = await lb.get_item(user.id, item["id"])
    assert fetched["project_repo_mode"] == "workspace"
    assert fetched["workspace_repos"] == [
        "https://github.com/org/a.git",
        "https://github.com/org/b.git",
    ]


async def test_local_get_item_projectless_repo_mode_none():
    """LocalBackend get_item projectless: project_repo_mode None, no workspace_repos."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_pless_get@example.com", "pass123")
    lb = LocalBackend()
    item = await lb.create_item(user.id, title="LB inbox", status="inbox")
    fetched = await lb.get_item(user.id, item["id"])
    assert fetched["project_repo_mode"] is None
    assert "workspace_repos" not in fetched


async def test_local_list_items_compact_carries_project_repo_mode():
    """LocalBackend compact list_items carries project_repo_mode for mono/ws/None."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    user = await register_user("lb_compact_rm@example.com", "pass123")
    db = await get_db()
    mono = await project_service.create_project(db, user.id, name="LB M")
    ws = await project_service.create_project(
        db,
        user.id,
        name="LB W",
        repo_mode="workspace",
        workspace_repos=["https://github.com/org/x.git"],
    )

    lb = LocalBackend()
    await lb.create_item(
        user.id, title="Mono item", status="active", project_id=mono["id"]
    )
    await lb.create_item(user.id, title="WS item", status="active", project_id=ws["id"])
    await lb.create_item(user.id, title="Floater", status="inbox")

    result = await lb.list_items(user.id)
    by_title = {i["title"]: i for i in result["items"]}
    assert by_title["Mono item"]["project_repo_mode"] == "monorepo"
    assert by_title["WS item"]["project_repo_mode"] == "workspace"
    assert by_title["Floater"]["project_repo_mode"] is None
    for item in result["items"]:
        assert "workspace_repos" not in item


# --- gate_command round-trips (LocalBackend) ---


async def test_local_backend_create_project_gate_command():
    """LocalBackend.create_project passes gate_command through to the service."""
    from agent_gtd.auth import register_user
    from agent_gtd.mcp_backend import LocalBackend

    user = await register_user("lb_gc_create@example.com", "pass")
    lb = LocalBackend()
    result = await lb.create_project(
        user.id,
        name="Gate Create",
        gate_command="uv run pytest",
    )
    assert result["gate_command"] == "uv run pytest"


async def test_local_backend_update_project_gate_command():
    """LocalBackend.update_project sets gate_command."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    user = await register_user("lb_gc_upd@example.com", "pass")
    db = await get_db()
    row = await project_service.create_project(db, user.id, name="Gate Upd LB")
    pid = row["id"]

    lb = LocalBackend()
    updated = await lb.update_project(user.id, pid, gate_command="cargo nextest run")
    assert updated["gate_command"] == "cargo nextest run"


async def test_local_backend_clear_gate_command():
    """LocalBackend.update_project clears gate_command back to None."""
    from agent_gtd.auth import register_user
    from agent_gtd.database import get_db
    from agent_gtd.mcp_backend import LocalBackend
    from agent_gtd.services import project_service

    user = await register_user("lb_gc_clear@example.com", "pass")
    db = await get_db()
    row = await project_service.create_project(
        db, user.id, name="Gate Clear LB", gate_command="npm test"
    )
    pid = row["id"]

    lb = LocalBackend()
    cleared = await lb.update_project(user.id, pid, clear_gate_command=True)
    assert cleared["gate_command"] is None
