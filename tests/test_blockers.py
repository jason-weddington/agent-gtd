"""Tests for blocker add/remove/list API endpoints."""

import pytest
from httpx import AsyncClient


async def _create_item(
    client: AsyncClient, auth_headers: dict[str, str], title: str = "Item"
) -> str:
    """Helper: create an item and return its ID."""
    res = await client.post("/api/items", json={"title": title}, headers=auth_headers)
    assert res.status_code == 201
    return res.json()["id"]


# ---------------------------------------------------------------------------
# add_blocker
# ---------------------------------------------------------------------------


async def test_add_blocker_success(client: AsyncClient, auth_headers: dict[str, str]):
    item_id = await _create_item(client, auth_headers, "Task A")
    blocker_id = await _create_item(client, auth_headers, "Blocker B")

    res = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["id"] == blocker_id
    assert data["title"] == "Blocker B"
    assert data["status"] == "inbox"
    assert data["project_id"] is None
    assert data["project_name"] is None


async def test_add_blocker_with_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Blocker summary includes project info when the blocker is in a project."""
    # Create blocker item in a project
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Blocker in project"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    blocker_id = res.json()["id"]

    item_id = await _create_item(client, auth_headers, "Needs blocker")

    res = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == project_id
    assert data["project_name"] == "Test Project"


async def test_add_blocker_rejects_self_block(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """An item cannot block itself — service validates this and returns 400."""
    item_id = await _create_item(client, auth_headers, "Solo item")

    res = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": item_id},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "itself" in res.json()["detail"]


async def test_add_blocker_rejects_2_step_cycle(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A→B, then B→A must be rejected (2-step cycle)."""
    a = await _create_item(client, auth_headers, "A")
    b = await _create_item(client, auth_headers, "B")

    # A is blocked by B (B blocks A)
    res = await client.post(
        f"/api/items/{a}/blockers",
        json={"blocker_item_id": b},
        headers=auth_headers,
    )
    assert res.status_code == 201

    # Now try to make B blocked by A — would create A←B←A cycle
    res = await client.post(
        f"/api/items/{b}/blockers",
        json={"blocker_item_id": a},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "cycle" in res.json()["detail"]


async def test_add_blocker_rejects_3_step_cycle(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A→B, B→C, then C→A must be rejected (3-step cycle)."""
    a = await _create_item(client, auth_headers, "A")
    b = await _create_item(client, auth_headers, "B")
    c = await _create_item(client, auth_headers, "C")

    # A is blocked by B
    res = await client.post(
        f"/api/items/{a}/blockers",
        json={"blocker_item_id": b},
        headers=auth_headers,
    )
    assert res.status_code == 201

    # B is blocked by C
    res = await client.post(
        f"/api/items/{b}/blockers",
        json={"blocker_item_id": c},
        headers=auth_headers,
    )
    assert res.status_code == 201

    # Now try C is blocked by A — would complete the cycle A←B←C←A
    res = await client.post(
        f"/api/items/{c}/blockers",
        json={"blocker_item_id": a},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "cycle" in res.json()["detail"]


async def test_add_blocker_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Adding the same blocker twice returns 201 silently — idempotent."""
    item_id = await _create_item(client, auth_headers, "Task")
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    res1 = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res1.status_code == 201

    # Second call — idempotent, returns same blocker summary
    res2 = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res2.status_code == 201
    assert res2.json()["id"] == blocker_id


async def test_add_blocker_404_if_item_not_owned(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Returns 404 if item_id doesn't exist or isn't owned by user."""
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    res = await client.post(
        "/api/items/nonexistent-id/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_add_blocker_404_if_blocker_not_owned(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Returns 404 if blocker_item_id doesn't exist or isn't owned by user — no leak."""
    item_id = await _create_item(client, auth_headers, "Task")

    # Register a second user and create an item as them
    res = await client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "otherpass"},
    )
    other_token = res.json()["token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}
    other_item_res = await client.post(
        "/api/items", json={"title": "Other user item"}, headers=other_headers
    )
    other_item_id = other_item_res.json()["id"]

    # First user tries to use other user's item as blocker
    res = await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": other_item_id},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# list_blockers
# ---------------------------------------------------------------------------


async def test_list_blockers_returns_summary_with_project_info(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """list_blockers returns joined summary including project info."""
    # Blocker in a project
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Blocker task"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    blocker_id = res.json()["id"]

    item_id = await _create_item(client, auth_headers, "Main task")

    # Add blocker
    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    res = await client.get(f"/api/items/{item_id}/blockers", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == blocker_id
    assert items[0]["title"] == "Blocker task"
    assert items[0]["project_id"] == project_id
    assert items[0]["project_name"] == "Test Project"


async def test_list_blockers_empty(client: AsyncClient, auth_headers: dict[str, str]):
    """list_blockers returns empty list for item with no blockers."""
    item_id = await _create_item(client, auth_headers, "No blockers here")

    res = await client.get(f"/api/items/{item_id}/blockers", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_list_blockers_404_for_unknown_item(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.get("/api/items/nonexistent-id/blockers", headers=auth_headers)
    assert res.status_code == 404


async def test_list_blockers_multiple(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """list_blockers returns all blockers in insertion order."""
    item_id = await _create_item(client, auth_headers, "Main")
    b1 = await _create_item(client, auth_headers, "Blocker 1")
    b2 = await _create_item(client, auth_headers, "Blocker 2")

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": b1},
        headers=auth_headers,
    )
    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": b2},
        headers=auth_headers,
    )

    res = await client.get(f"/api/items/{item_id}/blockers", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert b1 in ids
    assert b2 in ids
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# remove_blocker
# ---------------------------------------------------------------------------


async def test_remove_blocker_success(
    client: AsyncClient, auth_headers: dict[str, str]
):
    item_id = await _create_item(client, auth_headers, "Task")
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    res = await client.delete(
        f"/api/items/{item_id}/blockers/{blocker_id}", headers=auth_headers
    )
    assert res.status_code == 204

    # Confirm it's gone
    list_res = await client.get(f"/api/items/{item_id}/blockers", headers=auth_headers)
    assert list_res.json() == []


async def test_remove_blocker_noop_if_not_exists(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """remove_blocker is a no-op if the dependency doesn't exist."""
    item_id = await _create_item(client, auth_headers, "Task")
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    # No blocker added — still returns 204
    res = await client.delete(
        f"/api/items/{item_id}/blockers/{blocker_id}", headers=auth_headers
    )
    assert res.status_code == 204


async def test_remove_blocker_404_for_unknown_item(
    client: AsyncClient, auth_headers: dict[str, str]
):
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    res = await client.delete(
        f"/api/items/nonexistent-id/blockers/{blocker_id}", headers=auth_headers
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# CASCADE on item delete
# ---------------------------------------------------------------------------


async def test_cascade_delete_blocker_removes_dependency(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Deleting the blocker item cascades and removes the dependency row."""
    item_id = await _create_item(client, auth_headers, "Main task")
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    # Delete the blocker item
    del_res = await client.delete(f"/api/items/{blocker_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # Dependency should be gone via CASCADE
    list_res = await client.get(f"/api/items/{item_id}/blockers", headers=auth_headers)
    assert list_res.status_code == 200
    assert list_res.json() == []


async def test_cascade_delete_blocked_item_removes_dependency(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Deleting the blocked item cascades and removes the dependency row."""
    item_id = await _create_item(client, auth_headers, "Main task")
    blocker_id = await _create_item(client, auth_headers, "Blocker")

    await client.post(
        f"/api/items/{item_id}/blockers",
        json={"blocker_item_id": blocker_id},
        headers=auth_headers,
    )

    # Delete the main (blocked) item
    del_res = await client.delete(f"/api/items/{item_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # Blocker item still exists but dependency is gone — verify via list on blocker
    list_res = await client.get(
        f"/api/items/{blocker_id}/blockers", headers=auth_headers
    )
    assert list_res.status_code == 200
    assert list_res.json() == []


@pytest.mark.parametrize(
    "non_cycle_scenario",
    [
        # A→B, A→C (diamond, no cycle)
        [("a", "b"), ("a", "c")],
        # A→B, C→B (two items block B, no cycle)
        [("a", "b"), ("c", "b")],
    ],
)
async def test_add_blocker_allows_non_cycle_fan(
    client: AsyncClient,
    auth_headers: dict[str, str],
    non_cycle_scenario: list[tuple[str, str]],
):
    """Non-cyclic graphs with multiple edges are allowed."""
    # Create items named a, b, c
    ids: dict[str, str] = {}
    for name in {"a", "b", "c"}:
        ids[name] = await _create_item(client, auth_headers, name)

    for item_key, blocker_key in non_cycle_scenario:
        res = await client.post(
            f"/api/items/{ids[item_key]}/blockers",
            json={"blocker_item_id": ids[blocker_key]},
            headers=auth_headers,
        )
        assert res.status_code == 201, (
            f"Expected 201 for {item_key}→{blocker_key}, "
            f"got {res.status_code}: {res.json()}"
        )
