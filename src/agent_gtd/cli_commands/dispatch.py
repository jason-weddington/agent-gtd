"""CLI dispatch, run, and dispatch-host subcommands for agent-gtd.

Registers seven subcommands on the shared subparsers action:

- ``dispatch-item``: dispatch an item for autonomous build or plan execution.
- ``list-runs``: list dispatch runs, optionally filtered by item or status.
- ``cancel-run``: cancel a single dispatched run (no-op if already finished).
- ``list-dispatch-hosts``: list registered dispatch hosts (id, label, URL, drain state).
- ``drain-host``: take a host out of rotation (operator action; --reason mandatory
  unless the host is already drained).
- ``undrain-host``: return a drained host to rotation.
- ``set-host-labels``: replace a host's operator-set capability labels.
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
    ``max_turns``, ``rollout_id``, and ``dispatch_host_id``; prints the
    resulting run dict as JSON to stdout.

    **Local-mode limitation:** in local SQLite mode (no ``AGENT_GTD_URL``),
    the CLI creates the run row in the database but does *not* enqueue it for
    execution — there is no in-process dispatch worker in a short-lived CLI
    process, so the run remains ``status=pending`` until an external worker
    picks it up.  In HTTP mode the server enqueues the run immediately
    server-side after creation.

    Args:
        args: Parsed namespace with ``item_id``, ``mode``, ``max_turns``,
            ``rollout_id``, and ``dispatch_host_id``.
    """

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.dispatch_item(
                user_id,
                args.item_id,
                max_turns=args.max_turns,
                mode=args.mode,
                rollout_id=args.rollout_id,
                dispatch_host_id=args.dispatch_host_id,
                allow_drained_host=args.allow_drained_host,
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

    Calls ``backend.list_dispatch_hosts``; prints the ``{id, label, url,
    capability_labels, drain_reason}`` list as JSON to stdout.  A non-null
    ``drain_reason`` means the host is out of rotation and the string says
    why.  No secret fields are printed — the backend projection already
    excludes ``api_key`` and related fields.

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


def _cmd_drain_host(args: argparse.Namespace) -> None:
    """Take a dispatch host out of rotation (operator action).

    Calls ``backend.drain_dispatch_host`` with the host reference (id,
    unique label, or unique URL substring) and the optional ``--reason``;
    prints the resulting host dict (``{id, label, url, drain_reason}``) as
    JSON to stdout.  A drain an agent can trigger is not a drain, so these
    verbs have no MCP counterpart — draining is an operator action with a
    reason string.  There is no override: nothing in this CLI contract can
    route work to a drained host.

    Args:
        args: Parsed namespace with ``host`` and optional ``reason``.
    """

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.drain_dispatch_host(
                user_id, args.host, reason=args.reason
            )

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def _cmd_set_host_labels(args: argparse.Namespace) -> None:
    """Replace a dispatch host's capability labels.

    Calls ``backend.set_dispatch_host_labels`` with the host reference (id,
    unique label, or unique URL substring) and the full replacement list
    (``--clear`` sends an empty list); prints the resulting host dict as JSON.

    Args:
        args: Parsed namespace with ``host``, ``labels`` and ``clear``.
    """
    if args.clear == bool(args.labels):
        fail(ValueError("supply one or more labels, or --clear (not both)"))

    labels: list[str] = [] if args.clear else list(args.labels)

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.set_dispatch_host_labels(user_id, args.host, labels)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def _cmd_cancel_run(args: argparse.Namespace) -> None:
    """Cancel a single dispatched run and print the run dict as JSON."""

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.cancel_run(user_id, args.run_id, force=args.force)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def _cmd_undrain_host(args: argparse.Namespace) -> None:
    """Return a drained dispatch host to rotation.

    Calls ``backend.undrain_dispatch_host`` with the host reference; prints
    the resulting host dict as JSON to stdout.  Idempotent — undraining a
    never-drained host succeeds with ``drain_reason: null``.

    Args:
        args: Parsed namespace with ``host``.
    """

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.undrain_dispatch_host(user_id, args.host)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        fail(e)
    emit_json(result)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the seven dispatch/host subparsers.

    Registers dispatch-item, list-runs, cancel-run, list-dispatch-hosts, drain-host,
    undrain-host, and set-host-labels.

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
    # cancel-run
    # ------------------------------------------------------------------ #
    cr = subparsers.add_parser(
        "cancel-run",
        help=(
            "Cancel a single dispatched run (no-op if already finished;"
            " rollout runs are refused unless --force is given)."
        ),
    )
    cr.add_argument("run_id", help="ID of the dispatch run.")
    cr.add_argument(
        "--force",
        action="store_true",
        help=(
            "Cancel a run that belongs to a rollout anyway and record"
            " 'forced by operator'; the rollout's own status is not changed."
            " Force-cancelling a rollout's loop run stops that loop on its"
            " dispatch host, leaving the rollout running without a driver —"
            " follow it with cancel-rollout or halt-rollout, because otherwise"
            " the next restart of that host resumes the loop."
        ),
    )
    cr.set_defaults(func=_cmd_cancel_run)

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
    di.add_argument(
        "--allow-drained-host",
        action="store_true",
        dest="allow_drained_host",
        help=(
            "Smoke-test a drained host on purpose: skip the drain refusal for"
            " this one dispatch. Requires --dispatch-host-id."
        ),
    )
    di.add_argument(
        "--rollout-id",
        type=str,
        default=None,
        dest="rollout_id",
        metavar="ROLLOUT_ID",
        help=(
            "Associate this dispatch with an existing rollout by ID"
            " (permitted with build and plan modes)."
        ),
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
        help="List registered dispatch hosts (id, label, URL, drain state).",
    )
    ldh.set_defaults(func=_cmd_list_dispatch_hosts)

    # ------------------------------------------------------------------ #
    # drain-host
    # ------------------------------------------------------------------ #
    dh = subparsers.add_parser(
        "drain-host",
        help=(
            "Take a dispatch host out of rotation"
            " (--reason mandatory unless already drained)."
        ),
    )
    dh.add_argument("host", type=str, help="Host id, unique label, or URL substring.")
    dh.add_argument(
        "--reason",
        type=str,
        default=None,
        dest="reason",
        help=(
            "Why the host is out of rotation. Mandatory unless the host is"
            " already drained; whitespace is stripped. Omit to keep an"
            " existing reason."
        ),
    )
    dh.set_defaults(func=_cmd_drain_host)

    # ------------------------------------------------------------------ #
    # undrain-host
    # ------------------------------------------------------------------ #
    uh = subparsers.add_parser(
        "undrain-host",
        help="Return a drained dispatch host to rotation.",
    )
    uh.add_argument("host", type=str, help="Host id, unique label, or URL substring.")
    uh.set_defaults(func=_cmd_undrain_host)

    # ------------------------------------------------------------------ #
    # set-host-labels
    # ------------------------------------------------------------------ #
    shl = subparsers.add_parser(
        "set-host-labels",
        help=(
            "Replace a dispatch host's capability labels (full list). Work"
            " whose required labels the host lacks is never routed to it."
        ),
    )
    shl.add_argument(
        "host", help="Host id, exact label, or a unique substring of its URL."
    )
    shl.add_argument("labels", nargs="*", metavar="LABEL", help="Labels to set.")
    shl.add_argument(
        "--clear", action="store_true", help="Remove all capability labels."
    )
    shl.set_defaults(func=_cmd_set_host_labels)
