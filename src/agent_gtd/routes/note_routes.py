"""Project notes CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import decode_json_list, get_db
from agent_gtd.exceptions import NotFoundError
from agent_gtd.models import (
    CreateNoteRequest,
    NoteResponse,
    UpdateNoteRequest,
    User,
)
from agent_gtd.services import note_service

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


# --- Project-scoped endpoints ---


@router.get("/projects/{project_id}/notes", response_model=list[NoteResponse])
async def list_project_notes(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[NoteResponse]:
    """List notes for a specific project."""
    db = await get_db()
    try:
        rows = await note_service.list_project_notes(db, user.id, project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return [_note_response(r) for r in rows]


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
    try:
        row = await note_service.create_note(
            db,
            user.id,
            project_id,
            title=body.title,
            content_markdown=body.content_markdown,
            labels=body.labels,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _note_response(row)


# --- Direct note endpoints ---


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Get a single note by ID."""
    db = await get_db()
    try:
        row = await note_service.get_note(db, user.id, note_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found") from None
    return _note_response(row)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    body: UpdateNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> NoteResponse:
    """Update an existing note."""
    db = await get_db()
    try:
        row = await note_service.update_note(
            db,
            user.id,
            note_id,
            title=body.title,
            content_markdown=body.content_markdown,
            labels=body.labels,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found") from None
    return _note_response(row)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a note."""
    db = await get_db()
    try:
        await note_service.delete_note(db, user.id, note_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Note not found") from None
