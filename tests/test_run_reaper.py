"""Tests for the server-side run reaper (services/run_reaper.py).

Covers every decision branch of ``reap_stuck_runs``: adopting a host-reported
terminal status, failing a run the host has no record of, the
wait-then-timeout path for an unreachable host, the race-safe write, the log
lines and pass summary, loop resilience, lifespan wiring, rollouts left
untouched, and the historical shapes from the incident write-ups.
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pydantic
import pytest
from agent_gtd_dispatch_protocol import RunResponse, RunStatus

from agent_gtd.database import get_db
from agent_gtd.exceptions import RunActiveError
from agent_gtd.services import dispatch_service
from agent_gtd.services.run_reaper import (
    REAPED_NO_RECORD_ERROR,
    REAPER_UNREACHABLE_SLACK_MINUTES,
    reap_stuck_runs,
    run_reaper_loop,
)
from agent_gtd.services.settings_service import set_setting

FIXED_NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)

REAPER_LOGGER = "agent_gtd.services.run_reaper"
HOST_URL = "http://host-a"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(minutes_before: int = 0) -> str:
    return (FIXED_NOW - timedelta(minutes=minutes_before)).isoformat()


async def _remote(
    status: RunStatus, *, error: str = "", engine_actual: str | None = None
) -> RunResponse:
    return RunResponse(
        id="r-1",
        item_id="i-1",
        project_name="p",
        branch_name="b",
        engine="claude-code-sonnet",
        engine_actual=engine_actual,
        agent_name=None,
        mode="build",
        rollout_id=None,
        status=status,
        started_at=_iso(60),
        completed_at=_iso(0),
        exit_code=0,
        error=error,
        completion=None,
        created_at=_iso(60),
    )


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"{HOST_URL}/runs/r-1")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(f"{code}", request=request, response=response)


async def _insert_host(db: Any, owner_id: str, url: str = HOST_URL) -> None:
    """Directly insert a dispatch_hosts row owned by *owner_id*."""
    now = _iso(0)
    await db.execute(
        "INSERT INTO dispatch_hosts"
        " (id, user_id, label, url, api_key, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        str(uuid.uuid4()),
        owner_id,
        "test-host",
        url,
        "sk-test",
        now,
        now,
    )


async def _insert_rollout(
    db: Any, project_id: str, user_id: str, status: str = "running"
) -> str:
    """Directly insert an autonomous_rollouts row; return its id."""
    rollout_id = str(uuid.uuid4())
    now = _iso(0)
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        user_id,
        status,
        now,
        now,
    )
    return rollout_id


async def _make_project(
    client: Any,
    auth_headers: dict[str, str],
    *,
    timeout_minutes: int | None = None,
    git_origin: str = "git@example:repo.git",
) -> str:
    res = await client.post(
        "/api/projects",
        json={"name": f"Reaper {uuid.uuid4().hex[:8]}", "git_origin": git_origin},
        headers=auth_headers,
    )
    project_id: str = res.json()["id"]
    if timeout_minutes is not None:
        db = await get_db()
        await db.execute(
            "UPDATE projects SET dispatch_timeout_minutes = $1 WHERE id = $2",
            timeout_minutes,
            project_id,
        )
    return project_id


async def _insert_run(
    db: Any,
    *,
    user_id: str,
    project_id: str,
    item_id: str | None = None,
    mode: str = "build",
    status: str = "running",
    started_minutes: int | None = None,
    created_minutes: int = 0,
    started_at: str | None | object = "auto",
    remote_run_id: str = "r-1",
    dispatch_host_url: str = HOST_URL,
    rollout_id: str | None = None,
) -> str:
    """Insert a claude_runs row directly; return its id."""
    run_id = str(uuid.uuid4())
    if started_at == "auto":
        started = _iso(started_minutes) if started_minutes is not None else None
    else:
        started = started_at
    created = _iso(created_minutes)
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, mode, max_turns,"
        " created_at, updated_at, started_at, remote_run_id,"
        " dispatch_host_url, rollout_id)"
        " VALUES ($1, $2, $3, $4, $5, $6, 100, $7, $8, $9, $10, $11, $12)",
        run_id,
        item_id,
        project_id,
        user_id,
        status,
        mode,
        created,
        created,
        started,
        remote_run_id,
        dispatch_host_url,
        rollout_id,
    )
    return run_id


async def _get_run(db: Any, run_id: str) -> dict[str, Any]:
    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None
    return dict(row)


async def _reap(db: Any, poll: Any = None) -> int:
    """Run one pass at FIXED_NOW with an optional _poll_remote_run patch."""
    if poll is None:

        async def poll(*args: Any, **kwargs: Any) -> RunResponse:
            return await _remote(RunStatus.succeeded)

    with patch("agent_gtd.dispatch_worker._poll_remote_run", new=poll):
        return await reap_stuck_runs(db, now=FIXED_NOW)


async def _me(client: Any, auth_headers: dict[str, str]) -> str:
    me = await client.get("/api/auth/me", headers=auth_headers)
    return str(me.json()["id"])


async def _seed_candidate(
    client: Any,
    auth_headers: dict[str, str],
    *,
    started_minutes: int,
    **kwargs: Any,
) -> tuple[str, str, str, str]:
    """Create (user_id, project_id, run_id, host_url) for one running run."""
    user_id = await _me(client, auth_headers)
    db = await get_db()
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    run_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        started_minutes=started_minutes,
        **kwargs,
    )
    return user_id, project_id, run_id, HOST_URL


# ---------------------------------------------------------------------------
# AC-10: board-outage shape
# ---------------------------------------------------------------------------


async def test_board_outage_shape_adopts_and_is_idempotent(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """Succeeded remote run with engine_actual is adopted; second pass is a no-op."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=40
    )

    poll = AsyncMock(
        return_value=await _remote(RunStatus.succeeded, engine_actual="talos-glm")
    )
    assert await _reap(db, poll) == 1

    row = await _get_run(db, run_id)
    assert row["status"] == "success"
    assert row["finished_at"]
    assert row["engine_actual"] == "talos-glm"

    before = dict(row)
    assert await _reap(db, AsyncMock(side_effect=AssertionError("polled"))) == 0
    assert await _get_run(db, run_id) == before


