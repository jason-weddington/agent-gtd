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

    args = parser.parse_args()

    if args.command == "run-status":
        _cmd_run_status(args.run_id)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)
