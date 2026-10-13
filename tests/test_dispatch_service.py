"""Unit tests for dispatch_service (reconcile_orphans and cancel_run forwarding)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_orphan_db(rows: list[dict]) -> MagicMock:
    """Create a DB mock that returns ``rows`` from ``.fetch()``."""
    db = MagicMock()
    db.fetch = AsyncMock(return_value=rows)
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# reconcile_orphans — per-row SSE publish (AC-2 / AC-5b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_orphans_publishes_one_event_per_row() -> None:
    """reconcile_orphans publishes one run_failed SSE event per active run row."""
    from agent_gtd.services.dispatch_service import reconcile_orphans

    rows = [
        {"id": "run-o1", "user_id": "u1", "project_id": "p1", "item_id": "i1"},
        {"id": "run-o2", "user_id": "u1", "project_id": "p1", "item_id": "i2"},
    ]
    db = _make_orphan_db(rows)

    mock_bus = MagicMock()
    mock_bus.publish = AsyncMock(return_value=None)

    tasks: list[object] = []

    def capture_task(coro: object) -> MagicMock:
        tasks.append(coro)
        return MagicMock()

    with (
        patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus),
        patch("asyncio.create_task", side_effect=capture_task),
    ):
        count = await reconcile_orphans(db)

    # Drain captured coroutines so publish() is actually called
    for coro in tasks:
        await coro  # type: ignore[misc]

    assert count == 2
    assert mock_bus.publish.call_count == 2

    # Every call must carry reconciled=True, event_type=run_failed
    for c in mock_bus.publish.call_args_list:
        assert c.kwargs["event_type"] == "run_failed"
        assert c.kwargs["payload"]["reconciled"] is True


@pytest.mark.asyncio
async def test_reconcile_orphans_payload_contains_run_id_and_error_msg() -> None:
    """Each published event includes run_id and error_msg in payload."""
    from agent_gtd.services.dispatch_service import reconcile_orphans

    rows = [
        {"id": "run-p1", "user_id": "u1", "project_id": "p1", "item_id": "i1"},
    ]
    db = _make_orphan_db(rows)

    mock_bus = MagicMock()
    mock_bus.publish = AsyncMock(return_value=None)

    tasks: list[object] = []

    def capture_task(coro: object) -> MagicMock:
        tasks.append(coro)
        return MagicMock()

    with (
        patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus),
        patch("asyncio.create_task", side_effect=capture_task),
    ):
        await reconcile_orphans(db)

    for coro in tasks:
        await coro  # type: ignore[misc]

    assert mock_bus.publish.call_count == 1
    payload = mock_bus.publish.call_args.kwargs["payload"]
    assert payload["run_id"] == "run-p1"
    assert "Server restarted" in payload["error_msg"]


@pytest.mark.asyncio
async def test_reconcile_orphans_returns_zero_when_no_active_runs() -> None:
    """reconcile_orphans returns 0 and publishes no events when nothing active."""
    from agent_gtd.services.dispatch_service import reconcile_orphans

    db = _make_orphan_db([])
    mock_bus = MagicMock()
    mock_bus.publish = AsyncMock()

    with patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus):
        count = await reconcile_orphans(db)

    assert count == 0
    mock_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# reconcile_orphans — per-row ID logging (AC-3 GTD side / AC-5b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_orphans_logs_each_run_id() -> None:
    """reconcile_orphans logs each orphaned run ID individually, not just the count."""
    from agent_gtd.services.dispatch_service import reconcile_orphans

    rows = [
        {"id": "run-log-1", "user_id": "u1", "project_id": "p1", "item_id": "i1"},
        {"id": "run-log-2", "user_id": "u1", "project_id": "p1", "item_id": "i2"},
    ]
    db = _make_orphan_db(rows)

    tasks: list[object] = []

    def capture_task(coro: object) -> MagicMock:
        tasks.append(coro)
        return MagicMock()

    mock_bus = MagicMock()
    mock_bus.publish = AsyncMock(return_value=None)

    with (
        patch("agent_gtd.event_bus.get_event_bus", return_value=mock_bus),
        patch("asyncio.create_task", side_effect=capture_task),
        patch("agent_gtd.services.dispatch_service.logger") as mock_logger,
    ):
        await reconcile_orphans(db)

    # Collect all logged messages (info + warning)
    all_messages = [str(c) for c in mock_logger.info.call_args_list]
    all_messages += [str(c) for c in mock_logger.warning.call_args_list]
    combined = "\n".join(all_messages)

    assert "run-log-1" in combined, (
        f"Expected run-log-1 in log messages, got:\n{combined}"
    )
    assert "run-log-2" in combined, (
        f"Expected run-log-2 in log messages, got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# AC-5: create_run rejects mode='manage' (Bug 1 regression test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run_manage_mode_rejected() -> None:
    """AC-5: create_run raises ValidationError when mode='manage'.

    This blocks the old path that allowed a manage run to be keyed to a rollout
    item's ID, which caused RunActiveError deadlock when the manage agent later
    tried to dispatch a child build for that same item.

    Callers must use dispatch_rollout (which calls dispatch_rollout_run) instead.
    """
    from agent_gtd.exceptions import ValidationError as GTDValidationError
    from agent_gtd.services.dispatch_service import create_run

    # DB is never reached because the guard fires first — use a mock.
    db = MagicMock()

    with pytest.raises(GTDValidationError) as exc_info:
        await create_run(
            db,
            user_id="any-user-id",
            item_id="any-item-id",
            mode="manage",
            rollout_id="any-rollout-id",
        )

    # Error message must direct caller to dispatch_rollout
    assert "dispatch_rollout" in str(exc_info.value)


# ---------------------------------------------------------------------------
# cancel_run — cross-service forwarding (AC-4a/4b/4c/4d)
# ---------------------------------------------------------------------------

_FAKE_DISPATCH_CFG = {"url": "http://fake-dispatch", "api_key": "test-key"}


async def _setup_cancel_run_fixture(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    *,
    remote_run_id: str = "",
    dispatch_host_url: str = "",
    status: str | None = None,
    rollout_id: str | None = None,
    mode: str | None = None,
) -> tuple[str, str]:
    """Create user/project/item/run; return (user_id, run_id).

    Args:
        client: Async HTTP test client.
        auth_headers: Auth headers for the test user.
        remote_run_id: Value to store in ``claude_runs.remote_run_id``.
        dispatch_host_url: Value for ``claude_runs.dispatch_host_url`` if set.
        status: Override ``claude_runs.status`` if not None.
        rollout_id: Owning rollout; an ``autonomous_rollouts`` row is inserted.
        mode: Override ``claude_runs.mode`` if not None.

    Returns:
        Tuple of (user_id, run_id).
    """
    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import create_run

    me = await client.get("/api/auth/me", headers=auth_headers)
    user_id: str = me.json()["id"]

    proj = await client.post(
        "/api/projects",
        json={"name": "CancelTest", "git_origin": "git@github.com:test/repo.git"},
        headers=auth_headers,
    )
    project_id: str = proj.json()["id"]

    item = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Cancel task"},
        headers=auth_headers,
    )
    item_id: str = item.json()["id"]

    db = await get_db()
    run = await create_run(db, user_id, item_id)
    run_id: str = run["id"]

    if remote_run_id:
        await db.execute(
            "UPDATE claude_runs SET remote_run_id = $1 WHERE id = $2",
            remote_run_id,
            run_id,
        )
    if dispatch_host_url:
        await db.execute(
            "UPDATE claude_runs SET dispatch_host_url = $1 WHERE id = $2",
            dispatch_host_url,
            run_id,
        )
    if status is not None:
        await db.execute(
            "UPDATE claude_runs SET status = $1 WHERE id = $2", status, run_id
        )
    if mode is not None:
        await db.execute("UPDATE claude_runs SET mode = $1 WHERE id = $2", mode, run_id)
    if rollout_id is not None:
        now = "2026-01-01T00:00:00+00:00"
        await db.execute(
            "INSERT INTO autonomous_rollouts"
            " (id, project_id, lead_user_id, status, created_at, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6)",
            rollout_id,
            project_id,
            user_id,
            "pending",
            now,
            now,
        )
        await db.execute(
            "UPDATE claude_runs SET rollout_id = $1 WHERE id = $2",
            rollout_id,
            run_id,
        )

    return user_id, run_id


def _make_async_client_mock(
    status_code: int = 200,
    text: str = "OK",
    side_effect: Exception | None = None,
) -> MagicMock:
    """Return a mock for ``httpx.AsyncClient`` used as async context manager."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text

    mock_post = AsyncMock(
        return_value=mock_resp,
        side_effect=side_effect,
    )

    # Use MagicMock (not AsyncMock) as the base so the async context-manager
    # protocol is set up manually without leaving unawaited internal coroutines.
    mock_instance = MagicMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_instance.post = mock_post

    return mock_instance


