"""Projects CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.dispatch_constants import (
    MAX_TIMEOUT_MINUTES,
    MAX_TURNS,
    MIN_TIMEOUT_MINUTES,
    MIN_TURNS,
)
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


_DISPATCH_ONLY_FIELDS = {
    "dispatch_max_turns",
    "dispatch_timeout_minutes",
    "plan_dispatch_agent",
    "build_dispatch_agent",
}


def _project_response(
    row: dict[str, object],
    caller_user_id: str | None = None,
    description_preview: str | None = None,
) -> ProjectResponse:
    raw_turns = row.get("dispatch_max_turns")
    raw_timeout = row.get("dispatch_timeout_minutes")
    raw_plan_agent = row.get("plan_dispatch_agent")
    raw_build_agent = row.get("build_dispatch_agent")
    raw_owner_email = row.get("owner_email")
    raw_member_count = row.get("member_count")
    raw_total_items = row.get("total_items")
    is_owner = (
        (str(row.get("user_id", "")) == caller_user_id)
        if caller_user_id is not None
        else None
    )
    return ProjectResponse(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        status=ProjectStatus(str(row["status"])),
        area=str(row["area"]),
        git_origin=str(row.get("git_origin", "")),
        kb_project_ref=str(row.get("kb_project_ref", "")),
        dispatch_max_turns=int(str(raw_turns)) if raw_turns is not None else None,
        dispatch_timeout_minutes=int(str(raw_timeout))
        if raw_timeout is not None
        else None,
        plan_dispatch_agent=str(raw_plan_agent) if raw_plan_agent is not None else None,
        build_dispatch_agent=str(raw_build_agent)
        if raw_build_agent is not None
        else None,
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        is_owner=is_owner,
        owner_email=str(raw_owner_email) if raw_owner_email is not None else None,
        member_count=(
            int(str(raw_member_count)) if raw_member_count is not None else None
        ),
        total_items=int(str(raw_total_items)) if raw_total_items is not None else 0,
        description_preview=description_preview,
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
    return [
        _project_response(
            r,
            caller_user_id=user.id,
            description_preview=r.get("description_preview"),
        )
        for r in rows
    ]


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
    return _project_response(
        row,
        caller_user_id=user.id,
        description_preview=row.get("description_preview"),
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectResponse:
    """Update an existing project."""
    # Ownership guard: only the project owner may change dispatch-only fields.
    if body.model_fields_set & _DISPATCH_ONLY_FIELDS:
        db = await get_db()
        proj = await db.fetchrow(
            "SELECT user_id FROM projects WHERE id = $1", project_id
        )
        if proj is None or str(proj["user_id"]) != user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the project owner can edit dispatch settings",
            )

    # Validate dispatch_max_turns bounds if explicitly provided and non-null.
    if (
        "dispatch_max_turns" in body.model_fields_set
        and body.dispatch_max_turns is not None
        and not (MIN_TURNS <= body.dispatch_max_turns <= MAX_TURNS)
    ):
        raise HTTPException(
            status_code=400,
            detail=f"dispatch_max_turns must be between {MIN_TURNS} and {MAX_TURNS}",
        )

    # Validate dispatch_timeout_minutes bounds if explicitly provided and non-null.
    if (
        "dispatch_timeout_minutes" in body.model_fields_set
        and body.dispatch_timeout_minutes is not None
        and not (
            MIN_TIMEOUT_MINUTES <= body.dispatch_timeout_minutes <= MAX_TIMEOUT_MINUTES
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"dispatch_timeout_minutes must be between "
                f"{MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}"
            ),
        )

    # Use model_fields_set to distinguish "absent" from "explicit null" for
    # nullable override columns.
    clear_dispatch_max_turns = (
        "dispatch_max_turns" in body.model_fields_set
        and body.dispatch_max_turns is None
    )
    clear_dispatch_timeout_minutes = (
        "dispatch_timeout_minutes" in body.model_fields_set
        and body.dispatch_timeout_minutes is None
    )
    clear_plan_dispatch_agent = (
        "plan_dispatch_agent" in body.model_fields_set
        and body.plan_dispatch_agent is None
    )
    clear_build_dispatch_agent = (
        "build_dispatch_agent" in body.model_fields_set
        and body.build_dispatch_agent is None
    )

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
            dispatch_max_turns=body.dispatch_max_turns,
            clear_dispatch_max_turns=clear_dispatch_max_turns,
            dispatch_timeout_minutes=body.dispatch_timeout_minutes,
            clear_dispatch_timeout_minutes=clear_dispatch_timeout_minutes,
            plan_dispatch_agent=body.plan_dispatch_agent,
            clear_plan_dispatch_agent=clear_plan_dispatch_agent,
            build_dispatch_agent=body.build_dispatch_agent,
            clear_build_dispatch_agent=clear_build_dispatch_agent,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _project_response(row, caller_user_id=user.id)


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
