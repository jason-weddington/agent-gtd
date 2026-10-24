"""Background dispatch worker — proxies runs to remote dispatch service.

Manages the lifecycle: dispatch to remote service, poll for completion,
update run status, publish SSE events. Comments are posted by the
remote dispatch service via the GTD API.
"""

import asyncio
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from agent_gtd_dispatch_protocol import DispatchMode, DispatchRequest
from agent_gtd_dispatch_protocol import RunResponse as RemoteRunResponse
from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

from agent_gtd.auth import create_token
from agent_gtd.dispatch_constants import MANAGER_DEFAULT_TIMEOUT_MINUTES
from agent_gtd.exceptions import HostFullError
from agent_gtd.identity import compute_run_attribution
from agent_gtd.models import (
    TALOS_ENGINES,
    LocalRunStatus,
    manage_engine_rejection,
)
from agent_gtd.util.tasks import supervise_task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = int(os.environ.get("DISPATCH_DEFAULT_MAX_TURNS", "100"))
POLL_INTERVAL = 15  # seconds between status polls

# Mode-specific turn budget for manage runs.
#
# ``None`` means "manage resolves its budget exactly as build and plan do" —
# which is today's behaviour, so leaving this at None changes nothing.  The
# point of the seam is that a four-hour resident manager and a thirty-minute
# builder currently share a single 100-turn budget, and the short-lived merge
# reviewer that replaces the resident manager will need a much smaller one.
# That change should get to set a number, not have to invent the plumbing.
#
# A project-level ``dispatch_max_turns`` override still wins over this value —
# an operator who set an explicit per-project budget meant it for every mode.
MANAGE_MAX_TURNS: int | None = None

# Mode-specific turn budget for REVIEW runs — the short-lived merge reviewer
# that replaced the resident manager.
#
# 40, not 100.  A reviewer's whole job is ONE completed build: read the diff,
# reconcile the item's acceptance criteria against it, run the project
# gate_command, merge up to a handful of repos, write a verdict artifact.  That
# is a bounded errand, and 40 turns is roughly double a measured worst case
# (three workspace repos, one inline fix, one re-run of the gate) — enough head
# room to finish, tight enough that a reviewer which has lost the plot stops
# instead of wandering.
#
# Note what this number is NOT: it is not comparable to the resident manager's
# 100.  The manager spent one budget on an entire rollout; the reviewers spend
# N x REVIEW_MAX_TURNS across a rollout of N items.  Aggregate turn spend is a
# DIFFERENT quantity from any single agent's budget, and the two must not be
# compared as if they measured the same thing.  The saving comes from the
# reviewer being SONNET and holding no idle context between items, not from the
# per-agent ceiling.
#
# A project-level ``dispatch_max_turns`` override still wins, same as manage.
REVIEW_MAX_TURNS: int | None = 40

# Cap on the remote `error` text mirrored onto a local run's `error_msg`.
# This is the SECOND of two truncation layers (the dispatch service applies its
# own, governed by agent_gtd_dispatch.dispatch.ERROR_TEXT_MAX_CHARS); the pair
# once clipped a failing pre-commit hook down to nothing but `Skipped` lines.
# Both layers carry the same 2000-char budget so neither can silently bind
# first again.  `runs.error_msg` is a TEXT column — nothing in the schema
# forces truncation and no migration is involved.
ERROR_MSG_MAX_CHARS = 2000

# DEFAULT manage-mode engine — Opus (claude-code), regardless of the global engine.
# This ensures the manage-mode rollout driver never accidentally downgrades to a
# cheaper model when the global is set to claude-code-sonnet.
#
# A project MAY override this via `projects.manage_engine` (NULL = use this
# default).  The default deliberately stays claude-code: a manager has a small
# turn count but a huge blast radius, so downgrading it is an explicit opt-in,
# never something a global setting can do behind the operator's back.
MANAGE_ENGINE = "claude-code"

# DEFAULT review-mode engine — Sonnet, deliberately NOT Opus.
#
# A reviewer decides one thing about one build against a written contract (the
# item's acceptance criteria and the project's gate_command), and the expensive
# half of its job — running the gate, driving git — is not model work at all.
# The resident manager was Opus because it held a whole rollout in its head;
# nothing about a per-build reviewer justifies that tier.
#
# Resolution order (see ``resolve_reviewer_engine``):
#   rollout.reviewer_engine -> project.reviewer_engine -> this default.
REVIEWER_ENGINE = "claude-code-sonnet"

# Terminal statuses from the shared dispatch-protocol package.
# When the remote run reaches one of these, we stop polling and map to a
# local status via LocalRunStatus.from_remote().
#
# DERIVED, not hand-listed. A hand-written set is exactly how `already_satisfied`
# went missing: it was added to the protocol enum AND to `from_remote`, whose
# `assert_never` guard forced that update — but nothing forces a frozenset
# literal, so the poller treated the new terminal as "still running" and looped
# forever. Two runs sat at `running` for over half an hour on 2026-09-19 while
# the dispatch service had marked them terminal, which also means `--wait` never
# returns and a Monitor never fires.
#
# Deriving from the enum minus the known non-terminals means a future protocol
# status is terminal-by-default here. That is the safe direction: treating a new
# status as terminal surfaces it immediately (it maps through `from_remote`,
# whose assert_never fails loudly if unmapped), whereas treating it as
# non-terminal hangs silently.
_NON_TERMINAL_STATUSES: frozenset[RemoteRunStatus] = frozenset(
    {
        RemoteRunStatus.pending,
        RemoteRunStatus.running,
    }
)

_TERMINAL_STATUSES: frozenset[RemoteRunStatus] = frozenset(
    status for status in RemoteRunStatus if status not in _NON_TERMINAL_STATUSES
)


# ---------------------------------------------------------------------------
# Resolution helpers (pure functions — easy to test, no DB dependency)
# ---------------------------------------------------------------------------


def resolve_agent(
    mode: str,
    project_plan_agent: str | None,
    project_build_agent: str | None,
    global_plan_agent: str,
    global_build_agent: str,
) -> str:
    """Resolve the effective agent name for a dispatch run.

    Resolution order for plan mode:
        project plan_dispatch_agent → global plan_agent_name → ""

    Resolution order for build mode:
        project build_dispatch_agent → global build_agent_name → ""

    Args:
        mode: The run mode, either ``"plan"`` or ``"build"``.
        project_plan_agent: The project's ``plan_dispatch_agent`` value, or
            ``None`` if not set.
        project_build_agent: The project's ``build_dispatch_agent`` value, or
            ``None`` if not set.
        global_plan_agent: The deployment-wide plan agent from app_settings.
        global_build_agent: The deployment-wide build agent from app_settings.

    Returns:
        The resolved agent name (may be empty string when none are set).
    """
    if mode == "plan":
        return project_plan_agent or global_plan_agent or ""
    return project_build_agent or global_build_agent or ""


def resolve_max_turns(
    project_dispatch_max_turns: int | None,
    global_default_max_turns: int,
    mode: str = "build",
) -> int:
    """Resolve the effective max_turns for a dispatch run.

    Resolution order:
        project ``dispatch_max_turns`` → mode-specific default (manage only,
        when ``MANAGE_MAX_TURNS`` is set) → deployment-wide
        ``dispatch.default_max_turns``.

    The mode branch exists so a manage run can carry a budget that differs from
    a build run's.  ``MANAGE_MAX_TURNS`` defaults to ``None``, which makes manage
    resolve exactly as build and plan do — i.e. no behavioural change until
    someone deliberately sets a manage-specific number.

    ``"review"`` uses the same seam with a number actually set:
    ``REVIEW_MAX_TURNS`` (40).  A per-decision reviewer needs far fewer turns
    than a resident manager did — see the constant's comment for why 40, and
    for why aggregate spend across N reviewers is not the same quantity as one
    manager's budget.

    Args:
        project_dispatch_max_turns: The project's ``dispatch_max_turns``
            value, or ``None`` if the project inherits the global default.
        global_default_max_turns: The deployment-wide default from
            app_settings (or the env-var fallback).
        mode: The run mode — ``"build"``, ``"plan"``, ``"manage"`` or
            ``"review"``.  Only ``"manage"`` and ``"review"`` have
            mode-specific branches today.

    Returns:
        The resolved max_turns integer.
    """
    if project_dispatch_max_turns is not None:
        return project_dispatch_max_turns
    if mode == "manage" and MANAGE_MAX_TURNS is not None:
        return MANAGE_MAX_TURNS
    if mode == "review" and REVIEW_MAX_TURNS is not None:
        return REVIEW_MAX_TURNS
    return global_default_max_turns


def resolve_reviewer_engine(
    rollout_reviewer_engine: str | None,
    project_reviewer_engine: str | None = None,
) -> str:
    """Resolve the engine a rollout's merge REVIEWERS run on.

    Resolution order — most specific wins:
        1. ``rollout.reviewer_engine`` — chosen when the rollout was
           dispatched (``POST /api/rollouts/{id}/dispatch``).
        2. ``project.reviewer_engine`` — the project's standing default.
        3. ``REVIEWER_ENGINE`` — the deployment default, Sonnet.

    Empty strings are treated as unset at every level, so a cleared column
    falls through rather than resolving to ``""``.

    Args:
        rollout_reviewer_engine: The rollout's stored override, or None/"".
        project_reviewer_engine: The project's standing default, or None/"".

    Returns:
        The resolved engine name.

    Raises:
        ValueError: If the resolved engine is not review-capable (a talos
            engine, for instance — see ``reviewer_engine_rejection``).
    """
    from agent_gtd.models import reviewer_engine_rejection

    engine = (rollout_reviewer_engine or "") or (project_reviewer_engine or "")
    engine = engine or REVIEWER_ENGINE
    rejection = reviewer_engine_rejection(engine)
    if rejection is not None:
        raise ValueError(rejection)
    return engine


def resolve_engine(
    mode: str,
    item_build_engine: str | None,
    global_engine: str | None,
    project_manage_engine: str | None = None,
) -> str:
    """Resolve effective dispatch engine.

    Resolution order:
        manage → project.manage_engine if set, else MANAGE_ENGINE (Opus /
                 claude-code); ignores the global and the item engine
        build   → item.build_engine if set, else global
        plan    → item.build_engine if set and NOT a talos-* engine, else global

    Plan honors the item's build engine, same as build, with one exception:
    talos engines are build-mode only (talos has no GTD/MCP access and the
    dispatch worker commits + pushes its own output — a plan run handed a
    talos engine would try to build and commit code instead of writing a
    spec). So when the item's build_engine is a talos engine (see
    ``TALOS_ENGINES``), plan falls back to the global engine instead.

    The global engine must be explicitly set for build and plan modes.  An unset
    global raises ``ValueError`` rather than silently falling back to a hardcoded
    literal, making misconfiguration loud — this check runs before any
    item-engine return, so an unset global still raises even when the item has
    a usable (non-talos) build_engine.

    Args:
        mode: Dispatch mode ("build", "plan", or "manage").
        item_build_engine: The item's ``build_engine`` field value, or ``None``
            if the item inherits the global engine.
        global_engine: The deployment-wide engine from app_settings, or ``None``
            if the global is not yet configured.
        project_manage_engine: The project's ``manage_engine`` override, or
            ``None``/``""`` when the project inherits ``MANAGE_ENGINE``.  Only
            consulted for manage mode.

    Returns:
        The resolved engine string.

    Raises:
        ValueError: If ``global_engine`` is unset and ``mode`` is not "manage",
            or if the project's ``manage_engine`` is not manage-capable (a
            talos engine, for instance — see ``manage_engine_rejection``).
    """
    if mode == "manage":
        # Project override wins; NULL/empty falls back to the unchanged default.
        # Never raises on an unset global — manage mode does not consult it.
        manage_engine = project_manage_engine or MANAGE_ENGINE
        rejection = manage_engine_rejection(manage_engine)
        if rejection is not None:
            # Fail fast and loudly: a manager on a non-manage-capable engine
            # would otherwise come up without the dispatch env it needs and the
            # failure would read as a model problem, not a config problem.
            raise ValueError(rejection)
        return manage_engine
    if not global_engine:
        raise ValueError(
            "dispatch.engine global setting is unset; configure a global dispatch"
            " engine in Settings before dispatching"
        )
    if mode == "build" and item_build_engine:
        return item_build_engine
    if mode == "plan" and item_build_engine and item_build_engine not in TALOS_ENGINES:
        return item_build_engine
    return global_engine


def resolve_timeout_minutes(
    mode: str,
    project_timeout: int | None,
    global_worker: int,
    global_manager: int,
) -> int:
    """Resolve the effective timeout_minutes for a dispatch run.

    Project-level override wins if set (non-None).  Otherwise, manage-mode
    runs fall back to ``global_manager`` and all other modes (build, plan)
    fall back to ``global_worker``.

    Args:
        mode: The run mode (``"manage"``, ``"build"``, ``"plan"``, etc.).
        project_timeout: The project's ``dispatch_timeout_minutes`` value, or
            ``None`` if the project inherits the global default.
        global_worker: The deployment-wide default for worker modes (build,
            plan) from app_settings (hard-coded fallback: 30).
        global_manager: The deployment-wide default for manager-mode runs from
            app_settings (fallback: ``MANAGER_DEFAULT_TIMEOUT_MINUTES``, 45).

    Returns:
        The resolved timeout_minutes integer.
    """
    if project_timeout is not None:
        return project_timeout
    if mode == "manage":
        return global_manager
    return global_worker


# ---------------------------------------------------------------------------
# Run DB updates
# ---------------------------------------------------------------------------


async def _update_run(
    db: Any,
    run_id: str,
    **fields: object,
) -> None:
    """Update fields on a claude_runs row."""
    now = datetime.now(UTC).isoformat()
    updates = ["updated_at = $1"]
    params: list[object] = [now]

    for key, value in fields.items():
        params.append(value)
        updates.append(f"{key} = ${len(params)}")

    params.append(run_id)
    sql = (
        f"UPDATE claude_runs SET {', '.join(updates)}"  # noqa: S608
        f" WHERE id = ${len(params)}"
    )
    await db.execute(sql, *params)


async def _run_status(db: Any, run_id: str) -> str:
    """Return the current ``claude_runs.status`` of *run_id* ('' if missing)."""
    row = await db.fetchrow("SELECT status FROM claude_runs WHERE id = $1", run_id)
    return str(row["status"]) if row is not None else ""


def _publish_run_event(
    db: Any,
    user_id: str,
    run_id: str,
    item_id: str | None,
    run: dict[str, Any],
    event_type: str,
    *,
    reconciled: bool = False,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Fire-and-forget SSE event publish (best effort).

    Args:
        db: Database connection pool.
        user_id: Owner of the run.
        run_id: Local run ID.
        item_id: Associated item ID (may be ``None`` for manage-mode runs).
        run: The full run dict (used to extract ``project_id``).
        event_type: SSE event type string (e.g. ``"run_completed"``).
        reconciled: When ``True``, adds ``reconciled: True`` to the payload so
            the UI can distinguish reconciled events from live-path events.
        extra: Additional payload keys merged after ``run_id`` / ``item_id``
            / ``reconciled`` (e.g. the reaper's ``reaped`` marker).
    """
    from agent_gtd.event_bus import get_event_bus
    from agent_gtd.event_helpers import best_effort_publish

    bus = get_event_bus()
    payload: dict[str, Any] = {"run_id": run_id, "item_id": item_id}
    if reconciled:
        payload["reconciled"] = True
    if extra:
        payload.update(extra)
    supervise_task(
        asyncio.create_task(
            best_effort_publish(
                bus,
                db,
                user_id=user_id,
                event_type=event_type,
                entity_type="run",
                entity_id=run_id,
                project_id=str(run["project_id"]),
                payload=payload,
                context={
                    "run_id": run_id,
                    "item_id": str(item_id) if item_id else "",
                },
            )
        ),
        context={"run_id": run_id, "event_type": event_type},
    )


# ---------------------------------------------------------------------------
# Remote dispatch client
# ---------------------------------------------------------------------------


async def _dispatch_to_remote(
    client: httpx.AsyncClient,
    item_id: str | None,
    max_turns: int,
    mode: str = "build",
    *,
    rollout_id: str | None = None,
    url: str,
    api_key: str,
    engine: str,
    agent_name: str = "",
    attribution: str = "",
    timeout_minutes: int = 30,
    callback_token: str | None = None,
) -> RemoteRunResponse:
    """POST /dispatch to the remote service. Returns the validated remote run."""
    req = DispatchRequest(
        item_id=item_id,
        max_turns=max_turns,
        mode=DispatchMode(mode),
        engine=engine,
        timeout_minutes=timeout_minutes,
        agent_name=agent_name or None,
        attribution=attribution or None,
        rollout_id=rollout_id,
        callback_token=callback_token,
    )
    resp = await client.post(
        f"{url}/dispatch",
        json=req.model_dump(exclude_none=True),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return RemoteRunResponse.model_validate(resp.json())


async def _poll_remote_run(
    client: httpx.AsyncClient,
    remote_run_id: str,
    *,
    url: str,
    api_key: str,
) -> RemoteRunResponse:
    """GET /runs/{id} from the remote service. Returns the validated remote run."""
    resp = await client.get(
        f"{url}/runs/{remote_run_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return RemoteRunResponse.model_validate(resp.json())


async def _cancel_remote_run(
    client: httpx.AsyncClient,
    remote_run_id: str,
    *,
    url: str,
    api_key: str,
) -> None:
    """POST /runs/{id}/cancel on the remote service."""
    try:
        await client.post(
            f"{url}/runs/{remote_run_id}/cancel",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )
    except Exception:
        logger.exception("Failed to cancel remote run %s", remote_run_id)


# ---------------------------------------------------------------------------
# Startup reconciliation
# ---------------------------------------------------------------------------


PLAN_NO_AC_ERROR = "Plan run wrote no acceptance criteria"


async def _plan_success_gate(
    db: Any,
    run: dict[str, Any],
    local_status: Any,
    error_msg: str,
) -> tuple[Any, str]:
    """Downgrade a plan-mode SUCCESS whose item still has no acceptance criteria.

    A plan run that finishes without writing acceptance criteria (a malformed
    tool call, or a clarifying question instead) leaves the item not ready, so
    a bare success would mislead the lead. The item is re-read fresh; missing
    items, lookup errors and non-plan runs are never downgraded.

    Returns:
        ``(status, error_msg)`` — unchanged unless the run is downgraded.
    """
    if (
        str(run.get("mode", "build")) != "plan"
        or local_status != LocalRunStatus.SUCCESS
        or not run.get("item_id")
    ):
        return local_status, error_msg

    from agent_gtd.services.comment_service import list_comments
    from agent_gtd.services.item_service import get_item as svc_get_item

    user_id = str(run["user_id"])
    item_id = str(run["item_id"])
    try:
        fresh = await svc_get_item(db, user_id, item_id)
    except Exception:
        logger.warning("Plan-run AC check could not read item %s", item_id)
        return local_status, error_msg
    if fresh.get("acceptance_criteria"):
        return local_status, error_msg

    detail = ""
    try:
        comments = await list_comments(db, user_id, item_id=item_id)
        if comments:
            last = comments[-1]
            excerpt = " ".join(str(last.get("content_markdown", "")).split())[:300]
            detail = (
                f" Agent's last comment ({last.get('created_by', 'unknown')}): "
                f'"{excerpt}"'
            )
    except Exception:
        logger.warning("Plan-run AC check could not read comments for %s", item_id)
    if not detail:
        detail = " The item has no comments; check the run transcript."
    return LocalRunStatus.FAILED, f"{PLAN_NO_AC_ERROR}.{detail}"[:ERROR_MSG_MAX_CHARS]


async def reconcile_active_runs() -> int:
    """Reconcile runs that were active when the server last stopped.

    For each active run:
    - If it has a remote_run_id, poll the dispatch service for actual status.
      - Still running → resume polling.
      - Terminal → update local status to match.
      - Unreachable → mark as failed.
    - If no remote_run_id (never dispatched remotely) → mark as failed.

    Returns the number of runs reconciled.
    """
    from agent_gtd.database import get_db, row_to_dict
    from agent_gtd.services.settings_service import get_dispatch_hosts

    db = await get_db()
    rows = await db.fetch(
        "SELECT * FROM claude_runs WHERE status IN ($1, $2, $3)",
        "pending",
        "cloning",
        "running",
    )
    if not rows:
        return 0

    now = datetime.now(UTC).isoformat()
    reconciled = 0

    for row in rows:
        run = row_to_dict(row)
        run_id = str(run["id"])
        remote_id = str(run.get("remote_run_id", ""))
        user_id = str(run["user_id"])
        item_id = str(run["item_id"]) if run.get("item_id") else None

        if not remote_id:
            # Never made it to remote dispatch — mark as failed
            await _update_run(
                db,
                run_id,
                status="failed",
                finished_at=now,
                error_msg="Server restarted before dispatch completed",
            )
            reconciled += 1
            continue

        # Determine the dispatch host URL from the run row (written at dispatch time).
        # Fall back to looking up the project owner's hosts if the column is absent/empty
        # (handles runs created before this migration).
        dispatch_url = str(run.get("dispatch_host_url", ""))
        dispatch_api_key = ""

        if dispatch_url:
            # Look up the api_key for this URL from the owner's hosts list.
            run_project_id = run.get("project_id")
            if run_project_id:
                proj_row = await db.fetchrow(
                    "SELECT user_id FROM projects WHERE id = $1", str(run_project_id)
                )
                owner_id = str(proj_row["user_id"]) if proj_row else user_id
            else:
                owner_id = user_id

            hosts = await get_dispatch_hosts(db, owner_id)
            matching = next((h for h in hosts if h["url"] == dispatch_url), None)
            if matching:
                dispatch_api_key = matching["api_key"]
            else:
                # URL recorded but no matching host — can't authenticate; fail the run.
                await _update_run(
                    db,
                    run_id,
                    status="failed",
                    finished_at=now,
                    error_msg="Dispatch host no longer configured; cannot reconcile run",
                )
                reconciled += 1
                continue
        else:
            # No dispatch_host_url on the run row (pre-migration run or dispatch failed
            # before reaching the running state). Attempt a best-effort lookup via hosts.
            run_project_id = run.get("project_id")
            if run_project_id:
                proj_row = await db.fetchrow(
                    "SELECT user_id FROM projects WHERE id = $1", str(run_project_id)
                )
                owner_id = str(proj_row["user_id"]) if proj_row else user_id
            else:
                owner_id = user_id

            hosts = await get_dispatch_hosts(db, owner_id)
            if not hosts:
                await _update_run(
                    db,
                    run_id,
                    status="failed",
                    finished_at=now,
                    error_msg="Project owner has not configured dispatch",
                )
                reconciled += 1
                continue

            # Use the first host as best-effort fallback for pre-migration runs.
            dispatch_url = hosts[0]["url"]
            dispatch_api_key = hosts[0]["api_key"]

        # Poll remote for actual status
        try:
            async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
                remote = await _poll_remote_run(
                    client, remote_id, url=dispatch_url, api_key=dispatch_api_key
                )
        except Exception:
            logger.warning(
                "Cannot reach dispatch service for run %s (remote %s), marking failed",
                run_id,
                remote_id,
            )
            await _update_run(
                db,
                run_id,
                status="failed",
                finished_at=now,
                error_msg="Dispatch service unreachable after restart",
            )
            reconciled += 1
            continue

        if remote.status in _TERMINAL_STATUSES:
            # Already finished — sync local status
            local_status = LocalRunStatus.from_remote(remote.status)
            error_msg = remote.error or ""
            local_status, error_msg = await _plan_success_gate(
                db, run, local_status, error_msg
            )
            # Truthful forwarding: record the engine the remote actually used.
            # getattr keeps this working against the currently-pinned protocol
            # (which lacks the field -> None). Never mirror the requested engine.
            ea = getattr(remote, "engine_actual", None)
            update_fields: dict[str, object] = {
                "status": local_status,
                "finished_at": now,
                "error_msg": error_msg[:ERROR_MSG_MAX_CHARS] if error_msg else "",
            }
            # Omit when None: _update_run writes every passed kwarg, so passing
            # engine_actual=None would overwrite a set value with SQL NULL.
            if ea is not None:
                update_fields["engine_actual"] = ea
            await _update_run(db, run_id, **update_fields)
            event_type = (
                "run_completed"
                if local_status == LocalRunStatus.SUCCESS
                else "run_failed"
            )
            _publish_run_event(
                db, user_id, run_id, item_id, run, event_type, reconciled=True
            )
            logger.info(
                "Reconciled run %s: remote=%s → local=%s",
                run_id,
                remote.status,
                local_status,
            )
        else:
            # Still running (pending/running) — resume polling.
            # Unknown statuses surface as ValidationError from _poll_remote_run
            # and are caught by the except block above.
            logger.info("Resuming polling for run %s (remote %s)", run_id, remote_id)
            supervise_task(
                asyncio.create_task(
                    _resume_polling(
                        db, run, remote_id, url=dispatch_url, api_key=dispatch_api_key
                    )
                ),
                context={"run_id": run_id, "event_type": "resume_polling"},
            )

        reconciled += 1

    logger.info("Reconciled %d active run(s) after restart", reconciled)
    return reconciled


async def _resume_polling(
    db: Any,
    run: dict[str, Any],
    remote_run_id: str,
    *,
    url: str,
    api_key: str,
) -> None:
    """Resume the poll loop for a run that was still active after restart."""
    run_id = str(run["id"])
    item_id = str(run["item_id"])
    user_id = str(run["user_id"])

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                try:
                    remote = await _poll_remote_run(
                        client, remote_run_id, url=url, api_key=api_key
                    )
                except Exception:
                    logger.warning(
                        "Poll failed for resumed run %s (remote %s), will retry",
                        run_id,
                        remote_run_id,
                    )
                    continue

                if remote.status in _TERMINAL_STATUSES:
                    break
                # else: still running (pending/running) — continue polling

        except asyncio.CancelledError:
            await _cancel_remote_run(client, remote_run_id, url=url, api_key=api_key)
            await _update_run(
                db,
                run_id,
                status="cancelled",
                finished_at=datetime.now(UTC).isoformat(),
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
            return

        # Map terminal status
        finished = datetime.now(UTC).isoformat()
        local_status = LocalRunStatus.from_remote(remote.status)
        error_msg = remote.error or ""
        local_status, error_msg = await _plan_success_gate(
            db, run, local_status, error_msg
        )
        # Truthful forwarding: capture the actual engine used (remote may differ
        # from requested on fallback). getattr keeps this working against the
        # currently-pinned protocol (None). Never mirror the requested engine.
        ea = getattr(remote, "engine_actual", None)
        update_fields: dict[str, object] = {
            "status": local_status,
            "finished_at": finished,
            "error_msg": error_msg[:ERROR_MSG_MAX_CHARS] if error_msg else "",
        }
        # Omit when None so we never overwrite a set value with SQL NULL.
        if ea is not None:
            update_fields["engine_actual"] = ea
        await _update_run(db, run_id, **update_fields)

        event_type = (
            "run_completed" if local_status == LocalRunStatus.SUCCESS else "run_failed"
        )
        _publish_run_event(db, user_id, run_id, item_id, run, event_type)
        logger.info("Resumed run %s completed: %s", run_id, local_status)


# ---------------------------------------------------------------------------
# Single run executor
# ---------------------------------------------------------------------------


async def execute_run(
    db: Any,
    run: dict[str, Any],
    item: dict[str, Any] | None,
    project: dict[str, Any],
) -> None:
    """Execute a dispatch run by forwarding to the remote dispatch service.

    Looks up the run owner's dispatch config from ``user_settings``.  If not
    configured, the run is immediately marked failed with a clear message.

    Updates the local run row as it progresses. The remote service handles
    cloning, Claude invocation, and posting comments to the GTD API.
    """
    from agent_gtd.services.settings_service import get_setting

    run_id = str(run["id"])
    item_id = str(run["item_id"]) if run.get("item_id") is not None else None
    user_id = str(run["user_id"])
    max_turns = int(str(run["max_turns"]))
    mode = str(run.get("mode", "build"))
    attribution = compute_run_attribution(mode, run_id)

    async def _fail_run(error_msg: str) -> None:
        """Mark the run failed and post a comment (shared across retry paths)."""
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=datetime.now(UTC).isoformat(),
            error_msg=error_msg,
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
        if item_id:
            try:
                from agent_gtd.services.comment_service import create_comment

                await create_comment(
                    db,
                    user_id,
                    item_id=item_id,
                    content_markdown=f"Dispatch failed: {error_msg}",
                    created_by=attribution,
                )
            except Exception:
                logger.warning(
                    "Failed to post dispatch failure comment to item %s", item_id
                )

    # Dispatch config belongs to the project owner, not the caller.
    # Inbox items (no project) use the caller's own config.
    project_id = run.get("project_id")
    if project_id:
        proj_row = await db.fetchrow(
            "SELECT user_id FROM projects WHERE id = $1", str(project_id)
        )
        owner_id = str(proj_row["user_id"]) if proj_row else user_id
    else:
        owner_id = user_id

    # Resolve deployment-wide engine + agent names (app_settings, not user_settings)
    global_engine = await get_setting(db, "dispatch.engine")
    item_build_engine = (
        str(item.get("build_engine")) if item and item.get("build_engine") else None
    )
    raw_manage_engine = project.get("manage_engine")
    project_manage_engine = (
        str(raw_manage_engine) if raw_manage_engine is not None else None
    )
    try:
        engine = resolve_engine(
            mode, item_build_engine, global_engine, project_manage_engine
        )
    except ValueError as exc:
        # Misconfigured engine (unset global, or a non-manage-capable
        # project manage_engine). Fail the run with the explanatory message
        # rather than letting it surface as an opaque worker traceback.
        await _fail_run(str(exc)[:500])
        return
    global_plan_agent = await get_setting(db, "dispatch.plan_agent_name") or ""
    global_build_agent = await get_setting(db, "dispatch.build_agent_name") or ""
    # Project override wins if set; fall back to the global deployment setting.
    raw_plan_agent = project.get("plan_dispatch_agent")
    project_plan_agent = str(raw_plan_agent) if raw_plan_agent is not None else None
    raw_build_agent = project.get("build_dispatch_agent")
    project_build_agent = str(raw_build_agent) if raw_build_agent is not None else None
    agent_name = resolve_agent(
        mode,
        project_plan_agent,
        project_build_agent,
        global_plan_agent,
        global_build_agent,
    )

    # Resolve effective timeout: project override > mode-specific global > hard-coded default
    raw_global_worker_timeout = await get_setting(
        db, "dispatch.default_timeout_minutes"
    )
    global_worker_timeout_minutes = (
        int(raw_global_worker_timeout) if raw_global_worker_timeout is not None else 30
    )
    raw_global_manager_timeout = await get_setting(
        db, "dispatch.manager_default_timeout_minutes"
    )
    global_manager_timeout_minutes = (
        int(raw_global_manager_timeout)
        if raw_global_manager_timeout is not None
        else MANAGER_DEFAULT_TIMEOUT_MINUTES
    )
    raw_project_timeout = project.get("dispatch_timeout_minutes")
    project_timeout_minutes = (
        int(str(raw_project_timeout)) if raw_project_timeout is not None else None
    )
    effective_timeout_minutes = resolve_timeout_minutes(
        mode,
        project_timeout_minutes,
        global_worker_timeout_minutes,
        global_manager_timeout_minutes,
    )

    # Get dispatch hosts for the project owner
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        NoCompatibleHostError,
        UnmetCapabilityError,
        pick_dispatch_host,
    )
    from agent_gtd.services.dispatch_service import effective_required_labels
    from agent_gtd.services.settings_service import get_dispatch_hosts

    # Effective requirement is the union of the project's and the item's
    # required capability labels — an item can add a constraint but never
    # relax one the project declares.
    required_labels = frozenset(effective_required_labels(project, item))

    # The run may have been cancelled (cancel-run / cancel-rollout / halt)
    # while it sat in the queue; never launch a run that is no longer pending.
    status_now = await _run_status(db, run_id)
    if status_now and status_now != "pending":
        logger.info("Run %s is %s before routing; not launching it", run_id, status_now)
        return

    hosts = await get_dispatch_hosts(db, owner_id)
    if not hosts:
        msg = "Project owner has not configured dispatch hosts"
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=datetime.now(UTC).isoformat(),
            error_msg=msg,
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
        return

    # Extract targeted host ID (None = auto-route)
    dispatch_host_id = (
        str(run["dispatch_host_id"]) if run.get("dispatch_host_id") else None
    )

    allow_drained_host = bool(run.get("allow_drained_host")) and (
        dispatch_host_id is not None
    )

    # Retry loop: pick a host and dispatch, retrying on 503 (at capacity) by
    # excluding the full host and trying the next-best candidate.
    # Targeted dispatch (dispatch_host_id set) does not retry on 503.
    excluded_urls: set[str] = set()

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        # --- Pick host and dispatch (with 503 retry for auto-routing) ---
        dispatch_url: str = ""
        dispatch_api_key: str = ""
        remote_run_id: str = ""
        routing_rationale: str = ""

        while True:
            # Pick the best host for the required engine + agent
            try:
                selected_host = await pick_dispatch_host(
                    hosts,
                    engine=engine,
                    agent_name=agent_name or None,
                    target_host_id=dispatch_host_id,
                    exclude_urls=frozenset(excluded_urls),
                    required_labels=required_labels,
                    allow_drained_host=allow_drained_host,
                )
            except (
                NoCompatibleHostError,
                UnmetCapabilityError,
                HostFullError,
                HostDrainingError,
            ) as exc:
                # Refusals (drain, no compatible host, unmet labels, full
                # host) fail the run — they are never retried against
                # another host. Log the UNTRUNCATED message so the operator
                # watching logs sees the full drain reason, then persist the
                # 500-char-capped version on the run row.
                logger.warning("Run %s refused: %s", run_id, exc)
                await _fail_run(str(exc)[:500])
                return

            dispatch_url = selected_host["url"]
            dispatch_api_key = selected_host["api_key"]
            routing_rationale = selected_host.pop("_routing_rationale", "")
            host_label = selected_host.get("label") or dispatch_url

            # --- Dispatch to remote ---
            try:
                remote_run = await _dispatch_to_remote(
                    client,
                    item_id,
                    max_turns,
                    mode,
                    rollout_id=str(run["rollout_id"])
                    if run.get("rollout_id")
                    else None,
                    url=dispatch_url,
                    api_key=dispatch_api_key,
                    engine=engine,
                    agent_name=agent_name,
                    attribution=attribution,
                    timeout_minutes=effective_timeout_minutes,
                    callback_token=create_token(user_id, run_id=run_id, run_mode=mode),
                )
                logger.info(
                    "minted run-scoped callback token run=%s mode=%s host=%s",
                    run_id,
                    mode,
                    dispatch_url,
                )
                remote_run_id = remote_run.id
                break  # success — exit retry loop
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503 and not dispatch_host_id:
                    # Auto-routing: host is at capacity — try next-best host
                    logger.warning(
                        "Host %s returned 503 (at capacity) for run %s, retrying with next-best host",
                        dispatch_url,
                        run_id,
                    )
                    excluded_urls.add(dispatch_url)
                    continue
                if exc.response.status_code == 409 and mode == "manage":
                    # The host refuses a second loop for a rollout it already
                    # drives (one loop per rollout per host). The live loop
                    # keeps driving: cancel this run, leave the rollout alone.
                    logger.info(
                        "Run %s: host %s already drives rollout %s; cancelling",
                        run_id,
                        dispatch_url,
                        run.get("rollout_id"),
                    )
                    await _update_run(
                        db,
                        run_id,
                        status="cancelled",
                        finished_at=datetime.now(UTC).isoformat(),
                        dispatch_host_url=dispatch_url,
                        error_msg=(
                            f"Rollout {run.get('rollout_id')} is already driven "
                            f"by a live loop on {host_label}; nothing started"
                        )[:ERROR_MSG_MAX_CHARS],
                    )
                    _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
                    return
                # Other HTTP error or targeted-dispatch 503: fail immediately
                logger.exception("Failed to dispatch run %s to remote service", run_id)
                await _fail_run(f"Dispatch service error: {exc}"[:500])
                return
            except Exception as exc:
                logger.exception("Failed to dispatch run %s to remote service", run_id)
                await _fail_run(f"Dispatch service error: {exc}"[:500])
                return

        # Cancelled locally while we were routing (empty remote_run_id at the
        # time, so the cancel could not be forwarded): stop it on the host now
        # and record where it went, without overwriting 'cancelled'.
        if await _run_status(db, run_id) == "cancelled":
            logger.info(
                "Run %s cancelled during routing; cancelling remote %s on %s",
                run_id,
                remote_run_id,
                dispatch_url,
            )
            await _cancel_remote_run(
                client, remote_run_id, url=dispatch_url, api_key=dispatch_api_key
            )
            await _update_run(
                db,
                run_id,
                remote_run_id=remote_run_id,
                dispatch_host_url=dispatch_url,
                engine=engine,
            )
            return

        # --- Running ---
        now = datetime.now(UTC).isoformat()
        await _update_run(
            db,
            run_id,
            status="running",
            started_at=now,
            remote_run_id=remote_run_id,
            dispatch_host_url=dispatch_url,
            engine=engine,
            routing_rationale=routing_rationale,
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_started")

        # Best-effort: surface the routing decision on the item so a human
        # can see why this host was picked without opening the run record.
        if item_id and routing_rationale:
            try:
                from agent_gtd.services.comment_service import create_comment

                await create_comment(
                    db,
                    user_id,
                    item_id=item_id,
                    content_markdown=(
                        f"Dispatched to **{host_label}** — {routing_rationale}"
                    ),
                    created_by=attribution,
                )
            except Exception:
                logger.warning(
                    "Failed to post routing-rationale comment to item %s", item_id
                )

        # --- Poll until terminal ---
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)

                try:
                    remote = await _poll_remote_run(
                        client,
                        remote_run_id,
                        url=dispatch_url,
                        api_key=dispatch_api_key,
                    )
                except Exception:
                    logger.warning(
                        "Poll failed for run %s (remote %s), will retry",
                        run_id,
                        remote_run_id,
                    )
                    continue

                if remote.status in _TERMINAL_STATUSES:
                    break
                # else: still running (pending/running) — continue polling

        except asyncio.CancelledError:
            # Local cancellation — forward to remote
            await _cancel_remote_run(
                client, remote_run_id, url=dispatch_url, api_key=dispatch_api_key
            )
            await _update_run(
                db,
                run_id,
                status="cancelled",
                finished_at=datetime.now(UTC).isoformat(),
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
            return

        # --- Map remote result to local run ---
        finished = datetime.now(UTC).isoformat()
        local_status = LocalRunStatus.from_remote(remote.status)
        error_msg = remote.error or ""
        local_status, error_msg = await _plan_success_gate(
            db, run, local_status, error_msg
        )
        # Truthful forwarding: capture the actual engine used (remote may differ
        # from requested on fallback). getattr keeps this working against the
        # currently-pinned protocol (None). Never mirror the requested engine.
        ea = getattr(remote, "engine_actual", None)
        update_fields: dict[str, object] = {
            "status": local_status,
            "finished_at": finished,
            "error_msg": error_msg[:ERROR_MSG_MAX_CHARS] if error_msg else "",
        }
        # Omit when None so we never overwrite a set value with SQL NULL.
        if ea is not None:
            update_fields["engine_actual"] = ea
        await _update_run(db, run_id, **update_fields)

        event_type = (
            "run_completed" if local_status == LocalRunStatus.SUCCESS else "run_failed"
        )
        _publish_run_event(db, user_id, run_id, item_id, run, event_type)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

# Module-level queue — set during app startup
_dispatch_queue: asyncio.Queue[str] | None = None


def get_dispatch_queue() -> asyncio.Queue[str]:
    """Get the dispatch queue (must be called after startup)."""
    assert _dispatch_queue is not None, "Dispatch worker not started"  # noqa: S101
    return _dispatch_queue


async def dispatch_worker() -> None:
    """Background worker that drains the dispatch queue."""
    global _dispatch_queue
    _dispatch_queue = asyncio.Queue()

    logger.info("Dispatch worker started")

    while True:
        run_id = await _dispatch_queue.get()
        supervise_task(
            asyncio.create_task(_process_run(run_id)),
            context={"run_id": run_id, "event_type": "process_run"},
        )


async def _process_run(run_id: str) -> None:
    """Process a single run."""
    try:
        from agent_gtd.database import get_db
        from agent_gtd.services.item_service import (
            get_item as svc_get_item,
        )
        from agent_gtd.services.project_service import (
            get_project as svc_get_project,
        )

        db = await get_db()
        # Fetch run — use a direct query since get_run needs user_id
        row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
        if row is None:
            logger.error("Run %s not found, skipping", run_id)
            return

        from agent_gtd.database import row_to_dict

        run = row_to_dict(row)

        if run["status"] not in ("pending",):
            logger.warning("Run %s status is %s, skipping", run_id, run["status"])
            return

        user_id = str(run["user_id"])
        run_mode = str(run.get("mode", "build"))
        if run_mode == "manage":
            # manage-mode runs are not scoped to a single item
            item = None
        else:
            item = await svc_get_item(db, user_id, str(run["item_id"]))
        project = await svc_get_project(db, user_id, str(run["project_id"]))

        await execute_run(db, run, item, project)

    except Exception:
        logger.exception("Fatal error processing run %s", run_id)


def enqueue_run(run_id: str) -> None:
    """Add a run to the dispatch queue."""
    queue = get_dispatch_queue()
    queue.put_nowait(run_id)
    logger.info("Enqueued run %s", run_id)


async def shutdown_worker() -> None:
    """Graceful shutdown — cancel pending queue items."""
    global _dispatch_queue
    if _dispatch_queue is not None:
        # Drain remaining items
        while not _dispatch_queue.empty():
            try:
                _dispatch_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        _dispatch_queue = None
    logger.info("Dispatch worker shut down")
