# API Documentation

## Overview

Agent GTD exposes two API surfaces:

1. **REST API** (`/api/*`) — used by the React web frontend. Authenticated via JWT bearer tokens. Returns JSON.
2. **MCP Server** (`/mcp`) — used by AI agents. Served via FastMCP's HTTP transport (Streamable HTTP). Authenticated via API key or JWT.

Both surfaces share the same service layer and database. A mutation through the REST API is
immediately visible via MCP tools, and vice versa.

## Authentication

### REST API

All endpoints except `/api/auth/register` and `/api/auth/login` require:
```
Authorization: Bearer <jwt_token>
```

The JWT token is obtained from `/api/auth/login` or `/api/auth/register`. Tokens expire after
72 hours. The SSE endpoint (`/api/events`) also accepts `?token=<jwt>` as a query parameter,
since browsers cannot set custom headers for `EventSource`.

API keys (created via `/api/auth/api-keys`) can also be used as bearer tokens:
```
Authorization: Bearer agtd_<key>
```

### MCP Server

MCP tools authenticate using one of:
- `AGENT_GTD_API_KEY` env var → auto-authenticates at tool call time (no `login()` needed)
- `AGENT_GTD_URL` + `AGENT_GTD_API_KEY` → HTTP remote mode
- `login(api_key, agent_name)` MCP tool → manual authentication

In local mode (no `AGENT_GTD_DATABASE_URL`), authentication is disabled and all tools operate
as the built-in local user.

---

## REST API Endpoints

### Health & Config

#### `GET /api/health`
Returns system health.
- **Response:** `{"status": "ok"}`

#### `GET /api/health/events`
Returns per-event-type attempt/failure counts for monitoring.
- **Response:** `{"event_type": {"attempts": int, "failures": int}, ...}`

#### `GET /api/config`
Returns runtime configuration flags.
- **Response:** `{"local_mode": bool, "version": str}`

---

### Authentication (`/api/auth`)

#### `POST /api/auth/register`
Register a new user account. Requires a valid invite token.
- **Request body:** `{"email": str, "password": str, "invite_token": str}`
- **Response:** `{"token": str, "user": {"id": str, "email": str, "is_admin": bool, "created_at": str}}`
- **Errors:** 400 if invite token is invalid or already used; 409 if email already registered.

#### `POST /api/auth/login`
Authenticate with email and password.
- **Request body:** `{"email": str, "password": str}`
- **Response:** `{"token": str, "user": {"id": str, "email": str, "is_admin": bool, "created_at": str}}`
- **Errors:** 401 if credentials are invalid.

#### `POST /api/auth/logout`
Invalidate the current session token. (Stateless — client should discard the token.)
- **Response:** 204 No Content

#### `GET /api/auth/me`
Return the currently authenticated user.
- **Response:** `{"id": str, "email": str, "is_admin": bool, "created_at": str}`

#### `POST /api/auth/password`
Change the authenticated user's password.
- **Request body:** `{"current_password": str, "new_password": str}`
- **Response:** 204 No Content
- **Errors:** 401 if `current_password` is wrong.

#### `POST /api/auth/password-reset`
Consume a one-time password reset token (issued by admin out-of-band).
- **Request body:** `{"token": str, "new_password": str}`
- **Response:** 204 No Content
- **Errors:** 400 if token is invalid, expired, or already used.

#### `POST /api/auth/api-keys`
Create a new API key. The plaintext key is shown only in this response.
- **Request body:** `{"name": str}`
- **Response:** `{"api_key": "agtd_<key>", "name": str}`

#### `GET /api/auth/api-keys`
List the authenticated user's API keys (without secret material).
- **Response:** `[{"id": str, "name": str, "hash_prefix": str, "created_at": str}]`

---

### Projects (`/api/projects`)

#### `GET /api/projects`
List all projects accessible to the authenticated user (owned + shared).
- **Query params:** `status` (filter by status), `area` (filter by area)
- **Response:** `[ProjectResponse]` — includes `is_owner`, `owner_email`, `member_count`, `total_items`, `description_preview`

