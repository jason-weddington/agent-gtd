"""Server-side reaper for dispatch runs stuck at ``running``.

When a dispatch worker dies without writing a terminal status — the process
is killed, the host reboots, the run exceeds a limit the worker does not
enforce — the run record stays at ``status='running'`` with
``finished_at=NULL`` forever. Because ``dispatch_item`` refuses to dispatch an
item that has an active run, one dead worker strands the item until someone
restarts the board service, which the operator playbook forbids while other
runs are in flight.

This module reaps those records where the record lives. Each pass selects
every ``running`` run past a short grace window and asks its own dispatch
host what actually happened:

- The host reports a terminal status → adopt it (``adopted``).
- The host has no record of the run → the worker is gone; fail the run
  (``no_record``).
- The host cannot be reached → wait, but once the run is past its project's
  ``dispatch_timeout_minutes`` (plus slack) mark it ``timeout``
  (``unreachable_wait`` → ``unreachable_timeout``).

The item is thereby released for re-dispatch without touching the service.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pydantic

from agent_gtd import dispatch_worker
from agent_gtd.database import get_db, row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.dispatch_constants import MANAGER_DEFAULT_TIMEOUT_MINUTES
from agent_gtd.models import LocalRunStatus
from agent_gtd.services import settings_service
from agent_gtd.services.dispatch_service import _parse_run_timestamp

if TYPE_CHECKING:
    from agent_gtd_dispatch_protocol import RunResponse as RemoteRunResponse

logger = logging.getLogger(__name__)

# How often the reaper loop wakes.
REAPER_INTERVAL_SECONDS: int = 60
# A run younger than this is never sent to a host: the live poller owns it.
REAPER_GRACE_SECONDS: int = 600
# Extra minutes beyond the run's effective timeout before an unreachable host
# is declared fatal.
REAPER_UNREACHABLE_SLACK_MINUTES: int = 30
REAPED_NO_RECORD_ERROR: str = "reaped: dispatch host has no record of this run"


async def _lookup_project(db: DbPool, project_id: object) -> dict[str, Any] | None:
    """Fetch the run's project row (owner + dispatch timeout), if any.

    Mirrors cancel_run's owner lookup (projects.user_id, with the run's
    user_id as fallback) and adds the project-level
    ``dispatch_timeout_minutes`` the timeout limit is derived from.
    """
    if not project_id:
        return None
    return await db.fetchrow(
        "SELECT user_id, dispatch_timeout_minutes FROM projects WHERE id = $1",
        str(project_id),
    )


def _int_or_none(raw: object) -> int | None:
    """Best-effort int() conversion; None for NULL / non-integer values."""
    if raw is None:
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


async def _setting_int(db: DbPool, key: str, fallback: int) -> int:
    """Read an integer app setting, falling back when missing/invalid."""
    parsed = _int_or_none(await settings_service.get_setting(db, key))
    return parsed if parsed is not None else fallback


class _PassCounters:
    """Mutable per-pass tallies for the summary log line and return value."""

    def __init__(self) -> None:
        self.candidates = 0
        self.adopted = 0
        self.no_record = 0
        self.unreachable_timeout = 0
        self.unreachable_wait = 0
        self.host_active = 0
        self.lost_race = 0
        self.skipped_bad_ts = 0
        self.errors = 0
        self.changed = 0


async def _write_reaped(
    db: DbPool,
    run_id: str,
    now_iso: str,
    *,
    status: str,
    error_msg: str,
    engine_actual: object = None,
) -> tuple[bool, str]:
    """Conditionally write a terminal status; return (counted, observed).

    The UPDATE is guarded by ``AND status = 'running'`` so a run that reached
    a terminal state concurrently is never overwritten. The write only counts
    when the re-select shows the status we wrote AND our own finished_at.
    """
    sets = [
        "status = $1",
        "finished_at = $2",
        "updated_at = $3",
        "error_msg = $4",
    ]
    params: list[object] = [status, now_iso, now_iso, error_msg]
    # Omit engine_actual when None: writing it would clobber a set value.
    if engine_actual is not None:
        params.append(engine_actual)
        sets.append(f"engine_actual = ${len(params)}")
    params.append(run_id)
    update_clause = f"UPDATE claude_runs SET {', '.join(sets)}"  # noqa: S608
    sql = f"{update_clause} WHERE id = ${len(params)} AND status = 'running'"
    await db.execute(sql, *params)
    stored = await db.fetchrow(
        "SELECT status, finished_at FROM claude_runs WHERE id = $1", run_id
    )
    if stored is None:
        return False, "<missing>"
    observed = str(stored["status"])
    counted = observed == status and str(stored["finished_at"]) == now_iso
    return counted, observed


def _log_decision(
    run_id: str,
    decision: str,
    reason: str,
    remote_status: str,
    elapsed_m: int,
    limit_m: int,
    mode: str,
    rollout_id: str,
    host: str,
    resolution: str,
) -> None:
    """Emit the one decision line this candidate gets."""
    level = logging.WARNING
    if reason in ("http_401", "http_403", "unmatched_host"):
        # Configuration faults: ERROR on every pass until fixed.
        level = logging.ERROR
    elif decision in ("host_active", "unreachable_wait", "lost_race"):
        level = logging.INFO
    logger.log(
        level,
        "run_reaper: run_id=%s decision=%s reason=%s remote_status=%s"
        " elapsed_m=%d limit_m=%d mode=%s rollout_id=%s host=%s"
        " resolution=%s",
        run_id,
        decision,
        reason,
        remote_status,
        elapsed_m,
        limit_m,
        mode,
        rollout_id,
        host,
        resolution,
    )


async def reap_stuck_runs(db: DbPool, *, now: datetime | None = None) -> int:
    """Run one reaper pass and return the number of rows it changed.

    Covers every mode (build, plan, manage) with or without a rollout_id;
    ``pending`` and ``cloning`` runs are never selected — the live poller owns
    them. Rollout tables are never read or written: a reaped rollout child's
    parent status is left to the rollout machinery.
    """
    now_dt = now if now is not None else datetime.now(UTC)
    pass_started = datetime.now(UTC)
    counters = _PassCounters()
    rows = await db.fetch("SELECT * FROM claude_runs WHERE status = 'running'")
    if not rows:
        _log_pass_summary(counters, pass_started)
        return 0

    # Global timeout defaults are read once per pass, not once per candidate.
    global_worker = await _setting_int(db, "dispatch.default_timeout_minutes", 30)
    global_manager = await _setting_int(
        db, "dispatch.manager_default_timeout_minutes", MANAGER_DEFAULT_TIMEOUT_MINUTES
    )

    # One client per pass; host results are never cached between candidates.
    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        for row in rows:
            run = row_to_dict(row)
            run_id = str(run["id"])
            base = _parse_run_timestamp(run, "started_at")
            if base is None:
                base = _parse_run_timestamp(run, "created_at")
            if base is None:
                counters.skipped_bad_ts += 1
                logger.warning("run_reaper: unparseable timestamp run_id=%s", run_id)
                continue
            if (now_dt - base).total_seconds() <= REAPER_GRACE_SECONDS:
                # Inside the grace window: the live poller still owns it.
                continue
            counters.candidates += 1
            try:
                await _reap_candidate(
                    db,
                    client,
                    run,
                    run_id,
                    base=base,
                    now_dt=now_dt,
                    global_worker=global_worker,
                    global_manager=global_manager,
                    counters=counters,
                )
            except Exception:
                counters.errors += 1
                logger.warning("run_reaper: run_id=%s error", run_id, exc_info=True)

    _log_pass_summary(counters, pass_started)
    return counters.changed


def _log_pass_summary(counters: _PassCounters, pass_started: datetime) -> None:
    """Emit the one-line per-pass summary, even for a zero-candidate pass."""
    duration_ms = int((datetime.now(UTC) - pass_started).total_seconds() * 1000)
    logger.info(
        "run_reaper: pass candidates=%d adopted=%d no_record=%d"
        " unreachable_timeout=%d unreachable_wait=%d host_active=%d"
        " lost_race=%d skipped_bad_ts=%d errors=%d duration_ms=%d",
        counters.candidates,
        counters.adopted,
        counters.no_record,
        counters.unreachable_timeout,
        counters.unreachable_wait,
        counters.host_active,
        counters.lost_race,
        counters.skipped_bad_ts,
        counters.errors,
        duration_ms,
    )


async def _reap_candidate(
    db: DbPool,
    client: httpx.AsyncClient,
    run: dict[str, Any],
    run_id: str,
    *,
    base: datetime,
    now_dt: datetime,
    global_worker: int,
    global_manager: int,
    counters: _PassCounters,
) -> None:
    """Resolve one candidate's true state and write/record a decision."""
    now_iso = now_dt.isoformat()
    mode = str(run.get("mode") or "build")
    rollout_id = str(run.get("rollout_id") or "-")
    elapsed_minutes = int((now_dt - base).total_seconds() // 60)

    project = await _lookup_project(db, run.get("project_id"))
    owner_id = str(project["user_id"]) if project else str(run["user_id"])
    project_timeout = (
        _int_or_none(project.get("dispatch_timeout_minutes")) if project else None
    )
    effective_timeout_minutes = dispatch_worker.resolve_timeout_minutes(
        mode, project_timeout, global_worker, global_manager
    )
    limit_m = effective_timeout_minutes + REAPER_UNREACHABLE_SLACK_MINUTES

    remote_run_id = str(run.get("remote_run_id") or "")
    host_url = str(run.get("dispatch_host_url") or "")
    api_key = ""
    resolution = ""
    reason = "-"
    remote_status = "-"
    decision = ""
    new_status: str | None = None
    error_msg = ""
    engine_actual: object = None

    if not remote_run_id:
        resolution = "no_remote_run_id"
    elif not host_url:
        resolution = "no_host_url"
    else:
        hosts = await settings_service.get_dispatch_hosts(db, owner_id)
        matching = next((h for h in hosts if h.get("url") == host_url), None)
        if matching is None:
            # Configuration fault, not a dead worker: never fail immediately.
            resolution = "unmatched_host"
        else:
            resolution = "owning_host"
            api_key = str(matching["api_key"])

    if resolution == "owning_host":

        def _unreachable(reason_token: str) -> str:
            return (
                "unreachable_timeout"
                if elapsed_minutes >= limit_m
                else "unreachable_wait"
            )

        try:
            remote: RemoteRunResponse = await dispatch_worker._poll_remote_run(
                client, remote_run_id, url=host_url, api_key=api_key
            )
        except httpx.HTTPStatusError as exc:
            code = int(exc.response.status_code)
            if code == 404:
                decision = "no_record"
                reason = "http_404"
                new_status = "failed"
                error_msg = f"{REAPED_NO_RECORD_ERROR} (running for {elapsed_minutes}m)"
            else:
                reason = f"http_{code}"
                decision = _unreachable(reason)
        except httpx.ConnectError:
            reason = "connect_error"
            decision = _unreachable(reason)
        except httpx.TimeoutException:
            reason = "read_timeout"
            decision = _unreachable(reason)
        except httpx.HTTPError:
            reason = "http_error"
            decision = _unreachable(reason)
        except pydantic.ValidationError:
            reason = "invalid_body"
            decision = _unreachable(reason)
        else:
            remote_status = str(remote.status.value)
            if remote.status in dispatch_worker._TERMINAL_STATUSES:
                decision = "adopted"
                new_status = str(LocalRunStatus.from_remote(remote.status).value)
                error_msg = (remote.error or "")[: dispatch_worker.ERROR_MSG_MAX_CHARS]
                engine_actual = remote.engine_actual
            else:
                # Host says the work is in progress: never second-guess it.
                decision = "host_active"
    else:
        reason = resolution
        decision = (
            "unreachable_timeout" if elapsed_minutes >= limit_m else "unreachable_wait"
        )

    if decision == "unreachable_timeout":
        new_status = "timeout"
        error_msg = f"reaped: dispatch host unreachable for {elapsed_minutes}m"

    if new_status is None:
        # host_active / unreachable_wait: nothing is written, whatever the age.
        if decision == "host_active":
            counters.host_active += 1
        else:
            counters.unreachable_wait += 1
        _log_decision(
            run_id,
            decision,
            reason,
            remote_status,
            elapsed_minutes,
            limit_m,
            mode,
            rollout_id,
            host_url,
            resolution,
        )
        return

    counted, observed = await _write_reaped(
        db,
        run_id,
        now_iso,
        status=new_status,
        error_msg=error_msg,
        engine_actual=engine_actual,
    )
    if not counted:
        decision = "lost_race"
        counters.lost_race += 1
        logger.info(
            "run_reaper: run_id=%s decision=lost_race observed_status=%s",
            run_id,
            observed,
        )
        return

    if decision == "adopted":
        counters.adopted += 1
    elif decision == "no_record":
        counters.no_record += 1
    else:
        counters.unreachable_timeout += 1
    counters.changed += 1
    event_type = "run_completed" if new_status == "success" else "run_failed"
    dispatch_worker._publish_run_event(
        db,
        str(run["user_id"]),
        run_id,
        run.get("item_id") or None,
        run,
        event_type,
        reconciled=True,
        extra={"reaped": True, "reap_outcome": decision},
    )
    _log_decision(
        run_id,
        decision,
        reason,
        remote_status,
        elapsed_minutes,
        limit_m,
        mode,
        rollout_id,
        host_url,
        resolution,
    )


async def run_reaper_loop() -> None:
    """Loop forever, running one reaper pass per interval.

    Passes never overlap: each pass is awaited before the next sleep. A
    failing pass is logged and the loop continues; ``CancelledError`` ends it.
    """
    logger.info(
        "run_reaper: started interval_s=%d grace_s=%d slack_m=%d",
        REAPER_INTERVAL_SECONDS,
        REAPER_GRACE_SECONDS,
        REAPER_UNREACHABLE_SLACK_MINUTES,
    )
    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        try:
            await reap_stuck_runs(await get_db())
        except Exception:
            logger.warning("run_reaper: pass failed", exc_info=True)
