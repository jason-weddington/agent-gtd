"""Unit tests for dispatch_worker pure helper functions."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_gtd_dispatch_protocol import DispatchRequest
from agent_gtd_dispatch_protocol import RunResponse as RemoteRunResponse
from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

from agent_gtd import dispatch_worker
from agent_gtd.dispatch_constants import MANAGER_DEFAULT_TIMEOUT_MINUTES
from agent_gtd.dispatch_worker import (
    resolve_agent,
    resolve_engine,
    resolve_max_turns,
    resolve_timeout_minutes,
)


def _make_remote_run_response(
    status: RemoteRunStatus,
    *,
    error: str | None = None,
    run_id: str = "remote-run-1",
) -> RemoteRunResponse:
    """Construct a minimal ``RemoteRunResponse`` for test mocks."""
    return RemoteRunResponse(
        id=run_id,
        item_id=None,
        project_name="test-project",
        branch_name=None,
        engine="claude-code",
        agent_name=None,
        mode="build",
        rollout_id=None,
        status=status,
        started_at=None,
        completed_at=None,
        exit_code=None,
        error=error,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


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
    """Create a minimal DB mock for execute_run tests.

    Returns a ``claude-code-sonnet`` app_settings row for ``dispatch.engine``
    so that ``resolve_engine`` does not raise when mode is not ``manage``.
    """
    db = MagicMock()

    async def fetchrow(sql: str, *args: object) -> dict[str, object] | None:
        if "FROM projects" in sql and project_owner_id is not None:
            return {"user_id": project_owner_id}
        # Seed dispatch.engine so resolve_engine does not raise on build/plan mode.
        if "app_settings" in sql and args and args[0] == "dispatch.engine":
            return {"value": "claude-code-sonnet"}
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

    async def fake_get_dispatch_hosts(db_arg: object, uid: str) -> list:
        captured_user_ids.append(uid)
        return []  # no hosts → run will be marked failed

    with patch(
        "agent_gtd.services.settings_service.get_dispatch_hosts",
        new=fake_get_dispatch_hosts,
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
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=[]),
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

    assert any("not configured dispatch hosts" in msg.lower() for msg in error_msgs), (
        f"Expected clear error message, got: {error_msgs}"
    )


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

    async def fake_get_dispatch_hosts(db_arg: object, uid: str) -> list:
        captured_user_ids.append(uid)
        return []

    with patch(
        "agent_gtd.services.settings_service.get_dispatch_hosts",
        new=fake_get_dispatch_hosts,
    ):
        await execute_run(db, run, item, project)

    # For inbox items, config should be looked up with the caller's ID
    assert caller_id in captured_user_ids


@pytest.mark.asyncio
async def test_execute_run_manage_mode_uses_manager_timeout() -> None:
    """AC-12: mode=manage uses timeout_minutes=240 when no project/DB overrides."""
    from agent_gtd.dispatch_worker import execute_run

    dispatched_timeouts: list[int] = []

    async def fake_dispatch(
        client: object,
        item_id: object,
        max_turns: int,
        mode: str,
        *,
        rollout_id: object = None,
        url: str,
        api_key: str,
        engine: str = "claude-code",
        agent_name: str = "",
        attribution: str = "",
        timeout_minutes: int = 30,
        callback_token: str | None = None,
    ) -> object:
        dispatched_timeouts.append(timeout_minutes)
        raise RuntimeError("stop after dispatch")

    run = {
        "id": "run-mgr-1",
        "item_id": None,
        "user_id": "user-1",
        "project_id": "proj-1",
        "max_turns": 50,
        "mode": "manage",
    }
    project: dict[str, object] = {}  # no dispatch_timeout_minutes override
    db = _make_db_mock(project_owner_id="user-1")

    with (
        patch(
            "agent_gtd.services.settings_service.get_setting",
            new=AsyncMock(return_value=None),  # no DB rows → use hard-coded defaults
        ),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(
                return_value=[
                    {"id": "h1", "url": "http://host", "api_key": "key", "label": ""}
                ]
            ),
        ),
        patch(
            "agent_gtd.services.dispatch_router.pick_dispatch_host",
            new=AsyncMock(return_value={"url": "http://host", "api_key": "key"}),
        ),
        patch(
            "agent_gtd.dispatch_worker._dispatch_to_remote",
            new=fake_dispatch,
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        await execute_run(db, run, None, project)

    assert dispatched_timeouts == [240], (
        f"Expected manage-mode timeout=240, got {dispatched_timeouts}"
    )


@pytest.mark.asyncio
async def test_execute_run_build_mode_uses_worker_timeout() -> None:
    """AC-13: mode=build uses timeout_minutes=30 when no project/DB overrides."""
    from agent_gtd.dispatch_worker import execute_run

    dispatched_timeouts: list[int] = []

    async def fake_dispatch(
        client: object,
        item_id: object,
        max_turns: int,
        mode: str,
        *,
        rollout_id: object = None,
        url: str,
        api_key: str,
        engine: str = "claude-code",
        agent_name: str = "",
        attribution: str = "",
        timeout_minutes: int = 30,
        callback_token: str | None = None,
    ) -> object:
        dispatched_timeouts.append(timeout_minutes)
        raise RuntimeError("stop after dispatch")

    run = {
        "id": "run-build-1",
        "item_id": "item-1",
        "user_id": "user-1",
        "project_id": "proj-1",
        "max_turns": 50,
        "mode": "build",
    }
    project: dict[str, object] = {}  # no dispatch_timeout_minutes override
    db = _make_db_mock(project_owner_id="user-1")

    async def fake_get_setting(db_arg: object, key: str) -> str | None:
        # Provide an explicit engine so resolve_engine does not raise; return
        # None for everything else so the hard-coded defaults kick in.
        if key == "dispatch.engine":
            return "claude-code-sonnet"
        return None

    with (
        patch(
            "agent_gtd.services.settings_service.get_setting",
            new=fake_get_setting,
        ),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(
                return_value=[
                    {"id": "h1", "url": "http://host", "api_key": "key", "label": ""}
                ]
            ),
        ),
        patch(
            "agent_gtd.services.dispatch_router.pick_dispatch_host",
            new=AsyncMock(return_value={"url": "http://host", "api_key": "key"}),
        ),
        patch(
            "agent_gtd.dispatch_worker._dispatch_to_remote",
            new=fake_dispatch,
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        await execute_run(db, run, {}, project)

    assert dispatched_timeouts == [30], (
        f"Expected build-mode timeout=30, got {dispatched_timeouts}"
    )


# ---------------------------------------------------------------------------
# resolve_engine — parametrized matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,item_engine,global_engine,expected",
    [
        # build mode: item engine wins over global
        ("build", "claude-code-ollama", "claude-code-sonnet", "claude-code-ollama"),
        # build mode: item engine None → fallback to global
        ("build", None, "claude-code-sonnet", "claude-code-sonnet"),
        # build mode: item engine "" (falsy) → fallback to global
        ("build", "", "claude-code-sonnet", "claude-code-sonnet"),
        # plan mode: non-talos item engine wins over global (mirrors build)
        ("plan", "claude-code-ollama", "claude-code-sonnet", "claude-code-ollama"),
        ("plan", "claude-code-sonnet", "claude-code", "claude-code-sonnet"),
        ("plan", "claude-code-glm", "claude-code", "claude-code-glm"),
        # plan mode: item engine None → fallback to global
        ("plan", None, "claude-code-sonnet", "claude-code-sonnet"),
        # plan mode: item engine "" (falsy) → fallback to global
        ("plan", "", "claude-code-sonnet", "claude-code-sonnet"),
        # plan mode: talos item engine is NOT honored (build-only) → global fallback
        ("plan", "talos-glm", "claude-code-sonnet", "claude-code-sonnet"),
        ("plan", "talos-glm-flash", "claude-code-sonnet", "claude-code-sonnet"),
        # build mode: talos item engine IS honored (build-only path)
        ("build", "talos-glm", "claude-code-sonnet", "talos-glm"),
        # manage mode: MUST pin to MANAGE_ENGINE (claude-code / Opus) even when
        # the global is sonnet and the item has a different engine — this case
        # proves the sonnet global does NOT downgrade the manager.
        ("manage", "claude-code-ollama", "claude-code-sonnet", "claude-code"),
        # manage mode: item engine ignored regardless of value
        ("manage", "claude-code-sonnet", "claude-code-sonnet", "claude-code"),
        # manage mode with None global: must still return MANAGE_ENGINE without raising
        ("manage", None, None, "claude-code"),
    ],
)
def test_resolve_engine(
    mode: str,
    item_engine: str | None,
    global_engine: str | None,
    expected: str,
) -> None:
    assert resolve_engine(mode, item_engine, global_engine) == expected


def test_resolve_engine_raises_on_unset_global_build() -> None:
    """resolve_engine raises ValueError for build mode when global_engine is None."""
    with pytest.raises(ValueError, match=r"dispatch\.engine global setting is unset"):
        resolve_engine("build", None, None)


def test_resolve_engine_raises_on_unset_global_plan() -> None:
    """resolve_engine raises ValueError for plan mode when global_engine is None."""
    with pytest.raises(ValueError, match=r"dispatch\.engine global setting is unset"):
        resolve_engine("plan", "claude-code-ollama", None)


def test_resolve_engine_raises_on_unset_global_plan_non_talos() -> None:
    """Even a usable (non-talos) item engine doesn't bypass the unset-global check.

    The unset-global guard runs before any item-engine return, so plan mode
    still raises when the global is unset — regardless of whether the item's
    build_engine would otherwise be honored.
    """
    with pytest.raises(ValueError, match=r"dispatch\.engine global setting is unset"):
        resolve_engine("plan", "claude-code-sonnet", None)


def test_resolve_engine_manage_never_raises_on_unset_global() -> None:
    """resolve_engine manage mode returns MANAGE_ENGINE even when global is None."""
    from agent_gtd.dispatch_worker import MANAGE_ENGINE

    result = resolve_engine("manage", None, None)
    assert result == MANAGE_ENGINE == "claude-code"


def test_talos_engines_matches_enum_members_starting_with_talos_prefix() -> None:
    """TALOS_ENGINES is exactly the BuildEngine values starting with 'talos-'."""
    from agent_gtd.models import TALOS_ENGINES, BuildEngine

    expected = {
        member.value for member in BuildEngine if member.value.startswith("talos-")
    }
    assert frozenset(expected) == TALOS_ENGINES
    assert TALOS_ENGINES  # non-empty sanity check


# ---------------------------------------------------------------------------
# resolve_timeout_minutes — parametrized matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,project_timeout,global_worker,global_manager,expected",
    [
        # AC-5: manage mode, no project override → uses global_manager
        ("manage", None, 90, 240, 240),
        # AC-6: build mode, no project override → uses global_worker
        ("build", None, 90, 240, 90),
        # AC-7: plan mode, no project override → uses global_worker
        ("plan", None, 90, 240, 90),
        # AC-8: manage mode with project override → project override wins
        ("manage", 120, 90, 240, 120),
        # AC-9: build mode with project override → project override wins
        ("build", 60, 90, 240, 60),
        # plan mode with project override → project override wins
        ("plan", 45, 90, 240, 45),
        # unknown mode, no project override → uses global_worker (not manage)
        ("other", None, 90, 240, 90),
        # project override of 0 is still falsy-int → not override (None check)
        # (project_timeout=0 means no override when None is the sentinel)
        # Non-None zero IS a valid override value
        ("build", 0, 90, 240, 0),
    ],
)
def test_resolve_timeout_minutes(
    mode: str,
    project_timeout: int | None,
    global_worker: int,
    global_manager: int,
    expected: int,
) -> None:
    result = resolve_timeout_minutes(
        mode=mode,
        project_timeout=project_timeout,
        global_worker=global_worker,
        global_manager=global_manager,
    )
    assert result == expected


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
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(
                return_value=[
                    {
                        "url": "http://dispatch",
                        "api_key": "k",
                        "id": "h1",
                        "label": "default",
                    }
                ]
            ),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(RemoteRunStatus.succeeded)
            ),
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
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(
                return_value=[
                    {
                        "url": "http://dispatch",
                        "api_key": "k",
                        "id": "h1",
                        "label": "default",
                    }
                ]
            ),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(
                    RemoteRunStatus.failed, error="boom"
                )
            ),
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
async def test_poll_exception_retries_in_resume_polling_loop() -> None:
    """A poll exception (e.g. ValidationError for unknown status) retries the loop.

    With typed ``RemoteRunResponse``, unknown remote statuses raise a
    ``ValidationError`` inside ``_poll_remote_run``.  The caller catches it as
    a generic ``Exception``, logs a warning, and retries — it does NOT break
    out of the loop.  The loop terminates only when a terminal status is
    returned on a subsequent poll.
    """
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

    call_count = 0

    async def mock_poll(*args: object, **kwargs: object) -> RemoteRunResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate ValidationError for an unknown status value
            raise ValueError("unknown status 'zombie'")
        return _make_remote_run_response(RemoteRunStatus.succeeded)

    with (
        patch("agent_gtd.dispatch_worker.asyncio.sleep", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._poll_remote_run", new=mock_poll),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
        patch("agent_gtd.dispatch_worker.httpx.AsyncClient") as mock_cls,
        patch("agent_gtd.dispatch_worker.logger") as mock_logger,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        # Should complete after the second poll returns a terminal status
        await _resume_polling(db, run, "remote-z", url="http://test", api_key="key")

    # Loop should have polled twice: once failing, once succeeding
    assert call_count == 2

    # Warning should have been logged for the failed poll with the run_id
    warning_messages = [str(call) for call in mock_logger.warning.call_args_list]
    assert any("run-zombie" in msg for msg in warning_messages), (
        f"Expected warning with run_id 'run-zombie', got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# DispatchRequest serialisation parity (AC-4)
# ---------------------------------------------------------------------------


def test_dispatch_request_serialisation_parity() -> None:
    """DispatchRequest.model_dump matches the previous hand-built body dict.

    This test guards against silent field renames or drops in the shared
    protocol package: if ``DispatchRequest`` changes, either this test fails
    (rename/drop) or a new mypy error appears (missing required field).
    """
    # Required-only fields — no optional fields present
    req = DispatchRequest(
        max_turns=100,
        mode="build",
        engine="claude-code",
        timeout_minutes=30,
    )
    assert req.model_dump(exclude_none=True) == {
        "max_turns": 100,
        "mode": "build",
        "engine": "claude-code",
        "timeout_minutes": 30,
    }


@pytest.mark.parametrize(
    "extra_kwargs,expected_extra",
    [
        # item_id present
        ({"item_id": "item-abc"}, {"item_id": "item-abc"}),
        # agent_name present
        ({"agent_name": "my-agent"}, {"agent_name": "my-agent"}),
        # attribution present
        (
            {"attribution": "claude-build-abc123"},
            {"attribution": "claude-build-abc123"},
        ),
        # rollout_id present
        ({"rollout_id": "rollout-xyz"}, {"rollout_id": "rollout-xyz"}),
        # all optional fields present
        (
            {
                "item_id": "item-1",
                "agent_name": "agent-1",
                "attribution": "claude-build-x",
                "rollout_id": "rollout-1",
            },
            {
                "item_id": "item-1",
                "agent_name": "agent-1",
                "attribution": "claude-build-x",
                "rollout_id": "rollout-1",
            },
        ),
    ],
)
def test_dispatch_request_serialisation_parity_optional_fields(
    extra_kwargs: dict,
    expected_extra: dict,
) -> None:
    """Optional fields appear in model_dump(exclude_none=True) when provided."""
    req = DispatchRequest(
        max_turns=100,
        mode="build",
        engine="claude-code",
        timeout_minutes=30,
        **extra_kwargs,
    )
    result = req.model_dump(exclude_none=True)
    base = {
        "max_turns": 100,
        "mode": "build",
        "engine": "claude-code",
        "timeout_minutes": 30,
    }
    assert result == {**base, **expected_extra}


# ---------------------------------------------------------------------------
# reconcile_active_runs — brand-new-user flow (AC-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_brand_new_user_with_dispatch_host_url() -> None:
    """Brand-new-user reconcile: run row has dispatch_host_url, no legacy user_settings.

    A user who only ever configured dispatch via the hosts API (no legacy
    ``user_settings`` keys) should have their run reconciled correctly:
    - ``dispatch_host_url`` is read from the run row.
    - The api_key is looked up from ``get_dispatch_hosts`` by matching URL.
    - The correct host URL is used to poll the remote status.
    """
    from agent_gtd.dispatch_worker import reconcile_active_runs

    run_id = "run-brand-new-1"
    user_id = "brand-new-user"
    dispatch_url = "http://new-host:9100"
    dispatch_api_key = "new-host-key"

    run_row = {
        "id": run_id,
        "user_id": user_id,
        "project_id": None,  # inbox item — uses caller's own hosts
        "item_id": "item-bn-1",
        "remote_run_id": "remote-bn-1",
        "status": "running",
        "dispatch_host_url": dispatch_url,  # written at dispatch time
    }
    db = _make_reconcile_db_mock([run_row])

    polled_urls: list[str] = []
    polled_keys: list[str] = []

    async def fake_poll(
        client: object,
        remote_run_id: str,
        *,
        url: str,
        api_key: str,
    ) -> RemoteRunResponse:
        polled_urls.append(url)
        polled_keys.append(api_key)
        return _make_remote_run_response(
            RemoteRunStatus.succeeded, run_id=remote_run_id
        )

    # The user has a host registered via the hosts API only — no legacy user_settings.
    fake_hosts = [
        {
            "id": "host-bn-1",
            "url": dispatch_url,
            "api_key": dispatch_api_key,
            "label": "my-host",
        }
    ]

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=fake_hosts),
        ),
        patch("agent_gtd.dispatch_worker._poll_remote_run", new=fake_poll),
        patch("agent_gtd.dispatch_worker._update_run", new=AsyncMock()),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    # Verify the correct host URL and API key were used for polling
    assert polled_urls == [dispatch_url], (
        f"Expected [{dispatch_url}], got {polled_urls}"
    )
    assert polled_keys == [dispatch_api_key], (
        f"Expected [{dispatch_api_key}], got {polled_keys}"
    )


@pytest.mark.asyncio
async def test_reconcile_brand_new_user_missing_host_fails_run() -> None:
    """Brand-new-user reconcile: run has dispatch_host_url but the host is gone.

    If the host recorded in ``dispatch_host_url`` no longer exists in
    ``get_dispatch_hosts`` (e.g. the user deleted it), the run should be
    marked as failed with an informative error message.
    """
    from agent_gtd.dispatch_worker import reconcile_active_runs

    run_id = "run-missing-host"
    user_id = "user-mh"
    dispatch_url = "http://gone-host:9100"

    run_row = {
        "id": run_id,
        "user_id": user_id,
        "project_id": None,
        "item_id": "item-mh",
        "remote_run_id": "remote-mh",
        "status": "running",
        "dispatch_host_url": dispatch_url,
    }
    db = _make_reconcile_db_mock([run_row])

    update_calls: list[dict] = []

    async def fake_update(db_arg: object, rid: str, **kwargs: object) -> None:
        update_calls.append({"run_id": rid, **kwargs})

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=[]),  # host has been removed
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=fake_update),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    assert len(update_calls) == 1
    call = update_calls[0]
    assert call["run_id"] == run_id
    assert call.get("status") == "failed"
    assert "no longer configured" in str(call.get("error_msg", "")).lower()


# ---------------------------------------------------------------------------
# engine_actual truthful forwarding — omit-when-None semantics
# ---------------------------------------------------------------------------
#
# The worker records the engine the remote *actually* used, never mirroring the
# requested engine. _update_run builds a dynamic UPDATE from every passed kwarg,
# so passing engine_actual=None would clobber a set value with SQL NULL — the
# call sites must OMIT the kwarg when the remote reports None.
#
# NOTE: the currently-pinned RemoteRunResponse (protocol github main @ 1.15.0)
# has no engine_actual field, so any test that needs a *populated* engine_actual
# uses a SimpleNamespace stub in place of the real RemoteRunResponse where the
# worker only getattr()s the object. Once the protocol bump lands and
# RunResponse carries engine_actual, these stubs become unnecessary — a real
# RemoteRunResponse(engine_actual=...) can be constructed directly.


def _remote_stub(
    status: RemoteRunStatus,
    *,
    engine_actual: str | None,
    error: str | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for RemoteRunResponse carrying an engine_actual value.

    The worker only reads ``.status``, ``.error`` and
    ``getattr(remote, "engine_actual", None)`` off the remote object, so a
    ``SimpleNamespace`` suffices. Needed because the pinned protocol's
    ``RunResponse`` cannot carry ``engine_actual``.
    """
    return SimpleNamespace(status=status, error=error, engine_actual=engine_actual)


def _make_ea_run_row() -> dict:
    """A running run row for engine_actual reconcile tests."""
    return {
        "id": "run-ea",
        "user_id": "user-ea",
        "project_id": "proj-ea",
        "item_id": "item-ea",
        "remote_run_id": "remote-ea",
        "status": "running",
        "engine": "claude-code",
    }


_EA_HOSTS = [{"url": "http://dispatch", "api_key": "k", "id": "h1", "label": "default"}]


@pytest.mark.asyncio
async def test_reconcile_forwards_reported_engine_actual() -> None:
    """(a) reconcile path (:452): a reported engine_actual reaches _update_run.

    Uses a stub remote because the pinned RemoteRunResponse cannot carry the
    field. The reconcile terminal branch must forward the reported value verbatim.
    """
    from agent_gtd.dispatch_worker import reconcile_active_runs

    db = _make_reconcile_db_mock([_make_ea_run_row()], project_owner_id="user-ea")
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=_EA_HOSTS),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_remote_stub(
                    RemoteRunStatus.succeeded, engine_actual="claude-code-ollama"
                )
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    assert update_mock.call_args.kwargs["engine_actual"] == "claude-code-ollama"


@pytest.mark.asyncio
async def test_reconcile_omits_engine_actual_when_none() -> None:
    """(b) reconcile path (:452): a None engine_actual is OMITTED from _update_run.

    Uses a real RemoteRunResponse (the pinned class lacks engine_actual, so
    getattr yields None). Passing engine_actual=None would write SQL NULL over a
    possibly-set value, so the kwarg must be absent entirely.
    """
    from agent_gtd.dispatch_worker import reconcile_active_runs

    db = _make_reconcile_db_mock([_make_ea_run_row()], project_owner_id="user-ea")
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=_EA_HOSTS),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(RemoteRunStatus.succeeded)
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    assert "engine_actual" not in update_mock.call_args.kwargs


@pytest.mark.asyncio
async def test_resume_polling_omits_engine_actual_when_none() -> None:
    """(c) poll-terminal path (:546): a None engine_actual is OMITTED from _update_run.

    Real RemoteRunResponse (no field -> getattr None). The resumed poll loop's
    terminal branch must not pass engine_actual at all.
    """
    from agent_gtd.dispatch_worker import _resume_polling

    run = {
        "id": "run-ea-resume",
        "item_id": "item-ea-resume",
        "user_id": "user-ea-resume",
        "project_id": "proj-ea-resume",
        "engine": "claude-code",
    }
    db = MagicMock()
    db.execute = AsyncMock()
    mock_client = MagicMock()
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.dispatch_worker.asyncio.sleep", new=AsyncMock()),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(RemoteRunStatus.succeeded)
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
        patch("agent_gtd.dispatch_worker.httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _resume_polling(db, run, "remote-ea-resume", url="http://t", api_key="k")

    assert "engine_actual" not in update_mock.call_args.kwargs


@pytest.mark.asyncio
async def test_resume_polling_forwards_reported_engine_actual() -> None:
    """Poll-terminal path (:546): a reported engine_actual reaches _update_run.

    Stub remote (pinned RemoteRunResponse cannot carry the field). Confirms the
    value branch of the omit-when-None guard at the resumed-poll site.
    """
    from agent_gtd.dispatch_worker import _resume_polling

    run = {
        "id": "run-ea-resume-2",
        "item_id": "item-ea-resume-2",
        "user_id": "user-ea-resume-2",
        "project_id": "proj-ea-resume-2",
        "engine": "claude-code",
    }
    db = MagicMock()
    db.execute = AsyncMock()
    mock_client = MagicMock()
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.dispatch_worker.asyncio.sleep", new=AsyncMock()),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_remote_stub(
                    RemoteRunStatus.succeeded, engine_actual="claude-code"
                )
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
        patch("agent_gtd.dispatch_worker.httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _resume_polling(
            db, run, "remote-ea-resume-2", url="http://t", api_key="k"
        )

    assert update_mock.call_args.kwargs["engine_actual"] == "claude-code"


# ---------------------------------------------------------------------------
# callback_token forwarding — _dispatch_to_remote and execute_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_to_remote_includes_callback_token() -> None:
    """Supplying callback_token causes _dispatch_to_remote to POST it in the JSON body.

    The token must be non-empty and must decode via agent_gtd.auth.decode_token
    back to the originating user_id.
    """
    from agent_gtd.auth import create_token, decode_token
    from agent_gtd.dispatch_worker import _dispatch_to_remote

    user_id = "user-cb-1"
    token = create_token(user_id)

    # A minimal valid remote-run response body
    remote_run_body = {
        "id": "remote-cb-1",
        "item_id": None,
        "project_name": "test-project",
        "branch_name": None,
        "engine": "claude-code",
        "agent_name": None,
        "mode": "build",
        "rollout_id": None,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "created_at": "2026-01-01T00:00:00Z",
    }

    posted_json: list[dict] = []

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = remote_run_body

    async def fake_post(
        url: str, *, json: dict, headers: dict, timeout: float
    ) -> object:
        posted_json.append(json)
        return mock_response

    mock_client = MagicMock()
    mock_client.post = fake_post

    await _dispatch_to_remote(
        mock_client,
        "item-cb-1",
        50,
        "build",
        url="http://dispatch-host",
        api_key="test-key",
        engine="claude-code-sonnet",
        callback_token=token,
    )

    assert len(posted_json) == 1, "Expected exactly one POST"
    body = posted_json[0]
    assert "callback_token" in body, "callback_token must be present in POST JSON"
    cb_token = body["callback_token"]
    assert cb_token, "callback_token must be non-empty"
    decoded_user_id = decode_token(cb_token)
    assert decoded_user_id == user_id, (
        f"Decoded user_id {decoded_user_id!r} != originating user_id {user_id!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("run_mode", ["plan", "build"])
async def test_dispatch_to_remote_callback_token_carries_run_claims(
    run_mode: str,
) -> None:
    """A run-scoped callback token POSTs its run_id/run_mode claims intact.

    This is the producer end of the claim seam the GTD server's
    ``get_run_context`` dependency consumes.
    """
    import jwt

    import agent_gtd.auth
    from agent_gtd.auth import create_token
    from agent_gtd.dispatch_worker import _dispatch_to_remote

    user_id = "user-cb-2"
    token = create_token(user_id, run_id="run-plan-1", run_mode=run_mode)

    remote_run_body = {
        "id": "remote-cb-3",
        "item_id": None,
        "project_name": "test-project",
        "branch_name": None,
        "engine": "claude-code",
        "agent_name": None,
        "mode": run_mode,
        "rollout_id": None,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "created_at": "2026-01-01T00:00:00Z",
    }

    posted_json: list[dict] = []

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = remote_run_body

    async def fake_post(
        url: str, *, json: dict, headers: dict, timeout: float
    ) -> object:
        posted_json.append(json)
        return mock_response

    mock_client = MagicMock()
    mock_client.post = fake_post

    await _dispatch_to_remote(
        mock_client,
        "item-cb-2",
        50,
        run_mode,
        url="http://dispatch-host",
        api_key="test-key",
        engine="claude-code-sonnet",
        callback_token=token,
    )

    assert len(posted_json) == 1, "Expected exactly one POST"
    body = posted_json[0]
    payload = jwt.decode(
        body["callback_token"],
        agent_gtd.auth.SECRET_KEY,
        algorithms=[agent_gtd.auth.ALGORITHM],
    )
    assert payload["run_id"] == "run-plan-1"
    assert payload["run_mode"] == run_mode


@pytest.mark.asyncio
async def test_dispatch_to_remote_none_callback_token_omits_key() -> None:
    """When callback_token=None, model_dump(exclude_none=True) must omit the key.

    This preserves back-compat: callers that don't set a token produce a JSON
    body with no callback_token field at all.
    """
    from agent_gtd.dispatch_worker import _dispatch_to_remote

    remote_run_body = {
        "id": "remote-cb-2",
        "item_id": None,
        "project_name": "test-project",
        "branch_name": None,
        "engine": "claude-code",
        "agent_name": None,
        "mode": "build",
        "rollout_id": None,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "created_at": "2026-01-01T00:00:00Z",
    }

    posted_json: list[dict] = []

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = remote_run_body

    async def fake_post(
        url: str, *, json: dict, headers: dict, timeout: float
    ) -> object:
        posted_json.append(json)
        return mock_response

    mock_client = MagicMock()
    mock_client.post = fake_post

    await _dispatch_to_remote(
        mock_client,
        "item-cb-2",
        50,
        "build",
        url="http://dispatch-host",
        api_key="test-key",
        engine="claude-code-sonnet",
        callback_token=None,  # explicit None — must be omitted from JSON
    )

    assert len(posted_json) == 1, "Expected exactly one POST"
    body = posted_json[0]
    assert "callback_token" not in body, (
        "callback_token must NOT be present in JSON when None (exclude_none=True)"
    )


# ---------------------------------------------------------------------------
# error_msg truncation — the second of two layers (see ERROR_MSG_MAX_CHARS)
# ---------------------------------------------------------------------------


def _long_remote_error(n: int = 1500) -> str:
    """A realistic long pre-commit failure: failing hook at the head, noise after."""
    head = (
        "mypy....................................................Failed\n"
        "- hook id: mypy\n"
        "src/x.py:12: error: Incompatible return value type\n"
    )
    filler = "hook..........................(no files to check) Skipped\n"
    msg = "git commit failed: " + head
    while len(msg) < n:
        msg += filler
    return msg[:n]


def test_error_msg_budget_is_2000() -> None:
    """One named constant, matched to the dispatch service's own budget."""
    from agent_gtd.dispatch_worker import ERROR_MSG_MAX_CHARS

    assert ERROR_MSG_MAX_CHARS == 2000


@pytest.mark.asyncio
async def test_reconcile_mirrors_long_error_msg_uncut() -> None:
    """A ~1500-char remote error survives the reconcile mirror intact.

    The old 500-char clip kept only the tail of the dispatch service's own
    300-char tail, so the failing hook at the HEAD never reached the operator.
    ``runs.error_msg`` is a TEXT column — nothing forces truncation.
    """
    from agent_gtd.dispatch_worker import reconcile_active_runs

    error = _long_remote_error()
    assert len(error) == 1500

    db = _make_reconcile_db_mock([_make_ea_run_row()], project_owner_id="user-ea")
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.database.get_db", new=AsyncMock(return_value=db)),
        patch(
            "agent_gtd.services.settings_service.get_dispatch_hosts",
            new=AsyncMock(return_value=_EA_HOSTS),
        ),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(
                    RemoteRunStatus.failed, error=error
                )
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
    ):
        count = await reconcile_active_runs()

    assert count == 1
    stored = update_mock.call_args.kwargs["error_msg"]
    assert stored == error
    assert "- hook id: mypy" in stored


