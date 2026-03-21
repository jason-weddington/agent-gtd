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

**2. Set `AGENT_GTD_API_KEY` in your environment**

How you do this is up to you:

```bash
# Shell profile (~/.zshrc, ~/.bashrc)
export AGENT_GTD_API_KEY=agtd_...

# direnv (.envrc)
export AGENT_GTD_API_KEY=agtd_...

# Claude Code MCP config (~/.claude.json)
"agent-gtd": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "/path/to/agent_gtd", "agent-gtd-mcp"],
  "env": { "AGENT_GTD_API_KEY": "agtd_..." }
}
```

When the env var is set, the MCP server auto-authenticates on first tool call. No explicit `login` step needed.

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
| `switch_project` | Set active project context |

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

## Tech Stack

- **Backend:** FastAPI, asyncpg/aiosqlite, Pydantic v2, uvicorn
- **Frontend:** React 19, TypeScript, MUI 7, TipTap editor, Vite
- **MCP:** FastMCP 2.x (stdio transport)
- **Python:** 3.13+
