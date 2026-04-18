"""Tests for the app settings API.

Covers the dispatch concurrency cap and per-user dispatch configuration.
"""

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


# ---------------------------------------------------------------------------
# Per-user dispatch config (GET/PATCH /api/settings/dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dispatch_settings_defaults(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /api/settings/dispatch returns defaults when nothing is configured."""
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["engine"] == "claude"
    assert data["agent_name"] == ""
    assert data["max_concurrent"] == 6
    assert data["service_url"] == ""
    assert data["service_api_key_configured"] is False


@pytest.mark.asyncio
async def test_get_dispatch_settings_never_leaks_api_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /api/settings/dispatch never returns the actual api_key value."""
    # Configure a key
    await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "https://dispatch.example.com",
            "service_api_key": "super-secret-key",
        },
        headers=auth_headers,
    )

    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()

    # Key presence is indicated by the boolean, never exposed directly
    assert "service_api_key" not in data or data.get("service_api_key") is None
    assert data["service_api_key_configured"] is True
    assert "super-secret-key" not in str(data)


@pytest.mark.asyncio
async def test_patch_dispatch_settings_service_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /api/settings/dispatch updates service_url per user."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://dispatch.example.com"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["service_url"] == "https://dispatch.example.com"
    assert data["service_api_key_configured"] is False  # key not set yet


@pytest.mark.asyncio
async def test_patch_dispatch_settings_api_key_shows_configured(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH with service_api_key sets configured=True without leaking the value."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "https://dispatch.example.com",
            "service_api_key": "my-secret",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["service_api_key_configured"] is True
    assert "my-secret" not in str(data)


@pytest.mark.asyncio
async def test_patch_dispatch_settings_updates_user_settings_not_app_settings(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /api/settings/dispatch stores in user_settings, not app_settings."""
    from agent_gtd.database import get_db

    res = await client.get("/api/auth/me", headers=auth_headers)
    uid = res.json()["id"]

    await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "https://per-user.example.com",
            "service_api_key": "user-key",
        },
        headers=auth_headers,
    )

    db = await get_db()

    # Should be in user_settings
    row = await db.fetchrow(
        "SELECT value FROM user_settings WHERE user_id = $1 AND key = $2",
        uid,
        "dispatch.service_url",
    )
    assert row is not None
    assert row["value"] == "https://per-user.example.com"

    key_row = await db.fetchrow(
        "SELECT value FROM user_settings WHERE user_id = $1 AND key = $2",
        uid,
        "dispatch.service_api_key",
    )
    assert key_row is not None
    assert key_row["value"] == "user-key"

    # Should NOT be in app_settings
    app_row = await db.fetchrow(
        "SELECT value FROM app_settings WHERE key = $1",
        "dispatch.service_url",
    )
    assert app_row is None


@pytest.mark.asyncio
async def test_patch_dispatch_settings_partial_update(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH with only one field leaves the other unchanged."""
    # Set both fields
    await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "https://original.example.com",
            "service_api_key": "original-key",
        },
        headers=auth_headers,
    )

    # Update only the URL
    res = await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://updated.example.com"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["service_url"] == "https://updated.example.com"
    # API key should still be configured
    assert data["service_api_key_configured"] is True


@pytest.mark.asyncio
async def test_dispatch_config_is_per_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Each user has independent dispatch config; one user's settings don't leak."""
    # Register User B
    res_b = await client.post(
        "/api/auth/register",
        json={"email": "userb_settings@example.com", "password": "passb"},
    )
    user_b_headers = {"Authorization": f"Bearer {res_b.json()['token']}"}

    # User A configures dispatch
    await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://user-a.example.com", "service_api_key": "a-key"},
        headers=auth_headers,
    )

    # User B has no config
    res_b_get = await client.get("/api/settings/dispatch", headers=user_b_headers)
    assert res_b_get.status_code == 200
    data_b = res_b_get.json()
    assert data_b["service_url"] == ""
    assert data_b["service_api_key_configured"] is False


@pytest.mark.asyncio
async def test_get_dispatch_settings_unauthenticated(client: AsyncClient) -> None:
    """GET /api/settings/dispatch without auth returns 401."""
    res = await client.get("/api/settings/dispatch")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_patch_dispatch_settings_unauthenticated(client: AsyncClient) -> None:
    """PATCH /api/settings/dispatch without auth returns 401."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://example.com"},
    )
    assert res.status_code == 401
