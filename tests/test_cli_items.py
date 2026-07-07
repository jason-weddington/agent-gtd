"""Tests for src/agent_gtd/cli_commands/items.py.

Covers all 8 item lifecycle and blocker subcommand handlers following
the ``tests/test_cli.py`` conventions: argparse.Namespace builders,
monkeypatched backend session, sync handler invocation, capsys JSON
assertions, and a single parametrized error-path test.

No database is required — all backend calls are intercepted via the
monkeypatched session helper.
"""

from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent_gtd.cli_commands.items import (
    _cmd_add_blocker,
    _cmd_complete_item,
    _cmd_delete_item,
    _cmd_get_item,
    _cmd_inbox_capture,
    _cmd_list_blockers,
    _cmd_list_items,
    _cmd_remove_blocker,
    register,
)
from agent_gtd.exceptions import NotFoundError

# ---------------------------------------------------------------------------
# Canned payloads
# ---------------------------------------------------------------------------

_CANNED_ITEM: dict[str, Any] = {
    "id": "item-uuid-1",
    "title": "Test Item",
    "status": "active",
    "priority": "normal",
    "version": 1,
}

_CANNED_LIST: dict[str, Any] = {
    "items": [_CANNED_ITEM],
    "inbox_pending_count": 3,
}

_CANNED_DELETE: dict[str, Any] = {
    "status": "deleted",
    "item_id": "item-uuid-1",
}

_CANNED_INBOX: dict[str, Any] = {
    "id": "item-uuid-2",
    "title": "Quick capture",
    "status": "inbox",
    "inbox_pending_count": 4,
}

_CANNED_BLOCKER: dict[str, Any] = {
    "id": "blocker-uuid-1",
    "title": "Blocking item",
    "status": "active",
    "project_id": "proj-uuid-1",
    "project_name": "Test Project",
}

_CANNED_BLOCKERS_LIST: list[dict[str, Any]] = [_CANNED_BLOCKER]

# ---------------------------------------------------------------------------
# Namespace builders
# ---------------------------------------------------------------------------


