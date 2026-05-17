"""Unit tests for supervise_task helper."""

import asyncio
import logging

import pytest

from agent_gtd.util.tasks import supervise_task


async def test_supervise_task_logs_on_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Raising coroutine → exactly one log record, exception consumed."""

    async def _fail() -> None:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="agent_gtd.util.tasks"):
        task = asyncio.create_task(_fail())
        supervise_task(task, context={"run_id": "test-123", "event_type": "test"})
        await asyncio.sleep(0)  # let the task run and schedule its done callbacks
        await asyncio.sleep(0)  # let the done callbacks fire

    assert len(caplog.records) == 1
    assert "Supervised task failed" in caplog.records[0].message
    # Exception must be consumed — calling task.exception() here returns it
    assert isinstance(task.exception(), RuntimeError)


async def test_supervise_task_silent_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful coroutine → no log records."""

    async def _ok() -> int:
        return 42

    with caplog.at_level(logging.DEBUG, logger="agent_gtd.util.tasks"):
        task = asyncio.create_task(_ok())
        supervise_task(task, context={"run_id": "test-456"})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert caplog.records == []
