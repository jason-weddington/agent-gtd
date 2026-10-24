"""Unit tests for wave_service: pure functions and legality validation."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent_gtd.database import encode_file_specs, encode_json_list, get_db
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.services.rollout_service import (
    MERGE_NOTE_EVENT_KIND,
    MERGE_NOTE_MAX_CHARS,
    cancel_rollout,
    complete_item_in_rollout,
    get_recent_merge_notes,
    resume_rollout,
    start_rollout,
    validate_legality_contract,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC).isoformat()


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


_DEFAULT_ACCEPTANCE_CRITERIA = ["AC-1: Does the thing correctly"]
_DEFAULT_FILES_TO_MODIFY = [{"path": "src/main.py", "change": "Update logic"}]
_DEFAULT_BUILD_ENGINE = "claude-code"
_DEFAULT_COMMIT_TYPE = "feat"


async def _make_item(
    db,
    user_id: str,
    project_id: str,
    *,
    title: str = "Test Item",
    status: str = "ready",
    description: str = "",
    acceptance_criteria: list[str] | None = None,
    files_to_modify: list[dict] | None = None,
    build_engine: str | None = _DEFAULT_BUILD_ENGINE,
    commit_type: str = _DEFAULT_COMMIT_TYPE,
) -> str:
    """Insert a test item and return its ID.

    Defaults produce a fully-groomed item that passes legality validation.
    Pass acceptance_criteria=[], files_to_modify=[], build_engine=None or
    commit_type="" to simulate a partially-groomed item.
    """
    if acceptance_criteria is None:
        acceptance_criteria = _DEFAULT_ACCEPTANCE_CRITERIA
    if files_to_modify is None:
        files_to_modify = _DEFAULT_FILES_TO_MODIFY
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, acceptance_criteria, files_to_modify, scope_out, "
        " build_engine, commit_type, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
        item_id,
        project_id,
        user_id,
        title,
        description,
        status,
        encode_json_list([]),
        encode_json_list(acceptance_criteria),
        encode_file_specs(files_to_modify),
        encode_json_list([]),
        build_engine,
        commit_type,
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


# --- Rule 3: empty acceptance_criteria structured field ---


async def test_validate_missing_acceptance_criteria(db):
    """Empty acceptance_criteria field → legality failure."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, acceptance_criteria=[])
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("acceptance_criteria" in str(f) for f in failure["failures"])


async def test_validate_empty_acceptance_criteria(db):
    """Explicit empty list for acceptance_criteria → legality failure."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, acceptance_criteria=[])
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("acceptance_criteria" in str(f) for f in failure["failures"])


# --- Rule 4: empty files_to_modify structured field ---


async def test_validate_missing_files_to_modify(db):
    """Empty files_to_modify field → legality failure."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, files_to_modify=[])
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("files_to_modify" in str(f) for f in failure["failures"])


async def test_validate_empty_files_to_modify(db):
    """Explicit empty list for files_to_modify → legality failure."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, files_to_modify=[])
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("files_to_modify" in str(f) for f in failure["failures"])


# --- Rule 4b: build_engine must be set for groomed items ---


async def test_validate_missing_build_engine(db):
    """Groomed item (AC + files set) but build_engine=None → legality failure."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, build_engine=None)
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    assert any("build_engine" in str(f) for f in failure["failures"])


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
    item_no_ac = await _make_item(db, user_id, project_id, acceptance_criteria=[])
    item_no_files = await _make_item(db, user_id, project_id, files_to_modify=[])

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
    # Wrong status + no AC + no files + no build_engine
    item_id = await _make_item(
        db,
        user_id,
        project_id,
        status="inbox",
        acceptance_criteria=[],
        files_to_modify=[],
        build_engine=None,
        commit_type="",
    )
    with pytest.raises(LegalityContractError) as exc_info:
        await validate_legality_contract(db, user_id, [item_id])
    failure = exc_info.value.failures[0]
    # Should list at least 4 failures (status + AC + files + build_engine)
    assert len(failure["failures"]) >= 4


async def test_plan_rollout_rejects_item_without_commit_type(db):
    """Rule 4c: an otherwise-legal item with commit_type '' is refused."""
    from agent_gtd.services.rollout_service import (
        COMMIT_TYPE_REQUIRED_FAILURE,
        plan_rollout,
    )

    expected = (
        "commit_type must be set for groomed items (one of feat, fix, perf, "
        "refactor, test, docs, chore) — set it in the item drawer, with MCP "
        "update_item(commit_type=...), or `agent-gtd update-item <id> "
        "--commit-type <type>` (requires an agent-gtd CLI/MCP that includes "
        "commit_type)"
    )
    assert expected == COMMIT_TYPE_REQUIRED_FAILURE

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, commit_type="")

    with pytest.raises(LegalityContractError) as exc_info:
        await plan_rollout(db, user_id, [item_id])
    exc = exc_info.value
    assert exc.failures[0]["item_id"] == item_id
    assert expected in exc.failures[0]["failures"]
    assert item_id[:8] in str(exc)


async def test_validate_legality_passes_with_commit_type_set(db):
    """Rule 4c: the same item with commit_type 'fix' passes validation."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, commit_type="fix")

    await validate_legality_contract(db, user_id, [item_id])


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
# plan_rollout — project not found (line 309)
# ---------------------------------------------------------------------------


async def test_plan_rollout_project_not_found(db):
    """plan_rollout raises ValidationError when item's project_id doesn't exist."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    # Insert an inbox item (no project) — it has no project_id.
    # Must have structured legality fields set so legality passes before the
    # "no project" check is reached.
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, acceptance_criteria, files_to_modify, scope_out, "
        " build_engine, commit_type, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
        item_id,
        None,  # no project
        user_id,
        "Inbox item",
        "",
        "ready",
        encode_json_list([]),
        encode_json_list(["AC-1: Does X"]),
        encode_file_specs([{"path": "src/main.py", "change": "Update"}]),
        encode_json_list([]),
        "claude-code",
        "feat",
        NOW,
        NOW,
    )

    with pytest.raises(ValidationError, match="not found"):
        await plan_rollout(db, user_id, [item_id])


# ---------------------------------------------------------------------------
# plan_rollout — workspace project happy path
# ---------------------------------------------------------------------------


