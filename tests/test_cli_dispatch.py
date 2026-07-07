"""Tests for agent_gtd.cli_commands.dispatch.

Covers all three subcommands: dispatch-item, list-runs, list-dispatch-hosts.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent_gtd.cli import build_parser, main
from agent_gtd.cli_commands.dispatch import (
    _cmd_dispatch_item,
    _cmd_list_dispatch_hosts,
    _cmd_list_runs,
)

# ---------------------------------------------------------------------------
# Helpers — minimal dicts
# ---------------------------------------------------------------------------


def _make_run(**overrides: Any) -> dict[str, Any]:
    """Return a minimal run dict."""
    run: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "item_id": str(uuid.uuid4()),
        "status": "pending",
        "mode": "build",
        "max_turns": 50,
    }
    run.update(overrides)
    return run


def _make_host(**overrides: Any) -> dict[str, Any]:
    """Return a minimal dispatch-host dict (id/label/url only)."""
    host: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "label": "test-host",
        "url": "http://localhost:9000",
    }
    host.update(overrides)
    return host


# ---------------------------------------------------------------------------
# Helpers — argparse.Namespace builders
# ---------------------------------------------------------------------------


def _dispatch_item_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for dispatch-item with defaults."""
    defaults: dict[str, Any] = {
        "item_id": str(uuid.uuid4()),
        "mode": "build",
        "max_turns": None,
        "dispatch_host_id": None,
        "rollout_id": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list_runs_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for list-runs with defaults."""
    defaults: dict[str, Any] = {"item_id": None, "status": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list_dispatch_hosts_args() -> argparse.Namespace:
    """Return a Namespace for list-dispatch-hosts (no args)."""
    return argparse.Namespace()


# ---------------------------------------------------------------------------
# FakeBackend — records calls and returns canned results
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Minimal backend stub that records method calls for assertions."""

    def __init__(self) -> None:
        self.dispatch_item_calls: list[dict[str, Any]] = []
        self.list_runs_calls: list[dict[str, Any]] = []
        self.list_dispatch_hosts_calls: int = 0
        self._dispatch_item_result: dict[str, Any] = _make_run()
        self._list_runs_result: list[dict[str, Any]] = []
        self._list_dispatch_hosts_result: list[dict[str, Any]] = []

    async def dispatch_item(
        self,
        user_id: str,
        item_id: str,
        *,
        max_turns: int | None = None,
        mode: str = "build",
        rollout_id: str | None = None,
        dispatch_host_id: str | None = None,
    ) -> dict[str, Any]:
        self.dispatch_item_calls.append(
            {
                "user_id": user_id,
                "item_id": item_id,
                "max_turns": max_turns,
                "mode": mode,
                "rollout_id": rollout_id,
                "dispatch_host_id": dispatch_host_id,
            }
        )
        return self._dispatch_item_result

    async def list_runs(
        self,
        user_id: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.list_runs_calls.append(
            {"user_id": user_id, "item_id": item_id, "status": status}
        )
        return self._list_runs_result

    async def list_dispatch_hosts(self, user_id: str) -> list[dict[str, Any]]:
        self.list_dispatch_hosts_calls += 1
        return self._list_dispatch_hosts_result

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper — monkeypatchable backend_session factory
# ---------------------------------------------------------------------------


def _make_session(backend: Any, user_id: str = "fake-user") -> Any:
    """Return an async context manager function that yields (backend, user_id).

    Pass the result to ``monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )`` to replace the real backend_session.
    """

    @asynccontextmanager  # type: ignore[misc]
    async def _session() -> Any:
        yield backend, user_id

    return _session


# ---------------------------------------------------------------------------
# Tests for _cmd_dispatch_item
# ---------------------------------------------------------------------------


def test_cmd_dispatch_item_passes_args_and_prints_json(monkeypatch, capsys):
    """_cmd_dispatch_item passes all args to backend.dispatch_item, prints JSON."""
    fake = _FakeBackend()
    item_id = str(uuid.uuid4())
    run = _make_run(item_id=item_id, mode="plan", max_turns=10)
    fake._dispatch_item_result = run

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_dispatch_item(
        _dispatch_item_args(
            item_id=item_id, mode="plan", max_turns=10, dispatch_host_id="host-1"
        )
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["id"] == run["id"]

    assert len(fake.dispatch_item_calls) == 1
    call = fake.dispatch_item_calls[0]
    assert call["item_id"] == item_id
    assert call["mode"] == "plan"
    assert call["max_turns"] == 10
    assert call["dispatch_host_id"] == "host-1"


def test_cmd_dispatch_item_mode_manage_rejected_by_parser():
    """--mode manage is rejected by argparse (choices=['build','plan'] only)."""
    parser = build_parser()
    item_id = str(uuid.uuid4())

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["dispatch-item", item_id, "--mode", "manage"])

    assert exc_info.value.code != 0


def test_cmd_dispatch_item_no_enqueue_run_called(monkeypatch, capsys):
    """In local mode, dispatch-item does NOT call enqueue_run."""
    fake = _FakeBackend()
    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )
    enqueue_calls: list[Any] = []

    async def _fake_enqueue(*args: Any, **kwargs: Any) -> None:
        enqueue_calls.append(args)

    monkeypatch.setattr("agent_gtd.dispatch_worker.enqueue_run", _fake_enqueue)

    _cmd_dispatch_item(_dispatch_item_args())

    assert enqueue_calls == [], "enqueue_run must not be called from the CLI handler"


def test_cmd_dispatch_item_backend_error_prints_stderr_exits_1(monkeypatch, capsys):
    """_cmd_dispatch_item prints 'Error:' to stderr and exits 1 on backend exception."""

    @asynccontextmanager  # type: ignore[misc]
    async def _error_session() -> Any:
        class _ErrorBackend:
            async def dispatch_item(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("dispatch failed")

            async def close(self) -> None:
                pass

        yield _ErrorBackend(), "fake-user"

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _error_session
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_dispatch_item(_dispatch_item_args())

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "dispatch failed" in captured.err


def test_cmd_dispatch_item_default_mode_is_build(monkeypatch, capsys):
    """_cmd_dispatch_item with default mode passes mode='build' to backend."""
    fake = _FakeBackend()
    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_dispatch_item(_dispatch_item_args())  # mode defaults to "build"

    assert fake.dispatch_item_calls[0]["mode"] == "build"


# ---------------------------------------------------------------------------
# Tests for _cmd_list_runs
# ---------------------------------------------------------------------------


def test_cmd_list_runs_passes_filters_and_prints_json(monkeypatch, capsys):
    """_cmd_list_runs passes item_id/status to backend and prints the list as JSON."""
    fake = _FakeBackend()
    runs = [_make_run(), _make_run(status="success")]
    fake._list_runs_result = runs

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    item_id = str(uuid.uuid4())
    _cmd_list_runs(_list_runs_args(item_id=item_id, status="pending"))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert len(data) == 2

    assert len(fake.list_runs_calls) == 1
    call = fake.list_runs_calls[0]
    assert call["item_id"] == item_id
    assert call["status"] == "pending"


def test_cmd_list_runs_no_filters_passes_none(monkeypatch, capsys):
    """_cmd_list_runs passes None for both filters when none are supplied."""
    fake = _FakeBackend()
    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_list_runs(_list_runs_args())

    assert fake.list_runs_calls[0]["item_id"] is None
    assert fake.list_runs_calls[0]["status"] is None


def test_cmd_list_runs_error_exits_1(monkeypatch, capsys):
    """_cmd_list_runs prints 'Error:' to stderr and exits 1 on exception."""

    @asynccontextmanager  # type: ignore[misc]
    async def _err_session() -> Any:
        class _ErrBackend:
            async def list_runs(
                self, *args: Any, **kwargs: Any
            ) -> list[dict[str, Any]]:
                raise ValueError("oops")

            async def close(self) -> None:
                pass

        yield _ErrBackend(), "fake-user"

    monkeypatch.setattr("agent_gtd.cli_commands.dispatch.backend_session", _err_session)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_list_runs(_list_runs_args())

    assert exc_info.value.code == 1
    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Tests for _cmd_list_dispatch_hosts
# ---------------------------------------------------------------------------


def test_cmd_list_dispatch_hosts_prints_json(monkeypatch, capsys):
    """_cmd_list_dispatch_hosts prints id/label/url list as JSON to stdout."""
    fake = _FakeBackend()
    hosts = [_make_host(), _make_host(label="worker-2", url="http://worker-2:9001")]
    fake._list_dispatch_hosts_result = hosts

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_list_dispatch_hosts(_list_dispatch_hosts_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert len(data) == 2
    assert data[0]["label"] == "test-host"
    assert "id" in data[0]
    assert "url" in data[0]
    assert fake.list_dispatch_hosts_calls == 1


def test_cmd_list_dispatch_hosts_error_exits_1(monkeypatch, capsys):
    """_cmd_list_dispatch_hosts exits 1 on backend exception."""

    @asynccontextmanager  # type: ignore[misc]
    async def _err_session() -> Any:
        class _ErrBackend:
            async def list_dispatch_hosts(
                self, *args: Any, **kwargs: Any
            ) -> list[dict[str, Any]]:
                raise ConnectionError("no hosts")

            async def close(self) -> None:
                pass

        yield _ErrBackend(), "fake-user"

    monkeypatch.setattr("agent_gtd.cli_commands.dispatch.backend_session", _err_session)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_list_dispatch_hosts(_list_dispatch_hosts_args())

    assert exc_info.value.code == 1
    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# End-to-end argparse resolution tests
# ---------------------------------------------------------------------------


def test_build_parser_dispatch_item_resolves_to_handler():
    """Parsing 'dispatch-item <uuid>' yields Namespace with func=_cmd_dispatch_item."""
    item_id = str(uuid.uuid4())
    parser = build_parser()
    args = parser.parse_args(["dispatch-item", item_id])

    assert args.func is _cmd_dispatch_item
    assert args.item_id == item_id
    assert args.mode == "build"
    assert args.max_turns is None
    assert args.dispatch_host_id is None
    assert args.rollout_id is None


def test_build_parser_list_runs_resolves_to_handler():
    """Parsing 'list-runs' yields Namespace whose func is _cmd_list_runs."""
    parser = build_parser()
    args = parser.parse_args(["list-runs"])

    assert args.func is _cmd_list_runs
    assert args.item_id is None
    assert args.status is None


def test_build_parser_list_dispatch_hosts_resolves_to_handler():
    """Parsing 'list-dispatch-hosts' yields Namespace with the correct handler."""
    parser = build_parser()
    args = parser.parse_args(["list-dispatch-hosts"])

    assert args.func is _cmd_list_dispatch_hosts


def test_build_parser_dispatch_item_mode_plan_accepted():
    """dispatch-item accepts --mode plan."""
    item_id = str(uuid.uuid4())
    parser = build_parser()
    args = parser.parse_args(["dispatch-item", item_id, "--mode", "plan"])

    assert args.mode == "plan"


def test_build_parser_dispatch_item_max_turns_and_host_parsed():
    """--max-turns and --dispatch-host-id are correctly parsed for dispatch-item."""
    item_id = str(uuid.uuid4())
    parser = build_parser()
    args = parser.parse_args(
        [
            "dispatch-item",
            item_id,
            "--max-turns",
            "100",
            "--dispatch-host-id",
            "host-abc",
        ]
    )

    assert args.max_turns == 100
    assert args.dispatch_host_id == "host-abc"


def test_main_dispatches_dispatch_item_via_func_branch(monkeypatch, capsys):
    """main() dispatches 'dispatch-item' to _cmd_dispatch_item via args.func."""
    fake = _FakeBackend()
    run = _make_run()
    fake._dispatch_item_result = run
    item_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "dispatch-item", item_id])

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["id"] == run["id"]
    assert len(fake.dispatch_item_calls) == 1
    assert fake.dispatch_item_calls[0]["item_id"] == item_id


# ---------------------------------------------------------------------------
# Tests for --rollout-id flag
# ---------------------------------------------------------------------------


def test_build_parser_dispatch_item_rollout_id_parsed():
    """--rollout-id <uuid> is parsed and placed in args.rollout_id."""
    item_id = str(uuid.uuid4())
    rollout_id = str(uuid.uuid4())
    parser = build_parser()
    args = parser.parse_args(["dispatch-item", item_id, "--rollout-id", rollout_id])

    assert args.rollout_id == rollout_id


def test_cmd_dispatch_item_rollout_id_forwarded(monkeypatch, capsys):
    """_cmd_dispatch_item forwards rollout_id to backend.dispatch_item."""
    fake = _FakeBackend()
    rollout_id = str(uuid.uuid4())
    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_dispatch_item(_dispatch_item_args(rollout_id=rollout_id))

    assert len(fake.dispatch_item_calls) == 1
    assert fake.dispatch_item_calls[0]["rollout_id"] == rollout_id


def test_cmd_dispatch_item_no_rollout_id_passes_none(monkeypatch, capsys):
    """Omitting --rollout-id passes rollout_id=None to backend.dispatch_item."""
    fake = _FakeBackend()
    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )

    _cmd_dispatch_item(_dispatch_item_args())  # rollout_id defaults to None

    assert len(fake.dispatch_item_calls) == 1
    assert fake.dispatch_item_calls[0]["rollout_id"] is None


def test_main_dispatch_item_rollout_id_forwarded_end_to_end(monkeypatch, capsys):
    """main() with --rollout-id forwards the value to the backend call."""
    fake = _FakeBackend()
    run = _make_run()
    fake._dispatch_item_result = run
    item_id = str(uuid.uuid4())
    rollout_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.dispatch.backend_session", _make_session(fake)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-gtd", "dispatch-item", item_id, "--rollout-id", rollout_id],
    )

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["id"] == run["id"]
    assert fake.dispatch_item_calls[0]["rollout_id"] == rollout_id
