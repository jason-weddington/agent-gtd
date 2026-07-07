"""CLI subcommand handlers for item lifecycle and blocker operations.

Registers 8 subcommands on the ``agent-gtd`` parser via :func:`register`:
get-item, list-items, complete-item, delete-item, inbox-capture, add-blocker,
remove-blocker, list-blockers.  Each handler is a synchronous function that
runs its backend work inside :func:`asyncio.run`, following the sync-wrapper /
async-fetch split used by :mod:`agent_gtd.cli`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import backend_session, emit_json, fail

if TYPE_CHECKING:
    import argparse


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register 8 item lifecycle and blocker subcommands on *subparsers*.

    Each subcommand parser is wired to its handler via
    ``parser.set_defaults(func=handler)`` so that ``main()`` can dispatch
    with ``args.func(args)`` without naming the handlers explicitly.

    Args:
        subparsers: The subparsers action from the top-level ``agent-gtd``
            argument parser.
    """
    # ------------------------------------------------------------------
    # get-item
    # ------------------------------------------------------------------
    p = subparsers.add_parser("get-item", help="Get an item by ID.")
    p.add_argument("item_id", help="UUID of the item to retrieve.")
    p.set_defaults(func=_cmd_get_item)

    # ------------------------------------------------------------------
    # list-items
    # ------------------------------------------------------------------
    p = subparsers.add_parser("list-items", help="List items with optional filters.")
    p.add_argument(
        "--status",
        default=None,
        help=(
            "Filter by status. One of: inbox, new, ready, next_action,"
            " waiting_for, scheduled, someday_maybe, active, review, done,"
            " cancelled."
        ),
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Filter by project UUID.",
    )
    p.add_argument(
        "--priority",
        default=None,
        help="Filter by priority. One of: low, normal, high, urgent.",
    )
    p.add_argument(
        "--assigned-to",
        dest="assigned_to",
        default=None,
        help="Filter by assignee.",
    )
    p.set_defaults(func=_cmd_list_items)

    # ------------------------------------------------------------------
    # complete-item
    # ------------------------------------------------------------------
    p = subparsers.add_parser("complete-item", help="Mark an item as done.")
    p.add_argument("item_id", help="UUID of the item to complete.")
    p.set_defaults(func=_cmd_complete_item)

    # ------------------------------------------------------------------
    # delete-item
    # ------------------------------------------------------------------
    p = subparsers.add_parser("delete-item", help="Delete an item.")
    p.add_argument("item_id", help="UUID of the item to delete.")
    p.set_defaults(func=_cmd_delete_item)

    # ------------------------------------------------------------------
    # inbox-capture
    # ------------------------------------------------------------------
    p = subparsers.add_parser("inbox-capture", help="Capture a new item to the inbox.")
    p.add_argument("title", help="Title of the new item.")
    p.set_defaults(func=_cmd_inbox_capture)

    # ------------------------------------------------------------------
    # add-blocker
    # ------------------------------------------------------------------
    p = subparsers.add_parser("add-blocker", help="Add a blocker to an item.")
    p.add_argument("item_id", help="UUID of the item to block.")
    p.add_argument("blocker_item_id", help="UUID of the blocking item.")
    p.set_defaults(func=_cmd_add_blocker)

    # ------------------------------------------------------------------
    # remove-blocker
    # ------------------------------------------------------------------
    p = subparsers.add_parser("remove-blocker", help="Remove a blocker from an item.")
    p.add_argument("item_id", help="UUID of the item.")
    p.add_argument("blocker_item_id", help="UUID of the blocker to remove.")
    p.set_defaults(func=_cmd_remove_blocker)

    # ------------------------------------------------------------------
    # list-blockers
    # ------------------------------------------------------------------
    p = subparsers.add_parser("list-blockers", help="List blockers of an item.")
    p.add_argument("item_id", help="UUID of the item whose blockers to list.")
    p.set_defaults(func=_cmd_list_blockers)


