"""Dispatch run CRUD service functions.

Manages claude_runs records for tracking headless Claude Code dispatches.
The actual subprocess lifecycle (Phase 2B) is not yet implemented here —
this module handles the data layer only.
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from agent_gtd.database import row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import (
    BlockersUnresolvedError,
    NotFoundError,
    RolloutItemLockedError,
    RunActiveError,
    ValidationError,
)
from agent_gtd.services.item_service import (
    get_item,
    get_unresolved_blockers,
    update_item,
)
from agent_gtd.services.project_service import get_project

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("pending", "cloning", "running")
# Note: manage-mode runs are created via dispatch_rollout_run (item_id=NULL) and
# therefore never appear in the _ACTIVE_STATUSES check below, which filters by item_id.


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
    rollout_id: str | None = None,
) -> dict[str, Any]:
    """Create a new dispatch run for an item.

    Validates:
    - Item exists and belongs to user
    - Item has a project with git_origin configured
    - No other active run exists for this item
    - When mode="manage" with rollout_id: wave exists, is owned by caller,
      and has status="pending" (manage-mode launch is one-shot).

    Raises:
        NotFoundError: If item or project not found.
        RunActiveError: If an active run already exists for this item.
        ValidationError: If manage-mode wave pre-conditions are not met.
    """
    # Block manage-mode dispatch through this path. Manage runs must be created
    # via dispatch_rollout_run (which sets item_id=NULL). Allowing manage-mode
    # here would key the run to a rollout item's ID, causing RunActiveError when
    # the manage agent later tries to dispatch a child build for that same item.
    if mode == "manage":
        raise ValidationError(
            "Use dispatch_rollout to launch manage-mode runs; "
            "dispatch_item(mode='manage') is not supported"
        )

    item = await get_item(db, user_id, item_id)

    # Wave lock guard: items in an active wave cannot be re-dispatched
    if item.get("locked_by_rollout_id"):
        raise RolloutItemLockedError(item_id, str(item["locked_by_rollout_id"]))

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

    # Build-mode wave pre-flight: validate wave exists, is owned, and is running
    if mode == "build" and rollout_id is not None:
        from agent_gtd.services.rollout_service import _get_rollout

        rollout_build = await _get_rollout(db, user_id, rollout_id)
        if rollout_build["status"] != "running":
            raise ValidationError(
                f"Rollout {rollout_id} is not running"
                f" (status={rollout_build['status']}); "
                "build-mode dispatch requires a running rollout"
            )

    # Manage-mode pre-flight: validate the rollout exists, is owned, and is pending
    rollout: dict[str, Any] | None = None
    if mode == "manage" and rollout_id is not None:
        from agent_gtd.services.rollout_service import _get_rollout

        rollout = await _get_rollout(db, user_id, rollout_id)
        if rollout["status"] != "pending":
            raise ValidationError(
                f"Rollout {rollout_id} is not pending (status={rollout['status']}); "
                "manage-mode launch is one-shot"
            )

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
        "  max_turns, mode, rollout_id, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        run_id,
        item_id,
        project_id,
        user_id,
        "pending",
        branch,
        effective_max_turns,
        mode,
        rollout_id,
        now,
        now,
    )

    # Build-mode wave linkage: transition rollout_items ready → dispatched
    if mode == "build" and rollout_id is not None:
        await db.execute(
            "UPDATE rollout_items"
            " SET status = 'dispatched', claude_run_id = $1"
            " WHERE rollout_id = $2 AND item_id = $3 AND status = 'ready'",
            run_id,
            rollout_id,
            item_id,
        )
        # Append item_dispatched event and fan out via SSE
        from agent_gtd.services.rollout_service import (
            _append_rollout_event,
            _publish_rollout_event,
        )

        item_dispatched_event = await _append_rollout_event(
            db,
            rollout_id,
            kind="item_dispatched",
            actor="manager",
            payload={"item_id": item_id, "run_id": run_id},
        )
        _publish_rollout_event(
            db,
            lead_user_id=user_id,
            rollout_event=item_dispatched_event,
            project_id=str(project_id),
        )

    # Manage-mode wave status flip: pending → running
    if mode == "manage" and rollout_id is not None and rollout is not None:
        from agent_gtd.services.rollout_service import start_rollout

        await start_rollout(
            db,
            user_id,
            rollout_id,
            actor="manager",
            extra_payload={"manage_run_id": run_id},
        )

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None  # noqa: S101

    # Set item status to active — skip for manage mode, where the item_id is a
    # positional placeholder that the manage agent ignores entirely; its status
    # must not be touched (Bug 2 of kb-01515).
    if mode != "manage":
        try:
            await update_item(db, user_id, item_id, status="active")
        except Exception as exc:
            logger.warning(
                "Failed to set item status to active after dispatch",
                extra={
                    "item_id": item_id,
                    "exc_class": type(exc).__name__,
                    "exc_msg": str(exc),
                },
            )

    return row_to_dict(row)


async def dispatch_rollout_run(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Create a manage-mode dispatch run scoped to a rollout (no item_id).

    Validates:
    - Rollout exists and is owned by user
    - Rollout has status="pending" (one-shot)

    Creates a claude_runs row with item_id=NULL, mode="manage".
    Transitions rollout pending → running.

    Raises:
        NotFoundError: If rollout not found or not owned by user.
        ValidationError: If rollout is not in pending status.
    """
    from agent_gtd.services.rollout_service import _get_rollout, start_rollout

    rollout = await _get_rollout(db, user_id, rollout_id)
    if rollout["status"] != "pending":
        raise ValidationError(
            f"Rollout {rollout_id} is not pending (status={rollout['status']}); "
            "manage-mode launch is one-shot"
        )

    project_id = str(rollout["project_id"])
    project = await get_project(db, user_id, project_id)
    if not project.get("git_origin"):
        raise NotFoundError(
            "git_origin",
            f"Project '{project['name']}' has no git_origin configured",
        )

    from agent_gtd.dispatch_worker import DEFAULT_MAX_TURNS, resolve_max_turns
    from agent_gtd.services import settings_service

    stored = await settings_service.get_setting(db, "dispatch.default_max_turns")
    global_default = int(stored) if stored is not None else DEFAULT_MAX_TURNS
    raw_project_turns = project.get("dispatch_max_turns")
    project_dispatch_max_turns = (
        int(raw_project_turns) if raw_project_turns is not None else None
    )
    effective_max_turns = resolve_max_turns(project_dispatch_max_turns, global_default)

    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    branch = make_branch_name(rollout_id, "manage")

    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  max_turns, mode, rollout_id, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        run_id,
        None,  # item_id is NULL for manage-mode rollout runs
        project_id,
        user_id,
        "pending",
        branch,
        effective_max_turns,
        "manage",
        rollout_id,
        now,
        now,
    )

    # Transition rollout pending → running
    await start_rollout(
        db,
        user_id,
        rollout_id,
        actor="manager",
        extra_payload={"manage_run_id": run_id},
    )

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None  # noqa: S101
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

    After updating the local row to ``cancelled``, best-effort forwards the
    cancel to the remote dispatch service.  Remote call failures do not roll
    back the local state — local intent always wins.

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
    updated = row_to_dict(row)

    # Forward cancel to the dispatch service (best-effort; local cancel wins).
    remote_run_id = str(run.get("remote_run_id", "") or "")
    if not remote_run_id:
        logger.warning(
            "cancel_run: run %s has no remote_run_id; skip dispatch forward",
            run_id,
        )
    else:
        import httpx

        from agent_gtd.services.settings_service import get_dispatch_config

        # Dispatch config belongs to the project owner (mirrors execute_run).
        project_id_val = run.get("project_id")
        if project_id_val:
            proj_row = await db.fetchrow(
                "SELECT user_id FROM projects WHERE id = $1", str(project_id_val)
            )
            owner_id = str(proj_row["user_id"]) if proj_row else user_id
        else:
            owner_id = user_id

        settings = await get_dispatch_config(db, owner_id)
        if not settings:
            logger.warning(
                "cancel_run: no dispatch config for owner of run %s;"
                " cannot forward cancel",
                run_id,
            )
        else:
            try:
                async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
                    resp = await client.post(
                        f"{settings['url']}/runs/{remote_run_id}/cancel",
                        headers={"Authorization": f"Bearer {settings['api_key']}"},
                        timeout=15.0,
                    )
                    if resp.status_code == 200:
                        logger.info(
                            "cancel_run: forwarded cancel to dispatch for run %s"
                            " (remote_run_id=%s)",
                            run_id,
                            remote_run_id,
                        )
                    elif resp.status_code == 404:
                        logger.warning(
                            "cancel_run: remote run not found; possibly already"
                            " terminal (run_id=%s remote_run_id=%s)",
                            run_id,
                            remote_run_id,
                        )
                    else:
                        logger.warning(
                            "cancel_run: unexpected status %s forwarding cancel"
                            " (run_id=%s body=%s)",
                            resp.status_code,
                            run_id,
                            resp.text[:200],
                        )
            except Exception:
                logger.warning(
                    "cancel_run: exception forwarding cancel for run %s",
                    run_id,
                    exc_info=True,
                )

    return updated


