"""CLI subcommands for notes and comments.

Registers exactly these 8 subcommands via :func:`register`:
add-note, get-note, list-notes, update-note, delete-note,
add-comment, list-comments, update-comment.

Does NOT register delete-comment: the ``LocalBackend.delete_comment``
method exists at ``mcp_backend.py:242`` but is intentionally unsurfaced
(no matching ``@mcp.tool`` decorator in ``mcp_server.py``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import (
    backend_session,
    emit_json,
    fail,
    load_json_payload,
)

if TYPE_CHECKING:
    import argparse

# ---------------------------------------------------------------------------
# Allow-set constants for JSON payload validation.
#
# Each constant freezes the keys that a --from-json / --stdin payload may
# contain for its command.  Any key not in the set is rejected loudly
# (exit 1, "unknown key(s)") BEFORE any backend call, mirroring the
# _ADD_ITEM_FIELDS / _UPDATE_ITEM_FIELDS guards in cli.py.
#
# Defining a separate frozenset per command (rather than sharing one) means
# a future divergence — e.g. update-note gaining a "pinned" field that
# add-note does not support — is a deliberate edit rather than an accident.
# ---------------------------------------------------------------------------

#: Keys accepted by ``add-note --from-json / --stdin``.
_ADD_NOTE_FIELDS: frozenset[str] = frozenset({"title", "content_markdown", "labels"})

#: Keys accepted by ``update-note --from-json / --stdin``.
_UPDATE_NOTE_FIELDS: frozenset[str] = frozenset({"title", "content_markdown", "labels"})

#: Keys accepted by ``add-comment --from-json / --stdin``.
#: ``project_id`` and ``item_id`` are CLI-flag-only (not JSON payload keys).
_ADD_COMMENT_FIELDS: frozenset[str] = frozenset({"content_markdown"})

#: Keys accepted by ``update-comment --from-json / --stdin``.
_UPDATE_COMMENT_FIELDS: frozenset[str] = frozenset({"content_markdown"})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flatten_labels(raw_labels: list[str] | None) -> list[str] | None:
    """Flatten and split CLI label values into a clean list.

    Handles the repeat-flag and comma-separated patterns from argparse
    ``action="append"``:  ``--labels a,b --labels c`` → ``["a", "b", "c"]``.
    Blank tokens (empty or whitespace-only) are discarded.

    Args:
        raw_labels: The raw list of label strings from argparse
            ``action="append"`` (``None`` when the flag was never given).

    Returns:
        A flat, stripped list of non-empty labels, or ``None`` when
        *raw_labels* is falsy.
    """
    if not raw_labels:
        return None
    return [lbl.strip() for raw in raw_labels for lbl in raw.split(",") if lbl.strip()]


# ---------------------------------------------------------------------------
# Note async workers
# ---------------------------------------------------------------------------


async def _do_add_note(
    project_id: str,
    title: str,
    content_markdown: str,
    labels: list[str] | None,
) -> dict[str, Any]:
    """Create a note via the backend.

    Args:
        project_id: UUID of the project to add the note to.
        title: Note title.
        content_markdown: Note body in Markdown.
        labels: Optional list of labels.

    Returns:
        The newly created note dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.create_note(
            user_id,
            project_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )


async def _do_get_note(note_id: str) -> dict[str, Any]:
    """Fetch a single note by UUID via the backend.

    Args:
        note_id: UUID of the note to retrieve.

    Returns:
        The note dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.get_note(user_id, note_id)


async def _do_list_notes(project_id: str | None) -> list[dict[str, Any]]:
    """List notes, optionally filtered by project.

    Args:
        project_id: Optional project UUID to filter by.  ``None`` returns a
            cross-project list of all notes.

    Returns:
        A list of note dicts from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.list_notes(user_id, project_id=project_id)


async def _do_update_note(
    note_id: str,
    title: str | None,
    content_markdown: str | None,
    labels: list[str] | None,
) -> dict[str, Any]:
    """Update a note's fields via the backend.

    Any ``None`` argument leaves the corresponding field unchanged
    (backend no-op semantics).  Passing all ``None`` is a valid no-op.

    Args:
        note_id: UUID of the note to update.
        title: New title, or ``None`` to leave unchanged.
        content_markdown: New body in Markdown, or ``None`` to leave unchanged.
        labels: New labels, or ``None`` to leave unchanged.

    Returns:
        The updated (or unchanged) note dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.update_note(
            user_id,
            note_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )


async def _do_delete_note(note_id: str) -> dict[str, Any]:
    """Delete a note by UUID via the backend.

    Args:
        note_id: UUID of the note to delete.

    Returns:
        Confirmation dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.delete_note(user_id, note_id)


# ---------------------------------------------------------------------------
# Comment async workers
# ---------------------------------------------------------------------------


async def _do_add_comment(
    project_id: str | None,
    item_id: str | None,
    content_markdown: str,
) -> dict[str, Any]:
    """Create a comment on a project or item via the backend.

    Args:
        project_id: UUID of the project to comment on (mutually exclusive
            with *item_id*).
        item_id: UUID of the item to comment on (mutually exclusive with
            *project_id*).
        content_markdown: Comment body in Markdown.

    Returns:
        The newly created comment dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.create_comment(
            user_id,
            project_id=project_id,
            item_id=item_id,
            content_markdown=content_markdown,
            created_by="cli",
        )


async def _do_list_comments(
    project_id: str | None,
    item_id: str | None,
) -> list[dict[str, Any]]:
    """List comments, optionally filtered by project and/or item.

    Args:
        project_id: Optional project UUID to filter by.
        item_id: Optional item UUID to filter by.

    Returns:
        A list of comment dicts from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.list_comments(
            user_id,
            project_id=project_id,
            item_id=item_id,
        )


async def _do_update_comment(
    comment_id: str,
    content_markdown: str | None,
) -> dict[str, Any]:
    """Update a comment's content via the backend.

    Args:
        comment_id: UUID of the comment to update.
        content_markdown: New body in Markdown, or ``None`` for a no-op.

    Returns:
        The updated (or unchanged) comment dict from the backend.
    """
    async with backend_session() as (backend, user_id):
        return await backend.update_comment(
            user_id,
            comment_id,
            content_markdown=content_markdown,
        )


# ---------------------------------------------------------------------------
# Note sync handlers
# ---------------------------------------------------------------------------


def _handle_add_note(args: argparse.Namespace) -> None:
    """Execute the add-note subcommand.

    Reads optional fields from *args* (title, labels) and the JSON payload
    (``--from-json`` / ``--stdin``), merges them with flag-wins precedence
    (scalar flags override the same key in the JSON payload), then calls
    ``backend.create_note``.  Emits the new note as JSON on stdout.

    Args:
        args: Parsed argparse namespace for the add-note subcommand.
    """
    try:
        payload = load_json_payload(args.from_json, args.stdin)
    except Exception as exc:
        fail(exc)

    # Reject unknown payload keys BEFORE any field extraction or backend call.
    unknown = sorted(set(payload.keys()) - _ADD_NOTE_FIELDS)
    if unknown:
        fail(f"unknown key(s) in payload: {', '.join(unknown)}")

    # Scalar flags override the same key in the JSON payload.
    title: str
    if args.title is not None:
        title = args.title
    elif "title" in payload:
        title = str(payload["title"])
    else:
        title = ""

    labels_flat = _flatten_labels(args.labels)
    labels: list[str] | None
    if labels_flat is not None:
        labels = labels_flat
    elif "labels" in payload:
        raw = payload["labels"]
        labels = [str(v) for v in raw] if isinstance(raw, list) else None
    else:
        labels = None

    content_markdown = str(payload.get("content_markdown", ""))

    try:
        result = asyncio.run(
            _do_add_note(args.project_id, title, content_markdown, labels)
        )
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_get_note(args: argparse.Namespace) -> None:
    """Execute the get-note subcommand.

    Args:
        args: Parsed argparse namespace for the get-note subcommand.
    """
    try:
        result = asyncio.run(_do_get_note(args.note_id))
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_list_notes(args: argparse.Namespace) -> None:
    """Execute the list-notes subcommand.

    Args:
        args: Parsed argparse namespace for the list-notes subcommand.
    """
    try:
        result = asyncio.run(_do_list_notes(args.project_id))
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_update_note(args: argparse.Namespace) -> None:
    """Execute the update-note subcommand.

    Scalar flags (``--title``, ``--labels``) override the same key in the
    JSON payload when both are present.  All-``None`` inputs are a valid
    no-op: the backend is called with ``title=None``, ``content_markdown=None``,
    ``labels=None`` and returns the unchanged note.

    Args:
        args: Parsed argparse namespace for the update-note subcommand.
    """
    try:
        payload = load_json_payload(args.from_json, args.stdin)
    except Exception as exc:
        fail(exc)

    # Reject unknown payload keys BEFORE any field extraction or backend call.
    unknown = sorted(set(payload.keys()) - _UPDATE_NOTE_FIELDS)
    if unknown:
        fail(f"unknown key(s) in payload: {', '.join(unknown)}")

    # Scalar flags override payload keys when both present.
    title: str | None
    if args.title is not None:
        title = args.title
    elif "title" in payload:
        title = str(payload["title"])
    else:
        title = None

    labels_flat = _flatten_labels(args.labels)
    labels: list[str] | None
    if labels_flat is not None:
        labels = labels_flat
    elif "labels" in payload:
        raw = payload["labels"]
        labels = [str(v) for v in raw] if isinstance(raw, list) else None
    else:
        labels = None

    content_markdown: str | None
    if "content_markdown" in payload:
        content_markdown = str(payload["content_markdown"])
    else:
        content_markdown = None

    try:
        result = asyncio.run(
            _do_update_note(args.note_id, title, content_markdown, labels)
        )
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_delete_note(args: argparse.Namespace) -> None:
    """Execute the delete-note subcommand.

    Args:
        args: Parsed argparse namespace for the delete-note subcommand.
    """
    try:
        result = asyncio.run(_do_delete_note(args.note_id))
        emit_json(result)
    except Exception as exc:
        fail(exc)


