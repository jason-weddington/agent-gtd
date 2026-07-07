"""Tests for the rollout control CLI subcommand module.

Covers:
1. PARSING  — local parser built from register(); positionals, required flags,
   choices validation, SystemExit on missing-required and bad-choices.
2. HANDLER SUCCESS — _FakeBackend + monkeypatch on _shared.create_backend;
   correct backend method called with correct args; JSON output on stdout.
3. OMITTED-OPTIONAL DEFAULTS — omitting optional flags passes the right defaults
   to the backend (merge_actor='', decision_rule='', comment=None, etc.).
4. ERROR PATH — backend raises → 'Error:' on stderr, SystemExit(1).
"""

from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

import pytest

import agent_gtd.cli_commands.rollout_control as rollout_control

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction[Any]]:
    """Return a fresh (parser, subparsers) pair with rollout_control registered."""
    p = argparse.ArgumentParser(prog="test")
    sub = p.add_subparsers(dest="command")
    rollout_control.register(sub)
    return p, sub


def _ruid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fake backend
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Records calls and returns canned dicts for each rollout method."""

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[dict[str, Any]] = []
        # Canned return values keyed by method name
        self._responses: dict[str, dict[str, Any]] = {
            "advance_rollout": {
                "next_ready": None,
                "in_progress": [],
                "blocked": [],
                "graph_complete": False,
            },
            "complete_item_in_rollout": {
                "rollout_item": {"id": "ri-1"},
                "newly_ready": [],
            },
            "halt_rollout": {"id": "r-1", "status": "halted"},
            "cancel_rollout": {"id": "r-1", "status": "cancelled"},
            "replan_rollout": {
                "old_version": 1,
                "new_version": 2,
                "new_plan": [],
            },
            "update_rollout_state": {
                "rollout_id": "r-1",
                "ts": "2026-01-01T00:00:00Z",
                "phase": "dispatching",
                "current_item_id": None,
                "current_step": None,
            },
        }

    async def login(self, api_key: str, client: str) -> dict[str, str]:
        return {"user_id": "fake-user"}

    async def advance_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        self.calls.append(
            {"method": "advance_rollout", "user_id": user_id, "rollout_id": rollout_id}
        )
        return self._responses["advance_rollout"]

    async def complete_item_in_rollout(
        self,
        user_id: str,
        rollout_id: str,
        item_id: str,
        outcome: str,
        *,
        merge_actor: str = "",
        decision_rule: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "complete_item_in_rollout",
                "user_id": user_id,
                "rollout_id": rollout_id,
                "item_id": item_id,
                "outcome": outcome,
                "merge_actor": merge_actor,
                "decision_rule": decision_rule,
            }
        )
        return self._responses["complete_item_in_rollout"]

    async def halt_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
        *,
        comment: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "halt_rollout",
                "user_id": user_id,
                "rollout_id": rollout_id,
                "reason": reason,
                "comment": comment,
                "item_id": item_id,
            }
        )
        return self._responses["halt_rollout"]

    async def cancel_rollout(
        self, user_id: str, rollout_id: str, reason: str
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "cancel_rollout",
                "user_id": user_id,
                "rollout_id": rollout_id,
                "reason": reason,
            }
        )
        return self._responses["cancel_rollout"]

    async def replan_rollout(
        self,
        user_id: str,
        rollout_id: str,
        *,
        from_item: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "replan_rollout",
                "user_id": user_id,
                "rollout_id": rollout_id,
                "from_item": from_item,
            }
        )
        return self._responses["replan_rollout"]

    async def update_rollout_state(
        self,
        user_id: str,
        rollout_id: str,
        phase: str,
        current_item_id: str | None = None,
        current_step: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "update_rollout_state",
                "user_id": user_id,
                "rollout_id": rollout_id,
                "phase": phase,
                "current_item_id": current_item_id,
                "current_step": current_step,
            }
        )
        resp = dict(self._responses["update_rollout_state"])
        resp["phase"] = phase
        resp["current_item_id"] = current_item_id
        resp["current_step"] = current_step
        return resp

    async def close(self) -> None:
        self.closed = True


class _ErrorBackend:
    """Backend whose rollout methods all raise RuntimeError."""

    async def login(self, api_key: str, client: str) -> dict[str, str]:
        return {"user_id": "fake-user"}

    async def advance_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def complete_item_in_rollout(
        self, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def halt_rollout(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def cancel_rollout(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def replan_rollout(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def update_rollout_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 1. PARSING TESTS
# ---------------------------------------------------------------------------


class TestAdvanceRolloutParsing:
    def test_positional_required(self) -> None:
        p, _ = _make_parser()
        rid = _ruid()
        args = p.parse_args(["advance-rollout", rid])
        assert args.rollout_id == rid

    def test_missing_positional_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["advance-rollout"])

    def test_handler_wired(self) -> None:
        p, _ = _make_parser()
        args = p.parse_args(["advance-rollout", _ruid()])
        assert args.func is rollout_control._cmd_advance_rollout


class TestCompleteItemInRolloutParsing:
    def test_positionals_and_required_flag(self) -> None:
        p, _ = _make_parser()
        rid, iid = _ruid(), _ruid()
        args = p.parse_args(
            ["complete-item-in-rollout", rid, iid, "--outcome", "completed"]
        )
        assert args.rollout_id == rid
        assert args.item_id == iid
        assert args.outcome == "completed"

    def test_missing_outcome_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["complete-item-in-rollout", _ruid(), _ruid()])

    def test_bad_outcome_choice_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(
                ["complete-item-in-rollout", _ruid(), _ruid(), "--outcome", "bogus"]
            )

    def test_all_outcome_choices_accepted(self) -> None:
        p, _ = _make_parser()
        for choice in ("completed", "halted", "skipped"):
            args = p.parse_args(
                ["complete-item-in-rollout", _ruid(), _ruid(), "--outcome", choice]
            )
            assert args.outcome == choice

    def test_optional_flags_default_to_none(self) -> None:
        p, _ = _make_parser()
        args = p.parse_args(
            ["complete-item-in-rollout", _ruid(), _ruid(), "--outcome", "completed"]
        )
        assert args.merge_actor is None
        assert args.decision_rule is None

    def test_merge_actor_choices(self) -> None:
        p, _ = _make_parser()
        for actor in (
            "human",
            "manager-allowlist",
            "manager-autonomous",
            "manager+human-fixup",
        ):
            args = p.parse_args(
                [
                    "complete-item-in-rollout",
                    _ruid(),
                    _ruid(),
                    "--outcome",
                    "completed",
                    "--merge-actor",
                    actor,
                ]
            )
            assert args.merge_actor == actor

    def test_bad_merge_actor_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(
                [
                    "complete-item-in-rollout",
                    _ruid(),
                    _ruid(),
                    "--outcome",
                    "completed",
                    "--merge-actor",
                    "bogus",
                ]
            )

    def test_decision_rule_choice(self) -> None:
        p, _ = _make_parser()
        args = p.parse_args(
            [
                "complete-item-in-rollout",
                _ruid(),
                _ruid(),
                "--outcome",
                "completed",
                "--decision-rule",
                "agent-judgment",
            ]
        )
        assert args.decision_rule == "agent-judgment"

    def test_bad_decision_rule_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(
                [
                    "complete-item-in-rollout",
                    _ruid(),
                    _ruid(),
                    "--outcome",
                    "completed",
                    "--decision-rule",
                    "bogus",
                ]
            )


class TestHaltRolloutParsing:
    def test_required_flags(self) -> None:
        p, _ = _make_parser()
        rid = _ruid()
        args = p.parse_args(["halt-rollout", rid, "--reason", "oops"])
        assert args.rollout_id == rid
        assert args.reason == "oops"
        assert args.comment is None
        assert args.item_id is None

    def test_missing_reason_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["halt-rollout", _ruid()])

    def test_optional_flags(self) -> None:
        p, _ = _make_parser()
        iid = _ruid()
        args = p.parse_args(
            [
                "halt-rollout",
                _ruid(),
                "--reason",
                "stop",
                "--comment",
                "needs review",
                "--item-id",
                iid,
            ]
        )
        assert args.comment == "needs review"
        assert args.item_id == iid


class TestCancelRolloutParsing:
    def test_required_flags(self) -> None:
        p, _ = _make_parser()
        rid = _ruid()
        args = p.parse_args(["cancel-rollout", rid, "--reason", "abort"])
        assert args.rollout_id == rid
        assert args.reason == "abort"

    def test_missing_reason_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["cancel-rollout", _ruid()])


class TestReplanRolloutParsing:
    def test_positional_only(self) -> None:
        p, _ = _make_parser()
        rid = _ruid()
        args = p.parse_args(["replan-rollout", rid])
        assert args.rollout_id == rid
        assert args.from_item is None

    def test_from_item_optional(self) -> None:
        p, _ = _make_parser()
        iid = _ruid()
        args = p.parse_args(["replan-rollout", _ruid(), "--from-item", iid])
        assert args.from_item == iid

    def test_missing_positional_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["replan-rollout"])


class TestUpdateRolloutStateParsing:
    def test_required_phase(self) -> None:
        p, _ = _make_parser()
        rid = _ruid()
        args = p.parse_args(["update-rollout-state", rid, "--phase", "dispatching"])
        assert args.rollout_id == rid
        assert args.phase == "dispatching"
        assert args.current_item_id is None
        assert args.current_step is None

    def test_missing_phase_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["update-rollout-state", _ruid()])

    def test_bad_phase_raises_systemexit(self) -> None:
        p, _ = _make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["update-rollout-state", _ruid(), "--phase", "bogus"])

    def test_all_phase_choices_accepted(self) -> None:
        p, _ = _make_parser()
        for phase in (
            "warm_up",
            "dispatching",
            "polling",
            "reviewing",
            "merging",
            "reconciling_ac",
            "halted",
        ):
            args = p.parse_args(["update-rollout-state", _ruid(), "--phase", phase])
            assert args.phase == phase

    def test_optional_flags(self) -> None:
        p, _ = _make_parser()
        iid = _ruid()
        args = p.parse_args(
            [
                "update-rollout-state",
                _ruid(),
                "--phase",
                "polling",
                "--current-item-id",
                iid,
                "--current-step",
                "running tests",
            ]
        )
        assert args.current_item_id == iid
        assert args.current_step == "running tests"


# ---------------------------------------------------------------------------
# 2. HANDLER SUCCESS TESTS
# ---------------------------------------------------------------------------


def test_advance_rollout_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """advance-rollout calls backend.advance_rollout and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid = _ruid()
    p, _ = _make_parser()
    args = p.parse_args(["advance-rollout", rid])
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert "graph_complete" in data

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "advance_rollout"
    assert call["rollout_id"] == rid
    assert fake.closed is True


def test_complete_item_in_rollout_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """complete-item-in-rollout calls backend with correct args and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid, iid = _ruid(), _ruid()
    p, _ = _make_parser()
    args = p.parse_args(
        [
            "complete-item-in-rollout",
            rid,
            iid,
            "--outcome",
            "completed",
            "--merge-actor",
            "human",
            "--decision-rule",
            "agent-judgment",
        ]
    )
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert "rollout_item" in data

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "complete_item_in_rollout"
    assert call["rollout_id"] == rid
    assert call["item_id"] == iid
    assert call["outcome"] == "completed"
    assert call["merge_actor"] == "human"
    assert call["decision_rule"] == "agent-judgment"
    assert fake.closed is True


def test_halt_rollout_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """halt-rollout calls backend with correct args and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid = _ruid()
    p, _ = _make_parser()
    args = p.parse_args(
        ["halt-rollout", rid, "--reason", "manual stop", "--comment", "see notes"]
    )
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "halted"

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "halt_rollout"
    assert call["rollout_id"] == rid
    assert call["reason"] == "manual stop"
    assert call["comment"] == "see notes"
    assert fake.closed is True


def test_cancel_rollout_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """cancel-rollout calls backend with correct args and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid = _ruid()
    p, _ = _make_parser()
    args = p.parse_args(["cancel-rollout", rid, "--reason", "abort plan"])
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["status"] == "cancelled"

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "cancel_rollout"
    assert call["rollout_id"] == rid
    assert call["reason"] == "abort plan"
    assert fake.closed is True


def test_replan_rollout_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """replan-rollout calls backend with correct args and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid, iid = _ruid(), _ruid()
    p, _ = _make_parser()
    args = p.parse_args(["replan-rollout", rid, "--from-item", iid])
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert "new_plan" in data

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "replan_rollout"
    assert call["rollout_id"] == rid
    assert call["from_item"] == iid
    assert fake.closed is True


