# Environment Setup

## Prerequisites

- **Python 3.13+** — the project uses `requires-python = ">=3.13"` in `pyproject.toml`.
  Install via [pyenv](https://github.com/pyenv/pyenv) or your OS package manager.
- **uv** — the project uses `uv` for dependency management. Install via `pip install uv` or
  `curl -Ls https://astral.sh/uv/install.sh | sh`.
- **PostgreSQL 14+** — required for the production database. You need two databases: one for
  the app and one for tests.
- **Node.js 18+** — required for the React frontend. Install via
  [nvm](https://github.com/nvm-sh/nvm) or your OS package manager.
- **pre-commit** — installed as a dev dependency via `uv sync`. Git hooks are set up
  separately (see below).

Optional but recommended:
- **git** — the project uses conventional commits enforced by a commit-msg hook.
- **gitleaks** — used by the pre-commit hook for secrets scanning (auto-installed via
  pre-commit).

## Installation Steps

### 1. Clone the repository

```bash
git clone <repo-url>
cd agent_gtd
```

### 2. Install Python dependencies

```bash
uv sync
```

This installs all runtime and dev dependencies into a `.venv` managed by `uv`. The lock file
(`uv.lock`) pins exact versions — never modify it by hand. Use `uv add <package>` to add new
dependencies.

Note: `agent-gtd-dispatch-protocol` is a git dependency pointing to `ubuntu-vm01`. If you
are not on the internal network, this dependency may fail to fetch. In that case, contact the
project lead for a pre-built wheel or access to the repository.

### 3. Install git hooks

**Do this every time you clone fresh.** Without hooks installed, commits bypass lint, type
checks, coverage enforcement, and secrets scanning.

```bash
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type post-commit --hook-type pre-push
```

This installs four hook types:
- `pre-commit`: Ruff lint+format, mypy, ESLint, tsc, trailing whitespace, gitleaks
- `commit-msg`: Conventional commit message format validation
- `post-commit`: Semantic version bump on main (guards against `chore(release):` recursion)
- `pre-push`: Test coverage enforcement

### 4. Set up PostgreSQL databases

Create two databases — one for the app, one for tests:

```bash
psql -U postgres <<SQL
CREATE DATABASE agent_gtd;
CREATE DATABASE agent_gtd_test;
CREATE USER your_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE agent_gtd TO your_user;
GRANT ALL PRIVILEGES ON DATABASE agent_gtd_test TO your_user;
SQL
```

The database schema is created automatically at startup via `_SCHEMA_STATEMENTS` in
`database.py`. You do not need to run any migration scripts manually.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values. Minimum required for development:

```bash
# Required: change this before running the app
JWT_SECRET=dev-secret-change-me

# Required: connection string for your development database
AGENT_GTD_DATABASE_URL=postgresql://your_user:your_password@localhost:5432/agent_gtd
```

See the [Configuration](#configuration) section for all variables.

### 6. Create seed data (first-time only)

The seed script creates a default user and project, writing their IDs to `data/seed.json`.
The `data/` directory is gitignored.

```bash
uv run python scripts/seed.py
```

Expected output:
```
Seed complete. IDs written to data/seed.json
  user_id:    <uuid>
  project_id: <uuid>
```

Keep `data/seed.json` — you will need the IDs when testing with the web UI.

### 7. Install frontend dependencies

```bash
npm --prefix frontend install
```

### 8. Start the development servers

```bash
./start.sh
```

This launches:
- uvicorn on port 8000 (backend)
- Vite dev server on port 5173 (frontend)

The Vite dev server proxies `/api/*` requests to port 8000, so you can open
`http://localhost:5173` and the frontend will hit the local backend automatically.

## Configuration

All configuration is done via environment variables. The `.env` file is loaded automatically
by the application (using `python-dotenv` or by sourcing it in your shell before running
`./start.sh`).

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | Yes | Secret key for JWT signing. Change from the default in any shared environment. |
| `AGENT_GTD_DATABASE_URL` | Yes (PostgreSQL mode) | asyncpg-style connection string: `postgresql://user:pass@host:5432/dbname`. If absent, the app uses SQLite at `~/.local/share/agent_gtd/gtd.db` (local mode, no auth). |
| `AGENT_GTD_TEST_DATABASE_URL` | No | Connection string for the test database. Tests use in-memory SQLite by default (no env var needed). Set this only if you want tests to run against PostgreSQL. |
| `AGENT_GTD_URL` | No | Base URL of a remote Agent GTD instance. Set this in MCP client config to use remote mode (HTTP backend for MCP tools). |
| `AGENT_GTD_API_KEY` | No | API key for MCP authentication. When set, the MCP server auto-authenticates — no `login()` call needed. Also used by dispatched agents. |
| `DISPATCH_SERVICE_URL` | No | URL of a remote Claude Code dispatch service (e.g., `http://pironman01:8100`). Required to dispatch items to remote agents. |
| `DISPATCH_SERVICE_API_KEY` | No | API key for the remote dispatch service. |
| `DISPATCH_DEFAULT_MAX_TURNS` | No | Default maximum agent turns per dispatch run (default: 100). |
| `HOSTNAME` | No | Hostname added to CORS allowed origins. Set to the production hostname. |
| `LOCAL_USER_ID` | No | UUID to use for the built-in local user in local mode. Defaults to `00000000-0000-0000-0000-000000000001`. |
| `AGENT_GTD_AGENT_NAME` | No | Attribution name for the current MCP session (e.g., `claude-build-abc12345`). Set automatically by the dispatch worker for dispatched agents. |

### Local Mode vs PostgreSQL Mode

| Setting | `AGENT_GTD_DATABASE_URL` absent | `AGENT_GTD_DATABASE_URL` set |
|---|---|---|
| Database | SQLite at `~/.local/share/agent_gtd/gtd.db` | PostgreSQL (asyncpg pool) |
| Authentication | Disabled — uses hardcoded `LOCAL_USER_ID` | JWT required for all REST endpoints |
| Registration | Not available | Invite token required |
| Use case | Single-user developer install, quick demos | Multi-user production deployment |

### MCP Client Configuration

To configure the MCP server in your MCP client (e.g., Claude Code's `.mcp.json`):

```json
{
  "mcpServers": {
    "agent-gtd": {
      "type": "http",
      "url": "https://gtd.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${AGENT_GTD_API_KEY}"
      }
    }
  }
}
```

Or for local mode (SQLite, no auth):

```json
{
  "mcpServers": {
    "agent-gtd": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Verification

Run these commands after setup to verify everything is working:

```bash
# 1. Run the backend test suite
uv run pytest

# 2. Run the frontend test suite
npm --prefix frontend run test

# 3. Check types
uv run mypy src/

# 4. Check lint
uv run ruff check .

# 5. Start the dev servers and verify the health endpoint
./start.sh &
sleep 3
curl http://localhost:8000/api/health
# Expected: {"status": "ok"}

# 6. Open the web UI
# Visit http://localhost:5173 — the login page should render.
```

If the seed script ran successfully, use the credentials from `data/seed.json` to log in, or
register a new account (you will need an invite token — check `data/seed.json` for any token
written by the seed script, or create one via the admin API).

## Troubleshooting

### `uv sync` fails with "fetch error" on `agent-gtd-dispatch-protocol`

The dispatch protocol package is hosted on an internal git server (`ubuntu-vm01`). If you are
not on the internal network or VPN, `uv sync` cannot fetch this dependency.

**Solution:** Use SSH access to the internal network, or ask the project lead for a pre-built
wheel or a tarball of the package.

### PostgreSQL connection refused

Check that PostgreSQL is running and the connection string in `.env` is correct.

```bash
psql "$AGENT_GTD_DATABASE_URL" -c "SELECT 1"
```

### Pre-commit hooks not running

Verify hooks are installed:
```bash
ls .git/hooks/pre-commit    # Should exist
ls .git/hooks/commit-msg    # Should exist
ls .git/hooks/pre-push      # Should exist
```

If missing, re-run: `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type post-commit --hook-type pre-push`

### mypy strict errors after adding a new dependency

Add an override to `pyproject.toml` under `[[tool.mypy.overrides]]`:
```toml
[[tool.mypy.overrides]]
module = "new_package.*"
ignore_missing_imports = true
```

### Frontend build fails with Rollup error on `react-transition-group`

This is a known issue with `react-transition-group` v4 and ESM resolution. The fix is already
in `frontend/vite.config.ts` under `build.commonjsOptions.include`. If a fresh failure
appears for a different package, widen the regex in that option to include the failing
package's path. Do **not** try to upgrade `react-transition-group` beyond v4 — v5 does not
exist on npm (verified May 2026).

### "Duplicate server name" warnings from nginx

nginx loads every file in `sites-enabled/`, including `.bak` files. Always store backups in
`/etc/nginx/backups/`, not `sites-enabled/`. See `docs/deploy.md` for the full nginx setup.

### App starts but items are not appearing

If running in PostgreSQL mode, check that `AGENT_GTD_DATABASE_URL` is set correctly. In local
mode (SQLite), data persists in `~/.local/share/agent_gtd/gtd.db` — check that path exists
and is writable.

## Pointers

> `docs/deploy.md` — production nginx + systemd deployment runbook.
> `docs/testing.md` — running tests, coverage, pre-push enforcement.
> `docs/architecture.md` — local mode vs PostgreSQL mode in more detail.
> KB entry `kb-00306` — deployment details for the r7-research server.
