"""CLI for Agent GTD — shell-accessible companion to the MCP server."""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from agent_gtd.mcp_backend import create_backend


async def _fetch_run_status(run_id: str) -> dict[str, Any]:
    """Fetch a single run's status from the configured backend.

    Auth follows the same mechanism as the MCP server:
      - No AGENT_GTD_URL → LocalBackend (no auth needed, uses LOCAL_USER_ID)
      - AGENT_GTD_URL set → HttpBackend (authenticates via AGENT_GTD_API_KEY)

    Args:
        run_id: ID of the dispatch run to look up.

    Returns:
        Dict with run fields: id, item_id, status, started_at, finished_at,
        feature_branch, error_msg, and others.

    Raises:
        RuntimeError: If AGENT_GTD_API_KEY is required but not set.
        NotFoundError: (LocalBackend) If run not found.
        ToolError: (HttpBackend) If API returns non-2xx.
    """
    backend = create_backend()
    try:
        if not os.environ.get("AGENT_GTD_URL", ""):
            # Local mode — no auth needed
            from agent_gtd.database import LOCAL_USER_ID, init_db

            await init_db()
            user_id = LOCAL_USER_ID
        else:
            api_key = os.environ.get("AGENT_GTD_API_KEY", "")
            if not api_key:
                raise RuntimeError("AGENT_GTD_API_KEY environment variable is required")
            session = await backend.login(api_key, "cli")
            user_id = session["user_id"]
        return await backend.get_run(user_id, run_id)
    finally:
        await backend.close()


def _cmd_run_status(run_id: str) -> None:
    """Execute the run-status subcommand.

    Args:
        run_id: ID of the dispatch run to print status for.
    """
    try:
        run = asyncio.run(_fetch_run_status(run_id))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    json.dump(run, sys.stdout, default=str)
    print()  # trailing newline for shell friendliness


async def _promote_admin(email: str) -> str:
    """Set ``is_admin = 1`` on the user with the given email.

    Talks directly to the configured database — does NOT go through the
    HTTP API. Run this where ``AGENT_GTD_DATABASE_URL`` points at the
    target DB (typically on the host running the service).

    Returns:
        Human-readable status message.

    Raises:
        ValueError: If no user with that email exists.
    """
    from agent_gtd.database import close_db, get_db, init_db

    await init_db()
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, is_admin FROM users WHERE email = $1", email
            )
            if row is None:
                raise ValueError(f"no user found with email {email}")
            if row["is_admin"]:
                return f"{email} is already an admin"
            await conn.execute(
                "UPDATE users SET is_admin = 1 WHERE email = $1", email
            )
            return f"promoted {email} to admin"
    finally:
        await close_db()


def _cmd_promote_admin(email: str) -> None:
    """Execute the promote-admin subcommand."""
    try:
        msg = asyncio.run(_promote_admin(email))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(msg)


def main() -> None:
    """Entry point for the agent-gtd CLI."""
    parser = argparse.ArgumentParser(
        prog="agent-gtd",
        description="Agent GTD command-line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    rs = subparsers.add_parser(
        "run-status",
        help="Print dispatch run status as JSON to stdout.",
    )
    rs.add_argument("run_id", help="Dispatch run ID.")

    pa = subparsers.add_parser(
        "promote-admin",
        help="Set is_admin=1 on the user with the given email (direct DB update).",
    )
    pa.add_argument("email", help="Email of the user to promote.")

    args = parser.parse_args()

    if args.command == "run-status":
        _cmd_run_status(args.run_id)
    elif args.command == "promote-admin":
        _cmd_promote_admin(args.email)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)
