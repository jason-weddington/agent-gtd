"""Dispatch run CRUD service functions.

Manages claude_runs records for tracking headless Claude Code dispatches.
The actual subprocess lifecycle (Phase 2B) is not yet implemented here —
this module handles the data layer only.
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from agent_gtd.database import decode_json_list, row_to_dict
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

# On the HTTP route path (dispatch_routes.dispatch_item ->
# dispatch_worker.enqueue_run -> execute_run) a run is board-pending with an
# empty remote_run_id only while execute_run routes it (dispatch_router.
# _fetch_host_info timeout 5.0s, then _dispatch_to_remote POST timeout 30.0s,
# per host on 503), at most about 35s per host; host-side queueing happens only
# after the POST returns, when execute_run has already set status 'running' and
# remote_run_id. Runs created through mcp_backend.LocalBackend.dispatch_item are
# never enqueued, so they are pending forever by construction and reaping them
# is intended. A reap whose age_s is under 2x this threshold is the signature of
# a legitimately-routing run being reaped and means this constant is too low.
STALE_PENDING_RUN_SECONDS: int = 600
STALE_PENDING_RUN_ERROR: str = (
    "Orphaned pending run reaped: never handed to a dispatch host within "
    f"{STALE_PENDING_RUN_SECONDS}s of creation (no remote run id)"
)
# Note: manage-mode runs are created via dispatch_rollout_run (item_id=NULL) and
# therefore never appear in the _ACTIVE_STATUSES check below, which filters by item_id.


def _parse_created_at(run: dict[str, Any]) -> datetime | None:
    """Return created_at as an aware datetime, or None if unavailable."""
    raw = run.get("created_at")
    try:
        if isinstance(raw, datetime):
            parsed = raw
        elif isinstance(raw, str):
            parsed = datetime.fromisoformat(raw)
        else:
            return None
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _is_stale_pending_run(run: dict[str, Any], now: datetime) -> bool:
    """True iff the run is a pending run with no remote id older than the TTL."""
    if run.get("status") != "pending" or run.get("remote_run_id"):
        return False
    created = _parse_created_at(run)
    if created is None:
        return False
    return now - created > timedelta(seconds=STALE_PENDING_RUN_SECONDS)


def _decode_label_list(raw: object) -> list[str]:
    """Tolerantly decode a required_labels value: list, JSON text, or absent.

    Handles both a service-layer dict (already decoded to a list) and a raw
    DB row dict (JSON text, as fetched directly by dispatch_worker), so this
    works against either shape without forcing callers to decode first.
    """
    if isinstance(raw, list):
        return [str(label) for label in raw]
    if raw:
        return decode_json_list(str(raw))
    return []


def effective_required_labels(
    project: dict[str, Any] | None, item: dict[str, Any] | None
) -> list[str]:
    """Return the effective capability-label requirement for a dispatch.

    The effective requirement is the UNION of the project's and the item's
    ``required_labels`` — an item may add a constraint on top of its
    project's, but can never relax one the project declares. Labels are
    already normalized (lowercase, stripped) at write time; this just unions
    the two sets and returns them sorted for deterministic output.
    """
    project_labels = _decode_label_list((project or {}).get("required_labels"))
    item_labels = _decode_label_list((item or {}).get("required_labels"))
    return sorted(set(project_labels) | set(item_labels))


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
    dispatch_host_id: str | None = None,
) -> dict[str, Any]:
    """Create a new dispatch run for an item.

    Validates:
    - Item exists and belongs to user
    - Item has a project with git_origin configured (monorepo) or a non-empty
      repos list (workspace)
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
    if project.get("repo_mode") == "workspace":
        if not project.get("workspace_repos"):
            raise NotFoundError(
                "repos",
                f"Workspace project '{project['name']}' has no repos configured",
            )
    else:
        if not project.get("git_origin"):
            raise NotFoundError(
                "git_origin",
                f"Project '{project['name']}' has no git_origin configured",
            )

    # Check for active runs on this item; reap stale orphaned pending ones.
    active_rows = [
        row_to_dict(r)
        for r in await db.fetch(
            "SELECT id, status, remote_run_id, created_at FROM claude_runs"
            " WHERE item_id = $1 AND status IN ($2, $3, $4)",
            item_id,
            *_ACTIVE_STATUSES,
        )
    ]
    now_dt = datetime.now(UTC)
    non_stale = [r for r in active_rows if not _is_stale_pending_run(r, now_dt)]
    for r in non_stale:
        if (
            r.get("status") == "pending"
            and not r.get("remote_run_id")
            and _parse_created_at(r) is None
        ):
            logger.warning(
                "stale_pending_unparseable_created_at run_id=%s created_at=%r",
                r["id"],
                r.get("created_at"),
            )
    if non_stale:
        first = non_stale[0]
        first_created = _parse_created_at(first)
        age_s: int | str = (
            int((now_dt - first_created).total_seconds())
            if first_created is not None
            else "unknown"
        )
        logger.info(
            "dispatch_blocked_active_run item_id=%s run_id=%s status=%s"
            " remote_run_id=%r age_s=%s threshold_s=%d",
            item_id,
            first["id"],
            first["status"],
            first.get("remote_run_id"),
            age_s,
            STALE_PENDING_RUN_SECONDS,
        )
        raise RunActiveError(item_id, str(first["id"]))
    for r in active_rows:
        reaped_at = now_dt.isoformat()
        await db.execute(
            "UPDATE claude_runs SET status = 'failed', error_msg = $1,"
            " finished_at = $2, updated_at = $3"
            " WHERE id = $4 AND status = 'pending'"
            " AND (remote_run_id = '' OR remote_run_id IS NULL)",
            STALE_PENDING_RUN_ERROR,
            reaped_at,
            reaped_at,
            r["id"],
        )
        check = await db.fetchrow(
            "SELECT status FROM claude_runs WHERE id = $1", r["id"]
        )
        if check is None or check["status"] != "failed":
            logger.info(
                "stale_pending_reap_lost_race run_id=%s item_id=%s", r["id"], item_id
            )
            raise RunActiveError(item_id, str(r["id"]))
        reaped_created = _parse_created_at(r)
        logger.warning(
            "stale_pending_reap run_id=%s item_id=%s age_s=%d threshold_s=%d"
            " created_at=%s outcome=reaped",
            r["id"],
            item_id,
            int((now_dt - reaped_created).total_seconds()) if reaped_created else 0,
            STALE_PENDING_RUN_SECONDS,
            r.get("created_at"),
        )

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
        # Child-build inheritance: an explicitly passed dispatch_host_id always
        # wins; otherwise the run inherits the rollout's stored pin (NULL =
        # auto-routing).
        if dispatch_host_id is None:
            inherited = rollout_build.get("dispatch_host_id")
            dispatch_host_id = str(inherited) if inherited is not None else None

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

    # Friendly early rejection: refuse a pin to a draining host BEFORE the
    # run row exists. OWNER-scoped (the pin validates against the project
    # owner's host list, like dispatch_rollout_run and the route pre-flight)
    # — using the caller's user_id would silently no-op for member-initiated
    # dispatches. Catches both explicit pins and rollout-inherited ones
    # (the inheritance block above runs before this check).
    if dispatch_host_id is not None:
        hosts = await settings_service.get_dispatch_hosts(db, str(project["user_id"]))
        host = next((h for h in hosts if h["id"] == dispatch_host_id), None)
        if host is not None and host.get("drain_reason") is not None:
            host_label = host.get("label") or host.get("url", "unknown")
            drain_reason = str(host["drain_reason"])
            logger.warning(
                "Refused dispatch to draining host %s (reason=%r) item=%s",
                host_label,
                drain_reason,
                item_id,
            )
            raise ValidationError(
                f"Dispatch host '{host_label}' is draining: {drain_reason}. "
                "Dispatch refused; retry when the host returns to rotation."
            )

    if max_turns is None:
        stored = await settings_service.get_setting(db, "dispatch.default_max_turns")
        global_default = int(stored) if stored is not None else DEFAULT_MAX_TURNS
        # Project-level override wins if set; falls back to the global default.
        raw_project_turns = project.get("dispatch_max_turns")
        project_dispatch_max_turns = (
            int(raw_project_turns) if raw_project_turns is not None else None
        )
        effective_max_turns = resolve_max_turns(
            project_dispatch_max_turns, global_default, mode
        )
    else:
        effective_max_turns = max_turns

    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    branch = make_branch_name(item_id, item["title"])

    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  max_turns, mode, rollout_id, created_at, updated_at, dispatch_host_id)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
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
        dispatch_host_id,
    )

    try:
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
    except Exception as exc:
        from agent_gtd.dispatch_worker import ERROR_MSG_MAX_CHARS

        cleanup = "marked_failed"
        setup_error = (
            f"Dispatch setup failed after run creation: {type(exc).__name__}: {exc}"
        )
        try:
            failed_at = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE claude_runs SET status = 'failed', error_msg = $1,"
                " finished_at = $2, updated_at = $3"
                " WHERE id = $4 AND status = 'pending'",
                setup_error[:ERROR_MSG_MAX_CHARS],
                failed_at,
                failed_at,
                run_id,
            )
        except Exception:
            cleanup = "cleanup_error"
            logger.exception("dispatch_setup_cleanup_failed run_id=%s", run_id)
        logger.exception(
            "dispatch_setup_failed run_id=%s item_id=%s rollout_id=%s mode=%s"
            " cleanup=%s",
            run_id,
            item_id,
            rollout_id,
            mode,
            cleanup,
        )
        raise

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
    *,
    dispatch_host_id: str | None = None,
    reviewer_engine: str | None = None,
) -> dict[str, Any]:
    """Create a manage-mode dispatch run scoped to a rollout (no item_id).

    Validates:
    - Rollout exists and is owned by user
    - Rollout has status="pending" (one-shot)
    - Workspace projects: non-empty workspace_repos required
    - Monorepo projects: non-empty git_origin required
    - When dispatch_host_id is set: it must exist in the project owner's
      dispatch host list (capacity/engine checks stay in pick_dispatch_host,
      enforced by the dispatch worker at execution time).

    Creates a claude_runs row with item_id=NULL, mode="manage". When
    dispatch_host_id is set, the pin is written to both the run and the
    rollout row (child build runs inherit it from the rollout).
    Transitions rollout pending → running.

    ``reviewer_engine`` is the engine this rollout's short-lived merge
    REVIEWERS run on.  It is RESOLVED here (rollout override → project default
    → deployment default) and persisted on the rollout row, so the dispatch
    worker reads one settled value off the rollout instead of re-deriving the
    order on the far side of the wire.

    Raises:
        NotFoundError: If rollout not found or not owned by user, if the
            project is missing its required repo configuration, or if the
            pinned dispatch host does not exist.
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
    if project.get("repo_mode") == "workspace":
        if not project.get("workspace_repos"):
            raise NotFoundError(
                "repos",
                f"Workspace project '{project['name']}' has no repos configured",
            )
    else:
        if not project.get("git_origin"):
            raise NotFoundError(
                "git_origin",
                f"Project '{project['name']}' has no git_origin configured",
            )

    from agent_gtd.dispatch_worker import (
        DEFAULT_MAX_TURNS,
        resolve_max_turns,
        resolve_reviewer_engine,
    )
    from agent_gtd.services import settings_service

    raw_project_reviewer_engine = project.get("reviewer_engine")
    try:
        effective_reviewer_engine = resolve_reviewer_engine(
            reviewer_engine,
            str(raw_project_reviewer_engine)
            if raw_project_reviewer_engine is not None
            else None,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    # Host pin validation: existence check only (owner-scoped, like the
    # dispatch_item route). Capacity/engine compatibility is enforced by
    # pick_dispatch_host in the dispatch worker, which fails the run loudly.
    if dispatch_host_id is not None:
        hosts = await settings_service.get_dispatch_hosts(db, str(project["user_id"]))
        if not any(h["id"] == dispatch_host_id for h in hosts):
            raise NotFoundError("DispatchHost", dispatch_host_id)
        # Refuse a pin to a draining host: the rollout row stays pending and
        # the caller is told to wait, not to re-route (docs/host-drain.md).
        pinned = next(h for h in hosts if h["id"] == dispatch_host_id)
        pinned_drain_reason = pinned.get("drain_reason")
        if pinned_drain_reason is not None:
            host_label = pinned.get("label") or pinned.get("url", "unknown")
            logger.warning(
                "Refused rollout dispatch to draining host %s (reason=%r) rollout=%s",
                host_label,
                pinned_drain_reason,
                rollout_id,
            )
            raise ValidationError(
                f"Dispatch host '{host_label}' is draining: "
                f"{pinned_drain_reason}. "
                "Dispatch refused; retry when the host returns to rotation."
            )

    stored = await settings_service.get_setting(db, "dispatch.default_max_turns")
    global_default = int(stored) if stored is not None else DEFAULT_MAX_TURNS
    raw_project_turns = project.get("dispatch_max_turns")
    project_dispatch_max_turns = (
        int(raw_project_turns) if raw_project_turns is not None else None
    )
    # This is the manage-mode launch path — mode is manage by construction.
    effective_max_turns = resolve_max_turns(
        project_dispatch_max_turns, global_default, "manage"
    )

    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    branch = make_branch_name(rollout_id, "manage")

    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  max_turns, mode, rollout_id, created_at, updated_at,"
        "  dispatch_host_id)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
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
        dispatch_host_id,
    )

    # Persist the pin at rollout level so child build runs inherit it.
    if dispatch_host_id is not None:
        await db.execute(
            "UPDATE autonomous_rollouts"
            " SET dispatch_host_id = $1, updated_at = $2 WHERE id = $3",
            dispatch_host_id,
            now,
            rollout_id,
        )

    # Persist the settled reviewer engine on the rollout — this is what the
    # dispatch worker reads when it launches a reviewer for a completed build.
    await db.execute(
        "UPDATE autonomous_rollouts"
        " SET reviewer_engine = $1, updated_at = $2 WHERE id = $3",
        effective_reviewer_engine,
        now,
        rollout_id,
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
    """Cancel a single dispatched run.

    Cancelling a run that is already in a terminal status is an idempotent
    no-op: the current row is returned unchanged and nothing is forwarded.
    Runs owned by a rollout (``rollout_id`` set or ``mode == 'manage'``) are
    refused with ``ValidationError``; use cancel-rollout or halt-rollout.

    For an active run the local row is updated to ``cancelled`` and the cancel
    is best-effort forwarded to the dispatch host that owns the run (matched on
    ``dispatch_host_url``; legacy dispatch config only when that is empty).
    Remote call failures do not roll back the local state.

    Raises:
        NotFoundError: If run not found or not accessible to the user.
        ValidationError: If the run belongs to a rollout.
    """
    run = await get_run(db, user_id, run_id)
    if run["status"] not in _ACTIVE_STATUSES:
        logger.info(
            "cancel_run: noop run_id=%s status=%s actor=%s",
            run_id,
            run["status"],
            user_id,
        )
        return run

    rollout_id = str(run.get("rollout_id") or "")
    if run.get("mode") == "manage" or rollout_id:
        raise ValidationError(
            f"run {run_id} belongs to rollout {rollout_id};"
            " use cancel-rollout or halt-rollout"
        )

    prior_status = run["status"]
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

    # Resolve the forward target (best-effort; local cancel wins).
    remote_run_id = str(run.get("remote_run_id", "") or "")
    resolution = "no_remote_run_id"
    host_url = ""
    api_key = ""
    if remote_run_id:
        from agent_gtd.services.settings_service import (
            get_dispatch_config,
            get_dispatch_hosts,
        )

        # Dispatch config belongs to the project owner (mirrors execute_run).
        project_id_val = run.get("project_id")
        if project_id_val:
            proj_row = await db.fetchrow(
                "SELECT user_id FROM projects WHERE id = $1", str(project_id_val)
            )
            owner_id = str(proj_row["user_id"]) if proj_row else user_id
        else:
            owner_id = user_id

        run_host_url = str(run.get("dispatch_host_url") or "")
        if run_host_url:
            resolution = "unmatched_host"
            for host in await get_dispatch_hosts(db, owner_id):
                if host["url"] == run_host_url:
                    resolution = "owning_host"
                    host_url = str(host["url"])
                    api_key = str(host["api_key"])
                    break
        else:
            settings = await get_dispatch_config(db, owner_id)
            if settings:
                resolution = "legacy_config"
                host_url = str(settings["url"])
                api_key = str(settings["api_key"])
            else:
                resolution = "no_config"

    logger.info(
        "cancel_run: forward run_id=%s remote_run_id=%s actor=%s"
        " prior_status=%s resolution=%s host=%s",
        run_id,
        remote_run_id,
        user_id,
        prior_status,
        resolution,
        host_url,
    )
    if resolution == "no_remote_run_id":
        logger.warning(
            "cancel_run: run %s has no remote_run_id; skip dispatch forward",
            run_id,
        )
    if resolution == "unmatched_host":
        logger.warning(
            "cancel_run: run %s dispatch_host_url=%s: no configured host matches;"
            " cannot forward cancel",
            run_id,
            run.get("dispatch_host_url"),
        )

    if host_url:
        import httpx

        try:
            async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
                resp = await client.post(
                    f"{host_url}/runs/{remote_run_id}/cancel",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    logger.info(
                        "cancel_run: forwarded cancel to dispatch for run %s"
                        " (remote_run_id=%s resolution=%s host=%s)",
                        run_id,
                        remote_run_id,
                        resolution,
                        host_url,
                    )
                elif resp.status_code == 404:
                    logger.warning(
                        "cancel_run: remote run not found; possibly already"
                        " terminal (run_id=%s remote_run_id=%s resolution=%s"
                        " host=%s)",
                        run_id,
                        remote_run_id,
                        resolution,
                        host_url,
                    )
                else:
                    logger.warning(
                        "cancel_run: unexpected status %s forwarding cancel"
                        " (run_id=%s body=%s resolution=%s host=%s)",
                        resp.status_code,
                        run_id,
                        resp.text[:200],
                        resolution,
                        host_url,
                    )
        except Exception:
            logger.warning(
                "cancel_run: exception forwarding cancel for run %s"
                " (resolution=%s host=%s)",
                run_id,
                resolution,
                host_url,
                exc_info=True,
            )

    from agent_gtd.event_bus import get_event_bus
    from agent_gtd.event_helpers import best_effort_publish

    await best_effort_publish(
        bus=get_event_bus(),
        db=db,
        user_id=user_id,
        event_type="run_failed",
        entity_type="run",
        entity_id=run_id,
        project_id=str(run["project_id"]) if run.get("project_id") else None,
        payload={"run_id": run_id, "item_id": run.get("item_id")},
        context={"run_id": run_id, "item_id": str(run.get("item_id") or "")},
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
