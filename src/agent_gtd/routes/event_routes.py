"""Server-Sent Events endpoint for real-time sync."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import StreamingResponse

from agent_gtd.auth import get_current_user_from_token, get_local_user
from agent_gtd.database import get_db, is_local_mode
from agent_gtd.event_bus import get_event_bus
from agent_gtd.models import User

router = APIRouter(prefix="/api/events", tags=["events"])

_HEARTBEAT_INTERVAL = 30  # seconds

_optional_bearer = HTTPBearer(auto_error=False)


async def _resolve_user(
    token: str | None = Query(default=None),
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_optional_bearer)
    ] = None,
) -> User:
    """Resolve user from query param token or Bearer header."""
    if is_local_mode():
        return await get_local_user()
    raw_token = token
    if raw_token is None and credentials is not None:
        raw_token = credentials.credentials
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    return await get_current_user_from_token(raw_token)


def _format_sse(event: dict[str, Any]) -> str:
    """Format an event dict as SSE wire format."""
    event_id = event["id"]
    event_type = event["event_type"]
    data = json.dumps(
        {
            "eventType": event_type,
            "entityType": event["entity_type"],
            "entityId": event["entity_id"],
            "projectId": event["project_id"],
            "payload": json.loads(event["payload"]),
            "createdAt": event["created_at"],
        },
        default=str,
    )
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


async def _event_stream(
    user_id: str,
    since: str | None,
    request: Request,
) -> AsyncGenerator[str]:
    """Async generator that yields SSE formatted events."""
    bus = get_event_bus()
    db = await get_db()

    # Replay missed events
    if since:
        missed = await bus.replay_since(db, user_id, since)
        for event in missed:
            yield _format_sse(event)

    # Subscribe to live events
    queue = bus.subscribe(user_id)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                live_event: dict[str, Any] | None = await asyncio.wait_for(
                    queue.get(), timeout=_HEARTBEAT_INTERVAL
                )
                if live_event is None:
                    # Shutdown signal
                    break
                yield _format_sse(live_event)
            except TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        bus.unsubscribe(user_id, queue)


@router.get("")
async def event_stream(
    request: Request,
    user: Annotated[User, Depends(_resolve_user)],
    since: str | None = Query(default=None),
) -> StreamingResponse:
    """SSE endpoint for real-time event streaming."""
    return StreamingResponse(
        _event_stream(user.id, since, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
