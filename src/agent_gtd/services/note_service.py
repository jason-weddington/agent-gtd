"""Note CRUD service functions."""

import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.exceptions import NotFoundError
from agent_gtd.services.project_service import verify_project_ownership


async def list_project_notes(
    db: aiosqlite.Connection, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """List notes for a specific project.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)

    cursor = await db.execute(
        "SELECT * FROM notes WHERE project_id = ? AND user_id = ? "
        "ORDER BY updated_at DESC",
        (project_id, user_id),
    )
    rows = await cursor.fetchall()
    return [row_to_dict(r) for r in rows]


async def create_note(
    db: aiosqlite.Connection,
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
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            note_id,
            project_id,
            user_id,
            title,
            content_markdown,
            encode_json_list(labels or []),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def get_note(
    db: aiosqlite.Connection, user_id: str, note_id: str
) -> dict[str, Any]:
    """Get a single note by ID.

    Raises:
        NotFoundError: If the note doesn't exist or isn't owned by user.
    """
    cursor = await db.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise NotFoundError("Note", note_id)
    return row_to_dict(row)


async def update_note(
    db: aiosqlite.Connection,
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
        updates.append("title = ?")
        params.append(title)
    if content_markdown is not None:
        updates.append("content_markdown = ?")
        params.append(content_markdown)
    if labels is not None:
        updates.append("labels = ?")
        params.append(encode_json_list(labels))

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(note_id)

        sql = f"UPDATE notes SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def delete_note(db: aiosqlite.Connection, user_id: str, note_id: str) -> None:
    """Delete a note.

    Raises:
        NotFoundError: If the note doesn't exist or isn't owned by user.
    """
    await get_note(db, user_id, note_id)  # verifies ownership
    await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    await db.commit()


def note_row_to_response_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw note row dict to a response-friendly dict with decoded labels."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }
