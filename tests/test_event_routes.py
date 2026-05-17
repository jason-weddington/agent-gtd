"""Tests for event_routes: _resolve_user, _event_stream, and the SSE route."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import AsyncClient

from agent_gtd.models import User
from agent_gtd.routes.event_routes import _event_stream, _resolve_user

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_EVENT = {
    "id": "evt-1",
    "event_type": "item.created",
    "entity_type": "item",
    "entity_id": "item-1",
    "project_id": "proj-1",
    "payload": "{}",
    "created_at": "2026-01-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# _resolve_user tests  (AC-1)
# ---------------------------------------------------------------------------


async def test_resolve_user_local_mode():
    """Local mode: returns get_local_user() without inspecting token or credentials."""
    mock_user = MagicMock(spec=User)
    with (
        patch("agent_gtd.routes.event_routes.is_local_mode", return_value=True),
        patch(
            "agent_gtd.routes.event_routes.get_local_user",
            new=AsyncMock(return_value=mock_user),
        ),
    ):
        result = await _resolve_user()
    assert result is mock_user


async def test_resolve_user_query_token():
    """Non-local: ?token=<jwt> calls get_current_user_from_token(token)."""
    mock_user = MagicMock(spec=User)
    mock_fn = AsyncMock(return_value=mock_user)
    with (
        patch("agent_gtd.routes.event_routes.is_local_mode", return_value=False),
        patch(
            "agent_gtd.routes.event_routes.get_current_user_from_token",
            new=mock_fn,
        ),
    ):
        result = await _resolve_user(token="mytoken")
    mock_fn.assert_called_once_with("mytoken")
    assert result is mock_user


async def test_resolve_user_bearer_header():
    """Non-local: Bearer token calls get_current_user_from_token(creds.credentials)."""
    mock_user = MagicMock(spec=User)
    mock_fn = AsyncMock(return_value=mock_user)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="mytoken")
    with (
        patch("agent_gtd.routes.event_routes.is_local_mode", return_value=False),
        patch(
            "agent_gtd.routes.event_routes.get_current_user_from_token",
            new=mock_fn,
        ),
    ):
        # Pass token=None explicitly: FastAPI's Query(default=None) is the
        # actual default when invoking the function directly (outside DI), so
        # we must supply None to avoid a non-None default being passed through.
        result = await _resolve_user(token=None, credentials=creds)
    mock_fn.assert_called_once_with("mytoken")
    assert result is mock_user


async def test_resolve_user_no_auth_raises_401():
    """Non-local mode with no token and no credentials: raises HTTP 401."""
    with (
        patch("agent_gtd.routes.event_routes.is_local_mode", return_value=False),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _resolve_user(token=None, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing authentication token"


# ---------------------------------------------------------------------------
# _event_stream helpers
# ---------------------------------------------------------------------------


def _make_mock_bus(queue: asyncio.Queue) -> MagicMock:
    """Return a mock bus wired to the given queue."""
    mock_bus = MagicMock()
    mock_bus.subscribe.return_value = queue
    mock_bus.replay_since = AsyncMock(return_value=[])
    mock_bus.unsubscribe = MagicMock()
    return mock_bus


def _make_mock_request(disconnected_values: list[bool]) -> MagicMock:
    """Return a mock Request whose is_disconnected() follows the given sequence."""
    mock_request = MagicMock()
    # Append True fallbacks so we never block mid-test on an empty queue.
    mock_request.is_disconnected = AsyncMock(
        side_effect=disconnected_values + [True] * 50
    )
    return mock_request


async def _run_event_stream(
    user_id: str,
    since: str | None,
    mock_request: MagicMock,
    mock_bus: MagicMock,
    mock_accessible: AsyncMock | None = None,
    heartbeat_interval: int | None = None,
) -> list[str]:
    """Run _event_stream under standard mocks and collect yielded chunks."""
    patches: list = [
        patch(
            "agent_gtd.routes.event_routes.get_event_bus",
            return_value=mock_bus,
        ),
        patch(
            "agent_gtd.routes.event_routes.get_db",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ]
    if mock_accessible is not None:
        patches.append(
            patch(
                "agent_gtd.routes.event_routes.accessible_project_ids",
                new=mock_accessible,
            )
        )
    if heartbeat_interval is not None:
        patches.append(
            patch(
                "agent_gtd.routes.event_routes._HEARTBEAT_INTERVAL",
                heartbeat_interval,
            )
        )

    chunks: list[str] = []
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        async for chunk in _event_stream(user_id, since, mock_request):
            chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# _event_stream: live events  (AC-2)
# ---------------------------------------------------------------------------


async def test_event_stream_live_event_yielded():
    """A live event from the queue is yielded as SSE-formatted text."""
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_SAMPLE_EVENT)
    await queue.put(None)  # shutdown signal

    mock_bus = _make_mock_bus(queue)
    mock_request = _make_mock_request([False, False])

    chunks = await _run_event_stream("user-1", None, mock_request, mock_bus)

    assert any("item.created" in c for c in chunks)
    assert all(c.endswith("\n\n") for c in chunks)
    mock_bus.unsubscribe.assert_called_once()


async def test_event_stream_none_signal_exits():
    """Shutdown signal (None) in the queue exits the generator without chunks."""
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)

    mock_bus = _make_mock_bus(queue)
    mock_request = _make_mock_request([False])

    chunks = await _run_event_stream("user-1", None, mock_request, mock_bus)

    assert chunks == []
    mock_bus.unsubscribe.assert_called_once()


async def test_event_stream_disconnected_exits():
    """request.is_disconnected()=True exits the generator without yielding."""
    queue: asyncio.Queue = asyncio.Queue()  # empty — no items

    mock_bus = _make_mock_bus(queue)
    mock_request = _make_mock_request([True])  # disconnect on first check

    chunks = await _run_event_stream("user-1", None, mock_request, mock_bus)

    assert chunks == []
    mock_bus.unsubscribe.assert_called_once()


async def test_event_stream_sse_format():
    """Yielded SSE chunks have id:/event:/data: lines and end with double-newline."""
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_SAMPLE_EVENT)
    await queue.put(None)

    mock_bus = _make_mock_bus(queue)
    mock_request = _make_mock_request([False, False])

    chunks = await _run_event_stream("user-1", None, mock_request, mock_bus)

    event_chunks = [c for c in chunks if c.startswith("id:")]
    assert len(event_chunks) == 1
    chunk = event_chunks[0]
    assert chunk.startswith(f"id: {_SAMPLE_EVENT['id']}\n")
    assert f"event: {_SAMPLE_EVENT['event_type']}\n" in chunk
    assert chunk.endswith("\n\n")
    data_line = next(ln for ln in chunk.split("\n") if ln.startswith("data:"))
    data = json.loads(data_line[len("data: ") :])
    assert data["eventType"] == _SAMPLE_EVENT["event_type"]
    assert data["entityType"] == _SAMPLE_EVENT["entity_type"]
    assert data["entityId"] == _SAMPLE_EVENT["entity_id"]


# ---------------------------------------------------------------------------
# _event_stream: heartbeat  (AC-2)
# ---------------------------------------------------------------------------


async def test_event_stream_heartbeat_on_timeout():
    """Yields ': heartbeat\\n\\n' when asyncio.wait_for raises TimeoutError."""
    queue: asyncio.Queue = asyncio.Queue()  # always empty → always times out

    mock_bus = _make_mock_bus(queue)
    # False → enter loop, timeout, yield heartbeat; True → exit
    mock_request = _make_mock_request([False, True])

    chunks = await _run_event_stream(
        "user-1",
        None,
        mock_request,
        mock_bus,
        heartbeat_interval=0,
    )

    assert ": heartbeat\n\n" in chunks
    mock_bus.unsubscribe.assert_called_once()


# ---------------------------------------------------------------------------
# _event_stream: finally/unsubscribe  (AC-2)
# ---------------------------------------------------------------------------


async def test_event_stream_unsubscribe_on_exception():
    """bus.unsubscribe is called in finally even when is_disconnected() raises."""
    queue: asyncio.Queue = asyncio.Queue()

    mock_bus = _make_mock_bus(queue)
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(
        side_effect=RuntimeError("connection error")
    )

    with (
        patch(
            "agent_gtd.routes.event_routes.get_event_bus",
            return_value=mock_bus,
        ),
        patch(
            "agent_gtd.routes.event_routes.get_db",
            new=AsyncMock(return_value=MagicMock()),
        ),
        pytest.raises(RuntimeError, match="connection error"),
    ):
        async for _ in _event_stream("user-1", None, mock_request):
            pass  # pragma: no cover

    mock_bus.unsubscribe.assert_called_once()


# ---------------------------------------------------------------------------
# _event_stream: replay (since=)  (AC-2)
# ---------------------------------------------------------------------------


async def test_event_stream_replay_with_since():
    """With since=: replay_since is called and missed events are yielded."""
    missed = {**_SAMPLE_EVENT, "id": "evt-missed", "event_type": "item.updated"}

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)  # shutdown after replay

    mock_bus = _make_mock_bus(queue)
    mock_bus.replay_since = AsyncMock(return_value=[missed])
    mock_accessible = AsyncMock(return_value=["proj-1"])
    mock_request = _make_mock_request([False])

    chunks = await _run_event_stream(
        "user-1",
        "since-evt-id",
        mock_request,
        mock_bus,
        mock_accessible=mock_accessible,
    )

    mock_accessible.assert_called_once()
    mock_bus.replay_since.assert_called_once()
    assert any("item.updated" in c for c in chunks)
    mock_bus.unsubscribe.assert_called_once()


async def test_event_stream_no_replay_without_since():
    """Without since=: replay is skipped and accessible_project_ids is not called."""
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)

    mock_bus = _make_mock_bus(queue)
    mock_accessible = AsyncMock(return_value=[])
    mock_request = _make_mock_request([False])

    await _run_event_stream(
        "user-1",
        None,
        mock_request,
        mock_bus,
        mock_accessible=mock_accessible,
    )

    mock_accessible.assert_not_called()
    mock_bus.replay_since.assert_not_called()
    mock_bus.unsubscribe.assert_called_once()


# ---------------------------------------------------------------------------
# event_stream route  (AC-3)
# ---------------------------------------------------------------------------


async def _finite_stream(
    user_id: str,
    since: str | None,
    request: object,
) -> AsyncGenerator[str]:
    """Minimal finite async generator used to stub out _event_stream in route tests."""
    yield "data: test\n\n"


async def test_event_stream_route_returns_200(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /api/events returns HTTP 200 with text/event-stream content-type."""
    with patch("agent_gtd.routes.event_routes._event_stream", _finite_stream):
        response = await client.get("/api/events", headers=auth_headers)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


async def test_event_stream_route_headers(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """GET /api/events includes Cache-Control: no-cache and X-Accel-Buffering: no."""
    with patch("agent_gtd.routes.event_routes._event_stream", _finite_stream):
        response = await client.get("/api/events", headers=auth_headers)
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
