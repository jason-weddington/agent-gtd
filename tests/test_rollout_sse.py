"""Tests for SSE rollout_event fan-out via the event bus.

Covers AC-7: fan-out unit tests, integration fan-out to project members,
event persistence, and SSE replay.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from agent_gtd.database import get_db
from agent_gtd.event_bus import get_event_bus

# ---------------------------------------------------------------------------
# DB helpers (shared across tests)
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _make_user(db: Any) -> str:
    """Insert a minimal user row and return its ID."""
    user_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        f"user-{user_id[:8]}@test.com",
        "hashed",
        now,
    )
    return user_id


async def _make_project(db: Any, user_id: str) -> str:
    """Insert a project row and return its ID."""
    project_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        f"project-{project_id[:8]}",
        now,
        now,
    )
    return project_id


async def _add_project_member(db: Any, project_id: str, user_id: str) -> None:
    """Insert a project_members row."""
    now = _now()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_id,
        now,
    )


async def _make_item(db: Any, user_id: str, project_id: str) -> str:
    """Insert a GTD item row and return its ID."""
    item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        "Test Task",
        "next_action",
        now,
        now,
    )
    return item_id


async def _make_wave_run(
    db: Any, user_id: str, project_id: str, status: str = "running"
) -> str:
    """Insert a wave run row and return its ID."""
    wave_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, started_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        wave_id,
        project_id,
        user_id,
        status,
        now,
        now,
        now,
    )
    return wave_id


async def _make_wave_plan(
    db: Any,
    rollout_id: str,
    nodes: list[str],
    edges: list[dict[str, str]],
    version: int = 1,
) -> str:
    """Insert a rollout_plans row and return its ID."""
    plan_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        version,
        json.dumps(nodes),
        json.dumps(edges),
        "test-model",
        now,
    )
    return plan_id


async def _make_wave_item(
    db: Any, rollout_id: str, item_id: str, status: str = "pending"
) -> None:
    """Insert a rollout_items row."""
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status) VALUES ($1, $2, $3)",
        rollout_id,
        item_id,
        status,
    )


# ---------------------------------------------------------------------------
# Unit tests — mock the event bus to verify publish is called correctly
# ---------------------------------------------------------------------------


async def test_complete_item_in_rollout_publishes_sse(_setup_db):
    """After complete_item_in_rollout(), item_outcome SSE is published.

    With a single-item rollout, graph_complete=True, so wave_completed is also
    emitted (2 SSE publishes total).  The first call is item_outcome.
    """
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [])
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        await complete_item_in_rollout(db, user_id, rollout_id, item_id, "completed")
        await asyncio.sleep(0)  # let the create_task coroutines execute

    # Single item → graph_complete=True → item_outcome + wave_completed
    assert mock_bus.publish.call_count == 2
    all_calls = mock_bus.publish.call_args_list
    kinds = [c.kwargs["payload"]["kind"] for c in all_calls]
    assert "item_outcome" in kinds
    assert "wave_completed" in kinds

    # Both calls must be correctly typed rollout_event publishes
    for call in all_calls:
        assert call.kwargs["event_type"] == "rollout_event"
        assert call.kwargs["entity_type"] == "rollout"
        assert call.kwargs["project_id"] == project_id
        assert call.kwargs["entity_id"] == rollout_id


async def test_halt_rollout_publishes_sse(_setup_db):
    """After halt_rollout(), publish is called with kind='wave_halted' in payload."""
    from agent_gtd.services.rollout_service import halt_rollout

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        await halt_rollout(db, user_id, rollout_id, reason="test_halt")
        await asyncio.sleep(0)

    # halt_rollout now emits 2 SSE events: comment_posted + wave_halted
    assert mock_bus.publish.call_count == 2
    # The last call should be wave_halted
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "rollout_event"
    assert call_kwargs["entity_type"] == "rollout"
    assert call_kwargs["project_id"] == project_id
    payload = call_kwargs["payload"]
    assert payload["kind"] == "wave_halted"


async def test_wave_completed_event_emitted_on_graph_complete(_setup_db):
    """When the last item is completed, wave_completed is emitted (AC-5)."""
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [])
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_id, "completed"
        )
        await asyncio.sleep(0)

    assert result["graph_complete"] is True

    # Two SSE publishes: item_outcome + wave_completed
    assert mock_bus.publish.call_count == 2
    all_calls = mock_bus.publish.call_args_list
    wave_completed_calls = [
        c for c in all_calls if c.kwargs["payload"]["kind"] == "wave_completed"
    ]
    assert len(wave_completed_calls) == 1

    wc_payload = wave_completed_calls[0].kwargs["payload"]["payload"]
    assert wc_payload["total_items"] == 1  # one item in this rollout

    # Verify the event was persisted in rollout_events
    rows = await db.fetch(
        "SELECT kind FROM rollout_events WHERE rollout_id = $1 ORDER BY seq",
        rollout_id,
    )
    kinds = [r["kind"] for r in rows]
    assert "wave_completed" in kinds


async def test_wave_completed_not_emitted_for_partial_completion(_setup_db):
    """wave_completed is NOT emitted when there are still pending items (AC-5)."""
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id)
    item_b = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_a, item_b], [])
    await _make_wave_item(db, rollout_id, item_a, status="dispatched")
    await _make_wave_item(db, rollout_id, item_b, status="pending")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        result = await complete_item_in_rollout(
            db, user_id, rollout_id, item_a, "completed"
        )
        await asyncio.sleep(0)

    assert result["graph_complete"] is False

    # Only item_outcome SSE — no wave_completed
    assert mock_bus.publish.call_count == 1
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["payload"]["kind"] == "item_outcome"

    rows = await db.fetch(
        "SELECT kind FROM rollout_events WHERE rollout_id = $1 ORDER BY seq",
        rollout_id,
    )
    kinds = [r["kind"] for r in rows]
    assert "wave_completed" not in kinds


async def test_update_rollout_state_publishes_sse(_setup_db):
    """update_rollout_state() publishes manager_state_update via SSE (AC-6)."""
    from agent_gtd.services.rollout_service import update_rollout_state

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        await update_rollout_state(
            db, user_id, rollout_id, phase="dispatching", current_item_id=None
        )
        await asyncio.sleep(0)

    mock_bus.publish.assert_called_once()
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "rollout_event"
    assert call_kwargs["entity_type"] == "rollout"
    assert call_kwargs["project_id"] == project_id
    assert call_kwargs["entity_id"] == rollout_id
    assert call_kwargs["payload"]["kind"] == "manager_state_update"
    assert call_kwargs["payload"]["payload"]["phase"] == "dispatching"


async def test_replan_rollout_publishes_sse(_setup_db):
    """After replan_rollout(), bus.publish is called once with kind='wave_replanned'."""
    from agent_gtd.services.rollout_service import replan_rollout

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [], version=1)
    await _make_wave_item(db, rollout_id, item_id, status="pending")

    mock_planner_result = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "test-model",
    }
    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with (
        patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus),
        patch(
            "agent_gtd.services.rollout_service._call_planner",
            return_value=mock_planner_result,
        ),
    ):
        await replan_rollout(db, user_id, rollout_id)
        await asyncio.sleep(0)

    mock_bus.publish.assert_called_once()
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "rollout_event"
    payload = call_kwargs["payload"]
    assert payload["kind"] == "wave_replanned"


# ---------------------------------------------------------------------------
# Integration test — real event bus, verify fan-out to project members
# ---------------------------------------------------------------------------


async def test_rollout_event_fan_out_to_members(_setup_db):
    """rollout_event is delivered to both owner and project member queues."""
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()
    bus = get_event_bus()

    owner_id = await _make_user(db)
    member_id = await _make_user(db)
    project_id = await _make_project(db, owner_id)
    await _add_project_member(db, project_id, member_id)

    item_id = await _make_item(db, owner_id, project_id)
    rollout_id = await _make_wave_run(db, owner_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [])
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")

    owner_queue = bus.subscribe(owner_id)
    member_queue = bus.subscribe(member_id)

    try:
        await complete_item_in_rollout(db, owner_id, rollout_id, item_id, "completed")
        # Give the event loop enough time to run the fire-and-forget publish task
        # (bus.publish does multiple DB awaits, so a single sleep(0) is not enough)
        await asyncio.sleep(0.05)

        # Both queues should receive the rollout_event.
        # complete_item_in_rollout now also
        # cascades the item status to 'done' which emits an item_updated event
        # first — drain the queue and look for the rollout_event specifically.
        def _drain_for_rollout_event(q):
            events = []
            while not q.empty():
                events.append(q.get_nowait())
            rollout_events = [e for e in events if e["event_type"] == "rollout_event"]
            assert rollout_events, (
                f"queue should contain a rollout_event, got: {events}"
            )
            return rollout_events[0]

        owner_event = _drain_for_rollout_event(owner_queue)
        assert owner_event["entity_type"] == "rollout"
        assert owner_event["project_id"] == project_id

        member_event = _drain_for_rollout_event(member_queue)
        assert member_event["entity_type"] == "rollout"
        assert member_event["project_id"] == project_id
    finally:
        bus.unsubscribe(owner_id, owner_queue)
        bus.unsubscribe(member_id, member_queue)


# ---------------------------------------------------------------------------
# Persistence test — rollout_event rows land in the events table
# ---------------------------------------------------------------------------


async def test_rollout_event_persisted_in_events_table(_setup_db):
    """After complete_item_in_rollout() on the last item, two rollout_event rows
    exist in the events table: item_outcome and wave_completed (AC-5)."""
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [])
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")

    await complete_item_in_rollout(db, user_id, rollout_id, item_id, "completed")
    await asyncio.sleep(0)  # let the task execute and persist

    rows = await db.fetch("SELECT * FROM events WHERE event_type = 'rollout_event'")
    # Single-item rollout → graph_complete=True → item_outcome + wave_completed
    assert len(rows) == 2
    kinds = {json.loads(r["payload"])["kind"] for r in rows}
    assert "item_outcome" in kinds
    assert "wave_completed" in kinds
    # All rows belong to the correct rollout/project
    for row in rows:
        assert row["entity_type"] == "rollout"
        assert row["entity_id"] == rollout_id
        assert row["project_id"] == project_id


# ---------------------------------------------------------------------------
# Replay test — rollout_event rows are returned by replay_since
# ---------------------------------------------------------------------------


async def test_rollout_event_replay(_setup_db):
    """SSE replay since a prior event ID returns the rollout_event row."""
    from agent_gtd.services.rollout_service import complete_item_in_rollout

    db = await get_db()
    bus = get_event_bus()

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, rollout_id, [item_id], [])
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")

    # Publish a baseline event to anchor the since_id
    since_id = await bus.publish(
        db,
        user_id=user_id,
        event_type="baseline",
        entity_type="item",
        entity_id="baseline-item",
        payload={},
    )

    await asyncio.sleep(0.01)  # ensure created_at ordering

    await complete_item_in_rollout(db, user_id, rollout_id, item_id, "completed")
    await asyncio.sleep(0.01)  # let task execute and persist

    # replay_since with the project_id so rollout_event (published by user_id)
    # is included
    replayed = await bus.replay_since(db, user_id, since_id, project_ids=[project_id])
    replayed_types = [e["event_type"] for e in replayed]
    assert "rollout_event" in replayed_types, (
        "wave_event should appear in SSE replay after complete_item_in_rollout"
    )
