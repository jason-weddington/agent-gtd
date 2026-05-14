"""Unit tests for wave_service: pure functions and legality validation."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_gtd.database import encode_json_list, get_db
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.services.rollout_service import (
    call_planner,
    cancel_rollout,
    complete_item_in_rollout,
    has_acceptance_criteria,
    parse_declared_files,
    start_rollout,
    validate_legality_contract,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC).isoformat()

VALID_DESC = """\
Some intro text.

## Acceptance Criteria
- [ ] First criterion
- [ ] Second criterion

## Files to Modify
- src/agent_gtd/services/rollout_service.py
- tests/test_rollout_service.py
"""

NO_AC_DESC = """\
## Files to Modify
- src/agent_gtd/services/rollout_service.py
"""

NO_FILES_DESC = """\
## Acceptance Criteria
- [ ] First criterion
"""

EMPTY_AC_DESC = """\
## Acceptance Criteria

## Files to Modify
- src/foo.py
"""

EMPTY_FILES_DESC = """\
## Acceptance Criteria
- [ ] First criterion

## Files to Modify

## Other Section
"""


@pytest.fixture
async def db():
    """Return the patched test database pool."""
    return await get_db()


async def _make_user(db) -> str:
    """Insert a test user and return its ID."""
    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id[:8]}@test.com",
        "hashed",
        NOW,
    )
    return user_id


async def _make_project(db, user_id: str) -> str:
    """Insert a test project and return its ID."""
    project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Test Project",
        NOW,
        NOW,
    )
    return project_id


async def _make_item(
    db,
    user_id: str,
    project_id: str,
    *,
    title: str = "Test Item",
    status: str = "ready",
    description: str = VALID_DESC,
) -> str:
    """Insert a test item and return its ID."""
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        item_id,
        project_id,
        user_id,
        title,
        description,
        status,
        encode_json_list([]),
        NOW,
        NOW,
    )
    return item_id


async def _add_blocker(db, item_id: str, blocker_item_id: str) -> None:
    """Add a blocker relationship between two items."""
    dep_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at) "
        "VALUES ($1, $2, $3, $4)",
        dep_id,
        item_id,
        blocker_item_id,
        NOW,
    )


# ---------------------------------------------------------------------------
# parse_declared_files — pure function tests
# ---------------------------------------------------------------------------


def test_parse_declared_files_extracts_lines():
    desc = (
        "Intro\n\n## Files to Modify\n"
        "- src/foo.py\n- src/bar.py\n\n## Other\n- not this"
    )
    result = parse_declared_files(desc)
    assert result == ["- src/foo.py", "- src/bar.py"]


def test_parse_declared_files_stops_at_next_heading():
    desc = "## Files to Modify\n- a.py\n## Something Else\n- b.py"
    result = parse_declared_files(desc)
    assert result == ["- a.py"]


def test_parse_declared_files_empty_section():
    desc = "## Files to Modify\n\n## Next Section\n"
    assert parse_declared_files(desc) == []


def test_parse_declared_files_no_section():
    assert parse_declared_files("No files section at all") == []


def test_parse_declared_files_blank_lines_ignored():
    desc = "## Files to Modify\n\n- src/a.py\n\n- src/b.py\n"
    result = parse_declared_files(desc)
    assert result == ["- src/a.py", "- src/b.py"]


def test_parse_declared_files_plain_paths():
    desc = "## Files to Modify\nsrc/a.py\nsrc/b.py"
    assert parse_declared_files(desc) == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# has_acceptance_criteria — pure function tests
# ---------------------------------------------------------------------------


def test_has_ac_true():
    desc = "## Acceptance Criteria\n- [ ] Thing to do\n"
    assert has_acceptance_criteria(desc) is True


def test_has_ac_true_multiple_lines():
    desc = "## Acceptance Criteria\n- [ ] A\n- [ ] B\n"
    assert has_acceptance_criteria(desc) is True


def test_has_ac_false_empty_section():
    desc = "## Acceptance Criteria\n\n## Files to Modify\n- src/foo.py"
    assert has_acceptance_criteria(desc) is False


def test_has_ac_false_no_section():
    assert has_acceptance_criteria("Nothing useful here") is False


def test_has_ac_false_only_blanks():
    desc = "## Acceptance Criteria\n   \n\t\n## Next"
    assert has_acceptance_criteria(desc) is False


# ---------------------------------------------------------------------------
# validate_legality_contract — DB-backed tests
# ---------------------------------------------------------------------------


async def test_validate_passes_for_valid_items(db):
    """All rules satisfied → no exception."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    # Should not raise
    await validate_legality_contract(db, user_id, [item_id])