#### `POST /api/projects`
Create a new project.
- **Request body:** `{"name": str, "description"?: str, "status"?: str, "area"?: str, "git_origin"?: str, "kb_project_ref"?: str}`
- **Response:** `ProjectResponse` — 201 Created

#### `GET /api/projects/{project_id}`
Retrieve a single project.
- **Response:** `ProjectResponse`
- **Errors:** 404 if not found or not accessible.

#### `PATCH /api/projects/{project_id}`
Partially update a project. All fields are optional.
- **Request body:** `{"name"?: str, "description"?: str, "status"?: str, "area"?: str, "dispatch_max_turns"?: int|null, "dispatch_timeout_minutes"?: int|null, ...}`
- Passing `null` for dispatch override fields clears them (reverts to global defaults). Only the project owner can set dispatch overrides.
- Validates turn bounds (10–500) and timeout bounds (5–480 min).
- **Response:** `ProjectResponse`
- **Errors:** 404, 403 if non-owner attempts to modify dispatch overrides.

#### `DELETE /api/projects/{project_id}`
Delete a project and all its items and notes (cascades).
- **Response:** 204 No Content

#### `POST /api/projects/{project_id}/members`
Share a project with another user by email. Idempotent.
- **Request body:** `{"email": str}`
- **Response:** `{"user_id": str, "email": str, "added_at": str}`
- **Errors:** 404 if email not registered.

#### `DELETE /api/projects/{project_id}/members/{email}`
Remove a user from project sharing. No-op if user is not a member.
- **Response:** 204 No Content

#### `GET /api/projects/{project_id}/members`
List project members (excludes the owner).
- **Response:** `[{"user_id": str, "email": str, "added_at": str}]`

---

### Items (`/api/items`)

#### `GET /api/items`
List items accessible to the authenticated user.
- **Query params:** `status`, `project_id`, `priority`, `assigned_to`
- **Response:** `[ItemResponse]`

#### `POST /api/items`
Create a new item.
- **Request body:**
```json
{
  "title": "string (required)",
  "description": "string",
  "status": "inbox | next_action | ...",
  "priority": "low | normal | high | urgent",
  "project_id": "uuid or null",
  "due_date": "ISO date or null",
  "labels": ["string"],
  "build_engine": "claude-code | claude-code-sonnet | ...",
  "acceptance_criteria": ["string"],
  "files_to_modify": [{"path": "string", "change": "string"}],
  "scope_out": ["string"],
  "created_by": "string (optional override)"
}
```
- **Response:** `ItemResponse` — 201 Created
- **Errors:** 404 if `project_id` does not exist or is not accessible.

#### `GET /api/items/search`
Typeahead search by title. Prefix matches rank above substring matches. Excludes done items.
- **Query params:** `q` (required), `limit` (default 10)
- **Response:** `[{"id": str, "title": str, "status": str, "project_id": str, "project_name": str}]`

#### `GET /api/items/{item_id}`
Retrieve a single item including its blockers list.
- **Response:** `ItemResponse` (includes `blockers: [BlockerSummary]`)

#### `PATCH /api/items/{item_id}`
Partially update an item. Requires `version` for optimistic locking.
- **Request body:** (all fields optional)
```json
{
  "version": 3,
  "title": "string",
  "description": "string",
  "status": "next_action",
  "priority": "high",
  "due_date": "2026-06-01 or '' to clear or null to leave unchanged",
  "labels": ["string"],
  "project_id": "uuid or '' to detach or null to leave unchanged",
  "build_engine": "claude-code or '' to clear or null to leave unchanged",
  "acceptance_criteria": ["string"],
  "files_to_modify": [{"path": "string", "change": "string"}],
  "scope_out": ["string"],
  "assigned_to": "string",
  "waiting_on": "string"
}
```
- **Response:** `ItemResponse`
- **Errors:** 409 if `version` is stale; 422 with blockers list if item has unresolved blockers and status is being set to done/ready; 423 if item is locked by a rollout.

#### `DELETE /api/items/{item_id}`
Delete an item.
- **Response:** 204 No Content

