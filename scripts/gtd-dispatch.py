#!/usr/bin/env python3
# ruff: noqa
"""Dispatch a GTD item to a headless Claude Code agent.

Usage:
    python scripts/gtd-dispatch.py <item-id>

Requires:
    AGENT_GTD_URL   - Base URL of the Agent GTD API
    AGENT_GTD_API_KEY - API key for authentication

The script:
1. Fetches the item and its project from the GTD API
2. Validates the project has a git_origin configured
3. Clones (or updates) the repo to ~/claude-workspace/<repo>-<item-short-id>/
4. Launches Claude Code headless with a tuned system prompt
5. Posts a result comment back to the GTD item
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path.home() / "claude-workspace"
MAX_TURNS = 20
TIMEOUT_SECONDS = 30 * 60  # 30 minutes hard kill

# Env vars the subprocess is allowed to inherit
_SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TERM",
    "SHELL",
    "ANTHROPIC_API_KEY",
    "SSH_AUTH_SOCK",  # needed for git SSH
    "GIT_SSH_COMMAND",  # user may set for deploy keys
    "AGENT_GTD_URL",  # agent needs to post comments back
    "AGENT_GTD_API_KEY",
    "PERSONAL_KB_URL",  # agent can search/update the knowledge base
    "PERSONAL_KB_API_KEY",
}


# ---------------------------------------------------------------------------
# GTD API client
# ---------------------------------------------------------------------------


def _api(method: str, path: str, **kwargs: object) -> dict:
    """Make an authenticated request to the GTD API."""
    base_url = os.environ.get("AGENT_GTD_URL", "")
    api_key = os.environ.get("AGENT_GTD_API_KEY", "")
    if not base_url or not api_key:
        print("Error: AGENT_GTD_URL and AGENT_GTD_API_KEY must be set", file=sys.stderr)
        sys.exit(1)

    url = f"{base_url}/api{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.request(method, url, headers=headers, verify=False, **kwargs)  # noqa: S501
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def get_item(item_id: str) -> dict:
    return _api("GET", f"/items/{item_id}")


def get_project(project_id: str) -> dict:
    return _api("GET", f"/projects/{project_id}")


def post_comment(item_id: str, content: str) -> None:
    _api(
        "POST",
        f"/items/{item_id}/comments",
        json={
            "content_markdown": content,
            "created_by": "claude-dispatch",
        },
    )


def update_item(item_id: str, **fields: object) -> None:
    _api("PATCH", f"/items/{item_id}", json=fields)


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------


def repo_name_from_origin(origin: str) -> str:
    """Extract a clean repo name from a git origin URL."""
    # Handle SSH (git@host:org/repo.git) and HTTPS
    match = re.search(r"[/:]([^/:]+/[^/:]+?)(?:\.git)?$", origin)
    if match:
        return match.group(1).replace("/", "-")
    # Fallback: use the last path component
    parsed = urlparse(origin)
    return Path(parsed.path).stem or "unknown"


def prepare_workspace(origin: str, item_id: str) -> Path:
    """Clone or update the repo into a workspace directory."""
    short_id = item_id[:8]
    name = repo_name_from_origin(origin)
    workspace = WORKSPACE_ROOT / f"{name}-{short_id}"

    if workspace.exists():
        print(f"  Workspace exists, pulling latest: {workspace}")
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=workspace,
            check=False,
            capture_output=True,
        )
    else:
        print(f"  Cloning {origin} -> {workspace}")
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", origin, str(workspace)],
            check=True,
        )

    return workspace


# ---------------------------------------------------------------------------
# Branch naming
# ---------------------------------------------------------------------------


def make_branch_name(item: dict) -> str:
    """Build a branch name from an item ID and title."""
    short_id = item["id"][:8]
    slug = re.sub(r"[^a-z0-9]+", "-", item["title"].lower())[:40].strip("-")
    return f"feat/{short_id}-{slug}"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def build_system_prompt(item: dict, project: dict, branch_name: str) -> str:
    """Build the headless agent system prompt."""
    item_id = item["id"]
    title = item["title"]
    description = item.get("description", "")
    project_name = project["name"]

    prompt = textwrap.dedent(f"""\
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

        - You have max {MAX_TURNS} turns. Budget them wisely.
        - Never force-push, never push to main, never delete branches you didn't create.
        - Never modify CI/CD configs, deployment scripts, or secrets.
        - Focus only on this task. Don't fix unrelated issues you notice.
    """)
    return prompt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch a GTD item to Claude Code")
    parser.add_argument("item_id", help="GTD item ID to dispatch")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the prompt without launching"
    )
    parser.add_argument(
        "--max-turns", type=int, default=MAX_TURNS, help="Max agent turns"
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Remove workspace after run"
    )
    args = parser.parse_args()

    print(f"Fetching item {args.item_id}...")
    item = get_item(args.item_id)
    print(f"  Title: {item['title']}")

    project_id = item.get("project_id")
    if not project_id:
        print(
            "Error: Item has no project assigned. Assign it to a project first.",
            file=sys.stderr,
        )
        sys.exit(1)

    project = get_project(project_id)
    print(f"  Project: {project['name']}")

    git_origin = project.get("git_origin", "")
    if not git_origin:
        print(
            f"Error: Project '{project['name']}' has no git_origin configured.",
            file=sys.stderr,
        )
        print("  Set it in the project edit dialog or via the API.", file=sys.stderr)
        sys.exit(1)

    print(f"  Git origin: {git_origin}")

    branch_name = make_branch_name(item)
    system_prompt = build_system_prompt(item, project, branch_name)

    if args.dry_run:
        print("\n--- System Prompt ---")
        print(system_prompt)
        print("--- End ---")
        return

    # Prepare workspace
    print("Preparing workspace...")
    workspace = prepare_workspace(git_origin, args.item_id)

    # Build sanitized environment
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["HOME"] = str(Path.home())  # ensure HOME is set

    # Build claude command
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--max-turns",
        str(args.max_turns),
        "--append-system-prompt",
        system_prompt,
        "--print",
        item["title"],
    ]

    print(
        f"Launching Claude Code (max {args.max_turns} turns, timeout {TIMEOUT_SECONDS}s)..."
    )
    print(f"  Working directory: {workspace}")

    # Post a "started" comment
    post_comment(
        args.item_id,
        f"Agent dispatched. Working on branch `{branch_name}` in `{project['name']}`.",
    )

    try:
        result = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        print(f"Claude Code exited with code {result.returncode}")
        if result.stdout:
            # Truncate output for display
            output = (
                result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
            )
            print(output)

        if result.returncode != 0 and result.stderr:
            print(f"STDERR: {result.stderr[-500:]}", file=sys.stderr)
            post_comment(
                args.item_id,
                f"Agent exited with code {result.returncode}.\n\n```\n{result.stderr[-500:]}\n```",
            )

    except subprocess.TimeoutExpired:
        print(f"Error: Claude Code timed out after {TIMEOUT_SECONDS}s", file=sys.stderr)
        post_comment(
            args.item_id,
            f"Agent timed out after {TIMEOUT_SECONDS // 60} minutes. "
            "The task may need to be broken down into smaller pieces.",
        )
    except FileNotFoundError:
        print(
            "Error: 'claude' command not found. Is Claude Code installed?",
            file=sys.stderr,
        )
        sys.exit(1)

    # Optional cleanup
    if args.cleanup and workspace.exists():
        print(f"Cleaning up workspace: {workspace}")
        shutil.rmtree(workspace)

    print("Done.")


if __name__ == "__main__":
    main()
