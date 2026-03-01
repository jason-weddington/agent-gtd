"""REST API optimistic locking tests for PATCH /items/{id}."""

import pytest
from httpx import AsyncClient


@pytest.fixture
async def item_id(client: AsyncClient, auth_headers, project_id):
    res = await client.post(
        "/api/items",
        json={"title": "Lockable Item", "project_id": project_id},
        headers=auth_headers,
    )
    return res.json()["id"]


async def test_patch_with_correct_version_succeeds(
    client: AsyncClient, auth_headers, item_id
):
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "Updated", "version": 1},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["title"] == "Updated"
    assert res.json()["version"] == 2


async def test_patch_with_wrong_version_returns_409(
    client: AsyncClient, auth_headers, item_id
):
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "Should Fail", "version": 99},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert "conflict" in res.json()["detail"].lower()


async def test_patch_without_version_still_works(
    client: AsyncClient, auth_headers, item_id
):
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "No Version Needed"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["title"] == "No Version Needed"
    assert res.json()["version"] == 2


async def test_patch_version_increments_correctly(
    client: AsyncClient, auth_headers, item_id
):
    # First update
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "V2", "version": 1},
        headers=auth_headers,
    )
    assert res.json()["version"] == 2

    # Second update with new version
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "V3", "version": 2},
        headers=auth_headers,
    )
    assert res.json()["version"] == 3

    # Stale version should fail
    res = await client.patch(
        f"/api/items/{item_id}",
        json={"title": "Stale", "version": 1},
        headers=auth_headers,
    )
    assert res.status_code == 409
