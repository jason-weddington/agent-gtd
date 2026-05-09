"""Dispatch run CRUD service functions.

Manages claude_runs records for tracking headless Claude Code dispatches.
The actual subprocess lifecycle (Phase 2B) is not yet implemented here —
this module handles the data layer only.
"""

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from agent_gtd.database import row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import BlockersUnresolvedError, NotFoundError, RunActiveError
from agent_gtd.services.item_service import (
    get_item,
    get_unresolved_blockers,
    update_item,
)
from agent_gtd.services.project_service import get_project

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("pending", "cloning", "running")


def make_branch_name(item_id: str, title: str) -> str:
    """Build a git branch name from an item ID and title."""
    short_id = item_id[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
    return f"feat/{short_id}-{slug}"


async def create_run(
    db: DbPool,
    user_id: str,
    item_id: str,
    *,
    max_turns: int | None = None,
    mode: str = "build",
) -> dict[str, Any]:
    """Create a new dispatch run for an item.

    Validates:
    - Item exists and belongs to user
    - Item has a project with git_origin configured
    - No other active run exists for this item

    Raises:
        NotFoundError: If item or project not found.
        RunActiveError: If an active run already exists for this item.
    """
    item = await get_item(db, user_id, item_id)
    project_id = item.get("project_id")
    if not project_id:
        raise NotFoundError("Project", "none (item has no project)")

    project = await get_project(db, user_id, project_id)
    if not project.get("git_origin"):
        raise NotFoundError(
            "git_origin",
            f"Project '{project['name']}' has no git_origin configured",
        )

    # Check for active run on this item
    existing = await db.fetchrow(
        "SELECT id FROM claude_runs WHERE item_id = $1 AND status IN ($2, $3, $4)",
        item_id,
        *_ACTIVE_STATUSES,
    )
    if existing:
        raise RunActiveError(item_id, str(existing["id"]))

    # Blocker enforcement: cannot dispatch an item with unresolved blockers
    unresolved = await get_unresolved_blockers(db, item_id)
    if unresolved:
        raise BlockersUnresolvedError("dispatch this item", unresolved)

    from agent_gtd.dispatch_worker import DEFAULT_MAX_TURNS, resolve_max_turns
    from agent_gtd.services import settings_service

    if max_turns is None:
        stored = await settings_service.get_setting(db, "dispatch.default_max_turns")
        global_default = int(stored) if stored is not None else DEFAULT_MAX_TURNS
        # Project-level override wins if set; falls back to the global default.
        raw_project_turns = project.get("dispatch_max_turns")
        project_dispatch_max_turns = (
            int(raw_project_turns) if raw_project_turns is not None else None
        )
        effective_max_turns = resolve_max_turns(
            project_dispatch_max_turns, global_default
        )
    else:
        effective_max_turns = max_turns

    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    branch = make_branch_name(item_id, item["title"])

    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  max_turns, mode, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        run_id,
        item_id,
        project_id,
        user_id,
        "pending",
        branch,
        effective_max_turns,
        mode,
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None  # noqa: S101

    # Set item status to active — backend owns this, regardless of dispatch origin
    try:
        await update_item(db, user_id, item_id, status="active")
    except Exception:
        logger.exception(
            "Failed to set item %s status to active after dispatch", item_id
        )

    return row_to_dict(row)


async def get_run(
    db: DbPool,
    user_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Get a single run by ID.

    Raises:
        NotFoundError: If run not found or not owned by user.
    """
    row = await db.fetchrow(
        "SELECT * FROM claude_runs WHERE id = $1 AND user_id = $2",
        run_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Run", run_id)
    return row_to_dict(row)


async def list_runs(
    db: DbPool,
    user_id: str,
    *,
    item_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    scope: Literal["user", "accessible_projects"] = "user",
) -> list[dict[str, Any]]:
    """List runs, optionally filtered by item, project, and/or status.

    Args:
        db: Database pool.
        user_id: The calling user's ID.
        item_id: Optional item ID filter.
        project_id: Optional project ID filter.
        status: Optional comma-separated status filter.
        scope: ``"user"`` (default) returns only runs owned by the caller.
            ``"accessible_projects"`` returns runs in all projects the caller
            can access (owned or shared), regardless of who dispatched them.
    """
    if scope == "accessible_projects":
        # Replace the user_id ownership guard with a project-membership subquery.
        # Pass user_id twice (as $1 and $2) for SQLite compatibility — asyncpg
        # also accepts the same value at distinct parameter positions.
        clauses: list[str] = [
            "project_id IN ("
            "SELECT id FROM projects WHERE user_id = $1 "
            "UNION "
            "SELECT project_id FROM project_members WHERE user_id = $2"
            ")"
        ]
        params: list[object] = [user_id, user_id]
    else:
        clauses = ["user_id = $1"]
        params = [user_id]

    if item_id is not None:
        params.append(item_id)
        clauses.append(f"item_id = ${len(params)}")
    if project_id is not None:
        params.append(project_id)
        clauses.append(f"project_id = ${len(params)}")
    if status is not None:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            params.append(statuses[0])
            clauses.append(f"status = ${len(params)}")
        else:
            placeholders = ", ".join(
                f"${len(params) + i + 1}" for i in range(len(statuses))
            )
            params.extend(statuses)
            clauses.append(f"status IN ({placeholders})")

    where = " AND ".join(clauses)
    rows = await db.fetch(
        f"SELECT r.*, u.email AS dispatched_by_email"  # noqa: S608
        " FROM claude_runs r"
        " LEFT JOIN users u ON u.id = r.user_id"
        f" WHERE {where}"
        " ORDER BY r.created_at DESC",
        *params,
    )
    return [row_to_dict(r) for r in rows]


async def cancel_run(
    db: DbPool,
    user_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Cancel a run. Only active runs can be cancelled.

    Raises:
        NotFoundError: If run not found or not owned by user.
    """
    run = await get_run(db, user_id, run_id)
    if run["status"] not in _ACTIVE_STATUSES:
        raise NotFoundError("Run", f"{run_id} (not active, status={run['status']})")

    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE claude_runs SET status = $1, finished_at = $2, updated_at = $3"
        " WHERE id = $4",
        "cancelled",
        now,
        now,
        run_id,
    )

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def reconcile_orphans(db: DbPool) -> int:
    """Mark any active runs as failed (called on startup).

    Returns the number of runs marked as failed.
    """
    # Count first, then update — works with both asyncpg and aiosqlite
    row = await db.fetchrow(
        "SELECT COUNT(*) AS cnt FROM claude_runs WHERE status IN ($1, $2, $3)",
        *_ACTIVE_STATUSES,
    )
    count = int(row["cnt"]) if row else 0

    if count:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE claude_runs SET status = 'failed',"
            " error_msg = 'Server restarted while run was active',"
            " finished_at = $1, updated_at = $2"
            " WHERE status IN ($3, $4, $5)",
            now,
            now,
            *_ACTIVE_STATUSES,
        )
        logger.info("Reconciled %d orphaned dispatch runs", count)
    return count