async def test_validate_multiple_valid_items_same_project(db):
    """Multiple valid items in the same project pass."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    ids = [
        await _make_item(db, user_id, project_id, title=f"Item {i}") for i in range(3)
    ]
    await validate_legality_contract(db, user_id, ids)


async def test_validate_empty_list_not_raised_here(db):
    """validate_legality_contract does not check for empty list (plan_rollout does)."""
    # Empty list — validate_legality_contract sees zero items and raises nothing.
    # The empty-list guard lives in plan_rollout, not here.
    # This test just confirms no exception for an empty list at this layer.
    user_id = await _make_user(db)
    await validate_legality_contract(db, user_id, [])


# --- Rule 1: item not found ---


async def test_validate_item_not_found(db):
    user_id = await _make_user(db)
    fake_id = str(uuid.uuid4())
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [fake_id])
    failures = exc_info.value.failures
    assert len(failures) == 1
    assert failures[0]["item_id"] == fake_id
    assert any("not found" in str(f) for f in failures[0]["failures"])


async def test_validate_item_not_accessible_by_user(db):
    """Item in another user's private project is not visible."""
    owner = await _make_user(db)
    attacker = await _make_user(db)
    project_id = await _make_project(db, owner)
    item_id = await _make_item(db, owner, project_id)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, attacker, [item_id])
    assert exc_info.value.failures[0]["item_id"] == item_id


# --- Rule 2: status must be 'ready' ---


async def test_validate_wrong_status_new(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="new")
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("status" in str(f) for f in failure["failures"])
    assert any("ready" in str(f) for f in failure["failures"])


async def test_validate_wrong_status_active(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    assert any("status" in str(f) for f in exc_info.value.failures[0]["failures"])


async def test_validate_wrong_status_done(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="done")
    with pytest.raises(LegalityContractError):
        await validate_legality_contract(db, user_id, [item_id])


# --- Rule 3: missing Acceptance Criteria ---


async def test_validate_missing_acceptance_criteria(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, description=NO_AC_DESC)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("Acceptance Criteria" in str(f) for f in failure["failures"])


async def test_validate_empty_acceptance_criteria(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, description=EMPTY_AC_DESC)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("Acceptance Criteria" in str(f) for f in failure["failures"])


# --- Rule 4: missing Files to Modify ---


async def test_validate_missing_files_to_modify(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, description=NO_FILES_DESC)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("Files to Modify" in str(f) for f in failure["failures"])


async def test_validate_empty_files_to_modify(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, description=EMPTY_FILES_DESC)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("Files to Modify" in str(f) for f in failure["failures"])


# --- Rule 5: unresolved external blockers ---


async def test_validate_external_blocker_blocks_item(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, title="Blocked item")
    blocker_id = await _make_item(db, user_id, project_id, title="External blocker")
    await _add_blocker(db, item_id, blocker_id)

    # blocker_id is NOT in item_ids → external blocker
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("External blocker" in str(f) for f in failure["failures"])


async def test_validate_internal_blocker_allowed(db):
    """Blockers within item_ids are acceptable — planner handles ordering."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, title="Item A")
    item_b = await _make_item(db, user_id, project_id, title="Item B (blocks A)")
    await _add_blocker(db, item_a, item_b)

    # Both items are in the wave → internal blocker → should pass
    await validate_legality_contract(db, user_id, [item_a, item_b])


async def test_validate_resolved_external_blocker_allowed(db):
    """A blocker with status 'done' or 'cancelled' is not considered unresolved."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, title="Main item")
    blocker_id = await _make_item(
        db, user_id, project_id, title="Done blocker", status="done"
    )
    await _add_blocker(db, item_id, blocker_id)

    # Blocker is done → resolved → should pass
    await validate_legality_contract(db, user_id, [item_id])


# --- Rule 6: mixed projects ---


async def test_validate_mixed_projects_rejected(db):
    """Items from different projects are rejected with per-item failures."""
    user_id = await _make_user(db)
    project_a = await _make_project(db, user_id)
    project_b = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_a, title="In Project A")
    item_b = await _make_item(db, user_id, project_b, title="In Project B")

    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_a, item_b])

    failures = exc_info.value.failures
    # Both items should appear in failures
    failed_ids = {f["item_id"] for f in failures}
    assert item_a in failed_ids
    assert item_b in failed_ids
    # Each failure should mention project mismatch
    for failure in failures:
        assert any("project" in str(f).lower() for f in failure["failures"])


