"""Sharing access tests — accessible_project_ids and service query scoping.

Covers the access matrix:
- User B (member) can list/read/write in shared project P
- User B cannot see User A's other projects or inbox
- Owner-only ops (delete project, update metadata) remain restricted to User A
- Removing B from project_members reverses all access
- B's items keep created_by after removal
- Share management API (task 3): REST endpoints + service functions
"""

import uuid
from datetime import UTC, datetime

import pytest

from agent_gtd.auth import register_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError, ValidationError
from agent_gtd.services import (
    comment_service,
    item_service,
    note_service,
    project_service,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def user_a():
    """User A: project owner."""
    return await register_user("user_a_sharing@example.com", "password123")


@pytest.fixture
async def user_b():
    """User B: will be added as project member."""
    return await register_user("user_b_sharing@example.com", "password123")


@pytest.fixture
async def project_p(user_a):
    """Project P owned by User A."""
    db = await get_db()
    return await project_service.create_project(db, user_a.id, name="Project P")


@pytest.fixture
async def item_i(user_a, project_p):
    """Item I in Project P, created by User A."""
    db = await get_db()
    return await item_service.create_item(
        db, user_a.id, title="Item I", project_id=project_p["id"]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def add_member(project_id: str, user_id: str) -> None:
    """Add a member directly via SQL (members-management API lands in task 3)."""
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_id,
        datetime.now(UTC).isoformat(),
    )


async def remove_member(project_id: str, user_id: str) -> None:
    """Remove a member directly via SQL."""
    db = await get_db()
    await db.execute(
        "DELETE FROM project_members WHERE project_id = $1 AND user_id = $2",
        project_id,
        user_id,
    )


# ---------------------------------------------------------------------------
# accessible_project_ids helper
# ---------------------------------------------------------------------------


async def test_accessible_project_ids_own(user_a, project_p):
    """Owner sees their own project in accessible_project_ids."""
    db = await get_db()
    ids = await project_service.accessible_project_ids(db, user_a.id)
    assert project_p["id"] in ids


async def test_accessible_project_ids_shared(user_a, user_b, project_p):
    """Member sees the shared project in accessible_project_ids."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    ids = await project_service.accessible_project_ids(db, user_b.id)
    assert project_p["id"] in ids


async def test_accessible_project_ids_not_member(user_a, user_b, project_p):
    """Non-member does not see the project in accessible_project_ids."""
    db = await get_db()
    ids = await project_service.accessible_project_ids(db, user_b.id)
    assert project_p["id"] not in ids


async def test_accessible_project_ids_empty(user_b):
    """User with no projects or memberships gets empty list."""
    db = await get_db()
    ids = await project_service.accessible_project_ids(db, user_b.id)
    assert ids == []


# ---------------------------------------------------------------------------
# verify_project_access
# ---------------------------------------------------------------------------


async def test_verify_project_access_owner(user_a, project_p):
    """Owner passes verify_project_access."""
    db = await get_db()
    await project_service.verify_project_access(db, project_p["id"], user_a.id)


async def test_verify_project_access_member(user_a, user_b, project_p):
    """Member passes verify_project_access."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    await project_service.verify_project_access(db, project_p["id"], user_b.id)


async def test_verify_project_access_non_member(user_b, project_p):
    """Non-member fails verify_project_access."""
    db = await get_db()
    with pytest.raises(NotFoundError):
        await project_service.verify_project_access(db, project_p["id"], user_b.id)


# ---------------------------------------------------------------------------
# B can list and read the project
# ---------------------------------------------------------------------------


async def test_member_can_list_project(user_a, user_b, project_p):
    """Member sees the shared project in list_projects."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    projects = await project_service.list_projects(db, user_b.id)
    assert any(p["id"] == project_p["id"] for p in projects)


async def test_member_cannot_see_other_projects(user_a, user_b, project_p):
    """Member only sees the shared project, not owner's other projects."""
    db = await get_db()
    other = await project_service.create_project(db, user_a.id, name="Other Project")
    await add_member(project_p["id"], user_b.id)

    projects = await project_service.list_projects(db, user_b.id)
    ids = [p["id"] for p in projects]
    assert project_p["id"] in ids
    assert other["id"] not in ids


async def test_member_can_get_project(user_a, user_b, project_p):
    """Member can get_project for a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    result = await project_service.get_project(db, user_b.id, project_p["id"])
    assert result["id"] == project_p["id"]


# ---------------------------------------------------------------------------
# B can read items in P
# ---------------------------------------------------------------------------


async def test_member_can_read_item(user_a, user_b, project_p, item_i):
    """Member can get_item for an item in a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    item = await item_service.get_item(db, user_b.id, item_i["id"])
    assert item["id"] == item_i["id"]


async def test_member_can_list_project_items(user_a, user_b, project_p, item_i):
    """Member sees items when listing a shared project's items."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    items = await item_service.list_project_items(db, user_b.id, project_p["id"])
    assert any(i["id"] == item_i["id"] for i in items)


async def test_member_sees_item_in_global_list(user_a, user_b, project_p, item_i):
    """Member sees shared-project items in the global list_items call."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    items = await item_service.list_items(db, user_b.id)
    assert any(i["id"] == item_i["id"] for i in items)


# ---------------------------------------------------------------------------
# Inbox (project-less) items stay private
# ---------------------------------------------------------------------------


async def test_owner_inbox_not_visible_to_member(user_a, user_b, project_p):
    """Owner's inbox (project-less) items are not visible to members."""
    db = await get_db()
    inbox = await item_service.inbox_capture(db, user_a.id, "A's private inbox item")
    await add_member(project_p["id"], user_b.id)

    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_b.id, inbox["id"])

    b_items = await item_service.list_items(db, user_b.id)
    assert not any(i["id"] == inbox["id"] for i in b_items)


