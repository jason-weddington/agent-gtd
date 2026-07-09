"""Projects + sharing CLI subcommands for the ``agent-gtd`` CLI.

Registers six subparsers via :func:`register`:

* ``list-projects``   — list all accessible projects (optional status filter)
* ``add-project``     — create a new project
* ``update-project``  — update an existing project
* ``share-project``   — add a member (by email) to a project
* ``unshare-project`` — remove a member from a project
* ``list-project-members`` — list all members of a project
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import backend_session, emit_json, fail
from agent_gtd.dispatch_constants import (
    MAX_TIMEOUT_MINUTES,
    MAX_TURNS,
    MIN_TIMEOUT_MINUTES,
    MIN_TURNS,
)

if TYPE_CHECKING:
    import argparse

# ---------------------------------------------------------------------------
# Status + repo-mode choices (derived from models.ProjectStatus / RepoMode)
# ---------------------------------------------------------------------------

_STATUS_CHOICES = ["active", "completed", "on_hold", "cancelled"]
_REPO_MODE_CHOICES = ["monorepo", "workspace"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register all project + sharing subcommands on *subparsers*.

    Adds exactly six subparsers (list-projects, add-project, update-project,
    share-project, unshare-project, list-project-members) and attaches a
    handler to each via ``parser.set_defaults(func=handler)``.

    Args:
        subparsers: The subparsers action from the top-level argument parser.
    """
    _register_list_projects(subparsers)
    _register_add_project(subparsers)
    _register_update_project(subparsers)
    _register_share_project(subparsers)
    _register_unshare_project(subparsers)
    _register_list_project_members(subparsers)


def _register_list_projects(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "list-projects",
        help="List accessible projects.",
    )
    parser.add_argument(
        "--status",
        choices=_STATUS_CHOICES,
        default=None,
        help="Filter by project status.",
    )
    parser.set_defaults(func=_cmd_list_projects)


def _register_add_project(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "add-project",
        help="Create a new project.",
    )
    parser.add_argument("name", help="Project name (required).")
    parser.add_argument("--description", default="", help="Project description.")
    parser.add_argument("--area", default="", help="Area of responsibility.")
    parser.add_argument(
        "--status",
        choices=_STATUS_CHOICES,
        default="active",
        help="Initial project status (default: active).",
    )
    parser.add_argument("--git-origin", default="", help="Git remote origin URL.")
    parser.add_argument(
        "--kb-project-ref", default="", help="Knowledge-base project ref."
    )
    parser.add_argument(
        "--repo-mode",
        choices=_REPO_MODE_CHOICES,
        default="monorepo",
        help="Repository layout mode (default: monorepo).",
    )
    parser.add_argument(
        "--workspace-repo",
        action="append",
        dest="workspace_repos",
        metavar="REPO",
        help="Additional workspace repo URL (repeatable).",
    )
    parser.add_argument(
        "--dispatch-max-turns",
        type=int,
        default=None,
        metavar="N",
        help=f"Max dispatch turns [{MIN_TURNS}-{MAX_TURNS}].",
    )
    parser.add_argument(
        "--dispatch-timeout-minutes",
        type=int,
        default=None,
        metavar="N",
        help=f"Dispatch timeout [{MIN_TIMEOUT_MINUTES}-{MAX_TIMEOUT_MINUTES} min].",
    )
    parser.add_argument(
        "--plan-dispatch-agent",
        default=None,
        help="Plan-mode dispatch agent name.",
    )
    parser.add_argument(
        "--build-dispatch-agent",
        default=None,
        help="Build-mode dispatch agent name.",
    )
    parser.add_argument(
        "--gate-command",
        default=None,
        dest="gate_command",
        help=(
            "Shell command that is the repo's quality gate"
            " (runs from repo root; exit 0 = green)."
        ),
    )
    parser.set_defaults(func=_cmd_add_project)


