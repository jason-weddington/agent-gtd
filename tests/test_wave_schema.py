"""Tests for wave-manager schema additions (autonomous_wave_runs, wave_plans,
wave_plan_items, wave_events) and corresponding Pydantic models."""

import json
import uuid
from datetime import UTC, datetime

import pytest

import agent_gtd.database as db_mod
from agent_gtd.sqlite_pool import SqlitePool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = "2026-01-01T00:00:00+00:00"


async def _make_pool() -> SqlitePool:
    """Return a fresh in-memory pool with the full schema applied."""
    pool = SqlitePool()
    async with pool.acquire() as conn:
        for stmt in db_mod._SCHEMA_STATEMENTS:
            await conn.execute(stmt)
    return pool


async def _seed_user_and_project(pool: SqlitePool) -> tuple[str, str]:
    """Insert a user + project and return (user_id, project_id)."""
    user_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id}@test.com",
        "x",
        NOW,
    )
    await pool.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Test Project",
        NOW,
        NOW,
    )
    return user_id, project_id


async def _seed_wave_run(pool: SqlitePool, project_id: str, user_id: str) -> str:
    """Insert a minimal wave run and return its id."""
    wave_run_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO autonomous_wave_runs "
        "(id, project_id, lead_user_id, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        wave_run_id,
        project_id,
        user_id,
        NOW,
        NOW,
    )
    return wave_run_id


async def _seed_item(pool: SqlitePool, project_id: str, user_id: str) -> str:
    """Insert a minimal item and return its id."""
    item_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        item_id,
        project_id,
        user_id,
        "Test Item",
        NOW,
        NOW,
    )
    return item_id


# ---------------------------------------------------------------------------
# Table-existence tests
# ---------------------------------------------------------------------------


async def test_autonomous_wave_runs_table_exists():
    pool = await _make_pool()
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='autonomous_wave_runs'"
    )
    assert len(tables) == 1
    assert tables[0]["name"] == "autonomous_wave_runs"
    await pool.close()


async def test_wave_plans_table_exists():
    pool = await _make_pool()
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wave_plans'"
    )
    assert len(tables) == 1
    await pool.close()


async def test_wave_plan_items_table_exists():
    pool = await _make_pool()
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wave_plan_items'"
    )
    assert len(tables) == 1
    await pool.close()


async def test_wave_events_table_exists():
    pool = await _make_pool()
    tables = await pool.fetch(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wave_events'"
    )
    assert len(tables) == 1
    await pool.close()


async def test_claude_runs_has_wave_run_id_column():
    pool = await _make_pool()
    cols = await pool.fetch("PRAGMA table_info(claude_runs)")
    col_names = [row["name"] for row in cols]
    assert "wave_run_id" in col_names
    await pool.close()


# ---------------------------------------------------------------------------
# INSERT / SELECT round-trip tests
# ---------------------------------------------------------------------------


async def test_insert_and_select_wave_run():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    row = await pool.fetchrow(
        "SELECT * FROM autonomous_wave_runs WHERE id = $1", wave_run_id
    )
    assert row is not None
    assert row["project_id"] == project_id
    assert row["lead_user_id"] == user_id
    assert row["status"] == "pending"
    assert row["halt_reason"] is None
    await pool.close()


async def test_insert_and_select_wave_plan():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    plan_id = str(uuid.uuid4())
    nodes = json.dumps(["item-1", "item-2"])
    edges = json.dumps([{"from": "item-1", "to": "item-2"}])
    await pool.execute(
        "INSERT INTO wave_plans "
        "(id, wave_run_id, nodes, edges, planner_model, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        plan_id,
        wave_run_id,
        nodes,
        edges,
        "claude-opus-4",
        NOW,
    )

    row = await pool.fetchrow("SELECT * FROM wave_plans WHERE id = $1", plan_id)
    assert row is not None
    assert row["wave_run_id"] == wave_run_id
    assert row["version"] == 1
    assert json.loads(row["nodes"]) == ["item-1", "item-2"]
    assert json.loads(row["edges"]) == [{"from": "item-1", "to": "item-2"}]
    await pool.close()


