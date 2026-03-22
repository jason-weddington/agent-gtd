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
    VersionConflictError,
)
from agent_gtd.mcp_backend import LocalBackend, create_backend

_backend = create_backend()
_HTTP_MODE = not isinstance(_backend, LocalBackend)

_ENV_API_KEY = os.environ.get("AGENT_GTD_API_KEY", "")


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
    if _HTTP_MODE:
        return not _ENV_API_KEY
    # Local mode: check if local-mode SQLite (no auth needed)
    from agent_gtd.database import is_local_mode

    return not is_local_mode()


_show_login = _needs_login()

_instructions = (
    "GTD (Getting Things Done) task management system. "
    "Use item and note tools to manage work."
    if not _show_login
    else (
        "GTD (Getting Things Done) task management system. "
        "Call login first with a valid api_key to authenticate. "
        "Then use item and note tools to manage work."
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
        result = await _backend.login(_ENV_API_KEY, "mcp-agent")
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

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def switch_project(
        project_id: str,
        ctx: Context,
    ) -> dict[str, str]:
        """Switch the current project context.

        Requires prior login. Sets the active project for context,
        though most tools accept project_id as an explicit parameter.

        Args:
            project_id: ID of the project to switch to.
            ctx: MCP context (injected automatically).

        Returns:
            Confirmation with new project_id.
        """
        session = await _get_session(ctx)

        try:
            project = await _backend.get_project(session["user_id"], project_id)
        except NotFoundError:
            raise ToolError(f"Project not found: {project_id}") from None

        session["project_id"] = project_id
        await ctx.set_state("agent_session", session)

        return {
            "status": "switched",
            "project_id": project_id,
            "project_name": project["name"],
            "agent_name": session["agent_name"],
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
) -> dict[str, Any]:
    """Create a new project.

    Args:
        name: Project name.
        ctx: MCP context (injected automatically).
        description: Optional project description.
        area: Optional area/category.
        status: Project status (active, on_hold, completed, cancelled).
            Default: active.

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
    )


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
    status: str = "inbox",
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
        status: Item status. Default: inbox. Options: inbox,
            next_action, waiting_for, scheduled, someday_maybe,
            active, done, cancelled.
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
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_items(
    ctx: Context,
    status: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """List items, optionally filtered by project and/or status.

    Without project_id, lists items across all projects.

    Args:
        ctx: MCP context (injected automatically).
        status: Optional filter by item status.
        assigned_to: Optional filter by assignee.
        priority: Optional filter by priority.
        project_id: Optional project filter. Omit to list cross-project.

    Returns:
        List of item dicts.
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


# --- Entry point ---


def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")
