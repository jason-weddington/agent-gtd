"""Integration tests for the plan_rollout MCP tool (happy path and error cases)."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_gtd.auth import generate_api_key, hash_api_key, register_user
from agent_gtd.database import encode_file_specs, encode_json_list, get_db
from agent_gtd.mcp_backend import LocalBackend
from agent_gtd.mcp_server import mcp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC).isoformat()

VALID_DESC = """\
## Acceptance Criteria
- [ ] First criterion done
- [ ] Second criterion done

## Files to Modify
- src/agent_gtd/services/rollout_service.py
- tests/test_mcp_wave.py
"""


def _parse_result(result: Any) -> Any:
    """Parse a CallToolResult into Python data."""
    if isinstance(result.data, dict):
        return result.data
    if result.content and hasattr(result.content[0], "text"):
        return json.loads(result.content[0].text)
    return result.data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def user():
    return await register_user("wave@example.com", "testpass123")


@pytest.fixture
async def user_id(user):
    return user.id


@pytest.fixture
async def api_key(user_id):
    """Create an API key for the test user and return the plaintext key."""
    db = await get_db()
    key = generate_api_key()
    h = hash_api_key(key)
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        str(uuid.uuid4()),
        user_id,
        h,
        "wave-test-key",
        NOW,
    )
    return key


@pytest.fixture(autouse=True)
def _force_local_backend(monkeypatch):
    """Ensure MCP tools use LocalBackend regardless of env vars."""
    import agent_gtd.database as db_mod
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", "")
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: False)


@pytest.fixture
async def mcp_client_authed(api_key, monkeypatch):
    """Authenticated MCP client via ENV API key (no login tool required)."""
    import agent_gtd.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_ENV_API_KEY", api_key)
    async with Client(mcp) as c:
        yield c


async def _configure_dispatch(user_id: str, url: str, api_key_val: str) -> None:
    """Insert per-user dispatch config directly into the DB."""
    db = await get_db()
    for key, value in [
        ("dispatch.service_url", url),
        ("dispatch.service_api_key", api_key_val),
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


async def _create_project(user_id: str) -> str:
    """Insert a project and return its ID."""
    db = await get_db()
    project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Wave Test Project",
        NOW,
        NOW,
    )
    return project_id


async def _create_ready_item(
    user_id: str,
    project_id: str,
    title: str = "Wave item",
) -> str:
    """Insert a ready item with valid structured fields and return its ID."""
    db = await get_db()
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, acceptance_criteria, files_to_modify, scope_out, "
        " build_engine, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
        item_id,
        project_id,
        user_id,
        title,
        "Background context for this wave item.",
        "ready",
        encode_json_list([]),
        encode_json_list(["AC-1: The feature works correctly."]),
        encode_file_specs(
            [{"path": "src/agent_gtd/main.py", "change": "Update logic"}]
        ),
        encode_json_list([]),
        "claude-code",
        NOW,
        NOW,
    )
    return item_id


# ---------------------------------------------------------------------------
# Happy path — single item, no edges
# ---------------------------------------------------------------------------


async def test_plan_rollout_happy_path_single_item(mcp_client_authed, user_id):
    """plan_rollout with one valid item and mocked planner returns a pending rollout."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan_response = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.rollout_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan_response,
    ):
        result = await mcp_client_authed.call_tool(
            "plan_rollout", {"item_ids": [item_id]}
        )

    data = _parse_result(result)

    assert data["status"] == "pending"
    assert data["rollout_id"] is not None
    assert data["item_count"] == 1
    assert data["planner_model"] == "claude-sonnet-4-6"
    assert data["plan"]["nodes"] == [item_id]
    assert data["plan"]["edges"] == []
    assert len(data["per_item"]) == 1

    per = data["per_item"][0]
    assert per["item_id"] == item_id
    assert per["title"] == "Wave item"
    assert per["predecessors"] == []


