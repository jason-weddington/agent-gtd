"""Tests for GET /api/rollouts/{id}/activity endpoint.

Covers:
- Basic activity fetch (no heartbeat events, seq DESC order)
- before_seq cursor pagination
- item_title enrichment from items table
- run_id enrichment from rollout_items
- Auth: 404 for unknown wave, 404 for wrong user
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _make_user(db: Any, email: str = "activity-test@example.com") -> str:
    from agent_gtd.auth import hash_password

    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        email,
        hash_password("pass"),
        _now(),
    )
    return user_id


async def _make_project(db: Any, user_id: str) -> str:
    project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Activity Test Project",
        _now(),
        _now(),
    )
    return project_id


async def _make_item(
    db: Any, user_id: str, project_id: str, title: str = "Test Item"
) -> str:
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        title,
        "next_action",
        _now(),
        _now(),
    )
    return item_id


async def _make_wave_run(
    db: Any, user_id: str, project_id: str, status: str = "running"
) -> str:
    wave_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, started_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        wave_id,
        project_id,
        user_id,
        status,
        _now(),
        _now(),
        _now(),
    )
    return wave_id


async def _make_wave_event(
    db: Any,
    rollout_id: str,
    kind: str,
    seq: int,
    actor: str = "manager",
    payload: dict[str, Any] | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO rollout_events"
        " (id, rollout_id, seq, ts, kind, actor, decision_rule, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        event_id,
        rollout_id,
        seq,
        _now(),
        kind,
        actor,
        "",
        json.dumps(payload or {}),
    )
    return event_id


async def _make_claude_run(
    db: Any,
    user_id: str,
    item_id: str,
    project_id: str,
    rollout_id: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  max_turns, mode, rollout_id, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        run_id,
        item_id,
        project_id,
        user_id,
        "completed",
        "feat/test",
        100,
        "build",
        rollout_id,
        _now(),
        _now(),
    )
    return run_id


async def _make_wave_plan_item(
    db: Any,
    rollout_id: str,
    item_id: str,
    status: str = "completed",
    claude_run_id: str | None = None,
) -> None:
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status, claude_run_id)"
        " VALUES ($1, $2, $3, $4)",
        rollout_id,
        item_id,
        status,
        claude_run_id,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def activity_setup(client: AsyncClient):
    """Set up a wave with events for activity endpoint testing."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("activity@example.com", "pass123")
    token = create_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = await _make_project(db, user.id)
    item_id = await _make_item(db, user.id, project_id, "Build auth module")
    wave_id = await _make_wave_run(db, user.id, project_id)

    run_id = await _make_claude_run(
        db, user.id, item_id, project_id, rollout_id=wave_id
    )
    await _make_wave_plan_item(
        db, wave_id, item_id, status="completed", claude_run_id=run_id
    )

    # Insert events: wave_planned (seq=1), item_dispatched (seq=2),
    # heartbeat (seq=3, should be excluded), item_outcome (seq=4)
    await _make_wave_event(
        db,
        wave_id,
        "wave_planned",
        seq=1,
        payload={"item_count": 1, "planner_model": "test-model", "plan_id": "plan-1"},
    )
    await _make_wave_event(
        db,
        wave_id,
        "item_dispatched",
        seq=2,
        payload={"item_id": item_id, "run_id": run_id},
    )
    await _make_wave_event(
        db,
        wave_id,
        "heartbeat",
        seq=3,
        payload={"phase": "waiting", "waiting_on": []},
    )
    await _make_wave_event(
        db,
        wave_id,
        "item_outcome",
        seq=4,
        payload={"item_id": item_id, "outcome": "completed"},
    )

    yield {
        "wave_id": wave_id,
        "item_id": item_id,
        "run_id": run_id,
        "project_id": project_id,
        "user_id": user.id,
        "headers": headers,
        "db": db,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_basic(client: AsyncClient, activity_setup: dict[str, Any]):
    """GET /activity returns events ordered seq DESC, heartbeat excluded."""
    wave_id = activity_setup["wave_id"]
    headers = activity_setup["headers"]

    res = await client.get(
        f"/api/rollouts/{wave_id}/activity?limit=200",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert "has_more" in data

    events = data["events"]
    # Heartbeat should be excluded → 3 events
    assert len(events) == 3

    # Should be ordered seq DESC
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs, reverse=True)

    # No heartbeat events
    kinds = [e["event_type"] for e in events]
    assert "heartbeat" not in kinds


@pytest.mark.asyncio
async def test_activity_item_enrichment(
    client: AsyncClient, activity_setup: dict[str, Any]
):
    """Events with item_id in payload get item_title and run_id populated."""
    wave_id = activity_setup["wave_id"]
    item_id = activity_setup["item_id"]
    run_id = activity_setup["run_id"]
    headers = activity_setup["headers"]

    res = await client.get(
        f"/api/rollouts/{wave_id}/activity",
        headers=headers,
    )
    assert res.status_code == 200
    events = res.json()["events"]

    # Find item_dispatched event
    dispatched = next(e for e in events if e["event_type"] == "item_dispatched")
    assert dispatched["item_id"] == item_id
    assert dispatched["item_title"] == "Build auth module"
    assert dispatched["run_id"] == run_id

    # Find item_outcome event
    outcome = next(e for e in events if e["event_type"] == "item_outcome")
    assert outcome["item_id"] == item_id
    assert outcome["item_title"] == "Build auth module"


@pytest.mark.asyncio
async def test_activity_before_seq_cursor(
    client: AsyncClient, activity_setup: dict[str, Any]
):
    """before_seq parameter returns only events with seq < N."""
    wave_id = activity_setup["wave_id"]
    headers = activity_setup["headers"]

    # seq 4 is item_outcome, seq 2 is item_dispatched, seq 1 is wave_planned
    # before_seq=4 should return seq 1 and 2 (not 4, heartbeat seq 3 excluded)
    res = await client.get(
        f"/api/rollouts/{wave_id}/activity?before_seq=4",
        headers=headers,
    )
    assert res.status_code == 200
    events = res.json()["events"]
    seqs = [e["seq"] for e in events]
    assert all(s < 4 for s in seqs)
    assert 4 not in seqs


@pytest.mark.asyncio
async def test_activity_has_more_false(
    client: AsyncClient, activity_setup: dict[str, Any]
):
    """has_more is False when fewer than limit events exist."""
    wave_id = activity_setup["wave_id"]
    headers = activity_setup["headers"]

    res = await client.get(
        f"/api/rollouts/{wave_id}/activity?limit=200",
        headers=headers,
    )
    assert res.status_code == 200
    # Only 3 non-heartbeat events, well under limit of 200
    assert res.json()["has_more"] is False


@pytest.mark.asyncio
async def test_activity_has_more_true(
    client: AsyncClient, activity_setup: dict[str, Any]
):
    """has_more is True when result count equals limit (more may exist)."""
    wave_id = activity_setup["wave_id"]
    headers = activity_setup["headers"]
    db = activity_setup["db"]

    # Insert 2 more events so total non-heartbeat = 5, limit = 3
    await _make_wave_event(db, wave_id, "wave_started", seq=5)
    await _make_wave_event(
        db, wave_id, "comment_posted", seq=6, payload={"comment_type": "halt_reason"}
    )

    res = await client.get(
        f"/api/rollouts/{wave_id}/activity?limit=3",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["events"]) == 3
    assert data["has_more"] is True


@pytest.mark.asyncio
async def test_activity_wrong_user(client: AsyncClient, activity_setup: dict[str, Any]):
    """Returns 404 when caller does not own the wave."""
    from agent_gtd.auth import create_token, register_user

    other_user = await register_user("other-activity@example.com", "pass123")
    other_token = create_token(other_user.id)
    other_headers = {"Authorization": f"Bearer {other_token}"}

    wave_id = activity_setup["wave_id"]
    res = await client.get(
        f"/api/rollouts/{wave_id}/activity",
        headers=other_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_activity_unknown_wave(
    client: AsyncClient, activity_setup: dict[str, Any]
):
    """Returns 404 for a non-existent wave run ID."""
    headers = activity_setup["headers"]
    res = await client.get(
        f"/api/rollouts/{uuid.uuid4()}/activity",
        headers=headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_activity_empty(client: AsyncClient, activity_setup: dict[str, Any]):
    """Returns empty events list for a wave with no non-heartbeat events."""
    from agent_gtd.database import get_db

    db = await get_db()
    user_id = activity_setup["user_id"]
    project_id = activity_setup["project_id"]
    headers = activity_setup["headers"]

    # Create a fresh wave with only heartbeat events
    wave_id = await _make_wave_run(db, user_id, project_id)
    await _make_wave_event(db, wave_id, "heartbeat", seq=1)

    res = await client.get(
        f"/api/rollouts/{wave_id}/activity",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["events"] == []
    assert data["has_more"] is False
