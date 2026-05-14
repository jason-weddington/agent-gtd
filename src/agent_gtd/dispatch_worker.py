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

from agent_gtd.identity import compute_run_attribution

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = int(os.environ.get("DISPATCH_DEFAULT_MAX_TURNS", "100"))
_MAX_CONCURRENT_DEFAULT = int(os.environ.get("DISPATCH_MAX_CONCURRENT", "6"))
POLL_INTERVAL = 15  # seconds between status polls

# Status mapping: remote dispatch API -> local run statuses
_TERMINAL_STATUSES = {"succeeded", "failed", "timed_out", "cancelled"}
_STATUS_MAP = {
    "succeeded": "success",
    "failed": "failed",
    "timed_out": "timeout",
    "cancelled": "cancelled",
}


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


def resolve_timeout_minutes(
    project_dispatch_timeout_minutes: int | None,
    global_default_timeout_minutes: int,
) -> int:
    """Resolve the effective timeout_minutes for a dispatch run.

    Project-level override wins if set (non-None); otherwise falls back to
    the deployment-wide ``dispatch.default_timeout_minutes`` setting.

    Args:
        project_dispatch_timeout_minutes: The project's
            ``dispatch_timeout_minutes`` value, or ``None`` if the project
            inherits the global default.
        global_default_timeout_minutes: The deployment-wide default from
            app_settings (hard-coded fallback: 30).

    Returns:
        The resolved timeout_minutes integer.
    """
    if project_dispatch_timeout_minutes is not None:
        return project_dispatch_timeout_minutes
    return global_default_timeout_minutes


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
    item_id: str,
    run: dict[str, Any],
    event_type: str,
) -> None:
    """Fire-and-forget SSE event publish (best effort)."""
    try:
        from agent_gtd.event_bus import get_event_bus

        bus = get_event_bus()
        asyncio.create_task(
            bus.publish(
                db,
                user_id=user_id,
                event_type=event_type,
                entity_type="run",
                entity_id=run_id,
                project_id=str(run["project_id"]),
                payload={"run_id": run_id, "item_id": item_id},
            )
        )
    except Exception:
        logger.exception("Failed to publish %s event", event_type)


# ---------------------------------------------------------------------------
# Remote dispatch client
# ---------------------------------------------------------------------------


