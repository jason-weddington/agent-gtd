"""Tests for dispatch host CRUD endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

import agent_gtd.routes.dispatch_routes as dr


@pytest.fixture(autouse=True)
def _clear_capabilities_cache():
    """Clear the in-process capabilities cache before and after each test."""
    dr._capabilities_cache.clear()
    yield
    dr._capabilities_cache.clear()


@pytest.fixture(autouse=True)
def mock_probe() -> AsyncMock:
    """Stub out probe_dispatch_host so tests don't need a live dispatch host.

    By default the probe succeeds (returns None).  Individual tests that want
    to simulate probe failures can override ``mock_probe.side_effect``.
    """
    with patch(
        "agent_gtd.routes.settings_routes.probe_dispatch_host",
        new_callable=AsyncMock,
    ) as m:
        yield m


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
    assert data["capability_labels"] == []


@pytest.mark.asyncio
async def test_add_dispatch_host_with_capability_labels(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST accepts capability_labels; normalized (lowercase, stripped, deduped)."""
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "host-b",
            "url": "http://r7.local:8001",
            "api_key": "some-key",
            "capability_labels": ["  Camera-Data ", "camera-data", "GPU"],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["capability_labels"] == ["camera-data", "gpu"]


@pytest.mark.asyncio
async def test_update_dispatch_host_labels(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH replaces the full capability_labels list."""
    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "host-c",
            "url": "http://r7server.local:8001",
            "api_key": "some-key",
            "capability_labels": ["gpu"],
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    patch_res = await client.patch(
        f"/api/settings/dispatch/hosts/{host_id}",
        json={"capability_labels": ["Tauri-Linux", "pnpm"]},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["id"] == host_id
    # Normalized (lowercase, stripped) but order-preserving, not sorted.
    assert data["capability_labels"] == ["tauri-linux", "pnpm"]

    # GET reflects the replacement, not a union with the old list.
    list_res = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert list_res.json()[0]["capability_labels"] == ["tauri-linux", "pnpm"]


@pytest.mark.asyncio
async def test_update_dispatch_host_labels_clears_with_empty_list(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH with an empty list clears all labels."""
    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "",
            "url": "http://clear.local:8001",
            "api_key": "some-key",
            "capability_labels": ["gpu"],
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    patch_res = await client.patch(
        f"/api/settings/dispatch/hosts/{host_id}",
        json={"capability_labels": []},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["capability_labels"] == []


@pytest.mark.asyncio
async def test_update_dispatch_host_not_found_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH on a nonexistent host id returns 404."""
    res = await client.patch(
        "/api/settings/dispatch/hosts/00000000-0000-0000-0000-000000000099",
        json={"capability_labels": ["gpu"]},
        headers=auth_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_dispatch_host_wrong_owner_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH by a non-owner returns 404 and does not modify the host."""
    from agent_gtd.auth import create_token, register_user

    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "",
            "url": "http://ownercheck.local:8001",
            "api_key": "keyA",
            "capability_labels": ["gpu"],
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    user_b = await register_user("userb_hostpatch@example.com", "passb")
    headers_b = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    res = await client.patch(
        f"/api/settings/dispatch/hosts/{host_id}",
        json={"capability_labels": ["camera-data"]},
        headers=headers_b,
    )
    assert res.status_code == 404

    # Unchanged from the owner's perspective.
    list_res = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert list_res.json()[0]["capability_labels"] == ["gpu"]


@pytest.mark.asyncio
async def test_update_dispatch_host_invalidates_capabilities_cache(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PATCH invalidates the in-process capabilities cache, same as add/delete."""
    from agent_gtd.models import DispatchCapabilitiesResponse

    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "",
            "url": "http://cachecheck.local:8001",
            "api_key": "some-key",
        },
        headers=auth_headers,
    )
    host_id = add_res.json()["id"]

    me_res = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me_res.json()["id"]
    dr._capabilities_cache[user_id] = (
        dr._now(),
        DispatchCapabilitiesResponse(engine="stale", version="0.0.0"),
    )

    await client.patch(
        f"/api/settings/dispatch/hosts/{host_id}",
        json={"capability_labels": ["gpu"]},
        headers=auth_headers,
    )
    assert user_id not in dr._capabilities_cache


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


# ---------------------------------------------------------------------------
# Probe tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_host_probe_success_returns_201(
    client: AsyncClient, auth_headers: dict[str, str], mock_probe: AsyncMock
) -> None:
    """POST returns 201 when probe_dispatch_host succeeds (returns without error)."""
    mock_probe.return_value = None  # default, but explicit for clarity
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "good-host",
            "url": "http://good.local:8100",
            "api_key": "validkey",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["url"] == "http://good.local:8100"


@pytest.mark.asyncio
async def test_add_host_probe_non_200_returns_400(
    client: AsyncClient, auth_headers: dict[str, str], mock_probe: AsyncMock
) -> None:
    """POST returns 400 with status code in detail when probe gets non-200 response."""
    mock_probe.side_effect = ValueError("HTTP 301 Moved Permanently")
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "redirect-host",
            "url": "http://redirect.local:8100",
            "api_key": "somekey",
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "301" in res.json()["detail"]


@pytest.mark.asyncio
async def test_add_host_probe_connection_error_returns_400(
    client: AsyncClient, auth_headers: dict[str, str], mock_probe: AsyncMock
) -> None:
    """POST returns 400 with reason in detail when probe cannot connect."""
    mock_probe.side_effect = ValueError("Connection refused")
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "dead-host",
            "url": "http://unreachable.local:8100",
            "api_key": "somekey",
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "Connection refused" in res.json()["detail"]


@pytest.mark.asyncio
async def test_add_host_probe_non_json_returns_400(
    client: AsyncClient, auth_headers: dict[str, str], mock_probe: AsyncMock
) -> None:
    """POST returns 400 when probe gets a non-JSON (e.g. HTML) response body."""
    mock_probe.side_effect = ValueError("Response is not valid JSON")
    res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "html-host",
            "url": "http://nginx.local:80",
            "api_key": "somekey",
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "JSON" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Cache invalidation (AC-4, AC-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_host_invalidates_capabilities_cache(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /hosts pops capabilities cache so next GET re-fetches from upstream."""
    # Seed the cache with a fake entry for the test user
    from agent_gtd.models import DispatchCapabilitiesResponse

    # Resolve the user id so we can seed the cache
    me_res = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me_res.json()["id"]

    # Seed the capabilities cache for this user
    dr._capabilities_cache[user_id] = (
        dr._now(),
        DispatchCapabilitiesResponse(engine="stale", version="0.0.0"),
    )

    fetch_host_cap = AsyncMock(
        return_value={
            "engine": "claude-code",
            "version": "1.0.0",
            "agents": [],
            "max_concurrent_runs": 2,
        }
    )

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        # Adding a host should bust the cache
        add_res = await client.post(
            "/api/settings/dispatch/hosts",
            json={  # gitleaks:allow
                "label": "cache-test",
                "url": "http://cache-test.local:8001",
                "api_key": "cache-test-key",
            },
            headers=auth_headers,
        )
        assert add_res.status_code == 201

        # GET capabilities — cache was invalidated, so upstream is called
        caps_res = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        assert caps_res.status_code == 200

    # Upstream was called once (cache miss after invalidation)
    assert fetch_host_cap.call_count == 1


@pytest.mark.asyncio
async def test_delete_host_invalidates_capabilities_cache(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DELETE /hosts/{id} pops capabilities cache so next GET re-fetches."""
    from agent_gtd.models import DispatchCapabilitiesResponse

    # First, add a host to have something to delete
    add_res = await client.post(
        "/api/settings/dispatch/hosts",
        json={  # gitleaks:allow
            "label": "to-delete",
            "url": "http://to-delete.local:8001",
            "api_key": "delete-me-key",
        },
        headers=auth_headers,
    )
    assert add_res.status_code == 201
    host_id = add_res.json()["id"]

    # Resolve the user id so we can seed the cache
    me_res = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me_res.json()["id"]

    # Seed the capabilities cache for this user
    dr._capabilities_cache[user_id] = (
        dr._now(),
        DispatchCapabilitiesResponse(engine="stale", version="0.0.0"),
    )

    fetch_host_cap = AsyncMock(
        return_value={
            "engine": "claude-code",
            "version": "1.0.0",
            "agents": [],
            "max_concurrent_runs": 2,
        }
    )

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        # Deleting the host should bust the cache
        del_res = await client.delete(
            f"/api/settings/dispatch/hosts/{host_id}", headers=auth_headers
        )
        assert del_res.status_code == 204

        # GET capabilities — no hosts left, returns empty result
        caps_res = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        assert caps_res.status_code == 200

    # No hosts remain, so upstream is NOT called (short-circuits before fetch).
    # The important assertion is that the cache was bust (not returned "stale").
    data = caps_res.json()
    assert data.get("engines") == [] or data.get("engine") is None
    fetch_host_cap.assert_not_called()


@pytest.mark.asyncio
async def test_get_dispatch_hosts_returns_drained_host_with_api_key_intact(
    client: AsyncClient, auth_headers: dict[str, str], user_id: str
) -> None:
    """AC13 (stranded-run trap): a drained host still returns its full api_key.

    Direct service-level call — the exact function the dispatch worker's
    reconciliation poll uses to re-authenticate against a drained host.
    Deliberately NOT asserted through GET /api/settings/dispatch/hosts,
    which masks api_key to api_key_preview and does not carry drain_reason.
    """
    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import (
        add_dispatch_host,
        get_dispatch_hosts,
    )

    db = await get_db()
    alpha = await add_dispatch_host(
        db, user_id, "alpha", "http://alpha:8100", "key-alpha"
    )
    beta = await add_dispatch_host(db, user_id, "beta", "http://beta:8100", "key-beta")
    await db.execute(
        "UPDATE dispatch_hosts SET drain_reason = $1 WHERE id = $2",
        "rolling deploy 2.0.2",
        alpha["id"],
    )

    hosts = await get_dispatch_hosts(db, user_id)

    # Both hosts returned, created_at ASC order, nothing filtered out.
    assert [h["label"] for h in hosts] == ["alpha", "beta"]
    assert [h["id"] for h in hosts] == [alpha["id"], beta["id"]]

    drained = next(h for h in hosts if h["id"] == alpha["id"])
    assert drained["drain_reason"] == "rolling deploy 2.0.2"
    assert drained["api_key"] == "key-alpha"  # full key, not a preview

    undrained = next(h for h in hosts if h["id"] == beta["id"])
    assert undrained["drain_reason"] is None
    assert undrained["api_key"] == "key-beta"
