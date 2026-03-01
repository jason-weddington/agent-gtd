"""In-process event bus with SSE fan-out and DB persistence."""

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg

from agent_gtd.database import row_to_dict

logger = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 256


class EventBus:
    """Pub/sub event bus that persists events and fans out to SSE subscribers."""

    def __init__(self) -> None:
        """Initialize the event bus with empty subscriber map."""
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = {}

    def subscribe(self, user_id: str) -> "asyncio.Queue[dict[str, Any] | None]":
        """Create a new subscription queue for a user."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=_QUEUE_MAXSIZE
        )
        self._subscribers.setdefault(user_id, []).append(queue)
        return queue

    def unsubscribe(
        self, user_id: str, queue: "asyncio.Queue[dict[str, Any] | None]"
    ) -> None:
        """Remove a subscription queue for a user."""
        queues = self._subscribers.get(user_id, [])
        with contextlib.suppress(ValueError):
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(user_id, None)

    async def publish(
        self,
        db: asyncpg.Pool,
        *,
        user_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        project_id: str | None = None,
        payload: dict[str, Any],
    ) -> str:
        """Persist an event to the DB and fan out to subscriber queues.

        Returns the event ID. Never raises — publish errors are logged and
        swallowed so mutations are not affected.
        """
        event_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        payload_json = json.dumps(payload, default=str)

        # Persist
        try:
            await db.execute(
                "INSERT INTO events "
                "(id, user_id, event_type, entity_type, entity_id, "
                "project_id, payload, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                event_id,
                user_id,
                event_type,
                entity_type,
                entity_id,
                project_id,
                payload_json,
                now,
            )
        except Exception:
            logger.exception("Failed to persist event %s", event_id)
            return event_id

        event_data: dict[str, Any] = {
            "id": event_id,
            "user_id": user_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "project_id": project_id,
            "payload": payload_json,
            "created_at": now,
        }

        # Fan out
        for queue in self._subscribers.get(user_id, []):
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                # Drop oldest to make room
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event_data)

        return event_id

    async def replay_since(
        self,
        db: asyncpg.Pool,
        user_id: str,
        since_id: str,
    ) -> list[dict[str, Any]]:
        """Replay events created after the given event ID.

        Returns events ordered by created_at ascending.
        """
        since_row = await db.fetchrow(
            "SELECT created_at FROM events WHERE id = $1 AND user_id = $2",
            since_id,
            user_id,
        )
        if since_row is None:
            return []

        rows = await db.fetch(
            "SELECT * FROM events "
            "WHERE user_id = $1 AND created_at > $2 "
            "ORDER BY created_at ASC",
            user_id,
            since_row["created_at"],
        )
        return [row_to_dict(r) for r in rows]

    async def drain(self) -> None:
        """Signal all subscribers to disconnect (used during shutdown)."""
        for queues in self._subscribers.values():
            for queue in queues:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(None)
        self._subscribers.clear()


_bus = EventBus()


def get_event_bus() -> EventBus:
    """Return the module-level event bus singleton."""
    return _bus
