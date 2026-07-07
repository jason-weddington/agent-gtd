"""CLI dispatch, run, and dispatch-host subcommands for agent-gtd.

Registers three subcommands on the shared subparsers action:

- ``dispatch-item``: dispatch an item for autonomous build or plan execution.
- ``list-runs``: list dispatch runs, optionally filtered by item or status.
- ``list-dispatch-hosts``: list registered dispatch hosts (id, label, URL only).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import backend_session, emit_json, fail

if TYPE_CHECKING:
    import argparse


def _cmd_dispatch_item(args: argparse.Namespace) -> None:
    """Dispatch an item for autonomous build or plan execution.

    Calls ``backend.dispatch_item`` with the provided ``item_id``, ``mode``,
    ``max_turns``, and ``dispatch_host_id``; prints the resulting run dict as
    JSON to stdout.  Does NOT call ``enqueue_run`` — in a one-shot CLI process
    no dispatch worker is running; in local mode the created run row remains
    ``status=pending``.

    Args:
        args: Parsed namespace with ``item_id``, ``mode``, ``max_turns``,
            and ``dispatch_host_id``.
    """

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.dispatch_item(
                user_id,
                args.item_id,
                max_turns=args.max_turns,
                mode=args.mode,
                dispatch_host_id=args.dispatch_host_id,
            )

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def _cmd_list_runs(args: argparse.Namespace) -> None:
    """List dispatch runs, optionally filtered by item or status.

    Calls ``backend.list_runs`` with optional ``item_id`` and ``status``
    filters; prints the resulting list as JSON to stdout.

    Args:
        args: Parsed namespace with optional ``item_id`` and ``status``.
    """

    async def _run() -> list[dict[str, Any]]:
        async with backend_session() as (backend, user_id):
            return await backend.list_runs(
                user_id,
                item_id=args.item_id,
                status=args.status,
            )

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def _cmd_list_dispatch_hosts(args: argparse.Namespace) -> None:
    """List registered dispatch hosts.

    Calls ``backend.list_dispatch_hosts``; prints the ``{id, label, url}``
    list as JSON to stdout.  No secret fields are printed — the backend
    projection already excludes ``api_key`` and related fields.

    Args:
        args: Parsed namespace (no filtering arguments for this subcommand).
    """

    async def _run() -> list[dict[str, Any]]:
        async with backend_session() as (backend, user_id):
            return await backend.list_dispatch_hosts(user_id)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register dispatch-item, list-runs, and list-dispatch-hosts subparsers.

    Each subparser calls ``parser.set_defaults(func=<handler>)`` so that
    ``cli.main()``'s ``args.func(args)`` fall-through invokes the right
    handler without touching ``cli.py``'s if/elif chain.

    Does NOT add ``manage`` mode — it is rejected server-side
    (``services/dispatch_service.py``).  Does NOT add a ``--engine`` flag —
    engine derives from the item's ``build_engine`` field.

    Args:
        subparsers: The subparsers action returned by
            ``parser.add_subparsers(...)`` in ``cli.py``.
    """
    # ------------------------------------------------------------------ #
    # dispatch-item
    # ------------------------------------------------------------------ #
    di = subparsers.add_parser(
        "dispatch-item",
        help="Dispatch an item for autonomous build or plan execution.",
    )
    di.add_argument("item_id", type=str, help="ID of the item to dispatch.")
    di.add_argument(
        "--mode",
        choices=["build", "plan"],
        default="build",
        help=(
            "Dispatch mode: 'build' (default) or 'plan'. 'manage' is excluded"
            " — it is rejected server-side."
        ),
    )
    di.add_argument(
        "--max-turns",
        type=int,
        default=None,
        dest="max_turns",
        help="Maximum agent turns (default: server-side default).",
    )
    di.add_argument(
        "--dispatch-host-id",
        type=str,
        default=None,
        dest="dispatch_host_id",
        help="Pin execution to a specific dispatch host by ID.",
    )
    di.set_defaults(func=_cmd_dispatch_item)

    # ------------------------------------------------------------------ #
    # list-runs
    # ------------------------------------------------------------------ #
    lr = subparsers.add_parser(
        "list-runs",
        help="List dispatch runs.",
    )
    lr.add_argument(
        "--item-id",
        type=str,
        default=None,
        dest="item_id",
        help="Filter runs by item ID.",
    )
    lr.add_argument(
        "--status",
        type=str,
        default=None,
        help=(
            "Filter by run status"
            " (pending|running|success|failed|cancelled|error|timeout)."
        ),
    )
    lr.set_defaults(func=_cmd_list_runs)

    # ------------------------------------------------------------------ #
    # list-dispatch-hosts
    # ------------------------------------------------------------------ #
    ldh = subparsers.add_parser(
        "list-dispatch-hosts",
        help="List registered dispatch hosts (id, label, URL).",
    )
    ldh.set_defaults(func=_cmd_list_dispatch_hosts)
