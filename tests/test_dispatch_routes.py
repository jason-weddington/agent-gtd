"""Tests for the /api/dispatch routes and helper functions."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

import agent_gtd.routes.dispatch_routes as dr

# ---------------------------------------------------------------------------
# Mock Transports
# ---------------------------------------------------------------------------


class _MockAsyncTransport(httpx.AsyncBaseTransport):
    """Minimal mock HTTP transport that returns a pre-built httpx.Response."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


class _RaisingTransport(httpx.AsyncBaseTransport):
    """Mock HTTP transport that raises a specified exception."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self._exception


# ---------------------------------------------------------------------------
# Patch Helpers
# ---------------------------------------------------------------------------


def _patch_client(monkeypatch, response_or_exception):
    """Monkey-patch httpx.AsyncClient in dispatch_routes to use a mock transport."""
    _orig = httpx.AsyncClient

    def _patched(*args, **kwargs):
        if isinstance(response_or_exception, Exception):
            transport = _RaisingTransport(response_or_exception)
        else:
            transport = _MockAsyncTransport(response_or_exception)
        return _orig(transport=transport)

    monkeypatch.setattr("agent_gtd.routes.dispatch_routes.httpx.AsyncClient", _patched)


# Fake dispatch host for use in tests that need a configured host.
_FAKE_HOST = {
    "id": "host-1",
    "url": "http://fake-dispatch:8100",
    "api_key": "fake-key",  # gitleaks:allow
    "label": "default",
}


# ---------------------------------------------------------------------------
# Tests for _check_dispatch_service
# ---------------------------------------------------------------------------


async def test_check_dispatch_service_no_config(monkeypatch):
    """_check_dispatch_service raises 503 when no dispatch hosts are configured."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test@example.com", "testpass")
    user_id = user.id

    # Mock get_dispatch_hosts to return empty list (no hosts configured)
    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "not configured" in exc_info.value.detail


async def test_check_dispatch_service_health_non_200(monkeypatch):
    """_check_dispatch_service raises 503 when all health endpoints return non-200."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test2@example.com", "testpass")
    user_id = user.id

    # Mock httpx.AsyncClient to return a 503 response
    _patch_client(monkeypatch, httpx.Response(503))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=[_FAKE_HOST],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "unreachable" in exc_info.value.detail


async def test_check_dispatch_service_connect_error(monkeypatch):
    """_check_dispatch_service raises 503 when dispatch service is unreachable."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test3@example.com", "testpass")
    user_id = user.id

    # Mock httpx.AsyncClient to raise ConnectError
    _patch_client(monkeypatch, httpx.ConnectError("Connection failed"))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=[_FAKE_HOST],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "unreachable" in exc_info.value.detail


async def test_check_dispatch_service_timeout(monkeypatch):
    """_check_dispatch_service raises 503 when dispatch service times out."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test4@example.com", "testpass")
    user_id = user.id

    # Mock httpx.AsyncClient to raise TimeoutException
    _patch_client(monkeypatch, httpx.TimeoutException("Timeout"))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=[_FAKE_HOST],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "unreachable" in exc_info.value.detail


async def test_check_dispatch_service_brand_new_user(monkeypatch):
    """Brand-new user with host via hosts API passes preflight (no legacy settings).

    A user who never set dispatch.service_url / dispatch.service_api_key in
    user_settings but has added a host via the dispatch hosts API should be able
    to dispatch successfully — _check_dispatch_service must NOT return 503.
    """
    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    # Fresh user — no legacy user_settings
    user = await register_user("brand-new@example.com", "testpass")
    user_id = user.id

    # Mock httpx.AsyncClient to return a healthy 200 response
    _patch_client(monkeypatch, httpx.Response(200))

    # Simulate get_dispatch_hosts returning the host added via the hosts API
    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=[_FAKE_HOST],
    ):
        # Should NOT raise — at least one host is healthy
        await dr._check_dispatch_service(db, user_id)


async def test_check_dispatch_service_one_host_down_one_up(monkeypatch):
    """_check_dispatch_service passes when at least one of multiple hosts is healthy."""
    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("multi-host@example.com", "testpass")
    user_id = user.id

    call_count = 0

    async def _mixed_health(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # First host fails, second succeeds
        if call_count == 1:
            raise httpx.ConnectError("first host down")
        return httpx.Response(200)

    _orig = httpx.AsyncClient

    def _patched(*args, **kwargs):
        transport = _MockAsyncTransport.__new__(_MockAsyncTransport)
        transport.handle_async_request = _mixed_health
        return _orig(transport=transport)

    monkeypatch.setattr("agent_gtd.routes.dispatch_routes.httpx.AsyncClient", _patched)

    two_hosts = [
        {"id": "h1", "url": "http://host1:8100", "api_key": "key1", "label": "h1"},
        {"id": "h2", "url": "http://host2:8100", "api_key": "key2", "label": "h2"},
    ]

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
        new_callable=AsyncMock,
        return_value=two_hosts,
    ):
        # Should NOT raise — second host is reachable
        await dr._check_dispatch_service(db, user_id)


# ---------------------------------------------------------------------------
# Tests for dispatch_host_id validation in dispatch_item route
# ---------------------------------------------------------------------------


async def test_dispatch_targeted_host_not_found(client, auth_headers, project_id):
    """dispatch_item returns 404 when dispatch_host_id is not in owner's host list."""
    # Create an item in the project
    item_res = await client.post(
        "/api/items",
        json={
            "title": "Test targeted dispatch",
            "project_id": project_id,
            "status": "next_action",
        },
        headers=auth_headers,
    )
    assert item_res.status_code == 201
    item_id = item_res.json()["id"]

    # Set git_origin on the project so dispatch validation passes that step
    await client.patch(
        f"/api/projects/{project_id}",
        json={"git_origin": "https://github.com/example/repo.git"},
        headers=auth_headers,
    )

    # Mock: dispatch service is configured with one host, but the requested ID differs
    _existing_host = {**_FAKE_HOST, "id": "real-host-id"}
    with (
        patch(
            "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
            new_callable=AsyncMock,
            return_value=[_existing_host],
        ),
        patch(
            "agent_gtd.routes.dispatch_routes._check_dispatch_service",
            new_callable=AsyncMock,
        ),
    ):
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={"mode": "build", "dispatch_host_id": "nonexistent-host-uuid"},
            headers=auth_headers,
        )

    assert res.status_code == 404
    assert "nonexistent-host-uuid" in res.json()["detail"]


async def test_dispatch_targeted_host_full(client, auth_headers, project_id):
    """dispatch_item returns 409 when the targeted host is at capacity."""
    # Create an item in the project
    item_res = await client.post(
        "/api/items",
        json={
            "title": "Test full host dispatch",
            "project_id": project_id,
            "status": "next_action",
        },
        headers=auth_headers,
    )
    assert item_res.status_code == 201
    item_id = item_res.json()["id"]

    # Set git_origin on the project
    await client.patch(
        f"/api/projects/{project_id}",
        json={"git_origin": "https://github.com/example/repo.git"},
        headers=auth_headers,
    )

    full_info = {
        "engine": "claude-code",
        "engines": ["claude-code"],
        "agents": [],
        "max_concurrent_runs": 4,
        "active_runs": 4,
    }

    _target_host = {**_FAKE_HOST, "id": "target-host-id"}
    with (
        patch(
            "agent_gtd.routes.dispatch_routes.get_dispatch_hosts",
            new_callable=AsyncMock,
            return_value=[_target_host],
        ),
        patch(
            "agent_gtd.routes.dispatch_routes._check_dispatch_service",
            new_callable=AsyncMock,
        ),
        patch(
            "agent_gtd.routes.dispatch_routes._fetch_host_capabilities",
            new_callable=AsyncMock,
            return_value=full_info,
        ),
    ):
        res = await client.post(
            f"/api/items/{item_id}/dispatch",
            json={"mode": "build", "dispatch_host_id": "target-host-id"},
            headers=auth_headers,
        )

    assert res.status_code == 409
    assert "capacity" in res.json()["detail"].lower()
