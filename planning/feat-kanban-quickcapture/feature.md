# Phase 4b: Kanban Board + Global Quick Capture

Two features shipping together on `feat/kanban-quickcapture`.

---

## Feature 1: Global Quick Capture (Spotlight Overlay)

### UX Design

**Keyboard shortcut:** `Cmd+K` (Mac) / `Ctrl+K` (other). Established command palette convention (Linear, Notion, VS Code).

**Overlay:** MUI Dialog positioned at top of viewport (10vh from top), `maxWidth="sm"` (~600px), Slide-down transition. Backdrop blur/dim.

**Two modes via progressive disclosure:**

1. **Fast mode (default):** Single text field, type title, press Enter. Item captured to inbox. Toast confirmation bottom-left: "Captured to Inbox" with "View" link.

2. **Expanded mode (Tab):** Press Tab from the title field to reveal optional fields below — Project dropdown, Priority select, Status select. All pre-populated with defaults (inbox, normal, no project). Enter to submit.

**After capture:** Brief checkmark + title shown for 1s, then field clears and is ready for another capture. Escape closes the overlay. Second Enter without typing also closes.

**Behavior rules:**
- `Cmd+K` toggles overlay (open/close)
- `Escape` collapses expanded fields first, second Escape closes overlay
- Click outside closes overlay
- Guard: don't fire shortcut when user is in a text input/textarea (check `e.target`)
- Focus returns to previously focused element on close

**Relationship to Inbox page:** Keep the existing inline capture field on Inbox.tsx. The overlay complements it for "capture from anywhere" use.

### Implementation

**New dependencies:** `react-hotkeys-hook` (global shortcut handling)

**New files:**
- `frontend/src/components/QuickCapture.tsx` — the overlay component (Dialog + form)
- `frontend/src/contexts/QuickCaptureContext.tsx` — provides `openCapture()` / `closeCapture()` + global shortcut registration

**Modified files:**
- `frontend/src/main.tsx` — wrap app in `QuickCaptureProvider`
- `frontend/src/components/Layout.tsx` — optional: add capture icon button in AppBar as secondary trigger

### Steps

1. `npm install react-hotkeys-hook`
2. Create `QuickCaptureContext.tsx` — register `meta+k` / `ctrl+k` via `useHotkeys`, manage open/close state
3. Create `QuickCapture.tsx` — MUI Dialog with Slide transition, title TextField, expandable fields panel (Collapse), submit handler calling `api.items.capture()` or `api.items.create()` (when fields are set)
4. Wire into `main.tsx`
5. Add capture icon button to Layout AppBar header
6. Tests: vitest for keyboard shortcut registration, form submission logic

---

## Feature 2: Kanban Board (Project Detail)

### UX Design

**Layout:** Hybrid of GTD Flow Board + simplified columns. 4 active columns + collapsed Done:

| Column | Status(es) | Purpose |
|--------|-----------|---------|
| **Inbox** | `inbox` | Unprocessed items |
| **Next Action** | `next_action` | Committed work |
| **In Progress** | `active` + `waiting_for` + `scheduled` | Currently being worked or blocked. Sub-status shown as chip on card. |
| **Someday** | `someday_maybe` | Low-commitment backlog |
| **Done** (collapsed) | `done` | Completed items. Shows count badge, expander reveals title list. |

`cancelled` items hidden from board. Toggle "Show cancelled" in toolbar reveals them greyed out.

**Card design:**
```
+-------------------------------+
| [colored left border = prio]  |
| Title of item                 |
| due: 2026-03-05               |
| [waiting_for] [label1]        |
|                    [edit] [x] |
+-------------------------------+
```
- Priority = colored left border (grey/blue/amber/red)
- Due date shown only if set; overdue in error color
- Sub-status chip shown only in "In Progress" column (to distinguish active/waiting/scheduled)
- Edit + delete icon buttons

**View toggle:** Icon button group in Items tab toolbar: list icon / board icon. Persisted in `localStorage` per project (`gtd_view_${projectId}`).

**Drag-and-drop rules:**
- Any column to any column: ALLOWED
- Drop into Done: sets `completedAt` timestamp
- Drop out of Done: clears `completedAt`
- Drop into In Progress: defaults to `active` status (user can change sub-status via edit)
- Within a column: reorder via `sortOrder`
- No forbidden transitions (keep it simple; edit dialog for nuanced changes)

**Empty columns:** Visible with dashed border, "+ Add item" button that pre-sets status.

**Sort order:** Float midpoint algorithm. Insert between A and B = `(A + B) / 2`. Rebalance (re-space to 0, 1000, 2000...) when gap < 0.001.

**SSE during drag:** Buffer incoming SSE events while `isDragging` ref is true. Apply buffered updates on drop completion. Toast "Items updated remotely" if buffer was non-empty.

**Optimistic updates:** On drop, immediately update local state. Fire PATCH. On failure, rollback to pre-drop snapshot. Suppress SSE re-fetch for items with in-flight mutations.

**Mobile (<600px):** Auto-fallback to list view. No toggle shown.

### Implementation

**New dependencies:** `@dnd-kit/react`, `@dnd-kit/dom`

**New files:**
- `frontend/src/components/KanbanBoard.tsx` — board container (columns layout, DragDropProvider)
- `frontend/src/components/KanbanColumn.tsx` — single column (droppable, header, card list, add button)
- `frontend/src/components/KanbanCard.tsx` — draggable item card

**Modified files:**
- `frontend/src/pages/ProjectDetail.tsx` — add view toggle, render KanbanBoard or existing list based on toggle state
- `frontend/src/api.ts` — may need a batch reorder endpoint or just use existing `items.update()`

**Backend changes:**
- None expected. `sortOrder` field already exists. `PATCH /items/:id` with `{status, sortOrder}` covers all drag operations.

### Steps

1. `npm install @dnd-kit/react @dnd-kit/dom`
2. Create `KanbanCard.tsx` — styled MUI Card with priority border, due date, labels, action buttons, useSortable from dnd-kit
3. Create `KanbanColumn.tsx` — column header with count, droppable zone, card list, empty state with "+ Add"
4. Create `KanbanBoard.tsx` — DragDropProvider, column layout, drag handlers (onDragEnd computes new sortOrder + status, fires optimistic update + PATCH)
5. Modify `ProjectDetail.tsx` — add toggle state (localStorage), conditionally render board vs list, pass items + handlers
6. Handle SSE buffering during drag
7. Tests: vitest for sortOrder midpoint calculation, column status mapping

---

## Shared Concerns

**New npm dependencies (3 total):**
- `@dnd-kit/react` + `@dnd-kit/dom` — drag-and-drop
- `react-hotkeys-hook` — keyboard shortcuts

**No backend changes required.** Existing API endpoints cover all operations.

**Build order:** Quick Capture first (smaller, standalone), then Kanban (larger, more complex). Both can be on the same feature branch.