async def test_plan_rollout_workspace_project_succeeds(db):
    """plan_rollout succeeds for workspace projects (rejection guard removed).

    Inserts a workspace project directly, configures dispatch settings for the
    owner, and asserts the returned dict and persisted row both have
    status='pending'.
    """
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)

    # Insert workspace project directly — bypasses the API validation that
    # requires non-empty repos, to keep the test self-contained.
    workspace_project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects"
        " (id, user_id, name, repo_mode, workspace_repos, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        workspace_project_id,
        user_id,
        "Workspace Project",
        "workspace",
        encode_json_list(["https://github.com/example/repo-a.git"]),
        NOW,
        NOW,
    )
    item_id = await _make_item(db, user_id, workspace_project_id)

    # Insert dispatch config for the owner user (mirrors _configure_dispatch in
    # test_mcp_rollout.py but uses the db fixture directly).
    for key, value in [
        ("dispatch.service_url", "http://dispatch.test:8100"),
        ("dispatch.service_api_key", "test-api-key"),
    ]:
        await db.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id, key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            user_id,
            key,
            value,
            NOW,
        )

    result = await plan_rollout(db, user_id, [item_id])

    assert result["status"] == "pending"
    assert result["planner_model"] == "derived-from-blockers"

    # Exactly one autonomous_rollouts row with status='pending'
    rows = await db.fetch("SELECT status FROM autonomous_rollouts")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# plan_rollout — the planner is genuinely out of the path
# ---------------------------------------------------------------------------


async def _configure_dispatch_for(db, user_id: str) -> None:
    """Write dispatch settings for *user_id*."""
    for key, value in [
        ("dispatch.service_url", "http://dispatch.test:8100"),
        ("dispatch.service_api_key", "test-api-key"),
    ]:
        await db.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id, key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            user_id,
            key,
            value,
            NOW,
        )


async def test_plan_rollout_makes_no_outbound_http_call(db):
    """plan_rollout must not touch the network — the DAG is derived locally.

    Any httpx request blows up, so the test fails loudly if a remote planner
    creeps back into this path.  The LLM planner it guards against was deleted
    along with ``POST /plan``; this guard outlives it.
    """
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(
        db,
        user_id,
        project_id,
        title="A",
        files_to_modify=[{"path": "src/a.py", "change": "x"}],
    )
    item_b = await _make_item(
        db,
        user_id,
        project_id,
        title="B",
        files_to_modify=[{"path": "src/b.py", "change": "y"}],
    )
    await _add_blocker(db, item_b, item_a)
    await _configure_dispatch_for(db, user_id)

    no_http = AssertionError("plan_rollout made an outbound HTTP call")
    with (
        patch.object(httpx.AsyncClient, "send", side_effect=no_http),
        patch.object(httpx.AsyncClient, "request", side_effect=no_http),
    ):
        result = await plan_rollout(db, user_id, [item_a, item_b])

    assert result["status"] == "pending"
    assert result["planner_model"] == "derived-from-blockers"
    assert result["plan"]["edges"] == [{"from_item_id": item_a, "to_item_id": item_b}]


async def test_plan_rollout_nodes_preserve_caller_order(db):
    """``nodes`` is list(item_ids) verbatim — several call sites iterate in order."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    ids = [
        await _make_item(
            db,
            user_id,
            project_id,
            title=f"Item {i}",
            files_to_modify=[{"path": f"src/f{i}.py", "change": "x"}],
        )
        for i in range(3)
    ]
    await _configure_dispatch_for(db, user_id)
    ordered = [ids[2], ids[0], ids[1]]

    result = await plan_rollout(db, user_id, ordered)

    assert result["plan"]["nodes"] == ordered
    assert [p["item_id"] for p in result["per_item"]] == ordered


async def test_plan_rollout_writes_plan_row_when_no_edges(db):
    """A rollout_plans row is written even when the derived edge list is empty."""
    from agent_gtd.services.rollout_service import get_rollout_plan, plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    await _configure_dispatch_for(db, user_id)

    result = await plan_rollout(db, user_id, [item_id])

    # No NotFoundError → no 404 on GET /api/rollouts/{id}/plan
    plan = await get_rollout_plan(db, user_id, result["rollout_id"])
    assert plan["edges"] == []
    assert plan["planner_model"] == "derived-from-blockers"


async def test_plan_rollout_serialises_file_overlap_without_blockers(db):
    """Two items touching the same file are serialised with no blocker recorded."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    shared = [{"path": "agent_gtd/src/agent_gtd/main.py", "change": "x"}]
    item_a = await _make_item(
        db, user_id, project_id, title="A", files_to_modify=shared
    )
    item_b = await _make_item(
        db, user_id, project_id, title="B", files_to_modify=shared
    )
    await _configure_dispatch_for(db, user_id)

    result = await plan_rollout(db, user_id, [item_a, item_b])

    assert result["plan"]["edges"] == [{"from_item_id": item_a, "to_item_id": item_b}]
    # In-degree drives readiness: A ready, B pending.
    rows = await db.fetch(
        "SELECT item_id, status FROM rollout_items WHERE rollout_id = $1",
        result["rollout_id"],
    )
    statuses = {str(r["item_id"]): str(r["status"]) for r in rows}
    assert statuses == {item_a: "ready", item_b: "pending"}


async def test_plan_rollout_ignores_blocker_outside_the_wave(db):
    """A blocker pointing outside the wave produces no edge (and no stuck item).

    The out-of-set blocker is resolved so the legality contract still passes;
    what matters is that no edge naming a non-node is persisted.
    """
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    inside = await _make_item(db, user_id, project_id, title="inside")
    outside = await _make_item(db, user_id, project_id, title="outside", status="done")
    await _add_blocker(db, inside, outside)
    await _configure_dispatch_for(db, user_id)

    result = await plan_rollout(db, user_id, [inside])

    assert result["plan"]["edges"] == []
    row = await db.fetchrow(
        "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        result["rollout_id"],
        inside,
    )
    assert row is not None
    assert row["status"] == "ready"


