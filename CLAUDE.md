## Setup (do this first)

```bash
uv sync
npm --prefix frontend install
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

Without local hooks installed, working-tree edits that haven't been staged can land on origin/main as lint/format regressions — happened three times on 2026-05-13. Run this every time you clone fresh. (`npm install` is part of setup because the pre-commit hooks run eslint + tsc via `npm --prefix frontend` — they fail on a fresh clone without it.)

Full fresh-machine setup (prerequisites, database creation, env vars, local SQLite mode): `docs/setup.md`.

## Check the Knowledge Base First

A personal-kb MCP server is available. **Before guessing, searching the filesystem, or asking the user**, search the KB for answers:
```
kb_search("agent-gtd deployment")    # deployment details, server info
kb_search("agent-gtd database")      # connection strings, schema
kb_ask("how do I bounce the server") # operational procedures
```

The KB contains deployment details, architectural decisions, debugging lessons, and operational procedures that have been verified and curated. If the KB has the answer, use it. Don't waste time rediscovering what's already captured.

## Deployment

The app runs on `r7-research` as a **user-level** systemd service (no sudo):
```bash
ssh r7-research 'systemctl --user restart agent-gtd'   # Restart
ssh r7-research 'systemctl --user status agent-gtd'     # Check status
ssh r7-research 'journalctl --user -u agent-gtd -f'     # Tail logs
```

The git remote `origin` points to `r7-research`. After `git push origin main --tags`, restart the service to pick up changes. See KB entries `kb-00306` and `kb-00307` for full deployment architecture and bounce guidelines.

## Headless Dispatch Hosts

**Two provisioning modes.** `setup-dispatch-host.sh` (in the `agent-gtd-dispatch`
repo) supports the **two-user split** described below (production homelab hosts) and a
**single-user mode** for a personal/dev machine: run
`sudo DISPATCH_SINGLE_USER=1 ./setup-dispatch-host.sh` — no sudoers rules, no user
split; the agent and the dispatch service run as the invoking user, and the
`/home/dispatch-svc` / `/home/dispatch` paths below do not exist (their equivalents
live under the invoking user's home). The script refuses to create a mixed state on a
host already provisioned in the other mode, and it mints a `DISPATCH_API_KEY` into the
service env file when one is absent. Single-user mode is the right starting point on a
fresh machine outside this homelab; everything below describes the two-user production
setup — adapt usernames/paths accordingly.

Dispatch runs on two hosts: `pironman01` and `r7-research` (`ubuntu-pi-01` was
removed from the rotation 2026-06-10 — too slow). On
each host the dispatch API runs as user **`dispatch-svc`**, and it launches Claude
Code as user **`dispatch`** (the two-user split). The dispatch code lives in the
separate `agent-gtd-dispatch` repo, not here.

**Canonical env file is `/home/dispatch-svc/.env`** — it is the systemd
`EnvironmentFile` (read by the running service) *and* the file `setup-dispatch-host.sh`
reads at provision time to inject KB secrets into the agent's MCP config.
`/home/dispatch/.env` is **vestigial** (a pre-split leftover) — nothing reads it; don't
put anything there. Full model + which-var-goes-where: **`kb-01598`**.

**Headless agents read their MCP servers from `/home/dispatch/.claude.json`** (not the
repo's gitignored `.mcp.json`, never cloned). The durable way to add/change a server is
to edit `agent-gtd-dispatch/templates/mcp-servers.sh` and re-register (setup script or
`claude mcp add --scope user`), not to hand-jq the JSON. The four registered servers:
`agent-gtd`, `personal-kb`, `team-kb`, `aws-documentation-mcp-server`.

Both KB servers carry `ANTHROPIC_API_KEY` in their *per-server* MCP `env` block (they
make their own LLM calls); it is injected from `KB_ANTHROPIC_API_KEY` in
`/home/dispatch-svc/.env` and must **never** reach the agent's own process env, or
Claude Code billing flips off the Max subscription (`kb-01512`). `team-kb` also carries
its own `KB_DATABASE_URL` (team DB) + `KB_INSTANCE_ROLE=team`/`KB_TEAM=grit-mile`/
`KB_CONTRIBUTOR=jason`; `personal-kb` inherits the personal `KB_DATABASE_URL` via the
worker passthrough. How env crosses the `dispatch-svc → dispatch` sudo boundary:
**`kb-01583`**.

**Workspace (multi-repo) projects.** GTD projects have a `repo_mode`
(`monorepo` | `workspace`). Workspace projects carry a `workspace_repos` list
(pre-seeded from the git origin when toggled in the UI), and dispatch clones every
listed repo under a shared workspace root for the run. Rollouts are supported for
workspace projects.

## Production Architecture

```
client (HTTPS 443)
   │
   ▼
