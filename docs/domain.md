# Domain Concepts

## Background

AI coding agents powered by frontier LLMs are exceptional at design, planning, and
implementation. But they still can't manage long-running projects (weeks, months) without
external tooling. Work discovered during implementation — bugs, TODOs, adjacent improvements —
gets lost when context windows compact. There is no durable "system of record" for what needs
to happen next.

Meanwhile, human operators lose track of fast-moving agent work within days. Multiple agents
run on multiple projects in parallel, each making decisions and producing artifacts. Without a
shared system, the human has no stake in the ground to return to — no single view of "what's
going on across all my projects."

**The solution:** GTD (Getting Things Done) for the AI age. David Allen's methodology provides
a battle-tested framework for managing commitments: capture everything, clarify what it means,
organize by context, review regularly, engage with confidence. Agent GTD adapts it for a world
where AI agents are the primary workers and humans are the primary decision-makers.

**Key insight: projects ARE contexts.** In classic GTD, contexts describe *where/how* you work
(`@phone`, `@computer`, `@errands`). When everyone — human and agent alike — is staring at a
screen, the relevant context is *which project* you're working in.

## Core Terminology

- **Item:** The atomic unit of work. Captures a single task, idea, or waiting-for entry. Has
  a `status` that determines which GTD list it belongs to. Items are universal — a next action,
  a waiting-for, and a someday/maybe are all items with different statuses.

- **Project:** The primary organizational unit. Every item and note belongs to a project (except
  inbox items, which are unassigned until triaged). Projects replace GTD contexts.

- **Note:** Markdown-formatted project support material. Architecture decisions, design docs,
  research findings, agent work logs. Always scoped to a project.

- **Comment:** A thread entry on an item or project. Used for agent progress updates, human
  review feedback, and automated status messages. Carries a `created_by` attribution field.

- **Inbox:** The "in-tray" — a holding area for unprocessed captures. Items arrive here from
  quick capture (human or agent) and stay until a human triages them (assign to project, park
  as someday/maybe, or trash).

- **Rollout (Wave):** A coordinated multi-item dispatch in dependency order. A rollout
  contains a DAG (directed acyclic graph) plan of items. Items are dispatched to AI agents
  in waves as their predecessors complete.

- **Run:** A single dispatch of one item to one remote Claude Code host. A run has a lifecycle
  (pending → running → success/failed/timeout/cancelled). Many runs may belong to one rollout.

- **MCP:** Model Context Protocol — the tool interface used by AI agents. Agent GTD exposes
  its full feature set as MCP tools, served over FastMCP's HTTP transport at `/mcp`.

- **Attribution (`created_by`):** A string identifying who created an entity. Dispatched
  agents carry a structured identifier (e.g., `claude-build-abc12345`). Humans carry their
  email or `"human"`.

- **Legality contract:** A set of preconditions an item must satisfy before it can be included
  in a rollout: `status=ready`, non-empty `acceptance_criteria`, non-empty `files_to_modify`,
  `build_engine` set, and no unresolved external blockers.

- **Optimistic locking:** A concurrency control mechanism. Every item has a `version` integer.
  Updates must supply the current version; a mismatch (another agent edited the item)
  returns 409 so the caller can re-fetch and retry.

- **Dispatch host:** A registered remote server running the Claude Code dispatch service.
  Multiple hosts can be registered per user. The dispatch router picks the best available host
  for a given engine type, with 503-retry for at-capacity hosts.

## Business Rules

- Items in `status=inbox` have no `project_id`. They are unprocessed and unowned by any project until a human triages them.
- `update_item` requires the current `version` for optimistic locking. A stale version returns 409; the caller must re-fetch and retry.
- Blocker relationships (`item_dependencies`) are restricted to items within the same project. Cross-project blockers are rejected.
- A rollout item is locked (`locked_by_rollout_id`) while it is being executed. No other rollout or manual dispatch can modify a locked item.
- Only the project owner can modify dispatch override fields (`dispatch_max_turns`, `dispatch_timeout_minutes`, `plan_dispatch_agent`, `build_dispatch_agent`). Members can read but not change these.
- Registration requires an invite token issued by an admin. Self-registration is not allowed.
- `complete_item` is a convenience shortcut that sets `status=done` and `completed_at=now`. It is not the same as `complete_item_in_rollout`, which additionally unblocks downstream rollout items.
- Inbox items (`status=inbox`) are automatically created without a project. The `inbox_capture` MCP tool always creates inbox items; use `add_item` with an explicit `project_id` for project-scoped items.
- Sharing a project (`add_member`) is idempotent: adding the same user twice is not an error.
- `plan_rollout` validates the legality contract for all items before calling the planner model. A `LegalityContractError` is returned with per-item failure details if any item fails.

## User Roles

- **Admin:** Can issue and revoke invite tokens, manage all users. Set via `users.is_admin = 1`. No additional privileges on items or projects — admins still own only their own data.

- **Project Owner:** Created the project. Can read/write all project items, notes, and comments. Can modify dispatch override settings. Can share the project with other users.

- **Project Member:** Added to a project via sharing. Can read and write items, notes, and comments in the shared project. Cannot modify dispatch overrides. Receives SSE events for the shared project.

- **Dispatched Agent:** Authenticates via `AGENT_GTD_API_KEY`. Can call any MCP tool the owner can call. Attribution is set to `claude-{mode}-{run_id_prefix}`. In practice, agents operate within a single project per session.

- **Interactive Lead:** A Claude Code session running interactively (not dispatched). Authenticates via API key. Attribution is set to `claude-lead-{user_id_prefix}`.

## Process Flows

### GTD Capture and Triage

1. Agent calls `inbox_capture("Fix the login bug")` → item created in inbox.
2. Human opens the Inbox page in the web UI — sees unclarified items one at a time.
3. Human triages: assigns to a project and promotes to `next_action`, parks as `someday_maybe`, or cancels.
4. Item is now visible in the project's item list and the global Next Actions view.

### Dispatching a Single Item

1. Human (or manager agent) selects an item in `status=ready` with acceptance criteria and `build_engine` set.
2. Calls POST `/api/items/{id}/dispatch` (or MCP `dispatch_item(item_id=...)`).
3. A `claude_runs` row is created (`status=pending`). The dispatch worker enqueues the run ID.
4. Worker resolves engine, agent name, timeout, and max_turns from item → project → global settings.
5. Worker selects a dispatch host (auto-route or pinned), posts to the remote service.
6. Worker polls the remote service every 15 seconds until the run reaches a terminal state.
7. On completion: SSE event (`run_completed` or `run_failed`) is published. The web UI updates in real time.

### Rollout (Wave) Execution

1. Human selects a set of items (all `status=ready`, same project, all satisfying the legality contract).
2. Calls `plan_rollout(item_ids=[...])` (MCP) or POST `/api/rollouts`.
3. The planner model constructs a DAG — determines which items can run in parallel and which must wait.
4. `dispatch_rollout(rollout_id)` launches a manage-mode agent for the rollout.
5. The manage agent calls `advance_rollout()` to get the next ready items (no unmet predecessors).
6. For each ready item: `dispatch_item(item_id, rollout_id=...)` → build agent dispatched.
7. Build agent implements the item, pushes a feature branch, marks its GTD item as `review`.
8. Human (or manager, if in autonomous mode) reviews and merges. Calls `complete_item_in_rollout(outcome=completed)`.
9. Downstream items become `ready`. Manager loops back to step 5.
10. Rollout completes when all items reach a terminal rollout status.

### Weekly Review

1. Human opens the Review page.
2. **Get Clear:** Process all inbox items.
3. **Get Current:** Review each project's status — check for stale waiting-for items, projects with no next actions, overdue items.
4. **Get Creative:** Review someday/maybe items; promote promising ones to `next_action`.

## Domain Models

### Project

The primary organizational unit. Every item and note belongs to a project (except inbox items).

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | Owner |
| `name` | TEXT | Human-readable project name |
| `description` | TEXT | Purpose, scope, definition of done |
| `status` | TEXT | `active`, `completed`, `on_hold`, `cancelled` |
| `area` | TEXT | GTD area of responsibility grouping |
| `git_origin` | TEXT | Git remote URL for the associated repo |
| `kb_project_ref` | TEXT | Personal-KB `project_ref` tag for cross-linking |
| `dispatch_max_turns` | INTEGER | Per-project override: max agent turns (10–500) |
| `dispatch_timeout_minutes` | INTEGER | Per-project override: run timeout (5–480 min) |
| `plan_dispatch_agent` | TEXT | Per-project override: agent name for plan mode |
| `build_dispatch_agent` | TEXT | Per-project override: agent name for build mode |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |

### Item

The atomic unit of work. A single table with a `status` field encodes which GTD list an item
belongs to.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK (nullable) | NULL for inbox items |
| `user_id` | TEXT FK | Owner |
| `title` | TEXT | Short description |
| `description` | TEXT | Markdown detail; for dispatched items this is the instruction |
| `status` | TEXT | See status values below |
| `priority` | TEXT | `low`, `normal`, `high`, `urgent` |
| `due_date` | TEXT | ISO date, nullable |
| `completed_at` | TEXT | ISO datetime when marked done |
| `created_by` | TEXT | Attribution string |
| `assigned_to` | TEXT | Agent name or empty for human tasks |
| `waiting_on` | TEXT | Who/what this is blocked on (when `waiting_for`) |
| `sort_order` | REAL | Float for manual ordering |
| `labels` | TEXT | JSON array of strings |
| `version` | INTEGER | Optimistic locking counter |
| `locked_by_rollout_id` | TEXT | Rollout lock; prevents concurrent dispatch |
| `build_engine` | TEXT | Engine: `claude-code`, `claude-code-sonnet`, `claude-code-haiku`, `kiro`, … |
| `acceptance_criteria` | TEXT | JSON array of strings; required for rollout |
| `files_to_modify` | TEXT | JSON array of `{"path": str, "change": str}` objects |
| `scope_out` | TEXT | JSON array of strings; things explicitly out of scope |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |

**Item statuses (the GTD lists):**

| Status | GTD List | Meaning |
|---|---|---|
| `inbox` | Inbox | Raw capture, unclarified, no project |
| `new` | (staging) | Created with project but not yet clarified |
| `ready` | (dispatch queue) | Satisfies legality contract; ready for rollout |
| `next_action` | Next Actions | Clarified, actionable, ready to execute |
| `waiting_for` | Waiting For | Blocked on someone/something |
| `scheduled` | Calendar | Deferred to a specific `scheduled_date` |
| `someday_maybe` | Someday/Maybe | Parked idea, not committed |
| `active` | (in progress) | Currently being worked on |
| `review` | (review) | Submitted for human review (agent pushed a branch) |
| `done` | (complete) | Completed; `completed_at` is set |
| `cancelled` | (dropped) | Abandoned |

**Key status transitions:**
```
inbox → next_action    (clarified, assigned to project)
inbox → someday_maybe  (parked for later)
inbox → cancelled      (discarded)
next_action → active   (work started)
next_action → ready    (acceptance criteria written, ready for rollout)
active → review        (agent submitted, waiting for human review)
active → waiting_for   (hit a blocker)
review → done          (merged)
waiting_for → next_action (unblocked)
any → cancelled        (dropped at any point)
```

### Note

Markdown project support material. Architecture decisions, design docs, research, agent logs.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK | Always scoped to a project |
| `user_id` | TEXT FK | Owner |
| `title` | TEXT | Note title |
| `content_markdown` | TEXT | Full markdown content |
| `labels` | TEXT | JSON array of strings |
| `created_at` / `updated_at` | TEXT | ISO datetime |

### Comment

Thread entry on an item or project. Exactly one of `project_id` or `item_id` must be set (enforced by a DB CHECK constraint).

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK (nullable) | Set for project-level comments |
| `item_id` | TEXT FK (nullable) | Set for item-level comments |
| `user_id` | TEXT FK | Owner |
| `content_markdown` | TEXT | Comment body |
| `created_by` | TEXT | Attribution string |
| `created_at` / `updated_at` | TEXT | ISO datetime |

### Run (`claude_runs`)

Tracks a single dispatch of an item to a remote Claude Code host.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `item_id` | TEXT FK | The item being dispatched |
| `project_id` | TEXT FK | Item's project |
| `user_id` | TEXT FK | Who triggered the dispatch |
| `status` | TEXT | `pending`, `cloning`, `running`, `success`, `failed`, `timeout`, `cancelled` |
| `mode` | TEXT | `build`, `plan`, `manage` |
| `feature_branch` | TEXT | Branch name the agent worked on |
| `max_turns` | INTEGER | Agent turn limit for this run |
| `remote_run_id` | TEXT | ID assigned by the remote dispatch service |
| `dispatch_host_url` | TEXT | Which host executed this run |
| `dispatch_host_id` | TEXT | Pinned target host (NULL = auto-routed) |
| `rollout_id` | TEXT FK | If part of a rollout wave |
| `started_at` / `finished_at` | TEXT | Lifecycle timestamps |
| `error_msg` | TEXT | Failure reason (if applicable) |

### Rollout (`autonomous_rollouts`)

Coordinates a wave of related items dispatched in dependency order.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK | All items must belong to this project |
| `lead_user_id` | TEXT FK | Who initiated the rollout |
| `status` | TEXT | `pending`, `planning`, `running`, `completed`, `halted`, `failed`, `cancelled` |
| `halt_reason` | TEXT | Why the rollout was halted |
| `manager_phase` | TEXT | Current phase for UI display: `warm_up`, `dispatching`, `polling`, `reviewing`, `merging`, `reconciling_ac`, `halted` |
| `manager_current_item_id` | TEXT | Item the manager is currently focused on |
| `started_at` / `ended_at` | TEXT | Lifecycle timestamps |

### Event

Persisted SSE event log. Enables resumable streams.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | Who triggered the event |
| `event_type` | TEXT | `item.created`, `item.updated`, `run.completed`, etc. |
| `entity_type` | TEXT | `item`, `project`, `note`, `run` |
| `entity_id` | TEXT | UUID of the affected entity |
| `project_id` | TEXT | For per-project SSE channel filtering |
| `payload` | TEXT | JSON snapshot of the changed entity |
| `created_at` | TEXT | ISO datetime |

## GTD Concepts Mapping

| GTD Concept | Agent GTD Implementation |
|---|---|
| **Inbox / Capture** | `inbox_capture()` (MCP) or quick-capture bar (UI). Items land in inbox with `status=inbox`. |
| **Clarify / Process** | Human triages inbox items one at a time in the UI: assign project, set status, or discard. |
| **Projects** | The `projects` table. Each project has a clear scope and assigned agents. |
| **Next Actions** | Items with `status=next_action`. The agent's task queue; the human's action list. |
| **Waiting For** | Items with `status=waiting_for`. The `waiting_on` field records the blocker. |
| **Someday / Maybe** | Items with `status=someday_maybe`. Reviewed during weekly review. |
| **Support Material** | Notes (`notes` table). Architecture decisions, design docs, work logs. |
| **Weekly Review** | A dedicated UI dashboard: Get Clear, Get Current, Get Creative phases. |

**What we exclude from GTD:**

| GTD Concept | Reason |
|---|---|
| **General Reference** | The personal-kb MCP server handles knowledge management. GTD handles commitments. |
| **Physical Contexts** | `@errands`, `@phone` — irrelevant in an all-digital world. Projects replace contexts. |
| **Full Calendar** | Out of scope. `due_date` on items is supported; we are not a calendar application. |
| **Horizons of focus above 20k ft** | Goals, vision, purpose — organizational strategy, not task management. |

## Boundary: Agent GTD vs Personal-KB

| | Agent GTD (this system) | Personal-KB (existing MCP server) |
|---|---|---|
| **Purpose** | Manage commitments and actions | Store and retrieve knowledge |
| **Content** | Tasks, projects, project notes, inbox items | Decisions, patterns, reference docs, lessons |
| **Lifecycle** | Dynamic — items flow through statuses | Static — knowledge accumulates |
| **Scope** | Tied to active projects | Cross-project, persistent |
| **Agents use it to...** | Track what to do next | Remember what they've learned |

Both systems complement each other. An agent working on a project uses Agent GTD to manage
its task queue and Personal-KB to recall prior decisions and patterns. Project notes may be
"graduated" to KB when a project completes and the knowledge has lasting value.

## Pointers

> See `docs/architecture.md` for the SSE event bus design and rollout execution model.
> See `docs/api-docs.md` for MCP tool signatures and REST endpoint reference.
