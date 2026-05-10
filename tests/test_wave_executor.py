"""Tests for the wave executor cycle MCP tools.

Covers: advance_wave, complete_in_wave, halt_wave, replan_wave — both the
service layer and the FastAPI REST routes.

The in-memory SQLite fixture from conftest.py is used for all tests.  The
dispatch-worker planner HTTP call inside replan_wave is mocked so no real
HTTP request is made.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _make_user(db: Any) -> str:
    """Insert a bare-minimum user row and return its ID."""
    from agent_gtd.auth import hash_password

    user_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        f"user-{user_id[:8]}@test.com",
        hash_password("pass"),
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
        "Test Wave Project",
        now,
        now,
    )
    return project_id


async def _make_item(
    db: Any, user_id: str, project_id: str, title: str = "Task"
) -> str:
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
        title,
        "next_action",
        now,
        now,
    )
    return item_id


async def _make_wave_run(
    db: Any,
    user_id: str,
    project_id: str,
    status: str = "running",
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
    db: Any,
    wave_run_id: str,
    item_id: str,
    status: str = "pending",
) -> None:
    """Insert a wave_plan_items row."""
    await db.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id, status)"
        " VALUES ($1, $2, $3)",
        wave_run_id,
        item_id,
        status,
    )


async def _get_wave_event(
    db: Any, wave_run_id: str, kind: str
) -> dict[str, Any] | None:
    """Fetch the first matching wave event (by kind) for a wave run."""
    row = await db.fetchrow(
        "SELECT * FROM wave_events WHERE wave_run_id = $1 AND kind = $2",
        wave_run_id,
        kind,
    )
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


async def _get_wave_plan_item(
    db: Any, wave_run_id: str, item_id: str
) -> dict[str, Any]:
    """Fetch a wave_plan_items row as a dict."""
    row = await db.fetchrow(
        "SELECT * FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_id,
    )
    assert row is not None
    return dict(row)


async def _get_wave_run(db: Any, wave_run_id: str) -> dict[str, Any]:
    """Fetch a wave run row as a dict."""
    row = await db.fetchrow(
        "SELECT * FROM autonomous_wave_runs WHERE id = $1", wave_run_id
    )
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# Shared fixture — a fresh wave with two items (A → B linear DAG)
# ---------------------------------------------------------------------------


@pytest.fixture
async def linear_wave(client: AsyncClient, auth_headers: dict[str, str]):
    """Set up a running wave with two items: A → B (linear DAG).

    Yields a dict with wave_run_id, item_a_id, item_b_id, user_id,
    project_id, and a db handle.
    """
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()

    user = await register_user("wave-test@example.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)
    item_a_id = await _make_item(db, user_id, project_id, "Task A")
    item_b_id = await _make_item(db, user_id, project_id, "Task B")
    wave_run_id = await _make_wave_run(db, user_id, project_id, status="running")
    # A → B: B can only start after A completes
    await _make_wave_plan(
        db,
        wave_run_id,
        nodes=[item_a_id, item_b_id],
        edges=[{"from_item_id": item_a_id, "to_item_id": item_b_id}],
    )
    await _make_wave_item(db, wave_run_id, item_a_id, status="pending")
    await _make_wave_item(db, wave_run_id, item_b_id, status="pending")

    yield {
        "wave_run_id": wave_run_id,
        "item_a_id": item_a_id,
        "item_b_id": item_b_id,
        "user_id": user_id,
        "project_id": project_id,
        "db": db,
        "headers": {"Authorization": f"Bearer {create_token(user_id)}"},
    }


# ---------------------------------------------------------------------------
# advance_wave tests
# ---------------------------------------------------------------------------


async def test_advance_wave_fresh(client: AsyncClient, linear_wave: dict):
    """Fresh wave: A (no predecessors) is next_ready; B (blocked by A) is blocked."""
    w = linear_wave
    resp = await client.get(
        f"/api/wave-runs/{w['wave_run_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_a_id"] in data["next_ready"]
    assert w["item_b_id"] in data["blocked"]
    assert data["in_progress"] == []
    assert data["graph_complete"] is False


async def test_advance_wave_after_dispatch(
    client: AsyncClient, linear_wave: dict
) -> None:
    """After A is dispatched: A in in_progress, B still blocked."""
    w = linear_wave
    db = w["db"]
    # Simulate dispatch by updating A's status directly
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )

    resp = await client.get(
        f"/api/wave-runs/{w['wave_run_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_a_id"] in data["in_progress"]
    assert w["item_b_id"] in data["blocked"]
    assert data["next_ready"] == []


async def test_advance_wave_after_complete(
    client: AsyncClient, linear_wave: dict
) -> None:
    """After A completes: B should be next_ready (unblocked via complete_in_wave)."""
    w = linear_wave
    db = w["db"]
    # Dispatch A, then complete it so B is unblocked
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    # Now advance_wave should show B as next_ready
    resp = await client.get(
        f"/api/wave-runs/{w['wave_run_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_b_id"] in data["next_ready"]
    assert data["blocked"] == []


async def test_advance_wave_graph_complete(
    client: AsyncClient, linear_wave: dict
) -> None:
    """All items terminal → graph_complete=True."""
    w = linear_wave
    db = w["db"]
    # Complete both items by updating their status directly
    await db.execute(
        "UPDATE wave_plan_items SET status = 'completed'"
        " WHERE wave_run_id = $1",
        w["wave_run_id"],
    )
    resp = await client.get(
        f"/api/wave-runs/{w['wave_run_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["graph_complete"] is True
    assert data["next_ready"] == []
    assert data["in_progress"] == []
    assert data["blocked"] == []


# ---------------------------------------------------------------------------
# complete_in_wave tests
# ---------------------------------------------------------------------------


async def test_complete_in_wave_unblocks(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Completing A transitions B from pending → ready (newly_ready)."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_b_id"] in data["newly_ready"]

    # Verify DB state
    b_row = await _get_wave_plan_item(db, w["wave_run_id"], w["item_b_id"])
    assert b_row["status"] == "ready"


async def test_complete_in_wave_closes_wave(
    client: AsyncClient, linear_wave: dict
) -> None:
    """When the last item completes the wave run status becomes 'completed'."""
    w = linear_wave
    db = w["db"]
    # Dispatch and complete A
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    # Dispatch and complete B (last item)
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_b_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_b_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    wave_run = await _get_wave_run(db, w["wave_run_id"])
    assert wave_run["status"] == "completed"
    assert wave_run["ended_at"] is not None


async def test_complete_in_wave_bad_status(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Completing an item not in 'dispatched' → 422 error."""
    w = linear_wave
    # A is still 'pending', not 'dispatched'
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_in_wave_persists_merge_actor(
    client: AsyncClient, linear_wave: dict
) -> None:
    """merge_actor is stored on the wave_plan_items row."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "merge_actor": "manager-allowlist",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["wave_plan_item"]["merge_actor"] == "manager-allowlist"

    # Verify in DB
    a_row = await _get_wave_plan_item(db, w["wave_run_id"], w["item_a_id"])
    assert a_row["merge_actor"] == "manager-allowlist"


async def test_complete_in_wave_decision_rule_in_event_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """decision_rule is stored in wave_events.payload for the item_outcome event."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "decision_rule": "patch-only",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["wave_run_id"], "item_outcome")
    assert event is not None
    assert event["payload"]["decision_rule"] == "patch-only"


