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


# ---------------------------------------------------------------------------
# Tests for _check_dispatch_service
# ---------------------------------------------------------------------------


async def test_check_dispatch_service_no_config(monkeypatch):
    """_check_dispatch_service raises 503 when dispatch is not configured."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    # Get database and a user ID
    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test@example.com", "testpass")
    user_id = user.id

    # Mock get_dispatch_config to return None
    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_config",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "not configured" in exc_info.value.detail


async def test_check_dispatch_service_health_non_200(monkeypatch):
    """_check_dispatch_service raises 503 when health endpoint returns non-200."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test2@example.com", "testpass")
    user_id = user.id

    # Mock get_dispatch_config to return a fake config
    fake_config = {"url": "http://fake-dispatch:8100", "api_key": "fake-key"}

    # Mock httpx.AsyncClient to return a 503 response
    _patch_client(monkeypatch, httpx.Response(503))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_config",
        new_callable=AsyncMock,
        return_value=fake_config,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "error" in exc_info.value.detail


async def test_check_dispatch_service_connect_error(monkeypatch):
    """_check_dispatch_service raises 503 when dispatch service is unreachable."""
    from fastapi import HTTPException

    from agent_gtd.database import get_db

    db = await get_db()
    from agent_gtd.auth import register_user

    user = await register_user("test3@example.com", "testpass")
    user_id = user.id

    # Mock get_dispatch_config to return a fake config
    fake_config = {"url": "http://fake-dispatch:8100", "api_key": "fake-key"}

    # Mock httpx.AsyncClient to raise ConnectError
    _patch_client(monkeypatch, httpx.ConnectError("Connection failed"))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_config",
        new_callable=AsyncMock,
        return_value=fake_config,
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

    # Mock get_dispatch_config to return a fake config
    fake_config = {"url": "http://fake-dispatch:8100", "api_key": "fake-key"}

    # Mock httpx.AsyncClient to raise TimeoutException
    _patch_client(monkeypatch, httpx.TimeoutException("Timeout"))

    with patch(
        "agent_gtd.routes.dispatch_routes.get_dispatch_config",
        new_callable=AsyncMock,
        return_value=fake_config,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dr._check_dispatch_service(db, user_id)

        assert exc_info.value.status_code == 503
        assert "timed out" in exc_info.value.detail
