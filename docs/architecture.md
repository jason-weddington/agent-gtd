# System Architecture

## High-Level Design

Agent GTD is a FastAPI-based task management system designed for coordinating AI coding agents
and human operators using GTD (Getting Things Done) methodology. The system combines a REST API
for the web frontend, an MCP server for AI agent tooling, a real-time SSE event bus for live
updates, and a background dispatch worker that routes tasks to remote Claude Code instances.

The application runs as a single Python process (uvicorn) behind an nginx reverse proxy in
production. nginx terminates TLS and serves the pre-built React frontend as static files — the
Vite dev server is not present in production. The backend shares one database pool with both the
REST API and the MCP server.

```
client (HTTPS 443)
   │
   ▼
nginx (r7-research)              ← terminates TLS, serves frontend/dist/
   ├── /              → static files (SPA fallback to index.html)
   ├── /api/events    → uvicorn :8000   (SSE — proxy_buffering off)
   ├── /api/*         → uvicorn :8000   (FastAPI REST)
   └── /mcp           → uvicorn :8000   (FastMCP HTTP transport)
```

## Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│         (MUI 7, react-router-dom v7, Vite build)         │
│  EventSource ──► /api/events    REST ──► /api/*          │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP (via nginx)
                            ▼
┌─────────────────────────────────────────────────────────┐
│                      FastAPI App                         │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ REST Routes  │  │  MCP Server  │  │  SSE Routes    │  │
│  │ /api/*       │  │  /mcp        │  │  /api/events   │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                 │                   │           │
│         ▼                 ▼                   │           │
│  ┌─────────────────────────────────┐          │           │
│  │         Service Layer            │          │           │
│  │  item_service, project_service,  │          │           │
│  │  rollout_service, comment_service│          │           │
│  └───────────┬─────────────┬───────┘          │           │
│              │             │                  │           │
│              ▼             ▼                  │           │
│  ┌──────────────┐  ┌──────────────┐           │           │
│  │  PostgreSQL  │  │  Event Bus   │◄──────────┘           │
│  │  (asyncpg)   │  │  (asyncio)   │                       │
│  └──────────────┘  └──────────────┘                       │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐  │
│  │            Dispatch Worker (background)              │  │
│  │  Poll queue → remote Claude Code host → SSE events  │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
             Remote Claude Code hosts
         (dispatch protocol over HTTPS)
```

## Data Flow

1. **Human creates a task (web UI):** React → POST `/api/items` → item_service writes to DB → event_bus publishes `item.created` → SSE streams event to all connected clients.

2. **Agent captures a task (MCP):** Agent calls `inbox_capture()` → mcp_server validates session → item_service writes to DB → event_bus publishes `item.created` → SSE syncs web UI in real time.

3. **Task is dispatched to a remote agent:** Human or manager agent calls POST `/api/items/{id}/dispatch` → dispatch_service creates a `claude_runs` row (status=pending) → enqueues run ID in dispatch worker's async queue → worker resolves engine/agent/timeout from per-project and global overrides → posts to remote dispatch host → polls until terminal → publishes `run_completed` or `run_failed` SSE event.

4. **Frontend receives live updates:** React's `EventSource` listens on `/api/events`. nginx disables `proxy_buffering` for this endpoint so events are not batched. Each SSE event carries a full entity snapshot so the client can update state without a follow-up fetch. On reconnect, the client passes `?since=<last_event_id>` to replay missed events from the persisted `events` table.

5. **MCP client reconnects:** The MCP server is stateless between tool calls. Session context is resolved per-call from `AGENT_GTD_API_KEY` env var (auto-auth) or a prior `login()` call stored in FastMCP context state.

## Key Components

### FastAPI Application (`main.py`)

- **Purpose:** Application entry point. Mounts all routers, runs startup/shutdown logic, starts the dispatch worker background task.
- **Interfaces:** ASGI app, served by uvicorn.
- **Lifespan:** Runs DB schema initialization, three one-time migrations (agent name backfill, engine rename, manager timeout default), starts dispatch worker task, reconciles any active runs from a prior restart, and drains the event bus on shutdown.
- **Local mode:** When `AGENT_GTD_DATABASE_URL` is absent, FastAPI overrides `get_current_user` with `get_local_user`, bypassing JWT auth entirely. This enables single-user SQLite deployments without credentials.

### MCP Server (`mcp_server.py`)

- **Purpose:** Serves 40+ MCP tools for AI agents over FastMCP's HTTP transport, mounted at `/mcp`.
- **Interfaces:** FastMCP `Server` instance; shares the same database pool and service layer as the REST API.
- **Session management:** Resolution order: (1) existing session from prior `login()` call, (2) local SQLite mode auto-creates a default session, (3) `AGENT_GTD_API_KEY` env var auto-authenticates, (4) raises `ToolError("Not logged in")`.
- **Tool groups:** Projects (CRUD + sharing), Items (CRUD + blockers + claim/release), Notes (CRUD), Comments, Dispatch runs, Rollout manager (plan/start/advance/halt/cancel/replan).
- **Destructive hints:** Tools that delete data or halt rollouts carry `annotations={"destructiveHint": True}` for MCP-aware clients.

### Database Layer (`database.py`, `sqlite_pool.py`)

- **Purpose:** Manages the connection pool and schema lifecycle.
- **PostgreSQL mode** (default): `asyncpg.create_pool(dsn)` when `AGENT_GTD_DATABASE_URL` is set.
- **SQLite mode** (local/test): `SqlitePool` wraps `aiosqlite` with the same `asyncpg`-compatible interface.
- **Schema:** Defined in `_SCHEMA_STATEMENTS` — a list of `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX` statements applied at startup. Tables never dropped automatically; add new statements to evolve the schema.
- **Query style:** asyncpg positional placeholders (`$1, $2, ...`), not `?`. All JSON columns (`labels`, `acceptance_criteria`, `files_to_modify`, `scope_out`) are stored as JSON text and decoded via `decode_json_list()` / `decode_file_specs()` helpers.
- **Helper functions:** `row_to_dict()` converts an asyncpg `Record` to `dict`; `encode_json_list()` / `decode_json_list()` handle JSON list columns; `encode_file_specs()` / `decode_file_specs()` handle the structured `files_to_modify` field.

### Service Layer (`services/`)

- **Purpose:** Contains all business logic. Both REST routes and MCP tools call the same service functions — this is the single source of truth for data mutations.
- **Modules:** `item_service`, `project_service`, `note_service`, `comment_service`, `rollout_service`, `rollout_lock_service`, `dispatch_service`, `dispatch_router`, `settings_service`, `attachment_service`.
- **Ownership checks:** Every service function accepts `user_id` and verifies the caller owns or has access to the requested entity. Raises `NotFoundError` (not 403) for unauthorized access to prevent enumeration.
- **Exceptions:** Custom exceptions in `exceptions.py` — `NotFoundError`, `VersionConflictError`, `BlockersUnresolvedError`, `RolloutItemLockedError`, `LegalityContractError`, `AlreadyClaimedError`.

### Event Bus (`event_bus.py`)

- **Purpose:** In-process pub/sub for SSE fan-out. Events are published by service layer calls and streamed to connected clients.
- **Interfaces:** `subscribe(user_id)` → `asyncio.Queue`, `publish(...)`, `replay_since(...)`, `drain()`.
- **Storage:** Events are persisted to the `events` table in addition to in-memory fan-out. This enables resumable SSE streams via `?since=<event_id>`.
- **Dependencies:** PostgreSQL/SQLite (event persistence), `asyncio` (queue management).

### SSE Endpoint (`routes/event_routes.py`)

- **Purpose:** Streams real-time events to the React frontend.
- **Protocol:** Server-Sent Events (`text/event-stream`). Each event is formatted as `event: <type>\ndata: <json>\n\n`. A heartbeat comment (`": heartbeat"`) is sent every 30 seconds to keep connections alive through proxies.
- **Resumability:** On connect with `?since=<event_id>`, the endpoint calls `replay_since()` to batch-send missed events before entering the live stream.
- **Auth:** Accepts JWT via `Authorization: Bearer` header or `?token=` query parameter (required for `EventSource`, which cannot set custom headers).

### Dispatch Worker (`dispatch_worker.py`)

- **Purpose:** Background asyncio task that executes dispatch runs against remote Claude Code hosts.
- **Interfaces:** `enqueue_run(run_id)` puts a run ID onto the module-level `asyncio.Queue`; the worker loop drains it. `reconcile_active_runs()` is called at startup to resume any runs that were in-flight before a restart.
- **Dependencies:** Remote dispatch service (HTTPS), `dispatch_router` (host selection), `event_bus` (run_started/run_completed/run_failed events).
- **Configuration:** Engine, agent name, timeout, and max_turns are resolved at dispatch time from item → project → global settings, in that priority order.

### Identity & Attribution (`identity.py`)

- **Purpose:** Computes `created_by` values for items, comments, and runs.
- **Scheme:**
  - Dispatched build agent: `"claude-build-<first_8_chars_of_run_id>"`
  - Dispatched plan agent: `"claude-plan-<first_8_chars_of_run_id>"`
  - Dispatched manage agent: `"claude-manage-<first_8_chars_of_run_id>"`
  - Interactive lead agent: `"claude-lead-<first_8_chars_of_user_id>"`
  - Web UI user (authed): `<email_address>`
  - Fallback: `"human"`

## SSE Event Bus Design

The event bus is a single in-process `EventBus` instance shared across the application. It is
not Redis-backed — a single-server deployment is the target architecture.

**Publishing:** The service layer calls `event_bus.publish(db, user_id=..., event_type=...,
entity_type=..., entity_id=..., project_id=..., payload=...)`. This writes to the `events` DB
table (for replay) and fans out to all in-memory subscriber queues for the owner and any
project members.

**Subscriber queues:** Each SSE connection gets its own `asyncio.Queue` with `maxsize=256`. On
overflow, the oldest event is dropped (non-blocking). The SSE handler reads from the queue and
formats each event as SSE text.

**Shared project events:** When `project_id` is set, the event is delivered to the project
owner's queue and to all project members' queues (resolved from the `project_members` table).

**Replay:** `replay_since(db, user_id, since_id, project_ids)` queries the `events` table for
events created after the `since_id` event's timestamp, scoped to the user's own events and
any shared project events. Results are returned in ascending order.

## MCP Server Surface

The MCP server is mounted at `/mcp` using FastMCP's HTTP transport (Streamable HTTP). It shares
the same FastAPI `app` instance and database pool.

**Tool groups:**
- **Projects:** `list_projects`, `add_project`, `update_project`, `share_project`, `unshare_project`, `list_project_members`
- **Items:** `inbox_capture`, `add_item`, `get_item`, `update_item`, `complete_item`, `delete_item`, `list_items`
- **Blockers:** `add_blocker`, `remove_blocker`, `list_blockers`
- **Notes:** `add_note`, `get_note`, `update_note`, `delete_note`, `list_notes`
- **Comments:** `add_comment`, `list_comments`, `update_comment`
- **Dispatch:** `dispatch_item`, `get_run_status`, `list_runs`
- **Rollout management:** `plan_rollout`, `start_rollout`, `get_rollout`, `get_rollout_plan`, `list_rollouts`, `advance_rollout`, `complete_item_in_rollout`, `halt_rollout`, `cancel_rollout`, `replan_rollout`, `update_rollout_state`, `dispatch_rollout`

## Rollout / Run / Item Execution Model

A **rollout** (also called a "wave") coordinates the dispatch of multiple related items to AI
agents in a dependency-ordered sequence.

**Lifecycle:**
1. **Planning** (`plan_rollout`): A planner model (called by `dispatch_rollout` or manually via
   `plan_rollout`) validates the legality contract (items must be `status=ready`, have non-empty
   `acceptance_criteria` and `files_to_modify`, have `build_engine` set, and share a project),
   then constructs a DAG of items and their ordering relationships. Stores the plan in
   `rollout_plans` (nodes = item IDs, edges = dependency pairs) and creates `rollout_items` rows
   for each item (all `status=pending` initially).

2. **Running** (`start_rollout` or `dispatch_rollout`): Rollout status transitions from `pending`
   → `running`. `dispatch_rollout` also launches a manage-mode agent responsible for driving the
   wave through completion.

3. **Dispatching** (`dispatch_item` with `rollout_id`): The manage agent (or human) calls
   `advance_rollout` to get the next ready items (no unmet predecessors), then dispatches each
   via `dispatch_item`. A `claude_runs` row is created (mode=`build`) and the dispatch worker
   executes it against a remote Claude Code host. The item is locked via `locked_by_rollout_id`
   to prevent concurrent modification.

4. **Completing** (`complete_item_in_rollout`): After a build agent pushes a branch and the
   human (or manager) merges it, `complete_item_in_rollout` is called with outcome
   `completed`, `halted`, or `skipped`. This unlocks the item, marks the rollout_item row, and
   unblocks downstream items.

5. **Terminal states:** `completed` (all items done), `halted` (manager paused for human
   input), `cancelled`, `failed`.

**State tracking:** The manage agent updates `autonomous_rollouts.manager_phase` and
`manager_current_item_id` via `update_rollout_state()` at each major transition. These fields
power the real-time rollout dashboard in the web UI.

## Attribution Scheme

Every item, comment, and run carries a `created_by` string identifying its creator. The scheme
is implemented in `identity.py` and applied consistently across REST routes and MCP tools.

| `created_by` value | Actor |
|---|---|
| `claude-build-<8-char run ID>` | Dispatched build-mode agent |
| `claude-plan-<8-char run ID>` | Dispatched plan-mode agent |
| `claude-manage-<8-char run ID>` | Dispatched manage-mode agent |
| `claude-lead-<8-char user ID>` | Interactive Claude Code session (lead) |
| `<user@email.com>` | Authenticated web UI user |
| `human` | Fallback / legacy |
| `mcp-agent` | Legacy (pre-2026-05-13 cutover) |
| `wave-manager` | Wave service server-side status comments |

Attribution is set at creation time and is immutable. When reading old `"mcp-agent"` comments,
infer the actor from branch names, timestamps, and rollout context.

## Database Schema

See `src/agent_gtd/database.py` for the canonical `_SCHEMA_STATEMENTS` list. Key tables:

| Table | Purpose |
|---|---|
| `users` | User accounts (email + bcrypt hash) |
| `api_keys` | API key credentials (stored as hash) |
| `projects` | GTD projects with dispatch overrides |
| `project_members` | Many-to-many project sharing |
| `items` | GTD items (tasks, inbox captures, notes targets) |
| `item_dependencies` | Blocker relationships (same-project only) |
| `notes` | Markdown project support material |
| `comments` | Thread comments on items or projects |
| `events` | Persisted SSE event log for replay |
| `claude_runs` | Dispatch run lifecycle tracking |
| `autonomous_rollouts` | Rollout (wave) lifecycle |
| `rollout_plans` | Versioned DAG plans for rollouts |
| `rollout_items` | Per-item status within a rollout |
| `rollout_events` | Append-only rollout audit log |
| `dispatch_hosts` | Registered remote dispatch hosts |
| `app_settings` | Global key-value settings |
| `user_settings` | Per-user key-value settings |
| `attachments` | File attachments on items |
| `invites` | One-time registration tokens |
| `password_resets` | One-time password reset tokens |

## Security Considerations

- **JWT authentication:** HS256, 72-hour expiry. Secret configured via `JWT_SECRET` env var. All REST routes require `Authorization: Bearer <token>` except register/login.
- **API keys:** Generated as `agtd_<random>`, stored as SHA-256 hash. Plaintext shown only once at creation. Used for MCP server and dispatch service authentication.
- **Invite-only registration:** `POST /api/auth/register` requires a valid `invite_token`. Tokens are one-time-use and issued by admins.
- **Ownership enforcement:** Every service function checks `user_id` ownership before read or write. Returns `NotFoundError` (not 403) to prevent entity enumeration.
- **Project sharing:** Access to shared projects is controlled via `project_members` table. Only the project owner can modify dispatch override fields.
- **Blocker invariant:** Blocker edges are restricted to same-project items. A one-time migration (`_sweep_cross_project_blockers`) cleans any pre-invariant data. This prevents information leakage through dependency traversal across project boundaries.
- **Optimistic locking:** Item updates require the current `version` value. Version mismatch returns 409, preventing silent data loss from concurrent edits.
- **Local mode:** When `AGENT_GTD_DATABASE_URL` is absent, auth is disabled entirely and a fixed `LOCAL_USER_ID` is used. This mode is for single-user developer deployments only.

## Performance Considerations

- **Async throughout:** All database calls use `asyncpg` (or `aiosqlite` in local mode) with `await`. No blocking I/O in the hot path.
- **Connection pooling:** A single `asyncpg` pool is shared across all requests. Pool size is left at the asyncpg default (10 connections).
- **Event bus queue size:** Each SSE subscriber gets a queue of 256 events. On overflow, the oldest event is dropped non-destructively (client can replay on reconnect). This prevents a slow client from blocking the event bus.
- **SSE heartbeat:** Sent every 30 seconds to prevent nginx and load balancers from closing idle SSE connections.
- **Dispatch polling:** The worker polls remote hosts every 15 seconds. This is a deliberate trade-off: faster polling increases remote API load; 15 seconds is a reasonable balance for long-running agent tasks.
- **No Redis:** The event bus is in-process. For a multi-process or multi-host deployment, this would need to be replaced with a Redis pub/sub layer. Current architecture targets a single-server deployment.
- **Static asset serving:** nginx serves `frontend/dist/` directly. Vite appends content hashes to asset filenames, enabling `expires 1y` cache headers for immutable assets.

## Pointers

> See KB entries `kb-00306` and `kb-00307` for deployment architecture details and bounce guidelines.
> The dispatch protocol is defined in the `agent-gtd-dispatch-protocol` package (`ubuntu-vm01:/~/repos/agent-gtd-dispatch`).
