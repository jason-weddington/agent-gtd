"""CLI subcommand module: rollout control commands.

Exposes a :func:`register` function that adds six subparsers for the
``agent-gtd`` CLI:

- ``advance-rollout``
- ``complete-item-in-rollout``
- ``halt-rollout``
- ``cancel-rollout``
- ``replan-rollout``
- ``update-rollout-state``

Each handler follows the same shape as the existing handlers in
:mod:`agent_gtd.cli`: a synchronous function that calls
:func:`asyncio.run` on a module-private async implementation, wrapped
in a broad ``except Exception`` catch that prints ``Error: <msg>`` to
stderr and exits with code 1.

The async implementations use :func:`agent_gtd.mcp_backend.create_backend`
(bound in this module's namespace so tests can monkeypatch it) and
replicate the local-vs-HTTP auth resolution from
:func:`agent_gtd.cli._fetch_rollout_status`.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import emit_json
from agent_gtd.mcp_backend import create_backend

if TYPE_CHECKING:
    import argparse

__all__ = ["register"]


# ---------------------------------------------------------------------------
# Shared async auth helper (mirrors cli._fetch_rollout_status lines 330-345)
# ---------------------------------------------------------------------------


async def _get_backend_and_user() -> tuple[Any, str]:
    """Return an authenticated ``(backend, user_id)`` pair.

    Auth follows the same mechanism as :func:`agent_gtd.cli._fetch_rollout_status`:

    - No ``AGENT_GTD_URL`` → LocalBackend (no auth; ``await init_db()`` then
      ``user_id = LOCAL_USER_ID``).
    - ``AGENT_GTD_URL`` set → HttpBackend; require ``AGENT_GTD_API_KEY``
      (raises ``RuntimeError`` when absent), then resolve user id via
      ``backend.login(api_key, "cli")``.

    Returns:
        A ``(backend, user_id)`` tuple. The caller is responsible for
        calling ``await backend.close()`` in a ``finally`` block.

    Raises:
        RuntimeError: If ``AGENT_GTD_API_KEY`` is required but not set.
    """
    backend = create_backend()
    if not os.environ.get("AGENT_GTD_URL", ""):
        from agent_gtd.database import LOCAL_USER_ID, init_db

        await init_db()
        user_id: str = LOCAL_USER_ID
    else:
        api_key = os.environ.get("AGENT_GTD_API_KEY", "")
        if not api_key:
            raise RuntimeError("AGENT_GTD_API_KEY environment variable is required")
        session = await backend.login(api_key, "cli")
        user_id = session["user_id"]
    return backend, user_id


# ---------------------------------------------------------------------------
# advance-rollout
# ---------------------------------------------------------------------------


async def _async_advance_rollout(rollout_id: str) -> None:
    """Fetch the next ready item in a rollout."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.advance_rollout(user_id, rollout_id)
        emit_json(result)
    finally:
        await backend.close()


def _cmd_advance_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for advance-rollout."""
    try:
        asyncio.run(_async_advance_rollout(args.rollout_id))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# complete-item-in-rollout
# ---------------------------------------------------------------------------


async def _async_complete_item_in_rollout(
    rollout_id: str,
    item_id: str,
    outcome: str,
    merge_actor: str,
    decision_rule: str,
) -> None:
    """Mark an item in a rollout as completed, halted, or skipped."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.complete_item_in_rollout(
            user_id,
            rollout_id,
            item_id,
            outcome,
            merge_actor=merge_actor,
            decision_rule=decision_rule,
        )
        emit_json(result)
    finally:
        await backend.close()


def _cmd_complete_item_in_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for complete-item-in-rollout."""
    merge_actor: str = args.merge_actor if args.merge_actor is not None else ""
    decision_rule: str = args.decision_rule if args.decision_rule is not None else ""
    try:
        asyncio.run(
            _async_complete_item_in_rollout(
                args.rollout_id,
                args.item_id,
                args.outcome,
                merge_actor,
                decision_rule,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# halt-rollout
# ---------------------------------------------------------------------------


async def _async_halt_rollout(
    rollout_id: str,
    reason: str,
    comment: str | None,
    item_id: str | None,
) -> None:
    """Halt a running rollout."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.halt_rollout(
            user_id,
            rollout_id,
            reason,
            comment=comment,
            item_id=item_id,
        )
        emit_json(result)
    finally:
        await backend.close()


def _cmd_halt_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for halt-rollout."""
    try:
        asyncio.run(
            _async_halt_rollout(
                args.rollout_id,
                args.reason,
                args.comment,
                args.item_id,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# cancel-rollout
# ---------------------------------------------------------------------------


async def _async_cancel_rollout(rollout_id: str, reason: str) -> None:
    """Cancel a rollout."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.cancel_rollout(
            user_id, rollout_id, reason
        )
        emit_json(result)
    finally:
        await backend.close()


def _cmd_cancel_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for cancel-rollout."""
    try:
        asyncio.run(_async_cancel_rollout(args.rollout_id, args.reason))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# replan-rollout
# ---------------------------------------------------------------------------


async def _async_replan_rollout(
    rollout_id: str,
    from_item: str | None,
) -> None:
    """Replan a rollout, optionally from a specific item."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.replan_rollout(
            user_id,
            rollout_id,
            from_item=from_item,
        )
        emit_json(result)
    finally:
        await backend.close()