# ---------------------------------------------------------------------------
# get-item
# ---------------------------------------------------------------------------


def _cmd_get_item(args: argparse.Namespace) -> None:
    """Handle the get-item subcommand.

    Retrieves the item at ``args.item_id`` and prints it as JSON to stdout.
    On any error, prints ``Error: <msg>`` to stderr and exits 1.

    Args:
        args: Parsed namespace; must have attribute ``item_id``.
    """
    try:
        result = asyncio.run(_fetch_get_item(args.item_id))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_get_item(item_id: str) -> dict[str, Any]:
    """Fetch an item by ID from the authenticated backend.

    Args:
        item_id: UUID of the item to retrieve.

    Returns:
        The item dict returned by the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.get_item(user_id, item_id)


# ---------------------------------------------------------------------------
# list-items
# ---------------------------------------------------------------------------


def _cmd_list_items(args: argparse.Namespace) -> None:
    """Handle the list-items subcommand.

    Lists items using the optional filters on *args* and prints the
    resulting dict as JSON to stdout.  On any error, prints ``Error: <msg>``
    to stderr and exits 1.

    Args:
        args: Parsed namespace; may have optional attributes ``status``,
            ``project_id``, ``priority``, ``assigned_to``.
    """
    try:
        result = asyncio.run(
            _fetch_list_items(
                status=args.status,
                project_id=args.project_id,
                priority=args.priority,
                assigned_to=args.assigned_to,
            )
        )
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_list_items(
    *,
    status: str | None,
    project_id: str | None,
    priority: str | None,
    assigned_to: str | None,
) -> dict[str, Any]:
    """Fetch items from the backend using optional filters.

    Args:
        status: Optional status filter string (no client-side validation).
        project_id: Optional project UUID filter.
        priority: Optional priority filter string (no client-side validation).
        assigned_to: Optional assignee filter.

    Returns:
        The dict returned by the backend (shape: ``{"items": [...], ...}``).
    """
    async with backend_session() as (backend, user_id):
        return await backend.list_items(
            user_id,
            status=status,
            project_id=project_id,
            priority=priority,
            assigned_to=assigned_to,
        )


# ---------------------------------------------------------------------------
# complete-item
# ---------------------------------------------------------------------------


def _cmd_complete_item(args: argparse.Namespace) -> None:
    """Handle the complete-item subcommand.

    Marks the item at ``args.item_id`` as done and prints the updated item
    as JSON to stdout.  On any error, prints ``Error: <msg>`` to stderr and
    exits 1.

    Args:
        args: Parsed namespace; must have attribute ``item_id``.
    """
    try:
        result = asyncio.run(_fetch_complete_item(args.item_id))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_complete_item(item_id: str) -> dict[str, Any]:
    """Complete an item via the authenticated backend.

    Args:
        item_id: UUID of the item to complete.

    Returns:
        The updated item dict returned by the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.complete_item(user_id, item_id)


# ---------------------------------------------------------------------------
# delete-item
# ---------------------------------------------------------------------------


