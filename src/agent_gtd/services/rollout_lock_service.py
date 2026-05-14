"""Rollout item lock service functions.

Manages the locked_by_rollout_id column on items to prevent parallel dispatches
while a rollout is active.
"""

import logging

from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def lock_items_for_rollout(
    db: DbPool, rollout_id: str, item_ids: list[str]
) -> None:
    """Flag each item as locked by rollout_id.

    Idempotent if the item is already locked by the same wave.
    Raises ValidationError if any item is already locked by a different wave.
    Non-existent item IDs silently affect zero rows.

    Args:
        db: Database pool.
        rollout_id: The rollout ID that will hold the lock.
        item_ids: List of item IDs to lock.

    Raises:
        ValidationError: If any item is already locked by a different wave run.
    """
    for item_id in item_ids:
        row = await db.fetchrow(
            "SELECT locked_by_rollout_id FROM items WHERE id = $1", item_id
        )
        if (
            row
            and row["locked_by_rollout_id"]
            and row["locked_by_rollout_id"] != rollout_id
        ):
            raise ValidationError(
                f"Item {item_id} is already locked by rollout"
                f" {row['locked_by_rollout_id']}"
            )

    for item_id in item_ids:
        # Use $3 == $1 (rollout_id) to avoid repeated $1 which confuses
        # the SQLite adapter's $N → ? substitution (it substitutes literally,
        # so $1 appearing twice → two ? placeholders needing two args each).
        await db.execute(
            "UPDATE items SET locked_by_rollout_id = $1"
            " WHERE id = $2"
            " AND (locked_by_rollout_id IS NULL OR locked_by_rollout_id = $3)",
            rollout_id,
            item_id,
            rollout_id,
        )


async def release_rollout_item(db: DbPool, rollout_id: str, item_id: str) -> None:
    """Clear the lock on one item (used by complete_item_in_rollout).

    Args:
        db: Database pool.
        rollout_id: The rollout ID that holds the lock.
        item_id: The item ID to unlock.
    """
    await db.execute(
        "UPDATE items SET locked_by_rollout_id = NULL"
        " WHERE id = $1 AND locked_by_rollout_id = $2",
        item_id,
        rollout_id,
    )


async def release_rollout_locks(db: DbPool, rollout_id: str) -> None:
    """Clear locks on all items held by this wave (used by halt_rollout).

    Args:
        db: Database pool.
        rollout_id: The rollout ID whose locks should be released.
    """
    await db.execute(
        "UPDATE items SET locked_by_rollout_id = NULL WHERE locked_by_rollout_id = $1",
        rollout_id,
    )