async def test_plan_rollout_happy_path_two_items_with_edge(mcp_client_authed, user_id):
    """plan_rollout with two items and an edge correctly sets in-degree statuses."""
    project_id = await _create_project(user_id)
    item_a = await _create_ready_item(user_id, project_id, title="Item A")
    item_b = await _create_ready_item(user_id, project_id, title="Item B")
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    # A → B: B depends on A  (from_item_id / to_item_id keys per reconciled spec)
    mock_plan_response = {
        "nodes": [item_a, item_b],
        "edges": [{"from_item_id": item_a, "to_item_id": item_b}],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.rollout_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan_response,
    ):
        result = await mcp_client_authed.call_tool(
            "plan_rollout", {"item_ids": [item_a, item_b]}
        )

    data = _parse_result(result)
    assert data["status"] == "pending"
    assert data["item_count"] == 2

    # Check per_item: A has no predecessors, B has A as predecessor
    per_map = {p["item_id"]: p for p in data["per_item"]}
    assert per_map[item_a]["predecessors"] == []
    assert per_map[item_b]["predecessors"] == [item_a]

    # Check DB: A should be 'ready', B should be 'pending'
    db = await get_db()
    rollout_id = data["rollout_id"]
    row_a = await db.fetchrow(
        "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_a,
    )
    row_b = await db.fetchrow(
        "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_b,
    )
    assert row_a is not None
    assert row_a["status"] == "ready"
    assert row_b is not None
    assert row_b["status"] == "pending"


# ---------------------------------------------------------------------------
# DB state after happy path
# ---------------------------------------------------------------------------


async def test_plan_rollout_inserts_wave_run_as_pending(mcp_client_authed, user_id):
    """After plan_rollout, the wave run is stored with status=pending."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.rollout_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        result = await mcp_client_authed.call_tool(
            "plan_rollout", {"item_ids": [item_id]}
        )

    data = _parse_result(result)
    rollout_id = data["rollout_id"]

    db = await get_db()
    row = await db.fetchrow(
        "SELECT status, project_id, lead_user_id "
        "FROM autonomous_rollouts WHERE id = $1",
        rollout_id,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["project_id"] == project_id
    assert row["lead_user_id"] == user_id


async def test_plan_rollout_inserts_wave_plan(mcp_client_authed, user_id):
    """After plan_rollout, a rollout_plans row is persisted with nodes and edges."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.rollout_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        result = await mcp_client_authed.call_tool(
            "plan_rollout", {"item_ids": [item_id]}
        )

    data = _parse_result(result)
    rollout_id = data["rollout_id"]

    db = await get_db()
    plan_row = await db.fetchrow(
        "SELECT version, nodes, edges, planner_model "
        "FROM rollout_plans WHERE rollout_id = $1",
        rollout_id,
    )
    assert plan_row is not None
    assert plan_row["version"] == 1
    assert json.loads(plan_row["nodes"]) == [item_id]
    assert json.loads(plan_row["edges"]) == []
    assert plan_row["planner_model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Error cases via MCP tool
# ---------------------------------------------------------------------------


async def test_plan_rollout_mcp_empty_item_ids_raises_tool_error(
    mcp_client_authed, user_id
):
    """Empty item_ids raises ToolError via the MCP tool."""
    with pytest.raises(ToolError, match="empty"):
        await mcp_client_authed.call_tool("plan_rollout", {"item_ids": []})


async def test_plan_rollout_mcp_legality_failure_raises_tool_error(
    mcp_client_authed, user_id
):
    """Items that fail the legality contract raise ToolError listing failures."""
    project_id = await _create_project(user_id)
    db = await get_db()
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        item_id,
        project_id,
        user_id,
        "Not ready item",
        "No special sections here",
        "new",
        encode_json_list([]),
        NOW,
        NOW,
    )
    with pytest.raises(ToolError, match="Legality contract failed"):
        await mcp_client_authed.call_tool("plan_rollout", {"item_ids": [item_id]})


async def test_plan_rollout_mcp_dispatch_not_configured_raises_tool_error(
    mcp_client_authed, user_id
):
    """ToolError is raised when dispatch service is not configured."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    # No dispatch config → ValidationError → ToolError
    with pytest.raises(ToolError, match="not configured"):
        await mcp_client_authed.call_tool("plan_rollout", {"item_ids": [item_id]})


async def test_plan_rollout_mcp_planner_failure_updates_wave_run_failed(
    mcp_client_authed, user_id
):
    """When the planner HTTP call fails, wave run is set to 'failed'."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    with (
        patch(
            "agent_gtd.services.rollout_service.call_planner",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ),
        pytest.raises(ToolError),
    ):
        await mcp_client_authed.call_tool("plan_rollout", {"item_ids": [item_id]})

    db = await get_db()
    rows = await db.fetch(
        "SELECT status, halt_reason FROM autonomous_rollouts WHERE project_id = $1",
        project_id,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "Connection refused" in str(rows[0]["halt_reason"])


# ---------------------------------------------------------------------------
# No DB rows on legality failure (acceptance-criteria check)
# ---------------------------------------------------------------------------


async def test_plan_rollout_mcp_no_db_rows_on_legality_failure(
    mcp_client_authed, user_id
):
    """No autonomous_rollouts rows are written when legality contract fails."""
    project_id = await _create_project(user_id)
    # Insert an item without structured fields — legality will reject it
    db = await get_db()
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        item_id,
        project_id,
        user_id,
        "Invalid item",
        "No structured fields set",
        "ready",
        encode_json_list([]),
        NOW,
        NOW,
    )

    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool("plan_rollout", {"item_ids": [item_id]})

    rows = await db.fetch("SELECT id FROM autonomous_rollouts")
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# cancel_rollout MCP tool tests
# ---------------------------------------------------------------------------


async def _create_wave_run(
    user_id: str,
    project_id: str,
    status: str = "pending",
) -> str:
    """Insert a wave run row and return its ID."""
    db = await get_db()
    wave_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        wave_id,
        project_id,
        user_id,
        status,
        NOW,
        NOW,
    )
    return wave_id


async def test_cancel_rollout_happy_path(mcp_client_authed, user_id):
    """cancel_rollout on a pending wave returns status='cancelled'."""
    project_id = await _create_project(user_id)
    wave_id = await _create_wave_run(user_id, project_id, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool(
            "cancel_rollout",
            {"rollout_id": wave_id, "reason": "test_cancel"},
        )
    )
    assert result["status"] == "cancelled"
    assert result["id"] == wave_id


async def test_cancel_rollout_not_found(mcp_client_authed):
    """cancel_rollout with unknown ID raises ToolError."""
    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool(
            "cancel_rollout",
            {"rollout_id": str(uuid.uuid4()), "reason": "ghost"},
        )


# ---------------------------------------------------------------------------
# Helper: insert a rollout plan row
# ---------------------------------------------------------------------------


async def _insert_rollout_plan(
    rollout_id: str,
    item_ids: list[str],
    edges: list[dict[str, str]] | None = None,
    version: int = 1,
    planner_model: str = "test-model",
) -> None:
    """Insert a rollout_plans row for testing get_rollout_plan."""
    db = await get_db()
    plan_id = str(uuid.uuid4())
    nodes_json = json.dumps(item_ids)
    edges_json = json.dumps(edges or [])
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        version,
        nodes_json,
        edges_json,
        planner_model,
        NOW,
    )


async def _insert_rollout_item(
    rollout_id: str,
    item_id: str,
    status: str = "pending",
) -> None:
    """Insert a rollout_items row for testing."""
    db = await get_db()
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status) VALUES ($1, $2, $3)",
        rollout_id,
        item_id,
        status,
    )


# ---------------------------------------------------------------------------
# get_rollout tests
# ---------------------------------------------------------------------------


async def test_get_rollout_happy_path(mcp_client_authed, user_id):
    """get_rollout returns correct fields for a known rollout."""
    project_id = await _create_project(user_id)
    wave_id = await _create_wave_run(user_id, project_id, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool("get_rollout", {"rollout_id": wave_id})
    )

    assert result["id"] == wave_id
    assert result["project_id"] == project_id
    assert result["status"] == "pending"
    assert result["lead_user_id"] == user_id


async def test_get_rollout_not_found(mcp_client_authed):
    """get_rollout with unknown ID raises ToolError."""
    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool(
            "get_rollout", {"rollout_id": str(uuid.uuid4())}
        )


async def test_get_rollout_wrong_owner(mcp_client_authed):
    """get_rollout raises ToolError if rollout belongs to a different user."""
    db = await get_db()
    # Create a rollout owned by a different user
    other_user = await register_user("other-rollout@example.com", "testpass123")
    other_project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        other_project_id,
        other_user.id,
        "Other Project",
        NOW,
        NOW,
    )
    other_wave_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        other_wave_id,
        other_project_id,
        other_user.id,
        "pending",
        NOW,
        NOW,
    )

    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool("get_rollout", {"rollout_id": other_wave_id})


# ---------------------------------------------------------------------------
# list_rollouts tests
# ---------------------------------------------------------------------------


async def test_list_rollouts_empty(mcp_client_authed, user_id):
    """list_rollouts returns an empty list when the user has no rollouts."""
    result = _parse_result(await mcp_client_authed.call_tool("list_rollouts", {}))
    assert result == []


async def test_list_rollouts_returns_own_rollouts(mcp_client_authed, user_id):
    """list_rollouts returns rollouts owned by the caller."""
    project_id = await _create_project(user_id)
    wave_id_1 = await _create_wave_run(user_id, project_id, status="pending")
    wave_id_2 = await _create_wave_run(user_id, project_id, status="running")

    result = _parse_result(await mcp_client_authed.call_tool("list_rollouts", {}))
    ids = [r["id"] for r in result]
    assert wave_id_1 in ids
    assert wave_id_2 in ids


async def test_list_rollouts_filters_by_status(mcp_client_authed, user_id):
    """list_rollouts(status=...) returns only rollouts with that status."""
    project_id = await _create_project(user_id)
    running_id = await _create_wave_run(user_id, project_id, status="running")
    await _create_wave_run(user_id, project_id, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool("list_rollouts", {"status": "running"})
    )
    ids = [r["id"] for r in result]
    assert running_id in ids
    assert all(r["status"] == "running" for r in result)


async def test_list_rollouts_filters_by_project_id(mcp_client_authed, user_id):
    """list_rollouts(project_id=...) returns only rollouts for that project."""
    project_a = await _create_project(user_id)
    project_b = await _create_project(user_id)
    wave_a = await _create_wave_run(user_id, project_a, status="pending")
    await _create_wave_run(user_id, project_b, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool("list_rollouts", {"project_id": project_a})
    )
    ids = [r["id"] for r in result]
    assert wave_a in ids
    assert all(r["project_id"] == project_a for r in result)


async def test_list_rollouts_respects_limit(mcp_client_authed, user_id):
    """list_rollouts respects the limit parameter."""
    project_id = await _create_project(user_id)
    for _ in range(5):
        await _create_wave_run(user_id, project_id, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool("list_rollouts", {"limit": 2})
    )
    assert len(result) == 2


async def test_list_rollouts_does_not_return_other_users_rollouts(
    mcp_client_authed, user_id
):
    """list_rollouts does not include rollouts owned by other users."""
    db = await get_db()
    other_user = await register_user("other-list@example.com", "testpass123")
    other_project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        other_project_id,
        other_user.id,
        "Other Project",
        NOW,
        NOW,
    )
    other_wave_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        other_wave_id,
        other_project_id,
        other_user.id,
        "pending",
        NOW,
        NOW,
    )

    result = _parse_result(await mcp_client_authed.call_tool("list_rollouts", {}))
    ids = [r["id"] for r in result]
    assert other_wave_id not in ids


# ---------------------------------------------------------------------------
# get_rollout_plan tests
# ---------------------------------------------------------------------------


async def test_get_rollout_plan_happy_path(mcp_client_authed, user_id):
    """get_rollout_plan returns nodes, edges, and items with titles."""
    project_id = await _create_project(user_id)
    item_a = await _create_ready_item(user_id, project_id, title="Item A")
    item_b = await _create_ready_item(user_id, project_id, title="Item B")
    wave_id = await _create_wave_run(user_id, project_id)
    edges = [{"from_item_id": item_a, "to_item_id": item_b}]
    await _insert_rollout_plan(wave_id, [item_a, item_b], edges=edges)
    await _insert_rollout_item(wave_id, item_a, status="completed")
    await _insert_rollout_item(wave_id, item_b, status="dispatched")

    result = _parse_result(
        await mcp_client_authed.call_tool("get_rollout_plan", {"rollout_id": wave_id})
    )

    assert result["rollout_id"] == wave_id
    assert result["plan_version"] == 1
    assert result["planner_model"] == "test-model"
    assert set(result["nodes"]) == {item_a, item_b}
    assert result["edges"] == edges

    item_map = {i["item_id"]: i for i in result["items"]}
    assert item_map[item_a]["title"] == "Item A"
    assert item_map[item_a]["rollout_status"] == "completed"
    assert item_map[item_a]["predecessors"] == []
    assert item_map[item_b]["title"] == "Item B"
    assert item_map[item_b]["rollout_status"] == "dispatched"
    assert item_map[item_b]["predecessors"] == [item_a]


async def test_get_rollout_plan_not_found(mcp_client_authed):
    """get_rollout_plan with unknown rollout ID raises ToolError."""
    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool(
            "get_rollout_plan", {"rollout_id": str(uuid.uuid4())}
        )


async def test_get_rollout_plan_no_plan_yet(mcp_client_authed, user_id):
    """get_rollout_plan raises ToolError when rollout has no plan yet."""
    project_id = await _create_project(user_id)
    wave_id = await _create_wave_run(user_id, project_id)

    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool("get_rollout_plan", {"rollout_id": wave_id})
