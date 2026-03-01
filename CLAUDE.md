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
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type post-commit --hook-type pre-push

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
│   ├── database.py            # Async PostgreSQL (asyncpg), connection pool
│   ├── models.py              # Pydantic v2 domain models + API request/response schemas
│   └── routes/
│       ├── auth_routes.py     # POST register, login, logout; GET me
│       └── note_routes.py     # Notes CRUD — example resource, replace with your domain
├── tests/
│   ├── conftest.py            # Shared fixtures (async client, test DB, auth helpers)
│   ├── test_auth.py           # Auth endpoint tests
│   └── test_smoke.py          # Health check, app startup
├── frontend/                  # React 19 + TypeScript + MUI 7 (Vite)
│   ├── src/
│   │   ├── App.tsx            # Route definitions (react-router-dom v7)
│   │   ├── main.tsx           # React root with Auth + Theme providers
│   │   ├── api.ts             # Typed API client — auto snake/camelCase conversion
│   │   ├── types.ts           # TypeScript interfaces matching backend response schemas
│   │   ├── utils.ts           # Pure utilities (key conversion) — tested
│   │   ├── theme.ts           # MUI theme customization
│   │   ├── contexts/
│   │   │   ├── AuthContext.tsx # Login/register/logout, JWT in localStorage
│   │   │   └── ThemeContext.tsx# Dark/light toggle, persisted in localStorage
│   │   ├── components/
│   │   │   ├── Layout.tsx     # App shell: header, sidebar, content area
│   │   │   ├── Sidebar.tsx    # Navigation drawer
│   │   │   └── ProtectedRoute.tsx  # Redirects to /login if not authenticated
│   │   ├── pages/
│   │   │   ├── Login.tsx      # Login + registration form
│   │   │   ├── Dashboard.tsx  # Notes CRUD — example page, replace with your domain
│   │   │   └── Settings.tsx   # User settings (theme toggle, etc.)
│   │   └── __tests__/
│   │       └── utils.test.ts  # Tests for pure utility functions
│   ├── vite.config.ts         # Dev server (port 5173), /api proxy to :8000, vitest config
│   ├── tsconfig.json          # Strict TS (noUnusedLocals, noUnusedParameters)
│   └── eslint.config.js       # ESLint config
├── docs/                      # Project documentation
├── planning/                  # Feature planning docs
│   ├── templates/             # feature.md template
│   └── <branch-name>/        # Per-branch planning (mirrors git branch)
│       └── feature.md         # Feature requirements and design
├── .env.example               # Environment variables template (JWT_SECRET, DATABASE_URL, etc.)
├── .pre-commit-config.yaml    # Git hooks config (ruff, mypy, eslint, tsc, gitleaks, etc.)
├── pyproject.toml             # Python config (deps, ruff, mypy, pytest, semantic-release)
└── start.sh                   # Dev server launcher (backend + frontend)
```

## What Already Exists

This project ships with a **working app** — not just boilerplate. Before writing new code, understand what's already here:

**Backend (fully functional):**
- User registration and login with JWT auth (bcrypt passwords, 72h token expiry)
- `get_current_user` FastAPI dependency — add it to any route that needs auth
- Async PostgreSQL database (asyncpg pool), schema auto-creation on startup
- Notes CRUD API as a reference implementation (list, create, get, update, delete)
- Health check endpoint at `/api/health`

**Frontend (fully functional):**
- Login page with registration flow
- Dashboard with Notes CRUD UI (cards, create/edit dialog, delete confirmation)
- Settings page with theme toggle
- App shell with sidebar navigation, header, and content area
- API client (`api.ts`) that handles auth tokens and snake/camelCase conversion automatically

**The notes app is example scaffolding.** It demonstrates the project's patterns for CRUD, dialogs, API calls, auth, etc. Replace it with your actual domain — don't build alongside it.

## Where to Put New Code

| What you're adding | Where it goes |
|---|---|
| New API resource (e.g., photos, tasks) | `src/agent_gtd/routes/new_routes.py` — copy `note_routes.py` as a starting point, mount in `main.py` |
| New domain/API models | `src/agent_gtd/models.py` — domain models at top, request/response schemas below |
| New database tables | `src/agent_gtd/database.py` — add to `_SCHEMA_STATEMENTS` list, tables auto-create on startup |
| New service/business logic | `src/agent_gtd/services/` — create this directory for non-trivial logic that doesn't belong in routes |
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

Releases are automated via a post-commit hook on main. When a `feat:` or `fix:` commit lands on main, `semantic-release version` runs automatically — bumps pyproject.toml, updates CHANGELOG.md and uv.lock, commits, and tags. You just need to `git push origin main --tags` after.

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
The notes app (`note_routes.py`, `Dashboard.tsx`, etc.) is example scaffolding that demonstrates the project's patterns. Replace it with your actual domain — don't build alongside it.

- **Backend CRUD**: See `note_routes.py` — ownership checks via `user_id`, PATCH with partial updates (`None` = unchanged), 204 on DELETE, prefix-based router (`/api/notes`)
- **Database**: See `database.py` — `_SCHEMA_STATEMENTS` list for table definitions, `get_db()` for pool, `row_to_dict()` for Record→dict, `encode_json_list()`/`decode_json_list()` for JSON list columns. Uses `$1, $2, ...` placeholders (asyncpg/PostgreSQL), not `?`
- **Models**: See `models.py` — domain models (internal, includes `hashed_password`) separate from response schemas (public, no secrets). Create/Update request models separate from response models.
- **API client**: See `api.ts` — namespaced methods (`api.notes.list()`), automatic snake_case/camelCase conversion on all request/response payloads, 401 auto-redirect to login
- **Dialogs**: See `Dashboard.tsx` — shared create/edit dialog distinguished by null/non-null `editing` state, delete confirmation dialog
- **State management**: `useState` + `useEffect` for API data, `useCallback` for stable fetch functions, loading/error/saving states
- **Auth flow**: JWT tokens stored in localStorage (`agent_gtd-token`), `AuthContext` provides login/register/logout, `ProtectedRoute` wraps authenticated pages
- **Theme**: Dark/light toggle via `ThemeContext`, persisted in localStorage
- **Vite proxy**: Frontend dev server proxies `/api` requests to backend at `localhost:8000` — no CORS issues in dev

## MCP Dogfooding

An MCP server (`agent-gtd`) is configured in `.mcp.json` for Claude Code. It exposes 16 GTD tools (items, notes, projects) via stdio.

**Prerequisites:** PostgreSQL with `agent_gtd` and `agent_gtd_test` databases. Connection strings in `.env` (`DATABASE_URL` and `TEST_DATABASE_URL`).

**First-time setup:**
```bash
uv run python scripts/seed.py    # Creates seed user + project, writes data/seed.json
```

**Seed IDs** are stored in `data/seed.json` (`user_id` and `project_id`). The `data/` directory is gitignored.

**Registration flow** — before using project-scoped tools, call:
```
register_agent(user_id=<from seed.json>, project_id=<from seed.json>, agent_name="claude-code")
```

Then use `inbox_capture`, `list_items`, `add_note`, etc. to manage work.
