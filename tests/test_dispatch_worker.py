"""Unit tests for dispatch_worker pure helper functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gtd.dispatch_worker import resolve_agent

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
