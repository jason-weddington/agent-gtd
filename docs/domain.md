# Agent GTD — Domain Model

## The Problem

AI coding agents powered by frontier LLMs are exceptional at design, planning, and
implementation. But they still can't manage long-running projects (weeks, months) without
external tooling. Work discovered during implementation — bugs, TODOs, adjacent improvements —
gets lost when context windows compact. There is no durable "system of record" for what needs
to happen next.

Meanwhile, human operators lose track of fast-moving agent work within days. Multiple agents
run on multiple projects in parallel, each making decisions and producing artifacts. Without a
shared system, the human has no stake in the ground to return to — no single view of "what's
going on across all my projects."

## The Solution

**GTD (Getting Things Done) for the AI age.** David Allen's methodology provides a
battle-tested framework for managing commitments: capture everything, clarify what it means,
organize by context, review regularly, engage with confidence. We adapt it for a world where
AI agents are the primary workers and humans are the primary decision-makers.

**Key insight: projects ARE contexts.** In classic GTD, contexts describe *where/how* you work
(`@phone`, `@computer`, `@errands`). When everyone — human and agent alike — is staring at a
screen, the relevant context is *which project* you're working in. An agent is "in context"
when it's registered to a project. A human is "in context" when they're viewing a project in
the UI.

**Two interfaces, one system:**
- **MCP tools** for AI agents — they call tools to capture, create, update, and query
- **Responsive web UI** for humans — React + MUI frontend for triage, review, and oversight
- **Real-time sync** — agent changes appear instantly in the UI; human changes push to agents via SSE

## GTD Concepts Mapped to Our Domain

### What We Include

