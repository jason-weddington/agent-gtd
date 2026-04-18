"""MCP server for Agent GTD — AI agent interface to the GTD system."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from agent_gtd.mcp_backend import LocalBackend, create_backend

_backend = create_backend()
_HTTP_MODE = not isinstance(_backend, LocalBackend)

_ENV_API_KEY = os.environ.get("AGENT_GTD_API_KEY", "")
_ENV_AGENT_NAME = os.environ.get("AGENT_GTD_AGENT_NAME", "mcp-agent")


@asynccontextmanager
async def mcp_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and tear down resources for standalone MCP mode."""
    if isinstance(_backend, LocalBackend):
        from agent_gtd.database import close_db, init_db

        await init_db()
        yield
        await close_db()
    else:
        yield
        await _backend.close()


def _needs_login() -> bool:
    """Whether the login tool should be registered."""
    if _ENV_API_KEY:
        return False
    if _HTTP_MODE:
        return True
    # Local mode: check if local-mode SQLite (no auth needed)
    from agent_gtd.database import is_local_mode

    return not is_local_mode()


_show_login = _needs_login()

# When login tools are hidden, auto-auth handles authentication transparently.
_instructions = (
    "GTD (Getting Things Done) task management system. "
    "Use item, note, and comment tools to manage work."
    if not _show_login
    else (
        "GTD (Getting Things Done) task management system. "
        "Call login first with a valid api_key to authenticate. "
        "Then use item, note, and comment tools to manage work."
    )
)

mcp = FastMCP(
    name="Agent GTD",
    instructions=_instructions,
    lifespan=mcp_lifespan,
)


# --- Session management ---


async def _get_session(ctx: Context) -> dict[str, str]:
    """Get the agent session from context state.

    Session is resolved in order:
    1. Existing session in context state (from prior login call).
    2. Local mode (SQLite): auto-creates a default session.
    3. AGENT_GTD_API_KEY env var: auto-authenticates on first call.
    4. Otherwise raises ToolError.
    """
    session: dict[str, str] | None = await ctx.get_state("agent_session")
    if session is not None:
        return session

    # Local SQLite mode — no auth needed
    if not _HTTP_MODE:
        from agent_gtd.database import is_local_mode

        if is_local_mode():
            from agent_gtd.database import LOCAL_USER_ID

            session = {
                "user_id": LOCAL_USER_ID,
                "agent_name": "local-agent",
            }
            await ctx.set_state("agent_session", session)
            return session

    # Auto-login via env var
    if _ENV_API_KEY:
        result = await _backend.login(_ENV_API_KEY, _ENV_AGENT_NAME)
        session = {
            "user_id": result["user_id"],
            "agent_name": result["agent_name"],
        }
        await ctx.set_state("agent_session", session)
        return session

    raise ToolError("Not logged in — call login first")


# --- Auth tools (when login is required) ---


if _show_login:

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def login(
        api_key: str,
        agent_name: str,
        ctx: Context,
    ) -> dict[str, str]:
        """Authenticate with an API key to start a session.

        Must be called before using any other tools. Validates the API key
        and establishes a session for the owning user.

        Args:
            api_key: API key (starts with agtd_).
            agent_name: Name of the agent (used for created_by, assigned_to).
            ctx: MCP context (injected automatically).

        Returns:
            Login confirmation with status, user email, and agent_name.
        """
        result = await _backend.login(api_key, agent_name)
        session = {
            "user_id": result["user_id"],
            "agent_name": agent_name,
        }
        await ctx.set_state("agent_session", session)

        return {
            "status": "logged_in",
            "user_email": result.get("email", ""),
            "agent_name": agent_name,
        }


