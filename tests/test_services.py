"""Unit tests for service layer functions (direct, no HTTP)."""

import pytest

from agent_gtd.auth import register_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    VersionConflictError,
)
from agent_gtd.services import item_service, note_service, project_service


@pytest.fixture
async def user_id():
    user = await register_user("svc@example.com", "testpass123")
    return user.id


@pytest.fixture
async def project(user_id):
    db = await get_db()
    return await project_service.create_project(
        db, user_id, name="Test Project", description="For tests"
    )


@pytest.fixture
async def project_id(project):
    return project["id"]


# --- Project service ---


async def test_list_projects(user_id, project_id):
    db = await get_db()
    rows = await project_service.list_projects(db, user_id)
    assert len(rows) == 1
    assert rows[0]["id"] == project_id


async def test_list_projects_filter_status(user_id, project_id):
    db = await get_db()
    rows = await project_service.list_projects(db, user_id, status="active")
    assert len(rows) == 1
    rows = await project_service.list_projects(db, user_id, status="completed")
    assert len(rows) == 0


async def test_get_project(user_id, project_id):
    db = await get_db()
    row = await project_service.get_project(db, user_id, project_id)
    assert row["name"] == "Test Project"


async def test_get_project_not_found(user_id):
    db = await get_db()
    with pytest.raises(NotFoundError):
        await project_service.get_project(db, user_id, "nonexistent")


async def test_update_project(user_id, project_id):
    db = await get_db()
    row = await project_service.update_project(db, user_id, project_id, name="Updated")
    assert row["name"] == "Updated"


async def test_delete_project(user_id, project_id):
    db = await get_db()
    await project_service.delete_project(db, user_id, project_id)
    with pytest.raises(NotFoundError):
        await project_service.get_project(db, user_id, project_id)


async def test_verify_project_ownership(user_id, project_id):
    db = await get_db()
    await project_service.verify_project_ownership(db, project_id, user_id)


async def test_verify_project_ownership_not_found(user_id):
    db = await get_db()
    with pytest.raises(NotFoundError):
        await project_service.verify_project_ownership(db, "nonexistent", user_id)


# --- Item service ---


async def test_create_and_get_item(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Test Item", project_id=project_id
    )
    assert row["title"] == "Test Item"
    assert row["version"] == 1

    fetched = await item_service.get_item(db, user_id, row["id"])
    assert fetched["id"] == row["id"]


async def test_get_item_not_found(user_id):
    db = await get_db()
    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_id, "nonexistent")


async def test_update_item_basic(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Original", project_id=project_id
    )
    updated = await item_service.update_item(db, user_id, row["id"], title="Changed")
    assert updated["title"] == "Changed"
    assert updated["version"] == 2