@pytest.mark.asyncio
async def test_cancel_run_forwards_200(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-4a: HTTP 200 → local run cancelled + INFO log emitted."""
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-abc"
    )

    mock_client_instance = _make_async_client_mock(status_code=200)

    with (
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value=_FAKE_DISPATCH_CFG),
        ),
        caplog.at_level(logging.INFO, logger="agent_gtd.services.dispatch_service"),
    ):
        db = await get_db()
        updated = await cancel_run(db, user_id, run_id)

    assert updated["status"] == "cancelled"

    log_text = caplog.text
    assert any(
        "INFO" in r.levelname and run_id in r.message
        for r in caplog.records
        if r.name == "agent_gtd.services.dispatch_service"
    ), f"Expected INFO log containing run_id={run_id!r}, got:\n{log_text}"


@pytest.mark.asyncio
async def test_cancel_run_no_remote_id(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-4b: Empty remote_run_id → local run cancelled + WARN log, no HTTP call."""
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    # remote_run_id left empty (default "")
    user_id, run_id = await _setup_cancel_run_fixture(client, auth_headers)

    mock_client_cls = MagicMock()

    with (
        patch("httpx.AsyncClient", mock_client_cls),
        caplog.at_level(logging.WARNING, logger="agent_gtd.services.dispatch_service"),
    ):
        db = await get_db()
        updated = await cancel_run(db, user_id, run_id)

    assert updated["status"] == "cancelled"

    # No HTTP call should have been made
    mock_client_cls.assert_not_called()

    assert any(
        r.levelno >= logging.WARNING and run_id in r.message
        for r in caplog.records
        if r.name == "agent_gtd.services.dispatch_service"
    ), f"Expected WARNING log containing run_id={run_id!r}, got:\n{caplog.text}"


@pytest.mark.asyncio
async def test_cancel_run_remote_404(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-4c: HTTP 404 → local run cancelled + WARN log."""
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-gone"
    )

    mock_client_instance = _make_async_client_mock(status_code=404, text="Not Found")

    with (
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value=_FAKE_DISPATCH_CFG),
        ),
        caplog.at_level(logging.WARNING, logger="agent_gtd.services.dispatch_service"),
    ):
        db = await get_db()
        updated = await cancel_run(db, user_id, run_id)

    assert updated["status"] == "cancelled"

    assert any(
        r.levelno >= logging.WARNING
        and (
            "not found" in r.message.lower()
            or "404" in r.message
            or run_id in r.message
        )
        for r in caplog.records
        if r.name == "agent_gtd.services.dispatch_service"
    ), f"Expected WARNING log for 404, got:\n{caplog.text}"


@pytest.mark.asyncio
async def test_cancel_run_remote_timeout(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-4d: Dispatch call raises TimeoutException → local run cancelled + WARN log."""
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-slow"
    )

    mock_client_instance = _make_async_client_mock(
        side_effect=httpx.TimeoutException("timeout")
    )

    with (
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value=_FAKE_DISPATCH_CFG),
        ),
        caplog.at_level(logging.WARNING, logger="agent_gtd.services.dispatch_service"),
    ):
        db = await get_db()
        updated = await cancel_run(db, user_id, run_id)

    assert updated["status"] == "cancelled"

    assert any(
        r.levelno >= logging.WARNING and run_id in r.message
        for r in caplog.records
        if r.name == "agent_gtd.services.dispatch_service"
    ), f"Expected WARNING log containing run_id={run_id!r}, got:\n{caplog.text}"


# ---------------------------------------------------------------------------
# Drain refusal in create_run (AC10 — friendly early rejection, owner-scoped)
# ---------------------------------------------------------------------------

_DRAIN_REASON = "rolling deploy 2.0.2"


async def _create_drained_host_setup(
    client: Any,
    auth_headers: dict[str, str],
    user_id: str,
    *,
    label: str = "host-b",
) -> tuple[Any, str, str, str]:
    """Create a monorepo project + item and a drained dispatch host.

    Returns (db, project_id, item_id, host_id).
    """
    import uuid

    from agent_gtd.database import get_db
    from agent_gtd.services.settings_service import add_dispatch_host

    res = await client.post(
        "/api/projects",
        json={"name": f"Drain Project {uuid.uuid4().hex[:6]}", "description": "d"},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]
    await client.patch(
        f"/api/projects/{project_id}",
        json={"git_origin": "https://github.com/example/repo.git"},
        headers=auth_headers,
    )
    item_res = await client.post(
        "/api/items",
        json={
            "title": "Drain item",
            "project_id": project_id,
            "status": "next_action",
        },
        headers=auth_headers,
    )
    assert item_res.status_code == 201, item_res.text
    item_id = item_res.json()["id"]

    db = await get_db()
    host = await add_dispatch_host(
        db, user_id, label, f"http://{label}:8100", "sk-drain-test"
    )
    await db.execute(
        "UPDATE dispatch_hosts SET drain_reason = $1 WHERE id = $2",
        _DRAIN_REASON,
        host["id"],
    )
    return db, project_id, item_id, host["id"]


@pytest.mark.asyncio
async def test_create_run_refuses_drained_host_no_run_row(
    client: Any,
    auth_headers: dict[str, str],
    user_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC10a: an explicit pin to a drained host is rejected; no run row is made."""
    import logging

    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.dispatch_service import create_run

    db, _project_id, item_id, host_id = await _create_drained_host_setup(
        client, auth_headers, user_id
    )

    with pytest.raises(ValidationError) as exc_info:
        await create_run(db, user_id, item_id, mode="build", dispatch_host_id=host_id)
    text = str(exc_info.value)
    assert "is draining" in text
    assert _DRAIN_REASON in text
    assert "host-b" in text

    row = await db.fetchrow(
        "SELECT COUNT(*) AS c FROM claude_runs WHERE item_id = $1", item_id
    )
    assert row is not None
    assert row["c"] == 0

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "Refused dispatch to draining host" in r.getMessage()
    ]
    assert any("host-b" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_create_run_refuses_rollout_inherited_drained_pin(
    client: Any,
    auth_headers: dict[str, str],
    user_id: str,
) -> None:
    """AC10b: a build dispatch inheriting a rollout's drained pin is rejected."""
    import uuid
    from datetime import UTC, datetime

    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.dispatch_service import create_run

    db, project_id, item_id, host_id = await _create_drained_host_setup(
        client, auth_headers, user_id
    )
    rollout_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, dispatch_host_id,"
        " created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rollout_id,
        project_id,
        user_id,
        "running",
        host_id,
        now,
        now,
    )

    with pytest.raises(ValidationError) as exc_info:
        await create_run(db, user_id, item_id, mode="build", rollout_id=rollout_id)
    text = str(exc_info.value)
    assert "is draining" in text
    assert _DRAIN_REASON in text

    row = await db.fetchrow(
        "SELECT COUNT(*) AS c FROM claude_runs WHERE item_id = $1", item_id
    )
    assert row is not None
    assert row["c"] == 0


@pytest.mark.asyncio
async def test_create_run_refuses_drained_host_for_member_caller(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    """AC10c: a project MEMBER pinning the owner's drained host is still refused.

    The check is owner-scoped (str(project['user_id'])) — looking the host
    up under the caller's user_id would silently no-op here, because the
    member owns no dispatch hosts.
    """
    from agent_gtd.auth import register_user
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.dispatch_service import create_run

    res = await client.get("/api/auth/me", headers=auth_headers)
    owner_id = res.json()["id"]

    db, project_id, item_id, host_id = await _create_drained_host_setup(
        client, auth_headers, owner_id
    )
    member = await register_user("member-drain@example.com", "memberpass123")
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        member.id,
        "2026-01-01T00:00:00",
    )

    with pytest.raises(ValidationError) as exc_info:
        await create_run(
            db, str(member.id), item_id, mode="build", dispatch_host_id=host_id
        )
    assert "is draining" in str(exc_info.value)
    assert _DRAIN_REASON in str(exc_info.value)


# ---------------------------------------------------------------------------
# cancel_run: terminal no-op, owning-host resolution, refusal, event
# ---------------------------------------------------------------------------

_SVC_LOGGER = "agent_gtd.services.dispatch_service"
_EPOCH = "2026-01-01T00:00:00+00:00"


def _hosts(drain_b: str | None = None) -> list[dict[str, Any]]:
    return [
        {"url": "https://host-a", "api_key": "ka", "drain_reason": None},
        {"url": "https://host-b", "api_key": "kb", "drain_reason": drain_b},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "failed", "timeout", "cancelled"])
async def test_cancel_run_terminal_is_noop(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    status: str,
) -> None:
    """Terminal runs are returned unchanged with no forward."""
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-x", status=status
    )
    db = await get_db()
    await db.execute(
        "UPDATE claude_runs SET finished_at = $1, updated_at = $2 WHERE id = $3",
        _EPOCH,
        _EPOCH,
        run_id,
    )
    mock_cls = MagicMock()
    with (
        patch("httpx.AsyncClient", mock_cls),
        caplog.at_level(logging.INFO, logger=_SVC_LOGGER),
    ):
        result = await cancel_run(db, user_id, run_id)

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None
    for got in (result, row):
        assert got["status"] == status
        assert got["finished_at"] == _EPOCH
        assert got["updated_at"] == _EPOCH
    mock_cls.assert_not_called()
    assert "cancel_run: noop" in caplog.text


async def _cancel_with_hosts(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    *,
    host_url: str,
    hosts: list[dict[str, Any]],
) -> tuple[MagicMock, AsyncMock, dict[str, Any], str]:
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-abc", dispatch_host_url=host_url
    )
    mock_inst = _make_async_client_mock(status_code=200)
    legacy = AsyncMock()
    with (
        patch("httpx.AsyncClient", return_value=mock_inst),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=hosts),
        ),
        patch("agent_gtd.services.settings_service.get_dispatch_config", new=legacy),
        caplog.at_level(logging.INFO, logger=_SVC_LOGGER),
    ):
        db = await get_db()
        updated = await cancel_run(db, user_id, run_id)
    return mock_inst, legacy, updated, run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("drain", [None, "maintenance"])
async def test_cancel_run_forwards_to_owning_host(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    drain: str | None,
) -> None:
    """The cancel goes to the host matching dispatch_host_url, even if drained."""
    mock_inst, legacy, updated, _ = await _cancel_with_hosts(
        client,
        auth_headers,
        caplog,
        host_url="https://host-b",
        hosts=_hosts(drain),
    )
    assert updated["status"] == "cancelled"
    mock_inst.post.assert_awaited_once()
    args, kwargs = mock_inst.post.await_args
    assert args[0] == "https://host-b/runs/remote-abc/cancel"
    assert kwargs["headers"] == {"Authorization": "Bearer kb"}
    legacy.assert_not_awaited()
    assert "resolution=owning_host host=https://host-b" in caplog.text


@pytest.mark.asyncio
async def test_cancel_run_unmatched_host_no_forward(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    mock_inst, legacy, updated, run_id = await _cancel_with_hosts(
        client, auth_headers, caplog, host_url="https://host-z", hosts=_hosts()
    )
    assert updated["status"] == "cancelled"
    mock_inst.post.assert_not_awaited()
    legacy.assert_not_awaited()
    assert any(
        r.name == _SVC_LOGGER
        and r.levelno == logging.WARNING
        and run_id in r.message
        and "no configured host matches" in r.message
        for r in caplog.records
    )
    assert "resolution=unmatched_host" in caplog.text


@pytest.mark.asyncio
async def test_cancel_run_legacy_resolution_logged(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-abc"
    )
    mock_inst = _make_async_client_mock(status_code=200)
    with (
        patch("httpx.AsyncClient", return_value=mock_inst),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value=_FAKE_DISPATCH_CFG),
        ),
        caplog.at_level(logging.INFO, logger=_SVC_LOGGER),
    ):
        await cancel_run(await get_db(), user_id, run_id)
    mock_inst.post.assert_awaited_once()
    assert "resolution=legacy_config" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rollout_id", "manage"])
async def test_cancel_run_refuses_rollout_runs(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    kind: str,
) -> None:
    from agent_gtd.database import get_db
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.dispatch_service import cancel_run

    kwargs: dict[str, Any] = (
        {"rollout_id": "11111111-1111-1111-1111-111111111111"}
        if kind == "rollout_id"
        else {"mode": "manage"}
    )
    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-abc", **kwargs
    )
    mock_cls = MagicMock()
    db = await get_db()
    with (
        patch("httpx.AsyncClient", mock_cls),
        pytest.raises(ValidationError) as exc,
    ):
        await cancel_run(db, user_id, run_id)
    assert "use cancel-rollout or halt-rollout" in str(exc.value)
    row = await db.fetchrow("SELECT status FROM claude_runs WHERE id = $1", run_id)
    assert row is not None and row["status"] == "pending"
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_run_publishes_event_only_on_transition(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
) -> None:
    from agent_gtd.database import get_db
    from agent_gtd.exceptions import ValidationError
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(client, auth_headers)
    db = await get_db()
    with patch("agent_gtd.event_helpers.best_effort_publish", new=AsyncMock()) as pub:
        await cancel_run(db, user_id, run_id)
        pub.assert_awaited_once()
        assert pub.await_args.kwargs["event_type"] == "run_failed"
        assert pub.await_args.kwargs["entity_id"] == run_id
        # Terminal no-op: no further publish.
        await cancel_run(db, user_id, run_id)
        pub.assert_awaited_once()

    _, run2 = await _setup_cancel_run_fixture(client, auth_headers, mode="manage")
    with patch("agent_gtd.event_helpers.best_effort_publish", new=AsyncMock()) as pub:
        with pytest.raises(ValidationError):
            await cancel_run(db, user_id, run2)
        pub.assert_not_awaited()


# ---------------------------------------------------------------------------
# Force cancel (operator escape hatch for rollout-owned and manage runs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run_force_manage_run(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Force on a manage run cancels it, forwards to the host, rollout untouched."""
    import logging
    import uuid

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    rollout_id = str(uuid.uuid4())
    user_id, run_id = await _setup_cancel_run_fixture(
        client,
        auth_headers,
        remote_run_id="remote-abc",
        dispatch_host_url="https://host-b",
        mode="manage",
        rollout_id=rollout_id,
    )
    db = await get_db()
    await db.execute(
        "UPDATE autonomous_rollouts SET status = 'running' WHERE id = $1", rollout_id
    )

    mock_inst = _make_async_client_mock(status_code=200)
    with (
        patch("httpx.AsyncClient", return_value=mock_inst),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=_hosts()),
        ),
        caplog.at_level(logging.WARNING, logger=_SVC_LOGGER),
    ):
        updated = await cancel_run(db, user_id, run_id, force=True)

    assert updated["status"] == "cancelled"
    assert updated["error_msg"] == "forced by operator"
    mock_inst.post.assert_awaited_once()
    args, _kwargs = mock_inst.post.await_args
    assert args[0] == "https://host-b/runs/remote-abc/cancel"

    rollout = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout is not None
    assert rollout["status"] == "running"
    assert f"cancel_run: forced run_id={run_id}" in caplog.text
    assert "prior_status=pending" in caplog.text


@pytest.mark.asyncio
async def test_cancel_run_force_rollout_build_child(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
) -> None:
    """Force on a rollout's build child cancels it and records the operator."""
    import uuid

    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    rollout_id = str(uuid.uuid4())
    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-child", rollout_id=rollout_id
    )
    db = await get_db()

    updated = await cancel_run(db, user_id, run_id, force=True)
    assert updated["status"] == "cancelled"
    assert updated["error_msg"] == "forced by operator"

    rollout = await db.fetchrow(
        "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert rollout is not None
    assert rollout["status"] == "pending"


@pytest.mark.asyncio
async def test_cancel_run_force_plain_build_run(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
) -> None:
    """Force on a plain build run cancels it with the operator marker + event."""
    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(client, auth_headers)
    db = await get_db()

    with patch("agent_gtd.event_helpers.best_effort_publish", new=AsyncMock()) as pub:
        updated = await cancel_run(db, user_id, run_id, force=True)

    assert updated["status"] == "cancelled"
    assert updated["error_msg"] == "forced by operator"
    pub.assert_awaited_once()
    assert pub.await_args.kwargs["payload"]["forced"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "failed", "timeout", "cancelled"])
async def test_cancel_run_force_terminal_is_noop(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
    status: str,
) -> None:
    """Force on an already-terminal run returns the row unchanged."""
    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(
        client, auth_headers, remote_run_id="remote-x", status=status
    )
    db = await get_db()
    await db.execute(
        "UPDATE claude_runs SET finished_at = $1, updated_at = $2, error_msg = $3"
        " WHERE id = $4",
        _EPOCH,
        _EPOCH,
        "kept",
        run_id,
    )

    mock_cls = MagicMock()
    with patch("httpx.AsyncClient", mock_cls):
        result = await cancel_run(db, user_id, run_id, force=True)

    row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
    assert row is not None
    for got in (result, dict(row)):
        assert got["status"] == status
        assert got["error_msg"] == "kept"
        assert got["finished_at"] == _EPOCH
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_run_without_force_leaves_error_msg(
    client: "httpx.AsyncClient",
    auth_headers: dict[str, str],
) -> None:
    """Without force, the plain cancel writes only status/finished_at/updated_at."""
    from agent_gtd.database import get_db
    from agent_gtd.services.dispatch_service import cancel_run

    user_id, run_id = await _setup_cancel_run_fixture(client, auth_headers)
    db = await get_db()
    await db.execute(
        "UPDATE claude_runs SET error_msg = 'prior failure text' WHERE id = $1",
        run_id,
    )

    updated = await cancel_run(db, user_id, run_id, force=False)
    assert updated["status"] == "cancelled"
    assert updated["error_msg"] == "prior failure text"


def test_parse_run_timestamp_variants() -> None:
    """_parse_run_timestamp reads any timestamp key; _parse_created_at delegates."""
    from datetime import UTC, datetime

    from agent_gtd.services.dispatch_service import (
        _parse_created_at,
        _parse_run_timestamp,
    )

    aware = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    run = {
        "created_at": aware,
        "started_at": "2026-10-13T11:00:00+00:00",
    }
    assert _parse_run_timestamp(run, "created_at") == aware
    assert _parse_run_timestamp(run, "started_at") == datetime(
        2026, 10, 13, 11, 0, tzinfo=UTC
    )
    assert _parse_created_at(run) == aware

    naive = {"started_at": "2026-10-13T11:00:00"}
    assert _parse_run_timestamp(naive, "started_at") == datetime(
        2026, 10, 13, 11, 0, tzinfo=UTC
    )

    assert _parse_run_timestamp({"started_at": "garbage"}, "started_at") is None
    assert _parse_run_timestamp({"started_at": None}, "started_at") is None
    assert _parse_run_timestamp({}, "started_at") is None


# ---------------------------------------------------------------------------
# Stale pending predicate and post-INSERT failure cleanup
# ---------------------------------------------------------------------------


