"""Note CRUD service functions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.event_bus import get_event_bus
from agent_gtd.exceptions import NotFoundError
from agent_gtd.services.project_service import verify_project_ownership

logger = logging.getLogger(__name__)


async def list_project_notes(
    db: asyncpg.Pool, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """List notes for a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)

    rows = await db.fetch(
        "SELECT * FROM notes WHERE project_id = $1 AND user_id = $2 "
        "ORDER BY updated_at DESC",
        project_id,
        user_id,
    )
    return [row_to_dict(r) for r in rows]


async def create_note(
    db: asyncpg.Pool,
    user_id: str,
    project_id: str,
    *,
    title: str = "",
    content_markdown: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a note in a project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)

    now = datetime.now(UTC).isoformat()
    note_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO notes "
        "(id, project_id, user_id, title, content_markdown, labels, "
        "created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        note_id,
        project_id,
        user_id,
        title,
        content_markdown,
        encode_json_list(labels or []),
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM notes WHERE id = $1", note_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="note_created",
            entity_type="note",
            entity_id=note_id,
            project_id=project_id,
            payload=note_row_to_response_dict(result),
        )
    except Exception:
        logger.exception("Failed to publish note_created event")

    return result


async def get_note(db: asyncpg.Pool, user_id: str, note_id: str) -> dict[str, Any]:
    """Get a single note by ID.

    Raises:
        NotFoundError: If the note doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT * FROM notes WHERE id = $1 AND user_id = $2",
        note_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Note", note_id)
    return row_to_dict(row)


async def update_note(
    db: asyncpg.Pool,
    user_id: str,
    note_id: str,
    *,
    title: str | None = None,
    content_markdown: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update a note. Only non-None fields are changed.

    Raises:
        NotFoundError: If the note doesn't exist or isn't owned by user.
    """
    # Verify ownership
    await get_note(db, user_id, note_id)

    updates: list[str] = []
    params: list[object] = []

    if title is not None:
        params.append(title)
        updates.append(f"title = ${len(params)}")
    if content_markdown is not None:
        params.append(content_markdown)
        updates.append(f"content_markdown = ${len(params)}")
    if labels is not None:
        params.append(encode_json_list(labels))
        updates.append(f"labels = ${len(params)}")

    if updates:
        params.append(datetime.now(UTC).isoformat())
        updates.append(f"updated_at = ${len(params)}")
        params.append(note_id)

        sql = f"UPDATE notes SET {', '.join(updates)} WHERE id = ${len(params)}"  # noqa: S608
        await db.execute(sql, *params)

    row = await db.fetchrow("SELECT * FROM notes WHERE id = $1", note_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="note_updated",
            entity_type="note",
            entity_id=note_id,
            project_id=str(result["project_id"]),
            payload=note_row_to_response_dict(result),
        )
    except Exception:
        logger.exception("Failed to publish note_updated event")

    return result


async def delete_note(db: asyncpg.Pool, user_id: str, note_id: str) -> None:
    """Delete a note.

    Raises:
        NotFoundError: If the note doesn't exist or isn't owned by user.
    """
    existing = await get_note(db, user_id, note_id)  # verifies ownership
    project_id = str(existing["project_id"])
    await db.execute("DELETE FROM notes WHERE id = $1", note_id)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="note_deleted",
            entity_type="note",
            entity_id=note_id,
            project_id=project_id,
            payload={"id": note_id},
        )
    except Exception:
        logger.exception("Failed to publish note_deleted event")


def note_row_to_response_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw note row dict to a response-friendly dict with decoded labels."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }
