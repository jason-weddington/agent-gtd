"""Unit tests for dispatch_service.reconcile_orphans (AC-2, AC-3, AC-5b)."""

from unittest.mock import AsyncMock, MagicMock, patch

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