async def test_plan_rollout_cycle_marks_rollout_failed(db):
    """A cyclic blocker graph fails the rollout instead of persisting a bad plan."""
    from agent_gtd.services.rollout_service import plan_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(
        db,
        user_id,
        project_id,
        title="A",
        files_to_modify=[{"path": "src/a.py", "change": "x"}],
    )
    item_b = await _make_item(
        db,
        user_id,
        project_id,
        title="B",
        files_to_modify=[{"path": "src/b.py", "change": "y"}],
    )
    await _add_blocker(db, item_b, item_a)
    await _add_blocker(db, item_a, item_b)
    await _configure_dispatch_for(db, user_id)

    with pytest.raises(ValueError, match="cyclic dependency detected"):
        await plan_rollout(db, user_id, [item_a, item_b])

    rows = await db.fetch("SELECT status, halt_reason FROM autonomous_rollouts")
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "cyclic dependency detected" in str(rows[0]["halt_reason"])
    # Nothing downstream of the failure was written.
    assert await db.fetch("SELECT id FROM rollout_plans") == []
    assert await db.fetch("SELECT item_id FROM rollout_items") == []


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


# ---------------------------------------------------------------------------
# get_rollout / halt_rollout
# ---------------------------------------------------------------------------


from agent_gtd.services import rollout_service as _rollout_service  # noqa: E402
from agent_gtd.services.rollout_service import (  # noqa: E402
    get_rollout,
    halt_rollout,
)


async def test_get_rollout_returns_dict(db):
    """get_rollout returns the rollout row as a dict."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["id"] == rollout_id
    assert result["status"] == "running"
    assert result["lead_user_id"] == user_id


async def test_get_rollout_not_found_raises(db):
    """get_rollout raises NotFoundError for unknown IDs."""
    user_id = await _make_user(db)

    with pytest.raises(NotFoundError):
        await get_rollout(db, user_id, "nonexistent-id")


async def test_get_rollout_wrong_user_raises(db):
    """get_rollout raises NotFoundError when caller doesn't own the rollout."""
    user_id = await _make_user(db)
    other_user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with pytest.raises(NotFoundError):
        await get_rollout(db, other_user_id, rollout_id)


def test_relaunch_manage_rollout_is_retired():
    """The resident-manager relaunch surface is gone (item 7baf77d0)."""
    assert not hasattr(_rollout_service, "relaunch_manage_rollout")


async def test_nothing_writes_manage_retry_count(db):
    """The column stays for historical rows; no rollout operation bumps it."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await halt_rollout(db, user_id, rollout_id, "test halt")

    row = await get_rollout(db, user_id, rollout_id)
    assert row["manage_retry_count"] == 0


# ---------------------------------------------------------------------------
# halt_rollout — accepts pending status (updated validation)
# ---------------------------------------------------------------------------


async def test_halt_rollout_accepts_running_status(db):
    """halt_rollout succeeds when rollout status is 'running'."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
        patch(
            "agent_gtd.services.comment_service.create_comment",
            new_callable=AsyncMock,
            return_value={"id": "comment-id"},
        ),
    ):
        result = await halt_rollout(db, user_id, rollout_id, "test_halt")

    assert result["status"] == "halted"
    assert result["halt_reason"] == "test_halt"


async def test_halt_rollout_accepts_pending_status(db):
    """halt_rollout accepts pending status (for cap-exceeded path)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="pending")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
        patch(
            "agent_gtd.services.comment_service.create_comment",
            new_callable=AsyncMock,
            return_value={"id": "comment-id"},
        ),
    ):
        result = await halt_rollout(
            db, user_id, rollout_id, "manage_relaunch_cap_exceeded"
        )

    assert result["status"] == "halted"
    assert result["halt_reason"] == "manage_relaunch_cap_exceeded"


async def test_halt_rollout_rejects_completed_status(db):
    """halt_rollout still rejects completed status."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="completed")

    with pytest.raises(ValidationError):
        await halt_rollout(db, user_id, rollout_id, "should_fail")


async def test_halt_rollout_rejects_halted_status(db):
    """halt_rollout still rejects already-halted status."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")

    with pytest.raises(ValidationError):
        await halt_rollout(db, user_id, rollout_id, "should_fail")


# ---------------------------------------------------------------------------
# AC-3: complete_item_in_rollout from 'ready' status (inline-management path)
# ---------------------------------------------------------------------------


async def test_complete_item_in_rollout_from_ready(db):
    """AC-3: complete_item_in_rollout succeeds when item status is 'ready'.

    This tests the inline-management path: manage agent completes an item
    directly without dispatching a child build run (ready → terminal, skipping
    the dispatched intermediate state).
    """
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    # Item is in 'ready' state — no child build was dispatched (inline path)
    await _make_wave_plan_item(db, rollout_id, item_id, status="ready")

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

    # Outcome should succeed
    assert result["rollout_item"]["status"] == "completed"
    assert result["graph_complete"] is True  # only item in the rollout

    # GTD item should be marked done
    row = await db.fetchrow(
        "SELECT status, completed_at FROM items WHERE id = $1", item_id
    )
    assert row is not None
    assert row["status"] == "done"
    assert row["completed_at"] is not None


async def test_complete_item_in_rollout_from_ready_unblocks_downstream(db):
    """AC-3: completing a 'ready' item unblocks its downstream successor."""
    import json

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, title="Item A", status="active")
    item_b = await _make_item(db, user_id, project_id, title="Item B", status="ready")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    # A is ready (inline), B is pending (blocked on A)
    await _make_wave_plan_item(db, rollout_id, item_a, status="ready")
    await _make_wave_plan_item(db, rollout_id, item_b, status="pending")

    # Insert rollout_plans so downstream unblocking logic can traverse the DAG
    plan_id = str(uuid.uuid4())
    edges = [{"from_item_id": item_a, "to_item_id": item_b}]
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        1,
        json.dumps([item_a, item_b]),
        json.dumps(edges),
        "test-model",
        NOW,
    )

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_a, outcome="completed"
        )

    # B should now be ready
    assert item_b in result["newly_ready"]
    assert result["graph_complete"] is False

    b_status = await _get_wave_item_status(db, rollout_id, item_b)
    assert b_status == "ready"


async def test_complete_item_in_rollout_rejects_pending_status(db):
    """complete_item_in_rollout still rejects items in 'pending' status."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="pending")

    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
        pytest.raises(ValidationError, match="pending"),
    ):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )


async def _count_events(db, rollout_id: str) -> int:
    row = await db.fetchrow(
        "SELECT COUNT(*) AS n FROM rollout_events WHERE rollout_id = $1", rollout_id
    )
    return int(row["n"])


async def _complete_twice_setup(db, *, extra_pending: bool = False):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")
    return user_id, rollout_id, item_id


