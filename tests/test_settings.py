"""Tests for the app settings API (dispatch concurrency cap)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_max_concurrent_default(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET returns 6 when no DB row or env var override is present."""
    res = await client.get(
        "/api/settings/dispatch/max-concurrent",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"value": 6}


@pytest.mark.asyncio
async def test_get_max_concurrent_env_var(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET falls back to DISPATCH_MAX_CONCURRENT env var when no DB row."""
    monkeypatch.setenv("DISPATCH_MAX_CONCURRENT", "4")
    res = await client.get(
        "/api/settings/dispatch/max-concurrent",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"value": 4}


@pytest.mark.asyncio
async def test_set_and_get_max_concurrent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH persists the value; subsequent GET returns it."""
    patch_res = await client.patch(
        "/api/settings/dispatch/max-concurrent",
        json={"value": 10},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json() == {"value": 10}

    get_res = await client.get(
        "/api/settings/dispatch/max-concurrent",
        headers=auth_headers,
    )
    assert get_res.status_code == 200
    assert get_res.json() == {"value": 10}


@pytest.mark.asyncio
async def test_set_max_concurrent_overrides_env_var(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB value takes precedence over DISPATCH_MAX_CONCURRENT env var."""
    monkeypatch.setenv("DISPATCH_MAX_CONCURRENT", "3")

    await client.patch(
        "/api/settings/dispatch/max-concurrent",
        json={"value": 8},
        headers=auth_headers,
    )

    get_res = await client.get(
        "/api/settings/dispatch/max-concurrent",
        headers=auth_headers,
    )
    assert get_res.status_code == 200
    assert get_res.json() == {"value": 8}


@pytest.mark.asyncio
async def test_patch_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Patching the same value twice is idempotent (upsert behaviour)."""
    for _ in range(2):
        res = await client.patch(
            "/api/settings/dispatch/max-concurrent",
            json={"value": 5},
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert res.json() == {"value": 5}


@pytest.mark.asyncio
async def test_patch_value_too_low(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH rejects value < 1."""
    res = await client.patch(
        "/api/settings/dispatch/max-concurrent",
        json={"value": 0},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_value_too_high(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH rejects value > 20."""
    res = await client.patch(
        "/api/settings/dispatch/max-concurrent",
        json={"value": 21},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_boundary_values(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH accepts boundary values 1 and 20."""
    for v in (1, 20):
        res = await client.patch(
            "/api/settings/dispatch/max-concurrent",
            json={"value": v},
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert res.json() == {"value": v}


@pytest.mark.asyncio
async def test_unauthenticated_get_rejected(client: AsyncClient) -> None:
    """GET without auth token returns 401."""
    res = await client.get("/api/settings/dispatch/max-concurrent")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_patch_rejected(client: AsyncClient) -> None:
    """PATCH without auth token returns 401."""
    res = await client.patch(
        "/api/settings/dispatch/max-concurrent",
        json={"value": 5},
    )
    assert res.status_code == 401
