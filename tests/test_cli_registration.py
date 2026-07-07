"""Tests for the per-resource CLI subcommand registration convention.

Proves the ``cli_commands`` registration machinery and the ``_shared`` helpers
WITHOUT introducing a real resource command module (those belong to items 2-7).
Fake command modules are injected via ``register_all(modules=[...])`` or by
monkeypatching ``agent_gtd.cli.register_all`` — no real files are created under
``src/agent_gtd/cli_commands/`` by these tests.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import types
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_gtd.cli import build_parser, main
from agent_gtd.cli_commands import _shared, register_all

# ---------------------------------------------------------------------------
# register_all — explicit modules injection
# ---------------------------------------------------------------------------


def _fresh_subparsers() -> argparse._SubParsersAction[Any]:
    """Return a subparsers action detached from any real command modules."""
    parser = argparse.ArgumentParser(prog="test")
    return parser.add_subparsers(dest="command")


def test_register_all_calls_module_register_once():
    """register_all(modules=[fake]) calls fake.register exactly once w/ subparsers."""
    subparsers = _fresh_subparsers()
    calls: list[Any] = []

    def _register(sp: Any) -> None:
        calls.append(sp)

    fake = types.SimpleNamespace(register=_register)

    register_all(subparsers, modules=[fake])

    assert calls == [subparsers]


def test_register_all_module_without_register_raises_attributeerror():
    """A fake module lacking a register attribute raises AttributeError."""
    subparsers = _fresh_subparsers()
    broken = types.SimpleNamespace()  # no .register

    with pytest.raises(AttributeError):
        register_all(subparsers, modules=[broken])


# ---------------------------------------------------------------------------
# register_all — default auto-discovery
# ---------------------------------------------------------------------------


def test_register_all_autodiscovery_does_not_raise_and_skips_shared():
    """Default auto-discovery does not raise and '_shared'/'shared' is not a command."""
    subparsers = _fresh_subparsers()

    register_all(subparsers)  # must not raise even with only _shared present

    assert "_shared" not in subparsers.choices
    assert "shared" not in subparsers.choices


def test_register_all_autodiscovery_imports_and_registers_command_modules(monkeypatch):
    """Auto-discovery skips '_'-prefixed modules, imports the rest, calls register().

    Exercises the import-and-register loop body without adding a real command
    module: pkgutil.iter_modules and importlib.import_module are stubbed so a
    fake non-underscore module is discovered, imported, and registered.
    """
    subparsers = _fresh_subparsers()
    register_calls: list[Any] = []
    fake_mod = types.SimpleNamespace(register=lambda sp: register_calls.append(sp))

    def _fake_iter_modules(path: Any) -> list[Any]:
        # One helper module (skipped) and one command module (registered).
        return [
            types.SimpleNamespace(name="_shared"),
            types.SimpleNamespace(name="widget"),
        ]

    imported: list[str] = []

    def _fake_import_module(name: str) -> Any:
        imported.append(name)
        return fake_mod

    monkeypatch.setattr(
        "agent_gtd.cli_commands.pkgutil.iter_modules", _fake_iter_modules
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.importlib.import_module", _fake_import_module
    )

    register_all(subparsers)

    # Only the non-underscore module was imported, and its register() ran once.
    assert imported == ["agent_gtd.cli_commands.widget"]
    assert register_calls == [subparsers]


def test_build_parser_does_not_expose_shared_as_subcommand():
    """The real build_parser() never registers _shared as a subcommand."""
    parser = build_parser()
    # Locate the subparsers action to read its choices.
    subparser_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert subparser_actions, "build_parser must define subparsers"
    choices = subparser_actions[0].choices
    assert "_shared" not in choices
    assert "shared" not in choices
    # The five existing commands remain registered.
    for cmd in (
        "run-status",
        "rollout-status",
        "promote-admin",
        "update-item",
        "add-item",
    ):
        assert cmd in choices


# ---------------------------------------------------------------------------
# End-to-end dispatch via the new args.func fall-through branch
# ---------------------------------------------------------------------------


def test_main_dispatches_registered_handler_via_func_branch(monkeypatch):
    """A command registered via set_defaults(func=...) is dispatched by main()."""
    invoked: list[argparse.Namespace] = []

    def _handler(args: argparse.Namespace) -> None:
        invoked.append(args)

    def _stub_register_all(subparsers: Any, modules: Any = None) -> None:
        p = subparsers.add_parser("fake-cmd", help="test-only fake command")
        p.set_defaults(func=_handler)

    # register_all is imported into cli.py's namespace, so patching the
    # agent_gtd.cli attribute is sufficient.
    monkeypatch.setattr("agent_gtd.cli.register_all", _stub_register_all)
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "fake-cmd"])

    main()

    assert len(invoked) == 1
    assert getattr(invoked[0], "func", None) is _handler


def test_main_no_subcommand_exits_nonzero_with_help(monkeypatch, capsys):
    """main() with no subcommand prints help to stderr and exits non-zero."""
    monkeypatch.setattr(sys, "argv", ["agent-gtd"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower() or "agent-gtd" in captured.err


def test_main_existing_command_does_not_hit_func_branch(monkeypatch, capsys):
    """The five existing commands never set args.func, so they skip the new branch."""
    expected = {"id": "run-1", "status": "running"}

    async def _fake_fetch(rid: str) -> dict[str, Any]:
        return expected

    monkeypatch.setattr("agent_gtd.cli._fetch_run_status", _fake_fetch)
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "run-status", "run-1"])

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "running"


# ---------------------------------------------------------------------------
# _shared.load_json_payload / emit_json / fail
# ---------------------------------------------------------------------------


def test_shared_load_json_payload_empty_when_no_source():
    """load_json_payload returns {} when neither file nor stdin is given."""
    assert _shared.load_json_payload(None, use_stdin=False) == {}


def test_shared_load_json_payload_from_file(tmp_path):
    """load_json_payload reads and returns a dict from a file."""
    f = tmp_path / "payload.json"
    f.write_text(json.dumps({"title": "Hi"}))
    assert _shared.load_json_payload(str(f), use_stdin=False) == {"title": "Hi"}


def test_shared_load_json_payload_non_dict_keeps_type_name(monkeypatch):
    """A non-dict payload raises ValueError whose message keeps the type name."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2, 3]"))
    with pytest.raises(ValueError, match="list"):
        _shared.load_json_payload(None, use_stdin=True)