async def test_complete_item_in_rollout_repeat_is_idempotent(db):
    user_id, rollout_id, item_id = await _complete_twice_setup(db)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        first = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
        events_before = await _count_events(db, rollout_id)
        row_before = await db.fetchrow(
            "SELECT completed_at FROM rollout_items"
            " WHERE rollout_id = $1 AND item_id = $2",
            rollout_id,
            item_id,
        )
        second = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
        row_after = await db.fetchrow(
            "SELECT completed_at FROM rollout_items"
            " WHERE rollout_id = $1 AND item_id = $2",
            rollout_id,
            item_id,
        )
    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    assert second["newly_ready"] == []
    assert await _count_events(db, rollout_id) == events_before
    assert row_after["completed_at"] == row_before["completed_at"]
    # Single-item wave: first call closed the rollout, repeat reports it.
    assert first["graph_complete"] is True
    assert second["graph_complete"] is True


async def test_complete_item_in_rollout_repeat_graph_complete_false_when_open(db):
    user_id, rollout_id, item_id = await _complete_twice_setup(db)
    other = await _make_item(db, user_id, await _project_of(db, item_id))
    await _make_wave_plan_item(db, rollout_id, other, status="dispatched")
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
        second = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
    assert second["already_recorded"] is True
    assert second["graph_complete"] is False