def _register_update_project(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "update-project",
        help="Update an existing project.",
    )
    parser.add_argument("project_id", help="UUID of the project to update.")
    parser.add_argument("--name", default=None, help="New project name.")
    parser.add_argument("--description", default=None, help="New description.")
    parser.add_argument(
        "--status",
        choices=_STATUS_CHOICES,
        default=None,
        help="New project status.",
    )
    parser.add_argument("--area", default=None, help="New area of responsibility.")
    parser.add_argument("--git-origin", default=None, help="New git remote origin URL.")
    parser.add_argument(
        "--kb-project-ref", default=None, help="New knowledge-base project ref."
    )
    parser.add_argument(
        "--repo-mode",
        choices=_REPO_MODE_CHOICES,
        default=None,
        help="New repository layout mode.",
    )
    parser.add_argument(
        "--workspace-repo",
        action="append",
        dest="workspace_repos",
        metavar="REPO",
        help="Workspace repo URL (repeatable; replaces existing list).",
    )

    # Mutually exclusive value/clear pairs for nullable dispatch fields.
    grp_turns = parser.add_mutually_exclusive_group()
    grp_turns.add_argument(
        "--dispatch-max-turns",
        type=int,
        default=None,
        metavar="N",
        help=f"Set max dispatch turns [{MIN_TURNS}-{MAX_TURNS}].",
    )
    grp_turns.add_argument(
        "--clear-dispatch-max-turns",
        action="store_true",
        help="Clear the dispatch-max-turns override.",
    )

    grp_timeout = parser.add_mutually_exclusive_group()
    grp_timeout.add_argument(
        "--dispatch-timeout-minutes",
        type=int,
        default=None,
        metavar="N",
        help=f"Set dispatch timeout [{MIN_TIMEOUT_MINUTES}-{MAX_TIMEOUT_MINUTES} min].",
    )
    grp_timeout.add_argument(
        "--clear-dispatch-timeout-minutes",
        action="store_true",
        help="Clear the dispatch-timeout-minutes override.",
    )

    grp_plan = parser.add_mutually_exclusive_group()
    grp_plan.add_argument(
        "--plan-dispatch-agent",
        default=None,
        help="Set plan-mode dispatch agent name.",
    )
    grp_plan.add_argument(
        "--clear-plan-dispatch-agent",
        action="store_true",
        help="Clear the plan-dispatch-agent override.",
    )

    grp_build = parser.add_mutually_exclusive_group()
    grp_build.add_argument(
        "--build-dispatch-agent",
        default=None,
        help="Set build-mode dispatch agent name.",
    )
    grp_build.add_argument(
        "--clear-build-dispatch-agent",
        action="store_true",
        help="Clear the build-dispatch-agent override.",
    )

    grp_gate = parser.add_mutually_exclusive_group()
    grp_gate.add_argument(
        "--gate-command",
        default=None,
        dest="gate_command",
        help=(
            "Shell command that is the repo's quality gate"
            " (runs from repo root; exit 0 = green)."
        ),
    )
    grp_gate.add_argument(
        "--clear-gate-command",
        action="store_true",
        dest="clear_gate_command",
        help="Clear the gate_command back to NULL.",
    )

    parser.set_defaults(func=_cmd_update_project)


def _register_share_project(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "share-project",
        help="Share a project with a user by email.",
    )
    parser.add_argument("project_id", help="UUID of the project to share.")
    parser.add_argument("email", help="Email address of the user to add.")
    parser.set_defaults(func=_cmd_share_project)


def _register_unshare_project(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "unshare-project",
        help="Remove a user from a project.",
    )
    parser.add_argument("project_id", help="UUID of the project.")
    parser.add_argument("email", help="Email address of the user to remove.")
    parser.set_defaults(func=_cmd_unshare_project)


def _register_list_project_members(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "list-project-members",
        help="List members of a project.",
    )
    parser.add_argument("project_id", help="UUID of the project.")
    parser.set_defaults(func=_cmd_list_project_members)


# ---------------------------------------------------------------------------
# Dispatch-bounds validation (mirrors mcp_server.py tool-layer checks)
# ---------------------------------------------------------------------------


