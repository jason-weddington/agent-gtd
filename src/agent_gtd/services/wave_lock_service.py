"""Wave item lock service functions.

Manages the locked_by_wave_id column on items to prevent parallel dispatches
while a wave run is active.
"""

import logging

from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def lock_items_for_wave(
    db: DbPool, wave_run_id: str, item_ids: list[str]
) -> None:
    """Flag each item as locked by wave_run_id.

    Idempotent if the item is already locked by the same wave.
    Raises ValidationError if any item is already locked by a different wave.
    Non-existent item IDs silently affect zero rows.

    Args:
        db: Database pool.
        wave_run_id: The wave run ID that will hold the lock.
        item_ids: List of item IDs to lock.

    Raises:
        ValidationError: If any item is already locked by a different wave run.
    """
    for item_id in item_ids:
        row = await db.fetchrow(
            "SELECT locked_by_wave_id FROM items WHERE id = $1", item_id
        )
        if row and row["locked_by_wave_id"] and row["locked_by_wave_id"] != wave_run_id:
            raise ValidationError(
                f"Item {item_id} is already locked by wave {row['locked_by_wave_id']}"
            )

    for item_id in item_ids:
        # Use $3 == $1 (wave_run_id) to avoid repeated $1 which confuses
        # the SQLite adapter's $N → ? substitution (it substitutes literally,
        # so $1 appearing twice → two ? placeholders needing two args each).
        await db.execute(
            "UPDATE items SET locked_by_wave_id = $1"
            " WHERE id = $2"
            " AND (locked_by_wave_id IS NULL OR locked_by_wave_id = $3)",
            wave_run_id,
            item_id,
            wave_run_id,
        )


async def release_wave_item(db: DbPool, wave_run_id: str, item_id: str) -> None:
    """Clear the lock on one item (used by complete_in_wave).

    Args:
        db: Database pool.
        wave_run_id: The wave run ID that holds the lock.
        item_id: The item ID to unlock.
    """
    await db.execute(
        "UPDATE items SET locked_by_wave_id = NULL"
        " WHERE id = $1 AND locked_by_wave_id = $2",
        item_id,
        wave_run_id,
    )


async def release_wave_locks(db: DbPool, wave_run_id: str) -> None:
    """Clear locks on all items held by this wave (used by halt_wave).

    Args:
        db: Database pool.
        wave_run_id: The wave run ID whose locks should be released.
    """
    await db.execute(
        "UPDATE items SET locked_by_wave_id = NULL WHERE locked_by_wave_id = $1",
        wave_run_id,
    )
