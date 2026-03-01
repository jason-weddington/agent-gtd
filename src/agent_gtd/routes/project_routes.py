"""Projects CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError
from agent_gtd.models import (
    CreateProjectRequest,
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