| GTD Concept | Agent GTD Implementation |
|---|---|
| **Inbox / Capture** | Agents call `inbox_capture()` when they discover work. Humans use a quick-capture bar in the UI. Items are raw and unprocessed until triaged. |
| **Clarify / Process** | The human is the primary clarifier. The UI presents inbox items one at a time for triage: assign to project, set status, or discard. Agents can suggest triage metadata. |
| **Projects** | The primary organizational unit. Maps to a software initiative or codebase. Each project has assigned agents, items, and notes. Projects replace GTD contexts. |
| **Next Actions** | Atomic tasks — the work agents and humans actually do. Status `next_action` means "ready to execute." |
| **Waiting For** | A task status, not a separate list. Tracks what's blocked and on whom — critical for agent-human handoffs. "Waiting for human to review PR" or "waiting for agent to finish implementation." |
| **Someday / Maybe** | Parked ideas not yet committed to. Feature wishes, refactoring ideas, "nice to have" items. Reviewed during weekly review; promoted to projects when ready. |
| **Project Support Material** | Markdown notes tied to projects. Architecture decisions, design docs, agent work logs. Rich editing via TipTap in the UI. |
| **Weekly Review** | A dedicated dashboard. Get Clear (process inbox), Get Current (review each project's status, surface stale waiting-for items), Get Creative (review someday/maybe, capture new ideas). |

### What We Exclude

| GTD Concept | Reason |
|---|---|
| **General Reference** | The personal-kb MCP server handles knowledge management. Agent GTD handles *commitments and actions*; KB handles *information and reference*. If it's tied to an active project, it's a project note here. If it's general knowledge, it goes in KB. |
| **Physical Contexts** | `@errands`, `@phone` — irrelevant in an all-digital world. Projects replace contexts entirely. |
| **Full Calendar** | Out of scope. We support `due_date` on items and milestones on projects, but we are not building a calendar application. |
| **Horizons above 20,000 ft** | Goals, vision, purpose — these are organizational strategy, not task management. We implement ground level (tasks) through 20,000 ft (areas of responsibility). |

### Horizons of Focus

| Horizon | Maps To |
|---|---|
| **Ground — Current Actions** | Items with status `next_action` or `active`. The agent's task queue; the human's action list. |
| **10,000 ft — Projects** | Active projects with assigned agents. Each has a clear outcome definition. |
| **20,000 ft — Areas** | Optional project grouping (e.g., "Infrastructure", "Product Features", "Tech Debt"). The `area` field on projects. |

## Core Entities

### Project

The primary organizational unit. Every item and note belongs to a project (except inbox
items, which are unassigned until triaged).

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | Owner (human operator) |
| `name` | TEXT | Human-readable project name |
| `description` | TEXT | Purpose, scope, what "done" looks like |
| `status` | TEXT | `active`, `completed`, `on_hold`, `cancelled` |
| `area` | TEXT | GTD area of responsibility grouping |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |

### Item

The atomic unit of work. Replaces GTD's "next action", "waiting for", and "someday/maybe"
as a single entity with a `status` field. This keeps the data model simple — one table, one
query surface, status distinguishes the GTD list an item belongs to.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK (nullable) | NULL for unprocessed inbox items |
| `user_id` | TEXT FK | Owner |
| `title` | TEXT | Short description (human-readable AND agent-parseable) |
| `description` | TEXT | Detailed markdown. For agent tasks, this is the instruction. |
| `status` | TEXT | See status values below |
| `item_type` | TEXT | `task`, `reference`, `event` |
| `priority` | TEXT | `low`, `normal`, `high`, `urgent` |
| `context` | TEXT | Free-text for any additional context tagging |
| `energy` | TEXT | `low`, `normal`, `high` — effort level hint |
| `time_estimate_minutes` | INTEGER | Optional time estimate |
| `due_date` | TEXT | ISO date, nullable |
| `scheduled_date` | TEXT | ISO date — "tickler" for deferred items |
| `completed_at` | TEXT | ISO datetime when marked done |
| `created_by` | TEXT | `human` or agent identifier — provenance tracking |
| `assigned_to` | TEXT | Agent name or empty for human tasks |
| `waiting_on` | TEXT | Who/what this item is blocked on (when status = `waiting_for`) |
| `sort_order` | REAL | Float for manual ordering (insert between: avg of neighbors) |
| `labels` | TEXT | JSON array of string labels |
| `version` | INTEGER | Optimistic locking — incremented on every update |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |

**Item statuses (the GTD lists):**

| Status | GTD List | Meaning |
|---|---|---|
| `inbox` | Inbox | Unclarified capture. No project assigned yet. |
| `next_action` | Next Actions | Clarified, actionable, ready to execute. |
| `waiting_for` | Waiting For | Blocked on someone/something. `waiting_on` describes whom. |
| `scheduled` | Calendar | Deferred to a specific `scheduled_date`. |
| `someday_maybe` | Someday/Maybe | Parked idea, not committed. |
| `active` | (in progress) | Currently being worked on by an agent or human. |
| `done` | (complete) | Completed. `completed_at` is set. |
| `cancelled` | (dropped) | Abandoned, no longer relevant. |

**Status transitions:**
```
inbox -> next_action    (clarified, assigned to project)
inbox -> someday_maybe  (parked for later)
inbox -> cancelled      (trash)
next_action -> active   (work started)
next_action -> waiting_for (blocked)
active -> waiting_for   (hit a blocker)
active -> done          (completed)
waiting_for -> next_action (unblocked)
scheduled -> next_action   (date arrived)
someday_maybe -> next_action (promoted during review)
any -> cancelled        (dropped at any point)
```

### Note

Markdown-formatted project support material. Architecture decisions, design docs, research
findings, agent work logs.

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK | Always scoped to a project |
| `user_id` | TEXT FK | Owner |
| `title` | TEXT | Note title |
| `content_markdown` | TEXT | Markdown content (rendered via TipTap in UI) |
| `labels` | TEXT | JSON array of string labels |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |

### Event

Persistent event log for real-time sync and audit trail. Enables resumable SSE streams —
if a client reconnects, it can replay from `?since=<last_event_id>`.

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment (monotonic ordering) |
| `user_id` | TEXT FK | Who triggered the event |
| `event_type` | TEXT | `item.created`, `item.updated`, `project.created`, etc. |
| `entity_type` | TEXT | `project`, `item`, `note` |
| `entity_id` | TEXT | UUID of the affected entity |
| `project_id` | TEXT | For per-project SSE channel filtering |
| `payload` | TEXT | JSON snapshot of the change |
| `created_at` | TEXT | ISO datetime |

## MCP Tool Interface (for AI Agents)

Agents interact with the system via MCP tools served by a FastMCP server mounted alongside
the FastAPI app. Both share the same database and service layer.

### Agent Registration (Session-Scoped)

Agents register with a project at the start of a session. All subsequent project-scoped
tools operate within that project automatically — no need to pass `project_id` on every call.

```
register_agent(project_id) -> { status, project_id }
switch_project(project_id) -> { status, project_id }
```

Session state is per-client, isolated by FastMCP automatically. Agent A's session cannot
affect Agent B's session.

### Discovery Tools (no registration required)

```
list_projects(status?) -> [Project]
get_project(project_id) -> Project
```

### Item Tools (project-scoped after registration)

```
inbox_capture(text, project_id?) -> Item
    # Quick capture. Status=inbox, title=text.
    # If project_id omitted, uses registered project.
    # created_by set to agent identifier.

add_item(title, description?, priority?, status?, labels?) -> Item
    # Full item creation in the registered project.

update_item(item_id, title?, description?, status?, priority?,
            assigned_to?, labels?, version) -> Item
    # Partial update. version required for optimistic locking.

complete_item(item_id) -> Item
    # Convenience: sets status=done, completed_at=now.

list_items(status?, assigned_to?, priority?) -> [Item]
    # Lists items in the registered project.

get_item(item_id) -> Item

claim_item(item_id) -> Item
    # Sets assigned_to = this agent. Fails if already assigned
    # to a different agent (prevents collisions).

release_item(item_id) -> Item
    # Clears assigned_to. Use when agent can't complete the work.
```

### Note Tools (project-scoped after registration)

```
add_note(title, content_markdown?, labels?) -> Note
update_note(note_id, title?, content_markdown?, labels?) -> Note
list_notes() -> [Note]
get_note(note_id) -> Note
```

### Multi-Agent Safety

1. **Session isolation**: Each MCP client session has its own state. `register_agent()` binds
   a session to a project. Tools enforce scoping — an agent cannot accidentally write to
   another project.

2. **Optimistic locking**: `update_item()` requires a `version` parameter. If the version in
   the DB doesn't match (another agent modified the item), the update fails with a clear error.
   The agent must re-fetch and retry.

3. **Claim semantics**: `claim_item()` atomically assigns a task to an agent. If another agent
   already claimed it, the call fails. No two agents can work the same task.

4. **Provenance tracking**: `created_by` records who created each item (human or agent
   identifier). This is immutable audit data.

## REST API Interface (for Web UI)

The web UI uses standard REST endpoints. All endpoints require JWT authentication.

```
# Projects
GET    /api/projects                     List (filter: ?status, ?area)
POST   /api/projects                     Create
GET    /api/projects/{id}                Detail
PATCH  /api/projects/{id}                Update (partial)
DELETE /api/projects/{id}                Delete (cascades items + notes)

# Items
GET    /api/items                        List across all projects
                                         ?status, ?project_id, ?assigned_to,
                                         ?priority, ?due_before, ?sort
GET    /api/inbox                        Shorthand for ?status=inbox
POST   /api/inbox                        Quick capture (title only)
POST   /api/items                        Create (full fields)
GET    /api/items/{id}                   Detail
PATCH  /api/items/{id}                   Update (partial)
DELETE /api/items/{id}                   Delete
POST   /api/items/bulk                   Bulk update (move, re-status, re-assign)

# Project-scoped convenience
GET    /api/projects/{id}/items          Items for a project
POST   /api/projects/{id}/items          Create item in project

# Notes
GET    /api/projects/{id}/notes          Notes for a project
POST   /api/projects/{id}/notes          Create note
GET    /api/notes/{id}                   Detail
PATCH  /api/notes/{id}                   Update
DELETE /api/notes/{id}                   Delete

# Real-time
GET    /api/events                       SSE stream (global)
GET    /api/events/{project_id}          SSE stream (project-scoped)
                                         ?since=<event_id> for resumable

# Auth (existing)
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/health
```

## Real-Time Sync Architecture

```
┌──────────────┐    ┌──────────────┐
│  REST Routes  │    │  MCP Server  │
│  (web UI)     │    │  (agents)    │
└──────┬───────┘    └──────┬───────┘
       │                    │
       ▼                    ▼
┌─────────────────────────────────┐
│         Service Layer            │
│  (shared business logic)         │
└───────┬──────────────┬──────────┘
        │              │
        ▼              ▼
┌────────────┐  ┌──────────────┐
│  SQLite DB  │  │  Event Bus   │
│  (WAL mode) │  │  (asyncio)   │
└────────────┘  └──────┬───────┘
                       │
                       ▼
              ┌──────────────────┐
              │  SSE Endpoints   │
              │  /api/events     │
              │  (per-project +  │
              │   global channel)│
              └──────────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  React Frontend  │
              │  (EventSource)   │
              └──────────────────┘
```

**Both MCP tools and REST routes call the same service layer.** The service layer writes to
the database and publishes to an in-process asyncio event bus. SSE endpoints subscribe to the
bus and stream events to connected clients.

**Event bus** is in-memory (no Redis needed for single-server deployment). Events are also
persisted to the `events` table for resumable streams — on reconnect, the client passes
`?since=<last_event_id>` to replay missed events.

**SSE channels** are per-project (clients viewing a project page subscribe to that project's
channel) plus a global channel (for the inbox and review dashboard). Events include the full
entity snapshot so clients can update optimistically without a follow-up fetch.

## Web UI Concepts

### Page Structure

| Route | Page | Purpose |
|---|---|---|
| `/` | Inbox | Unprocessed captures. Quick-add bar. Process one at a time. |
| `/projects` | Project List | All projects grouped by area, filtered by status. |
| `/projects/:id` | Project Detail | **Kanban board** of items + notes tab. |
| `/next-actions` | Next Actions | All `next_action` items, optionally grouped by project. |
| `/waiting-for` | Waiting For | Items blocked on someone. Highlights stale items. |
| `/someday-maybe` | Someday/Maybe | Parked ideas. Review and promote during weekly review. |
| `/review` | Weekly Review | Dashboard: inbox count, per-project summaries, stale items, this week's completions. |
| `/settings` | Settings | Theme, user preferences. |

### Sidebar Navigation

- **Inbox** (badge showing unprocessed count)
- **Next Actions**
- **Projects**
- **Waiting For**
- **Someday / Maybe**
- **Weekly Review**
- **Settings**

### Key UI Components

- **Kanban Board** — Project detail view. Columns map to item statuses (`next_action`,
  `active`, `waiting_for`, `done`). Drag-and-drop to change status. Cards show title,
  priority chip, assigned-to indicator (human vs agent icon).

- **Inbox Processor** — Sequential triage: show one item at a time with quick-action buttons
  (Assign to Project, Someday/Maybe, Trash). This is the core GTD "clarify" workflow.

- **Quick Capture** — Persistent input bar or keyboard shortcut. Title only, one keystroke to
  submit. Available on every page.

- **Note Editor** — TipTap-based rich markdown editor for project notes. Live preview,
  standard formatting toolbar.

- **Item Dialog** — Shared create/edit dialog. Fields: title, description (markdown), project
  selector, status, priority, energy, time estimate, due date, labels.

- **Review Dashboard** — Three phases: Get Clear (inbox count + link), Get Current (per-project
  status cards with completion stats, stale waiting-for warnings, "no next actions" alerts),
  Get Creative (someday/maybe list, capture prompt).

## Boundary: Agent GTD vs Personal-KB

| | Agent GTD (this system) | Personal-KB (existing MCP server) |
|---|---|---|
| **Purpose** | Manage commitments and actions | Store and retrieve knowledge |
| **Content** | Tasks, projects, project notes, inbox items | Decisions, patterns, reference docs, lessons |
| **Lifecycle** | Dynamic — items flow through statuses | Static — knowledge accumulates over time |
| **Scope** | Tied to active projects | Cross-project, persistent |
| **Agents use it to...** | Track what to do next | Remember what they've learned |

Both systems complement each other. An agent working on a project uses Agent GTD to manage
its task queue and uses Personal-KB to recall prior decisions and patterns. Project notes in
Agent GTD may be "graduated" to KB when a project completes and the knowledge has lasting value.

## Implementation Dependencies

**Python (new):**
- `fastmcp` — MCP server framework
- `sse-starlette` — SSE support for FastAPI

**Frontend (new):**
- `@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-markdown` — rich text editor
- `@mui/x-date-pickers`, `dayjs` — date pickers for due dates
- `@hello-pangea/dnd` — drag-and-drop for kanban board
