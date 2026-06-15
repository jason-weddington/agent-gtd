# Environment Setup

> **Deep-dive runbook.** For a quick-start, see [README.md](../README.md). This doc expands
> on every step, explains why each command works, and covers multi-user and admin workflows
> not in the README. Keep the two documents consistent — if they contradict, this doc is wrong.

## Prerequisites

- **Python 3.13+** — the project uses `requires-python = ">=3.13"` in `pyproject.toml`.
  Install via [pyenv](https://github.com/pyenv/pyenv) or your OS package manager.
- **uv** — the project uses `uv` for dependency management. Install via `pip install uv` or
  `curl -Ls https://astral.sh/uv/install.sh | sh`.
- **PostgreSQL 14+** — required for the production database (multi-user mode). Not required
  for local/single-user mode; see [Local Mode vs PostgreSQL Mode](#local-mode-vs-postgresql-mode).
- **Node.js 20.19+** — required for the React frontend (Vite 7 engine requirement; see
  `frontend/package.json`). Install via [nvm](https://github.com/nvm-sh/nvm) or your OS
  package manager.
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

Note: `agent-gtd-dispatch-protocol` is a git dependency fetched **anonymously over https from
the public GitHub repo** (`[tool.uv.sources]` in `pyproject.toml` pins
`git = "https://github.com/jason-weddington/agent-gtd-dispatch"`, `rev = "main"`) — no internal
network or credentials required. If you maintain a private fork, repoint that line at your own
git host (see README → "Internal dependency: agent-gtd-dispatch-protocol" for the fork-URL and
local-path override forms).

### 3. Install git hooks

**Do this every time you clone fresh.** Without hooks installed, commits bypass lint, type
checks, coverage enforcement, and secrets scanning.

```bash
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

This installs three hook types:
- `pre-commit`: Ruff lint+format, mypy, ESLint, tsc, trailing whitespace, gitleaks
- `commit-msg`: Conventional commit message format validation
- `pre-push`: Test coverage enforcement

Releases are not triggered by a hook — they are a deliberate step via `./release.sh`.

### 4. Set up PostgreSQL databases

> **Skip this step if you are using local (SQLite) mode.** If `AGENT_GTD_DATABASE_URL` is not
> set, the app uses SQLite at `$XDG_DATA_HOME/agent_gtd/gtd.db` (falling back to
> `~/.local/share/agent_gtd/gtd.db`) with no authentication. No database server needed.

On Ubuntu, the default PostgreSQL installation uses **peer authentication** for the `postgres`
superuser, so `psql -U postgres` fails unless you are the `postgres` OS user. Use `sudo -u
postgres` instead:

```bash
# Create a dedicated role that owns the database.
# CREATEDB is needed so the role can create the schema objects at startup.
sudo -u postgres psql -c "CREATE USER gtd WITH PASSWORD 'gtd' CREATEDB;"

# Create the database owned by that role.
sudo -u postgres createdb -O gtd agent_gtd
```

> **Ubuntu note:** Ubuntu auto-initializes the PostgreSQL data directory during package install
> and defaults to `md5` (or `scram-sha-256` on newer releases) for TCP connections, so
> password-based DSNs work without additional configuration.

#### AL2023 / RHEL / CentOS Stream — extra first-run steps

These distros ship `postgresql16-server` (or similar) without auto-initializing the data
directory. Two extra steps are required before you can connect:

**Step A — initialize and start the database**

```bash
# Initialize the data directory (run once, as root)
sudo postgresql-setup --initdb

# Enable and start the service
sudo systemctl enable --now postgresql
```

**Step B — fix pg_hba.conf for password authentication**

A fresh `initdb` defaults TCP connections (127.0.0.1 and ::1) to **ident** auth. The app's
DSN uses password auth (`postgresql://gtd:gtd@localhost/...`), which is rejected until you
switch those lines to `scram-sha-256` (or `md5`):

```bash
# Open pg_hba.conf — path may vary; check 'pg_lsclusters' or the postgresql.conf
# for data_directory, then look for pg_hba.conf inside it.
sudo vi /var/lib/pgsql/data/pg_hba.conf
```

Find the `host` lines for `127.0.0.1/32` and `::1/128` and change the method from
`ident` to `scram-sha-256`:

```
# Before:
host    all    all    127.0.0.1/32    ident
host    all    all    ::1/128         ident

# After:
host    all    all    127.0.0.1/32    scram-sha-256
host    all    all    ::1/128         scram-sha-256
```

Then reload PostgreSQL to pick up the change:

```bash
sudo systemctl reload postgresql
```

**Step C — create the role and database**

If `sudo -u postgres psql` is blocked (e.g. root-only sudoers), use `runuser` instead:

```bash
sudo runuser -u postgres -- psql -c "CREATE USER gtd WITH PASSWORD 'gtd' CREATEDB;"
sudo runuser -u postgres -- createdb -O gtd agent_gtd
```

Or with the standard form where `sudo -u` is available:

```bash
sudo -u postgres psql -c "CREATE USER gtd WITH PASSWORD 'gtd' CREATEDB;"
sudo -u postgres createdb -O gtd agent_gtd
```

The database schema is created automatically at startup via `_SCHEMA_STATEMENTS` in
`database.py`. You do not need to run any migration scripts manually.

**Why ownership matters (PostgreSQL 15+/16):** `GRANT ALL PRIVILEGES ON DATABASE` does NOT
grant `CREATE` on the `public` schema in PostgreSQL 15 and later (Ubuntu ships PostgreSQL 16).
Making the role the database owner (via `-O`) is the cleanest fix — the role can then create
tables in the public schema without any extra grants.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values. Minimum required for development:

```bash
# Required: change this before running the app
JWT_SECRET=dev-secret-change-me

# Required: connection string for your development database
AGENT_GTD_DATABASE_URL=postgresql://gtd:gtd@localhost:5432/agent_gtd
```

**`.env` is NOT loaded automatically.** The app reads `os.environ` directly. Neither
`start.sh` nor `serve.sh` sources `.env`. You must export the variables into your shell
before running the server or seed script, otherwise the app silently falls back to local
SQLite mode:

```bash
# Export all variables from .env into the current shell
set -a; source .env; set +a
```

Add this to your shell profile, a `.envrc` file (direnv), or run it in every new shell before
starting development. Without `AGENT_GTD_DATABASE_URL` exported, the seed script and servers
run against local SQLite, not PostgreSQL.

See the [Configuration](#configuration) section for all variables.

### 6. Create seed data (first-time only)

The seed script creates a default user (`admin@local` / `admin`) and project, writing their
IDs (and the API key on first run) to `data/seed.json`. The `data/` directory is gitignored.

```bash
# Make sure .env is sourced first if you are using PostgreSQL mode
set -a; source .env; set +a
uv run python scripts/seed.py
```

**First run — expected output:**
```
Created user: <uuid>
Created project: <uuid>
Created API key: agtd_<key>

Seed data written to data/seed.json
  user_id:    <uuid>
  project_id: <uuid>
  api_key:    agtd_<key>
```

**Subsequent runs — expected output** (resources already exist):
```
User already exists: <uuid>
Project already exists: <uuid>
API key already exists (prefix: xxxxxxxx...)

Seed data written to data/seed.json
  user_id:    <uuid>
  project_id: <uuid>
```

The **full API key is printed only on the first run**. On subsequent runs, only a prefix of
the stored hash is shown. The full key is preserved in `data/seed.json` on first run and
merged back on reruns. Keep `data/seed.json` — it holds `user_id`, `project_id`, and
`api_key`.

### 7. Install frontend dependencies

```bash
npm --prefix frontend install
```

### 8. Start the development servers

```bash
# Make sure .env is sourced first if you are using PostgreSQL mode
set -a; source .env; set +a
./start.sh
```

This launches:
- uvicorn on port 8000 (backend)
- Vite dev server on port 5173 (frontend)

The Vite dev server proxies `/api/*` requests to port 8000, so you can open
`http://localhost:5173` and the frontend will hit the local backend automatically.

## Configuration

All configuration is done via environment variables. **`.env` is NOT loaded automatically**
— export variables into your shell before running any commands (see step 5).

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | Yes (PostgreSQL mode) | Secret key for JWT signing. Change from the default in any shared environment. |
| `AGENT_GTD_DATABASE_URL` | No | asyncpg-style connection string: `postgresql://user:pass@host:5432/dbname`. If absent, the app uses SQLite at `$XDG_DATA_HOME/agent_gtd/gtd.db` (falling back to `~/.local/share/agent_gtd/gtd.db`) in local mode with no authentication. |
| `AGENT_GTD_URL` | No | Base URL of a remote Agent GTD instance. Set this in MCP client config to use remote mode (HTTP backend for MCP tools). |
| `AGENT_GTD_API_KEY` | No | API key for MCP authentication. When set, the MCP server auto-authenticates — no `login()` call needed. Also used by dispatched agents. |
| `AGENT_GTD_PUBLIC_URL` | No | Public-facing base URL for issued links (invite URLs, password-reset links). Set to your public hostname (e.g. `https://r7-research`) when behind a reverse proxy that does not forward the original `Host` header. |
| `AGENT_GTD_AGENT_NAME` | No | Attribution name for the current MCP session (e.g., `claude-build-abc12345`). Set automatically by the dispatch worker for dispatched agents. |
| `DISPATCH_SERVICE_URL` | No | URL of a remote Claude Code dispatch service (e.g., `http://pironman01:8100`). Required to dispatch items to remote agents. |
| `DISPATCH_SERVICE_API_KEY` | No | API key for the remote dispatch service. |
| `DISPATCH_DEFAULT_MAX_TURNS` | No | Default maximum agent turns per dispatch run (default: 100). |
| `HOSTNAME` | No | Hostname added to CORS allowed origins. Set to the production hostname. |

### Local Mode vs PostgreSQL Mode

| Setting | `AGENT_GTD_DATABASE_URL` absent | `AGENT_GTD_DATABASE_URL` set |
|---|---|---|
| Database | SQLite at `$XDG_DATA_HOME/agent_gtd/gtd.db` (fallback: `~/.local/share/...`) | PostgreSQL (asyncpg pool) |
| Authentication | Disabled — uses hardcoded local user (`00000000-0000-0000-0000-000000000001`) | JWT required for all REST endpoints |
| Registration | Not available | Invite token required |
| Use case | Single-user developer install, quick demos | Multi-user production deployment |

### MCP Client Configuration

The MCP server supports two transports. Choose the one that fits your setup:

#### stdio (recommended for local / Claude Code installs)

Runs the MCP server as a subprocess. Works in local SQLite mode with no env vars, or
HTTP-backed when `AGENT_GTD_URL`/`AGENT_GTD_API_KEY` are set in the `env` block.

In your Claude Code MCP config (e.g. `~/.claude.json`):

```json
{
  "mcpServers": {
    "agent-gtd": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/agent_gtd", "agent-gtd-mcp"],
      "env": {
        "AGENT_GTD_URL": "https://agent-gtd.example.com",
        "AGENT_GTD_API_KEY": "agtd_..."
      }
    }
  }
}
```

Omit the `env` block entirely to run in local SQLite mode (no auth required).

#### http (point at an already-running remote server)

Use this when the Agent GTD server is running remotely (e.g. production) and you want to
connect over HTTP rather than running a local subprocess:

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

Or for a locally-running server in local mode (no auth):

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

**When to use which:**
- **stdio** — typical Claude Code developer setup; the MCP binary is a subprocess of the
  editor. Works offline, no port to expose.
- **http** — connecting to a remote server you don't control locally (e.g. shared team
  instance, production). Requires the server to be running and reachable.

## Multi-User Administration (PostgreSQL mode only)

These steps require PostgreSQL mode (`AGENT_GTD_DATABASE_URL` set). Local SQLite mode has
no authentication and no registration flow.

### Minting an invite token

New user registration requires an invite token. To create one:

#### 1. Promote the seed user to admin

The seed script creates `admin@local` with `is_admin=0` — it is **not** an admin by default.
Promote it using the CLI's direct-DB subcommand (make sure `AGENT_GTD_DATABASE_URL` points at
the target database):

```bash
set -a; source .env; set +a
uv run agent-gtd promote-admin admin@local
```

This runs `UPDATE users SET is_admin = 1 WHERE email = 'admin@local'` directly against the
database. No running server is needed.

#### 2. Obtain a JWT

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@local","password":"admin"}' \
  | jq -r .token)
```

#### 3. Create an invite

```bash
curl -X POST http://localhost:8000/api/admin/invites \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"note": "for alice"}'
```

Response:

```json
{
  "token": "<token>",
  "url": "http://localhost:8000/register?token=<token>",
  "note": "for alice",
  "created_at": "2026-..."
}
```

Share the `url` with the new user — they open it in a browser to complete registration.

**Notes:**
- The endpoint is `POST /api/admin/invites` (router prefix `/api/admin`; see
  `src/agent_gtd/routes/admin_routes.py`).
- Auth is a **JWT Bearer token** (not an API key). The user must have `is_admin = 1`.
- The `note` field is optional.
- `AGENT_GTD_PUBLIC_URL` controls the base URL in the returned `url` field. Behind a reverse
  proxy, set it to your public hostname so the link is shareable.

## Verification

Run these commands after setup to verify everything is working:

```bash
# 1. Run the backend test suite — no database setup needed (uses in-memory SQLite)
uv run pytest

# 2. Run the frontend test suite
npm --prefix frontend run test

# 3. Check types
uv run mypy src/

# 4. Check lint
uv run ruff check .

# 5. Start the dev servers and verify the health endpoint
set -a; source .env; set +a    # if using PostgreSQL mode
./start.sh &
sleep 3
curl http://localhost:8000/api/health
# Expected: {"status": "ok"}

# 6. Open the web UI
# Visit http://localhost:5173 — the login page should render.
```

`uv run pytest` runs against a fresh in-memory SQLite pool per test (see `tests/conftest.py`)
and requires no database server or environment variable.

If the seed script ran successfully, use the credentials from `data/seed.json` to log in
(`admin@local` / `admin`), or register a new account with an invite token — see
[Minting an invite token](#minting-an-invite-token) above.

## Troubleshooting

### `uv sync` fails with "fetch error" on `agent-gtd-dispatch-protocol`

The dispatch protocol package is fetched anonymously over https from public GitHub
(`https://github.com/jason-weddington/agent-gtd-dispatch`, pinned in `pyproject.toml`'s
`[tool.uv.sources]`). This normally needs no credentials; a failure here usually means no
network egress to github.com, a proxy/firewall blocking it, or a private fork whose URL you
must repoint.

**Solution:** Use SSH access to the internal network, or ask the project lead for a pre-built
wheel or a tarball of the package.

### PostgreSQL connection refused

Check that PostgreSQL is running and the connection string in `.env` is correct.

```bash
set -a; source .env; set +a
psql "$AGENT_GTD_DATABASE_URL" -c "SELECT 1"
```

**On AL2023/RHEL:** If the service never started (fresh install), run:

```bash
sudo postgresql-setup --initdb   # only needed once
sudo systemctl enable --now postgresql
```

### Password authentication failed (AL2023/RHEL — ident auth mismatch)

If you see `FATAL: password authentication failed` or
`FATAL: Ident authentication failed for user "gtd"` on a RHEL-family host, the
`pg_hba.conf` TCP entries still use **ident** (the default after `initdb`). Switch
the `host` lines for `127.0.0.1/32` and `::1/128` to `scram-sha-256` and reload:

```bash
# Edit (path may vary — run `sudo -u postgres psql -c 'SHOW hba_file;'` to locate it)
sudo vi /var/lib/pgsql/data/pg_hba.conf

# Reload without a full restart
sudo systemctl reload postgresql
```

Ubuntu auto-sets md5/scram-sha-256 at install time, so this step is only needed on RHEL-family distros.

### Pre-commit hooks not running

Verify hooks are installed:
```bash
ls .git/hooks/pre-commit    # Should exist
ls .git/hooks/commit-msg    # Should exist
ls .git/hooks/pre-push      # Should exist
```

If missing, re-run:
```bash
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

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

If running in PostgreSQL mode, check that `AGENT_GTD_DATABASE_URL` is exported correctly. In
local mode (SQLite), data persists in `$XDG_DATA_HOME/agent_gtd/gtd.db` (falling back to
`~/.local/share/agent_gtd/gtd.db`) — check that path exists and is writable.

## Pointers

> `docs/deploy.md` — production nginx + systemd deployment runbook.
> `docs/testing.md` — running tests, coverage, pre-push enforcement.
> `docs/architecture.md` — local mode vs PostgreSQL mode in more detail.
> KB entry `kb-00306` — deployment details for the r7-research server.