#### `POST /api/items/{item_id}/complete`
Shortcut to mark an item done. Sets `status=done` and `completed_at=now`.
- **Response:** `ItemResponse`

#### `POST /api/items/{item_id}/claim`
Atomically assign the item to the calling agent. Fails if already claimed by a different agent.
- **Request body:** `{"agent_name": str}`
- **Response:** `ItemResponse`
- **Errors:** 409 if already claimed.

#### `POST /api/items/{item_id}/release`
Clear `assigned_to`. Allows another agent to claim the item.
- **Response:** `ItemResponse`

#### `GET /api/inbox`
Shorthand for `GET /api/items?status=inbox`.
- **Response:** `[ItemResponse]`

#### `POST /api/inbox`
Quick capture — creates an inbox item with title only.
- **Request body:** `{"title": str, "created_by"?: str}`
- **Response:** `ItemResponse` — 201 Created

#### `GET /api/projects/{project_id}/items`
List items scoped to a specific project.
- **Response:** `[ItemResponse]`

#### `POST /api/projects/{project_id}/items`
Create an item in a specific project.
- **Request body:** Same as `POST /api/items` (project_id comes from path)
- **Response:** `ItemResponse` — 201 Created

#### `POST /api/items/{item_id}/blockers`
Add a blocker relationship. Idempotent. Prevents cycles. Both items must be in the same project.
- **Request body:** `{"blocker_item_id": str}`
- **Response:** `{"id": str, "title": str, "status": str, "project_id": str, "project_name": str}`
- **Errors:** 400 if blocker would create a cycle or crosses project boundary.

#### `DELETE /api/items/{item_id}/blockers/{blocker_item_id}`
Remove a blocker relationship. No-op if not present.
- **Response:** 204 No Content

#### `GET /api/items/{item_id}/blockers`
List all blockers for an item.
- **Response:** `[{"id": str, "title": str, "status": str, "project_id": str, "project_name": str}]`

---

### Notes (`/api/notes`, `/api/projects/{project_id}/notes`)

#### `GET /api/notes`
List all notes. Optional project filter.
- **Query params:** `project_id`
- **Response:** `[NoteResponse]`

#### `GET /api/projects/{project_id}/notes`
List notes scoped to a project.
- **Response:** `[NoteResponse]`

#### `POST /api/projects/{project_id}/notes`
Create a note in a project.
- **Request body:** `{"title"?: str, "content_markdown"?: str, "labels"?: [str]}`
- **Response:** `NoteResponse` — 201 Created

#### `GET /api/notes/{note_id}`
Retrieve a single note.
- **Response:** `NoteResponse`

#### `PATCH /api/notes/{note_id}`
Partially update a note. All fields optional.
- **Request body:** `{"title"?: str, "content_markdown"?: str, "labels"?: [str]}`
- **Response:** `NoteResponse`

#### `DELETE /api/notes/{note_id}`
Delete a note.
- **Response:** 204 No Content

---

### Comments (`/api/comments`)

#### `GET /api/comments`
List comments (optional filter by project or item).
- **Query params:** `project_id`, `item_id`
- **Response:** `[CommentResponse]`

#### `GET /api/projects/{project_id}/comments`
List project-level comments.
- **Response:** `[CommentResponse]`

#### `POST /api/projects/{project_id}/comments`
Create a project-level comment.
- **Request body:** `{"content_markdown": str}`
- **Response:** `CommentResponse` — 201 Created

#### `GET /api/items/{item_id}/comments`
List item-level comments.
- **Response:** `[CommentResponse]`

#### `POST /api/items/{item_id}/comments`
Create an item-level comment.
- **Request body:** `{"content_markdown": str}`
- **Response:** `CommentResponse` — 201 Created

#### `GET /api/comments/{comment_id}`
Retrieve a single comment.
- **Response:** `CommentResponse`

#### `PATCH /api/comments/{comment_id}`
Update a comment.
- **Request body:** `{"content_markdown"?: str}`
- **Response:** `CommentResponse`

#### `DELETE /api/comments/{comment_id}`
Delete a comment.
- **Response:** 204 No Content

