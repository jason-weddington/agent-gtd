"""Rollout planning CLI commands for the ``agent-gtd`` CLI.

Adds five subcommands: ``plan-rollout``, ``dispatch-rollout``,
``start-rollout``, ``list-rollouts``, and ``get-rollout-plan``.  Each handler
acquires a backend + user_id pair via
:func:`~agent_gtd.cli_commands._shared.backend_session`, calls the
corresponding backend method, and writes the JSON result to stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import (
    backend_session,
    emit_json,
    fail,
)
from agent_gtd.exceptions import LegalityContractError

if TYPE_CHECKING:
    import argparse


def _cmd_plan_rollout(args: argparse.Namespace) -> None:
    """Execute the plan-rollout subcommand.

    Flattens space- and comma-separated item UUIDs, calls
    :meth:`~agent_gtd.mcp_backend.McpBackend.plan_rollout`, and writes the
    resulting rollout dict as JSON to stdout.  A
    :class:`~agent_gtd.exceptions.LegalityContractError` is caught before the
    generic ``Exception`` handler and emits a structured per-item failure
    report to stderr.

    Args:
        args: Parsed namespace containing ``item_ids`` (``list[str]``).
    """
    # Flatten comma/space-separated item IDs — mirrors cli.py _cmd_add_item L726-729.
    item_ids: list[str] = [
        t.strip() for raw in args.item_ids for t in raw.split(",") if t.strip()
    ]

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.plan_rollout(user_id, item_ids)

    try:
        result: Any = asyncio.run(_run())
    except LegalityContractError as exc:
        print(
            f"Error: legality contract failed for {len(exc.failures)} item(s):",
            file=sys.stderr,
        )
        print(json.dumps(exc.failures, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        fail(e)

    emit_json(result)


def _cmd_dispatch_rollout(args: argparse.Namespace) -> None:
    """Execute the dispatch-rollout subcommand.

    Calls :meth:`~agent_gtd.mcp_backend.McpBackend.dispatch_rollout` and
    writes the created manage-mode run dict as JSON to stdout.

    Args:
        args: Parsed namespace containing ``rollout_id`` (``str``).
    """
    rollout_id: str = args.rollout_id

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.dispatch_rollout(user_id, rollout_id)

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


def _cmd_start_rollout(args: argparse.Namespace) -> None:
    """Execute the start-rollout subcommand.

    Calls :meth:`~agent_gtd.mcp_backend.McpBackend.start_rollout` and writes
    the updated autonomous_rollouts row dict as JSON to stdout.

    Args:
        args: Parsed namespace containing ``rollout_id`` (``str``).
    """
    rollout_id: str = args.rollout_id

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.start_rollout(user_id, rollout_id)

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


def _cmd_get_rollout_plan(args: argparse.Namespace) -> None:
    """Execute the get-rollout-plan subcommand.

    Calls :meth:`~agent_gtd.mcp_backend.McpBackend.get_rollout_plan` and
    writes the rollout plan dict as JSON to stdout.

    Args:
        args: Parsed namespace containing ``rollout_id`` (``str``).
    """
    rollout_id: str = args.rollout_id

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.get_rollout_plan(user_id, rollout_id)

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


def _cmd_list_rollouts(args: argparse.Namespace) -> None:
    """Execute the list-rollouts subcommand.

    Clamps ``--limit`` to ``[1, 100]`` for MCP-parity (the clamp lives in the
    MCP tool layer at ``mcp_server.py`` L1419, not in the backend), then calls
    :meth:`~agent_gtd.mcp_backend.McpBackend.list_rollouts` and writes the
    result list as JSON to stdout.

    Args:
        args: Parsed namespace containing ``project_id`` (``str | None``),
            ``status`` (``str | None``), and ``limit`` (``int``).
    """
    project_id: str | None = args.project_id
    status: str | None = args.status
    limit: int = min(max(1, args.limit), 100)

    async def _run() -> Any:
        async with backend_session() as (backend, user_id):
            return await backend.list_rollouts(
                user_id, project_id=project_id, status=status, limit=limit
            )

    try:
        result: Any = asyncio.run(_run())
    except Exception as e:
        fail(e)

    emit_json(result)


def register(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register rollout-planning subcommands on *subparsers*.

    Adds five subparsers: ``plan-rollout``, ``dispatch-rollout``,
    ``start-rollout``, ``list-rollouts``, and ``get-rollout-plan``.  Each
    attaches its handler via ``set_defaults(func=<handler>)``.

    Args:
        subparsers: The subparsers action returned by
            ``parser.add_subparsers(...)`` in ``cli.py``.
    """
    # --- plan-rollout ---
    pr = subparsers.add_parser(
        "plan-rollout",
        help="Plan a new autonomous rollout from a set of item UUIDs.",
    )
    pr.add_argument(
        "item_ids",
        nargs="+",
        help="Item UUIDs to include (space- or comma-separated).",
    )
    pr.set_defaults(func=_cmd_plan_rollout)

    # --- dispatch-rollout ---
    dr = subparsers.add_parser(
        "dispatch-rollout",
        help="Dispatch a planned rollout, starting the manage-mode run.",
    )
    dr.add_argument("rollout_id", help="Autonomous rollout ID.")
    dr.set_defaults(func=_cmd_dispatch_rollout)

    # --- start-rollout ---
    sr = subparsers.add_parser(
        "start-rollout",
        help="Start an autonomous rollout, transitioning it to running state.",
    )
    sr.add_argument("rollout_id", help="Autonomous rollout ID.")
    sr.set_defaults(func=_cmd_start_rollout)

    # --- list-rollouts ---
    lr = subparsers.add_parser(
        "list-rollouts",
        help="List autonomous rollouts, optionally filtered by project or status.",
    )
    lr.add_argument(
        "--project",
        dest="project_id",
        metavar="PROJECT_ID",
        help="Filter by project UUID.",
    )
    lr.add_argument(
        "--status",
        help=(
            "Filter by rollout status: "
            "pending | planning | running | completed | failed | halted | cancelled"
        ),
    )
    lr.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of rollouts to return (default: 20; clamped to [1, 100]).",
    )
    lr.set_defaults(func=_cmd_list_rollouts)

    # --- get-rollout-plan ---
    grp = subparsers.add_parser(
        "get-rollout-plan",
        help="Fetch the plan (item schedule) for a rollout.",
    )
    grp.add_argument("rollout_id", help="Autonomous rollout ID.")
    grp.set_defaults(func=_cmd_get_rollout_plan)