async def test_complete_item_in_rollout_repeat_heals_partial_write(db):
    """AC11(a): a repeat completes a downstream unblock + item cascade that an
    earlier, partially-failed call left undone."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, title="A", status="review")
    item_b = await _make_item(db, user_id, project_id, title="B", status="ready")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_a, status="dispatched")
    await _make_wave_plan_item(db, rollout_id, item_b, status="pending")
    await _make_rollout_plan(
        db,
        rollout_id,
        [item_a, item_b],
        [{"from_item_id": item_a, "to_item_id": item_b}],
    )
    # Simulate a partial earlier write: the row went terminal, nothing else.
    await db.execute(
        "UPDATE rollout_items SET status = 'completed'"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_a,
    )
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_a, outcome="completed"
        )
    assert result["already_recorded"] is True
    assert result["newly_ready"] == [item_b]
    assert result["graph_complete"] is False
    b_row = await db.fetchrow(
        "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_b,
    )
    assert b_row["status"] == "ready"
    a_item = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_a)
    assert a_item["status"] == "done"


async def test_complete_item_in_rollout_repeat_closes_open_rollout(db):
    """AC11: a repeat closes a rollout whose items are all terminal."""
    user_id, rollout_id, item_id = await _complete_twice_setup(db)
    await db.execute(
        "UPDATE rollout_items SET status = 'completed'"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
    assert result["already_recorded"] is True
    assert result["graph_complete"] is True
    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row["status"] == "completed"
    n = await db.fetchrow(
        "SELECT COUNT(*) AS n FROM rollout_events"
        " WHERE rollout_id = $1 AND kind = 'wave_completed'",
        rollout_id,
    )
    assert int(n["n"]) == 1


async def test_complete_item_in_rollout_repeat_heals_missing_merge_note(db):
    """AC11(b): a repeat appends a missing merge_note event exactly once."""
    user_id, rollout_id, item_id = await _complete_twice_setup(db)
    other = await _make_item(db, user_id, await _project_of(db, item_id))
    await _make_wave_plan_item(db, rollout_id, other, status="dispatched")
    await db.execute(
        "UPDATE rollout_items SET status = 'completed'"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )

    async def _note_count() -> int:
        row = await db.fetchrow(
            "SELECT COUNT(*) AS n FROM rollout_events"
            " WHERE rollout_id = $1 AND kind = $2",
            rollout_id,
            MERGE_NOTE_EVENT_KIND,
        )
        return int(row["n"])

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed", merge_note="n"
        )
        assert await _note_count() == 1
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed", merge_note="n"
        )
        assert await _note_count() == 1


async def _project_of(db, item_id: str) -> str:
    row = await db.fetchrow("SELECT project_id FROM items WHERE id = $1", item_id)
    return str(row["project_id"])


async def test_complete_item_in_rollout_different_terminal_outcome_rejected(db):
    user_id, rollout_id, item_id = await _complete_twice_setup(db)
    other = await _make_item(db, user_id, await _project_of(db, item_id))
    await _make_wave_plan_item(db, rollout_id, other, status="dispatched")
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
        with pytest.raises(ValidationError, match=r"completed.*skipped"):
            await complete_item_in_rollout(
                db, user_id, rollout_id, item_id, outcome="skipped"
            )


async def _halted_item_setup(db, rollout_status: str = "halted"):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    rollout_id = await _make_rollout(db, user_id, project_id, status=rollout_status)
    await _make_wave_plan_item(db, rollout_id, item_id, status="halted")
    return user_id, project_id, rollout_id, item_id


async def test_halted_item_override_to_completed(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
    assert result["already_recorded"] is False
    assert result["graph_complete"] is True
    row = await db.fetchrow(
        "SELECT status, merge_actor FROM rollout_items"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    assert row["status"] == "completed"
    assert row["merge_actor"] == "lead"
    gtd = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_id)
    assert gtd["status"] == "done"


async def test_halted_item_override_keeps_supplied_merge_actor(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db, "running")
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, "completed", merge_actor="human"
        )
    row = await db.fetchrow(
        "SELECT merge_actor FROM rollout_items WHERE item_id = $1", item_id
    )
    assert row["merge_actor"] == "human"


async def test_halted_item_override_to_skipped(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="skipped"
        )
    assert await _get_wave_item_status(db, rollout_id, item_id) == "skipped"


async def test_halted_item_override_refused_when_rollout_cancelled(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db, "cancelled")
    with pytest.raises(ValidationError, match="already has terminal status"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="completed"
        )
    assert await _get_wave_item_status(db, rollout_id, item_id) == "halted"


async def test_completed_to_skipped_still_refused(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db)
    await db.execute(
        "UPDATE rollout_items SET status = 'completed' WHERE item_id = $1", item_id
    )
    with pytest.raises(ValidationError, match="cannot record a different outcome"):
        await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, outcome="skipped"
        )


async def test_resume_sweeps_done_item_and_unblocks_successor(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    a = await _make_item(db, user_id, project_id, status="done")
    b = await _make_item(db, user_id, project_id, status="ready")
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, a, status="halted")
    await _make_wave_plan_item(db, rollout_id, b, status="pending")
    await _make_rollout_plan(
        db, rollout_id, [a, b], [{"from_item_id": a, "to_item_id": b}]
    )
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await resume_rollout(
            db, rollout_id, "landed by hand", user_id, relaunch=False
        )
    assert await _get_wave_item_status(db, rollout_id, a) == "completed"
    assert await _get_wave_item_status(db, rollout_id, b) == "ready"
    row = await db.fetchrow(
        "SELECT merge_actor FROM rollout_items WHERE item_id = $1", a
    )
    assert row["merge_actor"] == "external"
    assert result["done_count"] == 1
    assert result["loop_run_id"] is None


async def test_resume_closes_rollout_when_all_items_done(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db)
    await db.execute("UPDATE items SET status = 'done' WHERE id = $1", item_id)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await resume_rollout(db, rollout_id, "ok", user_id, relaunch=False)
    assert result["status"] == "completed"
    assert result["done_count"] == 1
    assert result["loop_run_id"] is None


async def test_resume_leaves_not_done_item_untouched(db):
    user_id, _, rollout_id, item_id = await _halted_item_setup(db)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await resume_rollout(db, rollout_id, "ok", user_id, relaunch=False)
    assert result["done_count"] == 0
    assert await _get_wave_item_status(db, rollout_id, item_id) == "ready"


# ---------------------------------------------------------------------------
# AC-4: Full managed-rollout happy path (state machine end-to-end)
# ---------------------------------------------------------------------------


async def _make_rollout_plan(
    db,
    rollout_id: str,
    nodes: list[str],
    edges: list[dict],
) -> str:
    """Insert a rollout_plans row and return its ID."""
    import json

    plan_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        1,
        json.dumps(nodes),
        json.dumps(edges),
        "test-model",
        NOW,
    )
    return plan_id


async def test_managed_rollout_happy_path(db):
    """AC-4: Full end-to-end state machine for a 2-item rollout with A→B dependency.

    Simulates the complete managed-rollout flow:
    1. Create rollout with 2 items (A depends on B completing first: A→B edge means
       B blocks A, so A is a successor of B).
    2. Start rollout (pending → running).
    3. Dispatch child build for item A (rollout_items.A → dispatched).
    4. Complete item A (B becomes ready).
    5. Dispatch child build for item B (rollout_items.B → dispatched).
    6. Complete item B → rollout reaches 'completed'.

    This test would have caught both Bug 1 and Bug 2 in the real incident.
    """
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, title="Item A", status="ready")
    item_b = await _make_item(db, user_id, project_id, title="Item B", status="ready")

    # Create rollout in pending state
    rollout_id = await _make_rollout(db, user_id, project_id, status="pending")

    # Set up DAG: A → B (A must complete before B can run)
    # from_item_id=A, to_item_id=B means B depends on A
    edges = [{"from_item_id": item_a, "to_item_id": item_b}]
    await _make_rollout_plan(db, rollout_id, [item_a, item_b], edges)

    # Insert rollout_items: A is ready (no deps), B is pending (blocked on A)
    await _make_wave_plan_item(db, rollout_id, item_a, status="ready")
    await _make_wave_plan_item(db, rollout_id, item_b, status="pending")

    # Step 1: Start rollout (pending → running)
    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        result = await start_rollout(db, user_id, rollout_id)
    assert result["status"] == "running"

    # Step 2: Simulate dispatch of child build for A (ready → dispatched)
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_a,
    )

    # Step 3: Complete item A → B becomes ready
    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result_a = await complete_item_in_rollout(
            db, user_id, rollout_id, item_a, outcome="completed"
        )

    assert item_b in result_a["newly_ready"]
    assert result_a["graph_complete"] is False

    b_status = await _get_wave_item_status(db, rollout_id, item_b)
    assert b_status == "ready"

    # Step 4: Simulate dispatch of child build for B (ready → dispatched)
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_b,
    )

    # Step 5: Complete item B → rollout completes
    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        result_b = await complete_item_in_rollout(
            db, user_id, rollout_id, item_b, outcome="completed"
        )

    assert result_b["graph_complete"] is True

    # Verify rollout reached 'completed' status
    rollout_row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout_row is not None
    assert rollout_row["status"] == "completed"

    # Verify both GTD items are 'done'
    a_row = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_a)
    b_row = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_b)
    assert a_row["status"] == "done"
    assert b_row["status"] == "done"


# ---------------------------------------------------------------------------
# check_halted_rollout_completion — AC-1, AC-6, AC-7
# ---------------------------------------------------------------------------


from agent_gtd.services.rollout_service import (  # noqa: E402
    check_halted_rollout_completion,
)


async def test_check_halted_rollout_completion_closes_rollout(db):
    """AC-6: Halted rollout with all GTD items done → transitions to completed."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item1_id = await _make_item(db, user_id, project_id, title="Item 1", status="done")
    item2_id = await _make_item(db, user_id, project_id, title="Item 2", status="done")
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item1_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item2_id, status="halted")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await check_halted_rollout_completion(db, item1_id)

    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    assert row["status"] == "completed"


async def test_check_halted_rollout_completion_cancelled_item_counts(db):
    """AC-1: Halted rollout with all GTD items in {done, cancelled} → completed."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item1_id = await _make_item(db, user_id, project_id, title="Item 1", status="done")
    item2_id = await _make_item(
        db, user_id, project_id, title="Item 2", status="cancelled"
    )
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item1_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item2_id, status="halted")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await check_halted_rollout_completion(db, item1_id)

    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    assert row["status"] == "completed"


async def test_check_halted_rollout_completion_partial_not_closed(db):
    """AC-6: Halted rollout with only 1 of 2 items done → stays halted."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item1_id = await _make_item(db, user_id, project_id, title="Item 1", status="done")
    item2_id = await _make_item(
        db, user_id, project_id, title="Item 2", status="active"
    )
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item1_id, status="halted")
    await _make_wave_plan_item(db, rollout_id, item2_id, status="halted")

    with patch("agent_gtd.services.rollout_service._publish_rollout_event"):
        await check_halted_rollout_completion(db, item1_id)

    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    assert row["status"] == "halted"


