# Codebase Structure and Patterns

## Code Organization

```
agent_gtd/
├── src/agent_gtd/              # Python backend (FastAPI)
│   ├── main.py                 # App entry: CORS, router mounts, lifespan, migrations
│   ├── auth.py                 # JWT (HS256, 72h), bcrypt, API key hashing
│   ├── database.py             # Connection pool, schema (_SCHEMA_STATEMENTS), helpers
│   ├── sqlite_pool.py          # asyncpg-compatible wrapper around aiosqlite
│   ├── models.py               # Pydantic v2 enums, domain models, request/response schemas
│   ├── exceptions.py           # Custom exception types (NotFoundError, VersionConflictError, …)
│   ├── identity.py             # Attribution helpers (created_by computation)
│   ├── event_bus.py            # In-process asyncio pub/sub for SSE fan-out
│   ├── event_helpers.py        # best_effort_publish() wrapper for fire-and-forget events
│   ├── dispatch_worker.py      # Background task: dispatch runs to remote hosts, poll, reconcile
│   ├── dispatch_constants.py   # Shared constants for dispatch (engine names, etc.)
│   ├── mcp_server.py           # FastMCP server: 40+ MCP tools for AI agents
│   ├── mcp_backend.py          # HTTP backend adapter for MCP (for remote MCP mode)
│   ├── db_types.py             # Type aliases for DB rows
│   ├── cli.py                  # CLI entry point (agent-gtd command)
│   ├── util/                   # Pure utility modules
│   ├── routes/                 # FastAPI routers (one file per resource)
│   │   ├── auth_routes.py      # POST register/login/logout, GET me, API keys
│   │   ├── item_routes.py      # Items CRUD, inbox shortcuts, blockers, claim/release
│   │   ├── project_routes.py   # Projects CRUD, member sharing
│   │   ├── note_routes.py      # Notes CRUD
│   │   ├── comment_routes.py   # Comments CRUD (project-scoped and item-scoped)
│   │   ├── dispatch_routes.py  # Runs, dispatch settings, capabilities, hosts
│   │   ├── event_routes.py     # SSE streaming with replay
│   │   ├── rollout_routes.py   # Rollout lifecycle (plan/start/advance/halt/cancel)
│   │   ├── settings_routes.py  # User and app settings
│   │   ├── attachment_routes.py# File attachments on items
│   │   └── admin_routes.py     # Admin-only: user management, invites
│   └── services/               # Business logic (shared by routes and MCP tools)
│       ├── item_service.py
│       ├── project_service.py
│       ├── note_service.py
│       ├── comment_service.py
│       ├── rollout_service.py
│       ├── rollout_lock_service.py
│       ├── dispatch_service.py
│       ├── dispatch_router.py  # Multi-host capacity routing
│       ├── settings_service.py
│       └── attachment_service.py
├── tests/                      # pytest tests
│   ├── conftest.py             # Fixtures: async client, in-memory SQLite, auth helpers
│   └── test_*.py               # One file per resource or concern
├── frontend/                   # React 19 + TypeScript + MUI 7 (Vite)
│   ├── src/
│   │   ├── App.tsx             # Route definitions (react-router-dom v7)
│   │   ├── main.tsx            # React root with Auth + Theme providers
│   │   ├── api.ts              # Typed API client — namespaced, auto snake/camelCase
│   │   ├── types.ts            # TypeScript interfaces matching backend response schemas
│   │   ├── utils.ts            # Pure utilities (key conversion) — fully tested
│   │   ├── theme.ts            # MUI theme customization
│   │   ├── contexts/           # AuthContext, ThemeContext
│   │   ├── components/         # Shared UI components (Layout, Sidebar, GtdItemList, …)
│   │   ├── pages/              # Route-level page components
│   │   └── __tests__/          # vitest tests for pure utility functions and components
│   ├── vite.config.ts          # Dev server (5173), /api proxy to :8000, vitest config
│   ├── tsconfig.json           # Strict TS (noUnusedLocals, noUnusedParameters)
│   └── eslint.config.js        # ESLint config
├── docs/                       # Project documentation (this directory)
├── planning/                   # Feature planning docs and templates
├── scripts/                    # Operational scripts (seed.py, etc.)
├── .env.example                # Environment variable template
├── .pre-commit-config.yaml     # Git hooks (ruff, mypy, eslint, tsc, gitleaks, …)
├── pyproject.toml              # Python config (deps, ruff, mypy, pytest, coverage, semver)
├── start.sh                    # Dev entry point: uvicorn + Vite dev server
└── serve.sh                    # Production entry point: uvicorn only
```