# ---------------------------------------------------------------------------
# AC-11: unit coverage of each branch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remote_status", [RunStatus.running, RunStatus.pending])
async def test_host_active_leaves_row_untouched(
    client: Any, auth_headers: dict[str, str], remote_status: RunStatus
) -> None:
    """A run whose host still reports activity is never reaped."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=11
    )
    before = await _get_run(db, run_id)

    poll = AsyncMock(return_value=await _remote(remote_status))
    assert await _reap(db, poll) == 0

    row = await _get_run(db, run_id)
    assert row["status"] == "running"
    assert row["finished_at"] == before["finished_at"]
    assert row["updated_at"] == before["updated_at"]


async def test_grace_window_never_sends_to_host(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A run inside the 600s grace window is not sent to any host."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=9
    )
    poll = AsyncMock()
    assert await _reap(db, poll) == 0
    poll.assert_not_awaited()
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_lost_race_keeps_concurrent_writer(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A concurrent terminal write wins; the reaper does not overwrite it."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=30
    )

    async def _race(*args: Any, **kwargs: Any) -> RunResponse:
        await db.execute(
            "UPDATE claude_runs SET status='success', finished_at='X' WHERE id = $1",
            run_id,
        )
        return await _remote(RunStatus.failed)

    publish = MagicMock()
    with (
        patch("agent_gtd.dispatch_worker._poll_remote_run", new=_race),
        patch("agent_gtd.dispatch_worker._publish_run_event", publish),
    ):
        assert await reap_stuck_runs(db, now=FIXED_NOW) == 0

    row = await _get_run(db, run_id)
    assert row["status"] == "success"
    assert row["finished_at"] == "X"
    publish.assert_not_called()


async def test_deleted_row_counts_as_lost_race(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A row that disappears mid-write is a lost race, not a counted write."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=30
    )

    async def _vanish(*args: Any, **kwargs: Any) -> RunResponse:
        await db.execute("DELETE FROM claude_runs WHERE id = $1", run_id)
        return await _remote(RunStatus.failed)

    assert await _reap(db, _vanish) == 0


@pytest.mark.parametrize(
    ("remote_status", "expected_status"),
    [
        (RunStatus.failed, "failed"),
        (RunStatus.timed_out, "timeout"),
        (RunStatus.cancelled, "cancelled"),
        (RunStatus.already_satisfied, "success"),
    ],
)
async def test_terminal_mapping_and_error_truncation(
    client: Any,
    auth_headers: dict[str, str],
    remote_status: RunStatus,
    expected_status: str,
) -> None:
    """Each terminal remote status maps to its local status, error clipped."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=30
    )
    long_error = "E" * 2500
    poll = AsyncMock(return_value=await _remote(remote_status, error=long_error))
    assert await _reap(db, poll) == 1

    row = await _get_run(db, run_id)
    assert row["status"] == expected_status
    assert row["error_msg"] == long_error[:2000]


