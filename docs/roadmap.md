# Agent GTD — Roadmap

High-level phases. Each phase produces a working system — we ship vertically, not
horizontally. Details will be figured out at the start of each phase, not up front.

---

## Phase 1: Core Data Model + CRUD

Replace the notes scaffolding with the GTD domain. Get projects and items into the database,
expose them over REST, and render them in the frontend. No MCP, no real-time — just the
bones.

- Database schema: `projects`, `items`, `notes` tables (rip out `notes` scaffolding)
- Pydantic models and API schemas for all three entities
- REST routes: projects CRUD, items CRUD (including `/inbox` convenience endpoints), notes CRUD
- Frontend: project list page, project detail page (simple item list — not kanban yet),
  inbox page, basic item create/edit dialog
- Sidebar navigation updated to GTD structure
- Tests for all new backend routes

**Exit criteria:** A human can create projects, capture items to the inbox, triage them into
projects, and mark them done — all through the web UI.

---

## Phase 2: MCP Server

Give agents a way in. Mount FastMCP alongside FastAPI, sharing the same database and (soon)
service layer. Agents can discover projects, capture items, and manage tasks.

- FastMCP server mounted at `/mcp` within the FastAPI app
- Agent registration (session-scoped project binding)
- Core MCP tools: `list_projects`, `inbox_capture`, `add_item`, `update_item`,
  `complete_item`, `list_items`, `claim_item`, `release_item`
- Note tools: `add_note`, `update_note`, `list_notes`, `get_note`
- Optimistic locking (`version` column) on item updates
- Extract shared service layer so REST routes and MCP tools call the same code
- Tests for MCP tools (concurrent access, version conflicts, session isolation)

**Exit criteria:** An agent can register to a project, capture work, update items, and
complete tasks via MCP tools. Two agents on different projects can't collide.

---

## Phase 3: Real-Time Sync

Close the loop between agents and humans. When an agent creates an item via MCP, the human
sees it appear in their browser. When a human triages an inbox item, any SSE subscriber
learns about it.

- In-process asyncio event bus
- `events` table for persistence and resumable streams
- SSE endpoints: global (`/api/events`) and per-project (`/api/events/{project_id}`)
- Wire service layer mutations to publish events
- Frontend `useSSE` hook — subscribe to project or global channel, update component state
  on incoming events
- Reconnection with `?since=<last_event_id>` replay

**Exit criteria:** Open the UI, have an agent create items via MCP, watch them appear in
real time without refreshing.

---

## Phase 4: GTD Workflows + Rich UI

Make it feel like GTD, not just a task list. This is where the methodology comes alive in
the UI.

- **Inbox processor** — sequential triage view (one item at a time, quick-action buttons)
- **Kanban board** — project detail view with drag-and-drop columns mapped to item statuses
- **GTD list views** — next actions, waiting for, someday/maybe as dedicated pages with
  appropriate grouping and filtering
- **Weekly review dashboard** — Get Clear / Get Current / Get Creative phases
- **Quick capture** — global keyboard shortcut or floating input, available on every page
- **Note editor** — TipTap integration for rich markdown editing on project notes
- Bulk operations (move multiple inbox items, batch status changes during review)

**Exit criteria:** A human can run a complete GTD weekly review — process inbox, check each
project's status, review waiting-for items, scan someday/maybe — entirely within the app.

---

## Future (unscoped)

Ideas that may become phases once we learn more from using the system:

- **Agent activity feed** — timeline of what agents did, when, and why
- **Smart triage suggestions** — agent pre-fills project/priority/status on inbox items
- **Multi-user** — multiple human operators with shared projects
- **Notifications** — push alerts for stale waiting-for items, inbox overflow
- **Mobile-responsive polish** — the MUI foundation supports it, but needs attention
- **Metrics / analytics** — throughput, cycle time, items per project, agent productivity
