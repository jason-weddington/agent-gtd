# Agent GTD

A full-stack [Getting Things Done](https://gettingthingsdone.com/) app with an MCP server for AI agent integration. FastAPI + React 19, with PostgreSQL or zero-config SQLite.

## Quick Start (Local Mode)

No database setup required. The app uses SQLite and skips authentication automatically.

```bash
# Install dependencies
uv sync
npm --prefix frontend install

# Start both backend (port 8000) and frontend (port 5173)
./start.sh
```

Open http://localhost:5173. That's it.

## Quick Start (PostgreSQL)

```bash
# Create the database
createdb agent_gtd

# Configure environment
cp .env.example .env
# Edit .env: set AGENT_GTD_DATABASE_URL and JWT_SECRET

# Install and seed
uv sync
npm --prefix frontend install
uv run python scripts/seed.py   # Creates admin user (admin@local / admin)

# Start
./start.sh
```

## MCP Server

The app includes an MCP server for managing GTD items from AI agents (Claude Code, etc.).

### Local mode

In local mode (no `AGENT_GTD_DATABASE_URL`), the MCP server uses SQLite and auto-authenticates — no setup needed.

### Multi-user mode (PostgreSQL)

Authentication uses API keys. Get one, set it in your environment, and the MCP server handles the rest.

**1. Get an API key**

Either generate one with the seed script:

```bash
uv run python scripts/seed.py   # Prints the key
```

Or log into the web UI, go to **Settings > API Access**, and create one there.

**2. Set `AGENT_GTD_URL` and `AGENT_GTD_API_KEY` in your environment**

Both vars are required when talking to a remote server. `AGENT_GTD_URL` is the
base URL of the running app (e.g. `https://agent-gtd.example.com`); `AGENT_GTD_API_KEY`
is the key from step 1. How you set them is up to you:

```bash
# Shell profile (~/.zshrc, ~/.bashrc)
export AGENT_GTD_URL=https://agent-gtd.example.com
export AGENT_GTD_API_KEY=agtd_...

# direnv (.envrc)
export AGENT_GTD_URL=https://agent-gtd.example.com
export AGENT_GTD_API_KEY=agtd_...

# Claude Code MCP config (~/.claude.json)
"agent-gtd": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "/path/to/agent_gtd", "agent-gtd-mcp"],
  "env": {
    "AGENT_GTD_URL": "https://agent-gtd.example.com",
    "AGENT_GTD_API_KEY": "agtd_..."
  }
}
```

When the env vars are set, the MCP server auto-authenticates on first tool call. No explicit `login` step needed.

**Key management:** Create multiple keys (one per machine) from the Settings page. Revoke individually if a machine is lost or compromised.

### Available Tools

| Tool | Description |
|------|-------------|
| `login` | Authenticate with API key (not needed if env var is set) |
| `inbox_capture` | Quick-capture to inbox |
| `add_item` | Create an item with status, priority, labels |
| `update_item` | Update an existing item |
| `complete_item` | Mark an item done |
| `list_items` | List items (filter by status, project, etc.) |
| `get_item` | Get a single item by ID |
| `claim_item` / `release_item` | Lock/unlock items for concurrent agents |
| `add_note` / `update_note` | Create or update project notes |
| `list_notes` / `get_note` | Read project notes |
| `list_projects` / `add_project` | Manage projects |

## CLI

The same package ships an `agent-gtd` CLI that talks to the running server over
HTTP. It uses the **same `AGENT_GTD_URL` and `AGENT_GTD_API_KEY` env vars** as
the MCP server, so once those are set, the CLI works without further config.

Install it once as a `uv` tool from a local checkout of this repo:

```bash
uv tool install .              # from the repo root
agent-gtd --help               # available on $PATH afterwards
```

Re-run `uv tool install . --reinstall` after pulling new changes to refresh the
installed copy.

The CLI is the basis for the [event-driven monitoring](#event-driven-monitoring-dont-poll-on-a-timer)
pattern below — `agent-gtd run-status <run_id>` returns the same dispatch status
that the MCP `get_run_status` tool returns, so a lead agent can poll from the
shell and wake on completion instead of burning context on a timer.

## Development

```bash
uv run pytest                         # Run tests
uv run ruff check .                   # Lint
uv run mypy src/                      # Type check
npm --prefix frontend run test        # Frontend tests

# Install git hooks (recommended)
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg \
  --hook-type post-commit --hook-type pre-push
```

## Steering Your Agents

Agent GTD uses a grooming workflow to maximize headless agent success rates. The key insight: agent productivity correlates directly with task clarity. Well-groomed tasks get one-shotted; vague tasks waste turns.

### The Grooming Ritual

All new tasks start in **New** status. Grooming moves them to **Ready**.

A task is **Ready** when:
- Acceptance criteria are clear and testable
- Files to modify and patterns to follow are identified
- Scope boundaries are explicit (what NOT to touch)
- Verification steps are defined (how to test)
- The task is not blocked by other work

### The Lifecycle

```
New → Ready → To Do → In Progress → Review → Done
         ↑ grooming    ↑ dispatch     ↑ agent     ↑ human
```

**Interactive sessions** (human + agent): Groom the backlog, review dispatched work, tackle ambiguous problems.

**Headless dispatch**: Pick up Ready/To Do tasks and execute autonomously. Agents post progress comments and set status to Review when done.

### Writing Good Task Descriptions

```markdown
## Problem
What's wrong or missing (1-2 sentences)

## Acceptance criteria
- [ ] Specific, testable criteria
- [ ] Each one independently verifiable

## Files to modify
- path/to/file.py — what to change

## Pattern to follow
Reference an existing implementation the agent can copy

## Scope boundary
Do NOT touch X, Y, Z
```

## Steering Your Agents — Autonomous Operations (Advanced)

The workflow above gets you to "ship one feature with one dispatched agent." Once that's comfortable, you can run a higher-throughput pattern where a single interactive "tech lead" session orchestrates multiple headless agents in parallel — one human approves a plan, then watches a wave of agents land branches over the next hour while doing other work.

This section assumes the basic grooming and dispatch flow is already familiar.

### Treat the interactive context as the scarce resource

The session that drives orchestration has a finite context window. Every token it spends reading files, grepping, or doing implementation work inline is a token it can't spend later on review, judgment, or coordinating the next wave. Past ~60% utilization, quality degrades noticeably.

**Default: dispatch the work, don't do it inline.** Even when "I could just edit this myself" feels faster in the moment, the cost shows up later as a session that runs out of room before the feature is done.

Inline work is justified when:
- It's a trivial (<5 line) edit where grooming + dispatch costs more than just doing it
- The decision genuinely needs live conversation context (mid-discussion architecture calls, debugging where the loop is "run, see, fix")
- You're reviewing or merging a dispatched branch — that *is* the control plane's job

Everything else — including "let me just read these files to understand X" or "I'll do a quick refactor while I'm here" — should become a groomed task and a dispatch.

### Plan-mode dispatch for research and grooming

`dispatch_item` exposes two modes:

- `mode="build"` — implement, push a feature branch, comment back on the item
- `mode="plan"` — groom: write acceptance criteria, identify files to modify, ask clarifying questions, and update the item description

Use `plan` mode for the research and exploration phase, not just implementation. The agent's exploration tokens don't count against the interactive session, and what comes back is a dispatch-ready task description.

### Wave-based parallelization

When a feature splits into N subtasks, you don't dispatch them sequentially:

1. **Read the "Files to modify" list** from each groomed task.
2. **Group non-overlapping tasks into waves.** Tasks with no file overlap and no dependency chain can run concurrently. Tasks that touch the same file become successive waves.
3. **Dispatch a wave**, monitor for completion, merge each as it lands, then dispatch the next wave once it's unblocked.

A typical wave 1 might run 3–6 agents in parallel; wave 2 picks up after the merges land.

### Event-driven monitoring (don't poll on a timer)

The `agent-gtd` CLI exposes dispatch status to the shell, so the lead agent can wake on completion instead of polling:

```bash
# After dispatching, run in background:
until [ "$(agent-gtd run-status <run_id> | jq -r .status)" != "running" ]; do
  sleep 30
done
echo "DONE <run_id>"
```

In Claude Code, pair `Bash` with `run_in_background: true` and the `Monitor` tool watching that background task. The `DONE` line arrives as a notification within ~30s of the run finishing. One poller + one Monitor per dispatched run; fan out N dispatches and arm N Monitors. Each completion fires its own wake-up.

This is materially better than scheduled wake-ups: the lead agent stays free to do other work between completions instead of burning context checking status on a timer.

### Per-completion review cycle

When a Monitor wakes the lead on a finished run:

1. Read the agent's final comment on the GTD item — note any flagged issues
2. Fetch the branch, diff it, squash-merge to `main` with a clean conventional-commit message
3. Fix small issues **inline** (lint, format, line-length, merge conflicts) — don't redispatch unless the agent's logic is actually wrong or it missed scope
4. Push, `complete_item`, delete local + remote feature branches
5. If the wave still has runs in flight, wait for the next Monitor wake. If the wave is done and the next wave is unblocked, dispatch the next wave.

### Repo hygiene for headless agents

Headless agents clone fresh and have no prior context. Two artifacts make them dramatically more productive:

- **`CLAUDE.md` in the repo root** — build/test commands, project layout, where to put new code. Keep it under a page.
- **`README.md` with dev setup** — install, run, test in one read.

Without these, every dispatched agent burns 10–20 turns rediscovering the basics.

### When to escalate to multi-angle debate

For load-bearing design decisions where "wrong" means a long, fuzzy-feedback debugging cycle (rather than "run, see error, fix"), don't rely on a single agent or first instincts. Spin up 3–5 agents with genuinely distinct framings, run 2–3 rounds of structured debate (opening positions → responses → synthesis), and use the disagreement to sharpen the choice.

Use this sparingly — most decisions are validated by cheap iteration. Reserve it for choices that can't be tested in CI: API shape, data model boundaries, agent prompt design, anything where failure looks like vague user complaints rather than a stack trace.

## Tech Stack

- **Backend:** FastAPI, asyncpg/aiosqlite, Pydantic v2, uvicorn
- **Frontend:** React 19, TypeScript, MUI 7, TipTap editor, Vite
- **MCP:** FastMCP 2.x (stdio transport)
- **Python:** 3.13+
