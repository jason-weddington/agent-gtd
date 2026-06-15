# Agent GTD

A full-stack [Getting Things Done](https://gettingthingsdone.com/) app with an MCP server for AI agent integration. FastAPI + React 19, with PostgreSQL or zero-config SQLite.

![Agent GTD project board](images/agent-gtd.png)

## Prerequisites

- **Python 3.13+** and [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh` (uv downloads a matching Python automatically during `uv sync` if needed)
- **Node.js 20.19+** and npm — via [nvm](https://github.com/nvm-sh/nvm) or your package manager
- **PostgreSQL — only for multi-user mode.** Local mode uses SQLite with zero setup, and the test suite runs against in-memory SQLite, so `uv run pytest` works on a fresh clone with no database server installed.

## Internal dependency: agent-gtd-dispatch-protocol

`agent-gtd-dispatch-protocol` is an internal shared-schema package that lives in
the [agent-gtd-dispatch](https://github.com/jason-weddington/agent-gtd-dispatch)
repository — it is **not published to PyPI**. The default pin in
`pyproject.toml` (`[tool.uv.sources]`, line 131) fetches it anonymously over
https from the public GitHub repo:

```toml
agent-gtd-dispatch-protocol = { git = "https://github.com/jason-weddington/agent-gtd-dispatch", subdirectory = "packages/protocol", rev = "main" }
```

`uv sync` works on any machine with internet access — no SSH keys or private
hosts required. The lockfile pins an exact commit; to pick up a newer protocol
release run `uv lock --upgrade-package agent-gtd-dispatch-protocol`.

You only need an override in two situations:

### Override form A — porting: fork the dispatch repo

If you are forking this system (e.g. to an internal git host), fork
`agent-gtd-dispatch` too and replace the `agent-gtd-dispatch-protocol` line in
`[tool.uv.sources]` (`pyproject.toml` line 131) with your fork's URL:

```toml
agent-gtd-dispatch-protocol = { git = "https://<your-git-host>/<your-fork>/agent-gtd-dispatch", subdirectory = "packages/protocol", rev = "main" }
```

In a fork this is a committed change — your fork's pin is your source of truth.

### Override form B — local protocol development (tested ✓)

The GitHub pin only sees protocol changes after they are pushed to GitHub
(release time). When actively co-developing the protocol package, point at a
local sibling checkout instead (clone `agent-gtd-dispatch` next to `agent_gtd/`
so `../agent-gtd-dispatch` resolves):

```toml
agent-gtd-dispatch-protocol = { path = "../agent-gtd-dispatch/packages/protocol" }
```

Run `uv sync` from `agent_gtd/`; the full test suite passes unchanged against
the local checkout.

> **Do not commit the path override** — it is a local-development convenience.
> Revert to the GitHub pin before pushing.

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
# Install PostgreSQL and create a role + database
# (stock Ubuntu shown — adapt the role/password and pg setup to your environment)
sudo apt install -y postgresql
sudo -u postgres psql -c "CREATE USER gtd WITH PASSWORD 'gtd' CREATEDB;"
sudo -u postgres createdb -O gtd agent_gtd
```

> **AL2023 / RHEL / CentOS Stream:** `postgresql16-server` is NOT auto-initialized on install.
> Run these two steps first (once only), then continue with the `CREATE USER` commands above:
>
> ```bash
> sudo postgresql-setup --initdb
> sudo systemctl enable --now postgresql
> ```
>
> A fresh `initdb` also defaults TCP connections to **ident** auth, which rejects password DSNs.
> Edit `/var/lib/pgsql/data/pg_hba.conf` and change the `host` lines for `127.0.0.1/32` and
> `::1/128` from `ident` to `scram-sha-256`, then reload:
>
> ```bash
> sudo systemctl reload postgresql
> ```
>
> Ubuntu hides both steps — it auto-inits the data directory and ships md5/scram-sha-256 as
> the default TCP auth method, so no `pg_hba.conf` edit is needed there.
>
> If `sudo -u postgres psql` is blocked (e.g. root-only sudoers), use
> `sudo runuser -u postgres -- psql ...` instead.

```bash

# Configure environment
cp .env.example .env
# Edit .env: set AGENT_GTD_DATABASE_URL (e.g. postgresql://gtd:gtd@localhost:5432/agent_gtd)
# and JWT_SECRET

# IMPORTANT: .env is NOT auto-loaded — export it into the shell first
# (or use direnv / your own env mechanism). Without AGENT_GTD_DATABASE_URL
# in the environment, the steps below silently run against local SQLite.
set -a; source .env; set +a

# Install and seed
uv sync
npm --prefix frontend install
uv run python scripts/seed.py   # Creates seed user admin@local / admin (NOT an admin — run `agent-gtd promote-admin admin@local` to grant admin)

# Start (same shell, so the exported vars are visible)
./start.sh
```

## MCP Server

The app includes an MCP server for managing GTD items from AI agents (Claude Code, etc.).

### Local mode

In local mode (no `AGENT_GTD_DATABASE_URL`), the MCP server uses SQLite and auto-authenticates — no setup needed.

### Multi-user mode (PostgreSQL)

Authentication uses API keys. Get one, set it in your environment, and the MCP server handles the rest.

**1. Get an API key**

Either generate one with the seed script (run with `AGENT_GTD_DATABASE_URL` exported — see the PostgreSQL Quick Start — or the key lands in the local SQLite database instead):

```bash
uv run python scripts/seed.py   # First run prints the key and saves it to data/seed.json
```

The full key is only printed on the **first** run. On subsequent runs the script
prints just a key prefix — read the saved key from `data/seed.json` instead.

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

Core tools (subset):

| Tool | Description |
|------|-------------|
| `login` | Authenticate with API key (not needed if env var is set) |
| `inbox_capture` | Quick-capture to inbox |
| `add_item` | Create an item with status, priority, labels |
| `update_item` | Update an existing item |
| `complete_item` | Mark an item done |
| `list_items` | List items (filter by status, project, etc.) |
| `get_item` | Get a single item by ID |
| `add_note` / `update_note` | Create or update project notes |
| `list_notes` / `get_note` | Read project notes |
| `list_projects` / `add_project` | Manage projects |

The full surface also covers blockers, comments, project sharing, dispatch
(`dispatch_item`, `get_run_status`, `list_runs`, `list_dispatch_hosts`), and the
rollout family — see the `@mcp.tool` registrations in
`src/agent_gtd/mcp_server.py` for the complete list. (`claim_item` /
`release_item` are REST-only endpoints, not MCP tools.)

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

## Dispatch Service (Optional)

Headless dispatch (`dispatch_item`, rollouts, `agent-gtd run-status`) requires a
dispatch host running the service from the separate
[agent-gtd-dispatch](https://github.com/jason-weddington/agent-gtd-dispatch)
repository. Provision it with that repo's `setup-dispatch-host.sh` (full
walkthrough in its `docs/install.md`). For a single dev machine, use
**single-user mode** — everything runs under your own login account, with no
two-user split and no sudoers rules:

```bash
# From a clone of agent-gtd-dispatch, on the machine that will run agents
sudo --preserve-env=DISPATCH_SINGLE_USER DISPATCH_SINGLE_USER=1 \
  ./setup-dispatch-host.sh --env-file <your-env-file>
```

Then set `DISPATCH_SERVICE_URL` (and `DISPATCH_SERVICE_API_KEY`) in this app's
environment to point at that host — see `.env.example`. Without a dispatch
service, everything else in this README still works; only the dispatch and
rollout tools are unavailable.

## Development

```bash
uv run pytest                         # Run tests
uv run ruff check .                   # Lint
uv run mypy src/                      # Type check
npm --prefix frontend run test        # Frontend tests

# Install git hooks (recommended)
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg \
  --hook-type pre-push
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
