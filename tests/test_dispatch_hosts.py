"""Tests for dispatch host CRUD endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_dispatch_hosts_empty(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET returns empty list when no hosts configured."""
    res = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_add_dispatch_host(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST creates host; response has api_key_preview but never full key."""
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "pi-1",
            "url": "http://pi1.local:8001",
            "api_key": "super-secret-key",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["label"] == "pi-1"
    assert data["url"] == "http://pi1.local:8001"
    assert data["api_key_preview"] == "****-key"
    assert "super-secret-key" not in str(data)  # gitleaks:allow
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_dispatch_hosts_after_add(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET returns added host."""
    await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "host1",
            "url": "http://h1.local:8001",
            "api_key": "secret-full-api-key-abc123",
        },
        headers=auth_headers,
    )
    res = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["url"] == "http://h1.local:8001"
    # Full key must never appear in response (only last-4 preview is acceptable)
    assert "secret-full-api-key-abc123" not in str(data)  # gitleaks:allow


@pytest.mark.asyncio
async def test_delete_dispatch_host(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DELETE returns 204; subsequent GET returns empty list."""
    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "",
            "url": "http://host.local:8001",
            "api_key": "mykey",
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    del_res = await client.delete(
        f"/api/settings/dispatch/hosts/{host_id}", headers=auth_headers
    )
    assert del_res.status_code == 204

    list_res = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert list_res.json() == []


@pytest.mark.asyncio
async def test_delete_wrong_owner_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DELETE by non-owner returns 404."""
    from agent_gtd.auth import create_token, register_user

    # Add a host as user A
    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "",
            "url": "http://host.local:8001",
            "api_key": "keyA",
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    # User B tries to delete it
    user_b = await register_user("userb_hosts@example.com", "passb")
    headers_b = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    res = await client.delete(
        f"/api/settings/dispatch/hosts/{host_id}", headers=headers_b
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_add_duplicate_url_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST with duplicate URL for same user returns 409."""
    await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "first",
            "url": "http://same.local:8001",
            "api_key": "k1",
        },
        headers=auth_headers,
    )
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "second",
            "url": "http://same.local:8001",
            "api_key": "k2",
        },
        headers=auth_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_add_host_empty_url_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST with empty url returns 422."""
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={"label": "x", "url": "  ", "api_key": "key"},  # gitleaks:allow
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_add_host_empty_api_key_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST with empty api_key returns 422."""
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={"label": "x", "url": "http://host.local:8001", "api_key": ""},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_migration_from_legacy_user_settings(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """User with existing dispatch.service_url + service_api_key sees a default host."""
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import set_user_setting

    # Create a fresh user with legacy user_settings
    user = await register_user("legacy_user@example.com", "passw")
    headers = {"Authorization": f"Bearer {create_token(user.id)}"}
    db = await get_db()
    await set_user_setting(
        db, user.id, "dispatch.service_url", "http://legacy.local:8001"
    )
    await set_user_setting(
        db,
        user.id,
        "dispatch.service_api_key",
        "legacy-api-key",  # gitleaks:allow
    )

    res = await client.get("/api/settings/dispatch/hosts", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["label"] == "default"
    assert data[0]["url"] == "http://legacy.local:8001"
    assert "legacy-api-key" not in str(data)  # gitleaks:allow