# --- All failures collected (non-fail-fast) ---


async def test_validate_collects_all_failures(db):
    """Multiple items failing different rules all appear in the error."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_wrong_status = await _make_item(db, user_id, project_id, status="new")
    item_no_ac = await _make_item(db, user_id, project_id, description=NO_AC_DESC)
    item_no_files = await _make_item(db, user_id, project_id, description=NO_FILES_DESC)

    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(
            db, user_id, [item_wrong_status, item_no_ac, item_no_files]
        )

    # All three items should have failures
    failed_ids = {f["item_id"] for f in exc_info.value.failures}
    assert item_wrong_status in failed_ids
    assert item_no_ac in failed_ids
    assert item_no_files in failed_ids


async def test_validate_multiple_failures_same_item(db):
    """An item can fail multiple rules simultaneously."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    # Wrong status + no AC + no files
    item_id = await _make_item(
        db, user_id, project_id, status="inbox", description="Plain description"
    )
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    # Should list at least 3 failures
    assert len(failure["failures"]) >= 3


# ---------------------------------------------------------------------------
# plan_rollout — ValidationError for empty list
# ---------------------------------------------------------------------------


async def test_plan_rollout_empty_item_ids_raises(db):
    """plan_rollout raises ValidationError for empty item_ids before any DB reads."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    with pytest.raises(ValidationError, match="empty"):
        await plan_rollout(db, user_id, [])


async def test_plan_rollout_no_dispatch_config_raises(db):
    """plan_rollout raises ValidationError when dispatch is not configured."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    # No dispatch config configured → should raise
    with pytest.raises(ValidationError, match="not configured"):
        await plan_rollout(db, user_id, [item_id])


async def test_plan_rollout_no_rollout_inserted_on_legality_failure(db):
    """No autonomous_rollouts row is inserted when legality fails."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    # Item with wrong status
    item_id = await _make_item(db, user_id, project_id, status="new")

    with pytest.raises(LegalityContractError):
        await plan_rollout(db, user_id, [item_id])

    rows = await db.fetch("SELECT id FROM autonomous_rollouts")
    assert len(rows) == 0


async def test_plan_rollout_no_rollout_inserted_on_empty_list(db):
    """No DB writes happen when item_ids is empty."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    with pytest.raises(ValidationError):
        await plan_rollout(db, user_id, [])

    rows = await db.fetch("SELECT id FROM autonomous_rollouts")
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# cancel_rollout — DB-backed tests
# ---------------------------------------------------------------------------


async def _make_rollout(
    db, user_id: str, project_id: str, *, status: str = "halted"
) -> str:
    """Insert an autonomous_rollouts row and return its ID."""
    rollout_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        user_id,
        status,
        NOW,
        NOW,
    )
    return rollout_id


async def _make_wave_plan_item(
    db,
    rollout_id: str,
    item_id: str,
    *,
    status: str = "pending",
) -> None:
    """Insert a rollout_items row."""
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status) VALUES ($1, $2, $3)",
        rollout_id,
        item_id,
        status,
    )


