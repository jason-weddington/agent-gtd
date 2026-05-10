"""Tests for wave_reaper background job and ping_wave service function."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_gtd.database import get_db
from agent_gtd.wave_reaper import _reap_crashed_waves

# ---------------------------------------------------------------------------
# Timestamp helpers — computed at call time so tests don't go stale when the
# full suite takes several minutes to run.
# ---------------------------------------------------------------------------


def _now_str() -> str:
    return datetime.now(UTC).isoformat()


def _stale_ts() -> str:
    """10 minutes ago — exceeds the 300-second stale threshold."""
    return (datetime.now(UTC) - timedelta(seconds=600)).isoformat()


def _past_grace_ts() -> str:
    """5 minutes ago — exceeds the 120-second merge-grace window."""
    return (datetime.now(UTC) - timedelta(seconds=300)).isoformat()


def _within_grace_ts() -> str:
    """30 seconds ago — within the 120-second merge-grace window."""
    return (datetime.now(UTC) - timedelta(seconds=30)).isoformat()


def _fresh_ts() -> str:
    """5 seconds ago — well within the 300-second stale threshold."""
    return (datetime.now(UTC) - timedelta(seconds=5)).isoformat()


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Return the patched test database pool (autouse _setup_db applies schema)."""
    return await get_db()


# ---------------------------------------------------------------------------
# Helper functions to insert rows directly
# ---------------------------------------------------------------------------


async def _make_user(db) -> str:
    user_id = str(uuid.uuid4())
    now = _now_str()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id[:8]}@test.com",
        "hashed",
        now,
    )
    return user_id


async def _make_project(db, user_id: str) -> str:
    project_id = str(uuid.uuid4())
    now = _now_str()
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Test Project",
        now,
        now,
    )
    return project_id


async def _make_item(db, user_id: str, project_id: str) -> str:
    item_id = str(uuid.uuid4())
    now = _now_str()
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, labels, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        "Test Item",
        "[]",
        now,
        now,
    )
    return item_id


async def _make_wave_run(
    db,
    project_id: str,
    user_id: str,
    *,
    status: str = "running",
    updated_at: str | None = None,
) -> str:
    wave_run_id = str(uuid.uuid4())
    now = _now_str()
    await db.execute(
        "INSERT INTO autonomous_wave_runs "
        "(id, project_id, lead_user_id, status, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        wave_run_id,
        project_id,
        user_id,
        status,
        now,
        updated_at if updated_at is not None else now,
    )
    return wave_run_id


async def _make_claude_run(
    db,
    item_id: str,
    project_id: str,
    user_id: str,
    *,
    status: str = "running",
    finished_at: str | None = None,
    wave_run_id: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    now = _now_str()
    await db.execute(
        "INSERT INTO claude_runs "
        "(id, item_id, project_id, user_id, status, finished_at, wave_run_id, "
        " created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        run_id,
        item_id,
        project_id,
        user_id,
        status,
        finished_at,
        wave_run_id,
        now,
        now,
    )
    return run_id


async def _make_wave_plan_item(
    db,
    wave_run_id: str,
    item_id: str,
    *,
    status: str = "pending",
    claude_run_id: str | None = None,
) -> None:
    await db.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id, status, claude_run_id) "
        "VALUES ($1, $2, $3, $4)",
        wave_run_id,
        item_id,
        status,
        claude_run_id,
    )


async def _make_wave_event(
    db,
    wave_run_id: str,
    *,
    ts: str | None = None,
    kind: str = "heartbeat",
    seq: int = 1,
) -> None:
    event_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO wave_events (id, wave_run_id, seq, ts, kind, actor, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        event_id,
        wave_run_id,
        seq,
        ts if ts is not None else _now_str(),
        kind,
        "manager",
        "{}",
    )


# ---------------------------------------------------------------------------
# AC-1 / AC-2 / AC-3: staleness + compound condition
# ---------------------------------------------------------------------------


async def test_no_reap_stale_heartbeat_no_dispatched_items(db):
    """Stale wave with all items pending — NOT reaped (AC-3)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())

    # Wave event is stale (satisfies AC-1)
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    # Item is pending — no dispatched items (AC-2 not satisfied)
    await _make_wave_plan_item(db, wave_run_id, item_id, status="pending")

    reaped = await _reap_crashed_waves(db)

    assert reaped == 0
    row = await db.fetchrow(
        "SELECT status FROM autonomous_wave_runs WHERE id = $1", wave_run_id
    )
    assert row["status"] == "running"


async def test_no_reap_dispatched_child_still_running(db):
    """Dispatched item with child run still running — NOT reaped (AC-2)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    # Child run is still running — not terminal
    run_id = await _make_claude_run(db, item_id, project_id, user_id, status="running")
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    reaped = await _reap_crashed_waves(db)

    assert reaped == 0


async def test_no_reap_child_terminal_within_grace(db):
    """Child terminal but finished_at < grace ago — NOT reaped (AC-2)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    # Child finished only 30s ago — within the grace window (default 120s)
    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="success",
        finished_at=_within_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    reaped = await _reap_crashed_waves(db)

    assert reaped == 0


async def test_no_reap_wave_already_terminal(db):
    """Wave with status='crashed' — reaper skips it (AC-4 idempotent guard)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    _ = await _make_wave_run(
        db, project_id, user_id, status="crashed", updated_at=_stale_ts()
    )

    reaped = await _reap_crashed_waves(db)

    assert reaped == 0


async def test_no_reap_fresh_heartbeat(db):
    """Child terminal past grace, but recent wave_event → NOT reaped (AC-1)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    # Wave's updated_at is stale, but we'll insert a fresh event
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())

    # Fresh heartbeat event — resets the clock
    await _make_wave_event(db, wave_run_id, ts=_fresh_ts())

    # Child terminal and past grace — normally triggers condition (b)
    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="success",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    reaped = await _reap_crashed_waves(db)

    # Heartbeat is fresh (only 5s ago) so no reap
    assert reaped == 0


async def test_reap_compound_condition_met(db):
    """Stale + terminal child past grace → reaped (AC-3)."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="success",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    reaped = await _reap_crashed_waves(db)

    assert reaped == 1


# ---------------------------------------------------------------------------
# AC-4: Reap action
# ---------------------------------------------------------------------------


async def test_reap_sets_status_crashed(db):
    """Reaped wave: status='crashed', halt_reason set, ended_at set."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="failed",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    await _reap_crashed_waves(db)

    row = await db.fetchrow(
        "SELECT status, halt_reason, ended_at FROM autonomous_wave_runs WHERE id = $1",
        wave_run_id,
    )
    assert row["status"] == "crashed"
    assert row["halt_reason"] == "stale_heartbeat+terminal_child_run"
    assert row["ended_at"] is not None


async def test_reap_halts_pending_ready_dispatched(db):
    """Pending, ready, and dispatched items are set to 'halted' after reap."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    # Create items with each status
    pending_item = await _make_item(db, user_id, project_id)
    ready_item = await _make_item(db, user_id, project_id)
    dispatched_item = await _make_item(db, user_id, project_id)

    await _make_wave_plan_item(db, wave_run_id, pending_item, status="pending")
    await _make_wave_plan_item(db, wave_run_id, ready_item, status="ready")

    # Dispatched item with terminal child run (triggers reap)
    run_id = await _make_claude_run(
        db,
        dispatched_item,
        project_id,
        user_id,
        status="success",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, dispatched_item, status="dispatched", claude_run_id=run_id
    )

    await _reap_crashed_waves(db)

    rows = await db.fetch(
        "SELECT item_id, status FROM wave_plan_items WHERE wave_run_id = $1",
        wave_run_id,
    )
    statuses = {r["item_id"]: r["status"] for r in rows}
    assert statuses[pending_item] == "halted"
    assert statuses[ready_item] == "halted"
    assert statuses[dispatched_item] == "halted"


async def test_reap_preserves_completed_skipped(db):
    """Completed and skipped items are NOT changed by the reaper."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    completed_item = await _make_item(db, user_id, project_id)
    skipped_item = await _make_item(db, user_id, project_id)
    dispatched_item = await _make_item(db, user_id, project_id)

    await _make_wave_plan_item(db, wave_run_id, completed_item, status="completed")
    await _make_wave_plan_item(db, wave_run_id, skipped_item, status="skipped")

    run_id = await _make_claude_run(
        db,
        dispatched_item,
        project_id,
        user_id,
        status="success",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, dispatched_item, status="dispatched", claude_run_id=run_id
    )

    await _reap_crashed_waves(db)

    rows = await db.fetch(
        "SELECT item_id, status FROM wave_plan_items WHERE wave_run_id = $1",
        wave_run_id,
    )
    statuses = {r["item_id"]: r["status"] for r in rows}
    assert statuses[completed_item] == "completed"
    assert statuses[skipped_item] == "skipped"


async def test_reap_releases_item_locks(db):
    """items.locked_by_wave_id is cleared to NULL after reap."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="failed",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    # Lock the item for this wave
    await db.execute(
        "UPDATE items SET locked_by_wave_id = $1 WHERE id = $2",
        wave_run_id,
        item_id,
    )

    # Confirm lock is set
    before = await db.fetchrow(
        "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
    )
    assert before["locked_by_wave_id"] == wave_run_id

    await _reap_crashed_waves(db)

    after = await db.fetchrow(
        "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
    )
    assert after["locked_by_wave_id"] is None


async def test_reap_writes_wave_events_row(db):
    """After reap, wave_events has a row with kind='wave_crashed', actor='reaper'."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts(), seq=1)

    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="timeout",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    await _reap_crashed_waves(db)

    crash_events = await db.fetch(
        "SELECT kind, actor, payload FROM wave_events"
        " WHERE wave_run_id = $1 AND kind = 'wave_crashed'",
        wave_run_id,
    )
    assert len(crash_events) == 1
    assert crash_events[0]["actor"] == "reaper"
    payload = json.loads(crash_events[0]["payload"])
    assert payload["triggered_by_item_id"] == item_id
    assert payload["child_run_id"] == run_id
    assert payload["child_run_status"] == "timeout"
    assert "stale_seconds" in payload


async def test_reap_idempotent(db):
    """Second reaper scan on already-crashed wave → no error, no double-write."""
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())
    await _make_wave_event(db, wave_run_id, ts=_stale_ts())

    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="cancelled",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    # First scan — reaped
    reaped1 = await _reap_crashed_waves(db)
    assert reaped1 == 1

    # Second scan — wave is now 'crashed', not 'running', so skipped
    reaped2 = await _reap_crashed_waves(db)
    assert reaped2 == 0

    # Only one wave_crashed event should exist
    crash_events = await db.fetch(
        "SELECT id FROM wave_events WHERE wave_run_id = $1 AND kind = 'wave_crashed'",
        wave_run_id,
    )
    assert len(crash_events) == 1


# ---------------------------------------------------------------------------
# AC-5: ping_wave
# ---------------------------------------------------------------------------


async def test_ping_wave_writes_heartbeat_event(db):
    """ping_wave inserts a wave_events row with kind='heartbeat'."""
    from agent_gtd.services.wave_service import ping_wave

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id)

    result = await ping_wave(db, user_id, wave_run_id)

    assert result["wave_run_id"] == wave_run_id
    assert result["phase"] == ""
    assert result["waiting_on"] == ""
    assert "ts" in result

    events = await db.fetch(
        "SELECT kind, actor, payload FROM wave_events WHERE wave_run_id = $1",
        wave_run_id,
    )
    assert len(events) == 1
    assert events[0]["kind"] == "heartbeat"
    assert events[0]["actor"] == "manager"


async def test_ping_wave_stores_phase_and_waiting_on(db):
    """ping_wave(phase='merging', waiting_on='item-123') stores both in payload."""
    from agent_gtd.services.wave_service import ping_wave

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id)

    result = await ping_wave(
        db, user_id, wave_run_id, phase="merging", waiting_on="item-123"
    )

    assert result["phase"] == "merging"
    assert result["waiting_on"] == "item-123"

    event = await db.fetchrow(
        "SELECT payload FROM wave_events WHERE wave_run_id = $1 AND kind = 'heartbeat'",
        wave_run_id,
    )
    assert event is not None
    payload = json.loads(event["payload"])
    assert payload["phase"] == "merging"
    assert payload["waiting_on"] == "item-123"


async def test_ping_wave_invalid_phase_rejected(db):
    """ping_wave(..., phase='bogus') raises ValidationError."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.wave_service import ping_wave

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id)

    with pytest.raises(ValidationError):
        await ping_wave(db, user_id, wave_run_id, phase="bogus")


async def test_ping_wave_resets_reaper_clock(db):
    """After ping_wave, a stale-but-otherwise-reapable wave is NOT reaped."""
    from agent_gtd.services.wave_service import ping_wave

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    # Wave's updated_at is stale
    wave_run_id = await _make_wave_run(db, project_id, user_id, updated_at=_stale_ts())

    # Child terminal past grace — would normally trigger reap
    run_id = await _make_claude_run(
        db,
        item_id,
        project_id,
        user_id,
        status="success",
        finished_at=_past_grace_ts(),
    )
    await _make_wave_plan_item(
        db, wave_run_id, item_id, status="dispatched", claude_run_id=run_id
    )

    # Ping the wave — inserts a fresh heartbeat event
    await ping_wave(db, user_id, wave_run_id)

    # Reaper should not reap — heartbeat is fresh
    reaped = await _reap_crashed_waves(db)
    assert reaped == 0


async def test_ping_wave_rejected_non_running_wave(db):
    """ping_wave on a halted wave raises ValidationError."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.wave_service import ping_wave

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, project_id, user_id, status="halted")

    with pytest.raises(ValidationError):
        await ping_wave(db, user_id, wave_run_id)
