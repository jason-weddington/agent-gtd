"""Item CRUD service functions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.event_bus import get_event_bus
from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from agent_gtd.models import ItemStatus, Priority
from agent_gtd.services.project_service import verify_project_ownership

logger = logging.getLogger(__name__)


async def list_items(
    db: DbPool,
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
    db: DbPool,
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


async def get_item(db: DbPool, user_id: str, item_id: str) -> dict[str, Any]:
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
    db: DbPool,
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


async def delete_item(db: DbPool, user_id: str, item_id: str) -> None:
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
    db: DbPool,
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


async def list_inbox(db: DbPool, user_id: str) -> list[dict[str, Any]]:
    """List inbox items (status=inbox)."""
    return await list_items(db, user_id, status=ItemStatus.INBOX.value)


async def complete_item(db: DbPool, user_id: str, item_id: str) -> dict[str, Any]:
    """Set item status to done and auto-set completed_at.

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, status=ItemStatus.DONE.value)


async def claim_item(
    db: DbPool,
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


async def release_item(db: DbPool, user_id: str, item_id: str) -> dict[str, Any]:
    """Release an item (clear assigned_to).

    Raises:
        NotFoundError: If the item doesn't exist or isn't owned by user.
    """
    return await update_item(db, user_id, item_id, assigned_to="")


async def list_project_items(
    db: DbPool, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """List items for a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    return await list_items(db, user_id, project_id=project_id)


async def create_project_item(
    db: DbPool,
    user_id: str,
    project_id: str,
    *,
    title: str,
    description: str = "",
    status: str = ItemStatus.NEW.value,
    priority: str = Priority.NORMAL.value,
    due_date: str | None = None,
    created_by: str = "human",
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
        created_by=created_by,
        assigned_to=assigned_to,
        waiting_on=waiting_on,
        sort_order=sort_order,
        labels=labels,
    )


async def search_items(
    db: DbPool,
    user_id: str,
    q: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search items by title for the calling user.

    Returns a list of lightweight dicts suitable for BlockerSummary.
    Excludes done items. Prefix matches rank above substring matches.

    Args:
        db: Database pool.
        user_id: Owner user ID — only their items are returned.
        q: Search query (case-insensitive substring match on title).
        limit: Maximum number of results (default 10, max 25).
    """
    # Pass q twice: once for the WHERE filter, once for the ORDER BY prefix rank.
    # Using $3 / $4 separately keeps positional params compatible with the SQLite
    # adapter (which maps each $N to its own ? placeholder).
    sql = """
        SELECT i.id, i.title, i.status, i.project_id, p.name AS project_name
        FROM items i
        LEFT JOIN projects p ON p.id = i.project_id
        WHERE i.user_id = $1
          AND LOWER(i.title) LIKE '%' || LOWER($2) || '%'
          AND i.status <> 'done'
        ORDER BY
          (LOWER(i.title) LIKE LOWER($3) || '%') DESC,
          i.updated_at DESC
        LIMIT $4
    """
    rows = await db.fetch(sql, user_id, q, q, limit)
    return [row_to_dict(r) for r in rows]


def item_row_to_response_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw item row dict to a response-friendly dict with decoded labels."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }


# --- Blocker service functions ---


async def _would_create_cycle(db: DbPool, item_id: str, blocker_item_id: str) -> bool:
    """Return True if adding the blocker would create a dependency cycle.

    Performs a BFS from blocker_item_id through the item_dependencies graph.
    If item_id is reachable as a transitive blocker, a cycle would be created.
    """
    visited: set[str] = {blocker_item_id}
    queue: list[str] = [blocker_item_id]
    while queue:
        current = queue.pop()
        rows = await db.fetch(
            "SELECT blocker_item_id FROM item_dependencies WHERE item_id = $1",
            current,
        )
        for r in rows:
            bid = str(r["blocker_item_id"])
            if bid == item_id:
                return True
            if bid not in visited:
                visited.add(bid)
                queue.append(bid)
    return False


async def _blocker_summary_row(db: DbPool, blocker_item_id: str) -> dict[str, Any]:
    """Fetch a single item as a blocker summary dict (joins with projects)."""
    row = await db.fetchrow(
        """
        SELECT i.id, i.title, i.status, i.project_id, p.name AS project_name
        FROM items i
        LEFT JOIN projects p ON p.id = i.project_id
        WHERE i.id = $1
        """,
        blocker_item_id,
    )
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def add_blocker(
    db: DbPool,
    user_id: str,
    item_id: str,
    blocker_item_id: str,
) -> dict[str, Any]:
    """Add a blocker relationship.

    Idempotent: if the relationship already exists it is returned silently.

    Args:
        db: Database pool.
        user_id: Owner user ID — both items must belong to this user.
        item_id: The item being blocked.
        blocker_item_id: The item that blocks it.

    Raises:
        NotFoundError: If either item doesn't exist or isn't owned by user.
        ValidationError: If item_id == blocker_item_id (self-block).
        ValidationError: If adding the blocker would create a dependency cycle.
    """
    if item_id == blocker_item_id:
        raise ValidationError("an item cannot block itself")

    # Verify both items belong to the user (raises NotFoundError otherwise).
    await get_item(db, user_id, item_id)
    await get_item(db, user_id, blocker_item_id)

    # Idempotent: return existing silently.
    existing = await db.fetchrow(
        "SELECT id FROM item_dependencies WHERE item_id = $1 AND blocker_item_id = $2",
        item_id,
        blocker_item_id,
    )
    if existing is not None:
        return await _blocker_summary_row(db, blocker_item_id)

    # Cycle detection.
    if await _would_create_cycle(db, item_id, blocker_item_id):
        raise ValidationError("adding this blocker would create a cycle")

    dep_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at)"
        " VALUES ($1, $2, $3, $4)",
        dep_id,
        item_id,
        blocker_item_id,
        now,
    )
    return await _blocker_summary_row(db, blocker_item_id)


async def remove_blocker(
    db: DbPool,
    user_id: str,
    item_id: str,
    blocker_item_id: str,
) -> None:
    """Remove a blocker relationship.

    No-op if the relationship doesn't exist.

    Args:
        db: Database pool.
        user_id: Owner user ID — item_id must belong to this user.
        item_id: The blocked item.
        blocker_item_id: The blocker to remove.

    Raises:
        NotFoundError: If item_id doesn't exist or isn't owned by user.
    """
    await get_item(db, user_id, item_id)  # verifies ownership
    await db.execute(
        "DELETE FROM item_dependencies WHERE item_id = $1 AND blocker_item_id = $2",
        item_id,
        blocker_item_id,
    )


async def list_blockers(
    db: DbPool,
    user_id: str,
    item_id: str,
) -> list[dict[str, Any]]:
    """Return blockers of an item as lightweight summaries (joined with projects).

    Each entry has: id, title, status, project_id, project_name.

    Args:
        db: Database pool.
        user_id: Owner user ID — item_id must belong to this user.
        item_id: The item whose blockers to list.

    Raises:
        NotFoundError: If item_id doesn't exist or isn't owned by user.
    """
    await get_item(db, user_id, item_id)  # verifies ownership
    rows = await db.fetch(
        """
        SELECT i.id, i.title, i.status, i.project_id, p.name AS project_name
        FROM item_dependencies d
        JOIN items i ON i.id = d.blocker_item_id
        LEFT JOIN projects p ON p.id = i.project_id
        WHERE d.item_id = $1
        ORDER BY d.created_at
        """,
        item_id,
    )
    return [row_to_dict(r) for r in rows]