async def test_created_at_fallback_used(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A NULL started_at falls back to created_at; the host is still queried."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=None, created_minutes=20
    )
    poll = AsyncMock(side_effect=httpx.ConnectError("down"))
    assert await _reap(db, poll) == 0
    poll.assert_awaited_once()
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_unparseable_timestamp_is_skipped(
    client: Any, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Both timestamps garbage → skipped with a WARNING, nothing written."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client,
        auth_headers,
        started_minutes=30,
        started_at="garbage",
        created_minutes=0,
    )
    await db.execute(
        "UPDATE claude_runs SET created_at = 'garbage' WHERE id = $1", run_id
    )

    with caplog.at_level(logging.WARNING, logger=REAPER_LOGGER):
        assert await _reap(db) == 0
    assert "run_reaper: unparseable timestamp run_id=" in caplog.text
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_error_in_one_candidate_does_not_block_the_next(
    client: Any,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A candidate that raises mid-lookup is counted as an error; the rest reap."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    bad_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=30
    )
    good_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=30
    )

    async def _lookup(db: Any, project_id: object) -> dict[str, Any] | None:
        row = await db.fetchrow(
            "SELECT user_id, dispatch_timeout_minutes FROM projects WHERE id = $1",
            str(project_id),
        )
        if row and str(row["user_id"]) == user_id and _lookup.first:
            _lookup.first = False
            raise RuntimeError("project lookup exploded")
        return row

    _lookup.first = True  # type: ignore[attr-defined]

    poll = AsyncMock(side_effect=_http_status_error(404))
    with (
        patch("agent_gtd.services.run_reaper._lookup_project", new=_lookup),
        caplog.at_level(logging.INFO, logger=REAPER_LOGGER),
    ):
        changed = await _reap(db, poll)

    assert changed == 1
    assert (await _get_run(db, bad_id))["status"] == "running"
    assert (await _get_run(db, good_id))["status"] == "failed"
    assert "errors=1" in caplog.text
    assert "run_reaper: run_id=" in caplog.text