async def _get_wave_item_status(db, rollout_id: str, item_id: str) -> str:
    """Return the status of a rollout_items row."""
    row = await db.fetchrow(
        "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    assert row is not None
    return row["status"]  # type: ignore[return-value]


async def test_cancel_rollout_halted_to_cancelled(db):
    """halted → cancelled transition works."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result = await cancel_rollout(db, user_id, rollout_id, "test abort")

    assert result["status"] == "cancelled"
    assert result["halt_reason"] == "test abort"


async def test_cancel_rollout_running_to_cancelled(db):
    """running → cancelled transition works."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result = await cancel_rollout(db, user_id, rollout_id, "running abort")

    assert result["status"] == "cancelled"


async def test_cancel_rollout_idempotent(db):
    """Cancelling an already-cancelled wave returns success without error."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="cancelled")

    # No patch needed — the early-return path skips release_rollout_locks and publish.
    result = await cancel_rollout(db, user_id, rollout_id, "re-cancel")

    assert result["status"] == "cancelled"


async def test_cancel_rollout_marks_in_progress_items_skipped(db):
    """Non-terminal wave plan items are marked skipped."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")

    item_pending = await _make_item(db, user_id, project_id, title="Pending item")
    item_halted_i = await _make_item(db, user_id, project_id, title="Halted item")
    item_completed = await _make_item(db, user_id, project_id, title="Completed item")

    await _make_wave_plan_item(db, rollout_id, item_pending, status="pending")
    await _make_wave_plan_item(db, rollout_id, item_halted_i, status="halted")
    await _make_wave_plan_item(db, rollout_id, item_completed, status="completed")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        await cancel_rollout(db, user_id, rollout_id, "abort all")

    assert await _get_wave_item_status(db, rollout_id, item_pending) == "skipped"
    assert await _get_wave_item_status(db, rollout_id, item_halted_i) == "skipped"
    # completed items are untouched
    assert await _get_wave_item_status(db, rollout_id, item_completed) == "completed"


async def test_cancel_rollout_completed_items_untouched(db):
    """Completed wave plan items are not modified by cancel."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")

    item_done = await _make_item(db, user_id, project_id, title="Done item")
    await _make_wave_plan_item(db, rollout_id, item_done, status="completed")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        await cancel_rollout(db, user_id, rollout_id, "cancel with done items")

    assert await _get_wave_item_status(db, rollout_id, item_done) == "completed"


# ---------------------------------------------------------------------------
# start_rollout
# ---------------------------------------------------------------------------


async def test_start_rollout_pending_to_running(db):
    """pending → running transition works; started_at is set."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="pending")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await start_rollout(db, user_id, rollout_id)

    assert result["status"] == "running"
    assert result["started_at"] is not None


async def test_start_rollout_rejects_running(db):
    """ValidationError if wave is already running."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with pytest.raises(ValidationError):
        await start_rollout(db, user_id, rollout_id)


async def test_start_rollout_rejects_halted(db):
    """ValidationError if wave is halted."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")

    with pytest.raises(ValidationError):
        await start_rollout(db, user_id, rollout_id)


async def test_start_rollout_rejects_cancelled(db):
    """ValidationError if wave is cancelled."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="cancelled")

    with pytest.raises(ValidationError):
        await start_rollout(db, user_id, rollout_id)


async def test_start_rollout_rejects_done(db):
    """ValidationError if wave is done."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="done")

    with pytest.raises(ValidationError):
        await start_rollout(db, user_id, rollout_id)


async def test_start_rollout_wrong_user(db):
    """NotFoundError for wrong user_id."""
    user_id = await _make_user(db)
    other_user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="pending")

    with pytest.raises(NotFoundError):
        await start_rollout(db, other_user_id, rollout_id)


async def test_start_rollout_emits_wave_started_event(db):
    """wave_started event with kind='wave_started' appears in rollout_events."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="pending")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event") as mock_pub:
        await start_rollout(db, user_id, rollout_id)

    # Check the event was written to the DB
    row = await db.fetchrow(
        "SELECT kind, actor FROM rollout_events WHERE rollout_id = $1", rollout_id
    )
    assert row is not None
    assert row["kind"] == "wave_started"
    assert row["actor"] == "lead"
    # And publish was called once
    mock_pub.assert_called_once()


# ---------------------------------------------------------------------------
# Mixed-project failure with pre-existing per-item failures (lines 187-190)
# ---------------------------------------------------------------------------


async def test_validate_mixed_projects_item_with_existing_failures(db):
    """Item that already has per-item failures also gets project-mismatch failure."""
    user_id = await _make_user(db)
    project_a = await _make_project(db, user_id)
    project_b = await _make_project(db, user_id)
    # Item A: wrong status AND in different project from B
    item_a = await _make_item(
        db, user_id, project_a, title="Bad Status In A", status="new"
    )
    item_b = await _make_item(db, user_id, project_b, title="Good Item In B")

    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_a, item_b])

    # item_a should have BOTH status failure AND project mismatch failure
    failure_a = next(f for f in exc_info.value.failures if f["item_id"] == item_a)
    failure_a_msgs = [str(m) for m in failure_a["failures"]]
    assert any("status" in m for m in failure_a_msgs)
    assert any("project" in m.lower() for m in failure_a_msgs)


# ---------------------------------------------------------------------------
# call_planner error paths (lines 237-254)
# ---------------------------------------------------------------------------


def _make_async_client_mock(post_side_effect=None, response=None):
    """Build a mock httpx.AsyncClient context manager."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_client.post = AsyncMock(return_value=response)
    return mock_client


