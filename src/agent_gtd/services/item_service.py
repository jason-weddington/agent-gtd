"""Item CRUD service functions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.event_bus import get_event_bus
from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    VersionConflictError,
)
from agent_gtd.models import ItemStatus, Priority
from agent_gtd.services.project_service import verify_project_ownership

logger = logging.getLogger(__name__)


async def list_items(
    db: asyncpg.Pool,
    user_id: str,
    *,
    status: str | None = None,
    project_id: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
) -> list[dict[str, Any]]:
    """List items for a user, with optional filters."""
    clauses = ["user_id = $1"]
    params: list[object] = [user_id]

    if status is not None:
        params.append(status)
        clauses.append(f"status = ${len(params)}")
    if project_id is not None:
        params.append(project_id)
        clauses.append(f"project_id = ${len(params)}")
    if priority is not None:
        params.append(priority)
        clauses.append(f"priority = ${len(params)}")
    if assigned_to is not None:
        params.append(assigned_to)
        clauses.append(f"assigned_to = ${len(params)}")

    where = " AND ".join(clauses)
    rows = await db.fetch(
        f"SELECT * FROM items WHERE {where} ORDER BY sort_order, created_at DESC",  # noqa: S608
        *params,
    )
    return [row_to_dict(r) for r in rows]


async def create_item(
    db: asyncpg.Pool,
    user_id: str,
    *,
    title: str,
    description: str = "",
    project_id: str | None = None,
    status: str = ItemStatus.INBOX.value,
    priority: str = Priority.NORMAL.value,
    due_date: str | None = None,
    created_by: str = "human",
    assigned_to: str = "",
    waiting_on: str = "",
    sort_order: float = 0,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new item and return its row data.

    Raises:
        NotFoundError: If project_id is given but doesn't exist or isn't owned by user.
    """
    if project_id is not None:
        await verify_project_ownership(db, project_id, user_id)

    now = datetime.now(UTC).isoformat()
    item_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, priority, "
        "due_date, created_by, assigned_to, waiting_on, sort_order, labels, "
        "created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)",
        item_id,
        project_id,
        user_id,
        title,
        description,
        status,
        priority,
        due_date,
        created_by,
        assigned_to,
        waiting_on,
        sort_order,
        encode_json_list(labels or []),
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="item_created",
            entity_type="item",
            entity_id=item_id,
            project_id=project_id,
            payload=item_row_to_response_dict(result),
        )
    except Exception:
        logger.exception("Failed to publish item_created event")

    return result


async def get_item(db: asyncpg.Pool, user_id: str, item_id: str) -> dict[str, Any]:
    """Get a single item by ID.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT * FROM items WHERE id = $1 AND user_id = $2",
        item_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Item", item_id)
    return row_to_dict(row)


async def update_item(
    db: asyncpg.Pool,
    user_id: str,
    item_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    project_id: object = None,
    project_id_set: bool = False,
    status: str | None = None,
    priority: str | None = None,
    due_date: object = None,
    due_date_set: bool = False,
    assigned_to: str | None = None,
    waiting_on: str | None = None,
    sort_order: float | None = None,
    labels: list[str] | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    """Update an item. Only non-None fields are changed.

    Args:
        db: Database pool.
        user_id: Owner user ID.
        item_id: ID of the item to update.
        title: New title (None = unchanged).
        description: New description (None = unchanged).
        project_id: New project ID (used only if project_id_set is True).
        project_id_set: If True, project_id is written even if None.
        status: New status value (None = unchanged).
        priority: New priority value (None = unchanged).
        due_date: New due date (used only if due_date_set is True).
        due_date_set: If True, due_date is written even if None.
        assigned_to: New assignee (None = unchanged).
        waiting_on: New waiting_on value (None = unchanged).
        sort_order: New sort order (None = unchanged).
        labels: New labels list (None = unchanged).
        version: If provided, enforces optimistic locking — update fails
            if the current DB version doesn't match.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
        VersionConflictError: If version is provided and doesn't match.
    """
    existing = await get_item(db, user_id, item_id)

    # Optimistic locking
    if version is not None:
        current_version = int(str(existing["version"]))
        if current_version != version:
            raise VersionConflictError("Item", item_id, version, current_version)

    updates: list[str] = []
    params: list[object] = []

    if title is not None:
        params.append(title)
        updates.append(f"title = ${len(params)}")
    if description is not None:
        params.append(description)
        updates.append(f"description = ${len(params)}")

    if project_id_set:
        if project_id is not None:
            await verify_project_ownership(db, str(project_id), user_id)
        params.append(project_id)
        updates.append(f"project_id = ${len(params)}")

    if status is not None:
        params.append(status)
        updates.append(f"status = ${len(params)}")

        # Auto-set completed_at when transitioning to done
        old_status = str(existing["status"])
        if status == ItemStatus.DONE and old_status != ItemStatus.DONE:
            params.append(datetime.now(UTC).isoformat())
            updates.append(f"completed_at = ${len(params)}")
        elif status != ItemStatus.DONE and old_status == ItemStatus.DONE:
            params.append(None)
            updates.append(f"completed_at = ${len(params)}")

    if priority is not None:
        params.append(priority)
        updates.append(f"priority = ${len(params)}")

    if due_date_set:
        params.append(due_date)
        updates.append(f"due_date = ${len(params)}")

    if assigned_to is not None:
        params.append(assigned_to)
        updates.append(f"assigned_to = ${len(params)}")
    if waiting_on is not None:
        params.append(waiting_on)
        updates.append(f"waiting_on = ${len(params)}")
    if sort_order is not None:
        params.append(sort_order)
        updates.append(f"sort_order = ${len(params)}")
    if labels is not None:
        params.append(encode_json_list(labels))
        updates.append(f"labels = ${len(params)}")

    if updates:
        updates.append("version = version + 1")
        params.append(datetime.now(UTC).isoformat())
        updates.append(f"updated_at = ${len(params)}")
        params.append(item_id)

        sql = f"UPDATE items SET {', '.join(updates)} WHERE id = ${len(params)}"  # noqa: S608
        await db.execute(sql, *params)

    row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="item_updated",
            entity_type="item",
            entity_id=item_id,
            project_id=str(result["project_id"]) if result["project_id"] else None,
            payload=item_row_to_response_dict(result),
        )
    except Exception:
        logger.exception("Failed to publish item_updated event")

    return result


async def delete_item(db: asyncpg.Pool, user_id: str, item_id: str) -> None:
    """Delete an item.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    existing = await get_item(db, user_id, item_id)  # verifies ownership
    project_id = str(existing["project_id"]) if existing["project_id"] else None
    await db.execute("DELETE FROM items WHERE id = $1", item_id)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="item_deleted",
            entity_type="item",
            entity_id=item_id,
            project_id=project_id,
            payload={"id": item_id},
        )
    except Exception:
        logger.exception("Failed to publish item_deleted event")


