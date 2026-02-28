"""Notes CRUD API routes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from agent_gtd.auth import get_current_user
from agent_gtd.database import decode_tags, encode_tags, get_db, row_to_dict
from agent_gtd.models import (
    CreateNoteRequest,
    NoteResponse,
    UpdateNoteRequest,
    User,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _note_response(row: dict[str, object]) -> NoteResponse:
    return NoteResponse(
        id=str(row["id"]),
        title=str(row["title"]),
        content=str(row["content"]),
        tags=decode_tags(str(row["tags"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    user: Annotated[User, Depends(get_current_user)],
) -> list[NoteResponse]:
    """List all notes for the current user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC",
        (user.id,),
    )
    rows = await cursor.fetchall()
    return [_note_response(row_to_dict(r)) for r in rows]


@router.post("", response_model=NoteResponse, status_code=201)
async def create_note(
    body: CreateNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Create a new note."""
    now = datetime.now(UTC).isoformat()
    note_id = str(uuid.uuid4())

    db = await get_db()
    await db.execute(
        "INSERT INTO notes "
        "(id, user_id, title, content, tags, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            note_id,
            user.id,
            body.title,
            body.content,
            encode_tags(body.tags),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Insert failed")
    return _note_response(row_to_dict(row))


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Get a single note by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user.id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    return _note_response(row_to_dict(row))


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    body: UpdateNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Update an existing note."""
    db = await get_db()

    # Verify ownership
    cursor = await db.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user.id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    updates: list[str] = []
    params: list[object] = []

    if body.title is not None:
        updates.append("title = ?")
        params.append(body.title)
    if body.content is not None:
        updates.append("content = ?")
        params.append(body.content)
    if body.tags is not None:
        updates.append("tags = ?")
        params.append(encode_tags(body.tags))

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(note_id)

        sql = f"UPDATE notes SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Update failed")
    return _note_response(row_to_dict(row))


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a note."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user.id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    await db.commit()