def _cmd_delete_item(args: argparse.Namespace) -> None:
    """Handle the delete-item subcommand.

    Deletes the item at ``args.item_id`` and prints the confirmation dict
    as JSON to stdout.  On any error, prints ``Error: <msg>`` to stderr and
    exits 1.

    Args:
        args: Parsed namespace; must have attribute ``item_id``.
    """
    try:
        result = asyncio.run(_fetch_delete_item(args.item_id))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_delete_item(item_id: str) -> dict[str, Any]:
    """Delete an item via the authenticated backend.

    Args:
        item_id: UUID of the item to delete.

    Returns:
        The confirmation dict returned by the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.delete_item(user_id, item_id)


# ---------------------------------------------------------------------------
# inbox-capture
# ---------------------------------------------------------------------------


def _cmd_inbox_capture(args: argparse.Namespace) -> None:
    """Handle the inbox-capture subcommand.

    Captures ``args.title`` as a new inbox item and prints the returned
    dict as JSON to stdout.  On any error, prints ``Error: <msg>`` to stderr
    and exits 1.

    Args:
        args: Parsed namespace; must have attribute ``title``.
    """
    try:
        result = asyncio.run(_fetch_inbox_capture(args.title))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_inbox_capture(title: str) -> dict[str, Any]:
    """Capture a new item to the inbox via the authenticated backend.

    Uses ``created_by="cli"`` for attribution.

    Args:
        title: Title of the new inbox item.

    Returns:
        The dict returned by the backend (item fields + ``inbox_pending_count``).
    """
    async with backend_session() as (backend, user_id):
        return await backend.inbox_capture(user_id, title, created_by="cli")


# ---------------------------------------------------------------------------
# add-blocker
# ---------------------------------------------------------------------------


def _cmd_add_blocker(args: argparse.Namespace) -> None:
    """Handle the add-blocker subcommand.

    Adds ``args.blocker_item_id`` as a blocker of ``args.item_id`` and
    prints the resulting blocker dict as JSON to stdout.  On any error,
    prints ``Error: <msg>`` to stderr and exits 1.

    Args:
        args: Parsed namespace; must have attributes ``item_id`` and
            ``blocker_item_id``.
    """
    try:
        result = asyncio.run(_fetch_add_blocker(args.item_id, args.blocker_item_id))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_add_blocker(item_id: str, blocker_item_id: str) -> dict[str, Any]:
    """Add a blocker relation via the authenticated backend.

    Args:
        item_id: UUID of the item to block.
        blocker_item_id: UUID of the blocking item.

    Returns:
        The BlockerSummary dict returned by the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.add_blocker(user_id, item_id, blocker_item_id)


# ---------------------------------------------------------------------------
# remove-blocker
# ---------------------------------------------------------------------------


def _cmd_remove_blocker(args: argparse.Namespace) -> None:
    """Handle the remove-blocker subcommand.

    Removes ``args.blocker_item_id`` as a blocker of ``args.item_id`` and
    prints ``{"ok": true}`` as JSON to stdout.  On any error, prints
    ``Error: <msg>`` to stderr and exits 1.

    Args:
        args: Parsed namespace; must have attributes ``item_id`` and
            ``blocker_item_id``.
    """
    try:
        asyncio.run(_fetch_remove_blocker(args.item_id, args.blocker_item_id))
        emit_json({"ok": True})
    except Exception as e:
        fail(e)


async def _fetch_remove_blocker(item_id: str, blocker_item_id: str) -> None:
    """Remove a blocker relation via the authenticated backend.

    Args:
        item_id: UUID of the item.
        blocker_item_id: UUID of the blocker to remove.
    """
    async with backend_session() as (backend, user_id):
        await backend.remove_blocker(user_id, item_id, blocker_item_id)


# ---------------------------------------------------------------------------
# list-blockers
# ---------------------------------------------------------------------------


def _cmd_list_blockers(args: argparse.Namespace) -> None:
    """Handle the list-blockers subcommand.

    Lists the blockers of the item at ``args.item_id`` and prints them as
    a JSON array to stdout.  On any error, prints ``Error: <msg>`` to stderr
    and exits 1.

    Args:
        args: Parsed namespace; must have attribute ``item_id``.
    """
    try:
        result = asyncio.run(_fetch_list_blockers(args.item_id))
        emit_json(result)
    except Exception as e:
        fail(e)


async def _fetch_list_blockers(item_id: str) -> list[dict[str, Any]]:
    """Fetch the blockers of an item from the authenticated backend.

    Args:
        item_id: UUID of the item whose blockers to list.

    Returns:
        The list of BlockerSummary dicts returned by the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.list_blockers(user_id, item_id)