def _get_item_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the get-item subcommand."""
    return argparse.Namespace(item_id="item-uuid-1", **overrides)


def _list_items_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the list-items subcommand with default filters."""
    defaults: dict[str, Any] = {
        "status": None,
        "project_id": None,
        "priority": None,
        "assigned_to": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _complete_item_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the complete-item subcommand."""
    return argparse.Namespace(item_id="item-uuid-1", **overrides)


def _delete_item_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the delete-item subcommand."""
    return argparse.Namespace(item_id="item-uuid-1", **overrides)


def _inbox_capture_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the inbox-capture subcommand."""
    return argparse.Namespace(title="Quick capture", **overrides)


def _add_blocker_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the add-blocker subcommand."""
    return argparse.Namespace(
        item_id="item-uuid-1", blocker_item_id="blocker-uuid-1", **overrides
    )


def _remove_blocker_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the remove-blocker subcommand."""
    return argparse.Namespace(
        item_id="item-uuid-1", blocker_item_id="blocker-uuid-1", **overrides
    )


def _list_blockers_args(**overrides: Any) -> argparse.Namespace:
    """Return a Namespace for the list-blockers subcommand."""
    return argparse.Namespace(item_id="item-uuid-1", **overrides)


# ---------------------------------------------------------------------------
# Fake backend + session patcher
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Configurable fake backend for handler tests.

    Each method that returns data looks up ``self._results[<method_name>]``.
    Methods returning ``None`` (i.e. ``remove_blocker``) ignore ``_results``.
    """

    def __init__(self, **method_results: Any) -> None:
        self._results = method_results

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Return the canned get_item result."""
        return self._results["get_item"]  # type: ignore[no-any-return]

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any]:
        """Return the canned list_items result."""
        return self._results["list_items"]  # type: ignore[no-any-return]

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Return the canned complete_item result."""
        return self._results["complete_item"]  # type: ignore[no-any-return]

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Return the canned delete_item result."""
        return self._results["delete_item"]  # type: ignore[no-any-return]

    async def inbox_capture(
        self, user_id: str, title: str, *, created_by: str = "human"
    ) -> dict[str, Any]:
        """Return the canned inbox_capture result."""
        return self._results["inbox_capture"]  # type: ignore[no-any-return]

    async def add_blocker(
        self, user_id: str, item_id: str, blocker_item_id: str
    ) -> dict[str, Any]:
        """Return the canned add_blocker result."""
        return self._results["add_blocker"]  # type: ignore[no-any-return]

    async def remove_blocker(
        self, user_id: str, item_id: str, blocker_item_id: str
    ) -> None:
        """No-op fake: remove_blocker returns None."""
        return None

    async def list_blockers(self, user_id: str, item_id: str) -> list[dict[str, Any]]:
        """Return the canned list_blockers result."""
        return self._results["list_blockers"]  # type: ignore[no-any-return]

    async def close(self) -> None:
        """No-op close."""
        return None


def _patch_session(monkeypatch: pytest.MonkeyPatch, fake_backend: _FakeBackend) -> None:
    """Monkeypatch backend_session in the items module to yield *fake_backend*.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        fake_backend: The fake backend instance to yield from the session.
    """

    @asynccontextmanager  # type: ignore[misc]
    async def _fake_session():  # type: ignore[return]
        yield fake_backend, "test-user-id"

    monkeypatch.setattr("agent_gtd.cli_commands.items.backend_session", _fake_session)


# ---------------------------------------------------------------------------
# register() — subcommand wiring
# ---------------------------------------------------------------------------


def test_register_adds_eight_subcommands() -> None:
    """register() adds exactly the 8 expected subcommands to *subparsers*."""
    parser = argparse.ArgumentParser(prog="test")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)

    expected = {
        "get-item",
        "list-items",
        "complete-item",
        "delete-item",
        "inbox-capture",
        "add-blocker",
        "remove-blocker",
        "list-blockers",
    }
    assert set(subparsers.choices.keys()) == expected


# ---------------------------------------------------------------------------
# get-item
# ---------------------------------------------------------------------------


def test_cmd_get_item_prints_item_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_get_item prints the item dict as JSON to stdout."""
    fake = _FakeBackend(get_item=_CANNED_ITEM)
    _patch_session(monkeypatch, fake)

    _cmd_get_item(_get_item_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_ITEM


# ---------------------------------------------------------------------------
# list-items
# ---------------------------------------------------------------------------


def test_cmd_list_items_prints_list_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_list_items prints the items dict as JSON to stdout."""
    fake = _FakeBackend(list_items=_CANNED_LIST)
    _patch_session(monkeypatch, fake)

    _cmd_list_items(_list_items_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_LIST


def test_cmd_list_items_passes_filters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_list_items forwards all filter flags to backend.list_items."""
    received: dict[str, Any] = {}

    class _RecordingBackend(_FakeBackend):
        async def list_items(
            self,
            user_id: str,
            *,
            status: str | None = None,
            project_id: str | None = None,
            priority: str | None = None,
            assigned_to: str | None = None,
        ) -> dict[str, Any]:
            received.update(
                status=status,
                project_id=project_id,
                priority=priority,
                assigned_to=assigned_to,
            )
            return _CANNED_LIST

    _patch_session(monkeypatch, _RecordingBackend())

    _cmd_list_items(
        _list_items_args(
            status="active",
            project_id="proj-1",
            priority="high",
            assigned_to="alice",
        )
    )

    assert received["status"] == "active"
    assert received["project_id"] == "proj-1"
    assert received["priority"] == "high"
    assert received["assigned_to"] == "alice"


# ---------------------------------------------------------------------------
# complete-item
# ---------------------------------------------------------------------------


def test_cmd_complete_item_prints_item_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_complete_item prints the updated item dict as JSON to stdout."""
    fake = _FakeBackend(complete_item=_CANNED_ITEM)
    _patch_session(monkeypatch, fake)

    _cmd_complete_item(_complete_item_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_ITEM


# ---------------------------------------------------------------------------
# delete-item
# ---------------------------------------------------------------------------


def test_cmd_delete_item_prints_confirmation_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_delete_item prints the deletion confirmation dict as JSON to stdout."""
    fake = _FakeBackend(delete_item=_CANNED_DELETE)
    _patch_session(monkeypatch, fake)

    _cmd_delete_item(_delete_item_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_DELETE


# ---------------------------------------------------------------------------
# inbox-capture
# ---------------------------------------------------------------------------


def test_cmd_inbox_capture_prints_item_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_inbox_capture prints the captured item dict as JSON to stdout."""
    fake = _FakeBackend(inbox_capture=_CANNED_INBOX)
    _patch_session(monkeypatch, fake)

    _cmd_inbox_capture(_inbox_capture_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_INBOX


def test_cmd_inbox_capture_sends_created_by_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """inbox-capture passes created_by='cli' to the backend."""
    received: dict[str, str] = {}

    class _RecordingBackend(_FakeBackend):
        async def inbox_capture(
            self, user_id: str, title: str, *, created_by: str = "human"
        ) -> dict[str, Any]:
            received["created_by"] = created_by
            return _CANNED_INBOX

    _patch_session(monkeypatch, _RecordingBackend())

    _cmd_inbox_capture(_inbox_capture_args())

    assert received["created_by"] == "cli"


# ---------------------------------------------------------------------------
# add-blocker
# ---------------------------------------------------------------------------


def test_cmd_add_blocker_prints_blocker_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_add_blocker prints the blocker summary dict as JSON to stdout."""
    fake = _FakeBackend(add_blocker=_CANNED_BLOCKER)
    _patch_session(monkeypatch, fake)

    _cmd_add_blocker(_add_blocker_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_BLOCKER


# ---------------------------------------------------------------------------
# remove-blocker
# ---------------------------------------------------------------------------


def test_cmd_remove_blocker_prints_ok_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_remove_blocker prints {\"ok\": true} to stdout."""
    fake = _FakeBackend()  # remove_blocker returns None — no _results needed
    _patch_session(monkeypatch, fake)

    _cmd_remove_blocker(_remove_blocker_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"ok": True}


# ---------------------------------------------------------------------------
# list-blockers
# ---------------------------------------------------------------------------


def test_cmd_list_blockers_prints_blockers_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_cmd_list_blockers prints the blockers list as a JSON array to stdout."""
    fake = _FakeBackend(list_blockers=_CANNED_BLOCKERS_LIST)
    _patch_session(monkeypatch, fake)

    _cmd_list_blockers(_list_blockers_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _CANNED_BLOCKERS_LIST


# ---------------------------------------------------------------------------
# Error-path tests — parametrized across all 8 handlers
# ---------------------------------------------------------------------------

_ALL_HANDLERS: list[tuple[Any, Any, str]] = [
    (_cmd_get_item, _get_item_args, "get-item"),
    (_cmd_list_items, _list_items_args, "list-items"),
    (_cmd_complete_item, _complete_item_args, "complete-item"),
    (_cmd_delete_item, _delete_item_args, "delete-item"),
    (_cmd_inbox_capture, _inbox_capture_args, "inbox-capture"),
    (_cmd_add_blocker, _add_blocker_args, "add-blocker"),
    (_cmd_remove_blocker, _remove_blocker_args, "remove-blocker"),
    (_cmd_list_blockers, _list_blockers_args, "list-blockers"),
]


class _FailContext:
    """Async context manager that raises NotFoundError on __aenter__."""

    async def __aenter__(self) -> tuple[Any, str]:
        """Raise NotFoundError to simulate a backend failure."""
        raise NotFoundError("Item", "test-id")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """No-op exit."""
        return None


@pytest.mark.parametrize(
    "handler,args_builder,cmd_name",
    _ALL_HANDLERS,
    ids=[row[2] for row in _ALL_HANDLERS],
)
def test_handler_exits_1_on_backend_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    handler: Any,
    args_builder: Any,
    cmd_name: str,
) -> None:
    """All 8 handlers: backend error → SystemExit(1) + 'Error: ...' on stderr."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands.items.backend_session",
        lambda: _FailContext(),
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(args_builder())

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: ")
