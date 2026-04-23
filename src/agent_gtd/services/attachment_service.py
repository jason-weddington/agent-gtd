"""Attachment CRUD service functions."""

from typing import Any

from agent_gtd.database import row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.models import Attachment


async def list_for_item(db: DbPool, item_id: str) -> list[dict[str, Any]]:
    """Return all attachments for *item_id*, ordered oldest-first.

    Args:
        db: Database connection pool.
        item_id: Parent item UUID.

    Returns:
        List of raw attachment row dicts.
    """
    rows = await db.fetch(
        "SELECT * FROM attachments WHERE item_id = $1 ORDER BY created_at ASC",
        item_id,
    )
    return [row_to_dict(r) for r in rows]


async def get(db: DbPool, attachment_id: str) -> dict[str, Any] | None:
    """Fetch a single attachment by ID.

    Args:
        db: Database connection pool.
        attachment_id: Attachment UUID.

    Returns:
        Raw row dict, or ``None`` if not found.
    """
    row = await db.fetchrow(
        "SELECT * FROM attachments WHERE id = $1",
        attachment_id,
    )
    if row is None:
        return None
    return row_to_dict(row)


async def delete(db: DbPool, attachment_id: str) -> None:
    """Delete the attachment DB row.

    Disk cleanup is the caller's responsibility (use
    :func:`~agent_gtd.services.attachment_storage.delete_file` before calling
    this).

    Args:
        db: Database connection pool.
        attachment_id: Attachment UUID to delete.
    """
    await db.execute("DELETE FROM attachments WHERE id = $1", attachment_id)


async def insert(db: DbPool, attachment: Attachment) -> None:
    """Persist a new attachment record.

    Used by the upload endpoint (Part 2) once the file has been written to
    disk.

    Args:
        db: Database connection pool.
        attachment: Fully-populated domain model to insert.
    """
    await db.execute(
        "INSERT INTO attachments "
        "(id, item_id, filename, mime_type, size_bytes, storage_path, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        attachment.id,
        attachment.item_id,
        attachment.filename,
        attachment.mime_type,
        attachment.size_bytes,
        attachment.storage_path,
        attachment.created_at.isoformat(),
    )
