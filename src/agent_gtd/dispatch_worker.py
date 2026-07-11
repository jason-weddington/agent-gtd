"""Background dispatch worker — proxies runs to remote dispatch service.

Manages the lifecycle: dispatch to remote service, poll for completion,
update run status, publish SSE events. Comments are posted by the
remote dispatch service via the GTD API.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from agent_gtd_dispatch_protocol import DispatchMode, DispatchRequest
from agent_gtd_dispatch_protocol import RunResponse as RemoteRunResponse
from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

from agent_gtd.auth import create_token
from agent_gtd.exceptions import HostFullError
from agent_gtd.identity import compute_run_attribution
from agent_gtd.models import LocalRunStatus
from agent_gtd.util.tasks import supervise_task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = int(os.environ.get("DISPATCH_DEFAULT_MAX_TURNS", "100"))
POLL_INTERVAL = 15  # seconds between status polls

# Manage-mode is always pinned to Opus (claude-code), regardless of the global engine.
# This ensures the manage-mode rollout driver never accidentally downgrades to a
# cheaper model when the global is set to claude-code-sonnet.
MANAGE_ENGINE = "claude-code"

# Terminal statuses from the shared dispatch-protocol package.
# When the remote run reaches one of these, we stop polling and map to a
# local status via LocalRunStatus.from_remote().
_TERMINAL_STATUSES: frozenset[RemoteRunStatus] = frozenset(
    {
        RemoteRunStatus.succeeded,
        RemoteRunStatus.failed,
        RemoteRunStatus.timed_out,
        RemoteRunStatus.cancelled,
    }
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
) -> int:
    """Resolve the effective max_turns for a dispatch run.

    Project-level override wins if set (non-None); otherwise falls back to
    the deployment-wide ``dispatch.default_max_turns`` setting.

    Args:
        project_dispatch_max_turns: The project's ``dispatch_max_turns``
            value, or ``None`` if the project inherits the global default.
        global_default_max_turns: The deployment-wide default from
            app_settings (or the env-var fallback).

    Returns:
        The resolved max_turns integer.
    """
    if project_dispatch_max_turns is not None:
        return project_dispatch_max_turns
    return global_default_max_turns


def resolve_engine(
    mode: str,
    item_build_engine: str | None,
    global_engine: str | None,
) -> str:
    """Resolve effective dispatch engine.

    Resolution order:
        manage → always MANAGE_ENGINE (Opus / claude-code), ignores the global
        build   → item.build_engine if set, else global
        plan    → global

    The global engine must be explicitly set for build and plan modes.  An unset
    global raises ``ValueError`` rather than silently falling back to a hardcoded
    literal, making misconfiguration loud.

    Args:
        mode: Dispatch mode ("build", "plan", or "manage").
        item_build_engine: The item's ``build_engine`` field value, or ``None``
            if the item inherits the global engine.
        global_engine: The deployment-wide engine from app_settings, or ``None``
            if the global is not yet configured.

    Returns:
        The resolved engine string.

    Raises:
        ValueError: If ``global_engine`` is unset and ``mode`` is not "manage".
    """
    if mode == "manage":
        return MANAGE_ENGINE  # pinned to Opus; never raises on unset global
    if not global_engine:
        raise ValueError(
            "dispatch.engine global setting is unset; configure a global dispatch"
            " engine in Settings before dispatching"
        )
    if mode == "build" and item_build_engine:
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
            app_settings (hard-coded fallback: 240).

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


def _publish_run_event(
    db: Any,
    user_id: str,
    run_id: str,
    item_id: str | None,
    run: dict[str, Any],
    event_type: str,
    *,
    reconciled: bool = False,
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
    """
    from agent_gtd.event_bus import get_event_bus
    from agent_gtd.event_helpers import best_effort_publish

    bus = get_event_bus()
    payload: dict[str, Any] = {"run_id": run_id, "item_id": item_id}
    if reconciled:
        payload["reconciled"] = True
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
            # Truthful forwarding: record the engine the remote actually used.
            # getattr keeps this working against the currently-pinned protocol
            # (which lacks the field -> None). Never mirror the requested engine.
            ea = getattr(remote, "engine_actual", None)
            update_fields: dict[str, object] = {
                "status": local_status,
                "finished_at": now,
                "error_msg": error_msg[:500] if error_msg else "",
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
        # Truthful forwarding: capture the actual engine used (remote may differ
        # from requested on fallback). getattr keeps this working against the
        # currently-pinned protocol (None). Never mirror the requested engine.
        ea = getattr(remote, "engine_actual", None)
        update_fields: dict[str, object] = {
            "status": local_status,
            "finished_at": finished,
            "error_msg": error_msg[:500] if error_msg else "",
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
    engine = resolve_engine(mode, item_build_engine, global_engine)
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
        else 240
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
        NoCompatibleHostError,
        pick_dispatch_host,
    )
    from agent_gtd.services.settings_service import get_dispatch_hosts

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

    # Retry loop: pick a host and dispatch, retrying on 503 (at capacity) by
    # excluding the full host and trying the next-best candidate.
    # Targeted dispatch (dispatch_host_id set) does not retry on 503.
    excluded_urls: set[str] = set()

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

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        # --- Pick host and dispatch (with 503 retry for auto-routing) ---
        dispatch_url: str = ""
        dispatch_api_key: str = ""
        remote_run_id: str = ""

        while True:
            # Pick the best host for the required engine + agent
            try:
                selected_host = await pick_dispatch_host(
                    hosts,
                    engine=engine,
                    agent_name=agent_name or None,
                    target_host_id=dispatch_host_id,
                    exclude_urls=frozenset(excluded_urls),
                )
            except (NoCompatibleHostError, HostFullError) as exc:
                await _fail_run(str(exc)[:500])
                return

            dispatch_url = selected_host["url"]
            dispatch_api_key = selected_host["api_key"]

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
                    callback_token=create_token(user_id),
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
                # Other HTTP error or targeted-dispatch 503: fail immediately
                logger.exception("Failed to dispatch run %s to remote service", run_id)
                await _fail_run(f"Dispatch service error: {exc}"[:500])
                return
            except Exception as exc:
                logger.exception("Failed to dispatch run %s to remote service", run_id)
                await _fail_run(f"Dispatch service error: {exc}"[:500])
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
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_started")

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
        # Truthful forwarding: capture the actual engine used (remote may differ
        # from requested on fallback). getattr keeps this working against the
        # currently-pinned protocol (None). Never mirror the requested engine.
        ea = getattr(remote, "engine_actual", None)
        update_fields: dict[str, object] = {
            "status": local_status,
            "finished_at": finished,
            "error_msg": error_msg[:500] if error_msg else "",
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
