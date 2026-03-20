# Feature: Weekly Review

## Overview

The GTD weekly review is the keystone habit of the methodology — the one ritual that keeps the system trusted and complete. The app already has all the pages needed to *do* a review (Inbox, InboxProcessor, Next Actions, Waiting For, Someday/Maybe, Projects), but no guided flow that ties them together. Users must mentally track where they are and what they've covered.

The Weekly Review feature adds a single page that walks users through Allen's three phases (Get Clear, Get Current, Get Creative) with inline context, progress tracking, and links to existing views. The one genuinely new UI is **project review cards** that surface project health at a glance — something no existing page provides.

**Scope constraint:** Frontend-only. No new backend endpoints, no new database tables, no new API calls beyond what already exists.

## User Stories

- As a GTD practitioner, I want a guided weekly review flow so that I don't skip steps or lose my place.
- As a user with many projects, I want to see at a glance which projects are "stuck" (no next action) so I can fix them during review.
- As a busy user, I want the review to reuse existing pages where possible so I don't have to learn new UI for familiar tasks.

## Design Decisions

### 1. Single scrollable page, not a stepper/wizard

**Decision:** One page at `/review` with three clearly labeled sections. No MUI Stepper, no phase transitions, no gate logic.

**Rationale:** The debate surfaced that a stepper adds state management complexity (active phase, back/forward navigation, gate validation, localStorage persistence) without meaningfully improving the experience. A scrollable page with section headers communicates order just as well. The user scrolls down as they work. This was the convergence point between the UX expert's revised Round 2 position and the skeptic.

### 2. Soft inbox nudge, not a hard gate

**Decision:** Show inbox count prominently with warning styling if >0. Don't block the user from scrolling past Get Clear.

**Rationale:** Hard gates create edge cases — items arriving via SSE mid-review, users who just processed inbox an hour ago, the inevitable "skip anyway" escape hatch that makes the gate pointless. Trust the user. A prominent count is sufficient motivation.

### 3. Section-level checkboxes, not per-item tracking

**Decision:** Each review step gets one checkbox ("Reviewed Next Actions", "Reviewed Waiting For", etc.). Not per-item checkmarks.

**Rationale:** Per-item tracking requires storing which items the user has "seen" (a growing Set in state), adds UI clutter, and creates false precision. The user knows whether they've actually reviewed a list. Section-level checkboxes are simple local state — 6-8 booleans.

### 4. Links to existing pages for list reviews, inline cards for projects

**Decision:** Next Actions, Waiting For, and Someday/Maybe show item counts and link to their existing pages. Project review is the only section with genuinely new inline UI.

**Rationale:** The list pages already work well for reviewing items (edit, done, delete actions, project/priority chips). Rebuilding them inline adds duplication. But the project review has a gap: no existing page answers "does every active project have a next action?" at a glance. This is the one place where new UI adds real value.

### 5. Someday/Maybe in Get Current (per Allen's methodology)

**Decision:** Someday/Maybe review is part of Get Current, not Get Creative.

**Rationale:** Allen's checklist explicitly places "Review Someday/Maybe List" in Get Current. The purpose is to check if anything has become relevant (activate it) or stale (delete it). Get Creative is about generating *new* ideas, not reviewing existing ones.

### 6. No state persistence for v1

**Decision:** Review state lives in `useState`. Navigating away resets progress. No localStorage.

**Rationale:** A review takes 15-30 minutes. Asking users to redo it if they leave is acceptable for v1. localStorage persistence can be added later if users request it, without any architectural changes.

## Screen Map / API Surface

### Route

`/review` — protected route, added to `App.tsx` inside the Layout wrapper.

### Sidebar

New "Reflect" section between Lists and Organize, containing one entry: "Weekly Review" with `EventRepeatIcon`.

### Page Layout

