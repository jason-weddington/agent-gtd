"""MCP server for Agent GTD — AI agent interface to the GTD system."""

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from mcp.types import ToolAnnotations

from agent_gtd.client_config import resolve_client_config
from agent_gtd.dispatch_constants import (
    MAX_TIMEOUT_MINUTES,
    MAX_TURNS,
    MIN_TIMEOUT_MINUTES,
    MIN_TURNS,
)
from agent_gtd.exceptions import (
    BlockersUnresolvedError,
    LegalityContractError,
    NotFoundError,
    PlanEngineOverrideError,
    RolloutItemLockedError,
    ValidationError,
    VersionConflictError,
)
from agent_gtd.identity import compute_lead_attribution
from agent_gtd.mcp_backend import LocalBackend, McpBackend, create_backend

logger = logging.getLogger(__name__)

_backend = create_backend()
_HTTP_MODE = not isinstance(_backend, LocalBackend)

_ENV_API_KEY = resolve_client_config()[1]
_ENV_AGENT_NAME: str | None = os.environ.get("AGENT_GTD_AGENT_NAME")


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

_HTTP_INSTRUCTIONS = (
    "GTD (Getting Things Done) task management system. "
    "Use item, note, and comment tools to manage work."
)

# --- Tool registry ---
#
# Every tool is a plain module-level async function.  ``_tool`` records it in
# ``_TOOL_REGISTRY``; ``create_mcp_server`` registers the registry on a fresh
# FastMCP instance per transport (stdio below, streamable HTTP in mcp_http).

_F = TypeVar("_F", bound=Callable[..., Any])

_TOOL_REGISTRY: list[tuple[Callable[..., Any], ToolAnnotations]] = []


def _tool(annotations: ToolAnnotations) -> Callable[[_F], _F]:
    """Record *fn* in the tool registry and return it unchanged."""

    def decorator(fn: _F) -> _F:
        _TOOL_REGISTRY.append((fn, annotations))
        return fn

    return decorator


@dataclass(frozen=True)
class CallContext:
    """The principal a single tool call runs as."""

    user_id: str
    agent_name: str
    backend: McpBackend
    run_id: str | None = None
    run_mode: str | None = None


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
                "agent_name": (
                    _ENV_AGENT_NAME or compute_lead_attribution(LOCAL_USER_ID)
                ),
            }
            await ctx.set_state("agent_session", session)
            return session

    # Auto-login via env var
    if _ENV_API_KEY:
        result = await _backend.login(_ENV_API_KEY, _ENV_AGENT_NAME or "")
        agent_name = _ENV_AGENT_NAME or compute_lead_attribution(result["user_id"])
        logger.debug(
            "_get_session auto-login: _ENV_AGENT_NAME=%r resolved agent_name=%r",
            _ENV_AGENT_NAME,
            agent_name,
        )
        session = {
            "user_id": result["user_id"],
            "agent_name": agent_name,
        }
        await ctx.set_state("agent_session", session)
        return session

    raise ToolError("Not logged in — call login first")


async def _resolve_call(ctx: Context) -> CallContext:
    """Resolve the principal for one tool call.

    On the module-level stdio server the session comes from ``_get_session``.
    On any other server (the board's ``/mcp`` endpoint) the principal was put
    on the request by ``McpEndpoint`` after bearer auth; if it is missing the
    call fails closed — there is no fallback to env vars or the local user.
    """
    if ctx.fastmcp is mcp:
        session = await _get_session(ctx)
        return CallContext(
            user_id=session["user_id"],
            agent_name=session["agent_name"],
            backend=_backend,
        )
    call: object = None
    try:
        request = get_http_request()
    except RuntimeError:
        pass
    else:
        call = getattr(request.state, "agtd_mcp_call", None)
    if not isinstance(call, CallContext):
        logger.error(
            "mcp tool call without authenticated principal",
            extra={
                "event": "mcp_http.principal_missing",
                "server": ctx.fastmcp.name,
            },
        )
        raise ToolError("MCP tool call reached without an authenticated principal")
    return call


# --- Auth tools (when login is required) ---


_LOGIN_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


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
    # Guard against empty agent_name — fall back to lead attribution so that
    # session["agent_name"] is never "" (which would propagate as created_by=""
    # and trigger the human fallback on the server).
    resolved_name = agent_name or compute_lead_attribution(result["user_id"])
    logger.debug(
        "login tool: agent_name=%r resolved_name=%r user_id=%r",
        agent_name,
        resolved_name,
        result["user_id"],
    )
    session = {
        "user_id": result["user_id"],
        "agent_name": resolved_name,
    }
    await ctx.set_state("agent_session", session)

    return {
        "status": "logged_in",
        "user_email": result.get("email", ""),
        "agent_name": resolved_name,
    }


def _enqueue_if_local(call: CallContext, run: dict[str, Any], tool: str) -> None:
    """Hand a freshly created run to the in-process dispatch worker.

    Only in-process backends enqueue (HttpBackend's REST route does it
    server-side).  A worker that is not running raises AssertionError; on the
    board that is worth a WARNING, on a stdio LocalBackend it stays silent.
    """
    if not isinstance(call.backend, LocalBackend):
        return
    from agent_gtd import dispatch_worker

    try:
        dispatch_worker.enqueue_run(str(run["id"]))
    except AssertionError:
        from agent_gtd.mcp_http import BoardBackend

        if isinstance(call.backend, BoardBackend):
            logger.warning(
                "mcp-http enqueue skipped: dispatch worker not running",
                extra={
                    "event": "mcp_http.enqueue_failed",
                    "run_id": str(run["id"]),
                    "tool": tool,
                },
            )


# --- Project tools ---


