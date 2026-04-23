"""Tests for board_snapshot situational awareness in MCP backend responses."""

import pytest
from httpx import ASGITransport

from agent_gtd.main import app
from agent_gtd.mcp_backend import _TRACKED_STATUSES, HttpBackend, LocalBackend

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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
    resp = await backend._client.post(
        "/api/auth/register",
        json={"email": "bstate@example.com", "password": "testpass123"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await backend._client.post(
        "/api/auth/api-keys",
        json={"name": "test-key"},
        headers=headers,
    )
    api_key = resp.json()["api_key"]
    await backend.login(api_key, "test-agent")
    return backend


@pytest.fixture
async def project_id(authed_backend: HttpBackend) -> str:
    """Create a test project and return its ID."""
    result = await authed_backend.create_project(
        "", name="Board Test Project", description="For board state tests"
    )
    return result["id"]


@pytest.fixture
async def local_backend():
    """LocalBackend for direct service-layer tests."""
    return LocalBackend()


@pytest.fixture
async def user_id_and_project(authed_backend: HttpBackend) -> tuple[str, str]:
    """Return (user_id, project_id) for the authed backend."""
    # Get user_id via auth/me
    resp = await authed_backend._client.get(
        "/api/auth/me", headers=authed_backend._headers()
    )
    uid = resp.json()["id"]
    proj = await authed_backend.create_project("", name="Snapshot Project")
    return uid, proj["id"]


# ---------------------------------------------------------------------------
# board_snapshot service helper
# ---------------------------------------------------------------------------


async def test_board_snapshot_shape(authed_backend: HttpBackend, project_id: str):
    """board_snapshot returns all six tracked status keys, even when empty."""
    from agent_gtd.database import get_db
    from agent_gtd.services.item_service import board_snapshot

    # Get user_id
    resp = await authed_backend._client.get(
        "/api/auth/me", headers=authed_backend._headers()
    )
    user_id = resp.json()["id"]

    db = await get_db()
    snap = await board_snapshot(db, user_id, project_id)

    assert snap["project_id"] == project_id
    assert snap["project_name"] == "Board Test Project"
    for status in ("new", "ready", "next_action", "active", "review", "waiting_for"):
        assert status in snap
        assert isinstance(snap[status], list)
        assert snap[status] == []


async def test_board_snapshot_per_column_cap(
    authed_backend: HttpBackend, project_id: str
):
    """Items beyond per_column_cap get a __more__ N sentinel."""
    from agent_gtd.database import get_db
    from agent_gtd.services.item_service import board_snapshot

    resp = await authed_backend._client.get(
        "/api/auth/me", headers=authed_backend._headers()
    )
    user_id = resp.json()["id"]

    # Insert 12 new-status items
    for i in range(12):
        await authed_backend.create_item(
            "", title=f"Item {i:02d}", status="new", project_id=project_id
        )

    db = await get_db()
    snap = await board_snapshot(db, user_id, project_id)
    col = snap["new"]
    # 10 items + 1 __more__ sentinel
    assert len(col) == 11
    assert col[10] == "__more__ 2"
    # Each of the first 10 entries is a [id_prefix, title] pair
    for entry in col[:10]:
        assert isinstance(entry, list)
        assert len(entry) == 2


async def test_board_snapshot_title_truncation(
    authed_backend: HttpBackend, project_id: str
):
    """Titles are truncated to 60 characters."""
    from agent_gtd.database import get_db
    from agent_gtd.services.item_service import board_snapshot

    long_title = "A" * 80
    await authed_backend.create_item(
        "", title=long_title, status="active", project_id=project_id
    )

    resp = await authed_backend._client.get(
        "/api/auth/me", headers=authed_backend._headers()
    )
    user_id = resp.json()["id"]

    db = await get_db()
    snap = await board_snapshot(db, user_id, project_id)
    entry = snap["active"][0]
    assert len(entry[1]) == 60
    assert entry[1] == "A" * 60


async def test_board_snapshot_id_truncation(
    authed_backend: HttpBackend, project_id: str
):
    """Item IDs are truncated to 8 characters."""
    from agent_gtd.database import get_db
    from agent_gtd.services.item_service import board_snapshot

    item = await authed_backend.create_item(
        "", title="ID test", status="ready", project_id=project_id
    )

    resp = await authed_backend._client.get(
        "/api/auth/me", headers=authed_backend._headers()
    )
    user_id = resp.json()["id"]

    db = await get_db()
    snap = await board_snapshot(db, user_id, project_id)
    entry = snap["ready"][0]
    assert len(entry[0]) == 8
    assert item["id"].startswith(entry[0])


# ---------------------------------------------------------------------------
# add_item — project-scoped
# ---------------------------------------------------------------------------


async def test_add_item_with_project_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """add_item with project_id includes board_state; new item appears in snapshot."""
    result = await authed_backend.create_item(
        "", title="Feature X", status="new", project_id=project_id
    )
    assert "board_state" in result
    snap = result["board_state"]
    assert snap["project_id"] == project_id
    # The new item should appear in the 'new' column
    new_col = snap["new"]
    assert any(entry[1] == "Feature X" for entry in new_col if isinstance(entry, list))


async def test_add_item_without_project_returns_inbox_count(
    authed_backend: HttpBackend,
):
    """add_item without project_id includes inbox_pending_count, not board_state."""
    result = await authed_backend.create_item("", title="Inbox idea", status="inbox")
    assert "board_state" not in result
    assert "inbox_pending_count" in result
    assert result["inbox_pending_count"] >= 1


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


async def test_get_item_project_scoped_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """get_item on a project-scoped item includes board_state."""
    item = await authed_backend.create_item(
        "", title="Task 1", status="active", project_id=project_id
    )
    fetched = await authed_backend.get_item("", item["id"])
    assert "board_state" in fetched
    assert fetched["board_state"]["project_id"] == project_id


async def test_get_item_inbox_no_board_state(authed_backend: HttpBackend):
    """get_item on an inbox item (no project) does NOT include board_state."""
    item = await authed_backend.create_item("", title="Inbox item", status="inbox")
    fetched = await authed_backend.get_item("", item["id"])
    assert "board_state" not in fetched


# ---------------------------------------------------------------------------
# inbox_capture
# ---------------------------------------------------------------------------


async def test_inbox_capture_returns_inbox_pending_count(authed_backend: HttpBackend):
    """inbox_capture returns inbox_pending_count, not board_state."""
    result = await authed_backend.inbox_capture("", "Quick thought")
    assert "board_state" not in result
    assert "inbox_pending_count" in result
    assert result["inbox_pending_count"] >= 1


async def test_inbox_capture_count_increments(authed_backend: HttpBackend):
    """inbox_pending_count reflects the actual number of inbox items."""
    r1 = await authed_backend.inbox_capture("", "First thought")
    r2 = await authed_backend.inbox_capture("", "Second thought")
    assert r2["inbox_pending_count"] == r1["inbox_pending_count"] + 1


# ---------------------------------------------------------------------------
# list_items
# ---------------------------------------------------------------------------


async def test_list_items_no_project_id_returns_inbox_count(
    authed_backend: HttpBackend,
):
    """list_items without project_id returns inbox_pending_count, no board_state."""
    await authed_backend.inbox_capture("", "Queued thought")
    result = await authed_backend.list_items("")
    assert "items" in result
    assert "inbox_pending_count" in result
    assert "board_state" not in result
    assert result["inbox_pending_count"] >= 1


async def test_list_items_with_project_id_no_snapshot(
    authed_backend: HttpBackend, project_id: str
):
    """list_items with project_id does NOT add board_state (list IS the snapshot)."""
    result = await authed_backend.list_items("", project_id=project_id)
    assert "items" in result
    assert "board_state" not in result
    # inbox_pending_count also absent when project_id is set
    assert "inbox_pending_count" not in result


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------


async def test_update_item_project_scoped_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """update_item on a project item returns board_state."""
    item = await authed_backend.create_item(
        "", title="To update", status="new", project_id=project_id
    )
    updated = await authed_backend.update_item(
        "", item["id"], version=item["version"], status="active"
    )
    assert "board_state" in updated
    assert updated["board_state"]["project_id"] == project_id
    # Moved from new → active
    active_col = updated["board_state"]["active"]
    assert any(e[1] == "To update" for e in active_col if isinstance(e, list))


# ---------------------------------------------------------------------------
# complete_item
# ---------------------------------------------------------------------------


async def test_complete_item_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """complete_item returns board_state; completed item NOT in any column."""
    item = await authed_backend.create_item(
        "", title="Done task", status="active", project_id=project_id
    )
    done = await authed_backend.complete_item("", item["id"])
    assert done["status"] == "done"
    assert "board_state" in done
    snap = done["board_state"]
    # Completed item should not appear in any tracked column
    for status_key in _TRACKED_STATUSES:
        for entry in snap[status_key]:
            if isinstance(entry, list):
                assert entry[1] != "Done task"


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------


async def test_delete_item_with_project_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """delete_item returns board_state post-deletion; item no longer appears."""
    item = await authed_backend.create_item(
        "", title="Will be deleted", status="active", project_id=project_id
    )
    result = await authed_backend.delete_item("", item["id"])
    assert result["status"] == "deleted"
    assert "board_state" in result
    snap = result["board_state"]
    for status_key in _TRACKED_STATUSES:
        for entry in snap[status_key]:
            if isinstance(entry, list):
                assert entry[1] != "Will be deleted"


async def test_delete_item_without_project_no_board_state(authed_backend: HttpBackend):
    """delete_item on an inbox item (no project) does not include board_state."""
    item = await authed_backend.create_item("", title="Inbox trash", status="inbox")
    result = await authed_backend.delete_item("", item["id"])
    assert result["status"] == "deleted"
    assert "board_state" not in result


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


async def test_create_note_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """create_note includes board_state for the note's project."""
    note = await authed_backend.create_note(
        "", project_id, title="Architecture decision"
    )
    assert "board_state" in note
    assert note["board_state"]["project_id"] == project_id


async def test_update_note_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """update_note includes board_state."""
    note = await authed_backend.create_note("", project_id, title="Original")
    updated = await authed_backend.update_note("", note["id"], title="Updated")
    assert "board_state" in updated
    assert updated["board_state"]["project_id"] == project_id


async def test_get_note_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """get_note includes board_state for the note's project."""
    note = await authed_backend.create_note("", project_id, title="My note")
    fetched = await authed_backend.get_note("", note["id"])
    assert "board_state" in fetched
    assert fetched["board_state"]["project_id"] == project_id


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def test_add_comment_on_item_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """add_comment on a project-scoped item includes board_state."""
    item = await authed_backend.create_item(
        "", title="Commented task", status="active", project_id=project_id
    )
    comment = await authed_backend.create_comment(
        "", item_id=item["id"], content_markdown="LGTM"
    )
    assert "board_state" in comment
    assert comment["board_state"]["project_id"] == project_id


async def test_add_comment_on_project_no_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """add_comment directly on a project does NOT include board_state."""
    comment = await authed_backend.create_comment(
        "", project_id=project_id, content_markdown="Project note"
    )
    assert "board_state" not in comment


async def test_update_comment_on_item_returns_board_state(
    authed_backend: HttpBackend, project_id: str
):
    """update_comment on an item-comment includes board_state."""
    item = await authed_backend.create_item(
        "", title="Task with comment", status="active", project_id=project_id
    )
    comment = await authed_backend.create_comment(
        "", item_id=item["id"], content_markdown="Initial"
    )
    updated = await authed_backend.update_comment(
        "", comment["id"], content_markdown="Revised"
    )
    assert "board_state" in updated
    assert updated["board_state"]["project_id"] == project_id


# ---------------------------------------------------------------------------
# Shared project: member sees board_state; non-member does not
# ---------------------------------------------------------------------------


@pytest.fixture
async def second_authed_backend(backend: HttpBackend):
    """A second HttpBackend logged in as a different user."""
    resp = await backend._client.post(
        "/api/auth/register",
        json={"email": "member@example.com", "password": "pass456"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await backend._client.post(
        "/api/auth/api-keys", json={"name": "member-key"}, headers=headers
    )
    api_key = resp.json()["api_key"]

    # Create a fresh backend clone that shares the same ASGI transport
    transport = ASGITransport(app=app)
    be2 = HttpBackend(base_url="http://test")
    be2._client = be2._client.__class__(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    )
    await be2.login(api_key, "member-agent")
    yield be2
    await be2.close()


async def test_shared_project_member_gets_board_state(
    authed_backend: HttpBackend,
    second_authed_backend: HttpBackend,
    project_id: str,
):
    """A project member calling get_item receives board_state (access check passes)."""
    # Add an item to the project
    item = await authed_backend.create_item(
        "", title="Shared task", status="active", project_id=project_id
    )
    # Share the project with the second user
    await authed_backend.add_project_member("", project_id, "member@example.com")

    # Second user retrieves the item and should see board_state
    fetched = await second_authed_backend.get_item("", item["id"])
    assert "board_state" in fetched
    assert fetched["board_state"]["project_id"] == project_id


async def test_non_member_cannot_access_item(
    authed_backend: HttpBackend,
    project_id: str,
):
    """A non-member cannot get an item; board_state is never leaked."""
    from fastmcp.exceptions import ToolError

    item = await authed_backend.create_item(
        "", title="Private task", status="active", project_id=project_id
    )

    # Create a third user who is NOT a member
    transport = ASGITransport(app=app)
    intruder = HttpBackend(base_url="http://test")
    intruder._client = intruder._client.__class__(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    )
    resp = await intruder._client.post(
        "/api/auth/register",
        json={"email": "intruder@example.com", "password": "pass789"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await intruder._client.post(
        "/api/auth/api-keys", json={"name": "intruder-key"}, headers=headers
    )
    api_key = resp.json()["api_key"]
    await intruder.login(api_key, "intruder-agent")

    with pytest.raises(ToolError):
        await intruder.get_item("", item["id"])

    await intruder.close()
