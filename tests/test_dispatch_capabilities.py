"""Tests for the /api/dispatch/capabilities proxy endpoint."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient

import agent_gtd.routes.dispatch_routes as dr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_capabilities_cache():
    """Clear the in-process capabilities cache before (and after) each test."""
    dr._capabilities_cache.clear()
    yield
    dr._capabilities_cache.clear()


async def _configure_dispatch(
    client: AsyncClient,
    headers: dict[str, str],
    url: str = "http://fake-dispatch:8100",
    api_key: str = "test-api-key",
) -> None:
    """Configure per-user dispatch settings via the settings API."""
    res = await client.patch(
        "/api/settings/dispatch",
        json={"service_url": url, "service_api_key": api_key},
        headers=headers,
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# AC1 — happy path
# ---------------------------------------------------------------------------


async def test_capabilities_happy_path(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """/info succeeds — proxy returns engine, version, and agents."""
    await _configure_dispatch(client, auth_headers)

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=AsyncMock(
            return_value={
                "engine": "claude-code",
                "version": "1.2.3",
                "agents": ["code-reviewer"],
                "max_concurrent_runs": 4,
                "active_runs": 0,
            }
        ),
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] == "claude-code"
    assert data["version"] == "1.2.3"
    assert len(data["agents"]) == 1
    assert data["agents"][0]["name"] == "code-reviewer"


async def test_capabilities_requires_auth(client: AsyncClient):
    """Endpoint is auth-gated — unauthenticated requests get 401."""
    res = await client.get("/api/dispatch/capabilities")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# AC2 — graceful upstream failures
# ---------------------------------------------------------------------------


async def test_capabilities_info_fails(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Host /info fails — returns null engine/version and empty agents."""
    await _configure_dispatch(client, auth_headers)

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=AsyncMock(side_effect=httpx.ConnectError("unreachable")),
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] is None
    assert data["version"] is None
    assert data["agents"] == []


async def test_capabilities_agents_fails(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Host /info returns no agents — engine/version present, agents empty."""
    await _configure_dispatch(client, auth_headers)

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=AsyncMock(
            return_value={
                "engine": "claude-code",
                "version": "1.2.3",
                "agents": [],
                "max_concurrent_runs": 4,
                "active_runs": 0,
            }
        ),
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] == "claude-code"
    assert data["version"] == "1.2.3"
    assert data["agents"] == []


async def test_capabilities_both_fail(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Host /info fails — returns all null/empty fields."""
    await _configure_dispatch(client, auth_headers)

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=AsyncMock(side_effect=httpx.ConnectError("unreachable")),
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] is None
    assert data["version"] is None
    assert data["agents"] == []


async def test_capabilities_non_200_upstream(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Non-200 from upstream is treated as failure — still returns 200."""
    await _configure_dispatch(client, auth_headers)

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "503",
                request=httpx.Request("GET", "http://fake-dispatch:8100/info"),
                response=httpx.Response(503),
            )
        ),
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] is None
    assert data["version"] is None
    assert data["agents"] == []


async def test_capabilities_not_configured(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Dispatch URL not configured — returns all null/empty, no HTTP calls."""
    fetch_host_cap = AsyncMock()

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        res = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["engine"] is None
    assert data["version"] is None
    assert data["agents"] == []

    # No HTTP calls should have been made (no hosts configured)
    fetch_host_cap.assert_not_called()


# ---------------------------------------------------------------------------
# AC3 — short cache
# ---------------------------------------------------------------------------


async def test_capabilities_cache_hit(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Second call within 60s returns cached result without re-fetching upstream."""
    await _configure_dispatch(client, auth_headers)

    fetch_host_cap = AsyncMock(
        return_value={"engine": "claude-code", "version": "1.0.0", "agents": []}
    )

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        res1 = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        res2 = await client.get("/api/dispatch/capabilities", headers=auth_headers)

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json() == res2.json()

    # Upstream fetched only once — second call was a cache hit
    assert fetch_host_cap.call_count == 1


async def test_capabilities_cache_keyed_by_url(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Two different users have separate cache entries (keyed by user_id)."""
    from agent_gtd.auth import create_token, register_user

    await _configure_dispatch(client, auth_headers, url="http://dispatch-v1:8100")

    # Create a second user with their own dispatch host
    user_b = await register_user("userb_caps@example.com", "passb")
    headers_b = {"Authorization": f"Bearer {create_token(user_b.id)}"}
    await _configure_dispatch(client, headers_b, url="http://dispatch-v2:8100")

    fetch_host_cap = AsyncMock(
        return_value={"engine": "claude-code", "version": "1.0.0", "agents": []}
    )

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        # First user call — populates cache for user A
        res1 = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        assert res1.status_code == 200

        # Second user call — different user_id, different cache key
        res2 = await client.get("/api/dispatch/capabilities", headers=headers_b)
        assert res2.status_code == 200

    # Each user's hosts were fetched exactly once
    assert fetch_host_cap.call_count == 2


async def test_capabilities_cache_invalidated_after_ttl(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
):
    """After the 60s TTL expires, next call re-fetches from upstream."""
    await _configure_dispatch(client, auth_headers)

    # Control time via the module-level _now() helper
    current_time = [0.0]
    monkeypatch.setattr(
        "agent_gtd.routes.dispatch_routes._now",
        lambda: current_time[0],
    )

    fetch_host_cap = AsyncMock(
        return_value={"engine": "claude-code", "version": "1.0.0", "agents": []}
    )

    with patch(
        "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
        new=fetch_host_cap,
    ):
        # First call at t=0 — populates cache
        res1 = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        assert res1.status_code == 200

        # Advance time just inside TTL — cache still warm
        current_time[0] = 59.0
        res_cached = await client.get(
            "/api/dispatch/capabilities", headers=auth_headers
        )
        assert res_cached.status_code == 200

        # Advance time past TTL
        current_time[0] = 61.0
        res2 = await client.get("/api/dispatch/capabilities", headers=auth_headers)
        assert res2.status_code == 200

    # Upstream called twice: initial + after TTL expired (not for the t=59 call)
    assert fetch_host_cap.call_count == 2


# ---------------------------------------------------------------------------
# AC4 — HTTP helpers (unit tests covering the httpx calls directly)
# ---------------------------------------------------------------------------


class _MockAsyncTransport(httpx.AsyncBaseTransport):
    """Minimal mock HTTP transport that returns a pre-built httpx.Response."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


def _patch_client(monkeypatch, response: httpx.Response):
    """Monkey-patch httpx.AsyncClient in dispatch_routes to use a mock transport."""
    _orig = httpx.AsyncClient

    def _patched(*args, **kwargs):
        return _orig(transport=_MockAsyncTransport(response))

    monkeypatch.setattr("agent_gtd.routes.dispatch_routes.httpx.AsyncClient", _patched)


async def test_fetch_dispatch_info_success(monkeypatch):
    """_fetch_dispatch_info returns engine and version parsed from /info JSON."""
    _patch_client(
        monkeypatch,
        httpx.Response(200, json={"engine": "claude-code", "version": "1.2.3"}),
    )
    result = await dr._fetch_dispatch_info("http://fake:8100", "key")
    assert result == {"engine": "claude-code", "version": "1.2.3"}


async def test_fetch_dispatch_info_missing_fields(monkeypatch):
    """_fetch_dispatch_info returns None for absent engine/version fields."""
    _patch_client(monkeypatch, httpx.Response(200, json={"other": "stuff"}))
    result = await dr._fetch_dispatch_info("http://fake:8100", "key")
    assert result == {"engine": None, "version": None}


async def test_fetch_dispatch_info_non_200_raises(monkeypatch):
    """_fetch_dispatch_info propagates httpx.HTTPStatusError on non-200."""
    _patch_client(monkeypatch, httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await dr._fetch_dispatch_info("http://fake:8100", "key")


async def test_fetch_dispatch_agents_success(monkeypatch):
    """_fetch_dispatch_agents unwraps the ``{"agents": [...]}`` envelope."""
    agents = [{"name": "code-reviewer", "description": "Reviews code"}]
    _patch_client(monkeypatch, httpx.Response(200, json={"agents": agents}))
    result = await dr._fetch_dispatch_agents("http://fake:8100", "key")
    assert len(result) == 1
    assert result[0]["name"] == "code-reviewer"


async def test_fetch_dispatch_agents_unexpected_shape(monkeypatch):
    """_fetch_dispatch_agents returns [] when upstream JSON isn't envelope-shaped."""
    _patch_client(monkeypatch, httpx.Response(200, json=["bad", "shape"]))
    result = await dr._fetch_dispatch_agents("http://fake:8100", "key")
    assert result == []


async def test_fetch_dispatch_agents_non_200_raises(monkeypatch):
    """_fetch_dispatch_agents propagates httpx.HTTPStatusError on non-200."""
    _patch_client(monkeypatch, httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await dr._fetch_dispatch_agents("http://fake:8100", "key")