@_tool(
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
    call = await _resolve_call(ctx)
    return await call.backend.list_projects(call.user_id, status=status)


@_tool(
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
    repo_mode: str = "monorepo",
    workspace_repos: list[str] | None = None,
    dispatch_max_turns: int | None = None,
    dispatch_timeout_minutes: int | None = None,
    plan_dispatch_agent: str | None = None,
    build_dispatch_agent: str | None = None,
    gate_command: str | None = None,
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
        repo_mode: Repository mode — 'monorepo' (default) or 'workspace'.
            Use 'workspace' when the project spans multiple git repositories.
        workspace_repos: Ordered list of git clone URLs for workspace mode.
            Required when repo_mode='workspace'; ignored for monorepo.
        dispatch_max_turns: Optional override for max agent turns per dispatch
            run. Must be between 10 and 500. None = use server default.
        dispatch_timeout_minutes: Optional override for dispatch run timeout in
            minutes. Must be between 5 and 480. None = use server default.
        plan_dispatch_agent: Optional override for the agent name used in plan
            mode dispatches. None = use server default.
        build_dispatch_agent: Optional override for the agent name used in
            build mode dispatches. None = use server default.
        gate_command: Shell command that is the project's quality gate, run
            from the repo root (the workspace root for workspace projects);
            exit 0 = green. Dispatch runs it after each build run that
            pushes a branch and marks the run failed if it exits non-zero.
            None = not set.

    Returns:
        The created project dict.
    """
    if dispatch_max_turns is not None and not (
        MIN_TURNS <= dispatch_max_turns <= MAX_TURNS
    ):
        raise ToolError(
            f"dispatch_max_turns must be between {MIN_TURNS} and {MAX_TURNS}"
        )
    if dispatch_timeout_minutes is not None and not (
        MIN_TIMEOUT_MINUTES <= dispatch_timeout_minutes <= MAX_TIMEOUT_MINUTES
    ):
        raise ToolError(
            f"dispatch_timeout_minutes must be between "
            f"{MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}"
        )
    call = await _resolve_call(ctx)
    try:
        return await call.backend.create_project(
            call.user_id,
            name=name,
            description=description,
            area=area,
            status=status,
            git_origin=git_origin,
            kb_project_ref=kb_project_ref,
            repo_mode=repo_mode,
            workspace_repos=workspace_repos,
            dispatch_max_turns=dispatch_max_turns,
            dispatch_timeout_minutes=dispatch_timeout_minutes,
            plan_dispatch_agent=plan_dispatch_agent,
            build_dispatch_agent=build_dispatch_agent,
            gate_command=gate_command,
        )
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_project(
    project_id: str,
    ctx: Context,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    area: str | None = None,
    git_origin: str | None = None,
    kb_project_ref: str | None = None,
    repo_mode: str | None = None,
    workspace_repos: list[str] | None = None,
    dispatch_max_turns: int | None = None,
    clear_dispatch_max_turns: bool = False,
    dispatch_timeout_minutes: int | None = None,
    clear_dispatch_timeout_minutes: bool = False,
    plan_dispatch_agent: str | None = None,
    clear_plan_dispatch_agent: bool = False,
    build_dispatch_agent: str | None = None,
    clear_build_dispatch_agent: bool = False,
    gate_command: str | None = None,
    clear_gate_command: bool = False,
    required_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing project. None on any field = unchanged.

    Dispatch override fields use a value/clear pattern for nullable columns:
    pass a value to set it; set the corresponding clear_* flag to True
    (with the value param left None) to reset it to the server default;
    omit both to leave the current value unchanged.

    Only the project owner may change dispatch-only fields
    (dispatch_max_turns, dispatch_timeout_minutes, plan_dispatch_agent,
    build_dispatch_agent).

    Args:
        project_id: ID of the project to update.
        ctx: MCP context (injected automatically).
        name: New name (None = unchanged).
        description: New description (None = unchanged).
        status: New status (None = unchanged).
            Valid values: active, on_hold, completed, cancelled.
        area: New area/category (None = unchanged).
        git_origin: New git remote URL (None = unchanged).
        kb_project_ref: New personal-kb project reference (None = unchanged).
        repo_mode: New repository mode — 'monorepo' or 'workspace'
            (None = unchanged).
        workspace_repos: New ordered list of git clone URLs for workspace mode
            (None = unchanged).
        dispatch_max_turns: Override max agent turns (10-500). None = unchanged.
        clear_dispatch_max_turns: Set True to reset dispatch_max_turns to NULL
            (use server default). Mutually exclusive with dispatch_max_turns.
        dispatch_timeout_minutes: Override dispatch timeout in minutes (5-480).
            None = unchanged.
        clear_dispatch_timeout_minutes: Set True to reset
            dispatch_timeout_minutes to NULL. Mutually exclusive with
            dispatch_timeout_minutes.
        plan_dispatch_agent: Override agent name for plan-mode dispatches.
            None = unchanged.
        clear_plan_dispatch_agent: Set True to reset plan_dispatch_agent to
            NULL. Mutually exclusive with plan_dispatch_agent.
        build_dispatch_agent: Override agent name for build-mode dispatches.
            None = unchanged.
        clear_build_dispatch_agent: Set True to reset build_dispatch_agent to
            NULL. Mutually exclusive with build_dispatch_agent.
        gate_command: Shell command that is the project's quality gate, run
            from the repo root (the workspace root for workspace projects);
            exit 0 = green. Dispatch runs it after each build run that
            pushes a branch and marks the run failed if it exits non-zero.
            None = unchanged.
        clear_gate_command: Set True to reset gate_command to NULL.
            Mutually exclusive with gate_command.
        required_labels: Capability labels a dispatch host must carry to take
            any run in this project (unioned with each item's own
            required_labels at routing time). None = unchanged, [] = clear,
            non-empty = replace the full list.

    Returns:
        The updated project dict.
    """
    if dispatch_max_turns is not None and not (
        MIN_TURNS <= dispatch_max_turns <= MAX_TURNS
    ):
        raise ToolError(
            f"dispatch_max_turns must be between {MIN_TURNS} and {MAX_TURNS}"
        )
    if dispatch_timeout_minutes is not None and not (
        MIN_TIMEOUT_MINUTES <= dispatch_timeout_minutes <= MAX_TIMEOUT_MINUTES
    ):
        raise ToolError(
            f"dispatch_timeout_minutes must be between "
            f"{MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}"
        )

    call = await _resolve_call(ctx)

    try:
        return await call.backend.update_project(
            call.user_id,
            project_id,
            name=name,
            description=description,
            status=status,
            area=area,
            git_origin=git_origin,
            kb_project_ref=kb_project_ref,
            repo_mode=repo_mode,
            workspace_repos=workspace_repos,
            dispatch_max_turns=dispatch_max_turns,
            clear_dispatch_max_turns=clear_dispatch_max_turns,
            dispatch_timeout_minutes=dispatch_timeout_minutes,
            clear_dispatch_timeout_minutes=clear_dispatch_timeout_minutes,
            plan_dispatch_agent=plan_dispatch_agent,
            clear_plan_dispatch_agent=clear_plan_dispatch_agent,
            build_dispatch_agent=build_dispatch_agent,
            clear_build_dispatch_agent=clear_build_dispatch_agent,
            gate_command=gate_command,
            clear_gate_command=clear_gate_command,
            required_labels=required_labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


# --- Project member tools ---


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.add_project_member(call.user_id, project_id, email)
    except (NotFoundError, ValidationError) as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        await call.backend.remove_project_member(call.user_id, project_id, email)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    return {"ok": True}


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.list_project_members(call.user_id, project_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Item tools ---


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.inbox_capture(
            call.user_id,
            title,
            created_by=call.agent_name,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    due_date: str | None = None,
    build_engine: Literal[
        "claude-code",
        "claude-code-ollama",
        "claude-code-glm",
        "claude-code-sonnet",
        "claude-code-haiku",
        "kiro",
        "talos-haiku",
        "talos-sonnet",
        "talos-opus",
        "talos-qwen",
        "talos-glm",
        "talos-glm-flash",
        "",
    ]
    | None = None,
    commit_type: Literal[
        "feat", "fix", "perf", "refactor", "test", "docs", "chore", ""
    ] = "",
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
        due_date: Optional due date in YYYY-MM-DD format. Default: None (no due date).
        build_engine: Optional build engine preference (applies to build- and
            plan-mode dispatch; talos-* engines apply to build mode only —
            a plan dispatch on a talos-* item falls back to the global engine).
            - None (default) → no engine set (inherits global default)
            - Empty string "" → no engine set (inherits global default)
            - "claude-code" → Anthropic Claude Code
            - "claude-code-ollama" → Claude Code via local Ollama
            - "claude-code-glm" → Claude Code driving glm-5.3 via Ollama Cloud
            - "claude-code-sonnet" → Claude Code Sonnet model
            - "claude-code-haiku" → Claude Code Haiku model
            - "kiro" → Kiro engine
            - "talos-haiku"/"talos-sonnet"/"talos-opus"/"talos-qwen"/"talos-glm"
              → Talos engine variants (build mode only)
            - "talos-glm-flash" → Talos engine via glm-5.3-flash:cloud (Ollama
              Cloud) (build mode only)
        commit_type: Groomed conventional-commit type the item's squash
            commit will carry: one of "feat", "fix", "perf", "refactor",
            "test", "docs", "chore". Default "" (unset). plan_rollout
            requires it on every item.

    Returns:
        The created item dict.
    """
    call = await _resolve_call(ctx)

    # Inbox items are project-less (global capture bucket).
    effective_project_id = None if status == "inbox" else project_id

    try:
        return await call.backend.create_item(
            call.user_id,
            title=title,
            description=description,
            project_id=effective_project_id,
            status=status,
            priority=priority,
            created_by=call.agent_name,
            labels=labels,
            due_date=due_date,
            build_engine=build_engine,
            commit_type=commit_type,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_item(
    item_id: str,
    version: int,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    labels: list[str] | None = None,
    due_date: str | None = None,
    build_engine: Literal[
        "claude-code",
        "claude-code-ollama",
        "claude-code-glm",
        "claude-code-sonnet",
        "claude-code-haiku",
        "kiro",
        "talos-haiku",
        "talos-sonnet",
        "talos-opus",
        "talos-qwen",
        "talos-glm",
        "talos-glm-flash",
        "",
    ]
    | None = None,
    acceptance_criteria: list[str] | None = None,
    files_to_modify: list[dict[str, Any]] | None = None,
    scope_out: list[str] | None = None,
    project_id: str | None = None,
    commit_type: Literal["feat", "fix", "perf", "refactor", "test", "docs", "chore", ""]
    | None = None,
    required_labels: list[str] | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Update an existing item. Requires optimistic locking via version.

    Pass the item's current version number. The update will fail with a
    version conflict error if another update happened since you last read
    the item.

    Args:
        item_id: ID of the item to update.
        version: Current version of the item (required for optimistic locking).
        title: New title (None = unchanged).
        description: New description (None = unchanged).
        status: New status (None = unchanged).
        priority: New priority (None = unchanged).
        assigned_to: New assignee (None = unchanged).
        labels: New labels (None = unchanged).
        due_date: New due date in YYYY-MM-DD format.
            - None (default) → unchanged
            - Empty string "" → clear the due date
            - Non-empty string → set to that date
        build_engine: New build engine preference (applies to build- and
            plan-mode dispatch; talos-* engines apply to build mode only —
            a plan dispatch on a talos-* item falls back to the global engine).
            - None (default) → unchanged
            - Empty string "" → clear the preference (use global default)
            - "claude-code" → Anthropic Claude Code
            - "claude-code-ollama" → Claude Code via local Ollama
            - "claude-code-glm" → Claude Code driving glm-5.3 via Ollama Cloud
            - "claude-code-sonnet" → Claude Code Sonnet model
            - "claude-code-haiku" → Claude Code Haiku model
            - "kiro" → Kiro engine
            - "talos-glm-flash" → Talos engine via glm-5.3-flash:cloud (Ollama
              Cloud) (build mode only)
        acceptance_criteria: Structured acceptance criteria list (None = unchanged,
            empty list [] = clear, non-empty list = set).
        files_to_modify: Structured files-to-modify list of dicts with "path" and
            "change" keys (None = unchanged, empty list [] = clear, non-empty = set).
        scope_out: Structured scope-out list (None = unchanged, empty list [] = clear,
            non-empty list = set).
        project_id: Move item to a different project (or detach from project).
            - None (default) → unchanged
            - Empty string "" → detach from project (set project_id to null)
            - Non-empty UUID string → move to that project
        commit_type: Groomed conventional-commit type the item's squash
            commit will carry: one of "feat", "fix", "perf", "refactor",
            "test", "docs", "chore". plan_rollout requires it on every item.
            - None (default) → unchanged
            - Empty string "" → clear it (unset)
        required_labels: Capability labels a dispatch host must carry to take
            this item's runs (unioned with the project's required_labels at
            routing time). None = unchanged, [] = clear, non-empty = replace
            the full list.
        ctx: MCP context (injected automatically).

    Returns:
        The updated item dict.
    """
    # Defensive guard: if item_id is empty the call was malformed (e.g. harness
    # sent an empty-string value instead of a UUID).  Raise a clear ToolError
    # rather than letting the backend emit an opaque not-found or DB error.
    if not item_id:
        raise ToolError(
            "update_item called with empty item_id — tool-call body may be malformed"
        )

    call = await _resolve_call(ctx)

    # Translate MCP due_date sentinel into (due_date, due_date_set) pair for backend.
    # None means "don't touch it"; "" means "clear it"; date string means "set it".
    if due_date is None:
        backend_due_date: str | None = None
        due_date_set = False
    elif due_date == "":
        backend_due_date = None
        due_date_set = True
    else:
        backend_due_date = due_date
        due_date_set = True

    # Translate MCP build_engine sentinel into (build_engine, build_engine_set) pair.
    if build_engine is None:
        backend_build_engine: str | None = None
        build_engine_set = False
    elif build_engine == "":
        backend_build_engine = None
        build_engine_set = True
    else:
        backend_build_engine = build_engine
        build_engine_set = True

    # Translate MCP project_id sentinel into (project_id_val, project_id_set) pair.
    # None means "don't touch it"; "" means "detach (set to null)"; UUID means "move".
    if project_id is None:
        backend_project_id: str | None = None
        project_id_set = False
    elif project_id == "":
        backend_project_id = None
        project_id_set = True
    else:
        backend_project_id = project_id
        project_id_set = True

    try:
        return await call.backend.update_item(
            call.user_id,
            item_id,
            version=version,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            labels=labels,
            due_date=backend_due_date,
            due_date_set=due_date_set,
            build_engine=backend_build_engine,
            build_engine_set=build_engine_set,
            acceptance_criteria=acceptance_criteria,
            files_to_modify=files_to_modify,
            scope_out=scope_out,
            project_id=backend_project_id,
            project_id_set=project_id_set,
            commit_type=commit_type,
            required_labels=required_labels,
            actor_run_id=call.run_id,
            actor_run_mode=call.run_mode,
        )
    except PlanEngineOverrideError as e:
        logger.warning(
            "plan-mode run refused build_engine change on item %s",
            item_id,
            extra={
                "event": "mcp_http.plan_engine_override_refused",
                "item_id": item_id,
            },
        )
        raise ToolError(e.detail) from None
    except BlockersUnresolvedError as e:
        raise ToolError(e.detail) from None
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except RolloutItemLockedError as e:
        raise ToolError(e.detail) from None
    except VersionConflictError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.complete_item(call.user_id, item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.delete_item(call.user_id, item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_items(
    ctx: Context,
    status: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    detail: bool = False,
) -> dict[str, Any]:
    """List items, optionally filtered by project and/or status.

    By default, returns a **compact** list intended for scanning and finding
    items.  Each compact item has exactly 17 keys: id, title, status,
    priority, build_engine, commit_type, project_id, project_name, project_repo_mode,
    labels, assigned_to, created_by, created_at, updated_at, ac_count,
    files_count, and description_snippet.  Heavy fields (description,
    acceptance_criteria, files_to_modify, blockers, etc.) are omitted to
    avoid context blowout.

    ``project_repo_mode`` carries the parent project's repo_mode string
    (``"monorepo"`` or ``"workspace"``) so groom-time callers can see the
    workspace context without a second lookup; it is ``null`` when the
    item has no project or the project is not accessible.  Agents should
    check it before scoping cross-repo work.

    To read an item's full body (description, acceptance_criteria,
    files_to_modify), either:
    - Call ``get_item`` with the item's UUID (recommended — always
      full-fidelity), or
    - Pass ``detail=True`` to this tool to receive full rows for all
      matched items (use sparingly on large lists).

    Without project_id, lists items across all projects and includes
    ``inbox_pending_count`` in the response.

    Args:
        ctx: MCP context (injected automatically).
        status: Optional filter by item status.
        assigned_to: Optional filter by assignee.
        priority: Optional filter by priority.
        project_id: Optional project filter. Omit to list cross-project.
        detail: If True, return full item rows including description,
            acceptance_criteria, and files_to_modify.  Default False
            (compact list).

    Returns:
        Dict with ``items`` list and optional ``inbox_pending_count``.
    """
    call = await _resolve_call(ctx)
    return await call.backend.list_items(
        call.user_id,
        status=status,
        project_id=project_id,
        priority=priority,
        assigned_to=assigned_to,
        detail=detail,
    )


@_tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def get_item(
    item_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Get a single item by ID.

    The returned dict always carries ``project_repo_mode`` (str|null): the
    parent project's repo_mode when the item belongs to an accessible
    project, else ``null``.  When ``project_repo_mode == "workspace"``, the
    dict additionally carries ``workspace_repos`` — the ordered list of
    repo URLs that a workspace build agent receives cloned side by side.
    Groom-time callers should check these before scoping cross-repo work;
    the key is absent for monorepo items and project-less items.

    Args:
        item_id: ID of the item to retrieve.
        ctx: MCP context (injected automatically).

    Returns:
        The item dict.
    """
    call = await _resolve_call(ctx)

    try:
        return await call.backend.get_item(call.user_id, item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Blocker tools ---


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.add_blocker(call.user_id, item_id, blocker_item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        await call.backend.remove_blocker(call.user_id, item_id, blocker_item_id)
        return {"ok": True}
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.list_blockers(call.user_id, item_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Note tools ---


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.create_note(
            call.user_id,
            project_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.update_note(
            call.user_id,
            note_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
async def delete_note(
    note_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Permanently delete a note.

    This action is irreversible. The note and all its content will be removed.

    Args:
        note_id: ID of the note to delete.
        ctx: MCP context (injected automatically).

    Returns:
        Confirmation dict with deleted status and note_id.
    """
    call = await _resolve_call(ctx)

    try:
        return await call.backend.delete_note(call.user_id, note_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.list_notes(call.user_id, project_id=project_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)

    try:
        return await call.backend.get_note(call.user_id, note_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Comment tools ---


@_tool(
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

    call = await _resolve_call(ctx)
    try:
        return await call.backend.create_comment(
            call.user_id,
            project_id=project_id,
            item_id=item_id,
            content_markdown=content_markdown,
            created_by=call.agent_name,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.list_comments(
            call.user_id, project_id=project_id, item_id=item_id
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    try:
        return await call.backend.update_comment(
            call.user_id,
            comment_id,
            content_markdown=content_markdown,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None


# --- Dispatch tools ---


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def dispatch_item(
    item_id: str,
    ctx: Context,
    max_turns: int | None = None,
    mode: Literal["build", "plan", "manage"] = "build",
    rollout_id: str | None = None,
    dispatch_host_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a headless Claude Code agent to work on an item.

    The item's project must have a git_origin configured (monorepo projects) or a
    non-empty repos list (workspace projects, which are cloned as a multi-repo
    workspace). Creates a
    dispatch run that clones the repo, launches Claude Code, and
    reports back via comments.

    Args:
        item_id: ID of the item to dispatch.
        ctx: MCP context (injected automatically).
        max_turns: Maximum agent turns. Omit for server default.
        mode: Dispatch mode — "build" (implement and push branch),
            "plan" (groom task: write acceptance criteria, identify files,
            ask clarifying questions), or "manage" (launch a wave manager
            agent that drives an autonomous wave run). Default: "build".
        rollout_id: Required when mode="manage". The rollout ID that this
            manager agent will drive. The rollout must be in status="pending".
        dispatch_host_id: Optional host UUID from /api/settings/dispatch/hosts.
            Set to pin this dispatch to a specific host (use for verification,
            debugging, or cache affinity). Omit to let the router pick
            automatically based on engine + agent availability and capacity.

    Returns:
        The created run dict with status and branch name.
    """
    from fastapi import HTTPException

    from agent_gtd.exceptions import (
        RolloutItemLockedError,
        RunActiveError,
        ValidationError,
    )

    if mode == "manage" and rollout_id is None:
        raise ToolError("rollout_id is required when mode='manage'")

    call = await _resolve_call(ctx)
    try:
        run = await call.backend.dispatch_item(
            call.user_id,
            item_id,
            max_turns=max_turns,
            mode=mode,
            rollout_id=rollout_id,
            dispatch_host_id=dispatch_host_id,
        )
    except HTTPException as exc:
        # Only the board's BoardBackend raises this (REST dispatch pre-flight).
        logger.info(
            "mcp-http dispatch refused",
            extra={
                "event": "mcp_http.dispatch_refused",
                "tool": "dispatch_item",
                "item_id": item_id,
                "dispatch_host_id": dispatch_host_id,
                "status": exc.status_code,
                "detail": exc.detail,
            },
        )
        raise ToolError(str(exc.detail)) from None
    except RolloutItemLockedError as e:
        raise ToolError(e.detail) from None
    except BlockersUnresolvedError as e:
        raise ToolError(e.detail) from None
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except RunActiveError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None

    # Enqueue for background processing (in-process backends only — HTTP
    # mode enqueues server-side in the dispatch route)
    _enqueue_if_local(call, run, "dispatch_item")
    return run


@_tool(
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
        The run dict with current status, including ``remote_run_id`` — the
        DISPATCH-side run id (empty string for pre-migration rows or when the
        run was never dispatched remotely). Every surface a lead sees when
        investigating a run — this tool, ``agent-gtd run-status``,
        ``agent-gtd list-runs`` — carries this id, since a run's evidence
        directory on the dispatch host is keyed by it, not by this
        agent_gtd-side run id.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.get_run(call.user_id, run_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True
    ),
)
async def cancel_run(
    run_id: str,
    ctx: Context,
    force: bool = False,
) -> dict[str, Any]:
    """Cancel a single dispatched run.

    An active run is marked cancelled and the dispatch host running it is
    asked to stop it; a run that never reached a host is just marked
    cancelled. Cancelling an already-finished run is a no-op that returns its
    current status. A rollout's manage/loop run, and child build runs of a
    rollout that is still live (pending/planning/running), are refused (use
    cancel_rollout or halt_rollout) unless ``force`` is set. A child build
    run of a rollout that is already terminal (halted/cancelled/failed/done/
    completed) — e.g. one a halt left running — is cancelled without
    ``force``. The cancel is forwarded to the host using the host's own run
    id (``remote_run_id``), so pass the board run id here.

    With ``force=True`` a run that belongs to a rollout is cancelled anyway
    and ``'forced by operator'`` is recorded on it; the rollout's own status
    is not changed. Force-cancelling a rollout's loop run stops that loop on
    its dispatch host, leaving the rollout running without a driver — follow
    it with cancel-rollout or halt-rollout, because otherwise the next
    restart of that host resumes the loop.

    Args:
        run_id: ID of the dispatch run.
        ctx: MCP context (injected automatically).
        force: Cancel a rollout-owned run anyway, recording
            'forced by operator'; the rollout's own status is not changed.

    Returns:
        The run dict with its current status.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.cancel_run(call.user_id, run_id, force=force)
    except (NotFoundError, ValidationError) as e:
        raise ToolError(e.detail) from None


@_tool(
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
    call = await _resolve_call(ctx)
    return await call.backend.list_runs(call.user_id, item_id=item_id, status=status)


@_tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def list_dispatch_hosts(
    ctx: Context,
) -> list[dict[str, Any]]:
    """List the caller's registered dispatch hosts.

    Use this to discover the host UUID needed to pin a dispatch to a specific
    host via ``dispatch_item(dispatch_host_id=...)``. The ``id`` field of each
    returned host is the value to pass as ``dispatch_host_id``.

    A non-null ``drain_reason`` means the host is currently out of rotation
    (drained) and the string says why — do not dispatch to it and do not
    expect work on it to start; hold until it is undrained.

    ``capability_labels`` is the operator-set list of labels the host
    carries; work whose effective required_labels are not a subset of it is
    never routed there.

    No secret material is returned — only ``id``, ``label``, ``url``,
    ``capability_labels``, and ``drain_reason``.

    Args:
        ctx: MCP context (injected automatically).

    Returns:
        List of host dicts, each with keys ``id``, ``label``, ``url``,
        ``capability_labels``, and ``drain_reason``.
    """
    call = await _resolve_call(ctx)
    return await call.backend.list_dispatch_hosts(call.user_id)


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def set_dispatch_host_labels(
    host: str,
    labels: list[str],
    ctx: Context,
) -> dict[str, Any]:
    """Replace a dispatch host's capability labels.

    Capability labels are operator-set facts about what the host can do
    (installed toolchain, local data). Work whose effective required_labels
    (project plus item) are not a subset of a host's labels is never routed
    to that host.

    Args:
        host: The host to update — its id, its exact label, or a substring of
            its URL that matches exactly one host.
        labels: The full replacement label list (normalized to lowercase,
            deduplicated). An empty list clears all labels.
        ctx: MCP context (injected automatically).

    Returns:
        The updated host dict with keys ``id``, ``label``, ``url``,
        ``capability_labels``, and ``drain_reason``.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.set_dispatch_host_labels(call.user_id, host, labels)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


# --- Rollout manager tools ---


@_tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def advance_rollout(
    rollout_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Return the current readiness snapshot for a rollout.

    Pure read — no mutations, no events written.  Use this in the executor
    loop to determine which items can be dispatched next.

    Args:
        rollout_id: ID of the rollout to inspect.
        ctx: MCP context (injected automatically).

    Returns:
        Dict with keys:
          - next_ready (list[str]): Item IDs ready to dispatch.
          - in_progress (list[str]): Item IDs currently dispatched.
          - blocked (list[str]): Item IDs waiting on unfinished predecessors.
          - graph_complete (bool): True if every item is in a terminal state.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.advance_rollout(call.user_id, rollout_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
async def get_rollout(
    rollout_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Fetch the full lifecycle state of a rollout by ID.

    Use ``get_rollout`` for rollout lifecycle state (phase, halt_reason,
    manager_current_item_id, etc.).  Use ``get_run_status`` for a specific
    dispatched run's stdout and exit code.

    Args:
        rollout_id: ID of the rollout to fetch.
        ctx: MCP context (injected automatically).

    Returns:
        The autonomous_rollouts row dict with fields: id, project_id, status,
        halt_reason, started_at, ended_at, created_at, updated_at,
        manager_phase, manager_current_item_id, manager_current_step,
        manager_state_updated_at, manage_retry_count (historical; no
        longer written), and
        inFlightBuildRuns (list of {runId, itemId, status} for child build
        runs whose status is non-terminal — pending, cloning, or running).

    Raises:
        ToolError: If the rollout is not found or not owned by the caller.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.get_rollout(call.user_id, rollout_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
async def list_rollouts(
    ctx: Context,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List rollouts owned by the caller, with optional filters.

    Call ``list_rollouts(status='running')`` at the start of a new session to
    find any rollout that was left mid-execution and needs to be resumed or
    inspected.

    Args:
        ctx: MCP context (injected automatically).
        project_id: If provided, return only rollouts for this project.
        status: If provided, return only rollouts with this status
            (e.g. ``"running"``, ``"halted"``, ``"pending"``,
            ``"completed"``).
        limit: Maximum number of results to return (default 20, max 100).

    Returns:
        List of rollout dicts ordered by created_at DESC (newest first).
        Each dict has the same shape as ``get_rollout``.
    """
    call = await _resolve_call(ctx)
    clamped = min(max(1, limit), 100)
    return await call.backend.list_rollouts(
        call.user_id,
        project_id=project_id,
        status=status,
        limit=clamped,
    )


@_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
async def get_rollout_plan(
    rollout_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Show the rollout DAG with per-item progress at a glance.

    Use this instead of calling ``get_item`` for each item in a rollout —
    it returns the full plan graph with titles and current rollout_status for
    every item in one call.

    Args:
        rollout_id: ID of the rollout to inspect.
        ctx: MCP context (injected automatically).

    Returns:
        Dict with keys:
          - rollout_id (str)
          - plan_version (int): Latest plan version number.
          - planner_model (str): Model that generated the plan.
          - nodes (list[str]): Item IDs in the plan.
          - edges (list[dict]): Each has ``from_item_id`` and ``to_item_id``.
          - items (list[dict]): Each has ``item_id``, ``title``,
            ``rollout_status`` (pending/ready/dispatched/completed/halted/
            skipped), and ``predecessors`` (list of item IDs that must
            complete before this item can start).

    Raises:
        ToolError: If the rollout is not found, not owned by the caller,
            or has no plan yet.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.get_rollout_plan(call.user_id, rollout_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def plan_rollout(
    item_ids: list[str],
    ctx: Context,
) -> dict[str, Any]:
    """Plan a rollout: validate items, derive the dependency DAG, and return it.

    Validates the legality contract for every item before touching the
    database:
    - Each item must have ``status='ready'``.
    - Each item must have a non-empty ``acceptance_criteria`` structured field.
    - Each item must have a non-empty ``files_to_modify`` structured field.
    - Each item must have ``build_engine`` set.
    - Each item must have ``commit_type`` set.
    - Each item must have no unresolved blockers outside the rollout's own item
      set (internal blockers are fine — they become the ordering).
    - All items must belong to the same project.

    Ordering is derived from the items themselves, not from a language model:
    - **Blockers.** Every ``item_dependencies`` blocker whose blocker and
      blocked item are *both* inside ``item_ids`` becomes an edge
      ``blocker → blocked``.  Blockers pointing outside the set are rejected by
      the legality contract above, so record the dependencies you want honoured
      with ``add_blocker`` at grooming time.
    - **File overlap.** Any two items whose ``files_to_modify`` paths overlap
      are additionally serialised in the order they appear in ``item_ids``, so
      two build agents are never handed the same file concurrently.  A
      directory entry overlaps files nested beneath it; brace patterns
      (``{a,b}``) are expanded, globs overlap the paths they match, and an
      entry listing several paths in prose is split into them.
    Both sources are unioned and deduplicated, and the result is checked for
    cycles before anything is persisted.

    On success, inserts an ``autonomous_rollouts`` row, persists the derived
    DAG, and returns a plan summary for the lead to confirm.

    Workspace projects are supported.  For workspace items,
    ``files_to_modify`` paths are workspace-relative and repo-dir-prefixed
    (e.g. ``'agent_gtd/src/...'``, ``'agent-gtd-dispatch/src/...'``); overlap
    detection compares these path strings as-is, so identical prefixed paths
    across items produce dependency edges with no special handling.

    Args:
        item_ids: IDs of the items to include in the rollout (minimum 1).
        ctx: MCP context (injected automatically).

    Returns:
        Dict with ``rollout_id``, ``status``, ``plan`` (nodes + edges),
        ``planner_model`` (the sentinel ``'derived-from-blockers'``),
        ``item_count``, and ``per_item`` list (each entry has ``item_id``,
        ``title``, ``predecessors``).
    """
    import json

    call = await _resolve_call(ctx)
    try:
        return await call.backend.plan_rollout(call.user_id, item_ids)
    except LegalityContractError as exc:
        raise ToolError(
            f"Legality contract failed for {len(exc.failures)} item(s):\n"
            + json.dumps(exc.failures, indent=2)
        ) from None
    except ValidationError as exc:
        raise ToolError(exc.detail) from None
    except RuntimeError as exc:
        raise ToolError(str(exc)) from None
    except ValueError as exc:
        # Derived DAG contained a cycle — the items' blockers need fixing.
        raise ToolError(str(exc)) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def start_rollout(
    rollout_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Flip a rollout from pending → running without launching a manage agent.

    Useful for lead-as-manager debugging and human-driven rollouts where the
    normal ``dispatch_rollout`` path is not desired.  Both
    ``update_rollout_state`` and ``advance_rollout`` require the rollout to be running;
    this tool performs the status flip so those tools become available.

    Args:
        rollout_id: ID of the rollout to start.
        ctx: MCP context (injected automatically).

    Returns:
        The updated autonomous_rollouts row dict.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.start_rollout(call.user_id, rollout_id)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def complete_item_in_rollout(
    rollout_id: str,
    item_id: str,
    outcome: Literal["completed", "halted", "skipped"],
    ctx: Context,
    merge_actor: Literal[
        "human", "manager-allowlist", "manager-autonomous", "manager+human-fixup", ""
    ] = "",
    decision_rule: Literal["", "agent-judgment"] = "",
    merge_note: str = "",
) -> dict[str, Any]:
    """Mark a dispatched rollout item as done and unblock downstream items.

    After the item is recorded as terminal, each downstream item whose only
    remaining blocking predecessor was this one is transitioned to 'ready'.
    If all items in the rollout are now terminal the rollout is closed.

    Args:
        rollout_id: ID of the rollout.
        item_id: ID of the rollout_items row to complete.
        outcome: One of ``"completed"``, ``"halted"``, ``"skipped"``.
        ctx: MCP context (injected automatically).
        merge_actor: Who merged the PR (``"human"``,
            ``"manager-allowlist"``, ``"manager+human-fixup"``, or empty).
        decision_rule: Allowlist rule name that fired (from executor
            classifier).  Stored in the item_outcome event payload.
        merge_note: Short structured note recording what the merged work
            changed that could invalidate a LATER item's spec — changed public
            signatures, renamed classes, changed config keys.  NOT a prose
            summary of the diff (the commit message covers that).  Stored as a
            ``merge_note`` rollout event and fed into subsequent manage prompts
            so AC reconciliation reasons from a durable record.

    Returns:
        Dict with keys:
          - rollout_item (dict): The updated rollout_items row.
          - newly_ready (list[str]): Item IDs newly transitioned to 'ready'.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.complete_item_in_rollout(
            call.user_id,
            rollout_id,
            item_id,
            outcome,
            merge_actor=merge_actor,
            decision_rule=decision_rule,
            merge_note=merge_note,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
async def halt_rollout(
    rollout_id: str,
    reason: str,
    ctx: Context,
    comment: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    """Halt a running rollout — terminal operation.

    Transitions all in-flight items to 'halted', releases all rollout-scoped
    item locks, posts a GTD comment on the project, and appends a
    ``wave_halted`` event.  The event payload includes the offending item ID
    (if any) and the comment ID so the halt card UI can render both without
    an extra round trip.

    Halt is the non-destructive stop: it stops further dispatches (child runs
    not yet handed to a host are cancelled) but child builds already running
    on a dispatch host are left to finish and push their branches, so a halt
    never destroys work. They are listed in ``in_flight_run_ids``; to stop
    them, cancel each with cancel_run (allowed once the rollout is halted) or
    use cancel_rollout. The rollout's manage/loop run is not touched.

    Args:
        rollout_id: ID of the rollout to halt.
        reason: Short machine-readable halt reason (e.g. ``"merge_rejected"``).
        ctx: MCP context (injected automatically).
        comment: Optional human-readable context appended to the GTD comment.
        item_id: Optional ID of the item that triggered the halt.

    Returns:
        The updated autonomous_rollouts row dict plus ``cancelled_run_ids``
        (not-yet-routed child runs cancelled) and ``in_flight_run_ids``
        (child runs left running).
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.halt_rollout(
            call.user_id,
            rollout_id,
            reason,
            comment=comment,
            item_id=item_id,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def resume_rollout(
    rollout_id: str,
    ctx: Context,
    answer: str = "",
    relaunch: bool = True,
) -> dict[str, Any]:
    """Resume a halted rollout and relaunch its rollout loop.

    Resumes a halted rollout (posts ``answer`` as a project comment — required
    for a halted rollout — moves halted items back to ready/pending, re-locks
    them and sets the rollout to running) and relaunches the rollout loop on
    the dispatch host that last drove it.  The loop is never moved to a
    different host: if that host is gone or draining, the resume is refused
    and the rollout stays halted.

    On a running rollout it only relaunches a missing loop (e.g. one that
    crashed); there is no state change.  It refuses a duplicate loop: if a
    loop is still live, the dispatch host rejects the second one and the new
    run ends ``cancelled`` while the live loop keeps driving.  A rollout that
    never had a loop (lead-driven) resumes with ``loop_run_id`` null.

    Args:
        rollout_id: ID of the rollout to resume.
        ctx: MCP context (injected automatically).
        answer: The lead's answer or instruction, posted as a comment.
            Required for a halted rollout; pass it via the ``answer``
            argument (CLI: ``--answer``).
        relaunch: Also relaunch the rollout loop (default True).

    Returns:
        The updated rollout dict plus ``total_count``, ``done_count`` and
        ``loop_run_id`` (the relaunched loop's run id, or null).
    """
    call = await _resolve_call(ctx)
    try:
        result = await call.backend.resume_rollout(
            call.user_id, rollout_id, answer=answer, relaunch=relaunch
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None
    if result.get("loop_run_id"):
        _enqueue_if_local(call, {"id": result["loop_run_id"]}, "resume_rollout")
    return result


@_tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
async def cancel_rollout(
    rollout_id: str,
    reason: str,
    ctx: Context,
) -> dict[str, Any]:
    """Cancel a rollout, marking any remaining items as skipped.

    Accepts rollouts in any non-terminal status (pending, planning, running,
    halted, failed). Idempotent for already-cancelled rollouts.

    Cancel is the destructive stop: every active child build run of the
    rollout (including ones a halt left running) is cancelled and the cancel
    is forwarded to its dispatch host. The manage/loop run is not cancelled;
    it exits by itself.

    Args:
        rollout_id: ID of the rollout to cancel.
        reason: Short machine-readable cancellation reason (e.g. "superseded").
        ctx: MCP context (injected automatically).

    Returns:
        The updated autonomous_rollouts row dict plus ``cancelled_run_ids``
        (child runs stopped; empty when the rollout was already cancelled).
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.cancel_rollout(call.user_id, rollout_id, reason)
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def update_rollout_state(
    rollout_id: str,
    phase: Literal[
        "warm_up",
        "dispatching",
        "polling",
        "reviewing",
        "merging",
        "reconciling_ac",
        "parked",
        "halted",
    ],
    ctx: Context,
    current_item_id: str | None = None,
    current_step: str | None = None,
) -> dict[str, Any]:
    """Publish the manager's current semantic state for a running rollout.

    The manage-mode agent calls this at each major workflow transition so the
    dashboard can display "Manager: merging · working on <item> · last updated
    2 min ago" instead of just elapsed time.

    Valid ``phase`` values: ``"warm_up"``, ``"dispatching"``, ``"polling"``,
    ``"reviewing"``, ``"merging"``, ``"reconciling_ac"``, ``"parked"``,
    ``"halted"``.

    Args:
        rollout_id: ID of the rollout to update.
        phase: Current execution phase of the manager.
        ctx: MCP context (injected automatically).
        current_item_id: The item ID being acted on, or ``None``.
        current_step: Short free-form description of the current step.

    Returns:
        Dict with keys ``rollout_id``, ``ts``, ``phase``,
        ``current_item_id``, ``current_step``.
    """
    call = await _resolve_call(ctx)
    try:
        return await call.backend.update_rollout_state(
            call.user_id,
            rollout_id,
            phase=phase,
            current_item_id=current_item_id,
            current_step=current_step,
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except ValidationError as e:
        raise ToolError(e.detail) from None


@_tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
async def dispatch_rollout(
    rollout_id: str,
    ctx: Context,
    dispatch_host_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch the wave manager agent for this rollout.

    Use this instead of dispatch_item when launching a manage-mode run.
    Creates a manage-mode claude_runs row scoped to the rollout (no item_id),
    and transitions the rollout from pending → running.

    Workspace projects are supported; the manage agent receives workspace-aware
    repo information from the project record.

    Args:
        rollout_id: ID of the rollout to dispatch.
        ctx: MCP context (injected automatically).
        dispatch_host_id: Optional host UUID from /api/settings/dispatch/hosts.
            Set to pin this dispatch to a specific host (use for verification,
            debugging, or cache affinity). Omit to let the router pick
            automatically based on engine + agent availability and capacity.
            The pin is stored on the rollout and inherited by child build runs.

    Returns:
        The created run dict with status and branch name.
    """
    from agent_gtd.exceptions import (
        ValidationError as _ValidationError,
    )

    call = await _resolve_call(ctx)
    try:
        run = await call.backend.dispatch_rollout(
            call.user_id, rollout_id, dispatch_host_id=dispatch_host_id
        )
    except NotFoundError as e:
        raise ToolError(e.detail) from None
    except _ValidationError as e:
        raise ToolError(e.detail) from None
    _enqueue_if_local(call, run, "dispatch_rollout")
    return run


# --- Server factory ---


def create_mcp_server(*, transport: Literal["stdio", "http"]) -> FastMCP:
    """Build a new FastMCP server carrying every registered tool.

    Args:
        transport: ``"stdio"`` builds the standalone server (own lifespan,
            ``login`` when credentials are not in the env).  ``"http"`` builds
            the server the board mounts at ``/mcp``: no lifespan (the board
            owns the DB), no ``login`` (the board authenticates the bearer
            token before the MCP layer) and per-call logging middleware.

    Returns:
        A fresh FastMCP instance.
    """
    if transport == "stdio":
        server = FastMCP(
            name="Agent GTD",
            instructions=_instructions,
            lifespan=mcp_lifespan,
        )
        if _show_login:
            server.tool(login, annotations=_LOGIN_ANNOTATIONS)
    else:
        from agent_gtd.mcp_http import ToolCallLogMiddleware

        server = FastMCP(name="Agent GTD", instructions=_HTTP_INSTRUCTIONS)
        server.add_middleware(ToolCallLogMiddleware())
    for fn, annotations in _TOOL_REGISTRY:
        server.tool(fn, annotations=annotations)
    return server


mcp = create_mcp_server(transport="stdio")


# --- Entry point ---

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _warn_if_remote_stdio() -> None:
    """Point users of a remote board at its streamable HTTP endpoint."""
    url = resolve_client_config()[0]
    if not url:
        return
    if urlsplit(url).hostname in _LOOPBACK_HOSTS:
        return
    base = url.rstrip("/")
    logger.warning(
        "agent-gtd stdio MCP server is deprecated for remote boards; "
        "register %s/mcp as a streamable HTTP MCP server with header "
        '"Authorization: Bearer <key>" instead',
        base,
    )


def main() -> None:
    """Run the MCP server (stdio transport)."""
    _warn_if_remote_stdio()
    mcp.run(transport="stdio")