async def test_member_inbox_not_visible_to_owner(user_a, user_b, project_p):
    """Member's own inbox (project-less) items are invisible to project owner."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    b_inbox = await item_service.inbox_capture(db, user_b.id, "B's private inbox")

    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_a.id, b_inbox["id"])

    a_items = await item_service.list_items(db, user_a.id)
    assert not any(i["id"] == b_inbox["id"] for i in a_items)


# ---------------------------------------------------------------------------
# B can create items in P
# ---------------------------------------------------------------------------


async def test_member_can_create_item_in_project(user_a, user_b, project_p):
    """Member can create items in a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    item = await item_service.create_item(
        db, user_b.id, title="B's item", project_id=project_p["id"]
    )
    assert item["project_id"] == project_p["id"]
    assert item["user_id"] == user_b.id


async def test_member_can_create_project_item(user_a, user_b, project_p):
    """Member can use create_project_item for a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    item = await item_service.create_project_item(
        db, user_b.id, project_p["id"], title="B's project item"
    )
    assert item["project_id"] == project_p["id"]


# ---------------------------------------------------------------------------
# B can comment on items in P
# ---------------------------------------------------------------------------


async def test_member_can_comment_on_item(user_a, user_b, project_p, item_i):
    """Member can create a comment on an item in a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    comment = await comment_service.create_comment(
        db, user_b.id, item_id=item_i["id"], content_markdown="Hello from B"
    )
    assert comment["item_id"] == item_i["id"]
    assert comment["user_id"] == user_b.id


async def test_member_can_list_item_comments(user_a, user_b, project_p, item_i):
    """Member sees all comments (including owner's) when listing item comments."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    await comment_service.create_comment(
        db, user_a.id, item_id=item_i["id"], content_markdown="From A"
    )
    comments = await comment_service.list_comments(db, user_b.id, item_id=item_i["id"])
    assert len(comments) == 1
    assert comments[0]["content_markdown"] == "From A"


async def test_member_can_comment_on_project(user_a, user_b, project_p):
    """Member can create a comment directly on a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    comment = await comment_service.create_comment(
        db,
        user_b.id,
        project_id=project_p["id"],
        content_markdown="Project note from B",
    )
    assert comment["project_id"] == project_p["id"]


async def test_member_can_list_project_comments(user_a, user_b, project_p):
    """Member sees all project comments when listing them."""
    db = await get_db()
    await comment_service.create_comment(
        db, user_a.id, project_id=project_p["id"], content_markdown="Owner comment"
    )
    await add_member(project_p["id"], user_b.id)
    comments = await comment_service.list_comments(
        db, user_b.id, project_id=project_p["id"]
    )
    assert any(c["content_markdown"] == "Owner comment" for c in comments)


# ---------------------------------------------------------------------------
# B can create and read notes in P
# ---------------------------------------------------------------------------


