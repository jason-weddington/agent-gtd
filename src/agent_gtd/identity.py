"""Actor identity helpers for agent-level observability.

Cutover date: 2026-05-13. Comments predating this date have
created_by = "mcp-agent" (former default). That is expected and normal.

The helpers live here rather than in auth.py because they are pure
transformations on run/session data, not authentication logic.
"""

import os


def compute_run_attribution(mode: str, run_id: str) -> str:
    """Return created_by attribution for a dispatched agent run.

    Args:
        mode: Run mode — ``"build"``, ``"plan"``, or ``"manage"``.
        run_id: Full UUID from the ``claude_runs.id`` column.

    Returns:
        e.g. ``"claude-build-abc12345"`` (mode + first 8 chars of run_id).
    """
    return f"claude-{mode}-{run_id[:8]}"


def compute_lead_attribution(user_id: str) -> str:
    """Return created_by for an interactive lead session.

    Used when ``AGENT_GTD_AGENT_NAME`` is not set — i.e. the interactive
    Claude Code lead in the user's terminal.

    Args:
        user_id: Full UUID from ``users.id``.

    Returns:
        e.g. ``"claude-lead-4a3b2c1d"`` (first 8 chars of user_id).
    """
    return f"claude-lead-{user_id[:8]}"


def get_current_actor_attribution() -> str:
    """Get the created_by attribution for the current actor.

    Resolves in order:
    1. If AGENT_GTD_AGENT_NAME env var is set, use that (dispatched agent run)
    2. Otherwise, return "human" (interactive/API caller with no agent name)

    Returns:
        The appropriate created_by value (e.g. "claude-plan-abc12345",
        "claude-build-xyz", or "human").
    """
    agent_name = os.environ.get("AGENT_GTD_AGENT_NAME")
    if agent_name:
        return agent_name
    return "human"