async def test_check_halted_rollout_completion_not_halted_no_op(db):
    """AC-7: Running rollout is not auto-closed even when items are all done."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item1_id = await _make_item(db, user_id, project_id, title="Item 1", status="done")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item1_id, status="dispatched")

    # Should be a no-op — running rollouts are ignored
    with patch("agent_gtd.services.rollout_service._publish_rollout_event") as mock_pub:
        await check_halted_rollout_completion(db, item1_id)

    # Rollout should still be running
    row = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    assert row["status"] == "running"
    mock_pub.assert_not_called()


# ---------------------------------------------------------------------------
# Merge notes — persistence and retrieval
# ---------------------------------------------------------------------------


async def _complete_with_note(
    db, user_id, rollout_id, item_id, note, *, outcome="completed"
):
    """Complete a rollout item with a merge note, with side effects patched out."""
    with (
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_item",
            new_callable=AsyncMock,
        ),
        patch("agent_gtd.services.rollout_service._publish_rollout_event"),
    ):
        return await complete_item_in_rollout(
            db,
            user_id,
            rollout_id,
            item_id,
            outcome=outcome,
            merge_actor="manager-autonomous",
            merge_note=note,
        )


async def test_merge_note_persisted_and_retrievable(db):
    """A merge note supplied at merge time is stored and read back."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    note = "resolve_max_turns() gained a `mode` param; config key dispatch.foo renamed"
    await _complete_with_note(db, user_id, rollout_id, item_id, note)

    notes = await get_recent_merge_notes(db, rollout_id, user_id)
    assert len(notes) == 1
    assert notes[0]["item_id"] == item_id
    assert notes[0]["note"] == note
    assert notes[0]["outcome"] == "completed"


async def test_merge_note_stored_as_rollout_event(db):
    """The note lands in rollout_events under the merge_note kind."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    await _complete_with_note(db, user_id, rollout_id, item_id, "renamed Foo → Bar")

    rows = await db.fetch(
        "SELECT kind FROM rollout_events WHERE rollout_id = $1 AND kind = $2",
        rollout_id,
        MERGE_NOTE_EVENT_KIND,
    )
    assert len(rows) == 1


async def test_no_merge_note_event_when_note_empty(db):
    """Omitting the note (today's callers) appends no merge_note event."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    await _complete_with_note(db, user_id, rollout_id, item_id, "   ")

    assert await get_recent_merge_notes(db, rollout_id, user_id) == []


async def test_merge_notes_newest_first_and_limited(db):
    """Notes come back newest-first and honour the limit."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    item_ids = []
    for n in range(3):
        item_id = await _make_item(
            db, user_id, project_id, status="review", title=f"Item {n}"
        )
        item_ids.append(item_id)
        await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    for n, item_id in enumerate(item_ids):
        await _complete_with_note(db, user_id, rollout_id, item_id, f"note {n}")

    notes = await get_recent_merge_notes(db, rollout_id, user_id)
    assert [x["note"] for x in notes] == ["note 2", "note 1", "note 0"]

    assert [
        x["note"]
        for x in await get_recent_merge_notes(db, rollout_id, user_id, limit=2)
    ] == ["note 2", "note 1"]


async def test_merge_note_truncated_to_max_chars(db):
    """An over-long note is clipped rather than crowding out other notes."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="review")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    await _complete_with_note(db, user_id, rollout_id, item_id, "x" * 5000)

    notes = await get_recent_merge_notes(db, rollout_id, user_id)
    assert len(notes[0]["note"]) == MERGE_NOTE_MAX_CHARS


async def test_merge_notes_scoped_to_rollout(db):
    """Notes from another rollout never leak into this one's list."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_a = await _make_rollout(db, user_id, project_id, status="running")
    rollout_b = await _make_rollout(db, user_id, project_id, status="running")

    item_a = await _make_item(db, user_id, project_id, status="review", title="A")
    item_b = await _make_item(db, user_id, project_id, status="review", title="B")
    await _make_wave_plan_item(db, rollout_a, item_a, status="dispatched")
    await _make_wave_plan_item(db, rollout_b, item_b, status="dispatched")

    await _complete_with_note(db, user_id, rollout_a, item_a, "note A")
    await _complete_with_note(db, user_id, rollout_b, item_b, "note B")

    assert [
        n["note"] for n in await get_recent_merge_notes(db, rollout_a, user_id)
    ] == ["note A"]


async def test_merge_notes_rejects_foreign_user(db):
    """A user who does not own the rollout cannot read its merge notes."""
    user_id = await _make_user(db)
    other_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with pytest.raises(NotFoundError):
        await get_recent_merge_notes(db, rollout_id, other_id)


# ---------------------------------------------------------------------------
# reset_rollout_item — the seam a `re-dispatch` review verdict needs
#
# dispatch_item's wave linkage is guarded by `AND status = 'ready'`. That guard
# is what makes dispatch idempotent (and the startup re-adoption sweep safe),
# but it also makes a bare re-dispatch of a `dispatched` item a SILENT no-op.
# Resetting first keeps the guard doing its job instead of weakening it.
# ---------------------------------------------------------------------------


async def _make_claude_run(db, user_id: str, project_id: str) -> str:
    run_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, project_id, user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        run_id,
        project_id,
        user_id,
        "failed",
        NOW,
        NOW,
    )
    return run_id


async def test_reset_rollout_item_returns_a_dispatched_item_to_ready(db):
    from agent_gtd.services.rollout_service import reset_rollout_item

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    item_id = await _make_item(db, user_id, project_id)
    run_id = await _make_claude_run(db, user_id, project_id)
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")
    await db.execute(
        "UPDATE rollout_items SET claude_run_id = $1"
        " WHERE rollout_id = $2 AND item_id = $3",
        run_id,
        rollout_id,
        item_id,
    )

    result = await reset_rollout_item(db, user_id, rollout_id, item_id)

    assert result["status"] == "ready"
    assert result["previous_run_id"] == run_id
    assert await _get_wave_item_status(db, rollout_id, item_id) == "ready"
    row = await db.fetchrow(
        "SELECT claude_run_id FROM rollout_items"
        " WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    assert row["claude_run_id"] is None


async def test_reset_rollout_item_appends_an_item_reset_event(db):
    from agent_gtd.services.rollout_service import reset_rollout_item

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    item_id = await _make_item(db, user_id, project_id)
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    await reset_rollout_item(db, user_id, rollout_id, item_id)

    rows = await db.fetch(
        "SELECT kind FROM rollout_events WHERE rollout_id = $1", rollout_id
    )
    assert "item_reset" in [r["kind"] for r in rows]


async def test_reset_rollout_item_rejects_a_non_running_rollout(db):
    from agent_gtd.services.rollout_service import reset_rollout_item

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    item_id = await _make_item(db, user_id, project_id)
    await _make_wave_plan_item(db, rollout_id, item_id, status="dispatched")

    with pytest.raises(ValidationError, match="not running"):
        await reset_rollout_item(db, user_id, rollout_id, item_id)


async def test_reset_rollout_item_rejects_a_non_dispatched_item(db):
    from agent_gtd.services.rollout_service import reset_rollout_item

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    item_id = await _make_item(db, user_id, project_id)
    await _make_wave_plan_item(db, rollout_id, item_id, status="ready")

    with pytest.raises(ValidationError, match="only a dispatched item"):
        await reset_rollout_item(db, user_id, rollout_id, item_id)


async def test_reset_rollout_item_unknown_item_is_not_found(db):
    from agent_gtd.services.rollout_service import reset_rollout_item

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    with pytest.raises(NotFoundError):
        await reset_rollout_item(db, user_id, rollout_id, "no-such-item")


# ---------------------------------------------------------------------------
# halt/cancel and the rollout's child build runs
# ---------------------------------------------------------------------------


async def _make_child_run(
    db,
    user_id: str,
    project_id: str,
    rollout_id: str,
    *,
    status: str = "running",
    mode: str = "build",
    remote_run_id: str = "",
    dispatch_host_url: str = "",
) -> str:
    run_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, project_id, user_id, status, mode, rollout_id, remote_run_id,"
        "  dispatch_host_url, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        run_id,
        project_id,
        user_id,
        status,
        mode,
        rollout_id,
        remote_run_id,
        dispatch_host_url,
        NOW,
        NOW,
    )
    return run_id


async def _run_status(db, run_id: str) -> str:
    row = await db.fetchrow("SELECT status FROM claude_runs WHERE id = $1", run_id)
    assert row is not None
    return str(row["status"])


_CHILD_HOSTS = [{"url": "https://host-b", "api_key": "kb", "drain_reason": None}]


def _forward_client_mock(*, side_effect: Exception | None = None):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = 200
    resp.text = "OK"
    inst = MagicMock()
    inst.__aenter__ = AsyncMock(return_value=inst)
    inst.__aexit__ = AsyncMock(return_value=None)
    inst.post = AsyncMock(return_value=resp, side_effect=side_effect)
    return inst


def _halt_cancel_patches(client_mock):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("httpx.AsyncClient", return_value=client_mock))
    stack.enter_context(
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=_CHILD_HOSTS),
        )
    )
    stack.enter_context(
        patch(
            "agent_gtd.services.rollout_lock_service.release_rollout_locks",
            new_callable=AsyncMock,
        )
    )
    stack.enter_context(
        patch("agent_gtd.services.rollout_service._publish_rollout_event")
    )
    stack.enter_context(
        patch(
            "agent_gtd.services.comment_service.create_comment",
            new_callable=AsyncMock,
            return_value={"id": "comment-id"},
        )
    )
    return stack


async def test_cancel_rollout_cancels_active_child_runs_and_forwards(db):
    """AC-1: active non-manage children cancelled + forwarded by remote_run_id."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    running = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        remote_run_id="remote-1",
        dispatch_host_url="https://host-b",
    )
    done = await _make_child_run(
        db, user_id, project_id, rollout_id, status="success", remote_run_id="r-2"
    )
    manage = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        mode="manage",
        remote_run_id="remote-m",
        dispatch_host_url="https://host-b",
    )
    other_rollout = await _make_rollout(db, user_id, project_id, status="running")
    foreign = await _make_child_run(db, user_id, project_id, other_rollout)

    client_mock = _forward_client_mock()
    with _halt_cancel_patches(client_mock):
        result = await cancel_rollout(db, user_id, rollout_id, "abort")

    assert result["status"] == "cancelled"
    assert result["cancelled_run_ids"] == [running]
    assert await _run_status(db, running) == "cancelled"
    assert await _run_status(db, done) == "success"
    assert await _run_status(db, manage) == "running"
    assert await _run_status(db, foreign) == "running"
    client_mock.post.assert_awaited_once()
    assert client_mock.post.await_args.args[0] == (
        "https://host-b/runs/remote-1/cancel"
    )


