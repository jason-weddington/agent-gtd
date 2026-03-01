"""Project CRUD service functions."""

import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from agent_gtd.database import row_to_dict
from agent_gtd.exceptions import NotFoundError


async def verify_project_ownership(
    db: aiosqlite.Connection, project_id: str, user_id: str
) -> None:
    """Verify that a project exists and belongs to the user.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    cursor = await db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    )
    if await cursor.fetchone() is None:
        raise NotFoundError("Project", project_id)


async def list_projects(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    status: str | None = None,
    area: str | None = None,
) -> list[dict[str, Any]]:
    """List projects for a user, with optional filters."""
    clauses = ["user_id = ?"]
    params: list[object] = [user_id]

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if area is not None:
        clauses.append("area = ?")
        params.append(area)

    where = " AND ".join(clauses)
    cursor = await db.execute(
        f"SELECT * FROM projects WHERE {where} ORDER BY created_at DESC",  # noqa: S608
        tuple(params),
    )
    rows = await cursor.fetchall()
    return [row_to_dict(r) for r in rows]


async def create_project(
    db: aiosqlite.Connection,
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
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, user_id, name, description, status, area, now, now),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def get_project(
    db: aiosqlite.Connection, user_id: str, project_id: str
) -> dict[str, Any]:
    """Get a single project by ID.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    cursor = await db.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise NotFoundError("Project", project_id)
    return row_to_dict(row)


async def update_project(
    db: aiosqlite.Connection,
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
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if area is not None:
        updates.append("area = ?")
        params.append(area)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(project_id)

        sql = f"UPDATE projects SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def delete_project(
    db: aiosqlite.Connection, user_id: str, project_id: str
) -> None:
    """Delete a project and cascade to items and notes.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()