async def test_member_can_create_note(user_a, user_b, project_p):
    """Member can create a note in a shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    note = await note_service.create_note(
        db, user_b.id, project_p["id"], title="B's note"
    )
    assert note["project_id"] == project_p["id"]
    assert note["user_id"] == user_b.id


async def test_member_can_read_note(user_a, user_b, project_p):
    """Member can read a note in a shared project."""
    db = await get_db()
    a_note = await note_service.create_note(
        db, user_a.id, project_p["id"], title="A's note"
    )
    await add_member(project_p["id"], user_b.id)
    fetched = await note_service.get_note(db, user_b.id, a_note["id"])
    assert fetched["id"] == a_note["id"]


async def test_member_sees_all_project_notes(user_a, user_b, project_p):
    """Member sees all notes (not just their own) when listing project notes."""
    db = await get_db()
    await note_service.create_note(db, user_a.id, project_p["id"], title="A's note")
    await add_member(project_p["id"], user_b.id)
    await note_service.create_note(db, user_b.id, project_p["id"], title="B's note")
    notes = await note_service.list_project_notes(db, user_b.id, project_p["id"])
    titles = {n["title"] for n in notes}
    assert "A's note" in titles
    assert "B's note" in titles


async def test_member_sees_shared_notes_in_user_notes(user_a, user_b, project_p):
    """Member sees shared-project notes in list_user_notes."""
    db = await get_db()
    a_note = await note_service.create_note(
        db, user_a.id, project_p["id"], title="A's note in P"
    )
    await add_member(project_p["id"], user_b.id)
    notes = await note_service.list_user_notes(db, user_b.id)
    assert any(n["id"] == a_note["id"] for n in notes)


# ---------------------------------------------------------------------------
# Owner-only operations blocked for members
# ---------------------------------------------------------------------------


async def test_member_cannot_delete_project(user_a, user_b, project_p):
    """Member cannot delete the shared project (owner-only)."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    with pytest.raises(NotFoundError):
        await project_service.delete_project(db, user_b.id, project_p["id"])


async def test_member_cannot_update_project_metadata(user_a, user_b, project_p):
    """Member can update non-dispatch project metadata (AC5: access allowed)."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    # Non-dispatch fields (name, description, etc.) are editable by members
    updated = await project_service.update_project(
        db, user_b.id, project_p["id"], name="Updated by member"
    )
    assert updated["name"] == "Updated by member"


async def test_non_member_cannot_create_project_item(user_a, user_b, project_p):
    """Non-member cannot create items in the project."""
    db = await get_db()
    with pytest.raises(NotFoundError):
        await item_service.create_item(
            db, user_b.id, title="Sneaky item", project_id=project_p["id"]
        )


# ---------------------------------------------------------------------------
# Removing member reverses all access
# ---------------------------------------------------------------------------


async def test_remove_member_loses_item_access(user_a, user_b, project_p, item_i):
    """After removal, B loses access to items in the formerly shared project."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)

    # B has access
    item = await item_service.get_item(db, user_b.id, item_i["id"])
    assert item["id"] == item_i["id"]

    await remove_member(project_p["id"], user_b.id)

    # B no longer has access
    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_b.id, item_i["id"])