nginx (r7-research)              ← terminates TLS
   ├── /              → frontend/dist/  (static files, SPA fallback)
   ├── /api/events    → uvicorn :8000   (SSE, proxy_buffering off)
   └── /api/*         → uvicorn :8000   (FastAPI REST)
```

**Key points for agents and contributors:**

- **`serve.sh`** is the production entry point — launches uvicorn only, no Vite.
  The systemd unit on r7 runs `serve.sh`.
- **`start.sh`** is the dev entry point — launches uvicorn + Vite dev server. Use this locally.
- **Vite is dev-only.** Never start Vite in production. nginx serves the pre-built
  `frontend/dist/` instead. This eliminates HMR WebSocket reconnect reloads in prod.
- **nginx serves static files**, not uvicorn. Do not add a `StaticFiles` mount to FastAPI.
- **Build step belongs in `deploy.sh`** (operator-local, gitignored), not in `serve.sh`.
  Run `npm --prefix frontend run build` before restarting the service after a deploy.
- See `docs/deploy.md` for the full operator runbook (nginx config, systemd unit change,
  deploy.sh template).

## Build and Test Commands
```bash
uv sync                              # Install Python dependencies
uv run pytest                        # Run tests
uv run pytest --cov=agent_gtd         # Tests with coverage report
uv run ruff check .                  # Lint
uv run ruff format .                 # Format
uv run mypy src/                     # Type check
uv run pre-commit run --all-files    # Run all pre-commit hooks

# Install git hooks (not carried by git clone)
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push

npm --prefix frontend install        # Install frontend dependencies
npm --prefix frontend run dev        # Start frontend dev server (port 5173)
npm --prefix frontend run test       # Run frontend tests (vitest)
npm --prefix frontend run build      # Production build

./start.sh                           # Start both backend + frontend dev servers
```

## Project Structure
```
agent_gtd/
├── src/agent_gtd/              # Python backend (FastAPI)
│   ├── main.py                # App entry, lifespan (init/close DB), CORS, router mounts
│   ├── auth.py                # JWT (HS256, 72h) + bcrypt, get_current_user dependency
│   ├── database.py            # asyncpg PostgreSQL pool; SQLite fallback (sqlite_pool.py)
│   │                          #   when AGENT_GTD_DATABASE_URL is unset — single-user
│   │                          #   local mode, no auth (fixed LOCAL_USER_ID)
│   ├── sqlite_pool.py         # SQLite pool backing local single-user mode
│   ├── models.py              # Pydantic v2 domain models + API request/response schemas
│   ├── cli.py                 # `agent-gtd` CLI — mirrors the full MCP tool surface via the cli_commands/ package
│   ├── mcp_server.py          # MCP server entry point (tools for items/notes/dispatch/rollouts)
│   ├── mcp_backend.py         # Shared MCP backend — local-DB or HTTP mode
│   ├── dispatch_worker.py     # Executes dispatched runs against the dispatch service
│   ├── identity.py            # created_by attribution helpers
│   ├── event_bus.py           # In-process pub/sub feeding the SSE endpoint
│   ├── routes/                # 11 routers: auth, item, project, note, comment, dispatch,
│   │                          #   rollout, event (SSE), attachment, settings, admin
│   └── services/              # Business logic — item_service.py, project_service.py,
│                              #   dispatch_service.py, rollout_service.py, dispatch_router.py, ...
├── tests/                     # ~50 pytest modules; conftest.py gives each test a fresh
│                              #   in-memory SQLite pool — no PostgreSQL needed for tests
├── frontend/                  # React 19 + TypeScript + MUI 7 (Vite)
│   ├── src/
│   │   ├── App.tsx            # Route definitions (react-router-dom v7)
│   │   ├── main.tsx           # React root with providers
│   │   ├── api.ts             # Typed API client — auto snake/camelCase conversion
│   │   ├── types.ts           # TypeScript interfaces matching backend response schemas
│   │   ├── utils.ts           # Pure utilities — tested
│   │   ├── theme.ts           # MUI theme customization
│   │   ├── contexts/          # Auth, Theme, EventStream, ItemDrawer, QuickCapture
│   │   ├── hooks/             # useDraftState, useEventStream
│   │   ├── components/        # ~30 shared components: Layout, Sidebar, GtdItemList,
│   │   │                      #   KanbanBoard/Card/Column, ItemDetailDrawer, QuickCapture,
│   │   │                      #   ActivityDrawer, Rollout* widgets, ProtectedRoute, ...
│   │   ├── pages/             # 16 pages: Login, Register, ResetPassword, Inbox,
│   │   │                      #   InboxProcessor, NextActions, WaitingFor, SomedayMaybe,
│   │   │                      #   Projects, ProjectDetail, Runs, RolloutDetail,
│   │   │                      #   WeeklyReview, AdminUsers, AdminInvites, Settings
│   │   └── __tests__/         # vitest tests (pure utilities + components)
│   ├── vite.config.ts         # Dev server (port 5173), /api proxy to :8000, vitest config
│   ├── tsconfig.json          # Strict TS (noUnusedLocals, noUnusedParameters)
│   └── eslint.config.js       # ESLint config
├── docs/                      # setup.md (fresh-machine runbook), deploy.md, architecture.md, ...
├── scripts/                   # seed.py (seed user + project), migration SQL, commit-msg check
├── planning/                  # Feature planning docs
│   ├── templates/             # feature.md template
│   └── <branch-name>/        # Per-branch planning (mirrors git branch)
│       └── feature.md         # Feature requirements and design
├── .env.example               # Environment variables template (JWT_SECRET, AGENT_GTD_DATABASE_URL, etc.)
├── .pre-commit-config.yaml    # Git hooks config (ruff, mypy, eslint, tsc, gitleaks, etc.)
├── pyproject.toml             # Python config (deps, ruff, mypy, pytest, semantic-release)
├── start.sh                   # Dev entry point (backend + Vite dev server)
└── serve.sh                   # Production entry point (uvicorn only — see Production Architecture)
```

## What Already Exists

This project ships with a **working app** — not just boilerplate. Before writing new code, understand what's already here:

**Backend (fully functional):**
- Full GTD domain: items (statuses, priorities, blockers), projects, notes, comments, attachments
- Dispatch system: build/plan-mode runs, manage-mode rollouts, dispatch worker + engine router
- MCP server (`agent-gtd-mcp`) and `agent-gtd` CLI — both work in local-DB or HTTP mode
- SSE event stream at `/api/events` for live UI updates
- Auth: JWT login (bcrypt passwords, 72h token expiry), invite-token registration, admin user/invite management, API keys
- `get_current_user` FastAPI dependency — add it to any route that needs auth
- Database: asyncpg PostgreSQL pool, with **SQLite fallback** when `AGENT_GTD_DATABASE_URL` is unset — single-user local mode, auth disabled. Schema auto-creates on startup in both modes. See the "Local Mode vs PostgreSQL Mode" table in `docs/setup.md`.
- Health check endpoint at `/api/health`

**Frontend (fully functional):**
- Login page; separate Register page (registration requires an admin-issued invite token, PostgreSQL mode only — not available in local SQLite mode); password reset
- Inbox with quick capture and triage dialog, plus a dedicated Inbox Processor flow
- GTD list views: Next Actions, Waiting For, Someday/Maybe (cross-project, shared `GtdItemList` component)
- Projects list with create/edit; project detail with kanban board, item detail drawer, notes, and sharing
- Runs and Rollout Detail pages for monitoring dispatched agents, with live SSE activity
- Weekly Review, admin pages (users, invites), Settings page with theme toggle
- Sidebar organized into GTD sections (Collect / Lists / Organize)
- App shell with sidebar navigation, header, and content area
- API client (`api.ts`) that handles auth tokens and snake/camelCase conversion automatically

## Agent Attribution (`created_by`)

Every comment and item created via MCP carries a `created_by` field. Attribution
scheme (live as of cutover date 2026-05-13):

| Value | Who |
|---|---|
| `claude-build-<run_id_short>` | Dispatched build-mode agent (8-char run UUID prefix) |
| `claude-plan-<run_id_short>` | Dispatched plan-mode agent |
| `claude-manage-<run_id_short>` | Dispatched manage-mode agent |
| `claude-lead-<user_id_short>` | Interactive lead (Claude Code in terminal) |
| `wave-manager` | Wave service server-side status comments |
| `human` | Human web UI user in local/single-user mode |
| `alice@example.com` | Authenticated human web UI user in multi-user mode (email from account) |
| `mcp-agent` | **Legacy** — comments predating 2026-05-13 |

Helpers live in `src/agent_gtd/identity.py`.

When reading old `"mcp-agent"` comments, infer actor from branch names,
timestamps, and wave context. Attribution is trustworthy only after cutover.

## Where to Put New Code

| What you're adding | Where it goes |
|---|---|
| New API resource | `src/agent_gtd/routes/new_routes.py` — `note_routes.py` is the simplest existing router and a good copy-from template; mount in `main.py` |
| New domain/API models | `src/agent_gtd/models.py` — domain models at top, request/response schemas below |
| New database tables | `src/agent_gtd/database.py` — add to `_SCHEMA_STATEMENTS` list, tables auto-create on startup |
| New service/business logic | `src/agent_gtd/services/` — follow the existing `*_service.py` modules (e.g. `item_service.py`) |
| New frontend page | `frontend/src/pages/NewPage.tsx` — add route in `App.tsx`, add nav link in `Sidebar.tsx` |
| New frontend component | `frontend/src/components/` — shared/reusable UI components |
| New API namespace | `frontend/src/api.ts` — add a new namespace object (like `notes: { ... }`) |
| New TypeScript types | `frontend/src/types.ts` — keep frontend types in sync with backend response schemas |
| New pure utility function | `frontend/src/utils.ts` — must have a corresponding test in `__tests__/` |
| Backend tests | `tests/test_<module>.py` — use fixtures from `conftest.py` |
| Frontend tests | `frontend/src/__tests__/` — vitest, test pure functions and utilities |

## Planning Convention
When starting a feature branch, create `planning/<branch-name>/feature.md` to capture requirements and design decisions before coding. This serves as a durable reference artifact. Use Claude's built-in task tools for implementation tracking.

## Commit Convention
This repo uses **conventional commits** enforced by a `commit-msg` hook. Format: `type(optional-scope): description`

- `feat:` — new feature (bumps minor)
- `fix:` — bug fix (bumps patch)
- `chore:` — maintenance, deps, config (no bump)
- `docs:` — documentation only (no bump)
- `refactor:` — restructuring (no bump)
- `feat!:` or `fix!:` — breaking change (bumps major)

Releases are **decoupled from commits** (the old post-commit auto-release hook has been removed — `.pre-commit-config.yaml` has no `post-commit` stage). Commit freely on main, push to origin, and deploy liberally during a work session. A release is a deliberate step run at a meaningful boundary via `./release.sh`, which runs `semantic-release version` (bumps pyproject.toml + CHANGELOG.md + uv.lock and tags from the `feat:`/`fix:` commits since the last tag), pushes main + tags to **both** origin and github, then deploys. The version on the settings page tracks the latest release, so this doubles as "promote to UI."

## Code Style
- **Python**: Ruff (linting + formatting), mypy strict mode, Google-style docstrings
- **TypeScript**: ESLint + strict tsconfig (noUnusedLocals, noUnusedParameters)
- **Pre-commit hooks**: Enforced on every commit (ruff, mypy, eslint, tsc, gitleaks secrets detection, trailing whitespace, etc.)
- **Pre-push hooks**: Test coverage enforcement — `git push` is blocked if coverage drops below the `fail_under` threshold in `pyproject.toml`
- Planning directory is excluded from Python linting
- Local hooks that use `uv run` (mypy, pytest, etc.) use `uv run --frozen` to prevent uv from rebuilding the package mid-hook

## Testing Discipline
Tests must be written alongside the code they cover, not bolted on after the fact. When implementing a new feature or fixing a bug:
- **Backend**: Write unit tests for any new pure functions, model defaults, or service logic. Use `hypothesis` for property-based tests where inputs have mathematical invariants (distances, roundtrips, encodings). Privacy-critical paths require explicit test coverage before merging.
- **Frontend**: Write vitest tests for any new pure/exported utility functions. Keep testable logic in pure functions (e.g., `utils.ts`) separate from React components.
- **Run tests before committing**: `uv run pytest` and `npm --prefix frontend run test` should both pass.
- **Ratchet coverage**: After adding tests, increase `fail_under` in `pyproject.toml [tool.coverage.report]` up to the new coverage floor. Coverage should only ever go up.

## Design Principles
- **Proximity** — related controls live next to the content they affect
- **Consistency** — same patterns for same problems (dialogs, loading states, error handling)
- **Sensible defaults** — every setting has a smart default so users can start immediately
- **Keyboard composability** — keyboard shortcuts for common actions, forms submit on Enter
- **Adapt to context** — empty states guide users, populated states show data efficiently
- **Progressive disclosure** — show core actions up front, advanced options in settings/dialogs
- **Minimal chrome** — content-first layout, UI gets out of the way
- **No dead ends** — app logo/title in the header always navigates home; every screen should be escapable
- **Privacy by default** — users who don't understand and just click OK must be protected. Defaults are always the safest option. Users who understand the implications can explicitly open things up.
- **Human verification for critical paths** — AI-generated code that handles privacy or security must produce outputs a human can independently verify. Write scripts, tests, or tooling that make verification easy. "The AI wrote it" is not a defense — the human is accountable, so make accountability painless.

## Patterns to Follow
The existing pages (`Inbox.tsx`, `ProjectDetail.tsx`, `GtdItemList.tsx`, etc.) demonstrate the project's patterns for CRUD, dialogs, API calls, and auth.

- **Backend CRUD**: See `note_routes.py` — ownership checks via `user_id`, PATCH with partial updates (`None` = unchanged), 204 on DELETE, prefix-based router (`/api/notes`)
- **Database**: See `database.py` — `_SCHEMA_STATEMENTS` list for table definitions, `get_db()` for pool, `row_to_dict()` for Record→dict, `encode_json_list()`/`decode_json_list()` for JSON list columns. Uses `$1, $2, ...` placeholders (asyncpg/PostgreSQL), not `?`
- **Models**: See `models.py` — domain models (internal, includes `hashed_password`) separate from response schemas (public, no secrets). Create/Update request models separate from response models.
- **API client**: See `api.ts` — namespaced methods (`api.notes.list()`), automatic snake_case/camelCase conversion on all request/response payloads, 401 auto-redirect to login
- **Dialogs**: See `ProjectDetail.tsx` — shared create/edit dialog distinguished by null/non-null `editing` state, delete confirmation dialog
- **State management**: `useState` + `useEffect` for API data, `useCallback` for stable fetch functions, loading/error/saving states
- **Auth flow**: JWT tokens stored in localStorage (`agent_gtd-token`), `AuthContext` provides login/register/logout, `ProtectedRoute` wraps authenticated pages
- **Theme**: Dark/light toggle via `ThemeContext`, persisted in localStorage
- **Vite proxy**: Frontend dev server proxies `/api` requests to backend at `localhost:8000` — no CORS issues in dev

## Agent GTD Is the Source of Truth

**This project uses itself to manage its own development.** The Agent GTD MCP server (`agent-gtd`) is configured at the user scope in `~/.claude.json`. All work — features, bugs, ideas, someday/maybe items — lives in Agent GTD as items, not in markdown files, roadmap docs, or TODO comments.

**GTD project for this repo:** `cee5e952-c7f4-4115-8d25-17fbb62066b9` (name `agent-gtd-dev`). Use this `project_id` when calling `add_item` / `list_items` for this codebase.

### MANDATORY: Work out of Agent GTD

Every session that involves implementation work MUST follow this workflow:

1. **Check the backlog first.** Run `list_items` to see what's already tracked before starting work. The user may refer to items by title or description — find the matching item rather than starting from scratch. (Authentication is automatic when `AGENT_GTD_API_KEY` is set in the environment — no need to call `login`.)
2. **Capture new work as items.** When the user asks for something new, `add_item` or `inbox_capture` it. Features go to `next_action` or `someday_maybe`. Bugs go to `next_action` with `high` priority. Vague ideas go to `inbox` for later triage.
3. **Mark items done when complete.** After shipping a feature or fix, call `complete_item`. Don't leave stale open items.
4. **Use notes for design decisions.** When making architectural choices during a feature, capture the rationale as a project note via `add_note`. This is especially valuable for decisions that future sessions will need to understand.

### Never create roadmap or TODO files

There is no `docs/roadmap.md`. There are no TODO lists in markdown. If something needs to be tracked, it goes into Agent GTD as an item. If you catch yourself writing "TODO" in a doc or creating a planning list outside the tool, stop and `add_item` instead. We use the tool to build the tool.

### Prerequisites

None for local single-user mode — leave `AGENT_GTD_DATABASE_URL` unset and the app uses SQLite at `~/.local/share/agent_gtd/gtd.db` (auth disabled, fixed `LOCAL_USER_ID`). For multi-user/PostgreSQL mode, create an `agent_gtd` database and set `AGENT_GTD_DATABASE_URL` in `.env` (psql commands in `docs/setup.md`, step 4). Tests always run against in-memory SQLite — no test database or `AGENT_GTD_TEST_DATABASE_URL` is needed.

**First-time setup:**
```bash
uv run python scripts/seed.py    # Creates seed user + project, writes data/seed.json
```

**Seed IDs** are stored in `data/seed.json` (`user_id` and `project_id`). The `data/` directory is gitignored.

## Monitoring dispatched runs — event-driven, not polled

The CLI provides `run-status` and `rollout-status` subcommands that print the
relevant row as JSON to stdout.  Both support a `--wait` flag that blocks until
the run or rollout reaches a terminal state, collapsing the old two-tool pattern
(bash loop + Monitor) into a single call.

The CLI is at full parity with the MCP tool surface (every non-`login` MCP tool
has a matching `agent-gtd` subcommand via the `cli_commands/` package), enforced
by `tests/test_cli_parity.py`.

### Preferred: `--wait` flag (native blocking waiter)

Run in the background and arm a Monitor on the process exit:

```bash
# Blocking run waiter — exits when terminal; exit code encodes outcome.
agent-gtd run-status <run_id> --wait
# exit 0  → success
# exit 2  → failed / cancelled / error / timeout
# exit 124 → client --timeout exceeded (last JSON written to stderr)
# exit 1  → operational error (auth / not-found / network)
```

```bash
# Blocking rollout waiter
agent-gtd rollout-status <rollout_id> --wait
# exit 0  → completed
# exit 2  → failed / halted / cancelled
# exit 124 → client --timeout exceeded
# exit 1  → operational error
```

Additional options:

| Flag | Default | Description |
|---|---|---|
| `--poll-interval SECONDS` | 30 | Seconds between polls (floor: 5 s) |
| `--timeout SECONDS` | 0 (∞) | Client-side timeout; exits 124 on expiry, last JSON to stderr |

Terminal states — **run**: `success`, `failed`, `cancelled`, `error`, `timeout`.
Non-terminal: `pending`, `running`.

Terminal states — **rollout**: `completed`, `failed`, `halted`, `cancelled`.
Non-terminal: `pending`, `planning`, `running`.

Transient network/5xx errors during a wait are retried at the next poll
interval, not fatal.  Auth / not-found errors abort immediately with exit 1.

### Fallback: bash poll loop + Monitor

Keep the bash loop if you need fine-grained control (e.g., custom back-off,
per-poll side-effects) or cannot use blocking processes:

**Run:**

```bash
until s=$(agent-gtd run-status <run_id> | jq -r .status) && \
      [ "$s" != "pending" ] && [ "$s" != "running" ]; do
  sleep 30
done
echo "DONE run <run_id> status=$s"
```

Arm a Monitor on `"DONE run <run_id>"` in the script's output. When the run
reaches a terminal state (`success`, `failed`, `cancelled`), the Monitor fires.

**Rollout:**

```bash
until s=$(agent-gtd rollout-status <rollout_id> | jq -r .status) && \
      [ "$s" != "pending" ] && [ "$s" != "planning" ] && [ "$s" != "running" ]; do
  sleep 30
done
echo "DONE rollout <rollout_id> status=$s"
```

Arm a Monitor on `"DONE rollout <rollout_id>"` in the script's output. When
the rollout reaches a terminal state (`completed`, `failed`, `halted`,
`cancelled`), the Monitor fires.

### Auth / mode

Both commands follow the same auth logic as the MCP server:
- **Local mode** (no `AGENT_GTD_URL`): reads directly from the local DB,
  uses `LOCAL_USER_ID`, no credentials needed.
- **HTTP mode** (`AGENT_GTD_URL` + `AGENT_GTD_API_KEY`): authenticates via
  the API key and calls the REST API.
