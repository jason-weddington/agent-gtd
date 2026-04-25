# Feature: CLI Run Status Command

## Overview
Add a `agent-gtd run-status <run_id>` CLI command that exposes dispatch run status as JSON on stdout. This enables efficient shell-based monitoring of headless dispatch agents without going through the MCP transport — enabling the Bash+Monitor pattern (background poller + Monitor wakeup) instead of expensive periodic MCP polling.

## User Stories
- As a lead session, I want to run `agent-gtd run-status <run_id>` from a background script so that I can monitor dispatch completion without burning MCP polling turns.
- As a shell user, I want JSON output on stdout and errors on stderr so that I can pipe the result to `jq` cleanly.

## Design Decisions
- **argparse** (stdlib) — no new deps (click/typer not needed for a single subcommand)
- **Auth parity with MCP server**: env-var check (`AGENT_GTD_URL`) determines local vs HTTP mode, same as `mcp_server._get_session`
- **`create_backend()` reuse**: identical factory to MCP server; no duplicate auth logic
- **`json.dump(..., default=str)`**: handles datetime objects from `row_to_dict` without extra conversion
- **Exit code 0/1**: success/failure — shell-script friendly

## API Surface
```
agent-gtd run-status <run_id>
```
Stdout (success): JSON object with at minimum: `id`, `item_id`, `status`, `started_at`, `finished_at`, `feature_branch`, `error_msg`
Stderr (failure): human-readable error message
Exit code: 0 = success, 1 = any error

## Module Structure
```
src/agent_gtd/cli.py
  _fetch_run_status(run_id)  # async — creates backend, authenticates, calls get_run
  _cmd_run_status(run_id)    # sync — asyncio.run wrapper, capsys-testable
  main()                     # argparse entry point
```

## Definition of Done
- [x] `agent-gtd run-status <run_id>` exists as a shell command post `uv sync`
- [x] Stdout is valid JSON on success with required fields
- [x] Exit code 0 on success, 1 on any error
- [x] Errors printed to stderr only; stdout stays JSON-clean
- [x] Auth uses same env vars as MCP server
- [x] `uv run pytest -x` passes including new CLI tests
- [x] `uv run pytest tests/test_mcp_tools.py tests/test_mcp_backend.py` unchanged
- [x] `uv run ruff check` and `uv run mypy` pass