def _validate_dispatch_bounds(args: argparse.Namespace) -> None:
    """Validate dispatch_max_turns and dispatch_timeout_minutes bounds.

    Prints an error to stderr and exits 1 if either field is out of range.
    Both add-project and update-project call this before touching the backend.

    Args:
        args: Parsed namespace that may carry dispatch_max_turns and
            dispatch_timeout_minutes attributes.
    """
    max_turns: int | None = getattr(args, "dispatch_max_turns", None)
    timeout_mins: int | None = getattr(args, "dispatch_timeout_minutes", None)

    if max_turns is not None and not (MIN_TURNS <= max_turns <= MAX_TURNS):
        print(
            f"Error: dispatch_max_turns must be between {MIN_TURNS} and {MAX_TURNS}",
            file=sys.stderr,
        )
        sys.exit(1)

    if timeout_mins is not None and not (
        MIN_TIMEOUT_MINUTES <= timeout_mins <= MAX_TIMEOUT_MINUTES
    ):
        print(
            f"Error: dispatch_timeout_minutes must be between"
            f" {MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _cmd_list_projects(args: argparse.Namespace) -> None:
    """Handle the list-projects subcommand.

    Args:
        args: Parsed namespace containing optional ``status`` filter.
    """

    async def _run() -> list[dict[str, Any]]:
        async with backend_session() as (backend, user_id):
            return await backend.list_projects(user_id, status=args.status)

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json(result)


def _cmd_add_project(args: argparse.Namespace) -> None:
    """Handle the add-project subcommand.

    Args:
        args: Parsed namespace containing project creation fields.
    """
    _validate_dispatch_bounds(args)

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.create_project(
                user_id,
                name=args.name,
                description=args.description,
                area=args.area,
                status=args.status,
                git_origin=args.git_origin,
                kb_project_ref=args.kb_project_ref,
                repo_mode=args.repo_mode,
                workspace_repos=args.workspace_repos,
                dispatch_max_turns=args.dispatch_max_turns,
                dispatch_timeout_minutes=args.dispatch_timeout_minutes,
                plan_dispatch_agent=args.plan_dispatch_agent,
                build_dispatch_agent=args.build_dispatch_agent,
                gate_command=getattr(args, "gate_command", None),
            )

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json(result)


def _cmd_update_project(args: argparse.Namespace) -> None:
    """Handle the update-project subcommand.

    Args:
        args: Parsed namespace containing the project_id and update fields.
    """
    _validate_dispatch_bounds(args)

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.update_project(
                user_id,
                args.project_id,
                name=args.name,
                description=args.description,
                status=args.status,
                area=args.area,
                git_origin=args.git_origin,
                kb_project_ref=args.kb_project_ref,
                repo_mode=args.repo_mode,
                workspace_repos=args.workspace_repos,
                dispatch_max_turns=args.dispatch_max_turns,
                clear_dispatch_max_turns=args.clear_dispatch_max_turns,
                dispatch_timeout_minutes=args.dispatch_timeout_minutes,
                clear_dispatch_timeout_minutes=args.clear_dispatch_timeout_minutes,
                plan_dispatch_agent=args.plan_dispatch_agent,
                clear_plan_dispatch_agent=args.clear_plan_dispatch_agent,
                build_dispatch_agent=args.build_dispatch_agent,
                clear_build_dispatch_agent=args.clear_build_dispatch_agent,
                gate_command=getattr(args, "gate_command", None),
                clear_gate_command=getattr(args, "clear_gate_command", False),
            )

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json(result)


def _cmd_share_project(args: argparse.Namespace) -> None:
    """Handle the share-project subcommand.

    Args:
        args: Parsed namespace containing ``project_id`` and ``email``.
    """

    async def _run() -> dict[str, Any]:
        async with backend_session() as (backend, user_id):
            return await backend.add_project_member(
                user_id, args.project_id, args.email
            )

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json(result)


def _cmd_unshare_project(args: argparse.Namespace) -> None:
    """Handle the unshare-project subcommand.

    Args:
        args: Parsed namespace containing ``project_id`` and ``email``.
    """

    async def _run() -> None:
        async with backend_session() as (backend, user_id):
            await backend.remove_project_member(user_id, args.project_id, args.email)

    try:
        asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json({"ok": True})


def _cmd_list_project_members(args: argparse.Namespace) -> None:
    """Handle the list-project-members subcommand.

    Args:
        args: Parsed namespace containing ``project_id``.
    """

    async def _run() -> list[dict[str, Any]]:
        async with backend_session() as (backend, user_id):
            return await backend.list_project_members(user_id, args.project_id)

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        fail(exc)
    else:
        emit_json(result)
