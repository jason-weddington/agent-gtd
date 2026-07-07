"""CLI subcommand module: rollout control commands.

Exposes a :func:`register` function that adds six subparsers for the
``agent-gtd`` CLI:

- ``advance-rollout``
- ``complete-item-in-rollout``
- ``halt-rollout``
- ``cancel-rollout``
- ``replan-rollout``
- ``update-rollout-state``

Each handler follows the same shape as the sibling module
:mod:`agent_gtd.cli_commands.rollout_planning`: a synchronous function that
defines an inline ``async def _run()`` coroutine and runs it with
:func:`asyncio.run`.  Backend acquisition is delegated to
:func:`~agent_gtd.cli_commands._shared.backend_session`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal, cast

from agent_gtd.cli_commands._shared import backend_session, emit_json, fail

if TYPE_CHECKING:
    import argparse

__all__ = ["register"]


# ---------------------------------------------------------------------------
# advance-rollout
# ---------------------------------------------------------------------------


def _cmd_advance_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for advance-rollout."""
    rollout_id: str = args.rollout_id

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.advance_rollout(user_id, rollout_id)

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


# ---------------------------------------------------------------------------
# complete-item-in-rollout
# ---------------------------------------------------------------------------


def _cmd_complete_item_in_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for complete-item-in-rollout."""
    rollout_id: str = args.rollout_id
    item_id: str = args.item_id
    # argparse validates choices; cast narrows str → Literal for the typed backend.
    outcome = cast("Literal['completed', 'halted', 'skipped']", args.outcome)
    merge_actor = cast(
        "Literal['human', 'manager-allowlist', 'manager-autonomous', 'manager+human-fixup', '']",  # noqa: E501
        args.merge_actor if args.merge_actor is not None else "",
    )
    decision_rule = cast(
        "Literal['', 'agent-judgment']",
        args.decision_rule if args.decision_rule is not None else "",
    )

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.complete_item_in_rollout(
                user_id,
                rollout_id,
                item_id,
                outcome,
                merge_actor=merge_actor,
                decision_rule=decision_rule,
            )

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


# ---------------------------------------------------------------------------
# halt-rollout
# ---------------------------------------------------------------------------


def _cmd_halt_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for halt-rollout."""
    rollout_id: str = args.rollout_id
    reason: str = args.reason
    comment: str | None = args.comment
    item_id: str | None = args.item_id

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.halt_rollout(
                user_id,
                rollout_id,
                reason,
                comment=comment,
                item_id=item_id,
            )

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


# ---------------------------------------------------------------------------
# cancel-rollout
# ---------------------------------------------------------------------------


def _cmd_cancel_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for cancel-rollout."""
    rollout_id: str = args.rollout_id
    reason: str = args.reason

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.cancel_rollout(user_id, rollout_id, reason)

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


# ---------------------------------------------------------------------------
# replan-rollout
# ---------------------------------------------------------------------------


def _cmd_replan_rollout(args: argparse.Namespace) -> None:
    """Synchronous handler for replan-rollout."""
    rollout_id: str = args.rollout_id
    from_item: str | None = args.from_item

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.replan_rollout(
                user_id,
                rollout_id,
                from_item=from_item,
            )

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


# ---------------------------------------------------------------------------
# update-rollout-state
# ---------------------------------------------------------------------------


def _cmd_update_rollout_state(args: argparse.Namespace) -> None:
    """Synchronous handler for update-rollout-state."""
    rollout_id: str = args.rollout_id
    # argparse validates choices; cast narrows str → Literal for the typed backend.
    phase = cast(
        "Literal['warm_up', 'dispatching', 'polling', 'reviewing', 'merging', 'reconciling_ac', 'halted']",  # noqa: E501
        args.phase,
    )
    current_item_id: str | None = args.current_item_id
    current_step: str | None = args.current_step

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.update_rollout_state(
                user_id,
                rollout_id,
                phase=phase,
                current_item_id=current_item_id,
                current_step=current_step,
            )

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


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