async def test_cancel_rollout_forward_failure_keeps_local_cancel(db):
    """AC-6: a failing host forward never fails the cancel or rolls back."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    run_id = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        remote_run_id="remote-1",
        dispatch_host_url="https://host-b",
    )

    client_mock = _forward_client_mock(side_effect=httpx.ConnectError("down"))
    with _halt_cancel_patches(client_mock):
        result = await cancel_rollout(db, user_id, rollout_id, "abort")

    assert result["status"] == "cancelled"
    assert result["cancelled_run_ids"] == [run_id]
    assert await _run_status(db, run_id) == "cancelled"


async def test_cancel_rollout_recancel_is_noop(db):
    """AC-3: re-cancelling forwards nothing and returns empty cancelled_run_ids."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="cancelled")
    # A straggler on an already-cancelled rollout is left for cancel-run.
    run_id = await _make_child_run(
        db, user_id, project_id, rollout_id, remote_run_id="remote-1"
    )

    client_mock = _forward_client_mock()
    with _halt_cancel_patches(client_mock):
        result = await cancel_rollout(db, user_id, rollout_id, "again")

    assert result["status"] == "cancelled"
    assert result["cancelled_run_ids"] == []
    client_mock.post.assert_not_awaited()
    assert await _run_status(db, run_id) == "running"


async def test_cancel_rollout_of_halted_rollout_cancels_running_children(db):
    """AC-3: halt leaves a build running; a later cancel-rollout stops it."""
    from agent_gtd.services.rollout_service import halt_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    run_id = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        remote_run_id="remote-1",
        dispatch_host_url="https://host-b",
    )

    client_mock = _forward_client_mock()
    with _halt_cancel_patches(client_mock):
        halted = await halt_rollout(db, user_id, rollout_id, "reviewer_halt")
        assert halted["in_flight_run_ids"] == [run_id]
        assert await _run_status(db, run_id) == "running"
        client_mock.post.assert_not_awaited()

        result = await cancel_rollout(db, user_id, rollout_id, "stop it")

    assert result["cancelled_run_ids"] == [run_id]
    assert await _run_status(db, run_id) == "cancelled"
    client_mock.post.assert_awaited_once()