async def test_call_planner_http_status_error():
    """HTTPStatusError from raise_for_status is wrapped as RuntimeError."""
    mock_response = MagicMock()
    mock_request = httpx.Request("POST", "http://dispatch.test:8100/plan")
    error_response = MagicMock()
    error_response.status_code = 500
    error_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error",
        request=mock_request,
        response=error_response,
    )
    mock_client = _make_async_client_mock(response=mock_response)

    with (
        patch(
            "agent_gtd.services.rollout_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="Planner HTTP error 500"),
    ):
        await call_planner("http://dispatch.test:8100", "key", ["item-1"])


async def test_call_planner_timeout_error():
    """TimeoutException from client.post is wrapped as RuntimeError."""
    mock_client = _make_async_client_mock(
        post_side_effect=httpx.TimeoutException("Request timed out")
    )

    with (
        patch(
            "agent_gtd.services.rollout_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="timed out"),
    ):
        await call_planner("http://dispatch.test:8100", "key", ["item-1"])


async def test_call_planner_network_error():
    """RequestError from client.post is wrapped as RuntimeError."""
    mock_client = _make_async_client_mock(
        post_side_effect=httpx.ConnectError("Connection refused")
    )

    with (
        patch(
            "agent_gtd.services.rollout_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="network error"),
    ):
        await call_planner("http://dispatch.test:8100", "key", ["item-1"])


async def test_call_planner_success():
    """Successful planner call returns parsed JSON response."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "nodes": ["item-1"],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }
    mock_client = _make_async_client_mock(response=mock_response)

    with patch(
        "agent_gtd.services.rollout_service.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await call_planner("http://dispatch.test:8100", "key", ["item-1"])

    assert result["nodes"] == ["item-1"]
    assert result["planner_model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# plan_rollout — project not found (line 309)
# ---------------------------------------------------------------------------


async def test_plan_rollout_project_not_found(db):
    """plan_rollout raises ValidationError when item's project_id doesn't exist."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    # Insert an inbox item (no project) — it has no project_id
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        item_id,
        None,  # no project
        user_id,
        "Inbox item",
        VALID_DESC,
        "ready",
        encode_json_list([]),
        NOW,
        NOW,
    )

    with pytest.raises(ValidationError, match="not found"):
        await plan_rollout(db, user_id, [item_id])


# ---------------------------------------------------------------------------
# complete_item_in_rollout — cascade + graph_complete
# ---------------------------------------------------------------------------


async def test_complete_item_in_rollout_completed_cascades_item_done(db):
    """outcome='completed' flips the GTD item to done with completed_at set."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )

    row = await db.fetchrow(
        "SELECT status, completed_at FROM items WHERE id = $1", item_id
    )
    assert row is not None
    assert row["status"] == "done"
    assert row["completed_at"] is not None


async def test_complete_item_in_rollout_halted_does_not_cascade(db):
    """outcome='halted' leaves the GTD item status unchanged."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="halted"
        )

    row = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_id)
    assert row is not None
    assert row["status"] == "review"


async def test_complete_item_in_rollout_skipped_does_not_cascade(db):
    """outcome='skipped' leaves the GTD item status unchanged."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="skipped"
        )

    row = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_id)
    assert row is not None
    assert row["status"] == "active"


async def test_complete_item_in_rollout_graph_complete_true_when_last_item(db):
    """Single-item wave: completing the last item returns graph_complete=True."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )

    assert result["graph_complete"] is True


async def test_complete_item_in_rollout_graph_complete_false_when_items_remain(db):
    """Two-item wave: completing one dispatched item returns graph_complete=False."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item1_id = await _make_item(
        db, user_id, project_id, status="active", title="Item 1"
    )
    item2_id = await _make_item(
        db, user_id, project_id, status="active", title="Item 2"
    )
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item1_id, status="dispatched")
    await _make_wave_plan_item(db, rollout_id, item2_id, status="pending")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item1_id, outcome="completed"
        )

    assert result["graph_complete"] is False
