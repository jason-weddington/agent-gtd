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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DISPATCH_SERVICE_URL = os.environ.get("DISPATCH_SERVICE_URL", "")
DISPATCH_SERVICE_API_KEY = os.environ.get("DISPATCH_SERVICE_API_KEY", "")
DEFAULT_MAX_TURNS = int(os.environ.get("DISPATCH_DEFAULT_MAX_TURNS", "100"))
MAX_CONCURRENT = 3
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


def _dispatch_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {DISPATCH_SERVICE_API_KEY}"}


async def _dispatch_to_remote(
    client: httpx.AsyncClient,
    item_id: str,
    max_turns: int,
    mode: str = "build",
) -> dict[str, Any]:
    """POST /dispatch to the remote service. Returns the remote run dict."""
    resp = await client.post(
        f"{DISPATCH_SERVICE_URL}/dispatch",
        json={"item_id": item_id, "max_turns": max_turns, "mode": mode},
        headers=_dispatch_headers(),
        timeout=30.0,
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


async def _poll_remote_run(
    client: httpx.AsyncClient,
    remote_run_id: str,
) -> dict[str, Any]:
    """GET /runs/{id} from the remote service. Returns the remote run dict."""
    resp = await client.get(
        f"{DISPATCH_SERVICE_URL}/runs/{remote_run_id}",
        headers=_dispatch_headers(),
        timeout=15.0,
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


async def _cancel_remote_run(
    client: httpx.AsyncClient,
    remote_run_id: str,
) -> None:
    """POST /runs/{id}/cancel on the remote service."""
    try:
        await client.post(
            f"{DISPATCH_SERVICE_URL}/runs/{remote_run_id}/cancel",
            headers=_dispatch_headers(),
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

        # Poll remote for actual status
        try:
            async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
                remote = await _poll_remote_run(client, remote_id)
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
            asyncio.create_task(_resume_polling(db, run, remote_id))

        reconciled += 1

    logger.info("Reconciled %d active run(s) after restart", reconciled)
    return reconciled


async def _resume_polling(
    db: Any,
    run: dict[str, Any],
    remote_run_id: str,
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
                    remote = await _poll_remote_run(client, remote_run_id)
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
            await _cancel_remote_run(client, remote_run_id)
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

    Updates the local run row as it progresses. The remote service handles
    cloning, Claude invocation, and posting comments to the GTD API.
    """
    run_id = str(run["id"])
    item_id = str(run["item_id"])
    user_id = str(run["user_id"])
    max_turns = int(str(run["max_turns"]))
    mode = str(run.get("mode", "build"))

    if not DISPATCH_SERVICE_URL:
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=datetime.now(UTC).isoformat(),
            error_msg="DISPATCH_SERVICE_URL not configured",
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
        return

    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        # --- Dispatch to remote ---
        try:
            remote_run = await _dispatch_to_remote(client, item_id, max_turns, mode)
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
                    remote = await _poll_remote_run(client, remote_run_id)
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
            await _cancel_remote_run(client, remote_run_id)
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


async def dispatch_worker() -> None:
    """Background worker that drains the dispatch queue."""
    global _dispatch_queue, _semaphore
    _dispatch_queue = asyncio.Queue()
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    logger.info("Dispatch worker started (max %d concurrent)", MAX_CONCURRENT)

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
