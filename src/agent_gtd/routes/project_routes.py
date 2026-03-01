"""Projects CRUD API routes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db, row_to_dict
from agent_gtd.models import (
    CreateProjectRequest,
    ProjectResponse,
    ProjectStatus,
    UpdateProjectRequest,
    User,
)

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
    clauses = ["user_id = ?"]
    params: list[object] = [user.id]

    if project_status is not None:
        clauses.append("status = ?")
        params.append(project_status.value)
    if area is not None:
        clauses.append("area = ?")
        params.append(area)

    where = " AND ".join(clauses)
    cursor = await db.execute(
        f"SELECT * FROM projects WHERE {where} ORDER BY created_at DESC",  # noqa: S608
        tuple(params),
    )
    rows = await cursor.fetchall()
    return [_project_response(row_to_dict(r)) for r in rows]


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Create a new project."""
    now = datetime.now(UTC).isoformat()
    project_id = str(uuid.uuid4())

    db = await get_db()
    await db.execute(
        "INSERT INTO projects "
        "(id, user_id, name, description, status, area, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            user.id,
            body.name,
            body.description,
            body.status.value,
            body.area,
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Insert failed")
    return _project_response(row_to_dict(row))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Get a single project by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user.id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return _project_response(row_to_dict(row))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Update an existing project."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user.id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    updates: list[str] = []
    params: list[object] = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description)
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status.value)
    if body.area is not None:
        updates.append("area = ?")
        params.append(body.area)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(project_id)

        sql = f"UPDATE projects SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Update failed")
    return _project_response(row_to_dict(row))


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a project and cascade to items and notes."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user.id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()