async def inbox_capture(
    db: asyncpg.Pool,
    user_id: str,
    title: str,
    *,
    project_id: str | None = None,
    created_by: str = "human",
) -> dict[str, Any]:
    """Quick capture to inbox — title only.

    Raises:
        NotFoundError: If project_id is given but doesn't exist or isn't owned by user.
    """
    return await create_item(
        db,
        user_id,
        title=title,
        project_id=project_id,
        status=ItemStatus.INBOX.value,
        priority=Priority.NORMAL.value,
        created_by=created_by,
    )


async def list_inbox(db: asyncpg.Pool, user_id: str) -> list[dict[str, Any]]:
    """List inbox items (status=inbox)."""
    return await list_items(db, user_id, status=ItemStatus.INBOX.value)


async def complete_item(db: asyncpg.Pool, user_id: str, item_id: str) -> dict[str, Any]:
    """Set item status to done and auto-set completed_at.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, status=ItemStatus.DONE.value)


async def claim_item(
    db: asyncpg.Pool,
    user_id: str,
    item_id: str,
    agent_name: str,
) -> dict[str, Any]:
    """Atomically claim an item for an agent.

    Idempotent if the same agent re-claims. Raises AlreadyClaimedError if
    claimed by a different agent.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
        AlreadyClaimedError: If claimed by a different agent.
    """
    existing = await get_item(db, user_id, item_id)
    current_assignee = str(existing["assigned_to"])

    if current_assignee and current_assignee != agent_name:
        raise AlreadyClaimedError(item_id, current_assignee)

    if current_assignee == agent_name:
        # Idempotent — already claimed by this agent
        return existing

    return await update_item(db, user_id, item_id, assigned_to=agent_name)


async def release_item(db: asyncpg.Pool, user_id: str, item_id: str) -> dict[str, Any]:
    """Release an item (clear assigned_to).

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, assigned_to="")


async def list_project_items(
    db: asyncpg.Pool, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """List items for a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    return await list_items(db, user_id, project_id=project_id)


async def create_project_item(
    db: asyncpg.Pool,
    user_id: str,
    project_id: str,
    *,
    title: str,
    description: str = "",
    status: str = ItemStatus.INBOX.value,
    priority: str = Priority.NORMAL.value,
    due_date: str | None = None,
    assigned_to: str = "",
    waiting_on: str = "",
    sort_order: float = 0,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create an item in a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    return await create_item(
        db,
        user_id,
        title=title,
        description=description,
        project_id=project_id,
        status=status,
        priority=priority,
        due_date=due_date,
        assigned_to=assigned_to,
        waiting_on=waiting_on,
        sort_order=sort_order,
        labels=labels,
    )


def item_row_to_response_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw item row dict to a response-friendly dict with decoded labels."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }
