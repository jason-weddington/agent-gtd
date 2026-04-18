"""Comment CRUD service functions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_gtd.database import row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.event_bus import get_event_bus
from agent_gtd.exceptions import NotFoundError
from agent_gtd.services.item_service import get_item
from agent_gtd.services.project_service import verify_project_access

logger = logging.getLogger(__name__)


async def _verify_item_access(db: DbPool, item_id: str, user_id: str) -> dict[str, Any]:
    """Verify an item is accessible to the user. Returns the item row.

    An item is accessible if it is in a project the user can access (owned or
    shared), or is a project-less inbox item owned by the user.
    """
    return await get_item(db, user_id, item_id)


async def _resolve_project_id(
    db: DbPool, *, project_id: str | None, item_id: str | None
) -> str | None:
    """Get the project_id for SSE event context.

    For project comments, returns the project_id directly.
    For item comments, looks up the item's project_id (may be None for inbox).
    """
    if project_id:
        return project_id
    if item_id:
        row = await db.fetchrow("SELECT project_id FROM items WHERE id = $1", item_id)
        if row:
            pid: str | None = row["project_id"]
            return pid
    return None


async def list_comments(
    db: DbPool,
    user_id: str,
    *,
    project_id: str | None = None,
    item_id: str | None = None,
) -> list[dict[str, Any]]:
    """List comments, optionally filtered by project or item.

    Raises:
        NotFoundError: If the project/item doesn't exist or isn't owned by user.
    """
    if project_id:
        await verify_project_access(db, project_id, user_id)
        rows = await db.fetch(
            "SELECT * FROM comments WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
    elif item_id:
        await _verify_item_access(db, item_id, user_id)
        rows = await db.fetch(
            "SELECT * FROM comments WHERE item_id = $1 ORDER BY created_at ASC",
            item_id,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM comments WHERE user_id = $1 ORDER BY created_at ASC",
            user_id,
        )
    return [row_to_dict(r) for r in rows]


async def create_comment(
    db: DbPool,
    user_id: str,
    *,
    project_id: str | None = None,
    item_id: str | None = None,
    content_markdown: str = "",
    created_by: str = "human",
) -> dict[str, Any]:
    """Create a comment on a project or item.

    Exactly one of project_id or item_id must be provided.

    Raises:
        NotFoundError: If the parent doesn't exist or isn't owned by user.
    """
    if project_id:
        await verify_project_access(db, project_id, user_id)
    if item_id:
        await _verify_item_access(db, item_id, user_id)

    now = datetime.now(UTC).isoformat()
    comment_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO comments "
        "(id, project_id, item_id, user_id, content_markdown, created_by, "
        "created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        comment_id,
        project_id,
        item_id,
        user_id,
        content_markdown,
        created_by,
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM comments WHERE id = $1", comment_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    event_project_id = await _resolve_project_id(
        db, project_id=project_id, item_id=item_id
    )
    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="comment_created",
            entity_type="comment",
            entity_id=comment_id,
            project_id=event_project_id,
            payload=result,
        )
    except Exception:
        logger.exception("Failed to publish comment_created event")

    return result


async def get_comment(db: DbPool, user_id: str, comment_id: str) -> dict[str, Any]:
    """Get a single comment by ID.

    Raises:
        NotFoundError: If the comment doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT * FROM comments WHERE id = $1 AND user_id = $2",
        comment_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Comment", comment_id)
    return row_to_dict(row)


async def update_comment(
    db: DbPool,
    user_id: str,
    comment_id: str,
    *,
    content_markdown: str | None = None,
) -> dict[str, Any]:
    """Update a comment. Only non-None fields are changed.

    Raises:
        NotFoundError: If the comment doesn't exist or isn't owned by user.
    """
    await get_comment(db, user_id, comment_id)

    updates: list[str] = []
    params: list[object] = []

    if content_markdown is not None:
        params.append(content_markdown)
        updates.append(f"content_markdown = ${len(params)}")

    if updates:
        params.append(datetime.now(UTC).isoformat())
        updates.append(f"updated_at = ${len(params)}")
        params.append(comment_id)

        sql = f"UPDATE comments SET {', '.join(updates)} WHERE id = ${len(params)}"  # noqa: S608
        await db.execute(sql, *params)

    row = await db.fetchrow("SELECT * FROM comments WHERE id = $1", comment_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    event_project_id = await _resolve_project_id(
        db,
        project_id=result.get("project_id"),
        item_id=result.get("item_id"),
    )
    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="comment_updated",
            entity_type="comment",
            entity_id=comment_id,
            project_id=event_project_id,
            payload=result,
        )
    except Exception:
        logger.exception("Failed to publish comment_updated event")

    return result


async def delete_comment(db: DbPool, user_id: str, comment_id: str) -> None:
    """Delete a comment.

    Raises:
        NotFoundError: If the comment doesn't exist or isn't owned by user.
    """
    existing = await get_comment(db, user_id, comment_id)
    event_project_id = await _resolve_project_id(
        db,
        project_id=existing.get("project_id"),
        item_id=existing.get("item_id"),
    )
    await db.execute("DELETE FROM comments WHERE id = $1", comment_id)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="comment_deleted",
            entity_type="comment",
            entity_id=comment_id,
            project_id=event_project_id,
            payload={"id": comment_id},
        )
    except Exception:
        logger.exception("Failed to publish comment_deleted event")