---

### Dispatch (`/api/dispatch`, `/api/runs`)

#### `POST /api/items/{item_id}/dispatch`
Create and enqueue a dispatch run for an item.
- **Request body:**
```json
{
  "max_turns": 100,
  "mode": "build | plan | manage",
  "rollout_id": "uuid or null",
  "dispatch_host_id": "uuid or null (null = auto-route)"
}
```
- **Response:** `RunResponse` — 201 Created
- **Errors:** 404 if item not found; 409 if item is locked.

#### `GET /api/runs`
List dispatch runs.
- **Query params:** `item_id`, `status`
- **Response:** `[RunResponse]`

#### `GET /api/runs/{run_id}`
Get a single run's current status and details.
- **Response:** `RunResponse`

#### `GET /api/runs/failures`
List recent failed/timed-out runs (with item and project context).
- **Response:** `[{"id", "item_id", "item_title", "project_id", "project_name", "status", "error_msg", "started_at", "finished_at", ...}]`

#### `GET /api/runs/stale`
List runs that succeeded but whose item has not been advanced (e.g., still in `active`).
- **Response:** `[{"id", "item_id", "item_status", "project_id", ...}]`

#### `GET /api/dispatch/capabilities`
Proxy to the dispatch service: returns supported engines, agents, and total capacity.
- **Response:** `{"engines": [str], "versions": {...}, "agents": [{"name": str, "description": str}], "total_capacity": int}`

---

### Dispatch Settings

#### `GET /api/settings/dispatch`
Get the current user's dispatch configuration (engine, agent names, defaults, service URL).
- **Response:** Dispatch settings object.

#### `PATCH /api/settings/dispatch`
Update dispatch settings.
- **Request body:** Fields to update (all optional).
- **Response:** Updated settings object.

#### `GET /api/settings/dispatch/hosts`
List registered dispatch hosts.
- **Response:** `[{"id", "label", "url", "api_key_preview", "created_at"}]`

#### `POST /api/settings/dispatch/hosts`
Register a new dispatch host.
- **Request body:** `{"label": str, "url": str, "api_key": str}`
- **Response:** `DispatchHostResponse` — 201 Created

#### `DELETE /api/settings/dispatch/hosts/{host_id}`
Remove a dispatch host.
- **Response:** 204 No Content

---

### Events / SSE (`/api/events`)

#### `GET /api/events`
Open a Server-Sent Events stream for the authenticated user.
- **Auth:** `Authorization: Bearer <token>` header or `?token=<jwt>` query parameter.
- **Query params:** `since` (event ID — replays all events after this ID before going live)
- **Response:** `text/event-stream`

Event format:
```
event: item.updated
data: {"id": "...", "eventType": "item.updated", "entityType": "item", "entityId": "...",
       "projectId": "...", "payload": {...}, "createdAt": "..."}

: heartbeat
```

Heartbeats are sent every 30 seconds to keep the connection alive through proxies. The event
payload includes a full entity snapshot — clients do not need a follow-up fetch.

---

### Rollouts (`/api/rollouts`)

#### `POST /api/rollouts`
Plan a new rollout from a list of items. Validates the legality contract and constructs a DAG.
- **Request body:** `{"item_ids": ["uuid", ...]}`
- **Response:**
```json
{
  "rollout_id": "uuid",
  "status": "pending",
  "plan": {"nodes": ["uuid", ...], "edges": [{"from_item_id": "uuid", "to_item_id": "uuid"}]},
  "planner_model": "string",
  "item_count": 5,
  "per_item": {"uuid": {"status": "ok"} | {"error": "string"}}
}
```
- **Errors:** 422 with per-item failure details if legality contract is violated.

#### `GET /api/rollouts/{rollout_id}`
Get rollout state including progress counts.
- **Response:** `RolloutResponse` (includes `total_count`, `done_count`, `manager_phase`, etc.)

#### `POST /api/rollouts/{rollout_id}/start`
Transition a rollout from `pending` to `running` without launching a manage agent.
- **Response:** Updated rollout dict.

#### `POST /api/rollouts/{rollout_id}/dispatch`
Launch a manage-mode agent to drive the rollout. Sets status to `running`.
- **Response:** `RunResponse` for the manage run.

#### `GET /api/rollouts/{rollout_id}/advance`
Determine which items are ready to dispatch (no unmet predecessors).
- **Response:** `{"next_ready": ["uuid"], "in_progress": ["uuid"], "blocked": ["uuid"], "graph_complete": bool}`

#### `POST /api/rollouts/{rollout_id}/complete-item`
Mark an item as completed, halted, or skipped within the rollout. Unblocks downstream items.
- **Request body:** `{"item_id": str, "outcome": "completed | halted | skipped", "merge_actor"?: str, "decision_rule"?: str}`
- **Response:** `{"rollout_item": dict, "newly_ready": ["uuid"]}`

#### `POST /api/rollouts/{rollout_id}/halt`
Halt the rollout (pauses manager, marks in-flight items halted).
- **Request body:** `{"reason": str, "comment"?: str, "item_id"?: str}`
- **Response:** Updated rollout dict.

#### `POST /api/rollouts/{rollout_id}/cancel`
Cancel the rollout. Idempotent for already-cancelled rollouts.
- **Request body:** `{"reason": str}`
- **Response:** Updated rollout dict.

#### `POST /api/rollouts/{rollout_id}/replan`
Replan remaining pending/ready items. Generates a new DAG version.
- **Request body:** `{"from_item"?: str}`
- **Response:** `{"old_version": int, "new_version": int, "new_plan": dict}`

#### `POST /api/rollouts/{rollout_id}/state`
Update the manager's semantic phase for the real-time dashboard.
- **Request body:** `{"phase": str, "current_item_id"?: str, "current_step"?: str}`
- **Response:** `{"rollout_id", "ts", "phase", "current_item_id", "current_step"}`

#### `POST /api/rollouts/{rollout_id}/resume`
Resume a halted rollout with a human answer.
- **Request body:** `{"answer": str}`
- **Response:** Updated rollout dict.

#### `GET /api/rollouts/{rollout_id}/events`
List rollout audit events in sequence order.
- **Response:** `[RolloutEventResponse]`

#### `GET /api/projects/{project_id}/active-rollout`
Get the currently active rollout for a project (for the UI banner).
- **Response:** `RolloutResponse` or 404 if no active rollout.

#### `GET /api/projects/{project_id}/rollouts`
List rollouts for a project.
- **Query params:** `status`, `limit` (default 20)
- **Response:** `[RolloutResponse]`

---

## MCP Tools

All MCP tools are served at `/mcp` via FastMCP's HTTP transport. Tools are called by AI agents
using the MCP protocol. The session resolves the calling user from the API key context.

### Authentication

```python
# login() — only needed if AGENT_GTD_API_KEY is not set
login(api_key: str, agent_name: str) → {"status": "ok", "user_email": str, "agent_name": str}
```

### Projects

```python
list_projects(status: str | None = None) → list[dict]
# Returns all projects for the session user. Optional status filter.

add_project(
    name: str,
    description: str = "",
    area: str = "",
    status: str = "active",
    git_origin: str = "",
    kb_project_ref: str = "",
    dispatch_max_turns: int | None = None,
    dispatch_timeout_minutes: int | None = None,
    plan_dispatch_agent: str | None = None,
    build_dispatch_agent: str | None = None,
) → dict
# Creates a new project. Validates turn bounds (10–500) and timeout bounds (5–480 min).

update_project(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    area: str | None = None,
    git_origin: str | None = None,
    kb_project_ref: str | None = None,
    dispatch_max_turns: int | None = None,
    dispatch_timeout_minutes: int | None = None,
    plan_dispatch_agent: str | None = None,
    build_dispatch_agent: str | None = None,
    clear_dispatch_max_turns: bool = False,
    clear_dispatch_timeout_minutes: bool = False,
    clear_plan_dispatch_agent: bool = False,
    clear_build_dispatch_agent: bool = False,
) → dict
# Value/clear pattern: pass value to set, pass clear_* = True to revert to global default.
# Only project owner can change dispatch override fields.

share_project(project_id: str, email: str) → {"user_id": str, "email": str, "added_at": str}
# Adds a user as a project member. Idempotent.

unshare_project(project_id: str, email: str) → {"ok": True}
# Removes a user from project members. No-op if not a member.

list_project_members(project_id: str) → list[{"user_id": str, "email": str, "added_at": str}]
# Lists members excluding the owner.
```

