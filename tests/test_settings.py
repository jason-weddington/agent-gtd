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
    assert data["service_api_key_preview"] == ""


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

    # Full key is never exposed; only a masked preview is returned
    assert "service_api_key" not in data or data.get("service_api_key") is None
    assert data["service_api_key_preview"] == "****-key"
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
    assert data["service_api_key_preview"] == ""  # key not set yet


@pytest.mark.asyncio
async def test_patch_dispatch_settings_api_key_shows_configured(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH with service_api_key returns masked preview without leaking the value."""
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
    # "my-secret" last 4 chars = "cret"
    assert data["service_api_key_preview"] == "****cret"
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
    # API key should still be previewed (not cleared)
    assert data["service_api_key_preview"] == "****-key"


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
    assert data_b["service_api_key_preview"] == ""


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


# ---------------------------------------------------------------------------
# service_api_key_preview field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dispatch_settings_preview_empty_when_no_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET returns service_api_key_preview='' when no key has been stored."""
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["service_api_key_preview"] == ""


@pytest.mark.asyncio
async def test_get_dispatch_settings_preview_last4_after_patch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET returns ****XXXX preview (last 4 chars of key) after PATCH stores a key."""
    await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "http://pironman01:8100",
            "service_api_key": "abcd1234XYZjL54",  # gitleaks:allow
        },
        headers=auth_headers,
    )
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["service_api_key_preview"] == "****jL54"
    # Full key must never appear anywhere in the response
    assert "abcd1234XYZjL54" not in str(data)


@pytest.mark.asyncio
async def test_get_dispatch_settings_preview_not_in_full_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET response never contains the full stored API key value."""
    fake_key = "my-top-secret-key-9999"  # gitleaks:allow
    await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://example.com", "service_api_key": fake_key},
        headers=auth_headers,
    )
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    assert fake_key not in str(res.json())


@pytest.mark.asyncio
async def test_patch_omit_key_leaves_preview_unchanged(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH without service_api_key leaves the existing key and preview unchanged."""
    # Store an initial key
    await client.patch(
        "/api/settings/dispatch",
        json={
            "service_url": "https://example.com",
            "service_api_key": "abcd1234XYZjL54",  # gitleaks:allow
        },
        headers=auth_headers,
    )
    first_res = await client.get("/api/settings/dispatch", headers=auth_headers)
    first_preview = first_res.json()["service_api_key_preview"]
    assert first_preview == "****jL54"

    # Patch only the URL — key should be untouched
    await client.patch(
        "/api/settings/dispatch",
        json={"service_url": "https://updated.example.com"},
        headers=auth_headers,
    )
    second_res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert second_res.json()["service_api_key_preview"] == first_preview


@pytest.mark.asyncio
async def test_get_user_setting_last4_returns_exactly_4_chars(
    auth_headers: dict[str, str],
    client: AsyncClient,
) -> None:
    """get_user_setting_last4 returns exactly 4 chars for a key longer than 4 chars."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    # Get the authenticated user's ID
    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]

    db = await get_db()

    # Store a 10-char value directly
    await settings_service.set_user_setting(
        db, uid, "dispatch.service_api_key", "1234567890"
    )

    last4 = await settings_service.get_user_setting_last4(
        db, uid, "dispatch.service_api_key"
    )
    assert last4 == "7890"
    assert len(last4) == 4


@pytest.mark.asyncio
async def test_get_user_setting_last4_returns_full_value_when_short(
    auth_headers: dict[str, str],
    client: AsyncClient,
) -> None:
    """get_user_setting_last4 returns the full value when it is shorter than 4 chars."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]
    db = await get_db()

    await settings_service.set_user_setting(db, uid, "dispatch.service_api_key", "ab")
    last4 = await settings_service.get_user_setting_last4(
        db, uid, "dispatch.service_api_key"
    )
    assert last4 == "ab"


@pytest.mark.asyncio
async def test_get_user_setting_last4_empty_when_missing(
    auth_headers: dict[str, str],
    client: AsyncClient,
) -> None:
    """get_user_setting_last4 returns '' when no value is stored."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]
    db = await get_db()

    result = await settings_service.get_user_setting_last4(
        db, uid, "dispatch.service_api_key"
    )
    assert result == ""


@pytest.mark.asyncio
async def test_get_user_setting_last4_not_full_value(
    auth_headers: dict[str, str],
    client: AsyncClient,
) -> None:
    """get_user_setting_last4 never returns the full value for a long key."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    me = await client.get("/api/auth/me", headers=auth_headers)
    uid = me.json()["id"]
    db = await get_db()

    full_key = "abcd1234XYZjL54"  # gitleaks:allow
    await settings_service.set_user_setting(
        db, uid, "dispatch.service_api_key", full_key
    )

    last4 = await settings_service.get_user_setting_last4(
        db, uid, "dispatch.service_api_key"
    )
    assert last4 == "jL54"
    assert last4 != full_key


# ---------------------------------------------------------------------------
# dispatch.default_max_turns persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dispatch_settings_default_max_turns_unset(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /api/settings/dispatch returns default_max_turns=100 when nothing is set."""
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["default_max_turns"] == 100


@pytest.mark.asyncio
async def test_get_dispatch_settings_default_max_turns_env_var(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/settings/dispatch falls back to DISPATCH_DEFAULT_MAX_TURNS env var."""
    monkeypatch.setenv("DISPATCH_DEFAULT_MAX_TURNS", "200")
    res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["default_max_turns"] == 200


@pytest.mark.asyncio
async def test_patch_dispatch_settings_default_max_turns(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH /api/settings/dispatch persists default_max_turns; GET returns it."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 250},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["default_max_turns"] == 250

    # Confirm it persists
    get_res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["default_max_turns"] == 250


@pytest.mark.asyncio
async def test_patch_dispatch_settings_default_max_turns_db_overrides_env(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisted value overrides DISPATCH_DEFAULT_MAX_TURNS env var."""
    monkeypatch.setenv("DISPATCH_DEFAULT_MAX_TURNS", "50")
    await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 300},
        headers=auth_headers,
    )
    get_res = await client.get("/api/settings/dispatch", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["default_max_turns"] == 300


@pytest.mark.asyncio
async def test_patch_dispatch_settings_default_max_turns_too_low(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH rejects default_max_turns < 10."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 9},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_dispatch_settings_default_max_turns_too_high(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH rejects default_max_turns > 500."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"default_max_turns": 501},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_dispatch_settings_default_max_turns_boundary(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH accepts boundary values 10 and 500."""
    for v in (10, 500):
        res = await client.patch(
            "/api/settings/dispatch",
            json={"default_max_turns": v},
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert res.json()["default_max_turns"] == v
