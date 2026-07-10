"""Meta-test: every --from-json CLI subcommand rejects unknown payload keys.

Design
------
Discovery: introspects the live argparse parser (via ``build_parser()``) to find
every subcommand that registers a ``--from-json`` flag (i.e. has an action with
``dest == "from_json"``).  For each discovered command the test:

1. Feeds a JSON payload containing a single bogus key via ``--stdin``.
2. Asserts the command exits with code 1 (non-zero).
3. Asserts stderr contains the word "unknown" (the allow-set error phrase).
4. Asserts no backend write operation was invoked.

Guard semantics
---------------
A future ``--from-json`` subcommand added **without** allow-set validation will
automatically be included in the parametrized run and will fail the test,
surfacing the gap at CI time.  The companion ``test_from_json_commands_discovered``
assertion additionally catches the inverse case: a known command whose
``--from-json`` flag is accidentally removed.

Compliance status (as of this item)
-------------------------------------
* ``add-item``     — ALREADY COMPLIANT (``_ADD_ITEM_FIELDS`` guard in ``cli.py``)
* ``update-item``  — ALREADY COMPLIANT (``_UPDATE_ITEM_FIELDS`` guard in ``cli.py``)
* ``add-note``     — NEWLY FIXED (``_ADD_NOTE_FIELDS`` guard added in this item)
* ``update-note``  — NEWLY FIXED (``_UPDATE_NOTE_FIELDS`` guard added in this item)
* ``add-comment``  — NEWLY FIXED (``_ADD_COMMENT_FIELDS`` guard added in this item)
* ``update-comment`` — NEWLY FIXED (``_UPDATE_COMMENT_FIELDS`` guard added in this item)
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Any

import pytest

from agent_gtd.cli import build_parser, main

# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _subcommand_parsers() -> dict[str, argparse.ArgumentParser]:
    """Return ``{name: parser}`` for every registered CLI subcommand."""
    parser = build_parser()
    sub_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1, "expected exactly one subparsers action"
    return dict(sub_actions[0].choices)  # type: ignore[return-value]


def _from_json_subcommands() -> dict[str, argparse.ArgumentParser]:
    """Return parsers for subcommands that accept ``--from-json`` / ``--stdin``.

    Detection criterion: the subparser has at least one registered action whose
    ``dest == "from_json"``.  This matches the argparse pattern used by every
    from-json command in the codebase — both the flag ``--from-json FILE`` and
    the mutually-exclusive ``--stdin`` share the ``from_json`` dest on the
    former; the presence of the action is the reliable indicator.
    """
    return {
        name: sp
        for name, sp in _subcommand_parsers().items()
        if any(
            isinstance(a, argparse.Action) and a.dest == "from_json"
            for a in sp._actions
        )
    }


def _positional_count(subparser: argparse.ArgumentParser) -> int:
    """Return the number of required positional arguments for *subparser*.

    Positional actions have an empty ``option_strings`` list and are not
    ``_HelpAction`` or ``_SubParsersAction``.
    """
    return sum(
        1
        for a in subparser._actions
        if (
            not a.option_strings
            and a.dest != argparse.SUPPRESS
            and not isinstance(a, argparse._SubParsersAction | argparse._HelpAction)
        )
    )


# ---------------------------------------------------------------------------
# Module-level discovery (static — evaluated at import time so parametrize
# can reference it).  Any from-json command present at import time is tested.
# ---------------------------------------------------------------------------

_FROM_JSON_CMDS: dict[str, argparse.ArgumentParser] = _from_json_subcommands()

# ---------------------------------------------------------------------------
# Guard: the expected set of from-json commands is fully discovered
# ---------------------------------------------------------------------------

#: The canonical set of CLI subcommands that are expected to accept --from-json.
#: Update this set whenever a new from-json command is intentionally added or
#: an existing one's --from-json flag is intentionally removed.
_KNOWN_FROM_JSON_CMDS: frozenset[str] = frozenset(
    {
        "add-item",
        "update-item",
        "add-note",
        "update-note",
        "add-comment",
        "update-comment",
    }
)


def test_from_json_commands_discovered() -> None:
    """All expected --from-json commands are present in the live parser registry.

    This assertion catches two failure modes:
    * A known command had its ``--from-json`` flag accidentally removed.
    * A new command was added to ``_KNOWN_FROM_JSON_CMDS`` but not wired to the
      parser (or vice-versa — see the parametrized test for the other direction).
    """
    found = set(_FROM_JSON_CMDS.keys())
    missing = _KNOWN_FROM_JSON_CMDS - found
    assert not missing, (
        f"Expected these commands to expose --from-json but they were NOT found "
        f"in the live parser: {sorted(missing)}.  Either the --from-json flag "
        f"was accidentally removed or _KNOWN_FROM_JSON_CMDS is stale."
    )


# ---------------------------------------------------------------------------
# Parametrized rejection test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd_name", sorted(_FROM_JSON_CMDS.keys()))
def test_from_json_rejects_unknown_payload_key(
    cmd_name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each --from-json subcommand exits 1 with 'unknown' in stderr for a bogus key.

    The test feeds ``{"bogus_key_that_must_be_rejected": "totally_invalid"}``
    via ``--stdin`` and asserts:

    * ``SystemExit(1)`` — the command exits non-zero.
    * ``"unknown"`` appears in stderr — the allow-set error is surfaced.
    * No backend write method is invoked — validation fires before any write.

    A missing allow-set guard causes this test to fail with a message naming the
    command that needs the fix.

    Args:
        cmd_name: CLI subcommand name (parametrized from ``_FROM_JSON_CMDS``).
        monkeypatch: pytest monkeypatch fixture.
        capsys: pytest capsys fixture for capturing stdout/stderr.
    """
    subparser = _FROM_JSON_CMDS[cmd_name]
    n_positionals = _positional_count(subparser)

    # Build argv: supply "fake-uuid" for each required positional, then --stdin.
    positional_values = ["fake-uuid"] * n_positionals
    argv = ["agent-gtd", cmd_name, *positional_values, "--stdin"]

    bogus_payload = json.dumps({"bogus_key_that_must_be_rejected": "totally_invalid"})

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "stdin", io.StringIO(bogus_payload))

    # Backend spy: write methods raise AssertionError if ever called.
    # Because allow-set validation fires before any backend call, none of these
    # should ever be reached.
    write_calls: list[str] = []

    class _SpyBackend:
        async def create_note(self, *a: Any, **kw: Any) -> dict[str, Any]:
            write_calls.append("create_note")
            raise AssertionError(
                "create_note must not be called before validation passes"
            )

        async def update_note(self, *a: Any, **kw: Any) -> dict[str, Any]:
            write_calls.append("update_note")
            raise AssertionError(
                "update_note must not be called before validation passes"
            )

        async def create_comment(self, *a: Any, **kw: Any) -> dict[str, Any]:
            write_calls.append("create_comment")
            raise AssertionError(
                "create_comment must not be called before validation passes"
            )

        async def update_comment(self, *a: Any, **kw: Any) -> dict[str, Any]:
            write_calls.append("update_comment")
            raise AssertionError(
                "update_comment must not be called before validation passes"
            )

        async def update_item(self, *a: Any, **kw: Any) -> dict[str, Any]:
            write_calls.append("update_item")
            raise AssertionError(
                "update_item must not be called before validation passes"
            )

        async def get_item(self, *a: Any, **kw: Any) -> dict[str, Any]:
            # May be called for version fetch in update-item; safe to return a stub.
            return {"id": "fake-uuid", "version": 1}

        async def login(self, *a: Any, **kw: Any) -> dict[str, Any]:
            return {"user_id": "fake-user"}

        async def close(self) -> None:
            pass

    # Patch both create_backend call sites used by from-json commands:
    #  - cli.py uses agent_gtd.cli.create_backend (add-item, update-item)
    #  - _shared.py uses agent_gtd.cli_commands._shared.create_backend (notes/comments)
    monkeypatch.setattr("agent_gtd.cli.create_backend", lambda: _SpyBackend())
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend", lambda: _SpyBackend()
    )
    # Ensure local mode so backend_session does not require AGENT_GTD_API_KEY.
    monkeypatch.delenv("AGENT_GTD_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1, (
        f"command '{cmd_name}': expected exit code 1 for bogus payload key, "
        f"got exit code {exc_info.value.code!r}.  "
        f"This likely means the command lacks an allow-set validation guard."
    )

    captured = capsys.readouterr()
    assert "unknown" in captured.err.lower(), (
        f"command '{cmd_name}': expected 'unknown' in stderr for bogus payload key, "
        f"got: {captured.err!r}.  "
        f"The command may be silently ignoring unknown payload keys."
    )

    assert not write_calls, (
        f"command '{cmd_name}': backend write method(s) called unexpectedly: "
        f"{write_calls}.  Allow-set validation must fire BEFORE any backend call."
    )