The `routes/` layer is thin — it handles HTTP concerns (request parsing, auth dependency,
status codes) and delegates all business logic to the corresponding service. MCP tools call the
same service functions, ensuring consistent behaviour regardless of entry point.

## Style Guide

**Python:**
- **Formatter/linter:** Ruff (line length 88, target Python 3.13).
- **Type checking:** mypy in strict mode (`--strict`). All public functions require type annotations. `TYPE_CHECKING` guards for imports used only in annotations.
- **Docstrings:** Google style, enforced by Ruff's `D` rule set. One-line docstrings for simple functions; multi-line for anything with parameters or return values worth documenting.
- **Naming:** `snake_case` for functions and variables; `PascalCase` for classes and Pydantic models; `UPPER_SNAKE_CASE` for module-level constants.
- **Async:** All I/O is async. Route handlers and service functions are `async def`. Sync utility functions (pure computation) may be plain `def`.
- **Exceptions:** Raise project-specific exceptions from `exceptions.py`, not raw `HTTPException`, inside service functions. Routes catch service exceptions and map them to HTTP responses.

**TypeScript / React:**
- **Strict mode:** `noUnusedLocals` and `noUnusedParameters` are enabled. The build fails if either is violated.
- **ESLint:** Configured via `eslint.config.js`. No console.log in committed code.
- **Naming:** `camelCase` for variables and functions; `PascalCase` for components and types; `UPPER_SNAKE_CASE` for constants.
- **Component files:** One component per file. File name matches the component name (e.g. `GtdItemList.tsx`).
- **Typed API client:** All backend calls go through `api.ts`. The client automatically converts snake_case JSON keys from the backend to camelCase for TypeScript, and camelCase request fields back to snake_case. Never call `fetch()` or `axios` directly in components.

## Common Patterns

### Backend: Database Queries

Use asyncpg positional placeholders (`$1, $2, ...`), not `?`. The database pool is retrieved
via `get_db()`.

```python
db = await get_db()
row = await db.fetchrow(
    "SELECT * FROM items WHERE id = $1 AND user_id = $2",
    item_id, user_id
)
if row is None:
    raise NotFoundError(f"Item {item_id} not found")
return row_to_dict(row)
```

**JSON list columns** (`labels`, `acceptance_criteria`, `scope_out`) must be encoded/decoded:

```python
# Writing
await db.execute(
    "INSERT INTO items (labels) VALUES ($1)",
    encode_json_list(labels or [])
)

# Reading (in row_to_dict or manually)
labels = decode_json_list(row["labels"])
```

**`files_to_modify`** uses `encode_file_specs()` / `decode_file_specs()` since it holds a list
of `{"path": str, "change": str}` dicts, not plain strings.

### Backend: Schema Evolution

Add new tables or columns by appending to `_SCHEMA_STATEMENTS` in `database.py`. All
statements use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. There is no
migration framework — statements are idempotent and run at every startup. For column additions
on existing tables, use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (PostgreSQL) or a one-time
migration function called from `lifespan()`.

### Backend: Ownership Checks and Error Mapping

Services raise `NotFoundError` (not 403/404) for both "not found" and "not your resource"
cases. This prevents enumeration — an unauthorized caller cannot distinguish between
"does not exist" and "exists but you can't see it". Routes map exceptions to HTTP responses:

```python
try:
    item = await item_service.get_item(db, user_id, item_id)
except NotFoundError:
    raise HTTPException(status_code=404, detail="Item not found")
```

### Backend: Optimistic Locking

Every `UPDATE` on `items` requires the caller to pass the current `version`. The service
increments `version` on every write. If the caller's version does not match the DB row, the
service raises `VersionConflictError` and the route returns 409. This prevents silent data loss
from concurrent edits by multiple agents or UI tabs.