# ---------------------------------------------------------------------------
# Comment sync handlers
# ---------------------------------------------------------------------------


def _handle_add_comment(args: argparse.Namespace) -> None:
    """Execute the add-comment subcommand.

    Content resolution (``--content-markdown`` flag wins over the
    ``content_markdown`` key in the JSON payload):

    * ``--content-markdown TEXT`` provided → use TEXT (even if empty string).
    * Payload contains ``content_markdown`` → use that value.
    * Neither present → print ``Error:`` to stderr and exit 1.

    Target resolution (exactly one of ``--project-id`` / ``--item-id``):

    * Neither provided → error, exit 1.
    * Both provided → error, exit 1.

    Args:
        args: Parsed argparse namespace for the add-comment subcommand.
    """
    try:
        payload = load_json_payload(args.from_json, args.stdin)
    except Exception as exc:
        fail(exc)

    # Reject unknown payload keys BEFORE any field extraction or backend call.
    unknown = sorted(set(payload.keys()) - _ADD_COMMENT_FIELDS)
    if unknown:
        fail(f"unknown key(s) in payload: {', '.join(unknown)}")

    # Resolve content_markdown: flag wins over payload key.
    content_markdown: str
    if args.content_markdown is not None:
        content_markdown = args.content_markdown
    elif "content_markdown" in payload:
        content_markdown = str(payload["content_markdown"])
    else:
        fail(
            "content_markdown is required: supply --content-markdown TEXT"
            " or include 'content_markdown' in the JSON payload"
        )

    # Exactly one target required.
    if args.project_id is None and args.item_id is None:
        fail("exactly one of --project-id or --item-id is required")
    if args.project_id is not None and args.item_id is not None:
        fail("--project-id and --item-id are mutually exclusive")

    try:
        result = asyncio.run(
            _do_add_comment(args.project_id, args.item_id, content_markdown)
        )
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_list_comments(args: argparse.Namespace) -> None:
    """Execute the list-comments subcommand.

    Both ``--project-id`` and ``--item-id`` are optional and NOT mutually
    exclusive (matches MCP list_comments semantics).

    Args:
        args: Parsed argparse namespace for the list-comments subcommand.
    """
    try:
        result = asyncio.run(_do_list_comments(args.project_id, args.item_id))
        emit_json(result)
    except Exception as exc:
        fail(exc)


