"""Admin-only routes: invite management."""

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from agent_gtd.auth import require_admin
from agent_gtd.database import get_db
from agent_gtd.models import (
    CreateInviteRequest,
    InviteListItem,
    InviteResponse,
    User,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    request: Request,
    body: CreateInviteRequest,
    admin: Annotated[User, Depends(require_admin)],
) -> InviteResponse:
    """Create a new invite token (admin only)."""
    db = await get_db()
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC).isoformat()
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    invite_url = f"{base_url}/register?token={token}"
    await db.execute(
        "INSERT INTO invites (token, issued_by, note, created_at)"
        " VALUES ($1, $2, $3, $4)",
        token,
        admin.id,
        body.note,
        now,
    )
    return InviteResponse(
        token=token,
        url=invite_url,
        note=body.note,
        created_at=datetime.fromisoformat(now),
    )


@router.get("/invites", response_model=list[InviteListItem])
async def list_invites(
    _admin: Annotated[User, Depends(require_admin)],
) -> list[InviteListItem]:
    """List all invites, most recent first (admin only)."""
    db = await get_db()
    rows = await db.fetch(
        "SELECT token, issued_by, note, created_at, used_at, used_by"
        " FROM invites ORDER BY created_at DESC"
    )
    return [
        InviteListItem(
            token=row["token"],
            issued_by=row["issued_by"],
            note=row["note"],
            created_at=datetime.fromisoformat(row["created_at"]),
            used_at=datetime.fromisoformat(row["used_at"]) if row["used_at"] else None,
            used_by=row["used_by"],
        )
        for row in rows
    ]


@router.delete("/invites/{token}", status_code=204)
async def revoke_invite(
    token: str,
    _admin: Annotated[User, Depends(require_admin)],
) -> Response:
    """Revoke an unused invite (admin only). Returns 409 if already used."""
    db = await get_db()
    row = await db.fetchrow("SELECT used_at FROM invites WHERE token = $1", token)
    if row is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if row["used_at"] is not None:
        raise HTTPException(status_code=409, detail="Invite already used")
    await db.execute("DELETE FROM invites WHERE token = $1", token)
    return Response(status_code=204)