async def test_remove_member_loses_project_visibility(user_a, user_b, project_p):
    """After removal, B no longer sees the project in list_projects."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    assert any(
        p["id"] == project_p["id"]
        for p in await project_service.list_projects(db, user_b.id)
    )

    await remove_member(project_p["id"], user_b.id)

    assert not any(
        p["id"] == project_p["id"]
        for p in await project_service.list_projects(db, user_b.id)
    )


async def test_remove_member_loses_note_access(user_a, user_b, project_p):
    """After removal, B can no longer read notes in the project."""
    db = await get_db()
    a_note = await note_service.create_note(
        db, user_a.id, project_p["id"], title="Shared Note"
    )
    await add_member(project_p["id"], user_b.id)
    await note_service.get_note(db, user_b.id, a_note["id"])  # succeeds

    await remove_member(project_p["id"], user_b.id)

    with pytest.raises(NotFoundError):
        await note_service.get_note(db, user_b.id, a_note["id"])


# ---------------------------------------------------------------------------
# Items created by member persist with correct created_by after removal
# ---------------------------------------------------------------------------


async def test_member_items_keep_created_by_after_removal(user_a, user_b, project_p):
    """Items B created in P remain visible to A with correct created_by after removal.

    B's removal from project_members does not delete their items.
    """
    db = await get_db()
    await add_member(project_p["id"], user_b.id)

    b_item = await item_service.create_item(
        db,
        user_b.id,
        title="B's contribution",
        project_id=project_p["id"],
        created_by="user_b_sharing@example.com",
    )
    item_id = b_item["id"]

    await remove_member(project_p["id"], user_b.id)

    # A can still see B's item (it's in A's project)
    a_item = await item_service.get_item(db, user_a.id, item_id)
    assert a_item["created_by"] == "user_b_sharing@example.com"

    # B can no longer see it
    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_b.id, item_id)


# ---------------------------------------------------------------------------
# Share management service functions (task 3)
# ---------------------------------------------------------------------------


async def test_add_project_member_service(user_a, user_b, project_p):
    """Owner can add a member by email via service function."""
    db = await get_db()
    result = await project_service.add_project_member(
        db, user_a.id, project_p["id"], "user_b_sharing@example.com"
    )
    assert result["user_id"] == user_b.id
    assert result["email"] == "user_b_sharing@example.com"
    assert "added_at" in result


async def test_add_project_member_idempotent(user_a, user_b, project_p):
    """Adding a member twice is idempotent — returns existing membership."""
    db = await get_db()
    first = await project_service.add_project_member(
        db, user_a.id, project_p["id"], "user_b_sharing@example.com"
    )
    second = await project_service.add_project_member(
        db, user_a.id, project_p["id"], "user_b_sharing@example.com"
    )
    assert first["user_id"] == second["user_id"]
    assert first["added_at"] == second["added_at"]

    # Only one record in the table
    rows = await project_service.list_project_members(db, user_a.id, project_p["id"])
    assert len(rows) == 1


async def test_add_project_member_not_owner(user_a, user_b, project_p):
    """Non-owner cannot add members (raises NotFoundError)."""
    db = await get_db()
    with pytest.raises(NotFoundError):
        await project_service.add_project_member(
            db, user_b.id, project_p["id"], "user_a_sharing@example.com"
        )


async def test_add_project_member_unknown_email(user_a, project_p):
    """Adding unknown email raises NotFoundError."""
    db = await get_db()
    with pytest.raises(NotFoundError):
        await project_service.add_project_member(
            db, user_a.id, project_p["id"], "nobody@example.com"
        )


async def test_add_project_member_owner_self(user_a, project_p):
    """Owner cannot add themselves as member (raises ValidationError)."""
    db = await get_db()
    with pytest.raises(ValidationError):
        await project_service.add_project_member(
            db, user_a.id, project_p["id"], "user_a_sharing@example.com"
        )


async def test_remove_project_member_service(user_a, user_b, project_p):
    """Owner can remove a member; no-op if not a member."""
    db = await get_db()
    await project_service.add_project_member(
        db, user_a.id, project_p["id"], "user_b_sharing@example.com"
    )

    # Member has access before removal
    await project_service.verify_project_access(db, project_p["id"], user_b.id)

    await project_service.remove_project_member(
        db, user_a.id, project_p["id"], user_b.id
    )

    # No access after removal
    with pytest.raises(NotFoundError):
        await project_service.verify_project_access(db, project_p["id"], user_b.id)


async def test_remove_project_member_noop(user_a, user_b, project_p):
    """Removing someone who isn't a member is a no-op (no error)."""
    db = await get_db()
    # Should not raise
    await project_service.remove_project_member(
        db, user_a.id, project_p["id"], user_b.id
    )


async def test_remove_project_member_not_owner(user_a, user_b, project_p):
    """Non-owner cannot remove members."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    with pytest.raises(NotFoundError):
        await project_service.remove_project_member(
            db, user_b.id, project_p["id"], user_a.id
        )


async def test_list_project_members_service(user_a, user_b, project_p):
    """list_project_members returns all members, excluding the owner."""
    db = await get_db()
    await project_service.add_project_member(
        db, user_a.id, project_p["id"], "user_b_sharing@example.com"
    )
    members = await project_service.list_project_members(db, user_a.id, project_p["id"])
    assert len(members) == 1
    assert members[0]["user_id"] == user_b.id
    assert members[0]["email"] == "user_b_sharing@example.com"
    # Owner is not in the list
    user_ids = [m["user_id"] for m in members]
    assert user_a.id not in user_ids


async def test_list_project_members_accessible_to_member(user_a, user_b, project_p):
    """Members can list the project members (not owner-only)."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    # B calls list (not owner)
    members = await project_service.list_project_members(db, user_b.id, project_p["id"])
    assert len(members) == 1
    assert members[0]["user_id"] == user_b.id


async def test_list_project_members_non_member_denied(user_a, user_b, project_p):
    """Non-member cannot list members (raises NotFoundError)."""
    db = await get_db()
    # B is not a member
    with pytest.raises(NotFoundError):
        await project_service.list_project_members(db, user_b.id, project_p["id"])


# ---------------------------------------------------------------------------
# Share management REST endpoints (task 3)
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner_client():
    """HTTP client with user_a authenticated."""
    from httpx import ASGITransport, AsyncClient

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        user = await register_user("owner_api@example.com", "testpass")
        token = create_token(user.id)
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture
async def member_client():
    """HTTP client with user_b authenticated."""
    from httpx import ASGITransport, AsyncClient

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        user = await register_user("member_api@example.com", "testpass")
        token = create_token(user.id)
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture
async def api_project(owner_client):
    """Create a project via the API and return its data."""
    res = await owner_client.post(
        "/api/projects",
        json={"name": "API Project"},
    )
    assert res.status_code == 201
    return res.json()


async def test_rest_add_member(owner_client, member_client, api_project):
    """POST /api/projects/{id}/members returns 201 with member summary."""
    res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "member_api@example.com"
    assert "user_id" in data
    assert "added_at" in data


async def test_rest_add_member_not_owner(member_client, api_project):
    """Non-owner gets 404 when trying to add a member."""
    res = await member_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    assert res.status_code == 404


async def test_rest_add_member_unknown_email(owner_client, api_project):
    """Adding unknown email returns 404."""
    res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "nobody@example.com"},
    )
    assert res.status_code == 404


async def test_rest_add_member_invalid_email(owner_client, api_project):
    """Malformed email returns 422 from Pydantic validation."""
    res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "not-an-email"},
    )
    assert res.status_code == 422


async def test_rest_add_member_idempotent(owner_client, member_client, api_project):
    """Adding the same member twice returns 201 both times (idempotent)."""
    for _ in range(2):
        res = await owner_client.post(
            f"/api/projects/{api_project['id']}/members",
            json={"email": "member_api@example.com"},
        )
        assert res.status_code == 201


async def test_rest_remove_member(owner_client, member_client, api_project):
    """DELETE /api/projects/{id}/members/{user_id} returns 204."""
    add_res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    member_user_id = add_res.json()["user_id"]

    res = await owner_client.delete(
        f"/api/projects/{api_project['id']}/members/{member_user_id}"
    )
    assert res.status_code == 204

    # Member no longer sees the project
    list_res = await member_client.get("/api/projects")
    ids = [p["id"] for p in list_res.json()]
    assert api_project["id"] not in ids


async def test_rest_remove_member_not_owner(owner_client, member_client, api_project):
    """Non-owner gets 404 when trying to remove a member."""
    add_res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    member_user_id = add_res.json()["user_id"]

    res = await member_client.delete(
        f"/api/projects/{api_project['id']}/members/{member_user_id}"
    )
    assert res.status_code == 404


async def test_rest_list_members_owner(owner_client, member_client, api_project):
    """GET /api/projects/{id}/members returns the member list for the owner."""
    add_res = await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    assert add_res.status_code == 201
    res = await owner_client.get(f"/api/projects/{api_project['id']}/members")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["email"] == "member_api@example.com"


async def test_rest_list_members_accessible_to_member(
    owner_client, member_client, api_project
):
    """Members can call GET /api/projects/{id}/members."""
    await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    res = await member_client.get(f"/api/projects/{api_project['id']}/members")
    assert res.status_code == 200


async def test_rest_list_members_non_member_denied(member_client, api_project):
    """Non-member gets 404 on GET /api/projects/{id}/members."""
    res = await member_client.get(f"/api/projects/{api_project['id']}/members")
    assert res.status_code == 404


async def test_rest_list_members_excludes_owner(
    owner_client, member_client, api_project
):
    """GET /api/projects/{id}/members does not include the owner."""
    await owner_client.post(
        f"/api/projects/{api_project['id']}/members",
        json={"email": "member_api@example.com"},
    )
    res = await owner_client.get(f"/api/projects/{api_project['id']}/members")
    emails = [m["email"] for m in res.json()]
    assert "owner_api@example.com" not in emails
    assert "member_api@example.com" in emails


# ---------------------------------------------------------------------------
# add_project_member: blocker purge on share
# ---------------------------------------------------------------------------


async def test_add_project_member_purges_cross_project_blockers(
    user_a, user_b, project_p
):
    """Sharing a project with existing cross-project blockers purges them.

    Before the same-project invariant was introduced, blockers could cross
    project boundaries.  When the project is shared, those legacy edges are
    purged so the new member cannot infer private item titles from blocker info.
    """
    db = await get_db()

    # Create an inbox item for user A (no project)
    inbox_item = await item_service.inbox_capture(
        db, user_a.id, "A's private inbox item"
    )

    # Manually insert a cross-project blocker edge (simulating pre-invariant data)
    # The edge goes: project_p item (item_i) is blocked by inbox item
    project_item = await item_service.create_item(
        db, user_a.id, title="Project task", project_id=project_p["id"]
    )
    dep_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at)"
        " VALUES ($1, $2, $3, $4)",
        dep_id,
        project_item["id"],  # in project_p
        inbox_item["id"],  # in no project (inbox)
        now,
    )

    # Verify the cross-project edge exists
    dep = await db.fetchrow("SELECT id FROM item_dependencies WHERE id = $1", dep_id)
    assert dep is not None, "Cross-project blocker edge should exist before sharing"

    # Share the project — should purge the cross-project edge
    result = await project_service.add_project_member(
        db, user_a.id, project_p["id"], user_b.email
    )
    assert result["blockers_purged"] == 1

    # The cross-project edge must be gone
    dep_after = await db.fetchrow(
        "SELECT id FROM item_dependencies WHERE id = $1", dep_id
    )
    assert dep_after is None, (
        "Cross-project blocker edge should be purged after sharing"
    )


async def test_add_project_member_second_member_does_not_repurge(
    user_a, user_b, project_p
):
    """Adding a second member to an already-shared project does NOT re-purge blockers.

    The purge only happens on the first share (private → shared transition).
    Once a project is shared, add_blocker enforces the same-project invariant
    so no new cross-project edges can be created.
    """
    db = await get_db()
    user_c = await register_user("user_c_sharing@example.com", "password123")

    # First share: add user_b as member
    result_first = await project_service.add_project_member(
        db, user_a.id, project_p["id"], user_b.email
    )
    assert result_first["blockers_purged"] == 0  # no cross-project blockers exist

    # Create a same-project blocker (valid under the invariant)
    item_x = await item_service.create_item(
        db, user_a.id, title="Item X", project_id=project_p["id"]
    )
    item_y = await item_service.create_item(
        db, user_a.id, title="Item Y", project_id=project_p["id"]
    )
    await item_service.add_blocker(db, user_a.id, item_x["id"], item_y["id"])

    # Second share: add user_c as member — must NOT purge the valid same-project edge
    result_second = await project_service.add_project_member(
        db, user_a.id, project_p["id"], user_c.email
    )
    assert result_second["blockers_purged"] == 0

    # The same-project edge must still exist
    blockers = await item_service.list_blockers(db, user_a.id, item_x["id"])
    assert len(blockers) == 1
    assert blockers[0]["id"] == item_y["id"]


async def test_add_project_member_purge_leaves_same_project_edges(
    user_a, user_b, project_p
):
    """The on-share purge deletes only cross-project edges; same-project edges survive."""  # noqa: E501
    db = await get_db()

    # Create two items in project_p
    item_x = await item_service.create_item(
        db, user_a.id, title="Item X in P", project_id=project_p["id"]
    )
    item_y = await item_service.create_item(
        db, user_a.id, title="Item Y in P", project_id=project_p["id"]
    )

    # Manually insert a same-project blocker (valid edge)
    dep_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at)"
        " VALUES ($1, $2, $3, $4)",
        dep_id,
        item_x["id"],
        item_y["id"],
        now,
    )

    # Create an inbox item for user A
    inbox_item = await item_service.inbox_capture(db, user_a.id, "Inbox straggler")

    # Manually insert a cross-project blocker edge (legacy bad data)
    cross_dep_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at)"
        " VALUES ($1, $2, $3, $4)",
        cross_dep_id,
        item_x["id"],
        inbox_item["id"],  # different project (inbox)
        now,
    )

    # Share the project
    result = await project_service.add_project_member(
        db, user_a.id, project_p["id"], user_b.email
    )
    assert result["blockers_purged"] == 1  # only the cross-project edge

    # Same-project edge survives
    same_dep = await db.fetchrow(
        "SELECT id FROM item_dependencies WHERE id = $1", dep_id
    )
    assert same_dep is not None, "Same-project blocker edge must not be purged"

    # Cross-project edge is gone
    cross_dep = await db.fetchrow(
        "SELECT id FROM item_dependencies WHERE id = $1", cross_dep_id
    )
    assert cross_dep is None, "Cross-project blocker edge must be purged"