async def test_no_host_url_times_out_without_dispatch_config(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """Empty dispatch_host_url past the limit → timeout, config never read."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    run_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        started_minutes=400,
        dispatch_host_url="",
    )

    async def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("get_dispatch_config must not be called")

    with patch(
        "agent_gtd.services.settings_service.get_dispatch_config", new=_forbidden
    ):
        assert await _reap(db) == 1

    row = await _get_run(db, run_id)
    assert row["status"] == "timeout"
    assert row["error_msg"] == "reaped: dispatch host unreachable for 400m"


async def test_decision_log_lines_and_levels(
    client: Any, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """unreachable_wait carries limit_m/reason; http_401 is ERROR; summary always."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers, timeout_minutes=180)
    await _insert_host(db, user_id)
    wait_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        started_minutes=181,
        remote_run_id="r-wait",
    )
    unauth_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        started_minutes=181,
        remote_run_id="r-auth",
    )

    async def poll(client: Any, remote_run_id: str, **kwargs: Any) -> RunResponse:
        if remote_run_id == "r-wait":
            raise httpx.ConnectError("down")
        raise _http_status_error(401)

    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await _reap(db, poll) == 0

    wait_line = [r.message for r in caplog.records if f"run_id={wait_id}" in r.message]
    assert any("limit_m=" in m and "reason=connect_error" in m for m in wait_line)
    assert any(
        r.levelname == "ERROR" and f"run_id={unauth_id}" in r.message
        for r in caplog.records
    )
    assert "run_reaper: pass candidates=2" in caplog.text

    # Zero-candidate pass still logs the summary.
    await db.execute(
        "UPDATE claude_runs SET status = 'failed' WHERE status = 'running'"
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await reap_stuck_runs(db, now=FIXED_NOW) == 0
    assert "run_reaper: pass candidates=0" in caplog.text


# ---------------------------------------------------------------------------
# AC-7(b)/(c): event payload marker, lost-race log, summary counts
# ---------------------------------------------------------------------------


async def test_counted_write_publishes_reaped_marker(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """An adopted write publishes run_completed with the reaped marker."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    run_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=30
    )

    publish = MagicMock()
    poll = AsyncMock(return_value=await _remote(RunStatus.succeeded))
    with (
        patch("agent_gtd.dispatch_worker._poll_remote_run", new=poll),
        patch("agent_gtd.dispatch_worker._publish_run_event", publish),
    ):
        assert await reap_stuck_runs(db, now=FIXED_NOW) == 1

    publish.assert_called_once()
    call = publish.call_args
    assert call.args[5] == "run_completed"
    assert call.args[2] == run_id
    assert call.kwargs["reconciled"] is True
    assert call.kwargs["extra"] == {"reaped": True, "reap_outcome": "adopted"}


async def test_counted_timeout_publishes_run_failed(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """An unreachable-timeout write publishes run_failed with its marker."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    run_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=400
    )

    publish = MagicMock()
    with patch("agent_gtd.dispatch_worker._publish_run_event", publish):
        assert await reap_stuck_runs(db, now=FIXED_NOW) == 1

    publish.assert_called_once()
    call = publish.call_args
    assert call.args[5] == "run_failed"
    assert call.args[2] == run_id
    assert call.kwargs["extra"] == {
        "reaped": True,
        "reap_outcome": "unreachable_timeout",
    }


async def test_lost_race_logs_observed_status(
    client: Any, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """The lost-race INFO line names the observed status."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=30
    )

    async def _race(*args: Any, **kwargs: Any) -> RunResponse:
        await db.execute(
            "UPDATE claude_runs SET status='success', finished_at='X' WHERE id = $1",
            run_id,
        )
        return await _remote(RunStatus.failed)

    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await _reap(db, _race) == 0
    assert (
        f"run_reaper: run_id={run_id} decision=lost_race observed_status=success"
        in caplog.text
    )


# ---------------------------------------------------------------------------
# AC-2: candidate selection
# ---------------------------------------------------------------------------


async def test_pending_and_cloning_runs_are_never_selected(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """Only status='running' rows are candidates."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    pending_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        status="pending",
        started_minutes=400,
    )
    cloning_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        status="cloning",
        started_minutes=400,
    )

    poll = AsyncMock(side_effect=_http_status_error(404))
    assert await _reap(db, poll) == 0
    poll.assert_not_awaited()
    assert (await _get_run(db, pending_id))["status"] == "pending"
    assert (await _get_run(db, cloning_id))["status"] == "cloning"


async def test_no_user_id_filter_other_users_run_is_reaped(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A run owned by a different user is still reaped (no user filter)."""
    from agent_gtd.auth import register_user

    db = await get_db()
    user_id = await _me(client, auth_headers)
    other = await register_user("other@example.com", "otherpass123")
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    run_id = await _insert_run(
        db,
        user_id=str(other.id),
        project_id=project_id,
        started_minutes=30,
    )

    poll = AsyncMock(side_effect=_http_status_error(404))
    assert await _reap(db, poll) == 1
    assert (await _get_run(db, run_id))["status"] == "failed"


# ---------------------------------------------------------------------------
# AC-3/AC-6: remaining host-outcome branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ConnectError("down"), "connect_error"),
        (httpx.ReadTimeout("t"), "read_timeout"),
        (httpx.TransportError("boom"), "http_error"),
    ],
)
async def test_unreachable_reason_tokens_under_limit(
    client: Any,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    reason: str,
) -> None:
    """Each unreachable outcome keeps its own reason and waits under the limit."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=31
    )

    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await _reap(db, AsyncMock(side_effect=exc)) == 0
    line = [m for m in caplog.messages if f"run_id={run_id}" in m]
    assert any(f"reason={reason}" in m for m in line)
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_http_503_reason_token(client: Any, auth_headers: dict[str, str]) -> None:
    """A non-404 HTTPStatusError gives reason http_<code> and waits."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=31
    )
    poll = AsyncMock(side_effect=_http_status_error(503))
    assert await _reap(db, poll) == 0
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_invalid_body_reason_token(
    client: Any, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """A body that fails validation gives reason invalid_body and waits."""
    db = await get_db()
    _user, _project, run_id, _host = await _seed_candidate(
        client, auth_headers, started_minutes=31
    )
    ve = pydantic.ValidationError.from_exception_data(
        "RunResponse", [{"type": "missing", "loc": ("id",), "input": {}}]
    )
    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await _reap(db, AsyncMock(side_effect=ve)) == 0
    assert any(
        f"run_id={run_id}" in m and "reason=invalid_body" in m for m in caplog.messages
    )
    assert (await _get_run(db, run_id))["status"] == "running"


async def test_unmatched_host_is_a_config_fault_logged_at_error(
    client: Any, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """A URL matching no configured host is ERROR-logged and not failed."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    run_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        started_minutes=31,
        dispatch_host_url="http://not-configured",
    )

    with caplog.at_level(logging.INFO, logger=REAPER_LOGGER):
        assert await _reap(db) == 0

    assert any(
        r.levelname == "ERROR"
        and f"run_id={run_id}" in r.message
        and "resolution=unmatched_host" in r.message
        for r in caplog.records
    )
    assert (await _get_run(db, run_id))["status"] == "running"


