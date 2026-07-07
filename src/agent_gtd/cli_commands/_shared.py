"""Shared helpers for per-resource CLI command modules.

Every future ``cli_commands/<resource>.py`` module imports the helpers defined
here rather than re-implementing the JSON-payload loading, JSON emission,
error-exit, or backend-session boilerplate. These are the canonical, single
implementations — ``agent_gtd.cli`` re-exports :func:`load_json_payload` as
``_load_json_payload`` for backwards compatibility.

This module imports nothing from ``agent_gtd.cli`` (no circular import). The
``agent_gtd.database`` symbols used by :func:`backend_session` are imported
lazily inside the context manager, mirroring the existing ``cli.py`` handlers.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, NoReturn

from agent_gtd.mcp_backend import McpBackend, create_backend

if TYPE_CHECKING:
    import argparse

#: Type alias every per-resource command handler must match. A handler takes
#: the parsed argparse namespace and returns None; it is attached to its
#: subparser via ``parser.set_defaults(func=handler)``.
CommandHandler = Callable[["argparse.Namespace"], None]


def load_json_payload(from_json: str | None, use_stdin: bool) -> dict[str, Any]:
    """Load a JSON object from a file or stdin, validated as a dict.

    Args:
        from_json: File path to read JSON from. None if not provided.
        use_stdin: If True, read from stdin.

    Returns:
        The parsed JSON dict. Returns ``{}`` when neither source is specified.

    Raises:
        ValueError: If the parsed JSON value is not a dict.
        json.JSONDecodeError: If the input is not valid JSON.
        OSError: If the file at *from_json* cannot be opened.
    """
    if from_json is not None:
        with open(from_json) as fh:
            data = json.load(fh)
    elif use_stdin:
        data = json.load(sys.stdin)
    else:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"JSON payload must be an object (dict), not {type(data).__name__}"
        )
    return data


def emit_json(obj: Any) -> None:
    """Serialize *obj* as JSON to stdout with a trailing newline.

    Matches the existing run-status/rollout-status stdout contract:
    ``json.dump(obj, sys.stdout, default=str)`` followed by ``print()`` for a
    shell-friendly trailing newline. Non-JSON-serializable values (e.g.
    ``datetime``) are stringified via ``default=str``.

    Args:
        obj: Any JSON-serializable (or ``default=str``-coercible) object.
    """
    json.dump(obj, sys.stdout, default=str)
    print()


def fail(msg: object) -> NoReturn:
    """Print ``Error: <msg>`` to stderr and exit with status 1.

    Args:
        msg: The error to report. Rendered via ``f"Error: {msg}"``.
    """
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


@asynccontextmanager
async def backend_session() -> AsyncIterator[tuple[McpBackend, str]]:
    """Yield an authenticated ``(backend, user_id)`` pair, closed on exit.

    Auth follows the same mechanism as the MCP server and the existing
    ``cli.py`` handlers:

    - No ``AGENT_GTD_URL`` → LocalBackend (no auth; ``await init_db()`` then
      ``user_id = LOCAL_USER_ID``).
    - ``AGENT_GTD_URL`` set → HttpBackend; require ``AGENT_GTD_API_KEY``
      (raising ``RuntimeError`` when absent), then resolve the user id via
      ``backend.login(api_key, "cli")``.

    ``backend.close()`` is always awaited in a ``finally`` block, even when the
    ``with`` body raises.

    Yields:
        A ``(backend, user_id)`` tuple.

    Raises:
        RuntimeError: If ``AGENT_GTD_API_KEY`` is required but not set.
    """
    backend = create_backend()
    try:
        if not os.environ.get("AGENT_GTD_URL", ""):
            # Local mode — no auth needed.
            from agent_gtd.database import LOCAL_USER_ID, init_db

            await init_db()
            user_id = LOCAL_USER_ID
        else:
            api_key = os.environ.get("AGENT_GTD_API_KEY", "")
            if not api_key:
                raise RuntimeError("AGENT_GTD_API_KEY environment variable is required")
            session = await backend.login(api_key, "cli")
            user_id = session["user_id"]
        yield backend, user_id
    finally:
        await backend.close()
