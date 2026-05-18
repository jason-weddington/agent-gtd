"""Best-effort event publish wrapper with per-event-type failure counters."""

import logging
from collections import defaultdict
from typing import Any

from agent_gtd.db_types import DbPool
from agent_gtd.event_bus import EventBus

logger = logging.getLogger(__name__)

# Module-level per-event-type counters: {event_type: {"attempts": int, "failures": int}}
_publish_stats: defaultdict[str, dict[str, int]] = defaultdict(
    lambda: {"attempts": 0, "failures": 0}
)


async def best_effort_publish(
    bus: EventBus,
    db: DbPool,
    *,
    user_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    project_id: str | None = None,
    payload: dict[str, Any],
    context: dict[str, str],
) -> None:
    """Publish an event best-effort: log and count failures, never raise.

    Increments the attempt counter for *event_type* on every call.
    On exception, logs exactly once at WARN level with *event_type*, all
    keys from *context*, the exception class name, and the exception message,
    then increments the failure counter.

    Args:
        bus: The event bus instance.
        db: Database connection pool.
        user_id: Owner of the event.
        event_type: SSE event type string (e.g. ``"item_created"``).
        entity_type: Entity type (e.g. ``"note"``, ``"item"``, ``"run"``).
        entity_id: Entity ID.
        project_id: Optional project ID for member fan-out.
        payload: Event payload dict.
        context: Entity IDs for structured log fields (e.g.
            ``{"note_id": "abc123"}``). All keys are included in the log
            record on failure.
    """
    _publish_stats[event_type]["attempts"] += 1
    try:
        await bus.publish(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            payload=payload,
        )
    except Exception as exc:
        _publish_stats[event_type]["failures"] += 1
        logger.warning(
            "Failed to publish event",
            extra={
                "event_type": event_type,
                **context,
                "exc_class": type(exc).__name__,
                "exc_msg": str(exc),
            },
        )


def get_publish_stats() -> dict[str, dict[str, int]]:
    """Return current publish attempt/failure counts keyed by event_type.

    Returns:
        A plain ``dict`` snapshot of ``{event_type: {"attempts": int,
        "failures": int}, ...}``.  Safe to serialise to JSON.
    """
    return dict(_publish_stats)


def reset_publish_stats() -> None:
    """Reset all publish stats counters.

    Call this in test teardown to prevent counter bleed between tests.
    """
    _publish_stats.clear()
