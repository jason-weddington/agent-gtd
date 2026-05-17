"""Tests for the wave executor cycle MCP tools.

Covers: advance_rollout, complete_item_in_rollout, halt_rollout, replan_rollout —
both the
service layer and the FastAPI REST routes.

The in-memory SQLite fixture from conftest.py is used for all tests.  The
dispatch-worker planner HTTP call inside replan_rollout is mocked so no real
HTTP request is made.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from agent_gtd.database import encode_file_specs, encode_json_list

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
    db: Any,
    rollout_id: str,
    item_id: str,
    status: str = "pending",
) -> None:
    """Insert a rollout_items row."""
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status) VALUES ($1, $2, $3)",
        rollout_id,
        item_id,
        status,
    )


async def _get_wave_event(db: Any, rollout_id: str, kind: str) -> dict[str, Any] | None:
    """Fetch the first matching wave event (by kind) for a wave run."""
    row = await db.fetchrow(
        "SELECT * FROM rollout_events WHERE rollout_id = $1 AND kind = $2",
        rollout_id,
        kind,
    )
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


async def _get_wave_plan_item(db: Any, rollout_id: str, item_id: str) -> dict[str, Any]:
    """Fetch a rollout_items row as a dict."""
    row = await db.fetchrow(
        "SELECT * FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    assert row is not None
    return dict(row)


async def _get_rollout(db: Any, rollout_id: str) -> dict[str, Any]:
    """Fetch a wave run row as a dict."""
    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# Shared fixture — a fresh wave with two items (A → B linear DAG)
# ---------------------------------------------------------------------------


@pytest.fixture
async def linear_wave(client: AsyncClient, auth_headers: dict[str, str]):
    """Set up a running wave with two items: A → B (linear DAG).

    Yields a dict with rollout_id, item_a_id, item_b_id, user_id,
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
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    # A → B: B can only start after A completes
    await _make_wave_plan(
        db,
        rollout_id,
        nodes=[item_a_id, item_b_id],
        edges=[{"from_item_id": item_a_id, "to_item_id": item_b_id}],
    )
    await _make_wave_item(db, rollout_id, item_a_id, status="pending")
    await _make_wave_item(db, rollout_id, item_b_id, status="pending")

    yield {
        "rollout_id": rollout_id,
        "item_a_id": item_a_id,
        "item_b_id": item_b_id,
        "user_id": user_id,
        "project_id": project_id,
        "db": db,
        "headers": {"Authorization": f"Bearer {create_token(user_id)}"},
    }


# ---------------------------------------------------------------------------
# advance_rollout tests
# ---------------------------------------------------------------------------


async def test_advance_rollout_fresh(client: AsyncClient, linear_wave: dict):
    """Fresh wave: A (no predecessors) is next_ready; B (blocked by A) is blocked."""
    w = linear_wave
    resp = await client.get(
        f"/api/rollouts/{w['rollout_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_a_id"] in data["next_ready"]
    assert w["item_b_id"] in data["blocked"]
    assert data["in_progress"] == []
    assert data["graph_complete"] is False


async def test_advance_rollout_after_dispatch(
    client: AsyncClient, linear_wave: dict
) -> None:
    """After A is dispatched: A in in_progress, B still blocked."""
    w = linear_wave
    db = w["db"]
    # Simulate dispatch by updating A's status directly
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )

    resp = await client.get(
        f"/api/rollouts/{w['rollout_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_a_id"] in data["in_progress"]
    assert w["item_b_id"] in data["blocked"]
    assert data["next_ready"] == []


async def test_advance_rollout_after_complete(
    client: AsyncClient, linear_wave: dict
) -> None:
    """After A completes: B should be next_ready
    (unblocked via complete_item_in_rollout)."""
    w = linear_wave
    db = w["db"]
    # Dispatch A, then complete it so B is unblocked
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    # Now advance_rollout should show B as next_ready
    resp = await client.get(
        f"/api/rollouts/{w['rollout_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_b_id"] in data["next_ready"]
    assert data["blocked"] == []


