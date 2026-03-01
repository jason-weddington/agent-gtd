"""Project notes CRUD API routes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from agent_gtd.auth import get_current_user
from agent_gtd.database import decode_json_list, encode_json_list, get_db, row_to_dict
from agent_gtd.models import (
    CreateNoteRequest,
    NoteResponse,
    UpdateNoteRequest,
    User,
)

router = APIRouter(prefix="/api", tags=["notes"])


def _note_response(row: dict[str, object]) -> NoteResponse:
    return NoteResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        title=str(row["title"]),
        content_markdown=str(row["content_markdown"]),
        labels=decode_json_list(str(row["labels"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


async def _verify_project_ownership(
    db: aiosqlite.Connection, project_id: str, user_id: str
) -> None:
    """Verify that a project exists and belongs to the user."""
    cursor = await db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


# --- Project-scoped endpoints ---


@router.get("/projects/{project_id}/notes", response_model=list[NoteResponse])
async def list_project_notes(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[NoteResponse]:
    """List notes for a specific project."""
    db = await get_db()
    await _verify_project_ownership(db, project_id, user.id)

    cursor = await db.execute(
        "SELECT * FROM notes WHERE project_id = ? AND user_id = ? "
        "ORDER BY updated_at DESC",
        (project_id, user.id),
    )
    rows = await cursor.fetchall()
    return [_note_response(row_to_dict(r)) for r in rows]


@router.post(
    "/projects/{project_id}/notes",
    response_model=NoteResponse,
    status_code=201,
)
async def create_project_note(
    project_id: str,
    body: CreateNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Create a note in a project."""
    db = await get_db()
    await _verify_project_ownership(db, project_id, user.id)

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
            user.id,
            body.title,
            body.content_markdown,
            encode_json_list(body.labels),
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


# --- Direct note endpoints ---


@router.get("/notes/{note_id}", response_model=NoteResponse)
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


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    body: UpdateNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Update an existing note."""
    db = await get_db()

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
    if body.content_markdown is not None:
        updates.append("content_markdown = ?")
        params.append(body.content_markdown)
    if body.labels is not None:
        updates.append("labels = ?")
        params.append(encode_json_list(body.labels))

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


@router.delete("/notes/{note_id}", status_code=204)
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