@pytest.mark.asyncio
async def test_resume_polling_mirrors_long_error_msg_uncut() -> None:
    """Same for the resumed poll loop's terminal branch."""
    from agent_gtd.dispatch_worker import _resume_polling

    error = _long_remote_error()
    run = {
        "id": "run-err-resume",
        "item_id": "item-err-resume",
        "user_id": "user-err-resume",
        "project_id": "proj-err-resume",
        "engine": "claude-code",
    }
    db = MagicMock()
    db.execute = AsyncMock()
    mock_client = MagicMock()
    update_mock = AsyncMock()

    with (
        patch("agent_gtd.dispatch_worker.asyncio.sleep", new=AsyncMock()),
        patch(
            "agent_gtd.dispatch_worker._poll_remote_run",
            new=AsyncMock(
                return_value=_make_remote_run_response(
                    RemoteRunStatus.failed, error=error
                )
            ),
        ),
        patch("agent_gtd.dispatch_worker._update_run", new=update_mock),
        patch("agent_gtd.dispatch_worker._publish_run_event"),
        patch("agent_gtd.dispatch_worker.httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _resume_polling(db, run, "remote-err", url="http://t", api_key="k")

    assert update_mock.call_args.kwargs["error_msg"] == error


class TestProtocolEnumCoverage:
    """The pinned protocol must know every terminal the dispatch service emits.

    Regression guard for a latent production break found 2026-09-19. agent_gtd's
    uv.lock pinned agent-gtd-dispatch-protocol 0.1.0 — a version predating
    `RunStatus.already_satisfied` — while the deployed dispatch service had
    started emitting that terminal (talos exit 30, and the claude-code
    already_satisfied artifact disposition). `_poll_remote_run` validates poll
    responses with `RemoteRunResponse.model_validate`, so the first
    already_satisfied run would have raised a Pydantic ValidationError in the
    poller instead of reconciling. It had not fired yet only because no run had
    reached that terminal in production.

    The failure is silent in exactly the wrong way: nothing warns you that the
    lockfile is behind, and the deploy reports success. Pin the expectation here
    so a future protocol status is a red test rather than a runtime surprise.
    """

    def test_run_status_covers_every_dispatch_terminal(self) -> None:
        from agent_gtd_dispatch_protocol import RunStatus

        members = {m.value for m in RunStatus}
        required = {
            "pending",
            "running",
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
            "already_satisfied",
        }
        missing = required - members
        assert not missing, (
            f"pinned protocol is missing RunStatus members {sorted(missing)} — "
            "run `uv lock --upgrade-package agent-gtd-dispatch-protocol`"
        )

    def test_already_satisfied_poll_response_validates(self) -> None:
        """The exact shape that would have blown up the poller."""
        from agent_gtd.dispatch_worker import RemoteRunResponse

        parsed = RemoteRunResponse.model_validate(
            {
                "id": "0d3482320cfb",
                "item_id": "192d4b13-0000-0000-0000-000000000000",
                "project_name": "flickrasync",
                "branch_name": "feat/demo",
                "engine": "talos-glm-flash",
                "agent_name": None,
                "mode": "build",
                "rollout_id": None,
                "status": "already_satisfied",
                "started_at": "2026-09-19T12:00:00Z",
                "completed_at": "2026-09-19T12:04:00Z",
                "exit_code": 30,
                "error": None,
                "created_at": "2026-09-19T12:00:00Z",
            }
        )
        assert parsed.status.value == "already_satisfied"


class TestAlreadySatisfiedStatusMapping:
    """`already_satisfied` must mirror as a non-error terminal.

    Mapping it to FAILED would halt a rollout wave over work that was already
    correct — the exact false-negative shape the completion contract exists to
    avoid.
    """

    def test_already_satisfied_maps_to_success(self) -> None:
        from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

        from agent_gtd.models import LocalRunStatus

        assert (
            LocalRunStatus.from_remote(RemoteRunStatus.already_satisfied)
            is LocalRunStatus.SUCCESS
        )

    def test_mapping_is_total_over_the_remote_enum(self) -> None:
        """Every remote status maps without raising — the assert_never guard."""
        from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

        from agent_gtd.models import LocalRunStatus

        for remote in RemoteRunStatus:
            assert LocalRunStatus.from_remote(remote) is not None


# ---------------------------------------------------------------------------
# resolve_engine — per-project manage engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "project_manage_engine,expected",
    [
        # NULL / empty → the unchanged default. THIS IS THE NO-REGRESSION CASE:
        # a project that has never set manage_engine must resolve exactly as it
        # did before the column existed.
        (None, "claude-code"),
        ("", "claude-code"),
        # Explicit opt-in to a non-default claude-code-family engine.
        ("claude-code-sonnet", "claude-code-sonnet"),
        ("claude-code-haiku", "claude-code-haiku"),
        ("claude-code-glm", "claude-code-glm"),
        ("claude-code-ollama", "claude-code-ollama"),
        # Explicitly pinning the default is a no-op.
        ("claude-code", "claude-code"),
    ],
)
def test_resolve_engine_manage_uses_project_override(
    project_manage_engine: str | None,
    expected: str,
) -> None:
    """Manage mode consults the project's manage_engine, else MANAGE_ENGINE."""
    assert resolve_engine("manage", None, None, project_manage_engine) == expected


def test_resolve_engine_manage_null_matches_todays_behaviour() -> None:
    """A NULL manage_engine resolves identically to the pre-column call form.

    Explicit no-regression guard: the three-arg call (everything that existed
    before this option) and the four-arg call with NULL must agree, and both
    must be the unchanged MANAGE_ENGINE default.
    """
    from agent_gtd.dispatch_worker import MANAGE_ENGINE

    assert MANAGE_ENGINE == "claude-code"
    for item_engine in (None, "", "claude-code-sonnet", "talos-glm"):
        for global_engine in (None, "claude-code-sonnet", "talos-glm"):
            legacy = resolve_engine("manage", item_engine, global_engine)
            with_null = resolve_engine("manage", item_engine, global_engine, None)
            assert legacy == with_null == MANAGE_ENGINE


def test_resolve_engine_manage_ignores_item_and_global_when_project_set() -> None:
    """The project override beats both the item engine and the global."""
    assert (
        resolve_engine(
            "manage", "claude-code-ollama", "claude-code-sonnet", "claude-code-haiku"
        )
        == "claude-code-haiku"
    )


@pytest.mark.parametrize(
    "talos_engine",
    ["talos-haiku", "talos-sonnet", "talos-opus", "talos-qwen", "talos-glm"],
)
def test_resolve_engine_manage_rejects_talos(talos_engine: str) -> None:
    """A talos manage_engine fails fast with an explicit, informative error."""
    with pytest.raises(ValueError) as exc:
        resolve_engine("manage", None, "claude-code", talos_engine)
    msg = str(exc.value)
    assert talos_engine in msg
    assert "self-verif" in msg
    assert "multi-wave manager loop" in msg


def test_resolve_engine_manage_rejects_non_manage_capable_engine() -> None:
    """A registered but non-claude-code engine is also rejected for manage."""
    with pytest.raises(ValueError, match=r"not manage-capable"):
        resolve_engine("manage", None, "claude-code", "kiro")


def test_manage_capable_engines_are_the_claude_code_family() -> None:
    """The manage-capable set is derived from the enum, not a literal list."""
    from agent_gtd.models import (
        MANAGE_CAPABLE_ENGINES,
        TALOS_ENGINES,
        BuildEngine,
        manage_engine_rejection,
    )

    assert BuildEngine.CLAUDE_CODE.value in MANAGE_CAPABLE_ENGINES
    assert not (MANAGE_CAPABLE_ENGINES & TALOS_ENGINES)
    for name in MANAGE_CAPABLE_ENGINES:
        assert name.startswith("claude-code")
        assert manage_engine_rejection(name) is None
    for name in TALOS_ENGINES:
        assert manage_engine_rejection(name) is not None


@pytest.mark.asyncio
async def test_execute_run_fails_run_on_rejected_manage_engine() -> None:
    """A project carrying a talos manage_engine fails the run with the message."""
    from agent_gtd.dispatch_worker import execute_run

    run = {
        "id": "run-mgr-1",
        "item_id": None,
        "user_id": "user-1",
        "project_id": "proj-1",
        "max_turns": 50,
        "mode": "manage",
    }
    project: dict[str, object] = {"manage_engine": "talos-opus"}
    db = _make_db_mock(project_owner_id="user-1")

    await execute_run(db, run, None, project)

    failures = [
        call.args
        for call in db.execute.await_args_list
        if "UPDATE claude_runs" in str(call.args[0])
    ]
    assert failures, "expected the run row to be updated"
    joined = " ".join(str(a) for call in failures for a in call)
    assert "failed" in joined
    assert "talos-opus" in joined


# ---------------------------------------------------------------------------
# resolve_max_turns — mode-specific branch
# ---------------------------------------------------------------------------


def test_resolve_max_turns_manage_default_matches_build() -> None:
    """Default MANAGE_MAX_TURNS=None: manage resolves exactly as build does.

    This is the no-behavioural-change guard — the seam exists, the value does not
    differ yet.
    """
    assert dispatch_worker.MANAGE_MAX_TURNS is None
    assert resolve_max_turns(None, 100, "manage") == 100
    assert resolve_max_turns(None, 100, "manage") == resolve_max_turns(
        None, 100, "build"
    )


def test_resolve_max_turns_manage_uses_mode_specific_value(monkeypatch) -> None:
    """With a manage-specific budget set, manage mode returns it."""
    monkeypatch.setattr(dispatch_worker, "MANAGE_MAX_TURNS", 25)

    assert resolve_max_turns(None, 100, "manage") == 25


def test_resolve_max_turns_build_and_plan_unchanged_by_manage_value(
    monkeypatch,
) -> None:
    """A manage-specific budget must not leak into build or plan runs."""
    monkeypatch.setattr(dispatch_worker, "MANAGE_MAX_TURNS", 25)

    assert resolve_max_turns(None, 100, "build") == 100
    assert resolve_max_turns(None, 100, "plan") == 100


def test_resolve_max_turns_default_mode_is_build(monkeypatch) -> None:
    """Callers that omit `mode` keep the pre-existing behaviour."""
    monkeypatch.setattr(dispatch_worker, "MANAGE_MAX_TURNS", 25)

    assert resolve_max_turns(None, 100) == 100


def test_resolve_max_turns_project_override_wins_over_manage_value(
    monkeypatch,
) -> None:
    """An explicit per-project budget still beats the manage-specific default."""
    monkeypatch.setattr(dispatch_worker, "MANAGE_MAX_TURNS", 25)

    assert resolve_max_turns(250, 100, "manage") == 250


def test_manager_default_timeout_is_the_single_source_of_truth() -> None:
    """The GTD-side manage timeout constant is authoritative for 240 minutes.

    The dispatch service's ``config.MANAGE_TIMEOUT_SECONDS`` backstop derives
    from this value and must stay numerically equal to it.
    """
    assert MANAGER_DEFAULT_TIMEOUT_MINUTES == 240
    assert MANAGER_DEFAULT_TIMEOUT_MINUTES * 60 == 14400


class TestTerminalStatusCoverage:
    """Every non-running protocol status must be terminal to the poller.

    Regression guard for 2026-09-19: `already_satisfied` was added to the
    protocol enum and to `LocalRunStatus.from_remote` — whose `assert_never`
    guard forced that second update — but `_TERMINAL_STATUSES` was a hand-written
    frozenset and nothing forced it. The poller therefore treated the new
    terminal as "still running" and looped forever: two runs sat at `running`
    for over thirty minutes while the dispatch service had already marked them
    terminal. `run-status --wait` never returns in that state and a Monitor
    never fires, so the failure is invisible rather than loud.
    """

    def test_already_satisfied_is_terminal(self) -> None:
        from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

        from agent_gtd.dispatch_worker import _TERMINAL_STATUSES

        assert RemoteRunStatus.already_satisfied in _TERMINAL_STATUSES

    def test_only_pending_and_running_are_non_terminal(self) -> None:
        """A new protocol status is terminal by default — the safe direction.

        Treating an unknown status as terminal surfaces it immediately, because
        it then maps through from_remote whose assert_never fails loudly.
        Treating it as non-terminal hangs silently, which is the bug this
        guards.
        """
        from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus

        from agent_gtd.dispatch_worker import _TERMINAL_STATUSES

        non_terminal = set(RemoteRunStatus) - set(_TERMINAL_STATUSES)
        assert non_terminal == {
            RemoteRunStatus.pending,
            RemoteRunStatus.running,
        }

    def test_every_terminal_status_maps_locally(self) -> None:
        """No terminal status may break the mapping the poller runs next."""
        from agent_gtd.dispatch_worker import _TERMINAL_STATUSES
        from agent_gtd.models import LocalRunStatus

        for remote in _TERMINAL_STATUSES:
            assert LocalRunStatus.from_remote(remote) is not None


# ---------------------------------------------------------------------------
# resolve_max_turns — the review branch
# ---------------------------------------------------------------------------


def test_resolve_max_turns_review_uses_the_reviewer_budget() -> None:
    """A per-decision reviewer needs far fewer turns than a resident manager."""
    assert dispatch_worker.REVIEW_MAX_TURNS == 40
    assert resolve_max_turns(None, 100, "review") == 40


def test_resolve_max_turns_review_value_does_not_leak_into_other_modes() -> None:
    assert resolve_max_turns(None, 100, "build") == 100
    assert resolve_max_turns(None, 100, "plan") == 100
    assert resolve_max_turns(None, 100, "manage") == 100


def test_resolve_max_turns_project_override_still_wins_for_review() -> None:
    assert resolve_max_turns(250, 100, "review") == 250


def test_resolve_max_turns_review_unset_falls_through(monkeypatch) -> None:
    monkeypatch.setattr(dispatch_worker, "REVIEW_MAX_TURNS", None)
    assert resolve_max_turns(None, 100, "review") == 100


# ---------------------------------------------------------------------------
# resolve_reviewer_engine — rollout -> project -> deployment default (Sonnet)
# ---------------------------------------------------------------------------


def test_reviewer_engine_defaults_to_sonnet_not_opus() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    assert dispatch_worker.REVIEWER_ENGINE == "claude-code-sonnet"
    assert resolve_reviewer_engine(None, None) == "claude-code-sonnet"


def test_reviewer_engine_project_default_beats_the_deployment_default() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    assert resolve_reviewer_engine(None, "claude-code-haiku") == "claude-code-haiku"


def test_reviewer_engine_rollout_override_beats_the_project_default() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    assert resolve_reviewer_engine("claude-code", "claude-code-haiku") == "claude-code"


def test_reviewer_engine_empty_strings_are_treated_as_unset() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    assert resolve_reviewer_engine("", "") == "claude-code-sonnet"


def test_reviewer_engine_rejects_a_talos_engine() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    with pytest.raises(ValueError, match="not supported"):
        resolve_reviewer_engine("talos-sonnet", None)


def test_reviewer_engine_rejects_a_non_harness_engine() -> None:
    from agent_gtd.dispatch_worker import resolve_reviewer_engine

    with pytest.raises(ValueError, match="not review-capable"):
        resolve_reviewer_engine("kiro", None)
