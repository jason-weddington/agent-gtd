"""Items CRUD API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_gtd.auth import get_current_user
from agent_gtd.database import decode_json_list, get_db
from agent_gtd.exceptions import NotFoundError, VersionConflictError
from agent_gtd.models import (
    CreateItemRequest,
    InboxCaptureRequest,
    ItemResponse,
    ItemStatus,
    Priority,
    UpdateItemRequest,
    User,
)
from agent_gtd.services import item_service

router = APIRouter(prefix="/api", tags=["items"])


def _item_response(row: dict[str, object]) -> ItemResponse:
    return ItemResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        title=str(row["title"]),
        description=str(row["description"]),
        status=ItemStatus(str(row["status"])),
        priority=Priority(str(row["priority"])),
        due_date=str(row["due_date"]) if row["due_date"] is not None else None,
        completed_at=(
            str(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        created_by=str(row["created_by"]),
        assigned_to=str(row["assigned_to"]),
        waiting_on=str(row["waiting_on"]),
        sort_order=float(str(row["sort_order"])),
        labels=decode_json_list(str(row["labels"])),
        version=int(str(row["version"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


@router.get("/items", response_model=list[ItemResponse])
async def list_items(
    user: Annotated[User, Depends(get_current_user)],
    item_status: Annotated[ItemStatus | None, Query(alias="status")] = None,
    project_id: str | None = None,
    priority: Priority | None = None,
) -> list[ItemResponse]:
    """List items for the current user, with optional filters."""
    db = await get_db()
    rows = await item_service.list_items(
        db,
        user.id,
        status=item_status.value if item_status else None,
        project_id=project_id,
        priority=priority.value if priority else None,
    )
    return [_item_response(r) for r in rows]


@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(
    body: CreateItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Create a new item."""
    db = await get_db()
    try:
        row = await item_service.create_item(
            db,
            user.id,
            title=body.title,
            description=body.description,
            project_id=body.project_id,
            status=body.status.value,
            priority=body.priority.value,
            due_date=body.due_date,
            assigned_to=body.assigned_to,
            waiting_on=body.waiting_on,
            sort_order=body.sort_order,
            labels=body.labels,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _item_response(row)


@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Get a single item by ID."""
    db = await get_db()
    try:
        row = await item_service.get_item(db, user.id, item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None
    return _item_response(row)


@router.patch("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    body: UpdateItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Update an existing item."""
    db = await get_db()
    try:
        row = await item_service.update_item(
            db,
            user.id,
            item_id,
            title=body.title,
            description=body.description,
            project_id=body.project_id,
            project_id_set="project_id" in body.model_fields_set,
            status=body.status.value if body.status else None,
            priority=body.priority.value if body.priority else None,
            due_date=body.due_date,
            due_date_set="due_date" in body.model_fields_set,
            assigned_to=body.assigned_to,
            waiting_on=body.waiting_on,
            sort_order=body.sort_order,
            labels=body.labels,
            version=body.version,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None
    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=e.detail) from None
    return _item_response(row)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete an item."""
    db = await get_db()
    try:
        await item_service.delete_item(db, user.id, item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Item not found") from None


# --- Inbox shortcuts ---


@router.get("/inbox", response_model=list[ItemResponse])
async def list_inbox(
    user: Annotated[User, Depends(get_current_user)],
) -> list[ItemResponse]:
    """List inbox items (status=inbox)."""
    db = await get_db()
    rows = await item_service.list_inbox(db, user.id)
    return [_item_response(r) for r in rows]


@router.post("/inbox", response_model=ItemResponse, status_code=201)
async def capture_inbox(
    body: InboxCaptureRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Quick capture to inbox — title only."""
    db = await get_db()
    row = await item_service.inbox_capture(db, user.id, body.title)
    return _item_response(row)


# --- Project-scoped item endpoints ---


@router.get("/projects/{project_id}/items", response_model=list[ItemResponse])
async def list_project_items(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[ItemResponse]:
    """List items for a specific project."""
    db = await get_db()
    try:
        rows = await item_service.list_project_items(db, user.id, project_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return [_item_response(r) for r in rows]


@router.post(
    "/projects/{project_id}/items",
    response_model=ItemResponse,
    status_code=201,
)
async def create_project_item(
    project_id: str,
    body: CreateItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Create an item in a specific project."""
    db = await get_db()
    try:
        row = await item_service.create_project_item(
            db,
            user.id,
            project_id,
            title=body.title,
            description=body.description,
            status=body.status.value,
            priority=body.priority.value,
            due_date=body.due_date,
            assigned_to=body.assigned_to,
            waiting_on=body.waiting_on,
            sort_order=body.sort_order,
            labels=body.labels,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return _item_response(row)
