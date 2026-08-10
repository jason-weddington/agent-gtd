"""Unit tests for project_service audit-event emission on member add/remove.

Acceptance criteria verified here:
- add_project_member emits a project_member_added event with project, member, actor.
- remove_project_member emits a project_member_removed event with the same info.
- Both emissions are best-effort: a raised exception from the event bus does NOT
  fail the underlying membership operation.
- Payloads contain no credentials, tokens, or hashes.
"""

from unittest.mock import AsyncMock, patch

import pytest

from agent_gtd.auth import register_user
from agent_gtd.database import get_db
from agent_gtd.services import project_service

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner():
    """Project owner user."""
    return await register_user("owner_svc@example.com", "password123")


@pytest.fixture
async def member():
    """Future project member user."""
    return await register_user("member_svc@example.com", "password123")


@pytest.fixture
async def project(owner):
    """Project owned by owner."""
    db = await get_db()
    return await project_service.create_project(db, owner.id, name="Svc Test Project")


# ---------------------------------------------------------------------------
# add_project_member — event emission
# ---------------------------------------------------------------------------


async def test_add_member_emits_event(owner, member, project):
    """add_project_member emits a project_member_added event row."""
    db = await get_db()
    await project_service.add_project_member(db, owner.id, project["id"], member.email)

    rows = await db.fetch(
        "SELECT * FROM events WHERE event_type = 'project_member_added'"
        " AND project_id = $1",
        project["id"],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_type"] == "project_member"
    assert row["entity_id"] == member.id
    # actor is the owner
    assert row["user_id"] == owner.id


async def test_add_member_event_payload(owner, member, project):
    """project_member_added payload identifies project + member (id and email)."""
    import json

    db = await get_db()
    await project_service.add_project_member(db, owner.id, project["id"], member.email)

    row = await db.fetchrow(
        "SELECT payload FROM events WHERE event_type = 'project_member_added'"
        " AND project_id = $1",
        project["id"],
    )
    assert row is not None
    payload = json.loads(row["payload"])

    assert payload["project_id"] == project["id"]
    assert payload["member_user_id"] == member.id
    assert payload["member_email"] == member.email

    # No credentials or tokens in the payload
    payload_str = row["payload"].lower()
    for forbidden in ("password", "hashed_password", "token", "api_key", "secret"):
        assert forbidden not in payload_str, f"Payload must not contain '{forbidden}'"


async def test_add_member_idempotent_no_duplicate_event(owner, member, project):
    """Idempotent re-add (member already exists) does NOT emit a second event."""
    db = await get_db()
    # First add — real insert, should emit
    await project_service.add_project_member(db, owner.id, project["id"], member.email)
    # Second add — early return (already a member), should NOT emit
    await project_service.add_project_member(db, owner.id, project["id"], member.email)

    rows = await db.fetch(
        "SELECT id FROM events WHERE event_type = 'project_member_added'"
        " AND project_id = $1",
        project["id"],
    )
    assert len(rows) == 1, "Idempotent re-add must not emit a duplicate event"


async def test_add_member_event_bus_failure_does_not_fail_operation(
    owner, member, project
):
    """If the event bus raises, add_project_member still succeeds and inserts the row.

    Best-effort: membership op is not rolled back on publish failure.
    """
    db = await get_db()

    with patch("agent_gtd.services.project_service.get_event_bus") as mock_get_bus:
        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = RuntimeError("bus exploded")
        mock_get_bus.return_value = mock_bus

        # Should NOT raise even though the event bus fails
        result = await project_service.add_project_member(
            db, owner.id, project["id"], member.email
        )

    # The membership was still created
    assert result["user_id"] == member.id
    members = await project_service.list_project_members(db, owner.id, project["id"])
    assert any(m["user_id"] == member.id for m in members)


# ---------------------------------------------------------------------------
# remove_project_member — event emission
# ---------------------------------------------------------------------------


async def test_remove_member_emits_event(owner, member, project):
    """remove_project_member emits a project_member_removed event row."""
    db = await get_db()
    await project_service.add_project_member(db, owner.id, project["id"], member.email)
    await project_service.remove_project_member(db, owner.id, project["id"], member.id)

    rows = await db.fetch(
        "SELECT * FROM events WHERE event_type = 'project_member_removed'"
        " AND project_id = $1",
        project["id"],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_type"] == "project_member"
    assert row["entity_id"] == member.id
    assert row["user_id"] == owner.id


async def test_remove_member_event_payload(owner, member, project):
    """project_member_removed payload identifies project + member (id and email)."""
    import json

    db = await get_db()
    await project_service.add_project_member(db, owner.id, project["id"], member.email)
    await project_service.remove_project_member(db, owner.id, project["id"], member.id)

    row = await db.fetchrow(
        "SELECT payload FROM events WHERE event_type = 'project_member_removed'"
        " AND project_id = $1",
        project["id"],
    )
    assert row is not None
    payload = json.loads(row["payload"])

    assert payload["project_id"] == project["id"]
    assert payload["member_user_id"] == member.id
    assert payload["member_email"] == member.email

    # No credentials or tokens in the payload
    payload_str = row["payload"].lower()
    for forbidden in ("password", "hashed_password", "token", "api_key", "secret"):
        assert forbidden not in payload_str, f"Payload must not contain '{forbidden}'"


async def test_remove_member_noop_no_event(owner, member, project):
    """remove_project_member is a no-op when the user is not a member; no event emitted.

    Event emission must be skipped when there is nothing to delete.
    """
    db = await get_db()
    # member was never added
    await project_service.remove_project_member(db, owner.id, project["id"], member.id)

    rows = await db.fetch(
        "SELECT id FROM events WHERE event_type = 'project_member_removed'"
        " AND project_id = $1",
        project["id"],
    )
    assert len(rows) == 0, "No event should be emitted for a no-op remove"


async def test_remove_member_event_bus_failure_does_not_fail_operation(
    owner, member, project
):
    """Best-effort: remove_project_member succeeds even if the event bus raises.

    The membership row must be deleted regardless of publish failure.
    """
    db = await get_db()
    # First add the member (without mocking)
    await project_service.add_project_member(db, owner.id, project["id"], member.email)

    with patch("agent_gtd.services.project_service.get_event_bus") as mock_get_bus:
        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = RuntimeError("bus exploded")
        mock_get_bus.return_value = mock_bus

        # Should NOT raise even though the event bus fails
        await project_service.remove_project_member(
            db, owner.id, project["id"], member.id
        )

    # The membership was still removed
    members = await project_service.list_project_members(db, owner.id, project["id"])
    assert not any(m["user_id"] == member.id for m in members)
