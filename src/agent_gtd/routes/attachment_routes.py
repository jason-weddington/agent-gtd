"""Attachment read and delete API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError
from agent_gtd.models import AttachmentResponse, User
from agent_gtd.services import attachment_service, attachment_storage

router = APIRouter(prefix="/api", tags=["attachments"])


def _attachment_response(row: dict[str, object]) -> AttachmentResponse:
    return AttachmentResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]),
        filename=str(row["filename"]),
        mime_type=str(row["mime_type"]),
        size_bytes=int(str(row["size_bytes"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


@router.get("/items/{item_id}/attachments", response_model=list[AttachmentResponse])
async def list_item_attachments(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[AttachmentResponse]:
    """List all attachments for an item.

    The caller must own (or have access to) the parent item.

    Args:
        item_id: Parent item UUID.
        user: Authenticated user from JWT.

    Returns:
        List of attachment metadata (no storage paths).

    Raises:
        HTTPException: 404 if item not found or not accessible.
    """
    from agent_gtd.services import item_service

    db = await get_db()
    try:
        await item_service.get_item(db, user.id, item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None
    rows = await attachment_service.list_for_item(db, item_id)
    return [_attachment_response(r) for r in rows]


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    """Serve an attachment file with the correct Content-Type.

    Returns the raw file bytes with ``Content-Disposition: inline``.  The
    caller must be able to access the parent item.

    Args:
        attachment_id: Attachment UUID.
        user: Authenticated user from JWT.

    Returns:
        The file as a :class:`~fastapi.responses.FileResponse`.

    Raises:
        HTTPException: 404 if the attachment (or its parent item) is not found
            or not accessible.
    """
    from agent_gtd.services import item_service

    db = await get_db()
    row = await attachment_service.get(db, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Verify the caller can access the parent item.
    try:
        await item_service.get_item(db, user.id, str(row["item_id"]))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Attachment not found") from None

    path = attachment_storage.absolute_path(str(row["storage_path"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")

    filename = str(row["filename"])
    return FileResponse(
        path=path,
        media_type=str(row["mime_type"]),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete an attachment — removes the file on disk and the DB row.

    Only the item owner may delete attachments.

    Args:
        attachment_id: Attachment UUID.
        user: Authenticated user from JWT.

    Raises:
        HTTPException: 404 if the attachment is not found or not accessible.
    """
    from agent_gtd.services import item_service

    db = await get_db()
    row = await attachment_service.get(db, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Ownership check — item must be accessible to caller.
    try:
        await item_service.get_item(db, user.id, str(row["item_id"]))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Attachment not found") from None

    # Delete file first, then the DB row.
    attachment_storage.delete_file(str(row["storage_path"]))
    await attachment_service.delete(db, attachment_id)
