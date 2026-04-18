"""Sharing access tests — accessible_project_ids and service query scoping.

Covers the access matrix:
- User B (member) can list/read/write in shared project P
- User B cannot see User A's other projects or inbox
- Owner-only ops (delete project, update metadata) remain restricted to User A
- Removing B from project_members reverses all access
- B's items keep created_by after removal
"""

from datetime import UTC, datetime

import pytest

from agent_gtd.auth import register_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError
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
    """Member cannot update the shared project's metadata (owner-only)."""
    db = await get_db()
    await add_member(project_p["id"], user_b.id)
    with pytest.raises(NotFoundError):
        await project_service.update_project(
            db, user_b.id, project_p["id"], name="Hacked"
        )


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
