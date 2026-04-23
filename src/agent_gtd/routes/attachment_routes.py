"""Attachment upload, read, and delete API routes."""

import logging
import uuid as _uuid_mod
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError
from agent_gtd.models import Attachment, AttachmentResponse, User
from agent_gtd.services import attachment_service, attachment_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["attachments"])

# ---------------------------------------------------------------------------
# Upload constants
# ---------------------------------------------------------------------------

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_CHUNK_SIZE = 64 * 1024  # 64 KB read buffer

# Maps lowercase extension → canonical MIME type stored in DB.
_EXT_TO_CANONICAL_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

# Maps lowercase extension → set of acceptable declared Content-Type values.
# Markdown is lenient because browsers often send application/octet-stream
# for .md files.
_EXT_ALLOWED_DECLARED_MIMES: dict[str, frozenset[str]] = {
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".md": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
    ".markdown": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _attachment_response(row: dict[str, object]) -> AttachmentResponse:
    return AttachmentResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]),
        filename=str(row["filename"]),
        mime_type=str(row["mime_type"]),
        size_bytes=int(str(row["size_bytes"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


async def _check_item_ownership(
    db: object,
    user_id: str,
    item_id: str,
    detail: str = "Item not found",
) -> None:
    """Raise HTTP 404 if *item_id* is not accessible to *user_id*.

    Args:
        db: Database connection pool.
        user_id: Authenticated user's ID.
        item_id: Item UUID to check.
        detail: Error detail message for the 404 response.

    Raises:
        HTTPException: 404 if item not found or not owned by user.
    """
    from agent_gtd.services import item_service

    try:
        await item_service.get_item(db, user_id, item_id)  # type: ignore[arg-type]
    except NotFoundError:
        raise HTTPException(status_code=404, detail=detail) from None


# ---------------------------------------------------------------------------
# POST — upload
# ---------------------------------------------------------------------------


@router.post(
    "/items/{item_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    item_id: str,
    file: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(get_current_user)],
) -> AttachmentResponse:
    """Upload a new attachment to an item.

    Accepts ``multipart/form-data`` with a single ``file`` field.  Supported
    file types: JPEG (``.jpg`` / ``.jpeg``), PNG (``.png``), and Markdown
    (``.md`` / ``.markdown``).  Maximum file size is 10 MB.

    The file is written to disk first; the DB row is inserted afterwards.
    If the insert fails the file is cleaned up so no dangling artifact remains.

    Args:
        item_id: Parent item UUID.
        file: Uploaded file (multipart).
        user: Authenticated user from JWT.

    Returns:
        The created :class:`~agent_gtd.models.AttachmentResponse`, HTTP 201.

    Raises:
        HTTPException: 404 if item not found or not accessible.
        HTTPException: 413 if the file exceeds 10 MB.
        HTTPException: 415 if the file type is unsupported or the declared
            Content-Type does not match the file extension's expected category.
    """
    db = await get_db()
    await _check_item_ownership(db, user.id, item_id)

    # ------------------------------------------------------------------
    # Validate extension and declared MIME type
    # ------------------------------------------------------------------
    raw_filename = file.filename or "file"
    # Extract lowercase extension (includes the leading dot, e.g. ".png").
    dot_idx = raw_filename.rfind(".")
    ext = raw_filename[dot_idx:].lower() if dot_idx != -1 else ""

    if ext not in _EXT_TO_CANONICAL_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {ext or '(no extension)'!r}",
        )

    declared_mime = (file.content_type or "").lower().split(";")[0].strip()
    if declared_mime not in _EXT_ALLOWED_DECLARED_MIMES[ext]:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Content-Type {declared_mime!r} is not allowed for extension {ext!r}"
            ),
        )

    canonical_mime = _EXT_TO_CANONICAL_MIME[ext]

    # ------------------------------------------------------------------
    # Stream content with size limit
    # ------------------------------------------------------------------
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="File too large; maximum upload size is 10 MB",
            )
        chunks.append(chunk)

    content = b"".join(chunks)

    # ------------------------------------------------------------------
    # Write file to disk
    # ------------------------------------------------------------------
    attachment_id = str(_uuid_mod.uuid4())
    safe_filename = attachment_storage.sanitize_filename(raw_filename)
    storage_path = attachment_storage.build_storage_path(
        item_id, attachment_id, safe_filename
    )
    item_dir = attachment_storage.ensure_item_dir(item_id)
    dest = item_dir / f"{attachment_id}-{safe_filename}"
    dest.write_bytes(content)

    # ------------------------------------------------------------------
    # Insert DB row — clean up file if this fails
    # ------------------------------------------------------------------
    now = datetime.now(UTC)
    attachment = Attachment(
        id=attachment_id,
        item_id=item_id,
        filename=raw_filename,
        mime_type=canonical_mime,
        size_bytes=total_bytes,
        storage_path=storage_path,
        created_at=now,
    )
    try:
        await attachment_service.insert(db, attachment)
    except Exception:
        logger.exception(
            "Failed to insert attachment row; cleaning up file %s", storage_path
        )
        attachment_storage.delete_file(storage_path)
        raise HTTPException(
            status_code=500, detail="Failed to save attachment"
        ) from None

    return AttachmentResponse(
        id=attachment_id,
        item_id=item_id,
        filename=raw_filename,
        mime_type=canonical_mime,
        size_bytes=total_bytes,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# GET — download
# ---------------------------------------------------------------------------


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
    db = await get_db()
    await _check_item_ownership(db, user.id, item_id)
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
    db = await get_db()
    row = await attachment_service.get(db, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Verify the caller can access the parent item.
    await _check_item_ownership(
        db, user.id, str(row["item_id"]), detail="Attachment not found"
    )

    path = attachment_storage.absolute_path(str(row["storage_path"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")

    filename = str(row["filename"])
    return FileResponse(
        path=path,
        media_type=str(row["mime_type"]),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


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
    db = await get_db()
    row = await attachment_service.get(db, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Ownership check — item must be accessible to caller.
    await _check_item_ownership(
        db, user.id, str(row["item_id"]), detail="Attachment not found"
    )

    # Delete file first, then the DB row.
    attachment_storage.delete_file(str(row["storage_path"]))
    await attachment_service.delete(db, attachment_id)
