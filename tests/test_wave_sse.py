"""Tests for SSE wave_event fan-out via the event bus.

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
        "INSERT INTO autonomous_wave_runs"
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
    wave_run_id: str,
    nodes: list[str],
    edges: list[dict[str, str]],
    version: int = 1,
) -> str:
    """Insert a wave_plans row and return its ID."""
    plan_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO wave_plans"
        " (id, wave_run_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        wave_run_id,
        version,
        json.dumps(nodes),
        json.dumps(edges),
        "test-model",
        now,
    )
    return plan_id


async def _make_wave_item(
    db: Any, wave_run_id: str, item_id: str, status: str = "pending"
) -> None:
    """Insert a wave_plan_items row."""
    await db.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id, status)"
        " VALUES ($1, $2, $3)",
        wave_run_id,
        item_id,
        status,
    )


# ---------------------------------------------------------------------------
# Unit tests — mock the event bus to verify publish is called correctly
# ---------------------------------------------------------------------------


async def test_complete_in_wave_publishes_sse(_setup_db):
    """After complete_in_wave(), publish is called with event_type='wave_event'."""
    from agent_gtd.services.wave_service import complete_in_wave

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, wave_run_id, [item_id], [])
    await _make_wave_item(db, wave_run_id, item_id, status="dispatched")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        await complete_in_wave(db, user_id, wave_run_id, item_id, "completed")
        await asyncio.sleep(0)  # let the create_task coroutine execute

    mock_bus.publish.assert_called_once()
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "wave_event"
    assert call_kwargs["entity_type"] == "wave_run"
    assert call_kwargs["project_id"] == project_id
    assert call_kwargs["entity_id"] == wave_run_id


async def test_halt_wave_publishes_sse(_setup_db):
    """After halt_wave(), publish is called with kind='wave_halted' in payload."""
    from agent_gtd.services.wave_service import halt_wave

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock(return_value="event-id")

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        await halt_wave(db, user_id, wave_run_id, reason="test_halt")
        await asyncio.sleep(0)

    # halt_wave now emits 2 SSE events: comment_posted + wave_halted
    assert mock_bus.publish.call_count == 2
    # The last call should be wave_halted
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "wave_event"
    assert call_kwargs["entity_type"] == "wave_run"
    assert call_kwargs["project_id"] == project_id
    payload = call_kwargs["payload"]
    assert payload["kind"] == "wave_halted"


async def test_replan_wave_publishes_sse(_setup_db):
    """After replan_wave(), bus.publish is called once with kind='wave_replanned'."""
    from agent_gtd.services.wave_service import replan_wave

    db = await get_db()
    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, wave_run_id, [item_id], [], version=1)
    await _make_wave_item(db, wave_run_id, item_id, status="pending")

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
            "agent_gtd.services.wave_service._call_planner",
            return_value=mock_planner_result,
        ),
    ):
        await replan_wave(db, user_id, wave_run_id)
        await asyncio.sleep(0)

    mock_bus.publish.assert_called_once()
    call_kwargs = mock_bus.publish.call_args.kwargs
    assert call_kwargs["event_type"] == "wave_event"
    payload = call_kwargs["payload"]
    assert payload["kind"] == "wave_replanned"


# ---------------------------------------------------------------------------
# Integration test — real event bus, verify fan-out to project members
# ---------------------------------------------------------------------------


async def test_wave_event_fan_out_to_members(_setup_db):
    """wave_event is delivered to both owner and project member queues."""
    from agent_gtd.services.wave_service import complete_in_wave

    db = await get_db()
    bus = get_event_bus()

    owner_id = await _make_user(db)
    member_id = await _make_user(db)
    project_id = await _make_project(db, owner_id)
    await _add_project_member(db, project_id, member_id)

    item_id = await _make_item(db, owner_id, project_id)
    wave_run_id = await _make_wave_run(db, owner_id, project_id, status="running")
    await _make_wave_plan(db, wave_run_id, [item_id], [])
    await _make_wave_item(db, wave_run_id, item_id, status="dispatched")

    owner_queue = bus.subscribe(owner_id)
    member_queue = bus.subscribe(member_id)

    try:
        await complete_in_wave(db, owner_id, wave_run_id, item_id, "completed")
        # Give the event loop enough time to run the fire-and-forget publish task
        # (bus.publish does multiple DB awaits, so a single sleep(0) is not enough)
        await asyncio.sleep(0.05)

        # Both queues should receive the wave_event
        assert not owner_queue.empty(), "owner queue should have received wave_event"
        owner_event = owner_queue.get_nowait()
        assert owner_event["event_type"] == "wave_event"
        assert owner_event["entity_type"] == "wave_run"
        assert owner_event["project_id"] == project_id

        assert not member_queue.empty(), "member queue should have received wave_event"
        member_event = member_queue.get_nowait()
        assert member_event["event_type"] == "wave_event"
        assert member_event["entity_type"] == "wave_run"
        assert member_event["project_id"] == project_id
    finally:
        bus.unsubscribe(owner_id, owner_queue)
        bus.unsubscribe(member_id, member_queue)


# ---------------------------------------------------------------------------
# Persistence test — wave_event rows land in the events table
# ---------------------------------------------------------------------------


async def test_wave_event_persisted_in_events_table(_setup_db):
    """After complete_in_wave(), one wave_event row exists in the events table."""
    from agent_gtd.services.wave_service import complete_in_wave

    db = await get_db()

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, wave_run_id, [item_id], [])
    await _make_wave_item(db, wave_run_id, item_id, status="dispatched")

    await complete_in_wave(db, user_id, wave_run_id, item_id, "completed")
    await asyncio.sleep(0)  # let the task execute and persist

    rows = await db.fetch("SELECT * FROM events WHERE event_type = 'wave_event'")
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "wave_run"
    assert rows[0]["entity_id"] == wave_run_id
    assert rows[0]["project_id"] == project_id
    payload = json.loads(rows[0]["payload"])
    assert payload["kind"] == "item_outcome"


# ---------------------------------------------------------------------------
# Replay test — wave_event rows are returned by replay_since
# ---------------------------------------------------------------------------


async def test_wave_event_replay(_setup_db):
    """SSE replay since a prior event ID returns the wave_event row."""
    from agent_gtd.services.wave_service import complete_in_wave

    db = await get_db()
    bus = get_event_bus()

    user_id = await _make_user(db)
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id)
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_plan(db, wave_run_id, [item_id], [])
    await _make_wave_item(db, wave_run_id, item_id, status="dispatched")

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

    await complete_in_wave(db, user_id, wave_run_id, item_id, "completed")
    await asyncio.sleep(0.01)  # let task execute and persist

    # replay_since with the project_id so wave_event (published by user_id) is included
    replayed = await bus.replay_since(db, user_id, since_id, project_ids=[project_id])
    replayed_types = [e["event_type"] for e in replayed]
    assert "wave_event" in replayed_types, (
        "wave_event should appear in SSE replay after complete_in_wave"
    )