async def test_insert_and_select_wave_plan_item():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)
    item_id = await _seed_item(pool, project_id, user_id)

    await pool.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id) VALUES ($1, $2)",
        wave_run_id,
        item_id,
    )

    row = await pool.fetchrow(
        "SELECT * FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_id,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["claude_run_id"] is None
    assert row["merge_actor"] is None
    await pool.close()


async def test_insert_and_select_wave_event():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    event_id = str(uuid.uuid4())
    payload = json.dumps({"msg": "hello"})
    await pool.execute(
        "INSERT INTO wave_events "
        "(id, wave_run_id, seq, ts, kind, actor, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        event_id,
        wave_run_id,
        1,
        NOW,
        "run.started",
        "manager",
        payload,
    )

    row = await pool.fetchrow("SELECT * FROM wave_events WHERE id = $1", event_id)
    assert row is not None
    assert row["seq"] == 1
    assert row["kind"] == "run.started"
    assert row["actor"] == "manager"
    assert json.loads(row["payload"]) == {"msg": "hello"}
    assert row["decision_rule"] == ""
    await pool.close()


# ---------------------------------------------------------------------------
# Constraint tests
# ---------------------------------------------------------------------------


async def test_wave_plan_items_composite_pk_rejects_duplicate():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)
    item_id = await _seed_item(pool, project_id, user_id)

    await pool.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id) VALUES ($1, $2)",
        wave_run_id,
        item_id,
    )

    with pytest.raises(Exception):  # noqa: B017
        await pool.execute(
            "INSERT INTO wave_plan_items (wave_run_id, item_id) VALUES ($1, $2)",
            wave_run_id,
            item_id,
        )

    await pool.close()


async def test_wave_events_unique_seq_per_wave():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    await pool.execute(
        "INSERT INTO wave_events "
        "(id, wave_run_id, seq, ts, kind, actor) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        str(uuid.uuid4()),
        wave_run_id,
        1,
        NOW,
        "run.started",
        "manager",
    )

    with pytest.raises(Exception):  # noqa: B017
        await pool.execute(
            "INSERT INTO wave_events "
            "(id, wave_run_id, seq, ts, kind, actor) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            str(uuid.uuid4()),
            wave_run_id,
            1,  # duplicate seq for same wave_run_id
            NOW,
            "run.started",
            "manager",
        )

    await pool.close()


async def test_wave_events_same_seq_different_waves_allowed():
    """seq=1 in wave A and seq=1 in wave B should not conflict."""
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id_a = await _seed_wave_run(pool, project_id, user_id)
    wave_run_id_b = await _seed_wave_run(pool, project_id, user_id)

    await pool.execute(
        "INSERT INTO wave_events "
        "(id, wave_run_id, seq, ts, kind, actor) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        str(uuid.uuid4()),
        wave_run_id_a,
        1,
        NOW,
        "run.started",
        "manager",
    )
    # Must not raise
    await pool.execute(
        "INSERT INTO wave_events "
        "(id, wave_run_id, seq, ts, kind, actor) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        str(uuid.uuid4()),
        wave_run_id_b,
        1,
        NOW,
        "run.started",
        "manager",
    )
    await pool.close()


# ---------------------------------------------------------------------------
# JSON round-trip tests
# ---------------------------------------------------------------------------


async def test_wave_plan_json_roundtrip():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    plan_id = str(uuid.uuid4())
    nodes_in = ["a", "b", "c"]
    edges_in = [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]
    await pool.execute(
        "INSERT INTO wave_plans "
        "(id, wave_run_id, nodes, edges, planner_model, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        plan_id,
        wave_run_id,
        json.dumps(nodes_in),
        json.dumps(edges_in),
        "test-model",
        NOW,
    )

    row = await pool.fetchrow("SELECT * FROM wave_plans WHERE id = $1", plan_id)
    assert row is not None
    assert isinstance(row["nodes"], str), "nodes must be stored as TEXT"
    assert isinstance(row["edges"], str), "edges must be stored as TEXT"
    assert json.loads(row["nodes"]) == nodes_in
    assert json.loads(row["edges"]) == edges_in
    await pool.close()


async def test_wave_event_payload_json_roundtrip():
    pool = await _make_pool()
    user_id, project_id = await _seed_user_and_project(pool)
    wave_run_id = await _seed_wave_run(pool, project_id, user_id)

    payload_in: dict = {"reason": "ok", "items": [1, 2, 3], "nested": {"x": True}}
    await pool.execute(
        "INSERT INTO wave_events "
        "(id, wave_run_id, seq, ts, kind, actor, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        str(uuid.uuid4()),
        wave_run_id,
        1,
        NOW,
        "plan.ready",
        "manager",
        json.dumps(payload_in),
    )

    row = await pool.fetchrow(
        "SELECT * FROM wave_events WHERE wave_run_id = $1", wave_run_id
    )
    assert row is not None
    assert isinstance(row["payload"], str), "payload must be stored as TEXT"
    assert json.loads(row["payload"]) == payload_in
    await pool.close()


