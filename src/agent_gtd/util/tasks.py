"""Asyncio task supervision helpers."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def supervise_task(
    task: asyncio.Task[Any],
    *,
    context: dict[str, str],
) -> None:
    """Attach a done-callback that logs exceptions from fire-and-forget tasks.

    Args:
        task: The asyncio.Task to supervise.
        context: Key-value pairs included in the log record for attribution
            (e.g. ``{"run_id": ..., "event_type": ...}``).
    """

    def _on_done(t: asyncio.Task[Any]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception(
                "Supervised task failed — %s",
                context,
                exc_info=exc,
            )

    task.add_done_callback(_on_done)