```python
# Service side
if row["version"] != caller_version:
    raise VersionConflictError("Version conflict on item update")
```

### Backend: Sentinel Semantics for Nullable Fields

The `update_item` MCP tool uses a sentinel pattern to distinguish "omitted" from "clear":
- `None` (omitted) → field unchanged
- `""` (empty string) → field cleared (set to NULL in DB)
- Non-empty value → field set to that value

This avoids the need for `Optional` fields that accidentally clear data when omitted. The same
pattern applies to `due_date`, `build_engine`, and `project_id` in MCP tool calls.

### Backend: Service Layer Separation

Business logic lives exclusively in `services/`. Routes do not issue raw SQL. MCP tools do
not issue raw SQL. This separation keeps routes thin and enables easy unit testing of service
functions without HTTP overhead.

```python
# Route (thin)
@router.post("/api/items", response_model=ItemResponse, status_code=201)
async def create_item(body: CreateItemRequest, user: User = Depends(get_current_user)):
    db = await get_db()
    item = await item_service.create_item(db, user.id, **body.model_dump())
    return item

# Service (all logic here)
async def create_item(db, user_id: str, title: str, ...) -> dict:
    ...
```

### Frontend: API Client

All backend communication goes through the namespaced `api` object in `api.ts`. It handles
JWT token injection, snake_case ↔ camelCase conversion, and 401 auto-redirect to `/login`.

```typescript
// Adding a new resource (copy the pattern from api.ts)
export const api = {
  items: {
    list: (params?) => get<ItemResponse[]>('/api/items', params),
    create: (body) => post<ItemResponse>('/api/items', body),
    update: (id, body) => patch<ItemResponse>(`/api/items/${id}`, body),
    delete: (id) => del(`/api/items/${id}`),
  },
  // ... other namespaces
}
```

Never call `fetch()` directly in React components. If an endpoint is missing from `api.ts`,
add it there.

### Frontend: Dialogs

Shared create/edit dialogs are distinguished by a nullable `editing` state. When `editing`
is `null`, the dialog is in create mode; when it holds an item, it's in edit mode. This is
the project-wide convention — do not create separate `CreateFoo` and `EditFoo` components.

```typescript
const [editing, setEditing] = useState<Item | null>(null);
const [dialogOpen, setDialogOpen] = useState(false);

// Open for create
<Button onClick={() => { setEditing(null); setDialogOpen(true); }}>New</Button>

// Open for edit
<Button onClick={() => { setEditing(item); setDialogOpen(true); }}>Edit</Button>
```

### Frontend: State Management

Use `useState` + `useEffect` for server data, `useCallback` for stable fetch functions. No
Redux or Zustand — the app is simple enough that component-local state suffices. Data is
refetched on mutation success, not optimistically updated (keeps the implementation simpler
and the UI always consistent with the server).

```typescript
const [items, setItems] = useState<Item[]>([]);
const [loading, setLoading] = useState(true);

const loadItems = useCallback(async () => {
  setLoading(true);
  try {
    setItems(await api.items.list());
  } finally {
    setLoading(false);
  }
}, []);

useEffect(() => { loadItems(); }, [loadItems]);
```

### Frontend: Pure Utility Functions

Keep testable logic in pure functions in `utils.ts`, separate from React components. Every
exported function in `utils.ts` must have a corresponding test in `__tests__/utils.test.ts`.
This is enforced by convention, not tooling — do not skip it.

## Testing

Backend tests are in `tests/`, one file per resource or concern (`test_items.py`,
`test_rollout_service.py`, etc.). Frontend tests are in `frontend/src/__tests__/`.

**Run all backend tests:**
```bash
uv run pytest
```

**Run with coverage:**
```bash
uv run pytest --cov=agent_gtd
```

**Run frontend tests:**
```bash
npm --prefix frontend run test
```

See `docs/testing.md` for the full testing strategy, including hypothesis property-based tests,
vitest setup, coverage ratchet, and pre-push hook enforcement.

## Developer Onboarding

