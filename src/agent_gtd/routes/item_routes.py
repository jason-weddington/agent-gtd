"""Items CRUD API routes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from agent_gtd.auth import get_current_user
from agent_gtd.database import decode_json_list, encode_json_list, get_db, row_to_dict
from agent_gtd.models import (
    CreateItemRequest,
    InboxCaptureRequest,
    ItemResponse,
    ItemStatus,
    Priority,
    UpdateItemRequest,
    User,
)

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


async def _verify_project_ownership(
    db: aiosqlite.Connection, project_id: str, user_id: str
) -> None:
    """Verify that a project exists and belongs to the user."""
    cursor = await db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
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
    clauses = ["user_id = ?"]
    params: list[object] = [user.id]

    if item_status is not None:
        clauses.append("status = ?")
        params.append(item_status.value)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if priority is not None:
        clauses.append("priority = ?")
        params.append(priority.value)

    where = " AND ".join(clauses)
    cursor = await db.execute(
        f"SELECT * FROM items WHERE {where} ORDER BY sort_order, created_at DESC",  # noqa: S608
        tuple(params),
    )
    rows = await cursor.fetchall()
    return [_item_response(row_to_dict(r)) for r in rows]


@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(
    body: CreateItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Create a new item."""
    db = await get_db()

    if body.project_id is not None:
        await _verify_project_ownership(db, body.project_id, user.id)

    now = datetime.now(UTC).isoformat()
    item_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, priority, "
        "due_date, created_by, assigned_to, waiting_on, sort_order, labels, "
        "created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            body.project_id,
            user.id,
            body.title,
            body.description,
            body.status.value,
            body.priority.value,
            body.due_date,
            "human",
            body.assigned_to,
            body.waiting_on,
            body.sort_order,
            encode_json_list(body.labels),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Insert failed")
    return _item_response(row_to_dict(row))


@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Get a single item by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM items WHERE id = ? AND user_id = ?",
        (item_id, user.id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )
    return _item_response(row_to_dict(row))


@router.patch("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    body: UpdateItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Update an existing item."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT * FROM items WHERE id = ? AND user_id = ?",
        (item_id, user.id),
    )
    existing = await cursor.fetchone()
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )
    existing_dict = row_to_dict(existing)

    updates: list[str] = []
    params: list[object] = []

    if body.title is not None:
        updates.append("title = ?")
        params.append(body.title)
    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description)

    # project_id: use model_fields_set to distinguish "not sent" from "sent as null"
    if "project_id" in body.model_fields_set:
        if body.project_id is not None:
            await _verify_project_ownership(db, body.project_id, user.id)
        updates.append("project_id = ?")
        params.append(body.project_id)

    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status.value)

        # Auto-set completed_at when transitioning to done
        old_status = str(existing_dict["status"])
        if body.status == ItemStatus.DONE and old_status != ItemStatus.DONE:
            updates.append("completed_at = ?")
            params.append(datetime.now(UTC).isoformat())
        elif body.status != ItemStatus.DONE and old_status == ItemStatus.DONE:
            updates.append("completed_at = ?")
            params.append(None)

    if body.priority is not None:
        updates.append("priority = ?")
        params.append(body.priority.value)

    # due_date: use model_fields_set for nullable field
    if "due_date" in body.model_fields_set:
        updates.append("due_date = ?")
        params.append(body.due_date)

    if body.assigned_to is not None:
        updates.append("assigned_to = ?")
        params.append(body.assigned_to)
    if body.waiting_on is not None:
        updates.append("waiting_on = ?")
        params.append(body.waiting_on)
    if body.sort_order is not None:
        updates.append("sort_order = ?")
        params.append(body.sort_order)
    if body.labels is not None:
        updates.append("labels = ?")
        params.append(encode_json_list(body.labels))

    if updates:
        # Increment version on every update
        updates.append("version = version + 1")
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(item_id)

        sql = f"UPDATE items SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Update failed")
    return _item_response(row_to_dict(row))


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete an item."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM items WHERE id = ? AND user_id = ?",
        (item_id, user.id),
    )
    if await cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )

    await db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    await db.commit()


# --- Inbox shortcuts ---


@router.get("/inbox", response_model=list[ItemResponse])
async def list_inbox(
    user: Annotated[User, Depends(get_current_user)],
) -> list[ItemResponse]:
    """List inbox items (status=inbox)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM items WHERE user_id = ? AND status = ? "
        "ORDER BY sort_order, created_at DESC",
        (user.id, ItemStatus.INBOX.value),
    )
    rows = await cursor.fetchall()
    return [_item_response(row_to_dict(r)) for r in rows]


@router.post("/inbox", response_model=ItemResponse, status_code=201)
async def capture_inbox(
    body: InboxCaptureRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ItemResponse:
    """Quick capture to inbox — title only."""
    now = datetime.now(UTC).isoformat()
    item_id = str(uuid.uuid4())
    db = await get_db()

    await db.execute(
        "INSERT INTO items "
        "(id, user_id, title, status, priority, created_by, labels, "
        "created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            user.id,
            body.title,
            ItemStatus.INBOX.value,
            Priority.NORMAL.value,
            "human",
            encode_json_list([]),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Insert failed")
    return _item_response(row_to_dict(row))


# --- Project-scoped item endpoints ---


@router.get("/projects/{project_id}/items", response_model=list[ItemResponse])
async def list_project_items(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> list[ItemResponse]:
    """List items for a specific project."""
    db = await get_db()
    await _verify_project_ownership(db, project_id, user.id)

    cursor = await db.execute(
        "SELECT * FROM items WHERE project_id = ? AND user_id = ? "
        "ORDER BY sort_order, created_at DESC",
        (project_id, user.id),
    )
    rows = await cursor.fetchall()
    return [_item_response(row_to_dict(r)) for r in rows]


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
    await _verify_project_ownership(db, project_id, user.id)

    now = datetime.now(UTC).isoformat()
    item_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, priority, "
        "due_date, created_by, assigned_to, waiting_on, sort_order, labels, "
        "created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            project_id,
            user.id,
            body.title,
            body.description,
            body.status.value,
            body.priority.value,
            body.due_date,
            "human",
            body.assigned_to,
            body.waiting_on,
            body.sort_order,
            encode_json_list(body.labels),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Insert failed")
    return _item_response(row_to_dict(row))