def test_cli_alias_is_same_object_as_shared():
    """agent_gtd.cli._load_json_payload IS _shared.load_json_payload (single impl)."""
    from agent_gtd.cli import _load_json_payload

    assert _load_json_payload is _shared.load_json_payload


def test_shared_emit_json_trailing_newline_and_default_str(capsys):
    """emit_json writes obj + newline and serializes datetime via default=str."""
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    _shared.emit_json({"when": dt, "n": 1})

    out = capsys.readouterr().out
    assert out.endswith("\n")
    data = json.loads(out)
    assert data["n"] == 1
    assert data["when"] == str(dt)  # default=str stringified the datetime


def test_shared_fail_writes_stderr_and_exits_1(capsys):
    """fail('x') prints 'Error: x' to stderr and raises SystemExit with code 1."""
    with pytest.raises(SystemExit) as exc_info:
        _shared.fail("boom")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Error: boom"


# ---------------------------------------------------------------------------
# _shared.backend_session — local / http / missing-key branches
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Minimal backend recording close() and supporting login()."""

    def __init__(self, login_result: dict[str, Any] | None = None) -> None:
        self.closed = False
        self.login_calls: list[tuple[str, str]] = []
        self._login_result = login_result or {"user_id": "http-user"}

    async def login(self, api_key: str, client: str) -> dict[str, Any]:
        self.login_calls.append((api_key, client))
        return self._login_result

    async def close(self) -> None:
        self.closed = True


async def test_backend_session_local_mode_yields_local_user(monkeypatch):
    """Local mode (no AGENT_GTD_URL) yields (backend, LOCAL_USER_ID) and closes."""
    from agent_gtd.database import LOCAL_USER_ID

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    fake = _FakeBackend()
    monkeypatch.setattr(_shared, "create_backend", lambda: fake)

    init_calls: list[int] = []

    async def _fake_init_db() -> None:
        init_calls.append(1)

    monkeypatch.setattr("agent_gtd.database.init_db", _fake_init_db)

    async with _shared.backend_session() as (backend, user_id):
        assert backend is fake
        assert user_id == LOCAL_USER_ID

    assert init_calls == [1]
    assert fake.closed is True


async def test_backend_session_closes_even_when_body_raises(monkeypatch):
    """backend.close() is awaited even if the with-body raises."""
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    fake = _FakeBackend()
    monkeypatch.setattr(_shared, "create_backend", lambda: fake)

    async def _fake_init_db() -> None:
        return None

    monkeypatch.setattr("agent_gtd.database.init_db", _fake_init_db)

    with pytest.raises(RuntimeError, match="boom"):
        async with _shared.backend_session():
            raise RuntimeError("boom")

    assert fake.closed is True


async def test_backend_session_http_missing_key_raises(monkeypatch):
    """HTTP mode without AGENT_GTD_API_KEY raises the required-key RuntimeError."""
    monkeypatch.setenv("AGENT_GTD_URL", "https://example.test")
    monkeypatch.delenv("AGENT_GTD_API_KEY", raising=False)
    fake = _FakeBackend()
    monkeypatch.setattr(_shared, "create_backend", lambda: fake)

    with pytest.raises(
        RuntimeError, match="AGENT_GTD_API_KEY environment variable is required"
    ):
        async with _shared.backend_session():
            pass

    # Even on the auth failure, the backend is closed by the finally block.
    assert fake.closed is True


async def test_backend_session_http_logs_in_and_yields_user_id(monkeypatch):
    """HTTP mode with both env vars logs in and yields the returned user_id."""
    monkeypatch.setenv("AGENT_GTD_URL", "https://example.test")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "secret-key")
    fake = _FakeBackend(login_result={"user_id": "user-42"})
    monkeypatch.setattr(_shared, "create_backend", lambda: fake)

    async with _shared.backend_session() as (backend, user_id):
        assert backend is fake
        assert user_id == "user-42"

    assert fake.login_calls == [("secret-key", "cli")]
    assert fake.closed is True
