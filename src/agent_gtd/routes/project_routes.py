"""Projects CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError, ValidationError
from agent_gtd.models import (
    AddMemberRequest,
    CreateProjectRequest,
    MemberSummary,
    ProjectResponse,
    ProjectStatus,
    UpdateProjectRequest,
    User,
)
from agent_gtd.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_response(row: dict[str, object]) -> ProjectResponse:
    return ProjectResponse(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        status=ProjectStatus(str(row["status"])),
        area=str(row["area"]),
        git_origin=str(row.get("git_origin", "")),
        kb_project_ref=str(row.get("kb_project_ref", "")),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: Annotated[User, Depends(get_current_user)],
    project_status: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    area: str | None = None,
) -> list[ProjectResponse]:
    """List projects for the current user, with optional filters."""
    db = await get_db()
    rows = await project_service.list_projects(
        db,
        user.id,
        status=project_status.value if project_status else None,
        area=area,
    )
    return [_project_response(r) for r in rows]


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Create a new project."""
    db = await get_db()
    row = await project_service.create_project(
        db,
        user.id,
        name=body.name,
        description=body.description,
        status=body.status.value,
        area=body.area,
        git_origin=body.git_origin,
        kb_project_ref=body.kb_project_ref,
    )
    return _project_response(row)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Get a single project by ID."""
    db = await get_db()
    try:
        row = await project_service.get_project(db, user.id, project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _project_response(row)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Update an existing project."""
    db = await get_db()
    try:
        row = await project_service.update_project(
            db,
            user.id,
            project_id,
            name=body.name,
            description=body.description,
            status=body.status.value if body.status else None,
            area=body.area,
            git_origin=body.git_origin,
            kb_project_ref=body.kb_project_ref,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _project_response(row)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a project and cascade to items and notes."""
    db = await get_db()
    try:
        await project_service.delete_project(db, user.id, project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None


def _member_response(row: dict[str, object]) -> MemberSummary:
    return MemberSummary(
        user_id=str(row["user_id"]),
        email=str(row["email"]),
        added_at=datetime.fromisoformat(str(row["added_at"])),
    )


@router.post("/{project_id}/members", response_model=MemberSummary, status_code=201)
async def add_project_member(
    project_id: str,
    body: AddMemberRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> MemberSummary:
    """Add a member to a project by email (owner-only, idempotent)."""
    db = await get_db()
    try:
        row = await project_service.add_project_member(
            db, user.id, project_id, body.email
        )
    except NotFoundError:
        raise HTTPException(
            status_code=404, detail="Project or user not found"
        ) from None
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.detail) from None
    return _member_response(row)


@router.delete("/{project_id}/members/{member_user_id}", status_code=204)
async def remove_project_member(
    project_id: str,
    member_user_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove a member from a project (owner-only, no-op if not a member)."""
    db = await get_db()
    try:
        await project_service.remove_project_member(
            db, user.id, project_id, member_user_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.get("/{project_id}/members", response_model=list[MemberSummary])
async def list_project_members(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[MemberSummary]:
    """List members of a project (accessible to owner and any member)."""
    db = await get_db()
    try:
        rows = await project_service.list_project_members(db, user.id, project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return [_member_response(r) for r in rows]