def _cmd_replan_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for replan-rollout."""
    try:
        asyncio.run(_async_replan_rollout(args.rollout_id, args.from_item))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# update-rollout-state
# ---------------------------------------------------------------------------


async def _async_update_rollout_state(
    rollout_id: str,
    phase: str,
    current_item_id: str | None,
    current_step: str | None,
) -> None:
    """Update the internal state of a rollout."""
    backend, user_id = await _get_backend_and_user()
    try:
        result: dict[str, Any] = await backend.update_rollout_state(
            user_id,
            rollout_id,
            phase=phase,
            current_item_id=current_item_id,
            current_step=current_step,
        )
        emit_json(result)
    finally:
        await backend.close()


def _cmd_update_rollout_state(args: argparse.Namespace) -> None:
    """Synchronous handler for update-rollout-state."""
    try:
        asyncio.run(
            _async_update_rollout_state(
                args.rollout_id,
                args.phase,
                args.current_item_id,
                args.current_step,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register the six rollout control subcommands on *subparsers*.

    Adds: advance-rollout, complete-item-in-rollout, halt-rollout,
    cancel-rollout, replan-rollout, update-rollout-state.

    Args:
        subparsers: The subparsers action from the top-level argument parser.
    """
    # -- advance-rollout -------------------------------------------------------
    p_advance = subparsers.add_parser(
        "advance-rollout",
        help="Advance the rollout to the next ready item.",
    )
    p_advance.add_argument("rollout_id", help="ID of the rollout to advance.")
    p_advance.set_defaults(func=_cmd_advance_rollout)

    # -- complete-item-in-rollout ----------------------------------------------
    p_complete = subparsers.add_parser(
        "complete-item-in-rollout",
        help="Mark an item in a rollout as completed, halted, or skipped.",
    )
    p_complete.add_argument("rollout_id", help="ID of the rollout.")
    p_complete.add_argument("item_id", help="ID of the item to complete.")
    p_complete.add_argument(
        "--outcome",
        required=True,
        choices=["completed", "halted", "skipped"],
        help="Outcome for the item.",
    )
    p_complete.add_argument(
        "--merge-actor",
        dest="merge_actor",
        choices=[
            "human",
            "manager-allowlist",
            "manager-autonomous",
            "manager+human-fixup",
        ],
        default=None,
        help="Who performed the merge (omit to use backend default).",
    )
    p_complete.add_argument(
        "--decision-rule",
        dest="decision_rule",
        choices=["agent-judgment"],
        default=None,
        help="Decision rule applied (omit to use backend default).",
    )
    p_complete.set_defaults(func=_cmd_complete_item_in_rollout)

    # -- halt-rollout ----------------------------------------------------------
    p_halt = subparsers.add_parser(
        "halt-rollout",
        help="Halt a running rollout.",
    )
    p_halt.add_argument("rollout_id", help="ID of the rollout to halt.")
    p_halt.add_argument("--reason", required=True, help="Reason for halting.")
    p_halt.add_argument("--comment", default=None, help="Optional comment.")
    p_halt.add_argument(
        "--item-id",
        dest="item_id",
        default=None,
        help="Optional item ID associated with the halt.",
    )
    p_halt.set_defaults(func=_cmd_halt_rollout)

    # -- cancel-rollout --------------------------------------------------------
    p_cancel = subparsers.add_parser(
        "cancel-rollout",
        help="Cancel a rollout.",
    )
    p_cancel.add_argument("rollout_id", help="ID of the rollout to cancel.")
    p_cancel.add_argument("--reason", required=True, help="Reason for cancellation.")
    p_cancel.set_defaults(func=_cmd_cancel_rollout)

    # -- replan-rollout --------------------------------------------------------
    p_replan = subparsers.add_parser(
        "replan-rollout",
        help="Replan a rollout, optionally starting from a specific item.",
    )
    p_replan.add_argument("rollout_id", help="ID of the rollout to replan.")
    p_replan.add_argument(
        "--from-item",
        dest="from_item",
        default=None,
        help="Item ID to start replanning from (omit to replan from the start).",
    )
    p_replan.set_defaults(func=_cmd_replan_rollout)

    # -- update-rollout-state --------------------------------------------------
    p_update = subparsers.add_parser(
        "update-rollout-state",
        help="Update the internal state of a rollout.",
    )
    p_update.add_argument("rollout_id", help="ID of the rollout.")
    p_update.add_argument(
        "--phase",
        required=True,
        choices=[
            "warm_up",
            "dispatching",
            "polling",
            "reviewing",
            "merging",
            "reconciling_ac",
            "halted",
        ],
        help="New phase for the rollout.",
    )
    p_update.add_argument(
        "--current-item-id",
        dest="current_item_id",
        default=None,
        help="Current item being processed (optional).",
    )
    p_update.add_argument(
        "--current-step",
        dest="current_step",
        default=None,
        help="Current step description (optional).",
    )
    p_update.set_defaults(func=_cmd_update_rollout_state)