# --- Project tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_projects(
    ctx: Context,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List projects for the current user.

    Args:
        ctx: MCP context (injected automatically).
        status: Optional filter by project status
            (active, completed, on_hold, cancelled).

    Returns:
        List of project dicts.
    """
    session = await _get_session(ctx)
    return await _backend.list_projects(session["user_id"], status=status)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_project(
    name: str,
    ctx: Context,
    description: str = "",
    area: str = "",
    status: str = "active",
    git_origin: str = "",
    kb_project_ref: str = "",
) -> dict[str, Any]:
    """Create a new project.

    Args:
        name: Project name.
        ctx: MCP context (injected automatically).
        description: Optional project description.
        area: Optional area/category.
        status: Project status (active, on_hold, completed, cancelled).
            Default: active.
        git_origin: Optional git remote URL for the project repo.
        kb_project_ref: Optional personal-kb project reference for
            agent context preflight.

    Returns:
        The created project dict.
    """
    session = await _get_session(ctx)
    return await _backend.create_project(
        session["user_id"],
        name=name,
        description=description,
        area=area,
        status=status,
        git_origin=git_origin,
        kb_project_ref=kb_project_ref,
    )


# --- Project member tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def share_project(
    project_id: str,
    email: str,
    ctx: Context,
) -> dict[str, Any]:
    """Share a project with a user by email. Caller must own the project.

    Idempotent: if the user is already a member, returns the existing
    membership without error.

    Args:
        project_id: ID of the project to share.
        email: Email address of the user to add.
        ctx: MCP context (injected automatically).

    Returns:
        Member summary dict: user_id, email, added_at.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.add_project_member(session["user_id"], project_id, email)
    except (NotFoundError, ValidationError) as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def unshare_project(
    project_id: str,
    email: str,
    ctx: Context,
) -> dict[str, Any]:
    """Remove a user from a project by email. Caller must own the project.

    No-op if the user is not currently a member.

    Args:
        project_id: ID of the project.
        email: Email address of the user to remove.
        ctx: MCP context (injected automatically).

    Returns:
        {"ok": true}
    """
    session = await _get_session(ctx)
    try:
        await _backend.remove_project_member(session["user_id"], project_id, email)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    return {"ok": True}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_project_members(
    project_id: str,
    ctx: Context,
) -> list[dict[str, Any]]:
    """List the members of a project.

    Accessible to the project owner and any member. Does not include
    the owner in the results.

    Args:
        project_id: ID of the project.
        ctx: MCP context (injected automatically).

    Returns:
        List of member dicts: user_id, email, added_at.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.list_project_members(session["user_id"], project_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Item tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def inbox_capture(
    title: str,
    ctx: Context,
) -> dict[str, Any]:
    """Quick capture an item to the inbox.

    Creates a new inbox item with the given title. Inbox items are always
    project-less (project_id=None) — they land in the user's global inbox
    before triage assigns them to a project.

    Args:
        title: Title of the item to capture.
        ctx: MCP context (injected automatically).

    Returns:
        The created item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.inbox_capture(
            session["user_id"],
            title,
            created_by=session["agent_name"],
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_item(
    title: str,
    ctx: Context,
    description: str = "",
    priority: str = "normal",
    status: str = "new",
    labels: list[str] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Create a new item.

    Items with status='inbox' are always project-less. For other statuses,
    pass project_id to assign to a project, or omit for a project-less item.

    Args:
        title: Title of the item.
        ctx: MCP context (injected automatically).
        description: Optional description.
        priority: Priority level (low, normal, high, urgent). Default: normal.
        status: Item status. Default: new. Options: inbox, new, ready,
            next_action, waiting_for, scheduled, someday_maybe,
            active, review, done, cancelled.
        labels: Optional list of labels/tags.
        project_id: Optional project to assign to. Ignored for inbox items.

    Returns:
        The created item dict.
    """
    session = await _get_session(ctx)

    # Inbox items are project-less (global capture bucket).
    effective_project_id = None if status == "inbox" else project_id

    try:
        return await _backend.create_item(
            session["user_id"],
            title=title,
            description=description,
            project_id=effective_project_id,
            status=status,
            priority=priority,
            created_by=session["agent_name"],
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_item(
    item_id: str,
    version: int,
    ctx: Context,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing item. Requires optimistic locking via version.

    Pass the item's current version number. The update will fail with a
    version conflict error if another update happened since you last read
    the item.

    Args:
        item_id: ID of the item to update.
        version: Current version of the item (required for optimistic locking).
        ctx: MCP context (injected automatically).
        title: New title (None = unchanged).
        description: New description (None = unchanged).
        status: New status (None = unchanged).
        priority: New priority (None = unchanged).
        assigned_to: New assignee (None = unchanged).
        labels: New labels (None = unchanged).

    Returns:
        The updated item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.update_item(
            session["user_id"],
            item_id,
            version=version,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except VersionConflictError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def complete_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Mark an item as done. Automatically sets completed_at timestamp.

    Args:
        item_id: ID of the item to complete.
        ctx: MCP context (injected automatically).

    Returns:
        The updated item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.complete_item(session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
async def delete_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Permanently delete an item.

    This action is irreversible. The item and all its associated data will be
    removed permanently.

    Args:
        item_id: ID of the item to delete.
        ctx: MCP context (injected automatically).

    Returns:
        Confirmation dict with status and item_id.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.delete_item(session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_items(
    ctx: Context,
    status: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """List items, optionally filtered by project and/or status.

    Without project_id, lists items across all projects and includes
    ``inbox_pending_count`` in the response.

    Args:
        ctx: MCP context (injected automatically).
        status: Optional filter by item status.
        assigned_to: Optional filter by assignee.
        priority: Optional filter by priority.
        project_id: Optional project filter. Omit to list cross-project.

    Returns:
        Dict with ``items`` list and optional ``inbox_pending_count``.
    """
    session = await _get_session(ctx)
    return await _backend.list_items(
        session["user_id"],
        status=status,
        project_id=project_id,
        priority=priority,
        assigned_to=assigned_to,
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def get_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Get a single item by ID.

    Args:
        item_id: ID of the item to retrieve.
        ctx: MCP context (injected automatically).

    Returns:
        The item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.get_item(session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def claim_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Claim an item for this agent (sets assigned_to = agent_name).

    Idempotent if the same agent re-claims. Fails if already claimed by
    a different agent.

    Args:
        item_id: ID of the item to claim.
        ctx: MCP context (injected automatically).

    Returns:
        The updated item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.claim_item(
            session["user_id"], item_id, session["agent_name"]
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except AlreadyClaimedError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def release_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Release an item (clear assigned_to).

    Args:
        item_id: ID of the item to release.
        ctx: MCP context (injected automatically).

    Returns:
        The updated item dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.release_item(session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Blocker tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_blocker(
    item_id: str,
    blocker_item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Mark item_id as blocked by blocker_item_id.

    Idempotent — if the relationship already exists, returns it silently.
    Both items must belong to the authenticated user.
    Fails if the relationship would create a dependency cycle.

    Args:
        item_id: ID of the item being blocked.
        blocker_item_id: ID of the item that blocks it.
        ctx: MCP context (injected automatically).

    Returns:
        The blocker as a BlockerSummary dict: id, title, status,
        project_id, project_name.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.add_blocker(session["user_id"], item_id, blocker_item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
async def remove_blocker(
    item_id: str,
    blocker_item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Remove a blocker relationship.

    No-op if the relationship doesn't exist.

    Args:
        item_id: ID of the blocked item.
        blocker_item_id: ID of the blocker to remove.
        ctx: MCP context (injected automatically).

    Returns:
        Confirmation dict with ok=True.
    """
    session = await _get_session(ctx)
    try:
        await _backend.remove_blocker(session["user_id"], item_id, blocker_item_id)
        return {"ok": True}
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_blockers(
    item_id: str,
    ctx: Context,
) -> list[dict[str, Any]]:
    """List the blockers for an item.

    Args:
        item_id: ID of the item whose blockers to list.
        ctx: MCP context (injected automatically).

    Returns:
        List of blocker dicts: id, title, status, project_id, project_name.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.list_blockers(session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Note tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_note(
    project_id: str,
    ctx: Context,
    title: str = "",
    content_markdown: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new note in a project.

    Args:
        project_id: Project to create the note in.
        ctx: MCP context (injected automatically).
        title: Note title.
        content_markdown: Note content in Markdown.
        labels: Optional list of labels/tags.

    Returns:
        The created note dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.create_note(
            session["user_id"],
            project_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_note(
    note_id: str,
    ctx: Context,
    title: str | None = None,
    content_markdown: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing note.

    Args:
        note_id: ID of the note to update.
        ctx: MCP context (injected automatically).
        title: New title (None = unchanged).
        content_markdown: New content (None = unchanged).
        labels: New labels (None = unchanged).

    Returns:
        The updated note dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.update_note(
            session["user_id"],
            note_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_notes(
    ctx: Context,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """List notes, optionally filtered by project.

    Without project_id, lists all notes across all projects.

    Args:
        ctx: MCP context (injected automatically).
        project_id: Optional project filter. Omit to list cross-project.

    Returns:
        List of note dicts.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.list_notes(session["user_id"], project_id=project_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def get_note(
    note_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Get a single note by ID.

    Args:
        note_id: ID of the note to retrieve.
        ctx: MCP context (injected automatically).

    Returns:
        The note dict.
    """
    session = await _get_session(ctx)

    try:
        return await _backend.get_note(session["user_id"], note_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Comment tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_comment(
    content_markdown: str,
    ctx: Context,
    project_id: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    """Add a comment to a project or item.

    Exactly one of project_id or item_id must be provided.

    Args:
        content_markdown: Comment content in Markdown.
        ctx: MCP context (injected automatically).
        project_id: Project to comment on (mutually exclusive with item_id).
        item_id: Item to comment on (mutually exclusive with project_id).

    Returns:
        The created comment dict.
    """
    if not project_id and not item_id:
        raise ToolError("Either project_id or item_id is required")
    if project_id and item_id:
        raise ToolError("Provide only one of project_id or item_id")

    session = await _get_session(ctx)
    try:
        return await _backend.create_comment(
            session["user_id"],
            project_id=project_id,
            item_id=item_id,
            content_markdown=content_markdown,
            created_by=session["agent_name"],
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_comments(
    ctx: Context,
    project_id: str | None = None,
    item_id: str | None = None,
) -> list[dict[str, Any]]:
    """List comments on a project or item.

    Without filters, lists all comments for the user.

    Args:
        ctx: MCP context (injected automatically).
        project_id: Filter by project.
        item_id: Filter by item.

    Returns:
        List of comment dicts, oldest first.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.list_comments(
            session["user_id"], project_id=project_id, item_id=item_id
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_comment(
    comment_id: str,
    ctx: Context,
    content_markdown: str | None = None,
) -> dict[str, Any]:
    """Update an existing comment.

    Args:
        comment_id: ID of the comment to update.
        ctx: MCP context (injected automatically).
        content_markdown: New content (None = unchanged).

    Returns:
        The updated comment dict.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.update_comment(
            session["user_id"],
            comment_id,
            content_markdown=content_markdown,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Dispatch tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def dispatch_item(
    item_id: str,
    ctx: Context,
    max_turns: int | None = None,
    mode: str = "build",
) -> dict[str, Any]:
    """Dispatch a headless Claude Code agent to work on an item.

    The item's project must have a git_origin configured. Creates a
    dispatch run that clones the repo, launches Claude Code, and
    reports back via comments.

    Args:
        item_id: ID of the item to dispatch.
        ctx: MCP context (injected automatically).
        max_turns: Maximum agent turns. Omit for server default.
        mode: Dispatch mode — "build" (implement and push branch) or
            "plan" (groom task: write acceptance criteria, identify files,
            ask clarifying questions). Default: "build".

    Returns:
        The created run dict with status and branch name.
    """
    from agent_gtd.exceptions import RunActiveError

    session = await _get_session(ctx)
    try:
        run = await _backend.dispatch_item(
            session["user_id"], item_id, max_turns=max_turns, mode=mode
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except RunActiveError as e:
        raise ToolError(e.detail) from None

    # Enqueue for background processing (local mode only — HTTP mode
    # enqueues server-side in the dispatch route)
    if isinstance(_backend, LocalBackend):
        try:
            from agent_gtd.dispatch_worker import enqueue_run

            enqueue_run(str(run["id"]))
        except AssertionError:
            pass  # Worker not started

    return run


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def get_run_status(
    run_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Get the status of a dispatch run.

    Args:
        run_id: ID of the dispatch run.
        ctx: MCP context (injected automatically).

    Returns:
        The run dict with current status.
    """
    session = await _get_session(ctx)
    try:
        return await _backend.get_run(session["user_id"], run_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_runs(
    ctx: Context,
    item_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List dispatch runs, optionally filtered.

    Args:
        ctx: MCP context (injected automatically).
        item_id: Optional filter by item.
        status: Optional filter by run status.

    Returns:
        List of run dicts.
    """
    session = await _get_session(ctx)
    return await _backend.list_runs(session["user_id"], item_id=item_id, status=status)


# --- Entry point ---


def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")
