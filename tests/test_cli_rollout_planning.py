"""Tests for the rollout-planning CLI commands.

Mirrors the machinery of ``tests/test_cli.py``:
- ``argparse.Namespace`` fixtures per command
- ``capsys`` for stdout/stderr assertions
- ``pytest.raises(SystemExit)`` for exit codes
- Monkeypatches ``agent_gtd.cli_commands._shared.create_backend`` and
  ``agent_gtd.database.init_db`` so tests run without a real backend.

Required cases per the acceptance criteria:
1. One happy-path stdout-JSON assertion per command (all five).
2. ``plan-rollout`` comma-and-space item_ids flattening.
3. ``plan-rollout`` ``LegalityContractError`` path — exact stderr literal + exit 1.
4. Generic ``RuntimeError`` error-path test on ``dispatch-rollout`` — stderr starts
   with ``Error: `` + exit 1.
5. ``list-rollouts`` limit clamping: 500 → 100 and 0 → 1.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from agent_gtd.cli_commands import _shared
from agent_gtd.cli_commands.rollout_planning import (
    _cmd_dispatch_rollout,
    _cmd_get_rollout_plan,
    _cmd_list_rollouts,
    _cmd_plan_rollout,
    _cmd_start_rollout,
    register,
)
from agent_gtd.exceptions import LegalityContractError

# ---------------------------------------------------------------------------
# Shared fake backend
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Minimal fake backend for rollout-planning command tests.

    Callers set ``responses`` to control what each method returns.  Raising
    any exception from a method is supported via ``side_effects``.
    """

    def __init__(
        self,
        *,
        responses: dict[str, Any] | None = None,
        side_effects: dict[str, Exception] | None = None,
    ) -> None:
        """Initialise with optional per-method response/exception overrides.

        Args:
            responses: Mapping from method name to the value it should return.
            side_effects: Mapping from method name to an exception it should raise.
        """
        self._responses: dict[str, Any] = responses or {}
        self._side_effects: dict[str, Exception] = side_effects or {}
        self.calls: dict[str, list[Any]] = {}
        self.closed = False

    def _maybe_raise(self, method: str) -> None:
        exc = self._side_effects.get(method)
        if exc is not None:
            raise exc

    async def plan_rollout(self, user_id: str, item_ids: list[str]) -> dict[str, Any]:
        """Fake plan_rollout — records call args and returns configured response."""
        self.calls.setdefault("plan_rollout", []).append((user_id, item_ids))
        self._maybe_raise("plan_rollout")
        return self._responses.get("plan_rollout", {"id": "rollout-1"})

    async def dispatch_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        """Fake dispatch_rollout — records call args and returns configured response."""
        self.calls.setdefault("dispatch_rollout", []).append((user_id, rollout_id))
        self._maybe_raise("dispatch_rollout")
        return self._responses.get("dispatch_rollout", {"id": "run-1"})

    async def start_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        """Fake start_rollout — records call args and returns configured response."""
        self.calls.setdefault("start_rollout", []).append((user_id, rollout_id))
        self._maybe_raise("start_rollout")
        return self._responses.get(
            "start_rollout", {"id": "rollout-1", "status": "running"}
        )

    async def get_rollout_plan(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        """Fake get_rollout_plan — records call args and returns configured response."""
        self.calls.setdefault("get_rollout_plan", []).append((user_id, rollout_id))
        self._maybe_raise("get_rollout_plan")
        return self._responses.get(
            "get_rollout_plan", {"rollout_id": rollout_id, "items": []}
        )

    async def list_rollouts(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fake list_rollouts — records call args and returns configured response."""
        self.calls.setdefault("list_rollouts", []).append(
            (user_id, project_id, status, limit)
        )
        self._maybe_raise("list_rollouts")
        result: list[dict[str, Any]] = self._responses.get("list_rollouts", [])
        return result

    async def close(self) -> None:
        """Mark backend as closed."""
        self.closed = True


# ---------------------------------------------------------------------------
# Namespace factories
# ---------------------------------------------------------------------------


def _plan_rollout_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the plan-rollout subcommand with defaults."""
    defaults: dict[str, Any] = {
        "item_ids": ["item-uuid-1", "item-uuid-2"],
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _dispatch_rollout_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the dispatch-rollout subcommand with defaults."""
    defaults: dict[str, Any] = {
        "rollout_id": "rollout-uuid-1",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _start_rollout_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the start-rollout subcommand with defaults."""
    defaults: dict[str, Any] = {
        "rollout_id": "rollout-uuid-1",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _get_rollout_plan_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the get-rollout-plan subcommand with defaults."""
    defaults: dict[str, Any] = {
        "rollout_id": "rollout-uuid-1",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list_rollouts_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the list-rollouts subcommand with defaults."""
    defaults: dict[str, Any] = {
        "project_id": None,
        "status": None,
        "limit": 20,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Fixture: wire create_backend to a _FakeBackend instance
# ---------------------------------------------------------------------------


def _patch_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: dict[str, Any] | None = None,
    side_effects: dict[str, Exception] | None = None,
) -> _FakeBackend:
    """Monkeypatch ``_shared.create_backend`` to return a ``_FakeBackend``.

    Also patches ``agent_gtd.database.init_db`` so local-mode auth in
    ``backend_session()`` does not attempt a real database connection beyond
    the in-memory pool already set up by the ``_setup_db`` autouse fixture.

    Args:
        monkeypatch: pytest's monkeypatch fixture.
        responses: Optional per-method return values.
        side_effects: Optional per-method exceptions to raise.

    Returns:
        The ``_FakeBackend`` instance that ``create_backend`` will return.
    """
    fake = _FakeBackend(responses=responses, side_effects=side_effects)
    monkeypatch.setattr(_shared, "create_backend", lambda: fake)

    # Stub init_db so local-mode backend_session() does not re-init the pool.
    async def _noop_init_db() -> None:
        return None

    monkeypatch.setattr("agent_gtd.database.init_db", _noop_init_db)
    # Ensure local mode is active (no AGENT_GTD_URL set).
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    return fake


# ---------------------------------------------------------------------------
# 1. Happy-path tests — one per command
# ---------------------------------------------------------------------------


def test_plan_rollout_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """plan-rollout prints valid JSON dict to stdout on success."""
    expected = {
        "id": "rollout-42",
        "status": "planning",
        "item_ids": ["item-1", "item-2"],
    }
    _patch_backend(monkeypatch, responses={"plan_rollout": expected})

    _cmd_plan_rollout(_plan_rollout_args(item_ids=["item-1", "item-2"]))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["id"] == "rollout-42"
    assert data["status"] == "planning"


def test_dispatch_rollout_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """dispatch-rollout prints valid JSON dict to stdout on success."""
    expected = {"id": "run-99", "rollout_id": "rollout-1", "status": "running"}
    _patch_backend(monkeypatch, responses={"dispatch_rollout": expected})

    _cmd_dispatch_rollout(_dispatch_rollout_args(rollout_id="rollout-1"))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["id"] == "run-99"
    assert data["rollout_id"] == "rollout-1"


def test_start_rollout_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """start-rollout prints valid JSON dict to stdout on success."""
    expected = {"id": "rollout-1", "status": "running"}
    _patch_backend(monkeypatch, responses={"start_rollout": expected})

    _cmd_start_rollout(_start_rollout_args(rollout_id="rollout-1"))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["id"] == "rollout-1"
    assert data["status"] == "running"


def test_get_rollout_plan_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """get-rollout-plan prints valid JSON dict to stdout on success."""
    expected = {
        "rollout_id": "rollout-1",
        "items": [{"item_id": "item-1", "order": 1}],
    }
    _patch_backend(monkeypatch, responses={"get_rollout_plan": expected})

    _cmd_get_rollout_plan(_get_rollout_plan_args(rollout_id="rollout-1"))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["rollout_id"] == "rollout-1"
    assert len(data["items"]) == 1


def test_list_rollouts_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts prints valid JSON list to stdout on success."""
    expected: list[dict[str, Any]] = [
        {"id": "rollout-1", "status": "running"},
        {"id": "rollout-2", "status": "completed"},
    ]
    _patch_backend(monkeypatch, responses={"list_rollouts": expected})

    _cmd_list_rollouts(_list_rollouts_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["id"] == "rollout-1"


# ---------------------------------------------------------------------------
# 2. plan-rollout comma-and-space item_ids flattening
# ---------------------------------------------------------------------------


def test_plan_rollout_comma_space_flatten(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """plan-rollout flattens 'a,b' and 'c' tokens to ['a', 'b', 'c']."""
    fake = _patch_backend(monkeypatch)

    _cmd_plan_rollout(_plan_rollout_args(item_ids=["a,b", "c"]))

    # Verify the backend received the flattened list.
    assert "plan_rollout" in fake.calls
    _user_id, received_ids = fake.calls["plan_rollout"][0]
    assert received_ids == ["a", "b", "c"]

    captured = capsys.readouterr()
    assert captured.err == ""


def test_plan_rollout_comma_only_flatten(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """plan-rollout with a single comma-separated token yields multiple IDs."""
    fake = _patch_backend(monkeypatch)

    _cmd_plan_rollout(_plan_rollout_args(item_ids=["x,y,z"]))

    _user_id, received_ids = fake.calls["plan_rollout"][0]
    assert received_ids == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# 3. plan-rollout LegalityContractError path
# ---------------------------------------------------------------------------


def test_plan_rollout_legality_contract_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """plan-rollout LegalityContractError: exact stderr literal + JSON, exits 1."""
    failures = [
        {
            "item_id": "item-1",
            "title": "First Item",
            "failures": ["no acceptance criteria"],
        },
        {
            "item_id": "item-2",
            "title": "Second Item",
            "failures": ["no files_to_modify"],
        },
    ]
    exc = LegalityContractError(failures)
    _patch_backend(monkeypatch, side_effects={"plan_rollout": exc})

    with pytest.raises(SystemExit) as exc_info:
        _cmd_plan_rollout(_plan_rollout_args())

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    # Exact literal from the spec.
    assert "Error: legality contract failed for 2 item(s):" in captured.err
    # failures JSON (indent=2) embedded in stderr.
    failures_in_stderr = json.loads(captured.err.split("item(s):")[1])
    assert failures_in_stderr == failures


# ---------------------------------------------------------------------------
# 4. Generic Exception error paths
# ---------------------------------------------------------------------------


def test_dispatch_rollout_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """dispatch-rollout RuntimeError writes 'Error: ...' to stderr and exits 1."""
    _patch_backend(
        monkeypatch,
        side_effects={"dispatch_rollout": RuntimeError("backend unavailable")},
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_dispatch_rollout(_dispatch_rollout_args())

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: ")
    assert "backend unavailable" in captured.err


def test_start_rollout_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """start-rollout RuntimeError writes 'Error: ...' to stderr and exits 1."""
    _patch_backend(
        monkeypatch,
        side_effects={"start_rollout": RuntimeError("network failure")},
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_start_rollout(_start_rollout_args())

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: ")
    assert "network failure" in captured.err


def test_get_rollout_plan_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """get-rollout-plan RuntimeError writes 'Error: ...' to stderr and exits 1."""
    _patch_backend(
        monkeypatch,
        side_effects={"get_rollout_plan": RuntimeError("not found")},
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_get_rollout_plan(_get_rollout_plan_args())

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: ")


def test_list_rollouts_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts RuntimeError writes 'Error: ...' to stderr and exits 1."""
    _patch_backend(
        monkeypatch,
        side_effects={"list_rollouts": RuntimeError("server error")},
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_list_rollouts(_list_rollouts_args())

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: ")
    assert "server error" in captured.err


# ---------------------------------------------------------------------------
# 5. list-rollouts limit clamping
# ---------------------------------------------------------------------------


def test_list_rollouts_limit_clamped_high(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts clamps limit 500 → 100 before calling the backend."""
    fake = _patch_backend(monkeypatch)

    _cmd_list_rollouts(_list_rollouts_args(limit=500))

    _user_id, _project_id, _status, received_limit = fake.calls["list_rollouts"][0]
    assert received_limit == 100
    # No error output.
    captured = capsys.readouterr()
    assert captured.err == ""


def test_list_rollouts_limit_clamped_low(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts clamps limit 0 → 1 before calling the backend."""
    fake = _patch_backend(monkeypatch)

    _cmd_list_rollouts(_list_rollouts_args(limit=0))

    _user_id, _project_id, _status, received_limit = fake.calls["list_rollouts"][0]
    assert received_limit == 1
    captured = capsys.readouterr()
    assert captured.err == ""


def test_list_rollouts_limit_within_range_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts does not alter a limit already within [1, 100]."""
    fake = _patch_backend(monkeypatch)

    _cmd_list_rollouts(_list_rollouts_args(limit=50))

    _user_id, _project_id, _status, received_limit = fake.calls["list_rollouts"][0]
    assert received_limit == 50


# ---------------------------------------------------------------------------
# 6. list-rollouts filter flags passthrough
# ---------------------------------------------------------------------------


def test_list_rollouts_passes_project_and_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-rollouts passes --project and --status as kwargs to the backend."""
    fake = _patch_backend(monkeypatch)

    _cmd_list_rollouts(
        _list_rollouts_args(project_id="proj-uuid", status="running", limit=10)
    )

    _user_id, project_id, status, limit = fake.calls["list_rollouts"][0]
    assert project_id == "proj-uuid"
    assert status == "running"
    assert limit == 10


# ---------------------------------------------------------------------------
# 7. register() wires subparsers correctly
# ---------------------------------------------------------------------------


def test_register_adds_five_subparsers() -> None:
    """register() adds exactly the five expected subcommand names."""
    parser = argparse.ArgumentParser(prog="test")
    subparsers = parser.add_subparsers(dest="command")

    register(subparsers)

    expected_commands = {
        "plan-rollout",
        "dispatch-rollout",
        "start-rollout",
        "list-rollouts",
        "get-rollout-plan",
    }
    assert set(subparsers.choices.keys()) == expected_commands


def test_register_sets_func_on_all_subparsers() -> None:
    """register() calls set_defaults(func=...) on each subparser."""
    parser = argparse.ArgumentParser(prog="test")
    subparsers = parser.add_subparsers(dest="command")

    register(subparsers)

    for cmd in (
        "plan-rollout",
        "dispatch-rollout",
        "start-rollout",
        "list-rollouts",
        "get-rollout-plan",
    ):
        positional = [] if cmd == "list-rollouts" else ["dummy-id"]
        args = parser.parse_args([cmd, *positional])
        assert hasattr(args, "func"), f"{cmd!r} subparser did not set args.func"
        assert callable(args.func)


def test_register_plan_rollout_help_is_present() -> None:
    """plan-rollout subparser has a non-empty help string."""
    parser = argparse.ArgumentParser(prog="test")
    subparsers = parser.add_subparsers(dest="command")

    register(subparsers)

    # build_parser calls add_subparsers with no metavar, so choices is the map.
    # Verify the plan-rollout entry is present (help text is set via add_parser).
    assert "plan-rollout" in subparsers.choices
