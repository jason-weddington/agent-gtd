"""Comments CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError
from agent_gtd.identity import get_current_actor_attribution
from agent_gtd.models import (
    CommentResponse,
    CreateCommentRequest,
    UpdateCommentRequest,
    User,
)
from agent_gtd.services import comment_service

router = APIRouter(prefix="/api", tags=["comments"])


def _comment_response(row: dict[str, object]) -> CommentResponse:
    return CommentResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]) if row.get("project_id") else None,
        item_id=str(row["item_id"]) if row.get("item_id") else None,
        content_markdown=str(row["content_markdown"]),
        created_by=str(row["created_by"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


# --- Flat listing with optional filters ---


@router.get("/comments", response_model=list[CommentResponse])
async def list_comments(
    user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = None,
    item_id: str | None = None,
) -> list[CommentResponse]:
    """List comments, optionally filtered by project or item."""
    db = await get_db()
    try:
        rows = await comment_service.list_comments(
            db, user.id, project_id=project_id, item_id=item_id
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return [_comment_response(r) for r in rows]


# --- Project-scoped endpoints ---


@router.get("/projects/{project_id}/comments", response_model=list[CommentResponse])
async def list_project_comments(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[CommentResponse]:
    """List comments for a specific project."""
    db = await get_db()
    try:
        rows = await comment_service.list_comments(db, user.id, project_id=project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return [_comment_response(r) for r in rows]


@router.post(
    "/projects/{project_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
async def create_project_comment(
    project_id: str,
    body: CreateCommentRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Create a comment on a project."""
    db = await get_db()
    created_by = body.created_by or get_current_actor_attribution()
    try:
        row = await comment_service.create_comment(
            db,
            user.id,
            project_id=project_id,
            content_markdown=body.content_markdown,
            created_by=created_by,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _comment_response(row)


# --- Item-scoped endpoints ---


@router.get("/items/{item_id}/comments", response_model=list[CommentResponse])
async def list_item_comments(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[CommentResponse]:
    """List comments for a specific item."""
    db = await get_db()
    try:
        rows = await comment_service.list_comments(db, user.id, item_id=item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None
    return [_comment_response(r) for r in rows]


@router.post(
    "/items/{item_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
async def create_item_comment(
    item_id: str,
    body: CreateCommentRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Create a comment on an item."""
    db = await get_db()
    created_by = body.created_by or get_current_actor_attribution()
    try:
        row = await comment_service.create_comment(
            db,
            user.id,
            item_id=item_id,
            content_markdown=body.content_markdown,
            created_by=created_by,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None
    return _comment_response(row)


# --- Direct comment endpoints ---


@router.get("/comments/{comment_id}", response_model=CommentResponse)
async def get_comment(
    comment_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Get a single comment by ID."""
    db = await get_db()
    try:
        row = await comment_service.get_comment(db, user.id, comment_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Comment not found") from None
    return _comment_response(row)


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: str,
    body: UpdateCommentRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Update an existing comment."""
    db = await get_db()
    try:
        row = await comment_service.update_comment(
            db,
            user.id,
            comment_id,
            content_markdown=body.content_markdown,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Comment not found") from None
    return _comment_response(row)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a comment."""
    db = await get_db()
    try:
        await comment_service.delete_comment(db, user.id, comment_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Comment not found") from None
