# Agent GTD — Roadmap

High-level phases. Each phase produces a working system — we ship vertically, not
horizontally. Details will be figured out at the start of each phase, not up front.

---

## Phase 1: Core Data Model + CRUD ✅

Backend and frontend complete. Full-stack GTD app with working UI.

**What shipped:**
- Database schema: `projects`, `items`, `notes` tables
- Pydantic models and API schemas for all three entities
- REST routes: projects CRUD, items CRUD (including `/inbox` convenience endpoints), notes CRUD
- Service layer shared between REST and MCP
- 128 tests, 97% coverage threshold
- Frontend: login/register, inbox with quick capture + triage, projects list + detail (items
  and notes tabs), settings with theme toggle

**Exit criteria:** Met. Backend API and frontend UI are fully functional.

---

## Phase 2: MCP Server ✅

MCP server is live and being dogfooded via Claude Code.

**What shipped:**
- FastMCP server mounted at `/mcp` within the FastAPI app + stdio mode for Claude Code
- Agent registration (session-scoped project binding)
- 16 MCP tools: `register_agent`, `switch_project`, `list_projects`, `inbox_capture`,
  `add_item`, `update_item`, `complete_item`, `list_items`, `get_item`, `claim_item`,
  `release_item`, `add_note`, `update_note`, `list_notes`, `get_note`
- Optimistic locking (`version` column) on item updates
- Shared service layer (REST routes and MCP tools call the same code)
- Tests for MCP tools (session isolation, version conflicts, claim semantics)

**Infrastructure completed alongside:**
- Migrated from SQLite (aiosqlite) to PostgreSQL (asyncpg) — v1.3.0
- Connection pool, `$N` placeholders, auto-commit semantics
- `.env`-based config for `AGENT_GTD_DATABASE_URL` / `AGENT_GTD_TEST_DATABASE_URL`
- Pre-push coverage hook sources `.env` for DB access

**Exit criteria:** Met. Agents register, capture, update, and complete tasks. Session isolation verified.

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

## Phase 4: GTD Workflows + Rich UI (in progress)

Make it feel like GTD, not just a task list. This is where the methodology comes alive in
the UI.

**Done:**
- **GTD list views** — Next Actions, Waiting For, Someday/Maybe as cross-project pages with
  edit, done, delete actions and project/priority/due-date chips (v1.4.0)
- **Quick capture** — text field on Inbox page, submit on Enter
- **Sidebar restructured** into GTD sections: Collect / Lists / Organize

**Remaining:**
- **Inbox processor** — sequential triage view (one item at a time, quick-action buttons)
- **Kanban board** — project detail view with drag-and-drop columns mapped to item statuses
- **Weekly review dashboard** — Get Clear / Get Current / Get Creative phases
- **Global quick capture** — keyboard shortcut or floating input, available on every page
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