async def test_halt_rollout_leaves_running_children_and_cancels_unrouted(db):
    """AC-2/AC-5: halt keeps routed builds, cancels not-yet-routed ones."""
    from agent_gtd.services.rollout_service import halt_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    running = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        remote_run_id="remote-1",
        dispatch_host_url="https://host-b",
    )
    unrouted = await _make_child_run(
        db, user_id, project_id, rollout_id, status="pending"
    )
    manage = await _make_child_run(
        db, user_id, project_id, rollout_id, mode="manage", remote_run_id="m"
    )

    client_mock = _forward_client_mock()
    with _halt_cancel_patches(client_mock):
        result = await halt_rollout(db, user_id, rollout_id, "merge_rejected")

    assert result["status"] == "halted"
    assert result["in_flight_run_ids"] == [running]
    assert result["cancelled_run_ids"] == [unrouted]
    assert await _run_status(db, running) == "running"
    assert await _run_status(db, unrouted) == "cancelled"
    assert await _run_status(db, manage) == "running"
    # The unrouted run has no remote id, so nothing is forwarded.
    client_mock.post.assert_not_awaited()


async def test_cancel_run_of_child_after_halt_is_allowed(db):
    """AC-4: after a halt, cancel-run (no force) stops the orphaned child."""
    from agent_gtd.services.dispatch_service import cancel_run
    from agent_gtd.services.rollout_service import halt_rollout

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    run_id = await _make_child_run(
        db,
        user_id,
        project_id,
        rollout_id,
        remote_run_id="remote-1",
        dispatch_host_url="https://host-b",
    )

    client_mock = _forward_client_mock()
    with _halt_cancel_patches(client_mock):
        with pytest.raises(ValidationError):
            await cancel_run(db, user_id, run_id)
        await halt_rollout(db, user_id, rollout_id, "reviewer_halt")
        updated = await cancel_run(db, user_id, run_id)

    assert updated["status"] == "cancelled"
    client_mock.post.assert_awaited_once()
    assert client_mock.post.await_args.args[0] == (
        "https://host-b/runs/remote-1/cancel"
    )


# ---------------------------------------------------------------------------
# get_rollout: loop_host_url / loop_host_drain_reason (drain-park signal)
# ---------------------------------------------------------------------------


async def _make_manage_run(
    db,
    user_id: str,
    project_id: str,
    rollout_id: str,
    host_url: str,
    *,
    created_at: str = NOW,
) -> str:
    run_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, project_id, user_id, status, mode, rollout_id,"
        " dispatch_host_url, created_at, updated_at)"
        " VALUES ($1, $2, $3, 'running', 'manage', $4, $5, $6, $7)",
        run_id,
        project_id,
        user_id,
        rollout_id,
        host_url,
        created_at,
        created_at,
    )
    return run_id


async def _add_host(db, user_id: str, url: str, label: str = "h1") -> str:
    from agent_gtd.services import settings_service

    host = await settings_service.add_dispatch_host(db, user_id, label, url, "key")
    return str(host["id"])


async def test_get_rollout_loop_host_none_without_manage_run(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_url"] is None
    assert result["loop_host_drain_reason"] is None


async def test_get_rollout_loop_host_undrained(db):
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _add_host(db, user_id, "http://h1:8100")
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://h1:8100/")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_url"] == "http://h1:8100"
    assert result["loop_host_drain_reason"] is None


async def test_get_rollout_loop_host_drained_reports_reason(db):
    from agent_gtd.services import settings_service

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    host_id = await _add_host(db, user_id, "http://h1:8100")
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://h1:8100")
    await settings_service.drain_dispatch_host(db, user_id, host_id, "rolling deploy")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_url"] == "http://h1:8100"
    assert result["loop_host_drain_reason"] == "rolling deploy"


async def test_get_rollout_loop_host_pinned_wins_over_manage_run(db):
    from agent_gtd.services import settings_service

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    pinned_id = await _add_host(db, user_id, "http://pinned:8100", label="p")
    await _add_host(db, user_id, "http://other:8100", label="o")
    await db.execute(
        "UPDATE autonomous_rollouts SET dispatch_host_id = $1 WHERE id = $2",
        pinned_id,
        rollout_id,
    )
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://other:8100")
    await settings_service.drain_dispatch_host(db, user_id, pinned_id, "pin drain")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_url"] == "http://pinned:8100"
    assert result["loop_host_drain_reason"] == "pin drain"


async def test_get_rollout_loop_host_drain_matches_across_users(db):
    from agent_gtd.services import settings_service

    user_id = await _make_user(db)
    other_user = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    await _add_host(db, user_id, "http://h1:8100")
    other_host = await _add_host(db, other_user, "http://h1:8100")
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://h1:8100")
    await settings_service.drain_dispatch_host(
        db, other_user, other_host, "other user drain"
    )

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_drain_reason"] == "other user drain"


async def test_get_rollout_loop_host_trailing_slash_matches(db):
    from agent_gtd.services import settings_service

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    host_id = await _add_host(db, user_id, "http://h1:8100")
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://h1:8100/")
    await settings_service.drain_dispatch_host(db, user_id, host_id, "slash")

    result = await get_rollout(db, user_id, rollout_id)

    assert result["loop_host_url"] == "http://h1:8100"
    assert result["loop_host_drain_reason"] == "slash"


async def test_get_rollout_loop_host_reason_clears_after_undrain(db):
    from agent_gtd.services import settings_service

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")
    host_id = await _add_host(db, user_id, "http://h1:8100")
    await _make_manage_run(db, user_id, project_id, rollout_id, "http://h1:8100")
    await settings_service.drain_dispatch_host(db, user_id, host_id, "deploy")
    assert (await get_rollout(db, user_id, rollout_id))[
        "loop_host_drain_reason"
    ] == "deploy"

    await settings_service.undrain_dispatch_host(db, user_id, host_id)

    result = await get_rollout(db, user_id, rollout_id)
    assert result["loop_host_drain_reason"] is None
    assert result["loop_host_url"] == "http://h1:8100"
