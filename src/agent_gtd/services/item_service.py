"""Item CRUD service functions."""

import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    VersionConflictError,
)
from agent_gtd.models import ItemStatus, Priority
from agent_gtd.services.project_service import verify_project_ownership


async def list_items(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    status: str | None = None,
    project_id: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
) -> list[dict[str, Any]]:
    """List items for a user, with optional filters."""
    clauses = ["user_id = ?"]
    params: list[object] = [user_id]

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if priority is not None:
        clauses.append("priority = ?")
        params.append(priority)
    if assigned_to is not None:
        clauses.append("assigned_to = ?")
        params.append(assigned_to)

    where = " AND ".join(clauses)
    cursor = await db.execute(
        f"SELECT * FROM items WHERE {where} ORDER BY sort_order, created_at DESC",  # noqa: S608
        tuple(params),
    )
    rows = await cursor.fetchall()
    return [row_to_dict(r) for r in rows]


async def create_item(
    db: aiosqlite.Connection,
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
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
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
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def get_item(
    db: aiosqlite.Connection, user_id: str, item_id: str
) -> dict[str, Any]:
    """Get a single item by ID.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    cursor = await db.execute(
        "SELECT * FROM items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise NotFoundError("Item", item_id)
    return row_to_dict(row)


async def update_item(
    db: aiosqlite.Connection,
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
        db: Database connection.
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
        updates.append("title = ?")
        params.append(title)
    if description is not None:
        updates.append("description = ?")
        params.append(description)

    if project_id_set:
        if project_id is not None:
            await verify_project_ownership(db, str(project_id), user_id)
        updates.append("project_id = ?")
        params.append(project_id)

    if status is not None:
        updates.append("status = ?")
        params.append(status)

        # Auto-set completed_at when transitioning to done
        old_status = str(existing["status"])
        if status == ItemStatus.DONE and old_status != ItemStatus.DONE:
            updates.append("completed_at = ?")
            params.append(datetime.now(UTC).isoformat())
        elif status != ItemStatus.DONE and old_status == ItemStatus.DONE:
            updates.append("completed_at = ?")
            params.append(None)

    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)

    if due_date_set:
        updates.append("due_date = ?")
        params.append(due_date)

    if assigned_to is not None:
        updates.append("assigned_to = ?")
        params.append(assigned_to)
    if waiting_on is not None:
        updates.append("waiting_on = ?")
        params.append(waiting_on)
    if sort_order is not None:
        updates.append("sort_order = ?")
        params.append(sort_order)
    if labels is not None:
        updates.append("labels = ?")
        params.append(encode_json_list(labels))

    if updates:
        updates.append("version = version + 1")
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(item_id)

        sql = f"UPDATE items SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def delete_item(db: aiosqlite.Connection, user_id: str, item_id: str) -> None:
    """Delete an item.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    await get_item(db, user_id, item_id)  # verifies ownership
    await db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    await db.commit()


async def inbox_capture(
    db: aiosqlite.Connection,
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


async def list_inbox(db: aiosqlite.Connection, user_id: str) -> list[dict[str, Any]]:
    """List inbox items (status=inbox)."""
    return await list_items(db, user_id, status=ItemStatus.INBOX.value)


async def complete_item(
    db: aiosqlite.Connection, user_id: str, item_id: str
) -> dict[str, Any]:
    """Set item status to done and auto-set completed_at.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, status=ItemStatus.DONE.value)


async def claim_item(
    db: aiosqlite.Connection,
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


async def release_item(
    db: aiosqlite.Connection, user_id: str, item_id: str
) -> dict[str, Any]:
    """Release an item (clear assigned_to).

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, assigned_to="")


async def list_project_items(
    db: aiosqlite.Connection, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """List items for a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    return await list_items(db, user_id, project_id=project_id)


async def create_project_item(
    db: aiosqlite.Connection,
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
