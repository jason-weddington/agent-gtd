"""Integration tests for the plan_wave MCP tool (happy path and error cases)."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_gtd.auth import generate_api_key, hash_api_key, register_user
from agent_gtd.database import encode_json_list, get_db
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
- src/agent_gtd/services/wave_service.py
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
    description: str = VALID_DESC,
) -> str:
    """Insert a ready item with a valid description and return its ID."""
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
        title,
        description,
        "ready",
        encode_json_list([]),
        NOW,
        NOW,
    )
    return item_id


# ---------------------------------------------------------------------------
# Happy path — single item, no edges
# ---------------------------------------------------------------------------


async def test_plan_wave_happy_path_single_item(mcp_client_authed, user_id):
    """plan_wave with one valid item and mocked planner returns a pending wave run."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan_response = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.wave_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan_response,
    ):
        result = await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})

    data = _parse_result(result)

    assert data["status"] == "pending"
    assert data["wave_run_id"] is not None
    assert data["item_count"] == 1
    assert data["planner_model"] == "claude-sonnet-4-6"
    assert data["plan"]["nodes"] == [item_id]
    assert data["plan"]["edges"] == []
    assert len(data["per_item"]) == 1

    per = data["per_item"][0]
    assert per["item_id"] == item_id
    assert per["title"] == "Wave item"
    assert per["predecessors"] == []


async def test_plan_wave_happy_path_two_items_with_edge(mcp_client_authed, user_id):
    """plan_wave with two items and an edge correctly sets in-degree statuses."""
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
        "agent_gtd.services.wave_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan_response,
    ):
        result = await mcp_client_authed.call_tool(
            "plan_wave", {"item_ids": [item_a, item_b]}
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
    wave_run_id = data["wave_run_id"]
    row_a = await db.fetchrow(
        "SELECT status FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_a,
    )
    row_b = await db.fetchrow(
        "SELECT status FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_b,
    )
    assert row_a is not None
    assert row_a["status"] == "ready"
    assert row_b is not None
    assert row_b["status"] == "pending"


# ---------------------------------------------------------------------------
# DB state after happy path
# ---------------------------------------------------------------------------


async def test_plan_wave_inserts_wave_run_as_pending(mcp_client_authed, user_id):
    """After plan_wave, the wave run is stored with status=pending."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.wave_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        result = await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})

    data = _parse_result(result)
    wave_run_id = data["wave_run_id"]

    db = await get_db()
    row = await db.fetchrow(
        "SELECT status, project_id, lead_user_id "
        "FROM autonomous_wave_runs WHERE id = $1",
        wave_run_id,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["project_id"] == project_id
    assert row["lead_user_id"] == user_id


async def test_plan_wave_inserts_wave_plan(mcp_client_authed, user_id):
    """After plan_wave, a wave_plans row is persisted with nodes and edges."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    mock_plan = {
        "nodes": [item_id],
        "edges": [],
        "planner_model": "claude-sonnet-4-6",
    }

    with patch(
        "agent_gtd.services.wave_service.call_planner",
        new_callable=AsyncMock,
        return_value=mock_plan,
    ):
        result = await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})

    data = _parse_result(result)
    wave_run_id = data["wave_run_id"]

    db = await get_db()
    plan_row = await db.fetchrow(
        "SELECT version, nodes, edges, planner_model "
        "FROM wave_plans WHERE wave_run_id = $1",
        wave_run_id,
    )
    assert plan_row is not None
    assert plan_row["version"] == 1
    assert json.loads(plan_row["nodes"]) == [item_id]
    assert json.loads(plan_row["edges"]) == []
    assert plan_row["planner_model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Error cases via MCP tool
# ---------------------------------------------------------------------------


async def test_plan_wave_mcp_empty_item_ids_raises_tool_error(
    mcp_client_authed, user_id
):
    """Empty item_ids raises ToolError via the MCP tool."""
    with pytest.raises(ToolError, match="empty"):
        await mcp_client_authed.call_tool("plan_wave", {"item_ids": []})


async def test_plan_wave_mcp_legality_failure_raises_tool_error(
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
        await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})


async def test_plan_wave_mcp_dispatch_not_configured_raises_tool_error(
    mcp_client_authed, user_id
):
    """ToolError is raised when dispatch service is not configured."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    # No dispatch config → ValidationError → ToolError
    with pytest.raises(ToolError, match="not configured"):
        await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})


async def test_plan_wave_mcp_planner_failure_updates_wave_run_failed(
    mcp_client_authed, user_id
):
    """When the planner HTTP call fails, wave run is set to 'failed'."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(user_id, project_id)
    await _configure_dispatch(user_id, "http://dispatch.test:8100", "test-api-key")

    with (
        patch(
            "agent_gtd.services.wave_service.call_planner",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ),
        pytest.raises(ToolError),
    ):
        await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})

    db = await get_db()
    rows = await db.fetch(
        "SELECT status, halt_reason FROM autonomous_wave_runs WHERE project_id = $1",
        project_id,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "Connection refused" in str(rows[0]["halt_reason"])


# ---------------------------------------------------------------------------
# No DB rows on legality failure (acceptance-criteria check)
# ---------------------------------------------------------------------------


async def test_plan_wave_mcp_no_db_rows_on_legality_failure(mcp_client_authed, user_id):
    """No autonomous_wave_runs rows are written when legality contract fails."""
    project_id = await _create_project(user_id)
    item_id = await _create_ready_item(
        user_id,
        project_id,
        description="No acceptance criteria here",
    )

    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool("plan_wave", {"item_ids": [item_id]})

    db = await get_db()
    rows = await db.fetch("SELECT id FROM autonomous_wave_runs")
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# cancel_wave MCP tool tests
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
        "INSERT INTO autonomous_wave_runs"
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


async def test_cancel_wave_happy_path(mcp_client_authed, user_id):
    """cancel_wave on a pending wave returns status='cancelled'."""
    project_id = await _create_project(user_id)
    wave_id = await _create_wave_run(user_id, project_id, status="pending")

    result = _parse_result(
        await mcp_client_authed.call_tool(
            "cancel_wave",
            {"wave_run_id": wave_id, "reason": "test_cancel"},
        )
    )
    assert result["status"] == "cancelled"
    assert result["id"] == wave_id


async def test_cancel_wave_not_found(mcp_client_authed):
    """cancel_wave with unknown ID raises ToolError."""
    with pytest.raises(ToolError):
        await mcp_client_authed.call_tool(
            "cancel_wave",
            {"wave_run_id": str(uuid.uuid4()), "reason": "ghost"},
        )