### Items

```python
inbox_capture(title: str) → dict
# Quick capture: creates status=inbox item with title. project_id=None.
# created_by is set to the calling agent's attribution string.

add_item(
    title: str,
    description: str = "",
    priority: str = "normal",
    status: str = "new",
    labels: list[str] | None = None,
    project_id: str | None = None,
    due_date: str | None = None,
) → dict
# Full item creation. Inbox items always have project_id=None.

update_item(
    item_id: str,
    version: int,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    due_date: str | None = None,      # None=unchanged, ""=clear, date=set
    project_id: str | None = None,    # None=unchanged, ""=detach, uuid=move
    build_engine: str | None = None,  # None=unchanged, ""=clear, engine=set
    assigned_to: str | None = None,
    waiting_on: str | None = None,
    labels: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,   # None=unchanged, []=clear, [...]= set
    files_to_modify: list[dict] | None = None,       # None=unchanged, []=clear, [...]= set
    scope_out: list[str] | None = None,              # None=unchanged, []=clear, [...]= set
) → dict
# Optimistic locking: version must match DB. Raises VersionConflictError on mismatch.
# Raises BlockersUnresolvedError if item has unresolved blockers and status→done/ready.
# Raises RolloutItemLockedError if item is locked by a rollout.

complete_item(item_id: str) → dict
# Shortcut: sets status=done, completed_at=now.

delete_item(item_id: str) → dict
# Permanently deletes the item. Destructive.

list_items(
    status: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
) → {"items": list[dict], "inbox_pending_count": int}
# When project_id is omitted, returns cross-project listing with inbox_pending_count.

get_item(item_id: str) → dict
# Returns full item dict including blockers.
```

### Blockers

```python
add_blocker(item_id: str, blocker_item_id: str) → BlockerSummary
# Adds a blocker dependency. Idempotent. Prevents cycles. Same-project items only.

remove_blocker(item_id: str, blocker_item_id: str) → {"ok": True}
# Removes a blocker relationship. No-op if not present.

list_blockers(item_id: str) → list[BlockerSummary]
# Lists all blockers for an item.
```

### Notes

```python
add_note(project_id: str, title: str = "", content_markdown: str = "", labels: list[str] | None = None) → dict

update_note(note_id: str, title: str | None = None, content_markdown: str | None = None, labels: list[str] | None = None) → dict

delete_note(note_id: str) → dict
# Destructive.

list_notes(project_id: str | None = None) → list[dict]
# Cross-project listing if project_id omitted.

get_note(note_id: str) → dict
```

### Comments

```python
add_comment(content_markdown: str, project_id: str | None = None, item_id: str | None = None) → dict
# Exactly one of project_id or item_id must be provided.

list_comments(project_id: str | None = None, item_id: str | None = None) → list[dict]
# No filters = all comments for the session user.

update_comment(comment_id: str, content_markdown: str | None = None) → dict
```

### Dispatch Runs

```python
dispatch_item(
    item_id: str,
    max_turns: int | None = None,
    mode: Literal["build", "plan", "manage"] = "build",
    rollout_id: str | None = None,
    dispatch_host_id: str | None = None,
) → dict
# Creates and enqueues a dispatch run. mode="manage" requires rollout_id.
# dispatch_host_id=None triggers auto-routing with 503 retry.

get_run_status(run_id: str) → dict
# Returns current run status and details.

list_runs(item_id: str | None = None, status: str | None = None) → list[dict]
```

### Rollout Manager

