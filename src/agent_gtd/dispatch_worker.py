"""Background dispatch worker for headless Claude Code agents.

Manages the full lifecycle: clone repo, launch Claude Code subprocess,
capture output, update run status, post comments, publish SSE events.
"""

import asyncio
import logging
import os
import re
import signal
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path.home() / "claude-workspace"
TIMEOUT_SECONDS = 30 * 60  # 30 minutes hard kill
MAX_CONCURRENT = 3

# Env vars the subprocess is allowed to inherit
_SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TERM",
    "SHELL",
    "ANTHROPIC_API_KEY",
    "SSH_AUTH_SOCK",
    "GIT_SSH_COMMAND",
    "AGENT_GTD_URL",
    "AGENT_GTD_API_KEY",
    "KB_DATABASE_URL",
}

# ---------------------------------------------------------------------------
# Workspace helpers
# ---------------------------------------------------------------------------


def _repo_name_from_origin(origin: str) -> str:
    """Extract a clean repo name from a git origin URL."""
    match = re.search(r"[/:]([^/:]+/[^/:]+?)(?:\.git)?$", origin)
    if match:
        return match.group(1).replace("/", "-")
    parsed = urlparse(origin)
    return Path(parsed.path).stem or "unknown"


def _prepare_workspace(origin: str, item_id: str) -> Path:
    """Clone or update the repo into a workspace directory."""
    short_id = item_id[:8]
    name = _repo_name_from_origin(origin)
    workspace = WORKSPACE_ROOT / f"{name}-{short_id}"

    if workspace.exists():
        logger.info("Workspace exists, pulling latest: %s", workspace)
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=workspace,
            check=False,
            capture_output=True,
        )
    else:
        logger.info("Cloning %s -> %s", origin, workspace)
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", origin, str(workspace)],
            check=True,
        )

    # Install pre-commit hooks if the project uses them
    if (workspace / ".pre-commit-config.yaml").exists():
        logger.info("Installing pre-commit hooks...")
        subprocess.run(
            [
                "pre-commit",
                "install",
                "--hook-type",
                "pre-commit",
                "--hook-type",
                "commit-msg",
                "--hook-type",
                "post-commit",
                "--hook-type",
                "pre-push",
            ],
            cwd=workspace,
            check=False,
            capture_output=True,
        )

    return workspace


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def _build_system_prompt(
    item: dict[str, Any],
    project: dict[str, Any],
    branch_name: str,
    max_turns: int,
) -> str:
    """Build the headless agent system prompt."""
    item_id = str(item["id"])
    title = str(item["title"])
    description = str(item.get("description", ""))
    project_name = str(project["name"])
    kb_ref = str(project.get("kb_project_ref", ""))

    kb_section = ""
    if kb_ref:
        kb_section = textwrap.dedent(f"""\

        ## Knowledge Base

        A personal-kb MCP server is available. Before starting work, run:
        ```
        kb_preflight(project_ref="{kb_ref}")
        ```
        This will surface recent decisions, conventions, and lessons learned
        for this project. Search the KB before guessing or asking questions.
        When you learn something non-obvious during this task, store it with
        `kb_store(project_ref="{kb_ref}")`.
        """)

    return textwrap.dedent(f"""\
        You are a headless Claude Code agent dispatched by Agent GTD.
        No human is available for questions — you must work autonomously.

        ## Your Task

        **Project:** {project_name}
        **Item:** {title}
        **Item ID:** {item_id}

        {f"**Description:**{chr(10)}{description}" if description else "No description provided — work from the title only."}

        ## Rules

        1. **Understand first.** Read the codebase, understand the patterns, then act.
        2. **Branch.** Create and work on the branch `{branch_name}`. Never commit to main.
        3. **Test.** Run the project's test suite before committing. Fix failures.
        4. **Commit.** Use conventional commit messages. Small, focused commits.
        5. **Push.** When done, push `{branch_name}` to origin.
        6. **Stop if stuck.** If the task is too ambiguous, you lack information, or
           you cannot complete it cleanly — STOP. Do not guess or produce low-quality work.
        {kb_section}
        ## Reporting

        When you finish (success or blocked), post a comment to the GTD item.
        The Agent GTD MCP server is available — use `add_comment` with item_id="{item_id}".

        **On success**, your comment should include:
        - What you did (1-3 sentences)
        - The branch name: `{branch_name}`
        - Any notes for the reviewer

        **On failure/blocked**, your comment should include:
        - Why you stopped
        - What information or clarification you need
        - Any partial progress (if you pushed commits)

        ## Important

        - You have max {max_turns} turns. Budget them wisely.
        - Never force-push, never push to main, never delete branches you didn't create.
        - Never modify CI/CD configs, deployment scripts, or secrets.
        - Focus only on this task. Don't fix unrelated issues you notice.
    """)