# ---------------------------------------------------------------------------
# AC-6: timeout resolution inputs
# ---------------------------------------------------------------------------


async def test_global_setting_fallbacks(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """Missing/non-integer settings fall back to 30 / MANAGER_DEFAULT (240)."""
    from agent_gtd.dispatch_constants import MANAGER_DEFAULT_TIMEOUT_MINUTES

    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    await set_setting(db, "dispatch.default_timeout_minutes", "not-a-number")
    # manager setting intentionally unset → MANAGER_DEFAULT_TIMEOUT_MINUTES

    # Build run: 100m > 30+30 limit → timeout.
    build_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=100
    )
    # Manage run: 300m > 240+30 limit → timeout (global_manager fallback).
    manage_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        mode="manage",
        started_minutes=300,
        remote_run_id="",
    )
    # Manage run under the 270 limit → untouched.
    young_manage_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        mode="manage",
        started_minutes=260,
        remote_run_id="",
    )

    assert await _reap(db, AsyncMock(side_effect=httpx.ConnectError("down"))) == 2
    assert (await _get_run(db, build_id))["status"] == "timeout"
    assert (await _get_run(db, manage_id))["status"] == "timeout"
    assert (await _get_run(db, young_manage_id))["status"] == "running"
    assert MANAGER_DEFAULT_TIMEOUT_MINUTES == 240


async def test_project_timeout_non_integer_is_ignored(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A non-integer projects.dispatch_timeout_minutes inherits the global."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await db.execute(
        "UPDATE projects SET dispatch_timeout_minutes = 'abc' WHERE id = $1",
        project_id,
    )
    await _insert_host(db, user_id)
    run_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=100
    )
    # Global worker default 30 + slack 30 = 60; 100 ≥ 60 → timeout.
    assert await _reap(db, AsyncMock(side_effect=httpx.ConnectError("down"))) == 1
    assert (await _get_run(db, run_id))["status"] == "timeout"