async def list_failed_runs(
    db: DbPool,
    user_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List failed / timeout runs across the user's accessible projects.

    Returns runs with status in {failed, timeout} enriched with item_title
    (nullable) and project_name, ordered by finished_at DESC.

    Args:
        db: Database pool.
        user_id: The calling user's ID — only runs in their accessible projects.
        limit: Maximum number of rows to return (capped at 100).

    Returns:
        List of enriched run dicts.
    """
    clamped = min(max(1, limit), 100)
    rows = await db.fetch(
        "SELECT r.*, i.title AS item_title, p.name AS project_name"
        " FROM claude_runs r"
        " LEFT JOIN items i ON i.id = r.item_id"
        " JOIN projects p ON p.id = r.project_id"
        " WHERE r.status IN ('failed', 'timeout')"
        " AND r.project_id IN ("
        "   SELECT id FROM projects WHERE user_id = $1"
        "   UNION"
        "   SELECT project_id FROM project_members WHERE user_id = $2"
        " )"
        " ORDER BY r.finished_at DESC"
        " LIMIT $3",
        user_id,
        user_id,
        clamped,
    )
    return [row_to_dict(r) for r in rows]


async def list_stale_completed_runs(
    db: DbPool,
    user_id: str,
    hours: int = 72,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List successful build-mode runs whose item status was not advanced.

    A "stale" run is a build-mode run with status='success' whose linked item
    is still in a non-terminal status (not review / done / cancelled), meaning
    the agent completed but skipped the status-flip step.

    Only build-mode runs with a non-null item_id within the past ``hours``
    hours are considered.

    Args:
        db: Database pool.
        user_id: The calling user's ID — only runs in their accessible projects.
        hours: Look-back window in hours (default 72).
        limit: Maximum number of rows to return (capped at 100).

    Returns:
        List of enriched run dicts including item_title, project_name, and
        item_status.
    """
    from datetime import timedelta

    clamped = min(max(1, limit), 100)
    cutoff = (datetime.now(UTC) - timedelta(hours=max(1, hours))).isoformat()

    # Note: $1/$2 must appear before $3/$4 in the SQL string so that the
    # $N → ? positional substitution used by SqlitePool binds values correctly.
    rows = await db.fetch(
        "SELECT r.*, i.title AS item_title, p.name AS project_name,"
        "       i.status AS item_status"
        " FROM claude_runs r"
        " JOIN items i ON i.id = r.item_id"
        " JOIN projects p ON p.id = r.project_id"
        " WHERE r.project_id IN ("
        "   SELECT id FROM projects WHERE user_id = $1"
        "   UNION"
        "   SELECT project_id FROM project_members WHERE user_id = $2"
        " )"
        " AND r.status = 'success'"
        " AND r.mode = 'build'"
        " AND r.item_id IS NOT NULL"
        " AND r.finished_at > $3"
        " AND i.status NOT IN ('review', 'done', 'cancelled')"
        " ORDER BY r.finished_at DESC"
        " LIMIT $4",
        user_id,
        user_id,
        cutoff,
        clamped,
    )
    return [row_to_dict(r) for r in rows]


async def reconcile_orphans(db: DbPool) -> int:
    """Mark any active runs as failed (called on startup).

    Fetches affected rows first so we can publish a ``run_failed`` SSE event
    per row and log each run ID individually.  The bulk UPDATE is preserved for
    efficiency; per-row events are published after the UPDATE completes.

    Returns the number of runs marked as failed.
    """
    rows = await db.fetch(
        "SELECT id, user_id, project_id, item_id FROM claude_runs"
        " WHERE status IN ($1, $2, $3)",
        *_ACTIVE_STATUSES,
    )
    if not rows:
        return 0

    count = len(rows)
    now = datetime.now(UTC).isoformat()

    # Bulk update — efficient single query, aiosqlite-safe (no RETURNING clause)
    await db.execute(
        "UPDATE claude_runs SET status = 'failed',"
        " error_msg = 'Server restarted while run was active',"
        " finished_at = $1, updated_at = $2"
        " WHERE status IN ($3, $4, $5)",
        now,
        now,
        *_ACTIVE_STATUSES,
    )

    # Publish one SSE event per orphaned run and log each run ID
    from agent_gtd.event_bus import get_event_bus

    bus = get_event_bus()
    for row in rows:
        run_id = str(row["id"])
        user_id = str(row["user_id"])
        project_id = str(row["project_id"]) if row.get("project_id") else ""
        item_id = str(row["item_id"]) if row.get("item_id") else None

        logger.info("Reconciling orphaned run %s (marking as failed)", run_id)
        try:
            asyncio.create_task(  # noqa: RUF006
                bus.publish(
                    db,
                    user_id=user_id,
                    event_type="run_failed",
                    entity_type="run",
                    entity_id=run_id,
                    project_id=project_id,
                    payload={
                        "run_id": run_id,
                        "item_id": item_id,
                        "reconciled": True,
                        "error_msg": "Server restarted while run was active",
                    },
                )
            )
        except Exception:
            logger.exception(
                "Failed to publish run_failed event for orphaned run %s", run_id
            )

    logger.info("Reconciled %d orphaned dispatch runs", count)
    return count