# ---------------------------------------------------------------------------
# Sanitized environment
# ---------------------------------------------------------------------------


def _build_env() -> dict[str, str]:
    """Build a sanitized environment for the subprocess."""
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["HOME"] = str(Path.home())
    return env


# ---------------------------------------------------------------------------
# Single run executor
# ---------------------------------------------------------------------------


async def _update_run(
    db: Any,
    run_id: str,
    **fields: object,
) -> None:
    """Update fields on a claude_runs row."""
    now = datetime.now(UTC).isoformat()
    updates = ["updated_at = $1"]
    params: list[object] = [now]

    for key, value in fields.items():
        params.append(value)
        updates.append(f"{key} = ${len(params)}")

    params.append(run_id)
    sql = (
        f"UPDATE claude_runs SET {', '.join(updates)}"  # noqa: S608
        f" WHERE id = ${len(params)}"
    )
    await db.execute(sql, *params)


async def _post_comment(db: Any, user_id: str, item_id: str, content: str) -> None:
    """Post a comment on an item (best-effort, never raises)."""
    try:
        from agent_gtd.services.comment_service import create_comment

        await create_comment(
            db,
            user_id,
            item_id=item_id,
            content_markdown=content,
            created_by="claude-dispatch",
        )
    except Exception:
        logger.exception("Failed to post dispatch comment on item %s", item_id)