async def test_owner_falls_back_to_run_user_when_project_row_missing(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """No project row: hosts resolve via the run's own user_id, timeout global."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    run_id = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=30
    )

    poll = AsyncMock(return_value=await _remote(RunStatus.succeeded))
    with patch(
        "agent_gtd.services.run_reaper._lookup_project",
        new=AsyncMock(return_value=None),
    ):
        assert await _reap(db, poll) == 1
    assert (await _get_run(db, run_id))["status"] == "success"


async def test_lookup_project_without_project_id() -> None:
    """A falsy project_id short-circuits: no query, owner falls back to user."""
    from agent_gtd.services.run_reaper import _lookup_project

    db = MagicMock()
    db.fetchrow = AsyncMock(side_effect=AssertionError("must not query"))
    assert await _lookup_project(db, None) is None
    db.fetchrow.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-9: rollouts untouched
# ---------------------------------------------------------------------------


async def test_manage_run_404_fails_without_touching_rollout(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A manage-mode run whose host 404s fails; the rollout row is untouched."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    rollout_id = await _insert_rollout(db, project_id, user_id, status="running")
    run_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        item_id=None,
        mode="manage",
        rollout_id=rollout_id,
        started_minutes=30,
    )

    poll = AsyncMock(side_effect=_http_status_error(404))
    assert await _reap(db, poll) == 1

    row = await _get_run(db, run_id)
    assert row["status"] == "failed"
    assert row["error_msg"] == (f"{REAPED_NO_RECORD_ERROR} (running for 30m)")
    rollout = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout["status"] == "running"


async def test_rollout_child_adopted_without_touching_rollout(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """A build child run adopted as success leaves the rollout row alone."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    rollout_id = await _insert_rollout(db, project_id, user_id, status="running")
    run_id = await _insert_run(
        db,
        user_id=user_id,
        project_id=project_id,
        rollout_id=rollout_id,
        started_minutes=30,
    )

    poll = AsyncMock(return_value=await _remote(RunStatus.succeeded))
    assert await _reap(db, poll) == 1

    assert (await _get_run(db, run_id))["status"] == "success"
    rollout = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout["status"] == "running"


# ---------------------------------------------------------------------------
# AC-15: historical camera-profiles shape
# ---------------------------------------------------------------------------


async def test_camera_profiles_shape(client: Any, auth_headers: dict[str, str]) -> None:
    """181/186-minute runs under a 180+30 limit wait; a 300-minute run times out."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers, timeout_minutes=180)
    await _insert_host(db, user_id)
    run_181 = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=181
    )
    run_186 = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=186
    )
    run_300 = await _insert_run(
        db, user_id=user_id, project_id=project_id, started_minutes=300
    )

    poll = AsyncMock(side_effect=httpx.ConnectError("host down"))
    assert await _reap(db, poll) == 1

    assert (await _get_run(db, run_181))["status"] == "running"
    assert (await _get_run(db, run_186))["status"] == "running"
    row = await _get_run(db, run_300)
    assert row["status"] == "timeout"
    assert row["error_msg"] == "reaped: dispatch host unreachable for 300m"


# ---------------------------------------------------------------------------
# AC-16: no success without the host
# ---------------------------------------------------------------------------


def _unresolvable_ids() -> list[tuple[str, dict[str, Any]]]:
    """(label, kwargs) for each branch that must never produce 'success'."""
    return [
        ("http_404", {"started_minutes": 30}),
        ("connect_error", {"started_minutes": 400}),
        ("no_remote_run_id", {"started_minutes": 400, "remote_run_id": ""}),
        ("no_host_url", {"started_minutes": 400, "dispatch_host_url": ""}),
        (
            "unmatched_host",
            {"started_minutes": 400, "dispatch_host_url": "http://nowhere"},
        ),
    ]


@pytest.mark.parametrize(
    ("label", "kwargs"),
    _unresolvable_ids(),
)
async def test_no_success_without_the_host(
    client: Any, auth_headers: dict[str, str], label: str, kwargs: dict[str, Any]
) -> None:
    """Every non-adopted terminal path ends failed/timeout with a reaped msg."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id)
    elapsed = kwargs["started_minutes"]
    run_id = await _insert_run(db, user_id=user_id, project_id=project_id, **kwargs)

    if label == "http_404":
        poll: Any = AsyncMock(side_effect=_http_status_error(404))
    elif label == "connect_error":
        poll = AsyncMock(side_effect=httpx.ConnectError("down"))
    else:
        # Unresolvable: the host is never even asked.
        async def _never_polled(*args: Any, **k: Any) -> RunResponse:
            raise AssertionError("host must not be polled")

        poll = _never_polled

    assert await _reap(db, poll) == 1
    row = await _get_run(db, run_id)
    assert row["status"] in {"failed", "timeout"}
    assert row["error_msg"].startswith("reaped: ")
    assert f"{elapsed}m" in row["error_msg"]
    assert REAPER_UNREACHABLE_SLACK_MINUTES == 30


# ---------------------------------------------------------------------------
# AC-14: the item can be dispatched again
# ---------------------------------------------------------------------------


async def test_item_dispatchable_again_after_reap(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """After a reaped stuck run, create_run for the same item succeeds."""
    db = await get_db()
    user_id = await _me(client, auth_headers)
    project_id = await _make_project(client, auth_headers)
    await _insert_host(db, user_id, url=HOST_URL)
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Stranded task"},
        headers=auth_headers,
    )
    item_id = str(res.json()["id"])

    run = await dispatch_service.create_run(db, user_id, item_id)
    run_id = run["id"]
    now = datetime.now(UTC)
    await db.execute(
        "UPDATE claude_runs SET status='running', started_at=$1, remote_run_id=$2,"
        " dispatch_host_url=$3 WHERE id=$4",
        (now - timedelta(hours=2)).isoformat(),
        "r-1",
        HOST_URL,
        run_id,
    )

    with pytest.raises(RunActiveError):
        await dispatch_service.create_run(db, user_id, item_id)

    poll = AsyncMock(side_effect=_http_status_error(404))
    with patch("agent_gtd.dispatch_worker._poll_remote_run", new=poll):
        assert await reap_stuck_runs(db) == 1

    second = await dispatch_service.create_run(db, user_id, item_id)
    assert second["status"] == "pending"
    assert second["id"] != run_id


# ---------------------------------------------------------------------------
# AC-12: loop resilience
# ---------------------------------------------------------------------------


async def test_loop_survives_a_failing_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing pass is logged; the next interval runs another pass."""
    from agent_gtd.services import run_reaper as rr

    passes: list[object] = []

    async def fake_reap(db: Any) -> int:
        passes.append(db)
        if len(passes) == 1:
            raise RuntimeError("boom")
        return 0

    fake_db = object()

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    with (
        patch.object(rr, "reap_stuck_runs", new=fake_reap),
        patch.object(rr, "get_db", new=AsyncMock(return_value=fake_db)),
        patch("asyncio.sleep", new=fake_sleep),
        caplog.at_level(logging.WARNING, logger=REAPER_LOGGER),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_reaper_loop()

    assert len(passes) == 2  # second pass ran after the first raised
    assert passes[0] is fake_db
    assert "run_reaper: pass failed" in caplog.text


async def test_loop_logs_started_before_first_sleep(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The started line is emitted before the loop's first sleep."""

    seen: list[bool] = []

    started_line = "run_reaper: started interval_s=60 grace_s=600 slack_m=30"

    async def fake_sleep(seconds: float) -> None:
        seen.append(started_line in caplog.text)
        raise asyncio.CancelledError

    with (
        patch("asyncio.sleep", new=fake_sleep),
        caplog.at_level(logging.INFO, logger=REAPER_LOGGER),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_reaper_loop()

    assert seen and seen[0] is True


async def test_loop_propagates_cancellation() -> None:
    """CancelledError from a pass ends the loop (not swallowed)."""
    from agent_gtd.services import run_reaper as rr

    async def fake_reap(db: Any) -> int:
        raise asyncio.CancelledError

    async def fake_sleep(seconds: float) -> None:
        return None

    with (
        patch.object(rr, "reap_stuck_runs", new=fake_reap),
        patch.object(rr, "get_db", new=AsyncMock(return_value=object())),
        patch("asyncio.sleep", new=fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_reaper_loop()


# ---------------------------------------------------------------------------
# AC-13: lifespan wiring
# ---------------------------------------------------------------------------


async def test_lifespan_starts_and_cancels_reaper(monkeypatch: Any) -> None:
    """lifespan starts the reaper task and awaits its cancellation on exit."""
    from agent_gtd import main as app_main

    started = asyncio.Event()
    cancelled: list[bool] = []

    async def fake_reaper_loop() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    @asynccontextmanager
    async def fake_mcp_lifespan(app: Any) -> Any:
        yield

    bus = MagicMock()
    bus.drain = AsyncMock()

    monkeypatch.setattr(app_main, "init_db", AsyncMock())
    monkeypatch.setattr(app_main, "_migrate_global_agent_name", AsyncMock())
    monkeypatch.setattr(app_main, "_migrate_engine_name", AsyncMock())
    monkeypatch.setattr(app_main, "_migrate_engine_default_to_sonnet", AsyncMock())
    monkeypatch.setattr(app_main, "_migrate_manager_timeout_default", AsyncMock())
    monkeypatch.setattr(app_main, "close_db", AsyncMock())
    # Keep the shared test app in authenticated mode: is_local_mode() would
    # otherwise install get_local_user into app.dependency_overrides for
    # every later test in the session.
    monkeypatch.setattr(app_main, "is_local_mode", lambda: False)
    monkeypatch.setattr(app_main, "get_event_bus", lambda: bus)
    monkeypatch.setattr(app_main, "mcp_http_lifespan", fake_mcp_lifespan)

    import agent_gtd.dispatch_worker as dw

    with (
        patch.object(dw, "dispatch_worker", new=AsyncMock()),
        patch.object(dw, "reconcile_active_runs", new=AsyncMock()),
        patch.object(dw, "shutdown_worker", new=AsyncMock()),
        patch.object(app_main, "run_reaper_loop", new=fake_reaper_loop),
    ):
        async with app_main.lifespan(app_main.app):
            await asyncio.sleep(0)  # let the reaper task start
            assert started.is_set()

    assert cancelled == [True]
