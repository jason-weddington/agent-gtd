"""CLI for Agent GTD — shell-accessible companion to the MCP server."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from agent_gtd.mcp_backend import create_backend

# ---------------------------------------------------------------------------
# Terminal-state definitions (client-only; do not change server semantics)
# ---------------------------------------------------------------------------

#: Run statuses that are considered terminal successes.
_RUN_SUCCESS_STATES: frozenset[str] = frozenset({"success"})
#: All terminal run statuses.
_RUN_TERMINAL_STATES: frozenset[str] = frozenset(
    {"success", "failed", "cancelled", "error", "timeout"}
)

#: Rollout statuses that are considered terminal successes.
_ROLLOUT_SUCCESS_STATES: frozenset[str] = frozenset({"completed"})
#: All terminal rollout statuses.
_ROLLOUT_TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "halted", "cancelled"}
)


def _load_json_payload(from_json: str | None, use_stdin: bool) -> dict[str, Any]:
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


async def _http_post_create_item(
    base_url: str,
    api_key: str,
    *,
    title: str,
    description: str = "",
    labels: list[str] | None = None,
    status: str = "inbox",
    build_engine: str | None = None,
    acceptance_criteria: list[str] | None = None,
    files_to_modify: list[dict[str, Any]] | None = None,
    scope_out: list[str] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/items with full structured fields via a direct httpx call.

    Bypasses :class:`~agent_gtd.mcp_backend.HttpBackend.create_item` (which
    drops heavy fields) and sends all structured payload fields directly to the
    REST API.

    Args:
        base_url: Base URL of the Agent GTD API (e.g. ``https://host``).
        api_key: API key for Bearer authentication.
        title: Item title (required).
        description: Item description.
        labels: Optional list of label strings.
        status: Item status string.
        build_engine: Optional build engine preference.
        acceptance_criteria: Optional list of acceptance-criteria strings.
        files_to_modify: Optional list of ``{path, change}`` dicts.
        scope_out: Optional list of scope-out strings.
        project_id: Optional project UUID to associate the item with.

    Returns:
        Created item dict as returned by the API.

    Raises:
        ToolError: If the API returns a non-2xx response.
    """
    import ssl

    import httpx
    import truststore
    from fastmcp.exceptions import ToolError

    body: dict[str, Any] = {
        "title": title,
        "description": description,
        "status": status,
        "created_by": "cli",
    }
    if labels is not None:
        body["labels"] = labels
    if project_id is not None:
        body["project_id"] = project_id
    if build_engine is not None:
        body["build_engine"] = build_engine
    if acceptance_criteria is not None:
        body["acceptance_criteria"] = acceptance_criteria
    if files_to_modify is not None:
        body["files_to_modify"] = files_to_modify
    if scope_out is not None:
        body["scope_out"] = scope_out

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=30.0,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    ) as client:
        resp = await client.post(
            "/api/items",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if not resp.is_success:
            try:
                detail: str = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ToolError(f"{detail}")
        result: dict[str, Any] = resp.json()
        return result


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


def _is_fatal_wait_error(exc: Exception) -> bool:
    """Return True if *exc* should abort the wait loop immediately.

    Fatal errors are those that cannot resolve on the next poll: entity not
    found, missing auth credentials, or explicit HTTP 401/403 responses.
    All other exceptions (network errors, transient 5xx) are treated as
    transient and retried at the next poll interval.

    Args:
        exc: Exception raised by a fetcher during the wait loop.

    Returns:
        True if the wait loop should abort; False to retry.
    """
    from agent_gtd.exceptions import NotFoundError

    if isinstance(exc, NotFoundError):
        return True
    # Only the specific "missing API key" RuntimeError is unrecoverable — generic
    # RuntimeErrors from network layers are transient and should be retried.
    if isinstance(exc, RuntimeError) and "API_KEY" in str(exc):
        return True
    msg = str(exc).lower()
    return any(
        kw in msg
        for kw in ("not found", "404", "401", "403", "unauthorized", "forbidden")
    )


async def _wait_for_terminal(
    fetcher: Callable[[str], Awaitable[dict[str, Any]]],
    entity_id: str,
    terminal_states: frozenset[str],
    success_states: frozenset[str],
    poll_interval: float,
    timeout: float,
) -> tuple[dict[str, Any], int]:
    """Poll *fetcher* until terminal state or client timeout.

    Transient fetch errors (network issues, 5xx) are logged to stderr and
    retried at the next poll interval. Fatal errors (not-found, auth) are
    re-raised so the caller can exit with code 1.

    Args:
        fetcher: Async callable that takes an entity ID and returns a status
            dict. Must be ``_fetch_run_status`` or ``_fetch_rollout_status``.
        entity_id: ID passed verbatim to *fetcher* on each poll.
        terminal_states: Set of status strings that end the wait.
        success_states: Subset of *terminal_states* that map to exit code 0;
            all others map to exit code 2.
        poll_interval: Seconds between polls (already clamped to floor ≥ 5 by
            the caller).
        timeout: Client timeout in seconds; 0 means wait indefinitely.

    Returns:
        ``(last_data, exit_code)`` where *exit_code* is one of:
        - 0  — terminal success
        - 2  — terminal non-success
        - 124 — client timeout exceeded
    """
    loop = asyncio.get_running_loop()
    deadline: float | None = loop.time() + timeout if timeout > 0 else None
    last_data: dict[str, Any] = {}

    while True:
        # --- fetch ---
        try:
            data = await fetcher(entity_id)
            last_data = data
            status = str(data.get("status", ""))
            if status in terminal_states:
                return data, 0 if status in success_states else 2
        except Exception as exc:
            if _is_fatal_wait_error(exc):
                raise
            # Transient error — print a notice and retry at the next interval.
            print(f"[wait] transient fetch error (will retry): {exc}", file=sys.stderr)

        # --- check timeout before sleeping ---
        if deadline is not None:
            now = loop.time()
            if now >= deadline:
                return last_data, 124
            sleep_time = min(poll_interval, deadline - now)
        else:
            sleep_time = poll_interval

        await asyncio.sleep(sleep_time)

        # --- recheck after sleep (accounts for any over-sleep) ---
        if deadline is not None and loop.time() >= deadline:
            return last_data, 124


def _cmd_run_status(args: argparse.Namespace) -> None:
    """Execute the run-status subcommand.

    Without ``--wait``: single fetch, print JSON to stdout, return.
    With ``--wait``: block until the run reaches a terminal state, print the
    final JSON to stdout (or to stderr on client timeout), then exit with the
    appropriate exit code (0/2/124/1).

    Args:
        args: Parsed namespace containing run_id, wait, poll_interval, timeout.
    """
    run_id: str = args.run_id
    wait: bool = args.wait
    poll_interval = max(5.0, float(args.poll_interval))
    timeout = float(args.timeout)

    if not wait:
        # Original one-shot behaviour — unchanged.
        try:
            run = asyncio.run(_fetch_run_status(run_id))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        json.dump(run, sys.stdout, default=str)
        print()  # trailing newline for shell friendliness
        return

    # --- blocking wait mode ---
    try:
        data, exit_code = asyncio.run(
            _wait_for_terminal(
                _fetch_run_status,
                run_id,
                _RUN_TERMINAL_STATES,
                _RUN_SUCCESS_STATES,
                poll_interval,
                timeout,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if exit_code == 124:
        # Timeout: print last-known JSON to stderr and exit 124.
        json.dump(data, sys.stderr, default=str)
        print(file=sys.stderr)
        sys.exit(124)

    json.dump(data, sys.stdout, default=str)
    print()
    sys.exit(exit_code)


async def _fetch_rollout_status(rollout_id: str) -> dict[str, Any]:
    """Fetch a single rollout's status from the configured backend.

    Auth follows the same mechanism as the MCP server:
      - No AGENT_GTD_URL → LocalBackend (no auth needed, uses LOCAL_USER_ID)
      - AGENT_GTD_URL set → HttpBackend (authenticates via AGENT_GTD_API_KEY)

    Args:
        rollout_id: ID of the autonomous rollout to look up.

    Returns:
        Dict with rollout fields: id, project_id, lead_user_id, status,
        created_at, updated_at, and others.

    Raises:
        RuntimeError: If AGENT_GTD_API_KEY is required but not set.
        NotFoundError: (LocalBackend) If rollout not found.
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
        return await backend.get_rollout(user_id, rollout_id)
    finally:
        await backend.close()


def _cmd_rollout_status(args: argparse.Namespace) -> None:
    """Execute the rollout-status subcommand.

    Without ``--wait``: single fetch, print JSON to stdout, return.
    With ``--wait``: block until the rollout reaches a terminal state, print
    the final JSON to stdout (or to stderr on client timeout), then exit with
    the appropriate exit code (0/2/124/1).

    Args:
        args: Parsed namespace containing rollout_id, wait, poll_interval,
            timeout.
    """
    rollout_id: str = args.rollout_id
    wait: bool = args.wait
    poll_interval = max(5.0, float(args.poll_interval))
    timeout = float(args.timeout)

    if not wait:
        # Original one-shot behaviour — unchanged.
        try:
            rollout = asyncio.run(_fetch_rollout_status(rollout_id))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        json.dump(rollout, sys.stdout, default=str)
        print()  # trailing newline for shell friendliness
        return

    # --- blocking wait mode ---
    try:
        data, exit_code = asyncio.run(
            _wait_for_terminal(
                _fetch_rollout_status,
                rollout_id,
                _ROLLOUT_TERMINAL_STATES,
                _ROLLOUT_SUCCESS_STATES,
                poll_interval,
                timeout,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if exit_code == 124:
        # Timeout: print last-known JSON to stderr and exit 124.
        json.dump(data, sys.stderr, default=str)
        print(file=sys.stderr)
        sys.exit(124)

    json.dump(data, sys.stdout, default=str)
    print()
    sys.exit(exit_code)


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
            await conn.execute("UPDATE users SET is_admin = 1 WHERE email = $1", email)
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


async def _do_update_item(
    item_id: str,
    payload: dict[str, Any],
    status: str | None,
    build_engine: str | None,
    explicit_version: int | None,
) -> None:
    """Apply a structured update to a GTD item via the configured backend.

    Reads auth from the same environment variables as the MCP server. When
    ``explicit_version`` is None the current version is fetched automatically
    and the write is retried exactly once on a version conflict. When
    ``explicit_version`` is supplied the caller's version is used directly with
    no auto-fetch and no retry.

    Args:
        item_id: UUID of the item to update.
        payload: JSON dict with any of: title, description,
            acceptance_criteria, files_to_modify, scope_out, labels. Keys
            absent from this dict are not modified on the item.
        status: New status value, or None to leave unchanged.
        build_engine: New build engine value, or None to leave unchanged.
        explicit_version: Explicit optimistic-lock version, or None for
            auto-fetch + single retry.

    Raises:
        RuntimeError: If AGENT_GTD_API_KEY is required but not set.
        VersionConflictError: (LocalBackend) If two consecutive attempts both
            conflict.
        ToolError: (HttpBackend) For non-conflict API errors, or if two
            consecutive version-conflict responses occur.
    """
    from fastmcp.exceptions import ToolError

    from agent_gtd.exceptions import VersionConflictError

    backend = create_backend()
    try:
        if not os.environ.get("AGENT_GTD_URL", ""):
            from agent_gtd.database import LOCAL_USER_ID, init_db

            await init_db()
            user_id = LOCAL_USER_ID
        else:
            api_key = os.environ.get("AGENT_GTD_API_KEY", "")
            if not api_key:
                raise RuntimeError("AGENT_GTD_API_KEY environment variable is required")
            session = await backend.login(api_key, "cli")
            user_id = session["user_id"]

        # Pass only keys present in payload — absent key → argument stays None
        # → item_service.update_item leaves that column unchanged.
        title: str | None = payload.get("title")
        description: str | None = payload.get("description")
        acceptance_criteria: list[str] | None = payload.get("acceptance_criteria")
        files_to_modify: list[dict[str, Any]] | None = payload.get("files_to_modify")
        scope_out: list[str] | None = payload.get("scope_out")
        labels: list[str] | None = payload.get("labels")

        def _is_conflict(exc: Exception) -> bool:
            """Return True if *exc* represents a version-conflict error."""
            return isinstance(exc, VersionConflictError) or (
                isinstance(exc, ToolError) and "Version conflict" in str(exc)
            )

        async def _call(version: int) -> None:
            await backend.update_item(
                user_id,
                item_id,
                version=version,
                title=title,
                description=description,
                status=status,
                labels=labels,
                build_engine=build_engine,
                build_engine_set=build_engine is not None,
                acceptance_criteria=acceptance_criteria,
                files_to_modify=files_to_modify,
                scope_out=scope_out,
            )

        if explicit_version is not None:
            # Caller supplied an explicit version: use directly, no retry.
            await _call(explicit_version)
        else:
            # Auto-fetch current version; retry exactly once on conflict.
            item = await backend.get_item(user_id, item_id)
            version = int(item["version"])
            try:
                await _call(version)
            except Exception as exc:
                if _is_conflict(exc):
                    item = await backend.get_item(user_id, item_id)
                    version = int(item["version"])
                    await _call(version)
                else:
                    raise
    finally:
        await backend.close()


def _cmd_update_item(args: argparse.Namespace) -> None:
    """Execute the update-item subcommand.

    Args:
        args: Parsed namespace containing item_id, from_json, stdin, status,
            build_engine, and version.
    """
    if (
        not args.from_json
        and not args.stdin
        and not args.status
        and not args.build_engine
    ):
        print(
            "Error: supply at least one of --from-json, --stdin, --status,"
            " or --build-engine",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        payload = _load_json_payload(args.from_json, args.stdin)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(
            _do_update_item(
                args.item_id,
                payload,
                args.status,
                args.build_engine,
                args.version,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def _do_add_item(
    project_id: str | None,
    payload: dict[str, Any],
    status: str | None,
    labels_cli: list[str] | None,
) -> str:
    """Create a new GTD item with full structured field support.

    Routes directly through item_service.create_item in local mode so that
    heavy fields (acceptance_criteria, files_to_modify, scope_out, build_engine)
    are persisted — bypassing backend.create_item which drops them.

    In HTTP mode issues a direct POST /api/items (also bypasses
    HttpBackend.create_item for the same reason).

    Args:
        project_id: Optional project UUID to associate the new item with.
        payload: JSON dict that MUST contain ``title`` plus any of:
            description, acceptance_criteria, files_to_modify, scope_out,
            labels, build_engine.
        status: Override status (defaults to ``inbox`` when None).
        labels_cli: Labels from the CLI ``--labels`` flag (takes precedence
            over ``labels`` in the JSON payload).

    Returns:
        UUID string of the newly created item.

    Raises:
        ValueError: If ``title`` is absent from *payload*.
        RuntimeError: If AGENT_GTD_API_KEY is required but not set.
        ValidationError: (LocalBackend) If build_engine or status is invalid.
        ToolError: (HttpBackend) If the API returns an error.
    """
    if "title" not in payload:
        raise ValueError("JSON payload must include 'title'")

    title = str(payload["title"])
    description = str(payload.get("description", ""))
    acceptance_criteria: list[str] | None = payload.get("acceptance_criteria")
    files_to_modify: list[dict[str, Any]] | None = payload.get("files_to_modify")
    scope_out: list[str] | None = payload.get("scope_out")
    build_engine: str | None = (
        str(payload["build_engine"]) if "build_engine" in payload else None
    )
    # CLI --labels takes precedence over JSON "labels" when both are present.
    labels: list[str] | None = (
        labels_cli if labels_cli is not None else payload.get("labels")
    )
    final_status = status or "inbox"

    backend = create_backend()
    try:
        if not os.environ.get("AGENT_GTD_URL", ""):
            # Local mode: call item_service.create_item directly so that heavy
            # fields (ac/ftm/scope_out/build_engine) are NOT dropped.
            from agent_gtd.database import LOCAL_USER_ID, get_db, init_db
            from agent_gtd.services import item_service

            await init_db()
            db = await get_db()
            row = await item_service.create_item(
                db,
                LOCAL_USER_ID,
                title=title,
                description=description,
                labels=labels,
                status=final_status,
                build_engine=build_engine,
                acceptance_criteria=acceptance_criteria,
                files_to_modify=files_to_modify,
                scope_out=scope_out,
                project_id=project_id,
            )
            return str(row["id"])
        else:
            # HTTP mode: POST /api/items directly (bypasses HttpBackend.create_item
            # which omits the heavy fields from the request body).
            api_key = os.environ.get("AGENT_GTD_API_KEY", "")
            if not api_key:
                raise RuntimeError("AGENT_GTD_API_KEY environment variable is required")
            await backend.login(api_key, "cli")
            base_url = os.environ.get("AGENT_GTD_URL", "").rstrip("/")
            item = await _http_post_create_item(
                base_url,
                api_key,
                title=title,
                description=description,
                labels=labels,
                status=final_status,
                build_engine=build_engine,
                acceptance_criteria=acceptance_criteria,
                files_to_modify=files_to_modify,
                scope_out=scope_out,
                project_id=project_id,
            )
            return str(item["id"])
    finally:
        await backend.close()


def _cmd_add_item(args: argparse.Namespace) -> None:
    """Execute the add-item subcommand.

    Prints the new item's UUID to stdout (and nothing else) on success.

    Args:
        args: Parsed namespace containing project, from_json, stdin, status,
            and labels.
    """
    try:
        payload = _load_json_payload(args.from_json, args.stdin)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Flatten and split labels — supports both ``--labels a,b`` and
    # ``--labels a --labels b``.
    labels_cli: list[str] | None = None
    if args.labels:
        labels_cli = [
            lbl.strip() for raw in args.labels for lbl in raw.split(",") if lbl.strip()
        ]

    try:
        new_id = asyncio.run(
            _do_add_item(
                args.project,
                payload,
                args.status,
                labels_cli,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(new_id)


def main() -> None:
    """Entry point for the agent-gtd CLI."""
    parser = argparse.ArgumentParser(
        prog="agent-gtd",
        description="Agent GTD command-line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- run-status ---
    rs = subparsers.add_parser(
        "run-status",
        help="Print dispatch run status as JSON to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print a dispatch run's current status as JSON.  With --wait, block\n"
            "until the run reaches a terminal state and exit with a status code\n"
            "that reflects the outcome:\n\n"
            "  0   terminal success  (status=success)\n"
            "  2   terminal failure  (status=failed|cancelled|error|timeout)\n"
            "  124 client --timeout exceeded (last-fetched JSON goes to stderr)\n"
            "  1   operational error (auth / network / not-found)\n"
        ),
    )
    rs.add_argument("run_id", help="Dispatch run ID.")
    rs.add_argument(
        "--wait",
        action="store_true",
        default=False,
        help=(
            "Block until the run reaches a terminal state "
            "(success|failed|cancelled|error|timeout), then print the final "
            "status JSON and exit with the appropriate exit code."
        ),
    )
    rs.add_argument(
        "--poll-interval",
        type=float,
        default=30,
        metavar="SECONDS",
        help=(
            "Seconds between status polls (default: 30; minimum 5 — "
            "values below 5 are clamped up to 5)."
        ),
    )
    rs.add_argument(
        "--timeout",
        type=float,
        default=0,
        metavar="SECONDS",
        help=(
            "Maximum seconds to wait before giving up (default: 0 = wait "
            "indefinitely).  On expiry, the last-fetched JSON is written to "
            "stderr and the process exits with code 124."
        ),
    )

    # --- rollout-status ---
    rls = subparsers.add_parser(
        "rollout-status",
        help="Print autonomous rollout status as JSON to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print a rollout's current status as JSON.  With --wait, block\n"
            "until the rollout reaches a terminal state and exit with a status\n"
            "code that reflects the outcome:\n\n"
            "  0   terminal success  (status=completed)\n"
            "  2   terminal failure  (status=failed|halted|cancelled)\n"
            "  124 client --timeout exceeded (last-fetched JSON goes to stderr)\n"
            "  1   operational error (auth / network / not-found)\n"
        ),
    )
    rls.add_argument("rollout_id", help="Autonomous rollout ID.")
    rls.add_argument(
        "--wait",
        action="store_true",
        default=False,
        help=(
            "Block until the rollout reaches a terminal state "
            "(completed|failed|halted|cancelled), then print the final "
            "status JSON and exit with the appropriate exit code."
        ),
    )
    rls.add_argument(
        "--poll-interval",
        type=float,
        default=30,
        metavar="SECONDS",
        help=(
            "Seconds between status polls (default: 30; minimum 5 — "
            "values below 5 are clamped up to 5)."
        ),
    )
    rls.add_argument(
        "--timeout",
        type=float,
        default=0,
        metavar="SECONDS",
        help=(
            "Maximum seconds to wait before giving up (default: 0 = wait "
            "indefinitely).  On expiry, the last-fetched JSON is written to "
            "stderr and the process exits with code 124."
        ),
    )

    # --- promote-admin ---
    pa = subparsers.add_parser(
        "promote-admin",
        help="Set is_admin=1 on the user with the given email (direct DB update).",
    )
    pa.add_argument("email", help="Email of the user to promote.")

    # --- update-item ---
    ui = subparsers.add_parser(
        "update-item",
        help="Update a GTD item's fields from a JSON file or stdin.",
    )
    ui.add_argument("item_id", help="UUID of the item to update.")
    ui_src = ui.add_mutually_exclusive_group()
    ui_src.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with fields to update.",
    )
    ui_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    ui.add_argument("--status", help="New status value.")
    ui.add_argument("--build-engine", help="New build engine preference.")
    ui.add_argument(
        "--version",
        type=int,
        help="Explicit optimistic-lock version (no auto-fetch, no retry on conflict).",
    )

    # --- add-item ---
    ai = subparsers.add_parser(
        "add-item",
        help="Create a new GTD item from a JSON file or stdin; prints UUID to stdout.",
    )
    ai.add_argument("--project", metavar="PROJECT_ID", help="Project UUID.")
    ai_src = ai.add_mutually_exclusive_group()
    ai_src.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with item fields (must include 'title').",
    )
    ai_src.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read JSON payload from stdin.",
    )
    ai.add_argument("--status", help="Item status (default: inbox).")
    ai.add_argument(
        "--labels",
        action="append",
        metavar="LABELS",
        help="Labels (repeatable; comma-separated values accepted per flag).",
    )

    args = parser.parse_args()

    if args.command == "run-status":
        _cmd_run_status(args)
    elif args.command == "rollout-status":
        _cmd_rollout_status(args)
    elif args.command == "promote-admin":
        _cmd_promote_admin(args.email)
    elif args.command == "update-item":
        _cmd_update_item(args)
    elif args.command == "add-item":
        _cmd_add_item(args)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)