```
/review

Weekly Review
─────────────────────────────────────────────────

GET CLEAR
  [!] 5 items in inbox              [Process Inbox ->]
  [ ] Inbox processed to zero

GET CURRENT
  [ ] Review Next Actions (34)                    [->]
  [ ] Review Waiting For (8)                      [->]
  [ ] Review Someday / Maybe (12)                 [->]

  Active Projects
  ┌─────────────────────────────────────────────┐
  │ Project Alpha          3 next actions       │
  │ Has next action: Yes   Last active: 2d ago  │
  │                            [ ] Reviewed  [->]│
  ├─────────────────────────────────────────────┤
  │ Project Beta           0 next actions       │
  │ Has next action: No    Last active: 12d ago │
  │                            [ ] Reviewed  [->]│
  └─────────────────────────────────────────────┘

GET CREATIVE
  [Capture a new idea...]
  [ ] Brainstormed new ideas

  [Finish Review]

─────────────────────────────────────────────────
Reviewed 3 of 8 steps
```

### Completion

"Finish Review" button shows a brief summary: "Review complete. You have X next actions, Y waiting-for items across Z active projects." Then navigates home or offers to stay.

### API Calls (all existing)

| Call | Purpose |
|------|---------|
| `api.items.inbox()` | Inbox count for Get Clear |
| `api.items.list({ status: 'next_action' })` | Count for Next Actions step |
| `api.items.list({ status: 'waiting_for' })` | Count for Waiting For step |
| `api.items.list({ status: 'someday_maybe' })` | Count for Someday/Maybe step |
| `api.projects.list({ status: 'active' })` | Active projects list |
| `api.projects.items(id)` per project | Item breakdown per project for health indicator |

All fetched on page mount. The per-project items calls are the most expensive — for users with many projects, this could mean 10-15 parallel requests. Acceptable for v1; a summary endpoint could optimize this later.

## New Files

- `frontend/src/pages/WeeklyReview.tsx` — page component (~200-250 lines): fetches data, renders three phase sections, manages checkbox state, completion screen
- `frontend/src/components/ProjectReviewCard.tsx` — card for each active project (~80-100 lines): shows name, next-action indicator, last activity, reviewed checkbox, link to ProjectDetail

## Modified Files

- `frontend/src/App.tsx` — add `/review` route
- `frontend/src/components/Sidebar.tsx` — add "Reflect" section with "Weekly Review" link

## Implementation Steps

1. Create `ProjectReviewCard.tsx` — project name, has-next-action indicator, last activity, reviewed checkbox, link to project detail
2. Create `WeeklyReview.tsx` — data fetching, three sections (Get Clear, Get Current, Get Creative), section checkboxes, project cards, quick capture, finish button with summary
3. Add route in `App.tsx`
4. Add sidebar section in `Sidebar.tsx`
5. TypeScript + ESLint + build verification

## Open Questions

- **Per-project item fetching**: Should we fetch items for all active projects in parallel on mount, or lazily when the user scrolls to the projects section? Parallel is simpler but could be slow with many projects.
- **Quick capture in Get Creative**: Reuse the exact Inbox capture pattern (`api.items.capture(title)`) or add a project selector for directed capture?
- **"Finish Review" behavior**: Navigate home, or stay on the review page showing the summary?

## Definition of Done

- [ ] `/review` route renders the three-phase weekly review page
- [ ] Get Clear shows inbox count with warning styling and links to InboxProcessor
- [ ] Get Current shows item counts with links to existing list pages
- [ ] Get Current shows active project cards with next-action health indicator
- [ ] Get Creative has a quick capture field
- [ ] Section-level checkboxes track progress, "X of Y steps" counter visible
- [ ] Finish Review shows completion summary
- [ ] Sidebar has "Reflect" section with "Weekly Review" entry
- [ ] `npx tsc -b --noEmit` — no type errors
- [ ] `npm run lint` — no ESLint errors
- [ ] `npm run build` — production build succeeds

## Explicitly Deferred

- Keyboard shortcuts
- localStorage persistence / resume
- Review history / streak tracking
- Hard gate on inbox zero
- Per-item review tracking (reviewed X of Y items)
- Calendar integration
- Trigger list / incompletion triggers
- Bulk operations
- Project health metrics beyond "has next action"
- Mobile-specific optimizations (swipe gestures, MobileStepper)
- AI-assisted review suggestions
