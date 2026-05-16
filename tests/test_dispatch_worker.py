"""Unit tests for dispatch_worker pure helper functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gtd.dispatch_worker import resolve_agent, resolve_engine

# ---------------------------------------------------------------------------
# resolve_agent — parametrized matrix (5-arg form: no legacy fallback fields)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,project_plan,project_build,global_plan,global_build,expected",
    [
        # plan mode: project plan agent wins
        (
            "plan",
            "proj-plan-agent",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "proj-plan-agent",
        ),
        # build mode: project build agent wins
        (
            "build",
            "proj-plan-agent",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "proj-build-agent",
        ),
        # plan mode: no project plan → global plan wins
        (
            "plan",
            None,
            "proj-build-agent",
            "global-plan",
            "global-build",
            "global-plan",
        ),
        # build mode: no project build → global build wins
        (
            "build",
            "proj-plan-agent",
            None,
            "global-plan",
            "global-build",
            "global-build",
        ),
        # plan mode: no project plan or global plan → empty string
        ("plan", None, "proj-build-agent", "", "global-build", ""),
        # build mode: no project build or global build → empty string
        ("build", "proj-plan-agent", None, "global-plan", "", ""),
        # plan mode: all empty → empty string
        ("plan", None, None, "", "", ""),
        # build mode: all empty → empty string
        ("build", None, None, "", "", ""),
        # plan mode: empty string project plan (falsy) → falls through to global plan
        (
            "plan",
            "",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "global-plan",
        ),
        # build mode: empty string project build (falsy) → falls through to global build
        (
            "build",
            "proj-plan-agent",
            "",
            "global-plan",
            "global-build",
            "global-build",
        ),
    ],
)
def test_resolve_agent(
    mode: str,
    project_plan: str | None,
    project_build: str | None,
    global_plan: str,
    global_build: str,
    expected: str,
) -> None:
    result = resolve_agent(
        mode=mode,
        project_plan_agent=project_plan,
        project_build_agent=project_build,
        global_plan_agent=global_plan,
        global_build_agent=global_build,
    )
    assert result == expected


# ---------------------------------------------------------------------------
# execute_run — owner config lookup
# ---------------------------------------------------------------------------


def _make_db_mock(project_owner_id: str | None = None) -> MagicMock:
    """Create a minimal DB mock for execute_run tests."""
    db = MagicMock()

    async def fetchrow(sql: str, *args: object) -> dict[str, object] | None:
        if "FROM projects" in sql and project_owner_id is not None:
            return {"user_id": project_owner_id}
        return None

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    return db


@pytest.mark.asyncio
async def test_execute_run_uses_project_owner_config() -> None:
    """execute_run looks up the project owner and uses their dispatch config."""
    from agent_gtd.dispatch_worker import execute_run

    owner_id = "owner-uuid"
    caller_id = "caller-uuid"

    run = {
        "id": "run-1",
        "item_id": "item-1",
        "user_id": caller_id,
        "project_id": "proj-1",
        "max_turns": 50,
        "mode": "build",
    }
    item: dict[str, object] = {}
    project: dict[str, object] = {}
    db = _make_db_mock(project_owner_id=owner_id)

    captured_user_ids: list[str] = []

    async def fake_get_dispatch_config(db_arg: object, uid: str) -> None:
        captured_user_ids.append(uid)
        return None  # no config → run will be marked failed

    with patch(
        "agent_gtd.services.settings_service.get_dispatch_config",
        new=fake_get_dispatch_config,
    ):
        await execute_run(db, run, item, project)

    # Config should have been looked up with the owner's ID, not the caller's
    assert owner_id in captured_user_ids
    assert caller_id not in captured_user_ids


@pytest.mark.asyncio
async def test_execute_run_owner_no_config_fails_with_clear_message() -> None:
    """When project owner has no dispatch config, run fails with a clear message."""
    from agent_gtd.dispatch_worker import execute_run

    owner_id = "owner-uuid"
    run = {
        "id": "run-2",
        "item_id": "item-2",
        "user_id": "caller-uuid",
        "project_id": "proj-2",
        "max_turns": 50,
        "mode": "build",
    }
    item: dict[str, object] = {}
    project: dict[str, object] = {}
    db = _make_db_mock(project_owner_id=owner_id)

    error_msgs: list[str] = []

    async def fake_update_run(
        db_arg: object,
        run_id: str,
        *,
        status: str = "",
        finished_at: str = "",
        error_msg: str = "",
    ) -> None:
        if error_msg:
            error_msgs.append(error_msg)

    with (
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent_gtd.dispatch_worker._update_run",
            new=fake_update_run,
        ),
        patch(
            "agent_gtd.dispatch_worker._publish_run_event",
        ),
    ):
        await execute_run(db, run, item, project)

    assert any(
        "Project owner has not configured dispatch" in msg for msg in error_msgs
    ), f"Expected clear error message, got: {error_msgs}"


@pytest.mark.asyncio
async def test_execute_run_inbox_item_uses_caller_config() -> None:
    """Inbox items (no project_id) use the caller's own dispatch config."""
    from agent_gtd.dispatch_worker import execute_run

    caller_id = "inbox-user"
    run = {
        "id": "run-3",
        "item_id": "item-3",
        "user_id": caller_id,
        "project_id": None,  # inbox item
        "max_turns": 50,
        "mode": "build",
    }
    item: dict[str, object] = {}
    project: dict[str, object] = {}
    db = _make_db_mock(project_owner_id=None)

    captured_user_ids: list[str] = []

    async def fake_get_dispatch_config(db_arg: object, uid: str) -> None:
        captured_user_ids.append(uid)
        return None

    with patch(
        "agent_gtd.services.settings_service.get_dispatch_config",
        new=fake_get_dispatch_config,
    ):
        await execute_run(db, run, item, project)

    # For inbox items, config should be looked up with the caller's ID
    assert caller_id in captured_user_ids


# ---------------------------------------------------------------------------
# resolve_engine — parametrized matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,item_engine,global_engine,expected",
    [
        # build mode: item engine wins
        ("build", "claude-code-ollama", "claude", "claude-code-ollama"),
        # build mode: item engine None → fallback to global
        ("build", None, "claude", "claude"),
        # build mode: item engine "" (falsy) → fallback to global
        ("build", "", "claude", "claude"),
        # plan mode: item engine is ignored → always use global
        ("plan", "claude-code-ollama", "claude", "claude"),
        # manage mode: item engine is ignored → always use global
        ("manage", "claude-code-ollama", "claude", "claude"),
    ],
)
def test_resolve_engine(
    mode: str,
    item_engine: str | None,
    global_engine: str,
    expected: str,
) -> None:
    assert resolve_engine(mode, item_engine, global_engine) == expected


# ---------------------------------------------------------------------------
# reconcile_active_runs — SSE publish (AC-1)
# ---------------------------------------------------------------------------


def _make_reconcile_db_mock(
    run_rows: list[dict],
    project_owner_id: str | None = None,
) -> MagicMock:
    """Create a minimal DB mock for reconcile_active_runs tests."""
    db = MagicMock()
    db.fetch = AsyncMock(return_value=run_rows)

    async def fetchrow(sql: str, *args: object) -> dict | None:
        if "FROM projects" in sql and project_owner_id is not None:
            return {"user_id": project_owner_id}
        return None

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_reconcile_active_runs_publishes_run_completed_event() -> None:
    """reconcile_active_runs emits run_completed with reconciled=True."""
    from agent_gtd.dispatch_worker import reconcile_active_runs

    run_id = "run-recon-1"
    user_id = "user-r1"
    project_id = "proj-r1"
    item_id = "item-r1"

    run_row = {
        "id": run_id,
        "user_id": user_id,
        "project_id": project_id,
        "item_id": item_id,
        "remote_run_id": "remote-r1",
        "status": "running",
    }
    db = _make_reconcile_db_mock([run_row], project_owner_id=user_id)

    publish_calls: list[dict] = []

    def fake_publish(
        db_arg: object,
        uid: str,
        rid: str,
        iid: object,
        run: object,
        etype: str,
        *,
        reconciled: bool = False,
    ) -> None:
        publish_calls.append(
            {
                "user_id": uid,
                "run_id": rid,
                "item_id": iid,
                "event_type": etype,
                "reconciled": reconciled,
            }
        )

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value={"url": "http://dispatch", "api_key": "k"}),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(return_value={"status": "succeeded", "error": None}),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event", new=fake_publish),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    assert len(publish_calls) == 1
    call = publish_calls[0]
    assert call["event_type"] == "run_completed"
    assert call["reconciled"] is True
    assert call["run_id"] == run_id
    assert call["item_id"] == item_id


@pytest.mark.asyncio
async def test_reconcile_active_runs_publishes_run_failed_event() -> None:
    """reconcile_active_runs emits run_failed with reconciled=True for failed run."""
    from agent_gtd.dispatch_worker import reconcile_active_runs

    run_row = {
        "id": "run-recon-2",
        "user_id": "user-r2",
        "project_id": "proj-r2",
        "item_id": "item-r2",
        "remote_run_id": "remote-r2",
        "status": "running",
    }
    db = _make_reconcile_db_mock([run_row], project_owner_id="user-r2")

    publish_calls: list[dict] = []

    def fake_publish(
        db_arg: object,
        uid: str,
        rid: str,
        iid: object,
        run: object,
        etype: str,
        *,
        reconciled: bool = False,
    ) -> None:
        publish_calls.append({"event_type": etype, "reconciled": reconciled})

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_config",
            new=AsyncMock(return_value={"url": "http://dispatch", "api_key": "k"}),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(return_value={"status": "failed", "error": "boom"}),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event", new=fake_publish),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    assert len(publish_calls) == 1
    assert publish_calls[0]["event_type"] == "run_failed"
    assert publish_calls[0]["reconciled"] is True


# ---------------------------------------------------------------------------
# Unknown remote status — poll loop guard (AC-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_remote_status_breaks_resume_polling_loop() -> None:
    """Unknown remote status breaks _resume_polling loop with a WARNING log."""
    from agent_gtd.dispatch_worker import _resume_polling

    run = {
        "id": "run-zombie",
        "item_id": "item-z",
        "user_id": "user-z",
        "project_id": "proj-z",
    }
    db = MagicMock()
    db.execute = AsyncMock()

    mock_client = MagicMock()

    with (
        patch("agent_gtd.dispatch_worker.asyncio.sleep", new=AsyncMock()),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(return_value={"status": "zombie"}),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
        patch("agent_gtd.dispatch_worker.httpx.AsyncClient") as mock_cls,
        patch("agent_gtd.dispatch_worker.logger") as mock_logger,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        # Should complete (not loop forever)
        await _resume_polling(db, run, "remote-z", url="http://test", api_key="key")

    # Warning must carry the run_id and the unknown status string
    warning_messages = [str(call) for call in mock_logger.warning.call_args_list]
    assert any("zombie" in msg for msg in warning_messages), (
        f"Expected warning about 'zombie' status, got: {warning_messages}"
    )
    assert any("run-zombie" in msg for msg in warning_messages), (
        f"Expected warning with run_id 'run-zombie', got: {warning_messages}"
    )
