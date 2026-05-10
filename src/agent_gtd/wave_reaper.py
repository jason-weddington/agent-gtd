"""Wave reaper — background job that marks crashed waves as 'crashed'.

A wave is reaped when **both** conditions are true:
1. Heartbeat stale: no wave event (any kind) in the last
   ``WAVE_REAPER_STALE_THRESHOLD_SECONDS`` seconds.
2. Dispatched child terminal: at least one ``wave_plan_items`` row still in
   ``'dispatched'`` status whose linked ``claude_run`` finished more than
   ``WAVE_REAPER_MERGE_GRACE_SECONDS`` ago.

Stale heartbeat alone NEVER reaps — that avoids false positives on slow
waves with no dispatched items.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import time — AC-7)
# ---------------------------------------------------------------------------

WAVE_REAPER_STALE_THRESHOLD_SECONDS = int(
    os.environ.get("WAVE_REAPER_STALE_THRESHOLD_SECONDS", "300")
)
WAVE_REAPER_MERGE_GRACE_SECONDS = int(
    os.environ.get("WAVE_REAPER_MERGE_GRACE_SECONDS", "120")
)
WAVE_REAPER_POLL_INTERVAL_SECONDS = int(
    os.environ.get("WAVE_REAPER_POLL_INTERVAL_SECONDS", "60")
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _next_event_seq(db: Any, wave_run_id: str) -> int:
    """Return the next available sequence number for a wave event."""
    row = await db.fetchrow(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq"
        " FROM wave_events WHERE wave_run_id = $1",
        wave_run_id,
    )
    return int(row["next_seq"]) if row else 1


async def _check_and_reap_wave(db: Any, wave: dict[str, Any]) -> bool:
    """Evaluate and possibly reap a single running wave.

    Args:
        db: Database pool.
        wave: Row dict from ``autonomous_wave_runs``.

    Returns:
        ``True`` if the wave was reaped, ``False`` otherwise.
    """
    wave_run_id = str(wave["id"])
    now = datetime.now(UTC)

    # ------------------------------------------------------------------
    # AC-1: Heartbeat staleness
    # ------------------------------------------------------------------
    # "Last heartbeat" = MAX(ts) from wave_events, or falls back to
    # autonomous_wave_runs.updated_at if no events exist.
    hb_row = await db.fetchrow(
        "SELECT MAX(ts) AS last_ts FROM wave_events WHERE wave_run_id = $1",
        wave_run_id,
    )
    last_ts_str: str | None = hb_row["last_ts"] if hb_row else None

    if last_ts_str:
        # Parse ISO-8601 string; strip trailing Z / offset for fromisoformat
        last_ts_str_clean = last_ts_str.replace("Z", "+00:00")
        try:
            last_heartbeat = datetime.fromisoformat(last_ts_str_clean)
        except ValueError:
            # Fallback if the format is unexpected
            last_heartbeat = now
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
    else:
        # No events — use updated_at from the wave run row
        updated_at_str = str(wave.get("updated_at", ""))
        if updated_at_str:
            updated_at_clean = updated_at_str.replace("Z", "+00:00")
            try:
                last_heartbeat = datetime.fromisoformat(updated_at_clean)
            except ValueError:
                last_heartbeat = now
            if last_heartbeat.tzinfo is None:
                last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
        else:
            last_heartbeat = now

    stale_seconds = (now - last_heartbeat).total_seconds()
    if stale_seconds <= WAVE_REAPER_STALE_THRESHOLD_SECONDS:
        # Heartbeat is fresh — definitely not stale
        return False

    # ------------------------------------------------------------------
    # AC-2: Dispatched item with terminal child run past grace window
    # ------------------------------------------------------------------
    grace_cutoff = (
        now - timedelta(seconds=WAVE_REAPER_MERGE_GRACE_SECONDS)
    ).isoformat()

    stuck_rows = await db.fetch(
        """
        SELECT wpi.item_id, cr.id AS run_id, cr.status AS run_status, cr.finished_at
        FROM wave_plan_items wpi
        JOIN claude_runs cr ON cr.id = wpi.claude_run_id
        WHERE wpi.wave_run_id = $1
          AND wpi.status = 'dispatched'
          AND cr.status IN ('success', 'failed', 'timeout', 'cancelled')
          AND cr.finished_at < $2
        """,
        wave_run_id,
        grace_cutoff,
    )

    if not stuck_rows:
        # No dispatched item with a terminal child run past grace — do not reap
        return False

    # Both conditions met — reap this wave
    triggered = stuck_rows[0]
    triggered_item_id = str(triggered["item_id"])
    child_run_id = str(triggered["run_id"])
    child_run_status = str(triggered["run_status"])

    await _reap_wave(
        db,
        wave,
        stale_seconds=stale_seconds,
        triggered_item_id=triggered_item_id,
        child_run_id=child_run_id,
        child_run_status=child_run_status,
    )
    return True


async def _reap_wave(
    db: Any,
    wave: dict[str, Any],
    *,
    stale_seconds: float,
    triggered_item_id: str,
    child_run_id: str,
    child_run_status: str,
) -> None:
    """Execute the reap action for a single wave (AC-4).

    Steps (all in a single logical block, best-effort atomicity):
      1. UPDATE autonomous_wave_runs status → 'crashed' (skip if 0 rows affected)
      2. UPDATE wave_plan_items: pending/ready/dispatched → 'halted'
      3. release_wave_locks()
      4. INSERT wave_events row (kind='wave_crashed')
      5. publish event_bus 'wave_crashed'

    Args:
        db: Database pool.
        wave: Row dict of the wave run.
        stale_seconds: How many seconds since the last heartbeat.
        triggered_item_id: item_id of the stuck wave_plan_items row.
        child_run_id: claude_run.id whose terminal status triggered the reap.
        child_run_status: Terminal status of that claude_run.
    """
    wave_run_id = str(wave["id"])
    project_id = str(wave.get("project_id", ""))
    lead_user_id = str(wave.get("lead_user_id", ""))

    now = datetime.now(UTC).isoformat()
    halt_reason = "stale_heartbeat+terminal_child_run"

    # Step 1: Atomically claim the wave — skip if already terminal
    result = await db.execute(
        "UPDATE autonomous_wave_runs"
        " SET status = 'crashed', halt_reason = $1, ended_at = $2, updated_at = $3"
        " WHERE id = $4 AND status = 'running'",
        halt_reason,
        now,
        now,
        wave_run_id,
    )
    # asyncpg returns "UPDATE N"; sqlite_pool also follows this pattern
    rows_affected = _parse_rowcount(result)
    if rows_affected == 0:
        logger.debug("wave reaper: wave %s already terminal, skipping", wave_run_id)
        return

    # Step 2: Halt pending/ready/dispatched items
    await db.execute(
        "UPDATE wave_plan_items SET status = 'halted'"
        " WHERE wave_run_id = $1 AND status IN ('pending', 'ready', 'dispatched')",
        wave_run_id,
    )

    # Step 3: Release item locks
    from agent_gtd.services.wave_lock_service import release_wave_locks

    await release_wave_locks(db, wave_run_id)

    # Step 4: Insert wave_crashed event
    event_id = str(uuid.uuid4())
    seq = await _next_event_seq(db, wave_run_id)
    event_payload = json.dumps(
        {
            "stale_seconds": int(stale_seconds),
            "triggered_by_item_id": triggered_item_id,
            "child_run_id": child_run_id,
            "child_run_status": child_run_status,
        }
    )
    await db.execute(
        "INSERT INTO wave_events"
        " (id, wave_run_id, seq, ts, kind, actor, decision_rule, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        event_id,
        wave_run_id,
        seq,
        now,
        "wave_crashed",
        "reaper",
        "stale_heartbeat+terminal_child_run",
        event_payload,
    )

    # Step 5: Publish SSE event
    from agent_gtd.event_bus import get_event_bus

    bus_payload: dict[str, Any] = {
        "wave_run_id": wave_run_id,
        "halt_reason": halt_reason,
    }
    await get_event_bus().publish(
        db,
        user_id=lead_user_id,
        event_type="wave_crashed",
        entity_type="wave_run",
        entity_id=wave_run_id,
        project_id=project_id or None,
        payload=bus_payload,
    )

    logger.warning(
        "wave reaper: reaped wave_run_id=%s project_id=%s stale_seconds=%d"
        " triggered_by_item_id=%s",
        wave_run_id,
        project_id,
        int(stale_seconds),
        triggered_item_id,
    )


def _parse_rowcount(result: str | Any) -> int:
    """Parse the row count from an asyncpg/sqlite execute result string.

    asyncpg returns e.g. ``"UPDATE 1"``; sqlite_pool returns the same.
    Falls back to 1 if parsing fails (conservative — better to skip than
    double-reap).
    """
    try:
        parts = str(result).strip().split()
        return int(parts[-1])
    except (IndexError, ValueError):
        return 1


async def _reap_crashed_waves(db: Any) -> int:
    """Scan all running waves and reap those meeting AC-3 conditions.

    Args:
        db: Database pool.

    Returns:
        Number of waves reaped.
    """
    rows = await db.fetch("SELECT * FROM autonomous_wave_runs WHERE status = 'running'")
    reaped = 0
    for row in rows:
        from agent_gtd.database import row_to_dict

        wave = row_to_dict(row)
        try:
            was_reaped = await _check_and_reap_wave(db, wave)
        except Exception:
            logger.exception("wave reaper: error checking wave %s", wave.get("id"))
            continue
        if was_reaped:
            reaped += 1
    return reaped


# ---------------------------------------------------------------------------
# Public coroutine — started as asyncio.create_task in main.py lifespan
# ---------------------------------------------------------------------------


async def wave_reaper() -> None:
    """Infinite loop that periodically scans for crashed waves.

    Starts with a sleep so the server can fully initialise before the first
    scan.  All exceptions from the scan are caught and logged — the task
    itself never crashes.
    """
    logger.info("Wave reaper started (poll=%ds)", WAVE_REAPER_POLL_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(WAVE_REAPER_POLL_INTERVAL_SECONDS)
        try:
            from agent_gtd.database import get_db

            db = await get_db()
            checked = await db.fetch(
                "SELECT COUNT(*) AS n"
                " FROM autonomous_wave_runs WHERE status = 'running'"
            )
            n_running = int(checked[0]["n"]) if checked else 0
            reaped = await _reap_crashed_waves(db)
            logger.debug(
                "wave reaper: checked %d running waves, reaped %d",
                n_running,
                reaped,
            )
        except Exception:
            logger.exception("wave reaper: unhandled error in scan cycle")