**What to read first:**
1. `docs/domain.md` — understand the GTD concepts and entity model
2. `docs/architecture.md` — understand the system design
3. `CLAUDE.md` — project conventions, git workflow, commit format
4. `src/agent_gtd/main.py` — see how routers are mounted and the lifespan is set up
5. `src/agent_gtd/routes/note_routes.py` — reference CRUD implementation to clone

**Local development setup:**
```bash
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type post-commit --hook-type pre-push
cp .env.example .env   # edit JWT_SECRET and AGENT_GTD_DATABASE_URL
./start.sh             # starts uvicorn + Vite dev server
```

See `docs/setup.md` for the complete setup guide including PostgreSQL creation and seed data.

**Common issues:**
- **Hook failures on commit:** Run `uv run pre-commit run --all-files` to see all linting errors at once before committing.
- **Type errors from asyncpg:** asyncpg `Record` is not a plain `dict`. Use `row_to_dict(row)` to convert before returning from service functions.
- **SQLite vs PostgreSQL differences:** Tests run against in-memory SQLite. If you use PostgreSQL-specific syntax (e.g., `ON CONFLICT DO UPDATE`), add a SQLite-compatible fallback or check in the fixture.

## Anti-patterns We've Learned About

> Findings from the May 2026 codebase audit and prior debugging sessions. Each entry is a brief description of the misfire — treat these as "don't repeat this" guidance.

- **Raw SQL in routes:** Routes used to issue queries directly via `get_db()`. All business logic must live in `services/` — routes are thin HTTP adapters only.
- **Calling `fetch()` directly in React components:** Early components bypassed `api.ts`, missing auth token injection and snake/camelCase conversion. All API calls must go through the `api` object.
- **Skipping `row_to_dict()`:** Returning a raw asyncpg `Record` from a service function causes serialization errors in routes and breaks mypy. Always convert with `row_to_dict()`.
- **Using `?` placeholders:** asyncpg requires positional `$1, $2, ...` placeholders. `?` silently fails or raises a runtime error depending on the DB driver. SQLite tests may pass with `?` if using the wrong path — always use `$N` style.
- **Mutating `None` JSON columns:** `labels`, `acceptance_criteria`, `scope_out` default to `'[]'` in the schema, but can be `None` if a row was inserted before the default was added. Always decode with `decode_json_list(row["labels"] or "[]")`.
- **Not installing pre-commit hooks after clone:** Working-tree edits that bypass hooks have landed on origin as lint and format regressions. Run `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type post-commit --hook-type pre-push` every time you clone fresh — this happened three times on 2026-05-13.
- **Using `--no-verify` to skip hooks:** Never bypass hooks. Fix the underlying issue. If the commit-msg hook fails, the commit message doesn't follow conventional commits format — fix it.
- **Running Vite in production:** The HMR WebSocket reconnect causes page reloads in the background tab. Production must serve `frontend/dist/` via nginx. `serve.sh` is the production entry point; `start.sh` is development-only.
- **Storing roadmaps in markdown files:** There are no roadmap or TODO markdown files in this repo. All tracked work lives in Agent GTD as items. If you're tempted to write a `TODO.md`, create a GTD item instead.
- **`*.bak` files in nginx `sites-enabled/`:** nginx loads every file in that directory. Backups stored there produce "conflicting server name" warnings and may serve stale config. Always back up to `/etc/nginx/backups/`.
- **Blockers across projects:** Blocker relationships are only valid between items in the same project. The service enforces this. Do not attempt to create cross-project blockers — they will be rejected (and historically cleaned up by `_sweep_cross_project_blockers`).
- **Not incrementing `fail_under` after adding tests:** The coverage threshold in `pyproject.toml` must be ratcheted up whenever coverage increases. Leaving it stale allows future regressions to pass silently.

## Pointers

> - `kb-00306`: Deployment architecture details (r7-research server setup)
> - `kb-00307`: Bounce guidelines and operational procedures
> - `docs/deploy.md`: Full nginx + systemd deployment runbook
> - `docs/architecture.md`: System design and component relationships
> - `docs/api-docs.md`: Full REST and MCP API reference