# ---------------------------------------------------------------------------
# init_db idempotency (via autouse fixture)
# ---------------------------------------------------------------------------


async def test_init_db_idempotent(_setup_db):
    """Calling init_db() twice must not raise (idempotent)."""
    from agent_gtd.database import init_db

    await init_db()  # second call — should be a no-op


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_wave_run_model():
    from agent_gtd.models import WaveRun, WaveRunStatus

    run = WaveRun(
        id="wr-1",
        project_id="p-1",
        lead_user_id="u-1",
        status=WaveRunStatus.RUNNING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert run.status == "running"
    assert run.halt_reason is None
    assert run.started_at is None
    assert run.ended_at is None


def test_wave_plan_model():
    from agent_gtd.models import WavePlan

    plan = WavePlan(
        id="wp-1",
        wave_run_id="wr-1",
        version=2,
        nodes=["a", "b"],
        edges=[{"from": "a", "to": "b"}],
        planner_model="claude-opus-4",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert plan.version == 2
    assert plan.nodes == ["a", "b"]
    assert plan.edges == [{"from": "a", "to": "b"}]


def test_wave_plan_item_model():
    from agent_gtd.models import WavePlanItem, WavePlanItemStatus

    item = WavePlanItem(
        wave_run_id="wr-1",
        item_id="i-1",
        status=WavePlanItemStatus.DISPATCHED,
    )
    assert item.status == "dispatched"
    assert item.claude_run_id is None
    assert item.merge_actor is None


def test_wave_event_model():
    from agent_gtd.models import WaveEvent, WaveEventActor

    event = WaveEvent(
        id="we-1",
        wave_run_id="wr-1",
        seq=1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        kind="run.started",
        actor=WaveEventActor.MANAGER,
        decision_rule="",
        payload={"key": "val"},
    )
    assert event.actor == "manager"
    assert event.payload == {"key": "val"}


def test_run_response_has_wave_run_id():
    from agent_gtd.models import RunResponse, RunStatus

    resp = RunResponse(
        id="r-1",
        item_id="i-1",
        project_id="p-1",
        status=RunStatus.PENDING,
        feature_branch="feat/test",
        workspace_dir="/workspace/test",
        max_turns=100,
        mode="build",
        started_at=None,
        finished_at=None,
        error_msg="",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert resp.wave_run_id is None

    resp_with_wave = resp.model_copy(update={"wave_run_id": "wr-1"})
    assert resp_with_wave.wave_run_id == "wr-1"


# ---------------------------------------------------------------------------
# Enum string-value tests
# ---------------------------------------------------------------------------


def test_wave_run_status_values():
    from agent_gtd.models import WaveRunStatus

    assert WaveRunStatus.PENDING == "pending"
    assert WaveRunStatus.PLANNING == "planning"
    assert WaveRunStatus.RUNNING == "running"
    assert WaveRunStatus.COMPLETED == "completed"
    assert WaveRunStatus.HALTED == "halted"
    assert WaveRunStatus.FAILED == "failed"


def test_wave_plan_item_status_values():
    from agent_gtd.models import WavePlanItemStatus

    assert WavePlanItemStatus.PENDING == "pending"
    assert WavePlanItemStatus.READY == "ready"
    assert WavePlanItemStatus.DISPATCHED == "dispatched"
    assert WavePlanItemStatus.COMPLETED == "completed"
    assert WavePlanItemStatus.HALTED == "halted"
    assert WavePlanItemStatus.SKIPPED == "skipped"


def test_wave_event_actor_values():
    from agent_gtd.models import WaveEventActor

    assert WaveEventActor.MANAGER == "manager"
    assert WaveEventActor.CHILD_AGENT == "child-agent"
    assert WaveEventActor.HUMAN == "human"


def test_merge_actor_values():
    from agent_gtd.models import MergeActor

    assert MergeActor.HUMAN == "human"
    assert MergeActor.MANAGER_ALLOWLIST == "manager-allowlist"
    assert MergeActor.MANAGER_HUMAN_FIXUP == "manager+human-fixup"