async def execute_run(
    db: Any,
    run: dict[str, Any],
    item: dict[str, Any],
    project: dict[str, Any],
) -> None:
    """Execute a single dispatch run (clone, launch, capture, cleanup).

    Updates the run row in the database as it progresses through states.
    Posts comments to the GTD item at start and end.
    """
    run_id = str(run["id"])
    item_id = str(run["item_id"])
    user_id = str(run["user_id"])
    branch = str(run["feature_branch"])
    max_turns = int(str(run["max_turns"]))
    git_origin = str(project["git_origin"])

    # --- Cloning ---
    await _update_run(db, run_id, status="cloning")

    try:
        workspace = await asyncio.to_thread(_prepare_workspace, git_origin, item_id)
    except Exception as e:
        logger.exception("Clone failed for run %s", run_id)
        now = datetime.now(UTC).isoformat()
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=now,
            error_msg=f"Clone failed: {e}",
        )
        await _post_comment(
            db,
            user_id,
            item_id,
            f"Dispatch failed: could not clone `{git_origin}`.\n\n```\n{e}\n```",
        )
        return

    await _update_run(
        db,
        run_id,
        status="running",
        workspace_dir=str(workspace),
        started_at=datetime.now(UTC).isoformat(),
    )

    # Post started comment
    await _post_comment(
        db,
        user_id,
        item_id,
        f"Agent started. Working on branch `{branch}` in `{project['name']}`.",
    )

    # Publish SSE event
    try:
        from agent_gtd.event_bus import get_event_bus

        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="run_started",
            entity_type="run",
            entity_id=run_id,
            project_id=str(run["project_id"]),
            payload={"run_id": run_id, "item_id": item_id, "branch": branch},
        )
    except Exception:
        logger.exception("Failed to publish run_started event")

    # --- Launch Claude Code ---
    prompt = _build_system_prompt(item, project, branch, max_turns)
    env = _build_env()
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--max-turns",
        str(max_turns),
        "--append-system-prompt",
        prompt,
        "--print",
        str(item["title"]),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        # Store PID for potential kill
        await _update_run(db, run_id, pid=proc.pid)

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT_SECONDS
            )
        except TimeoutError:
            # Kill the entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                await asyncio.sleep(5)
                if proc.returncode is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            now = datetime.now(UTC).isoformat()
            await _update_run(
                db,
                run_id,
                status="timeout",
                finished_at=now,
                error_msg=f"Timed out after {TIMEOUT_SECONDS // 60} minutes",
            )
            await _post_comment(
                db,
                user_id,
                item_id,
                f"Agent timed out after {TIMEOUT_SECONDS // 60} minutes. "
                "The task may need to be broken down into smaller pieces.",
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
            return

        # --- Process completed ---
        exit_code = proc.returncode or 0
        stdout_text = stdout.decode(errors="replace") if stdout else ""
        stderr_text = stderr.decode(errors="replace") if stderr else ""
        now = datetime.now(UTC).isoformat()

        if exit_code == 0:
            await _update_run(
                db,
                run_id,
                status="success",
                finished_at=now,
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_completed")
        else:
            truncated_err = (
                stderr_text[-500:] if len(stderr_text) > 500 else stderr_text
            )
            await _update_run(
                db,
                run_id,
                status="failed",
                finished_at=now,
                error_msg=f"Exit code {exit_code}: {truncated_err}",
            )
            await _post_comment(
                db,
                user_id,
                item_id,
                f"Agent exited with code {exit_code}.\n\n```\n{truncated_err}\n```",
            )
            _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")

        if stdout_text:
            logger.info(
                "Run %s output (last 1000 chars): %s",
                run_id,
                stdout_text[-1000:],
            )

    except FileNotFoundError:
        now = datetime.now(UTC).isoformat()
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=now,
            error_msg="'claude' command not found — is Claude Code installed?",
        )
        await _post_comment(
            db,
            user_id,
            item_id,
            "Dispatch failed: `claude` command not found on the server.",
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")
    except Exception as e:
        logger.exception("Unexpected error in run %s", run_id)
        now = datetime.now(UTC).isoformat()
        await _update_run(
            db,
            run_id,
            status="failed",
            finished_at=now,
            error_msg=str(e)[:500],
        )
        await _post_comment(
            db,
            user_id,
            item_id,
            f"Dispatch failed unexpectedly: {e}",
        )
        _publish_run_event(db, user_id, run_id, item_id, run, "run_failed")


def _publish_run_event(
    db: Any,
    user_id: str,
    run_id: str,
    item_id: str,
    run: dict[str, Any],
    event_type: str,
) -> None:
    """Fire-and-forget SSE event publish (best effort)."""
    try:
        from agent_gtd.event_bus import get_event_bus

        bus = get_event_bus()
        asyncio.create_task(
            bus.publish(
                db,
                user_id=user_id,
                event_type=event_type,
                entity_type="run",
                entity_id=run_id,
                project_id=str(run["project_id"]),
                payload={"run_id": run_id, "item_id": item_id},
            )
        )
    except Exception:
        logger.exception("Failed to publish %s event", event_type)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

# Module-level queue — set during app startup
_dispatch_queue: asyncio.Queue[str] | None = None
_semaphore: asyncio.Semaphore | None = None


def get_dispatch_queue() -> asyncio.Queue[str]:
    """Get the dispatch queue (must be called after startup)."""
    assert _dispatch_queue is not None, "Dispatch worker not started"  # noqa: S101
    return _dispatch_queue


async def dispatch_worker() -> None:
    """Background worker that drains the dispatch queue."""
    global _dispatch_queue, _semaphore
    _dispatch_queue = asyncio.Queue()
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    logger.info("Dispatch worker started (max %d concurrent)", MAX_CONCURRENT)

    while True:
        run_id = await _dispatch_queue.get()
        asyncio.create_task(_process_run(run_id))


async def _process_run(run_id: str) -> None:
    """Process a single run with concurrency limiting."""
    assert _semaphore is not None  # noqa: S101

    async with _semaphore:
        try:
            from agent_gtd.database import get_db
            from agent_gtd.services.item_service import (
                get_item as svc_get_item,
            )
            from agent_gtd.services.project_service import (
                get_project as svc_get_project,
            )

            db = await get_db()
            # Fetch run — use a direct query since get_run needs user_id
            row = await db.fetchrow("SELECT * FROM claude_runs WHERE id = $1", run_id)
            if row is None:
                logger.error("Run %s not found, skipping", run_id)
                return

            from agent_gtd.database import row_to_dict

            run = row_to_dict(row)

            if run["status"] not in ("pending",):
                logger.warning("Run %s status is %s, skipping", run_id, run["status"])
                return

            user_id = str(run["user_id"])
            item = await svc_get_item(db, user_id, str(run["item_id"]))
            project = await svc_get_project(db, user_id, str(run["project_id"]))

            await execute_run(db, run, item, project)

        except Exception:
            logger.exception("Fatal error processing run %s", run_id)


def enqueue_run(run_id: str) -> None:
    """Add a run to the dispatch queue."""
    queue = get_dispatch_queue()
    queue.put_nowait(run_id)
    logger.info("Enqueued run %s", run_id)


async def shutdown_worker() -> None:
    """Graceful shutdown — cancel pending queue items."""
    global _dispatch_queue
    if _dispatch_queue is not None:
        # Drain remaining items
        while not _dispatch_queue.empty():
            try:
                _dispatch_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        _dispatch_queue = None
    logger.info("Dispatch worker shut down")