# ---------------------------------------------------------------------------
# halt_wave tests
# ---------------------------------------------------------------------------


async def test_halt_wave(client: AsyncClient, linear_wave: dict) -> None:
    """halt_wave: wave → 'halted', all pending items → 'halted', event appended."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/halt",
        json={"reason": "test_reason"},
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "halted"
    assert data["halt_reason"] == "test_reason"

    # All items should be halted
    for item_id in [w["item_a_id"], w["item_b_id"]]:
        row = await _get_wave_plan_item(db, w["wave_run_id"], item_id)
        assert row["status"] == "halted"

    # Wave event should be appended
    event = await _get_wave_event(db, w["wave_run_id"], "wave_halted")
    assert event is not None


async def test_halt_wave_already_halted(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Attempting to halt an already-halted wave raises 422."""
    w = linear_wave
    # First halt
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/halt",
        json={"reason": "first_halt"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    # Second halt should fail
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/halt",
        json={"reason": "second_halt"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_halt_wave_with_item_id_in_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """item_id is included in the wave_halted event payload when supplied."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/halt",
        json={"reason": "item_failed", "item_id": w["item_a_id"]},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["wave_run_id"], "wave_halted")
    assert event is not None
    assert event["payload"]["item_id"] == w["item_a_id"]


async def test_halt_wave_emits_comment_id_in_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """The wave_halted event payload contains the comment_id of the created comment."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/halt",
        json={"reason": "manual_halt", "comment": "Stopping for review."},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["wave_run_id"], "wave_halted")
    assert event is not None
    comment_id = event["payload"].get("comment_id")
    assert comment_id is not None

    # Verify the comment actually exists in the DB
    comment_row = await db.fetchrow(
        "SELECT * FROM comments WHERE id = $1", comment_id
    )
    assert comment_row is not None
    assert "Stopping for review." in comment_row["content_markdown"]


# ---------------------------------------------------------------------------
# replan_wave tests
# ---------------------------------------------------------------------------


async def test_replan_wave_no_remaining(
    client: AsyncClient, linear_wave: dict
) -> None:
    """When all items are terminal, replan_wave raises 422 (nothing to replan)."""
    w = linear_wave
    db = w["db"]
    # Mark all items as completed
    await db.execute(
        "UPDATE wave_plan_items SET status = 'completed'"
        " WHERE wave_run_id = $1",
        w["wave_run_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/replan",
        json={},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_replan_wave_creates_new_version(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_wave creates a new wave_plans row with version = old_version + 1."""
    w = linear_wave
    db = w["db"]

    mock_plan = {
        "nodes": [w["item_b_id"]],
        "edges": [],
        "planner_model": "mock-model",
    }

    with patch(
        "agent_gtd.services.wave_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        # Complete A so B is the only remaining item
        await db.execute(
            "UPDATE wave_plan_items SET status = 'completed'"
            " WHERE wave_run_id = $1 AND item_id = $2",
            w["wave_run_id"],
            w["item_a_id"],
        )
        resp = await client.post(
            f"/api/wave-runs/{w['wave_run_id']}/replan",
            json={},
            headers=w["headers"],
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["old_version"] == 1
    assert data["new_version"] == 2
    assert data["new_plan"]["version"] == 2
    assert data["new_plan"]["planner_model"] == "mock-model"

    # Verify a wave_replanned event was emitted
    event = await _get_wave_event(db, w["wave_run_id"], "wave_replanned")
    assert event is not None
    assert event["payload"]["old_version"] == 1
    assert event["payload"]["new_version"] == 2


# ---------------------------------------------------------------------------
# Error-path / branch-coverage tests
# ---------------------------------------------------------------------------


async def test_advance_wave_not_found(
    client: AsyncClient, linear_wave: dict
) -> None:
    """advance_wave with a bad wave_run_id → 404."""
    w = linear_wave
    resp = await client.get(
        "/api/wave-runs/00000000-0000-0000-0000-000000000000/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 404


async def test_advance_wave_not_running(
    client: AsyncClient, linear_wave: dict
) -> None:
    """advance_wave on a non-running wave → 422."""
    w = linear_wave
    db = w["db"]
    # Halt the wave first
    await db.execute(
        "UPDATE autonomous_wave_runs SET status = 'halted'"
        " WHERE id = $1",
        w["wave_run_id"],
    )
    resp = await client.get(
        f"/api/wave-runs/{w['wave_run_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_in_wave_invalid_outcome(
    client: AsyncClient, linear_wave: dict
) -> None:
    """complete_in_wave with an invalid outcome → 422."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE wave_plan_items SET status = 'dispatched'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "invalid_outcome"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_in_wave_item_not_found(
    client: AsyncClient, linear_wave: dict
) -> None:
    """complete_in_wave with an item not in the wave → 404."""
    w = linear_wave
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/complete-item",
        json={
            "item_id": "00000000-0000-0000-0000-000000000000",
            "outcome": "completed",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 404


async def test_complete_in_wave_downstream_not_pending(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Downstream items already in non-pending state are skipped during unblocking."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("branch-test@example.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, "A")
    item_b = await _make_item(db, user_id, project_id, "B")
    item_c = await _make_item(db, user_id, project_id, "C")
    wave_id = await _make_wave_run(db, user_id, project_id, status="running")
    # A → B, A → C (parallel fork)
    await _make_wave_plan(
        db,
        wave_id,
        nodes=[item_a, item_b, item_c],
        edges=[
            {"from_item_id": item_a, "to_item_id": item_b},
            {"from_item_id": item_a, "to_item_id": item_c},
        ],
    )
    await _make_wave_item(db, wave_id, item_a, status="dispatched")
    # B is already dispatched, C is pending
    await _make_wave_item(db, wave_id, item_b, status="dispatched")
    await _make_wave_item(db, wave_id, item_c, status="pending")

    headers = {"Authorization": f"Bearer {create_token(user_id)}"}
    resp = await client.post(
        f"/api/wave-runs/{wave_id}/complete-item",
        json={"item_id": item_a, "outcome": "completed"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # B is dispatched so not newly_ready; C should be newly_ready
    assert item_c in data["newly_ready"]
    assert item_b not in data["newly_ready"]


async def test_replan_wave_not_running(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_wave on a non-running wave → 422."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE autonomous_wave_runs SET status = 'halted'" " WHERE id = $1",
        w["wave_run_id"],
    )
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/replan",
        json={},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_replan_wave_with_from_item(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_wave with from_item restricts replanning to A's subgraph (B only)."""
    w = linear_wave
    db = w["db"]

    mock_plan = {
        "nodes": [w["item_b_id"]],
        "edges": [],
        "planner_model": "mock",
    }

    with patch(
        "agent_gtd.services.wave_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        # Complete A so only B remains
        await db.execute(
            "UPDATE wave_plan_items SET status = 'completed'"
            " WHERE wave_run_id = $1 AND item_id = $2",
            w["wave_run_id"],
            w["item_a_id"],
        )
        resp = await client.post(
            f"/api/wave-runs/{w['wave_run_id']}/replan",
            json={"from_item": w["item_a_id"]},
            headers=w["headers"],
        )

    assert resp.status_code == 200
    data = resp.json()
    # B is downstream of A → it should be in the replanned subgraph
    assert data["new_version"] == 2


async def test_replan_wave_from_item_no_descendants(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_wave with from_item that has no remaining descendants → 422."""
    w = linear_wave
    db = w["db"]
    # Mark B as completed so from_item=A has no remaining descendants
    await db.execute(
        "UPDATE wave_plan_items SET status = 'completed'"
        " WHERE wave_run_id = $1 AND item_id = $2",
        w["wave_run_id"],
        w["item_b_id"],
    )
    # A is still pending; from_item=B (leaf) has no descendants at all
    resp = await client.post(
        f"/api/wave-runs/{w['wave_run_id']}/replan",
        json={"from_item": w["item_b_id"]},
        headers=w["headers"],
    )
    # B has no remaining descendant items → 422
    assert resp.status_code == 422


async def test_call_planner_no_config(linear_wave: dict) -> None:
    """_call_planner raises ValidationError when dispatch service is not configured."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.wave_service import _call_planner

    w = linear_wave
    db = w["db"]
    # user_id is w["user_id"] — no dispatch config has been set for this test user
    with pytest.raises(ValidationError, match="not configured"):
        await _call_planner(db, w["user_id"], w["wave_run_id"], [w["item_a_id"]])


async def test_call_planner_http_error(linear_wave: dict) -> None:
    """_call_planner raises ValidationError when the planner HTTP call fails."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.settings_service import set_user_setting
    from agent_gtd.services.wave_service import _call_planner

    w = linear_wave
    db = w["db"]
    user_id = w["user_id"]

    # Configure dispatch settings for this user
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake-planner:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Mock the httpx client to return a 500 error
    mock_resp = AsyncMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ValidationError, match="Planner returned 500"):
            await _call_planner(
                db, user_id, w["wave_run_id"], [w["item_a_id"]]
            )


async def test_replan_wave_readiness_regression(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """replan_wave reverts a 'ready' item to 'pending' when it gains a predecessor."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("replan-revert@example.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)
    item_a = await _make_item(db, user_id, project_id, "A")
    item_b = await _make_item(db, user_id, project_id, "B")
    wave_id = await _make_wave_run(db, user_id, project_id, status="running")

    # Initial plan: A → B (B is blocked by A)
    await _make_wave_plan(
        db, wave_id,
        nodes=[item_a, item_b],
        edges=[{"from_item_id": item_a, "to_item_id": item_b}],
    )
    await _make_wave_item(db, wave_id, item_a, status="pending")
    # B is 'ready' (was unblocked somehow), but new plan will re-block it
    await _make_wave_item(db, wave_id, item_b, status="ready")

    # New plan: A → B still (B has A as predecessor, A is still pending)
    # So B should be reverted back to 'pending' since A is pending
    mock_plan = {
        "nodes": [item_a, item_b],
        "edges": [{"from_item_id": item_a, "to_item_id": item_b}],
        "planner_model": "mock",
    }

    headers = {"Authorization": f"Bearer {create_token(user_id)}"}
    with patch(
        "agent_gtd.services.wave_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        resp = await client.post(
            f"/api/wave-runs/{wave_id}/replan",
            json={},
            headers=headers,
        )

    assert resp.status_code == 200
    # B should now be 'pending' since A (its predecessor) is still pending
    b_row = await _get_wave_plan_item(db, wave_id, item_b)
    assert b_row["status"] == "pending"