async def _dispatch_to_remote(
    client: httpx.AsyncClient,
    item_id: str,
    max_turns: int,
    mode: str = "build",
    *,
    rollout_id: str | None = None,
    url: str,
    api_key: str,
    engine: str = "claude",
    agent_name: str = "",
    attribution: str = "",
    timeout_minutes: int = 30,
) -> dict[str, Any]:
    """POST /dispatch to the remote service. Returns the remote run dict."""
    body: dict[str, Any] = {
        "item_id": item_id,
        "max_turns": max_turns,
        "mode": mode,
        "engine": engine,
        "timeout_minutes": timeout_minutes,
    }
    if agent_name:
        body["agent_name"] = agent_name
    if attribution:
        body["attribution"] = attribution
    if rollout_id:
        body["rollout_id"] = rollout_id
    resp = await client.post(
        f"{url}/dispatch",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


async def _poll_remote_run(
    client: httpx.AsyncClient,
    remote_run_id: str,
    *,
    url: str,
    api_key: str,
) -> dict[str, Any]:
    """GET /runs/{id} from the remote service. Returns the remote run dict."""
    resp = await client.get(
        f"{url}/runs/{remote_run_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15.0,
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


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
    from agent_gtd.services.settings_service import get_dispatch_config

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

        # Dispatch config belongs to the project owner, not the caller.
        # Inbox items (no project) use the caller's own config.
        run_project_id = run.get("project_id")
        if run_project_id:
            proj_row = await db.fetchrow(
                "SELECT user_id FROM projects WHERE id = $1", str(run_project_id)
            )
            owner_id = str(proj_row["user_id"]) if proj_row else user_id
        else:
            owner_id = user_id

        settings = await get_dispatch_config(db, owner_id)
        if not settings:
            await _update_run(
                db,
                run_id,
                status="failed",
                finished_at=now,
                error_msg="Project owner has not configured dispatch",
            )
            reconciled += 1
            continue

        dispatch_url = settings["url"]
        dispatch_api_key = settings["api_key"]

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

        remote_status = remote.get("status", "")
        if remote_status in _TERMINAL_STATUSES:
            # Already finished — sync local status
            local_status = _STATUS_MAP.get(remote_status, "failed")
            error_msg = remote.get("error") or ""
            await _update_run(
                db,
                run_id,
                status=local_status,
                finished_at=now,
                error_msg=error_msg[:500] if error_msg else "",
            )
            logger.info(
                "Reconciled run %s: remote=%s → local=%s",
                run_id,
                remote_status,
                local_status,
            )
        else:
            # Still running — resume polling
            logger.info("Resuming polling for run %s (remote %s)", run_id, remote_id)
            asyncio.create_task(
                _resume_polling(
                    db, run, remote_id, url=dispatch_url, api_key=dispatch_api_key
                )
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

                remote_status = remote.get("status", "")
                if remote_status in _TERMINAL_STATUSES:
                    break

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
        local_status = _STATUS_MAP.get(remote_status, "failed")
        error_msg = remote.get("error") or ""

        await _update_run(
            db,
            run_id,
            status=local_status,
            finished_at=finished,
            error_msg=error_msg[:500] if error_msg else "",
        )

        event_type = "run_completed" if local_status == "success" else "run_failed"
        _publish_run_event(db, user_id, run_id, item_id, run, event_type)
        logger.info("Resumed run %s completed: %s", run_id, local_status)


# ---------------------------------------------------------------------------
# Single run executor
# ---------------------------------------------------------------------------


async def execute_run(
    db: Any,
    run: dict[str, Any],
    item: dict[str, Any],
    project: dict[str, Any],
) -> None:
    """Execute a dispatch run by forwarding to the remote dispatch service.

    Looks up the run owner's dispatch config from ``user_settings``.  If not
    configured, the run is immediately marked failed with a clear message.

    Updates the local run row as it progresses. The remote service handles
    cloning, Claude invocation, and posting comments to the GTD API.
    """
    from agent_gtd.services.settings_service import (
        get_dispatch_config,
        get_setting,
    )

    run_id = str(run["id"])
    item_id = str(run["item_id"])
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

    # Resolve dispatch config via project owner
    settings = await get_dispatch_config(db, owner_id)
    if not settings:
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=datetime.now(UTC).isoformat(),
            error_msg="Project owner has not configured dispatch",
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
        return

    dispatch_url = settings["url"]
    dispatch_api_key = settings["api_key"]

    # Resolve deployment-wide engine + agent names (app_settings, not user_settings)
    engine = await get_setting(db, "dispatch.engine") or "claude"
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

    # Resolve effective timeout: project override > global setting > hard-coded default
    raw_global_timeout = await get_setting(db, "dispatch.default_timeout_minutes")
    global_timeout_minutes = (
        int(raw_global_timeout) if raw_global_timeout is not None else 30
    )
    raw_project_timeout = project.get("dispatch_timeout_minutes")
    project_timeout_minutes = (
        int(str(raw_project_timeout)) if raw_project_timeout is not None else None
    )
    effective_timeout_minutes = resolve_timeout_minutes(
        project_timeout_minutes, global_timeout_minutes
    )

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        # --- Dispatch to remote ---
        try:
            remote_run = await _dispatch_to_remote(
                client,
                item_id,
                max_turns,
                mode,
                rollout_id=str(run["rollout_id"]) if run.get("rollout_id") else None,
                url=dispatch_url,
                api_key=dispatch_api_key,
                engine=engine,
                agent_name=agent_name,
                attribution=attribution,
                timeout_minutes=effective_timeout_minutes,
            )
            remote_run_id = remote_run["id"]
        except Exception as e:
            logger.exception("Failed to dispatch run %s to remote service", run_id)
            await _update_run(
                db,
                run_id,
                status="failed",
                finished_at=datetime.now(UTC).isoformat(),
                error_msg=f"Dispatch service error: {e}"[:500],
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
            return

        # --- Running ---
        now = datetime.now(UTC).isoformat()
        await _update_run(
            db,
            run_id,
            status="running",
            started_at=now,
            remote_run_id=remote_run_id,
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

                remote_status = remote.get("status", "")
                if remote_status in _TERMINAL_STATUSES:
                    break

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
        local_status = _STATUS_MAP.get(remote_status, "failed")
        error_msg = remote.get("error") or ""

        await _update_run(
            db,
            run_id,
            status=local_status,
            finished_at=finished,
            error_msg=error_msg[:500] if error_msg else "",
        )

        event_type = "run_completed" if local_status == "success" else "run_failed"
        _publish_run_event(db, user_id, run_id, item_id, run, event_type)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

# Module-level queue — set during app startup
_dispatch_queue: asyncio.Queue[str] | None = None
_semaphore: asyncio.Semaphore | None = None


def get_dispatch_queue() -> asyncio.Queue[str]:
    """Get the dispatch queue (must be called after startup)."""
    assert _dispatch_queue is not None, "Dispatch worker not started"  # noqa: S101
    return _dispatch_queue


async def _resolve_max_concurrent() -> int:
    """Read the concurrency cap from DB, falling back to env var then literal 6."""
    from agent_gtd.database import get_db
    from agent_gtd.services import settings_service

    db = await get_db()
    val = await settings_service.get_setting(db, "dispatch.max_concurrent")
    if val is None:
        return _MAX_CONCURRENT_DEFAULT
    return max(1, int(val))


async def dispatch_worker() -> None:
    """Background worker that drains the dispatch queue."""
    global _dispatch_queue, _semaphore
    _dispatch_queue = asyncio.Queue()
    _max = await _resolve_max_concurrent()
    _semaphore = asyncio.Semaphore(_max)

    logger.info("Dispatch worker started (max %d concurrent)", _max)

    while True:
        run_id = await _dispatch_queue.get()
        asyncio.create_task(_process_run(run_id))


async def _process_run(run_id: str) -> None:
    """Process a single run with concurrency limiting."""
    assert _semaphore is not None  # noqa: S101

    async with _semaphore:
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