def test_update_rollout_state_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """update-rollout-state calls backend with correct args and prints JSON."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    rid, iid = _ruid(), _ruid()
    p, _ = _make_parser()
    args = p.parse_args(
        [
            "update-rollout-state",
            rid,
            "--phase",
            "reviewing",
            "--current-item-id",
            iid,
            "--current-step",
            "running lint",
        ]
    )
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["phase"] == "reviewing"

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "update_rollout_state"
    assert call["rollout_id"] == rid
    assert call["phase"] == "reviewing"
    assert call["current_item_id"] == iid
    assert call["current_step"] == "running lint"
    assert fake.closed is True


# ---------------------------------------------------------------------------
# 3. OMITTED-OPTIONAL DEFAULTS
# ---------------------------------------------------------------------------


def test_complete_item_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --merge-actor and --decision-rule passes '' to the backend."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(
        ["complete-item-in-rollout", _ruid(), _ruid(), "--outcome", "skipped"]
    )
    args.func(args)

    call = fake.calls[0]
    assert call["merge_actor"] == ""
    assert call["decision_rule"] == ""


def test_halt_rollout_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --comment and --item-id passes None to the backend."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["halt-rollout", _ruid(), "--reason", "stop"])
    args.func(args)

    call = fake.calls[0]
    assert call["comment"] is None
    assert call["item_id"] is None


def test_replan_rollout_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --from-item passes from_item=None to the backend."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["replan-rollout", _ruid()])
    args.func(args)

    call = fake.calls[0]
    assert call["from_item"] is None


def test_update_rollout_state_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --current-item-id and --current-step passes None to the backend."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["update-rollout-state", _ruid(), "--phase", "warm_up"])
    args.func(args)

    call = fake.calls[0]
    assert call["current_item_id"] is None
    assert call["current_step"] is None


# ---------------------------------------------------------------------------
# 4. ERROR PATH
# ---------------------------------------------------------------------------


def test_advance_rollout_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["advance-rollout", _ruid()])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


def test_complete_item_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(
        ["complete-item-in-rollout", _ruid(), _ruid(), "--outcome", "completed"]
    )

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_halt_rollout_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["halt-rollout", _ruid(), "--reason", "stop"])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_cancel_rollout_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["cancel-rollout", _ruid(), "--reason", "abort"])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_replan_rollout_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["replan-rollout", _ruid()])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_update_rollout_state_error_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend raises → 'Error:' on stderr + SystemExit(1)."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: _ErrorBackend(),
    )
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["update-rollout-state", _ruid(), "--phase", "halted"])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# 5. HTTP MODE TESTS (covers the AGENT_GTD_URL branch in backend_session)
# ---------------------------------------------------------------------------


def test_advance_rollout_http_mode_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """HTTP mode: AGENT_GTD_URL + AGENT_GTD_API_KEY set; login() resolves user_id."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.setenv("AGENT_GTD_URL", "http://example.test")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "test-api-key")

    rid = _ruid()
    p, _ = _make_parser()
    args = p.parse_args(["advance-rollout", rid])
    args.func(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert "graph_complete" in data

    # login() was called, which sets user_id to "fake-user"
    call = fake.calls[0]
    assert call["user_id"] == "fake-user"
    assert call["rollout_id"] == rid


def test_advance_rollout_http_mode_missing_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """HTTP mode: missing AGENT_GTD_API_KEY → RuntimeError → Error: stderr + exit 1."""
    fake = _FakeBackend()
    monkeypatch.setattr("agent_gtd.cli_commands._shared.create_backend", lambda: fake)
    monkeypatch.setenv("AGENT_GTD_URL", "http://example.test")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)

    p, _ = _make_parser()
    args = p.parse_args(["advance-rollout", _ruid()])

    with pytest.raises(SystemExit) as exc_info:
        args.func(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "AGENT_GTD_API_KEY" in captured.err
