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
) -> tuple[str, str]:
    """Create user/project/item/run; return (user_id, run_id).

    Args:
        client: Async HTTP test client.
        auth_headers: Auth headers for the test user.
        remote_run_id: Value to store in ``claude_runs.remote_run_id``.

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
    label: str = "r7-research",
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
    assert "r7-research" in text

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
    assert any("r7-research" in r.getMessage() for r in warnings)


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