def _stale_cases() -> list[tuple[dict[str, Any], bool]]:
    from datetime import UTC, datetime, timedelta

    from agent_gtd.services.dispatch_service import STALE_PENDING_RUN_SECONDS as T

    now = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)

    def ago(sec: int) -> datetime:
        return now - timedelta(seconds=sec)

    def run(age: int, **kw: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "status": "pending",
            "remote_run_id": "",
            "created_at": ago(age).isoformat(),
        }
        base.update(kw)
        return base

    return [
        (run(T + 1), True),
        (run(T + 1, remote_run_id=None), True),
        (run(T - 1), False),
        (run(T), False),
        (run(T + 1, remote_run_id="x"), False),
        (run(10 * T, status="running"), False),
        (run(10 * T, status="cloning"), False),
        (run(0, created_at=ago(T + 1).strftime("%Y-%m-%dT%H:%M:%SZ")), True),
        (run(0, created_at=ago(T + 1).replace(tzinfo=None).isoformat()), True),
        (run(0, created_at=ago(T + 1)), True),
        (run(0, created_at="garbage"), False),
        ({"status": "pending", "remote_run_id": ""}, False),
    ]


def test_is_stale_pending_run_cases() -> None:
    from datetime import UTC, datetime

    from agent_gtd.services.dispatch_service import _is_stale_pending_run

    now = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)
    for case, expected in _stale_cases():
        assert _is_stale_pending_run(case, now) is expected, case


async def _setup_failing_rollout(
    client: Any, auth_headers: dict[str, str], user_id: str
) -> tuple[Any, str, str, str]:
    import uuid
    from datetime import UTC, datetime

    db, project_id, item_id, _host = await _create_drained_host_setup(
        client, auth_headers, user_id
    )
    rollout_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, dispatch_host_id,"
        " created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rollout_id,
        project_id,
        user_id,
        "running",
        None,
        now,
        now,
    )
    return db, item_id, rollout_id, project_id


@pytest.mark.asyncio
async def test_create_run_marks_run_failed_when_setup_raises_after_insert(
    client: Any,
    auth_headers: dict[str, str],
    user_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from agent_gtd.services.dispatch_service import create_run

    db, item_id, rollout_id, _ = await _setup_failing_rollout(
        client, auth_headers, user_id
    )
    with (
        patch(
            "agent_gtd.services.rollout_service._append_rollout_event",
            AsyncMock(side_effect=RuntimeError("seq collision")),
        ),
        pytest.raises(RuntimeError),
    ):
        await create_run(db, user_id, item_id, mode="build", rollout_id=rollout_id)
    rows = await db.fetch("SELECT * FROM claude_runs WHERE item_id = $1", item_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert (
        rows[0]["error_msg"]
        == "Dispatch setup failed after run creation: RuntimeError: seq collision"
    )
    assert any(
        "dispatch_setup_failed" in r.getMessage()
        and "cleanup=marked_failed" in r.getMessage()
        for r in caplog.records
    )
    new = await create_run(db, user_id, item_id, mode="build")
    assert new["status"] == "pending"
    assert new["id"] != rows[0]["id"]


@pytest.mark.asyncio
async def test_create_run_reraises_original_when_cleanup_fails(
    client: Any,
    auth_headers: dict[str, str],
    user_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from agent_gtd.services.dispatch_service import create_run

    db, item_id, rollout_id, _ = await _setup_failing_rollout(
        client, auth_headers, user_id
    )
    original = db.execute

    async def wrapper(sql: str, *args: Any, **kw: Any) -> Any:
        if sql.startswith("UPDATE claude_runs SET status = 'failed'"):
            raise RuntimeError("cleanup boom")
        return await original(sql, *args, **kw)

    with (
        patch(
            "agent_gtd.services.rollout_service._append_rollout_event",
            AsyncMock(side_effect=RuntimeError("seq collision")),
        ),
        patch.object(db, "execute", side_effect=wrapper),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await create_run(db, user_id, item_id, mode="build", rollout_id=rollout_id)
    assert str(exc_info.value) == "seq collision"
    assert any(
        "dispatch_setup_cleanup_failed" in r.getMessage() for r in caplog.records
    )
