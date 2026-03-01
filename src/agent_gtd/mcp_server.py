"""MCP server for Agent GTD — AI agent interface to the GTD system."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from agent_gtd.database import close_db, decode_json_list, get_db, init_db
from agent_gtd.exceptions import (
    AlreadyClaimedError,
    NotFoundError,
    VersionConflictError,
)
from agent_gtd.services import item_service, note_service, project_service


@asynccontextmanager
async def mcp_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and tear down the database for standalone MCP mode."""
    await init_db()
    yield
    await close_db()


mcp = FastMCP(
    name="Agent GTD",
    instructions=(
        "GTD (Getting Things Done) task management system. "
        "Call register_agent first with a valid user_id and project_id "
        "to start working. Then use item and note tools to manage work."
    ),
    lifespan=mcp_lifespan,
)


# --- Helpers ---


async def _get_session(ctx: Context) -> dict[str, str]:
    """Get the registered agent session from context state.

    Raises:
        ToolError: If the agent hasn't registered yet.
    """
    session: dict[str, str] | None = await ctx.get_state("agent_session")
    if session is None:
        raise ToolError("Agent not registered — call register_agent first")
    return session


def _format_item(row: dict[str, Any]) -> dict[str, Any]:
    """Format an item row for MCP tool output."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }


def _format_note(row: dict[str, Any]) -> dict[str, Any]:
    """Format a note row for MCP tool output."""
    return {
        **row,
        "labels": decode_json_list(str(row["labels"])),
    }


# --- Registration tools ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def register_agent(
    user_id: str,
    project_id: str,
    agent_name: str,
    ctx: Context,
) -> dict[str, str]:
    """Register an agent session for a user and project.

    Must be called before using project-scoped tools. Validates that
    the user and project exist and that the project belongs to the user.

    Args:
        user_id: ID of the user account to operate as.
        project_id: ID of the project to work in.
        agent_name: Name of the agent (used for created_by, assigned_to).
        ctx: MCP context (injected automatically).

    Returns:
        Registration confirmation with status, project_id, and agent_name.
    """
    db = await get_db()

    # Validate user exists
    row = await db.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
    if row is None:
        raise ToolError(f"User not found: {user_id}")

    # Validate project exists and belongs to user
    try:
        await project_service.get_project(db, user_id, project_id)
    except NotFoundError:
        raise ToolError(f"Project not found: {project_id}") from None

    await ctx.set_state(
        "agent_session",
        {
            "user_id": user_id,
            "project_id": project_id,
            "agent_name": agent_name,
        },
    )

    return {
        "status": "registered",
        "project_id": project_id,
        "agent_name": agent_name,
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def switch_project(
    project_id: str,
    ctx: Context,
) -> dict[str, str]:
    """Switch the registered agent to a different project.

    Requires prior registration via register_agent.

    Args:
        project_id: ID of the project to switch to.
        ctx: MCP context (injected automatically).

    Returns:
        Confirmation with new project_id.
    """
    session = await _get_session(ctx)
    db = await get_db()

    try:
        await project_service.get_project(db, session["user_id"], project_id)
    except NotFoundError:
        raise ToolError(f"Project not found: {project_id}") from None

    session["project_id"] = project_id
    await ctx.set_state("agent_session", session)

    return {
        "status": "switched",
        "project_id": project_id,
        "agent_name": session["agent_name"],
    }


# --- Discovery tools (no registration required) ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_projects(
    user_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List projects for a user.

    Does not require registration. Use this to discover available projects
    before calling register_agent.

    Args:
        user_id: ID of the user to list projects for.
        status: Optional filter by project status
            (active, completed, on_hold, cancelled).

    Returns:
        List of project dicts.
    """
    db = await get_db()
    return await project_service.list_projects(db, user_id, status=status)


# --- Item tools (project-scoped, require registration) ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def inbox_capture(
    title: str,
    ctx: Context,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Quick capture an item to the inbox.

    Creates a new inbox item with the given title. The created_by field
    is automatically set to the registered agent name.

    Args:
        title: Title of the item to capture.
        ctx: MCP context (injected automatically).
        project_id: Optional project ID override.
            If omitted, uses the registered project.

    Returns:
        The created item dict.
    """
    session = await _get_session(ctx)
    db = await get_db()
    effective_project_id = project_id or session["project_id"]

    try:
        row = await item_service.inbox_capture(
            db,
            session["user_id"],
            title,
            project_id=effective_project_id,
            created_by=session["agent_name"],
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


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
) -> dict[str, Any]:
    """Create a new item in the registered project.

    Args:
        title: Title of the item.
        ctx: MCP context (injected automatically).
        description: Optional description.
        priority: Priority level (low, normal, high, urgent). Default: normal.
        status: Item status. Default: inbox. Options: inbox,
            next_action, waiting_for, scheduled, someday_maybe,
            active, done, cancelled.
        labels: Optional list of labels/tags.

    Returns:
        The created item dict.
    """
    session = await _get_session(ctx)
    db = await get_db()

    try:
        row = await item_service.create_item(
            db,
            session["user_id"],
            title=title,
            description=description,
            project_id=session["project_id"],
            status=status,
            priority=priority,
            created_by=session["agent_name"],
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


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
    db = await get_db()

    try:
        row = await item_service.update_item(
            db,
            session["user_id"],
            item_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            labels=labels,
            version=version,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except VersionConflictError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


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
    db = await get_db()

    try:
        row = await item_service.complete_item(db, session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_items(
    ctx: Context,
    status: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    """List items in the registered project.

    Args:
        ctx: MCP context (injected automatically).
        status: Optional filter by item status.
        assigned_to: Optional filter by assignee.
        priority: Optional filter by priority.

    Returns:
        List of item dicts.
    """
    session = await _get_session(ctx)
    db = await get_db()

    rows = await item_service.list_items(
        db,
        session["user_id"],
        status=status,
        project_id=session["project_id"],
        priority=priority,
        assigned_to=assigned_to,
    )
    return [_format_item(r) for r in rows]


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
    db = await get_db()

    try:
        row = await item_service.get_item(db, session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


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
    db = await get_db()

    try:
        row = await item_service.claim_item(
            db, session["user_id"], item_id, session["agent_name"]
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except AlreadyClaimedError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


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
    db = await get_db()

    try:
        row = await item_service.release_item(db, session["user_id"], item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_item(row)


# --- Note tools (project-scoped, require registration) ---


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def add_note(
    ctx: Context,
    title: str = "",
    content_markdown: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new note in the registered project.

    Args:
        ctx: MCP context (injected automatically).
        title: Note title.
        content_markdown: Note content in Markdown.
        labels: Optional list of labels/tags.

    Returns:
        The created note dict.
    """
    session = await _get_session(ctx)
    db = await get_db()

    try:
        row = await note_service.create_note(
            db,
            session["user_id"],
            session["project_id"],
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_note(row)


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
    db = await get_db()

    try:
        row = await note_service.update_note(
            db,
            session["user_id"],
            note_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_note(row)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_notes(
    ctx: Context,
) -> list[dict[str, Any]]:
    """List notes in the registered project.

    Args:
        ctx: MCP context (injected automatically).

    Returns:
        List of note dicts.
    """
    session = await _get_session(ctx)
    db = await get_db()

    try:
        rows = await note_service.list_project_notes(
            db, session["user_id"], session["project_id"]
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return [_format_note(r) for r in rows]


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
    db = await get_db()

    try:
        row = await note_service.get_note(db, session["user_id"], note_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None

    return _format_note(row)