async def test_update_item_version_match(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(db, user_id, title="V1", project_id=project_id)
    updated = await item_service.update_item(
        db, user_id, row["id"], title="V2", version=1
    )
    assert updated["version"] == 2


async def test_update_item_version_mismatch(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(db, user_id, title="V1", project_id=project_id)
    with pytest.raises(VersionConflictError) as exc_info:
        await item_service.update_item(db, user_id, row["id"], title="V2", version=99)
    assert exc_info.value.expected == 99
    assert exc_info.value.actual == 1


async def test_complete_item_sets_completed_at(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="To Complete", project_id=project_id
    )
    assert row["completed_at"] is None

    completed = await item_service.complete_item(db, user_id, row["id"])
    assert completed["status"] == "done"
    assert completed["completed_at"] is not None


async def test_complete_item_not_found(user_id):
    db = await get_db()
    with pytest.raises(NotFoundError):
        await item_service.complete_item(db, user_id, "nonexistent")


async def test_claim_item(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Claimable", project_id=project_id
    )
    claimed = await item_service.claim_item(db, user_id, row["id"], "agent-1")
    assert claimed["assigned_to"] == "agent-1"


async def test_claim_item_idempotent(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Claimable", project_id=project_id
    )
    await item_service.claim_item(db, user_id, row["id"], "agent-1")
    # Re-claim by same agent is idempotent
    re_claimed = await item_service.claim_item(db, user_id, row["id"], "agent-1")
    assert re_claimed["assigned_to"] == "agent-1"


async def test_claim_item_already_claimed(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Contested", project_id=project_id
    )
    await item_service.claim_item(db, user_id, row["id"], "agent-1")

    with pytest.raises(AlreadyClaimedError) as exc_info:
        await item_service.claim_item(db, user_id, row["id"], "agent-2")
    assert exc_info.value.claimed_by == "agent-1"


async def test_release_item(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="To Release", project_id=project_id
    )
    await item_service.claim_item(db, user_id, row["id"], "agent-1")
    released = await item_service.release_item(db, user_id, row["id"])
    assert released["assigned_to"] == ""


async def test_delete_item(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Doomed", project_id=project_id
    )
    await item_service.delete_item(db, user_id, row["id"])
    with pytest.raises(NotFoundError):
        await item_service.get_item(db, user_id, row["id"])


async def test_inbox_capture(user_id, project_id):
    db = await get_db()
    row = await item_service.inbox_capture(
        db, user_id, "Quick thought", project_id=project_id, created_by="test-agent"
    )
    assert row["title"] == "Quick thought"
    assert row["status"] == "inbox"
    assert row["created_by"] == "test-agent"


async def test_list_inbox(user_id, project_id):
    db = await get_db()
    await item_service.inbox_capture(db, user_id, "Inbox 1", project_id=project_id)
    await item_service.create_item(
        db, user_id, title="Not inbox", project_id=project_id, status="active"
    )
    inbox = await item_service.list_inbox(db, user_id)
    assert len(inbox) == 1
    assert inbox[0]["title"] == "Inbox 1"


async def test_list_project_items(user_id, project_id):
    db = await get_db()
    await item_service.create_item(
        db, user_id, title="In project", project_id=project_id
    )
    rows = await item_service.list_project_items(db, user_id, project_id)
    assert len(rows) == 1


async def test_create_project_item(user_id, project_id):
    db = await get_db()
    row = await item_service.create_project_item(
        db, user_id, project_id, title="Project Item"
    )
    assert row["project_id"] == project_id


async def test_list_items_filter_assigned_to(user_id, project_id):
    db = await get_db()
    await item_service.create_item(
        db, user_id, title="Unassigned", project_id=project_id
    )
    row = await item_service.create_item(
        db, user_id, title="Assigned", project_id=project_id, assigned_to="agent-1"
    )
    rows = await item_service.list_items(db, user_id, assigned_to="agent-1")
    assert len(rows) == 1
    assert rows[0]["id"] == row["id"]


async def test_update_item_all_fields(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Full Update", project_id=project_id
    )
    updated = await item_service.update_item(
        db,
        user_id,
        row["id"],
        title="New Title",
        description="New desc",
        status="active",
        priority="high",
        due_date="2026-12-31",
        due_date_set=True,
        assigned_to="agent-1",
        waiting_on="agent-2",
        sort_order=5.0,
        labels=["a", "b"],
    )
    assert updated["title"] == "New Title"
    assert updated["description"] == "New desc"
    assert updated["status"] == "active"
    assert updated["priority"] == "high"
    assert updated["assigned_to"] == "agent-1"
    assert updated["waiting_on"] == "agent-2"
    assert updated["sort_order"] == 5.0


async def test_uncomplete_item_clears_completed_at(user_id, project_id):
    db = await get_db()
    row = await item_service.create_item(
        db, user_id, title="Complete then undo", project_id=project_id
    )
    completed = await item_service.complete_item(db, user_id, row["id"])
    assert completed["completed_at"] is not None

    undone = await item_service.update_item(db, user_id, row["id"], status="active")
    assert undone["completed_at"] is None


# --- Note service ---


async def test_create_and_get_note(user_id, project_id):
    db = await get_db()
    row = await note_service.create_note(
        db, user_id, project_id, title="Test Note", content_markdown="# Hello"
    )
    assert row["title"] == "Test Note"

    fetched = await note_service.get_note(db, user_id, row["id"])
    assert fetched["content_markdown"] == "# Hello"


async def test_get_note_not_found(user_id):
    db = await get_db()
    with pytest.raises(NotFoundError):
        await note_service.get_note(db, user_id, "nonexistent")


async def test_update_note(user_id, project_id):
    db = await get_db()
    row = await note_service.create_note(db, user_id, project_id, title="Original")
    updated = await note_service.update_note(db, user_id, row["id"], title="Changed")
    assert updated["title"] == "Changed"


async def test_delete_note(user_id, project_id):
    db = await get_db()
    row = await note_service.create_note(db, user_id, project_id, title="Doomed")
    await note_service.delete_note(db, user_id, row["id"])
    with pytest.raises(NotFoundError):
        await note_service.get_note(db, user_id, row["id"])


async def test_list_project_notes(user_id, project_id):
    db = await get_db()
    await note_service.create_note(db, user_id, project_id, title="Note 1")
    await note_service.create_note(db, user_id, project_id, title="Note 2")
    rows = await note_service.list_project_notes(db, user_id, project_id)
    assert len(rows) == 2