async def test_advance_rollout_graph_complete(
    client: AsyncClient, linear_wave: dict
) -> None:
    """All items terminal → graph_complete=True."""
    w = linear_wave
    db = w["db"]
    # Complete both items by updating their status directly
    await db.execute(
        "UPDATE rollout_items SET status = 'completed' WHERE rollout_id = $1",
        w["rollout_id"],
    )
    resp = await client.get(
        f"/api/rollouts/{w['rollout_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["graph_complete"] is True
    assert data["next_ready"] == []
    assert data["in_progress"] == []
    assert data["blocked"] == []


# ---------------------------------------------------------------------------
# complete_item_in_rollout tests
# ---------------------------------------------------------------------------


async def test_complete_item_in_rollout_unblocks(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Completing A transitions B from pending → ready (newly_ready)."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert w["item_b_id"] in data["newly_ready"]

    # Verify DB state
    b_row = await _get_wave_plan_item(db, w["rollout_id"], w["item_b_id"])
    assert b_row["status"] == "ready"


async def test_complete_item_in_rollout_closes_wave(
    client: AsyncClient, linear_wave: dict
) -> None:
    """When the last item completes the wave run status becomes 'completed'."""
    w = linear_wave
    db = w["db"]
    # Dispatch and complete A
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    # Dispatch and complete B (last item)
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_b_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_b_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    rollout = await _get_rollout(db, w["rollout_id"])
    assert rollout["status"] == "completed"
    assert rollout["ended_at"] is not None


async def test_complete_item_in_rollout_bad_status(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Completing an item not in 'dispatched' → 422 error."""
    w = linear_wave
    # A is still 'pending', not 'dispatched'
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "completed"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_item_in_rollout_persists_merge_actor(
    client: AsyncClient, linear_wave: dict
) -> None:
    """merge_actor is stored on the rollout_items row."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "merge_actor": "manager-allowlist",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rollout_item"]["merge_actor"] == "manager-allowlist"

    # Verify in DB
    a_row = await _get_wave_plan_item(db, w["rollout_id"], w["item_a_id"])
    assert a_row["merge_actor"] == "manager-allowlist"


async def test_complete_item_in_rollout_decision_rule_in_event_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """decision_rule is stored in rollout_events.payload for the item_outcome event."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "decision_rule": "agent-judgment",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["rollout_id"], "item_outcome")
    assert event is not None
    assert event["payload"]["decision_rule"] == "agent-judgment"


# ---------------------------------------------------------------------------
# halt_rollout tests
# ---------------------------------------------------------------------------


async def test_halt_rollout(client: AsyncClient, linear_wave: dict) -> None:
    """halt_rollout: wave → 'halted', all pending items → 'halted', event appended."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/halt",
        json={"reason": "test_reason"},
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "halted"
    assert data["halt_reason"] == "test_reason"

    # All items should be halted
    for item_id in [w["item_a_id"], w["item_b_id"]]:
        row = await _get_wave_plan_item(db, w["rollout_id"], item_id)
        assert row["status"] == "halted"

    # Wave event should be appended
    event = await _get_wave_event(db, w["rollout_id"], "wave_halted")
    assert event is not None


async def test_halt_rollout_already_halted(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Attempting to halt an already-halted wave raises 422."""
    w = linear_wave
    # First halt
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/halt",
        json={"reason": "first_halt"},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    # Second halt should fail
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/halt",
        json={"reason": "second_halt"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_halt_rollout_with_item_id_in_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """item_id is included in the wave_halted event payload when supplied."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/halt",
        json={"reason": "item_failed", "item_id": w["item_a_id"]},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["rollout_id"], "wave_halted")
    assert event is not None
    assert event["payload"]["item_id"] == w["item_a_id"]


async def test_halt_rollout_emits_comment_id_in_payload(
    client: AsyncClient, linear_wave: dict
) -> None:
    """The wave_halted event payload contains the comment_id of the created comment."""
    w = linear_wave
    db = w["db"]
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/halt",
        json={"reason": "manual_halt", "comment": "Stopping for review."},
        headers=w["headers"],
    )
    assert resp.status_code == 200

    event = await _get_wave_event(db, w["rollout_id"], "wave_halted")
    assert event is not None
    comment_id = event["payload"].get("comment_id")
    assert comment_id is not None

    # Verify the comment actually exists in the DB
    comment_row = await db.fetchrow("SELECT * FROM comments WHERE id = $1", comment_id)
    assert comment_row is not None
    assert "Stopping for review." in comment_row["content_markdown"]


# ---------------------------------------------------------------------------
# replan_rollout tests
# ---------------------------------------------------------------------------


async def test_replan_rollout_no_remaining(
    client: AsyncClient, linear_wave: dict
) -> None:
    """When all items are terminal, replan_rollout raises 422 (nothing to replan)."""
    w = linear_wave
    db = w["db"]
    # Mark all items as completed
    await db.execute(
        "UPDATE rollout_items SET status = 'completed' WHERE rollout_id = $1",
        w["rollout_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/replan",
        json={},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_replan_rollout_creates_new_version(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_rollout creates a new rollout_plans row with version = old_version + 1."""
    w = linear_wave
    db = w["db"]

    mock_plan = {
        "nodes": [w["item_b_id"]],
        "edges": [],
        "planner_model": "mock-model",
    }

    with patch(
        "agent_gtd.services.rollout_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        # Complete A so B is the only remaining item
        await db.execute(
            "UPDATE rollout_items SET status = 'completed'"
            " WHERE rollout_id = $1 AND item_id = $2",
            w["rollout_id"],
            w["item_a_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{w['rollout_id']}/replan",
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
    event = await _get_wave_event(db, w["rollout_id"], "wave_replanned")
    assert event is not None
    assert event["payload"]["old_version"] == 1
    assert event["payload"]["new_version"] == 2


# ---------------------------------------------------------------------------
# Error-path / branch-coverage tests
# ---------------------------------------------------------------------------


async def test_advance_rollout_not_found(
    client: AsyncClient, linear_wave: dict
) -> None:
    """advance_rollout with a bad rollout_id → 404."""
    w = linear_wave
    resp = await client.get(
        "/api/rollouts/00000000-0000-0000-0000-000000000000/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 404


async def test_advance_rollout_not_running(
    client: AsyncClient, linear_wave: dict
) -> None:
    """advance_rollout on a non-running wave → 422."""
    w = linear_wave
    db = w["db"]
    # Halt the wave first
    await db.execute(
        "UPDATE autonomous_rollouts SET status = 'halted' WHERE id = $1",
        w["rollout_id"],
    )
    resp = await client.get(
        f"/api/rollouts/{w['rollout_id']}/advance",
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_item_in_rollout_invalid_outcome(
    client: AsyncClient, linear_wave: dict
) -> None:
    """complete_item_in_rollout with an invalid outcome → 422."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={"item_id": w["item_a_id"], "outcome": "invalid_outcome"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_item_in_rollout_item_not_found(
    client: AsyncClient, linear_wave: dict
) -> None:
    """complete_item_in_rollout with an item not in the wave → 404."""
    w = linear_wave
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": "00000000-0000-0000-0000-000000000000",
            "outcome": "completed",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 404


async def test_complete_item_in_rollout_downstream_not_pending(
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
        f"/api/rollouts/{wave_id}/complete-item",
        json={"item_id": item_a, "outcome": "completed"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # B is dispatched so not newly_ready; C should be newly_ready
    assert item_c in data["newly_ready"]
    assert item_b not in data["newly_ready"]


async def test_replan_rollout_not_running(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_rollout on a non-running wave → 422."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE autonomous_rollouts SET status = 'halted' WHERE id = $1",
        w["rollout_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/replan",
        json={},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_replan_rollout_with_from_item(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_rollout with from_item restricts replanning to A's subgraph (B only)."""
    w = linear_wave
    db = w["db"]

    mock_plan = {
        "nodes": [w["item_b_id"]],
        "edges": [],
        "planner_model": "mock",
    }

    with patch(
        "agent_gtd.services.rollout_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        # Complete A so only B remains
        await db.execute(
            "UPDATE rollout_items SET status = 'completed'"
            " WHERE rollout_id = $1 AND item_id = $2",
            w["rollout_id"],
            w["item_a_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{w['rollout_id']}/replan",
            json={"from_item": w["item_a_id"]},
            headers=w["headers"],
        )

    assert resp.status_code == 200
    data = resp.json()
    # B is downstream of A → it should be in the replanned subgraph
    assert data["new_version"] == 2


async def test_replan_rollout_from_item_no_descendants(
    client: AsyncClient, linear_wave: dict
) -> None:
    """replan_rollout with from_item that has no remaining descendants → 422."""
    w = linear_wave
    db = w["db"]
    # Mark B as completed so from_item=A has no remaining descendants
    await db.execute(
        "UPDATE rollout_items SET status = 'completed'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_b_id"],
    )
    # A is still pending; from_item=B (leaf) has no descendants at all
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/replan",
        json={"from_item": w["item_b_id"]},
        headers=w["headers"],
    )
    # B has no remaining descendant items → 422
    assert resp.status_code == 422


async def test_call_planner_no_config(linear_wave: dict) -> None:
    """_call_planner raises ValidationError when dispatch service is not configured."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.rollout_service import _call_planner

    w = linear_wave
    db = w["db"]
    # user_id is w["user_id"] — no dispatch config has been set for this test user
    with pytest.raises(ValidationError, match="not configured"):
        await _call_planner(db, w["user_id"], w["rollout_id"], [w["item_a_id"]])


async def test_call_planner_http_error(linear_wave: dict) -> None:
    """_call_planner raises ValidationError when the planner HTTP call fails."""
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.rollout_service import _call_planner
    from agent_gtd.services.settings_service import set_user_setting

    w = linear_wave
    db = w["db"]
    user_id = w["user_id"]

    # Configure dispatch settings for this user
    await set_user_setting(
        db, user_id, "dispatch.service_url", "http://fake-planner:8100"
    )
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
            await _call_planner(db, user_id, w["rollout_id"], [w["item_a_id"]])


async def test_replan_rollout_readiness_regression(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """replan_rollout reverts a 'ready' item to 'pending'
    when it gains a predecessor."""
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
        db,
        wave_id,
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
        "agent_gtd.services.rollout_service._call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        resp = await client.post(
            f"/api/rollouts/{wave_id}/replan",
            json={},
            headers=headers,
        )

    assert resp.status_code == 200
    # B should now be 'pending' since A (its predecessor) is still pending
    b_row = await _get_wave_plan_item(db, wave_id, item_b)
    assert b_row["status"] == "pending"


# ---------------------------------------------------------------------------
# POST /api/rollouts (plan_rollout route)
# ---------------------------------------------------------------------------


async def _make_ready_item(db: Any, user_id: str, project_id: str, title: str) -> str:
    """Insert a GTD item that satisfies the wave legality contract."""
    item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, description, status,"
        "  labels, acceptance_criteria, files_to_modify, scope_out,"
        "  build_engine, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
        item_id,
        project_id,
        user_id,
        title,
        "Background context.",
        "ready",
        encode_json_list([]),
        encode_json_list(["AC-1: The feature works correctly."]),
        encode_file_specs(
            [{"path": "src/agent_gtd/main.py", "change": "Update logic"}]
        ),
        encode_json_list([]),
        "claude-code",
        now,
        now,
    )
    return item_id


async def _configure_dispatch(db: Any, user_id: str, url: str, api_key: str) -> None:
    """Insert per-user dispatch config rows."""
    now = _now()
    for k, v in (
        ("dispatch.service_url", url),
        ("dispatch.service_api_key", api_key),
    ):
        await db.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at)"
            " VALUES ($1, $2, $3, $4)",
            user_id,
            k,
            v,
            now,
        )


async def test_plan_rollout_route_legality_failure_returns_422(
    client: AsyncClient, _setup_db
):
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("plan-route-1@example.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)
    # Item lacks the required ## Acceptance Criteria section
    bad_item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, description, status,"
        "  created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        bad_item_id,
        project_id,
        user_id,
        "Bad item",
        "no AC, no files",
        "ready",
        now,
        now,
    )
    await _configure_dispatch(db, user_id, "http://dispatch.test:8100", "k")

    resp = await client.post(
        "/api/rollouts",
        json={"item_ids": [bad_item_id]},
        headers={"Authorization": f"Bearer {create_token(user_id)}"},
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "legality_contract_failed"
    assert isinstance(detail["failures"], list)
    assert detail["failures"][0]["item_id"] == bad_item_id


async def test_plan_rollout_route_happy_path_returns_dag(
    client: AsyncClient, _setup_db
):
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("plan-route-2@example.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)
    item_a = await _make_ready_item(db, user_id, project_id, "Task A")
    item_b = await _make_ready_item(db, user_id, project_id, "Task B")
    await _configure_dispatch(db, user_id, "http://dispatch.test:8100", "k")

    mock_plan = {
        "nodes": [item_a, item_b],
        "edges": [{"from_item_id": item_a, "to_item_id": item_b}],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.rollout_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        resp = await client.post(
            "/api/rollouts",
            json={"item_ids": [item_a, item_b]},
            headers={"Authorization": f"Bearer {create_token(user_id)}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "rollout_id" in body
    assert body["status"] == "pending"
    assert body["item_count"] == 2
    assert body["plan"]["edges"] == [{"from_item_id": item_a, "to_item_id": item_b}]


# ---------------------------------------------------------------------------
# Manage-mode dispatch → wave status flip (AC-3)
# ---------------------------------------------------------------------------


@pytest.fixture
async def _mock_dispatch_preflight():
    """Skip the dispatch service health check for manage-mode dispatch tests."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
    ):
        yield


async def test_manage_dispatch_flips_wave_to_running(
    client: AsyncClient, _mock_dispatch_preflight
):
    """dispatch_rollout flips wave status to running."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-manage-1@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    # Give the project a git_origin so dispatch works
    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/manage-repo.git",
        now,
        project_id,
    )

    # Dispatch config required by the route
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    rollout_id = await _make_wave_run(db, user_id, project_id, status="pending")

    token = create_token(user_id)
    # Use dispatch_rollout (correct path: item_id=NULL manage run)
    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text

    wave = await _get_rollout(db, rollout_id)
    assert wave["status"] == "running"
    assert wave["started_at"] is not None


async def test_manage_dispatch_emits_wave_started_event(
    client: AsyncClient, _mock_dispatch_preflight
):
    """dispatch_rollout emits a wave_started event in rollout_events."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-manage-2@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/manage-repo2.git",
        now,
        project_id,
    )

    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    rollout_id = await _make_wave_run(db, user_id, project_id, status="pending")

    token = create_token(user_id)
    # Use dispatch_rollout (correct path: item_id=NULL manage run)
    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    manage_run_id = res.json()["id"]

    event = await _get_wave_event(db, rollout_id, "wave_started")
    assert event is not None
    assert event["actor"] == "manager"
    assert event["payload"]["manage_run_id"] == manage_run_id


async def test_manage_dispatch_rejected_if_wave_not_pending(
    client: AsyncClient, _mock_dispatch_preflight
):
    """dispatch_item(mode='manage') is rejected (409) when wave is not pending."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-manage-3@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/manage-repo3.git",
        now,
        project_id,
    )

    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    for bad_status in ("running", "halted", "completed", "failed"):
        item_id = await _make_item(db, user_id, project_id, f"Task {bad_status}")
        rollout_id = await _make_wave_run(db, user_id, project_id, status=bad_status)

        token = create_token(user_id)
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={"mode": "manage", "rollout_id": rollout_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 409, (
            f"Expected 409 for status={bad_status}, got {res.status_code}: {res.text}"
        )


# ---------------------------------------------------------------------------
# Build-mode wave linkage tests (AC-A1, AC-A2, AC-A3)
# ---------------------------------------------------------------------------


async def test_build_dispatch_transitions_wave_plan_item_to_dispatched(
    client: AsyncClient, _mock_dispatch_preflight
):
    """build dispatch with rollout_id flips rollout_items to 'dispatched'."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-build-1@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/build-repo1.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    item_id = await _make_item(db, user_id, project_id, "Build task 1")
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_item(db, rollout_id, item_id, status="ready")

    token = create_token(user_id)
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "build", "rollout_id": rollout_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text

    row = await _get_wave_plan_item(db, rollout_id, item_id)
    assert row["status"] == "dispatched"


async def test_build_dispatch_sets_claude_run_id_on_wave_plan_item(
    client: AsyncClient, _mock_dispatch_preflight
):
    """build dispatch stores new run ID in rollout_items.claude_run_id."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-build-2@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/build-repo2.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    item_id = await _make_item(db, user_id, project_id, "Build task 2")
    rollout_id = await _make_wave_run(db, user_id, project_id, status="running")
    await _make_wave_item(db, rollout_id, item_id, status="ready")

    token = create_token(user_id)
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "build", "rollout_id": rollout_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    run_id = res.json()["id"]

    row = await _get_wave_plan_item(db, rollout_id, item_id)
    assert row["status"] == "dispatched"
    assert str(row["claude_run_id"]) == run_id


async def test_build_dispatch_with_non_running_wave_raises_validation_error(
    client: AsyncClient, _mock_dispatch_preflight
):
    """build dispatch with non-running wave returns 409, leaves item unchanged."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-build-3@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/build-repo3.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    for bad_status in ("pending", "halted", "completed"):
        item_id = await _make_item(db, user_id, project_id, f"Build task {bad_status}")
        rollout_id = await _make_wave_run(db, user_id, project_id, status=bad_status)
        await _make_wave_item(db, rollout_id, item_id, status="ready")

        token = create_token(user_id)
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={"mode": "build", "rollout_id": rollout_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 409, (
            f"Expected 409 for status={bad_status}, got {res.status_code}: {res.text}"
        )
        # rollout_items row must remain unchanged
        row = await _get_wave_plan_item(db, rollout_id, item_id)
        assert row["status"] == "ready", (
            "rollout_items should stay 'ready' when dispatch is rejected"
        )


async def test_manage_dispatch_does_not_flip_item_status(
    client: AsyncClient, _mock_dispatch_preflight
):
    """dispatch_rollout does not change any item's status (regression: kb-01515, Bug 1).

    After the fix, dispatch_item(mode='manage') is blocked entirely. The correct
    path is dispatch_rollout which creates a manage run with item_id=NULL and
    therefore never touches any item's status. This test verifies that the old
    path (dispatch_item mode=manage) returns 409, and that dispatch_rollout
    leaves a 'ready' item untouched.
    """
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-manage-status@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/manage-status.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Create a rollout-bound item in 'ready' status
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        "Wave item A",
        "ready",
        now,
        now,
    )

    rollout_id = await _make_wave_run(db, user_id, project_id, status="pending")

    token = create_token(user_id)

    # Old path (dispatch_item mode=manage) must be rejected — confirms Bug 1 fix
    res_old = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "manage", "rollout_id": rollout_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_old.status_code == 409, (
        f"Expected 409 for dispatch_item(mode=manage), got {res_old.status_code}"
    )

    # Item status must still be unchanged after the rejected call
    row = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_id)
    assert row is not None
    got = row["status"]
    assert got == "ready", (
        f"Expected item status 'ready' after rejected manage dispatch, got '{got}'"
    )

    # Correct path: dispatch_rollout creates item_id=NULL run, item status unchanged
    res_new = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_new.status_code == 201, res_new.text

    # Item status still unchanged after correct dispatch path
    row2 = await db.fetchrow("SELECT status FROM items WHERE id = $1", item_id)
    assert row2 is not None
    assert row2["status"] == "ready", (
        f"Expected item status 'ready' after dispatch_rollout, got '{row2['status']}'"
    )


async def test_manage_dispatch_without_rollout_id_rejected(
    client: AsyncClient, _mock_dispatch_preflight
):
    """dispatch_item(mode='manage') without rollout_id returns 409."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-manage-no-wrid@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/manage-no-wrid.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    item_id = await _make_item(db, user_id, project_id, "Manager task no wrid")

    token = create_token(user_id)
    res = await client.post(
        f"/api/items/{item_id}/dispatch",
        json={"mode": "manage"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409, res.text


async def test_happy_path_plan_rollout_to_complete_item_in_rollout(
    client: AsyncClient, _mock_dispatch_preflight
):
    """Full happy path: dispatch_rollout → build dispatch → complete_item_in_rollout.

    Wave transitions: pending→running (dispatch_rollout), ready→dispatched (build),
    dispatched→completed (complete_item_in_rollout).  Downstream item B becomes 'ready'.

    This is the correct flow after Bug 1 fix: dispatch_rollout creates a manage run
    with item_id=NULL, avoiding the deadlock where the manage run was keyed to a
    rollout item's ID and blocked child build dispatch via RunActiveError.
    """
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    db = await get_db()
    user = await register_user("wave-happy-path@test.com", "pw")
    user_id = user.id
    project_id = await _make_project(db, user_id)

    now = _now()
    await db.execute(
        "UPDATE projects SET git_origin = $1, updated_at = $2 WHERE id = $3",
        "git@github.com:test/happy-path-repo.git",
        now,
        project_id,
    )
    await set_user_setting(db, user_id, "dispatch.service_url", "http://fake:8100")
    await set_user_setting(db, user_id, "dispatch.service_api_key", "test-key")

    # Create items: A (wave-1), B (wave-2, blocked by A)
    item_a_id = await _make_item(db, user_id, project_id, "Happy Item A")
    item_b_id = await _make_item(db, user_id, project_id, "Happy Item B")

    # Create a pending wave
    rollout_id = await _make_wave_run(db, user_id, project_id, status="pending")

    # Create DAG: A → B (B blocked by A)
    await _make_wave_plan(
        db,
        rollout_id,
        nodes=[item_a_id, item_b_id],
        edges=[{"from_item_id": item_a_id, "to_item_id": item_b_id}],
    )
    # Wave-1: A is ready; B is pending (blocked)
    await _make_wave_item(db, rollout_id, item_a_id, status="ready")
    await _make_wave_item(db, rollout_id, item_b_id, status="pending")

    token = create_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: dispatch_rollout → wave becomes 'running' (item_id=NULL manage run)
    res = await client.post(
        f"/api/rollouts/{rollout_id}/dispatch",
        headers=headers,
    )
    assert res.status_code == 201, f"dispatch_rollout failed: {res.text}"

    wave = await _get_rollout(db, rollout_id)
    assert wave["status"] == "running"

    # Step 2: build dispatch for item A → rollout_items A becomes 'dispatched'
    res = await client.post(
        f"/api/items/{item_a_id}/dispatch",
        json={"mode": "build", "rollout_id": rollout_id},
        headers=headers,
    )
    assert res.status_code == 201, f"build dispatch failed: {res.text}"
    run_id = res.json()["id"]

    row_a = await _get_wave_plan_item(db, rollout_id, item_a_id)
    assert row_a["status"] == "dispatched"
    assert str(row_a["claude_run_id"]) == run_id

    # Step 3: complete item A → B unblocked (becomes 'ready')
    res = await client.post(
        f"/api/rollouts/{rollout_id}/complete-item",
        json={"item_id": item_a_id, "outcome": "completed"},
        headers=headers,
    )
    assert res.status_code == 200, f"complete_item_in_rollout failed: {res.text}"
    data = res.json()
    assert item_b_id in data["newly_ready"]

    # Final DB state
    row_a = await _get_wave_plan_item(db, rollout_id, item_a_id)
    row_b = await _get_wave_plan_item(db, rollout_id, item_b_id)
    assert row_a["status"] == "completed"
    assert row_b["status"] == "ready"


# ---------------------------------------------------------------------------
# update_rollout_state tests (AC-2, AC-10)
# ---------------------------------------------------------------------------


async def test_update_rollout_state_valid_phase(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Valid phase updates manager state columns and appends an event."""
    w = linear_wave
    db = w["db"]

    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/state",
        json={
            "phase": "dispatching",
            "current_item_id": w["item_a_id"],
            "current_step": "Dispatching Task A",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rollout_id"] == w["rollout_id"]
    assert data["phase"] == "dispatching"
    assert data["current_item_id"] == w["item_a_id"]
    assert data["current_step"] == "Dispatching Task A"
    assert "ts" in data

    # DB columns updated
    wave = await _get_rollout(db, w["rollout_id"])
    assert wave["manager_phase"] == "dispatching"
    assert wave["manager_current_item_id"] == w["item_a_id"]
    assert wave["manager_current_step"] == "Dispatching Task A"
    assert wave["manager_state_updated_at"] is not None

    # SSE event appended (AC-5)
    event = await _get_wave_event(db, w["rollout_id"], "manager_state_update")
    assert event is not None
    assert event["actor"] == "manager"
    assert event["payload"]["phase"] == "dispatching"


async def test_update_rollout_state_all_phases(
    client: AsyncClient, linear_wave: dict
) -> None:
    """All valid phase values are accepted."""
    w = linear_wave
    valid_phases = [
        "warm_up",
        "dispatching",
        "polling",
        "reviewing",
        "merging",
        "reconciling_ac",
        "halted",
    ]
    for phase in valid_phases:
        resp = await client.post(
            f"/api/rollouts/{w['rollout_id']}/state",
            json={"phase": phase},
            headers=w["headers"],
        )
        assert resp.status_code == 200, f"phase '{phase}' was rejected"


async def test_update_rollout_state_invalid_phase(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Invalid phase value returns 422 Unprocessable Entity."""
    w = linear_wave
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/state",
        json={"phase": "not_a_real_phase"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_update_rollout_state_non_running_wave(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Calling update_rollout_state on a halted wave returns 422."""
    w = linear_wave
    db = w["db"]

    # Manually flip wave to halted
    await db.execute(
        "UPDATE autonomous_rollouts SET status = 'halted' WHERE id = $1",
        w["rollout_id"],
    )

    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/state",
        json={"phase": "merging"},
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_update_rollout_state_unauthorized(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Caller that does not own the wave gets 404."""
    from agent_gtd.auth import create_token, register_user

    w = linear_wave

    # Create a different user
    other_user = await register_user("other-wave-user@example.com", "pw")
    other_headers = {"Authorization": f"Bearer {create_token(other_user.id)}"}

    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/state",
        json={"phase": "merging"},
        headers=other_headers,
    )
    assert resp.status_code == 404


async def test_update_rollout_state_null_item(
    client: AsyncClient, linear_wave: dict
) -> None:
    """update_rollout_state with no current_item_id stores null correctly."""
    w = linear_wave
    db = w["db"]

    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/state",
        json={"phase": "polling", "current_step": "Waiting for build"},
        headers=w["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_item_id"] is None

    wave = await _get_rollout(db, w["rollout_id"])
    assert wave["manager_current_item_id"] is None
    assert wave["manager_current_step"] == "Waiting for build"


# ---------------------------------------------------------------------------
# Enum validation tests (AC-13)
# ---------------------------------------------------------------------------


async def test_complete_item_in_rollout_invalid_merge_actor(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Invalid merge_actor value returns 422 — Pydantic-enforced via MergeActor enum."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "merge_actor": "bogus-actor",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 422


async def test_complete_item_in_rollout_manager_autonomous_valid(
    client: AsyncClient, linear_wave: dict
) -> None:
    """'manager-autonomous' is now a valid MergeActor value (AC-1)."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "merge_actor": "manager-autonomous",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["rollout_item"]["merge_actor"] == "manager-autonomous"


async def test_complete_item_in_rollout_invalid_decision_rule(
    client: AsyncClient, linear_wave: dict
) -> None:
    """Invalid decision_rule value returns 422 — Pydantic-enforced via Literal type."""
    w = linear_wave
    db = w["db"]
    await db.execute(
        "UPDATE rollout_items SET status = 'dispatched'"
        " WHERE rollout_id = $1 AND item_id = $2",
        w["rollout_id"],
        w["item_a_id"],
    )
    resp = await client.post(
        f"/api/rollouts/{w['rollout_id']}/complete-item",
        json={
            "item_id": w["item_a_id"],
            "outcome": "completed",
            "decision_rule": "patch-only",
        },
        headers=w["headers"],
    )
    assert resp.status_code == 422
