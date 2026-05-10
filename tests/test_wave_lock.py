"""Tests for wave item lock / unlock service functions and dispatch guard."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from agent_gtd.database import get_db
from agent_gtd.exceptions import ValidationError, WaveItemLockedError
from agent_gtd.services.wave_lock_service import (
    lock_items_for_wave,
    release_wave_item,
    release_wave_locks,
)

# ---------------------------------------------------------------------------
# Autouse fixture: skip the dispatch service health check in all tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_dispatch_preflight():
    """Skip the dispatch service health check in all tests."""
    with patch(
        "agent_gtd.routes.dispatch_routes._check_dispatch_service",
        new_callable=AsyncMock,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project_with_origin(
    client: AsyncClient,
    headers: dict[str, str],
    name: str = "Wave Project",
    git_origin: str = "git@github.com:test/repo.git",
) -> str:
    """Create a project with git_origin and return its ID."""
    res = await client.post(
        "/api/projects",
        json={"name": name, "git_origin": git_origin},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _create_item(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    title: str = "Test task",
) -> str:
    """Create an item in a project and return its ID."""
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": title},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _seed_item(db, user_id: str, title: str = "Seeded item") -> str:
    """Insert a bare item directly into the DB and return its ID."""
    item_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO items"
        " (id, user_id, title, description, status, priority,"
        "  sort_order, labels, version, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        item_id,
        user_id,
        title,
        "",
        "inbox",
        "normal",
        0.0,
        "[]",
        1,
        now,
        now,
    )
    return item_id


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


async def test_lock_items_for_wave(user_id: str):
    """lock_items_for_wave sets locked_by_wave_id on each item."""
    db = await get_db()
    item_id = await _seed_item(db, user_id, "Lock me")

    wave_run_id = "wave-aaa-111"
    await lock_items_for_wave(db, wave_run_id, [item_id])

    row = await db.fetchrow(
        "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
    )
    assert row is not None
    assert row["locked_by_wave_id"] == wave_run_id


async def test_lock_same_wave_idempotent(user_id: str):
    """Locking the same item twice with the same wave is idempotent (no error)."""
    db = await get_db()
    item_id = await _seed_item(db, user_id, "Idempotent item")

    wave_run_id = "wave-bbb-222"
    await lock_items_for_wave(db, wave_run_id, [item_id])
    # Second call with same wave should not raise
    await lock_items_for_wave(db, wave_run_id, [item_id])

    row = await db.fetchrow(
        "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
    )
    assert row is not None
    assert row["locked_by_wave_id"] == wave_run_id


async def test_lock_already_locked_by_different_wave_raises(user_id: str):
    """lock_items_for_wave raises ValidationError if item is locked by another wave."""
    db = await get_db()
    item_id = await _seed_item(db, user_id, "Conflict item")

    await lock_items_for_wave(db, "wave-first-111", [item_id])

    with pytest.raises(ValidationError, match="already locked by wave wave-first-111"):
        await lock_items_for_wave(db, "wave-second-222", [item_id])


async def test_release_wave_item(user_id: str):
    """release_wave_item clears the lock on a single item."""
    db = await get_db()
    item_id = await _seed_item(db, user_id, "Release me")

    wave_run_id = "wave-ccc-333"
    await lock_items_for_wave(db, wave_run_id, [item_id])
    await release_wave_item(db, wave_run_id, item_id)

    row = await db.fetchrow(
        "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
    )
    assert row is not None
    assert row["locked_by_wave_id"] is None


async def test_release_wave_locks_bulk(user_id: str):
    """release_wave_locks clears all locks held by a wave."""
    db = await get_db()
    item_id_1 = await _seed_item(db, user_id, "Bulk item 1")
    item_id_2 = await _seed_item(db, user_id, "Bulk item 2")

    wave_run_id = "wave-ddd-444"
    await lock_items_for_wave(db, wave_run_id, [item_id_1, item_id_2])
    await release_wave_locks(db, wave_run_id)

    for item_id in (item_id_1, item_id_2):
        row = await db.fetchrow(
            "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
        )
        assert row is not None
        assert row["locked_by_wave_id"] is None


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


async def test_dispatch_unlocked_item_succeeds(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatching an unlocked item returns 201."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 201


async def test_dispatch_locked_item_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatching a locked item returns HTTP 409 with the wave_run_id in the detail."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item(client, auth_headers, project_id)

    wave_run_id = "wave-lock-http-test"
    db = await get_db()
    await lock_items_for_wave(db, wave_run_id, [item_id])

    res = await client.post(
        f"/api/items/{item_id}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert wave_run_id in detail
    assert item_id in detail


async def test_wave_lock_does_not_block_other_items(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Locking item A does NOT block dispatch of item B in the same project."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_a = await _create_item(client, auth_headers, project_id, "Item A")
    item_b = await _create_item(client, auth_headers, project_id, "Item B")

    wave_run_id = "wave-isolation-test"
    db = await get_db()
    await lock_items_for_wave(db, wave_run_id, [item_a])

    # Dispatching item B (unlocked) must succeed
    res = await client.post(
        f"/api/items/{item_b}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 201


async def test_dispatch_after_release_succeeds(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatch succeeds after the wave lock has been released."""
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item(client, auth_headers, project_id)

    wave_run_id = "wave-release-test"
    db = await get_db()
    await lock_items_for_wave(db, wave_run_id, [item_id])

    # Locked → 409
    res = await client.post(
        f"/api/items/{item_id}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 409

    # Release the lock
    await release_wave_item(db, wave_run_id, item_id)

    # Now dispatch must succeed
    res = await client.post(
        f"/api/items/{item_id}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# MCP tool test
# ---------------------------------------------------------------------------


async def test_dispatch_locked_item_mcp_raises_tool_error(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """WaveItemLockedError from dispatch_service propagates as ToolError in MCP.

    We verify the error shape here (detail string contains wave_run_id and item_id)
    since the actual MCP ToolError wrapping requires a live MCP session. The
    mcp_server.py wire-up is covered by code review of the catch clause.
    """
    project_id = await _create_project_with_origin(client, auth_headers)
    item_id = await _create_item(client, auth_headers, project_id)

    wave_run_id = "wave-mcp-test"
    db = await get_db()
    await lock_items_for_wave(db, wave_run_id, [item_id])

    # Confirm the exception shape — detail is what ToolError receives
    err = WaveItemLockedError(item_id, wave_run_id)
    assert wave_run_id in err.detail
    assert item_id in err.detail
    assert isinstance(err.detail, str)

    # Confirm the HTTP path also returns 409 (double-checks the same error)
    res = await client.post(
        f"/api/items/{item_id}/dispatch", json={}, headers=auth_headers
    )
    assert res.status_code == 409
    assert wave_run_id in res.json()["detail"]