```python
plan_rollout(item_ids: list[str]) → {
    "rollout_id": str,
    "status": str,
    "plan": {"nodes": list[str], "edges": list[dict]},
    "planner_model": str,
    "item_count": int,
    "per_item": dict,
}
# Validates legality contract, calls planner model, stores DAG. All items must be same project.
# Raises LegalityContractError with per-item failures if contract is violated.

get_rollout(rollout_id: str) → dict
# Full rollout lifecycle state including manager phase.

list_rollouts(project_id: str | None = None, status: str | None = None, limit: int = 20) → list[dict]
# Newest first. Status filter: "running", "halted", "pending", "completed", etc.

get_rollout_plan(rollout_id: str) → {
    "rollout_id": str,
    "plan_version": int,
    "planner_model": str,
    "nodes": list[str],
    "edges": list[dict],
    "items": [{"item_id": str, "title": str, "rollout_status": str, "predecessors": list[str]}],
}

advance_rollout(rollout_id: str) → {
    "next_ready": list[str],
    "in_progress": list[str],
    "blocked": list[str],
    "graph_complete": bool,
}
# Pure read: determines which items have no unmet predecessors.

start_rollout(rollout_id: str) → dict
# Transitions pending → running without launching a manage agent (debug/human-driven mode).

complete_item_in_rollout(
    rollout_id: str,
    item_id: str,
    outcome: Literal["completed", "halted", "skipped"],
    merge_actor: Literal["human", "manager-allowlist", "manager-autonomous", "manager+human-fixup", ""] = "",
    decision_rule: Literal["", "agent-judgment"] = "",
) → {"rollout_item": dict, "newly_ready": list[str]}
# Marks item terminal, releases lock, unblocks downstream items.
# Closes rollout if all items are terminal.

halt_rollout(rollout_id: str, reason: str, comment: str | None = None, item_id: str | None = None) → dict
# Destructive. Transitions in-flight items to halted, releases locks, posts comment.

cancel_rollout(rollout_id: str, reason: str) → dict
# Destructive. Idempotent for already-cancelled rollouts.

replan_rollout(rollout_id: str, from_item: str | None = None) → {
    "old_version": int,
    "new_version": int,
    "new_plan": dict,
}
# Replans remaining pending/ready items. Increments plan version. Emits SSE event.

update_rollout_state(
    rollout_id: str,
    phase: Literal["warm_up", "dispatching", "polling", "reviewing", "merging", "reconciling_ac", "halted"],
    current_item_id: str | None = None,
    current_step: str | None = None,
) → {"rollout_id": str, "ts": str, "phase": str, "current_item_id": str, "current_step": str}
# Manager-facing: updates semantic phase for the real-time dashboard.

dispatch_rollout(rollout_id: str) → dict
# Launches a manage-mode agent for the rollout. pending → running.
```

## Rate Limiting

No rate limiting is currently implemented. The API is intended for authenticated users and
their dispatched agents — not public access.

## Example Code

### Authenticate and create an item (REST)

```python
import httpx

BASE = "https://gtd.example.com"

# Log in
resp = httpx.post(f"{BASE}/api/auth/login", json={"email": "you@example.com", "password": "..."})
token = resp.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

# Create an item
resp = httpx.post(
    f"{BASE}/api/items",
    json={"title": "Write unit tests for rollout service", "priority": "high"},
    headers=headers,
)
item = resp.json()
print(item["id"])
```

### Use MCP tools (agent code, auto-auth via env var)

```python
# Environment: AGENT_GTD_API_KEY=agtd_...
# Session resolves automatically — no login() call needed.

result = await ctx.call_tool("add_comment", {
    "item_id": "950503a5-...",
    "content_markdown": "Implementing the rollout service changes."
})
```

### Listen for SSE events (browser JavaScript)

```javascript
const token = localStorage.getItem('agent_gtd-token');
const es = new EventSource(`/api/events?token=${token}`);

es.addEventListener('item.updated', (e) => {
    const data = JSON.parse(e.data);
    console.log('Item updated:', data.entityId, data.payload);
});
```

## Pointers

> See `docs/domain.md` for entity definitions and status transition diagrams.
> See `docs/architecture.md` for the SSE event bus design and dispatch worker lifecycle.
