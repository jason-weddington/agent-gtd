"""Project CRUD service functions."""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg

from agent_gtd.database import row_to_dict
from agent_gtd.exceptions import NotFoundError


async def verify_project_ownership(
    db: asyncpg.Pool, project_id: str, user_id: str
) -> None:
    """Verify that a project exists and belongs to the user.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT id FROM projects WHERE id = $1 AND user_id = $2",
        project_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Project", project_id)


async def list_projects(
    db: asyncpg.Pool,
    user_id: str,
    *,
    status: str | None = None,
    area: str | None = None,
) -> list[dict[str, Any]]:
    """List projects for a user, with optional filters."""
    clauses = ["user_id = $1"]
    params: list[object] = [user_id]

    if status is not None:
        clauses.append(f"status = ${len(params) + 1}")
        params.append(status)
    if area is not None:
        clauses.append(f"area = ${len(params) + 1}")
        params.append(area)

    where = " AND ".join(clauses)
    rows = await db.fetch(
        f"SELECT * FROM projects WHERE {where} ORDER BY created_at DESC",  # noqa: S608
        *params,
    )
    return [row_to_dict(r) for r in rows]


async def create_project(
    db: asyncpg.Pool,
    user_id: str,
    *,
    name: str,
    description: str = "",
    status: str = "active",
    area: str = "",
) -> dict[str, Any]:
    """Create a new project and return its row data."""
    now = datetime.now(UTC).isoformat()
    project_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO projects "
        "(id, user_id, name, description, status, area, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        project_id,
        user_id,
        name,
        description,
        status,
        area,
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def get_project(
    db: asyncpg.Pool, user_id: str, project_id: str
) -> dict[str, Any]:
    """Get a single project by ID.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT * FROM projects WHERE id = $1 AND user_id = $2",
        project_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Project", project_id)
    return row_to_dict(row)


async def update_project(
    db: asyncpg.Pool,
    user_id: str,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    area: str | None = None,
) -> dict[str, Any]:
    """Update a project. Only non-None fields are changed.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)

    updates: list[str] = []
    params: list[object] = []

    if name is not None:
        params.append(name)
        updates.append(f"name = ${len(params)}")
    if description is not None:
        params.append(description)
        updates.append(f"description = ${len(params)}")
    if status is not None:
        params.append(status)
        updates.append(f"status = ${len(params)}")
    if area is not None:
        params.append(area)
        updates.append(f"area = ${len(params)}")

    if updates:
        params.append(datetime.now(UTC).isoformat())
        updates.append(f"updated_at = ${len(params)}")
        params.append(project_id)

        sql = f"UPDATE projects SET {', '.join(updates)} WHERE id = ${len(params)}"  # noqa: S608
        await db.execute(sql, *params)

    row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def delete_project(db: asyncpg.Pool, user_id: str, project_id: str) -> None:
    """Delete a project and cascade to items and notes.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    await db.execute("DELETE FROM projects WHERE id = $1", project_id)