def _handle_update_comment(args: argparse.Namespace) -> None:
    """Execute the update-comment subcommand.

    Content resolution (``--content-markdown`` flag wins over the
    ``content_markdown`` key in the JSON payload).  Invoking with no content
    input at all is a valid no-op: the backend is called with
    ``content_markdown=None`` and returns the unchanged comment.

    Args:
        args: Parsed argparse namespace for the update-comment subcommand.
    """
    try:
        payload = load_json_payload(args.from_json, args.stdin)
    except Exception as exc:
        fail(exc)

    # Reject unknown payload keys BEFORE any field extraction or backend call.
    unknown = sorted(set(payload.keys()) - _UPDATE_COMMENT_FIELDS)
    if unknown:
        fail(f"unknown key(s) in payload: {', '.join(unknown)}")

    content_markdown: str | None
    if args.content_markdown is not None:
        content_markdown = args.content_markdown
    elif "content_markdown" in payload:
        content_markdown = str(payload["content_markdown"])
    else:
        content_markdown = None

    try:
        result = asyncio.run(_do_update_comment(args.comment_id, content_markdown))
        emit_json(result)
    except Exception as exc:
        fail(exc)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register note and comment subcommands on *subparsers*.

    Registers exactly these 8 subcommands: add-note, get-note, list-notes,
    update-note, delete-note, add-comment, list-comments, update-comment.
    Does NOT register delete-comment (intentionally unsurfaced — no matching
    ``@mcp.tool`` in ``mcp_server.py`` despite the backend method existing).

    Each subparser attaches its handler via
    ``parser.set_defaults(func=handler)``; handlers match the
    :data:`~agent_gtd.cli_commands._shared.CommandHandler` signature
    ``(argparse.Namespace) -> None``.

    Args:
        subparsers: The subparsers action returned by
            ``parser.add_subparsers(...)`` in ``cli.py``.
    """
    # --- add-note ---
    an = subparsers.add_parser(
        "add-note",
        help="Create a new note in a project.",
    )
    an.add_argument("project_id", help="UUID of the project to add the note to.")
    an.add_argument("--title", default=None, help="Note title.")
    an.add_argument(
        "--labels",
        action="append",
        metavar="LABELS",
        help="Labels (repeatable; comma-separated values accepted per flag).",
    )
    an_src = an.add_mutually_exclusive_group()
    an_src.add_argument(
        "--from-json",
        metavar="FILE",
        help=(
            "Path to a JSON file with note fields (title, content_markdown, labels)."
        ),
    )
    an_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    an.set_defaults(func=_handle_add_note)

    # --- get-note ---
    gn = subparsers.add_parser("get-note", help="Retrieve a note by UUID.")
    gn.add_argument("note_id", help="UUID of the note.")
    gn.set_defaults(func=_handle_get_note)

    # --- list-notes ---
    ln = subparsers.add_parser(
        "list-notes",
        help="List notes, optionally filtered by project.",
    )
    ln.add_argument(
        "--project-id",
        default=None,
        metavar="PROJECT_ID",
        help="Filter by project UUID (omit for cross-project list).",
    )
    ln.set_defaults(func=_handle_list_notes)

    # --- update-note ---
    un = subparsers.add_parser("update-note", help="Update a note's fields.")
    un.add_argument("note_id", help="UUID of the note to update.")
    un.add_argument("--title", default=None, help="New title.")
    un.add_argument(
        "--labels",
        action="append",
        metavar="LABELS",
        help="New labels (repeatable; comma-separated values accepted per flag).",
    )
    un_src = un.add_mutually_exclusive_group()
    un_src.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with note fields to update.",
    )
    un_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    un.set_defaults(func=_handle_update_note)

    # --- delete-note ---
    dn = subparsers.add_parser("delete-note", help="Delete a note by UUID.")
    dn.add_argument("note_id", help="UUID of the note to delete.")
    dn.set_defaults(func=_handle_delete_note)

    # --- add-comment ---
    ac = subparsers.add_parser(
        "add-comment",
        help="Add a comment to a project or item.",
    )
    ac.add_argument(
        "--content-markdown",
        metavar="TEXT",
        default=None,
        help=(
            "Comment content in Markdown."
            "  Required (overrides 'content_markdown' payload key when both given)."
        ),
    )
    ac_src = ac.add_mutually_exclusive_group()
    ac_src.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with comment fields (content_markdown key).",
    )
    ac_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    ac.add_argument(
        "--project-id",
        default=None,
        metavar="PROJECT_ID",
        help="Project to comment on (mutually exclusive with --item-id).",
    )
    ac.add_argument(
        "--item-id",
        default=None,
        metavar="ITEM_ID",
        help="Item to comment on (mutually exclusive with --project-id).",
    )
    ac.set_defaults(func=_handle_add_comment)

    # --- list-comments ---
    lc = subparsers.add_parser(
        "list-comments",
        help="List comments, optionally filtered by project and/or item.",
    )
    lc.add_argument(
        "--project-id",
        default=None,
        metavar="PROJECT_ID",
        help="Filter by project UUID.",
    )
    lc.add_argument(
        "--item-id",
        default=None,
        metavar="ITEM_ID",
        help="Filter by item UUID.",
    )
    lc.set_defaults(func=_handle_list_comments)

    # --- update-comment ---
    uc = subparsers.add_parser("update-comment", help="Update a comment's content.")
    uc.add_argument("comment_id", help="UUID of the comment to update.")
    uc.add_argument(
        "--content-markdown",
        metavar="TEXT",
        default=None,
        help=(
            "New comment content in Markdown"
            " (overrides 'content_markdown' payload key when both given)."
        ),
    )
    uc_src = uc.add_mutually_exclusive_group()
    uc_src.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with comment fields (content_markdown key).",
    )
    uc_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    uc.set_defaults(func=_handle_update_comment)
