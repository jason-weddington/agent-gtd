"""MCP-to-CLI surface parity tests (wave-final guard).

This test enforces that every MCP tool exposed by the FastMCP registry has a
corresponding ``agent-gtd`` CLI subcommand (and vice versa, modulo a small set
of sanctioned exceptions). Parity is asserted *structurally* by comparing the
two live registries — the MCP tool set and the argparse subparser choices —
rather than against any hardcoded list of names or tool-count literal. A future
MCP tool added without a matching CLI subcommand (or a CLI subcommand with no
MCP counterpart) makes this test go red and names the specific gap.

MCP side: introspects the live FastMCP registry via ``await mcp.list_tools()``.
CLI side: introspects the live argparse subparser registry via item 1's
``build_parser()`` factory.
"""

import argparse

# ``agent_gtd`` ships no ``py.typed`` marker, so mypy treats the package as an
# untyped third-party import when this test file is type-checked directly via
# ``uv run --frozen mypy tests/test_cli_parity.py`` (the enforcing command —
# the pre-commit hook only runs ``mypy src/`` and never covers tests/). The
# targeted ignores keep that command at exit 0 for this file.
from agent_gtd.cli import build_parser  # type: ignore[import-untyped]
from agent_gtd.mcp_server import mcp  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Parity constants
# ---------------------------------------------------------------------------

# MCP tools with no CLI counterpart by design. ``login`` is auth-bootstrap only
# and is env-resolved on the CLI side, so it never gets a subcommand.
#
# NB: this is subtracted from mcp_names UNCONDITIONALLY — no skipif, no env
# guard. ``_show_login = _needs_login()`` is computed at mcp_server import time
# from inherited env, and tests/conftest.py sanitizes only
# AGENT_GTD_AGENT_NAME (NOT AGENT_GTD_URL / AGENT_GTD_API_KEY), so whether
# ``login`` appears in ``list_tools()`` is env-dependent. We must therefore
# subtract it in every environment rather than copying test_mcp_tools.py's
# ``_show_login`` + skipif pattern (which is for login-behavior tests, not
# surface parity).
MCP_ONLY_EXCLUSIONS = {"login"}

# MCP tool name -> CLI subcommand name, for the two commands whose CLI names
# predate the parity convention. Every other tool maps by the kebab rule
# (underscores -> hyphens).
ALIAS_MAP = {
    "get_run_status": "run-status",
    "get_rollout": "rollout-status",
}

# CLI subcommands that legitimately have no MCP counterpart. ``promote-admin``
# is a local operational command (direct DB update), not a GTD tool.
CLI_ONLY_EXTRAS = {"promote-admin"}


def _cli_names() -> set[str]:
    """Return the live set of registered CLI subcommand names."""
    sub_actions = [
        a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    return set(sub_actions[0].choices)


async def _mcp_names() -> set[str]:
    """Return the live set of MCP tool names from the FastMCP registry."""
    tools = await mcp.list_tools()
    return {t.name for t in tools}


def _expected_cli_names(mcp_names: set[str]) -> set[str]:
    """Map non-excluded MCP tool names to their expected CLI subcommands."""
    return {
        ALIAS_MAP.get(n, n.replace("_", "-")) for n in (mcp_names - MCP_ONLY_EXCLUSIONS)
    }


# ---------------------------------------------------------------------------
# Forward parity: every MCP tool has a CLI subcommand
# ---------------------------------------------------------------------------


async def test_every_mcp_tool_has_cli_subcommand() -> None:
    """Every non-excluded MCP tool maps to a registered CLI subcommand."""
    mcp_names = await _mcp_names()
    expected_cli_names = _expected_cli_names(mcp_names)
    cli_names = _cli_names()

    missing = expected_cli_names - cli_names
    assert not missing, f"MCP tools with no CLI subcommand: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Reverse parity: no unexpected CLI subcommands
# ---------------------------------------------------------------------------


async def test_no_unexpected_cli_subcommands() -> None:
    """No CLI subcommand lacks an MCP tool beyond the sanctioned extras."""
    mcp_names = await _mcp_names()
    expected_cli_names = _expected_cli_names(mcp_names)
    cli_names = _cli_names()

    extras = cli_names - expected_cli_names - CLI_ONLY_EXTRAS
    assert not extras, (
        f"CLI subcommands with no MCP tool (and not a sanctioned extra): "
        f"{sorted(extras)}"
    )


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_no_duplicate_aliased_subcommands() -> None:
    """Aliased tools must not also register kebab-cased duplicates.

    ``get_run_status`` -> ``run-status`` and ``get_rollout`` -> ``rollout-status``
    via ALIAS_MAP; the raw kebab forms must be absent (disposition 2 guard).
    """
    cli_names = _cli_names()
    assert {"get-run-status", "get-rollout"} & cli_names == set()


def test_base_commands_survive_refactor() -> None:
    """The 5 pre-existing base commands survive item 1's refactor."""
    cli_names = _cli_names()
    assert {
        "run-status",
        "rollout-status",
        "promote-admin",
        "update-item",
        "add-item",
    } <= cli_names


def test_login_has_no_cli_subcommand() -> None:
    """The excluded MCP tool (login) has no CLI counterpart by design."""
    cli_names = _cli_names()
    assert "login" not in cli_names
