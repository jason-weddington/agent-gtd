## Agent GTD and Headless Dispatch

An Agent GTD MCP server is available for task management. When it is, use the interactive + autonomous workflow described below. In short:

- **Interactive sessions** (this one): planning, strategy, complex work, architecture, debugging, reviewing dispatched branches
- **Autonomous dispatch**: clearly-defined tasks get dispatched to headless agents via GTD. They push feature branches and comment on the task.
- During interactive sessions, create well-scoped tasks in GTD for autonomous work. Review the resulting branches in a later interactive session.
- The interactive session is the control plane. Don't dispatch ambiguous tasks.

**Important: if Agent GTD MCP is not available, something is wrong. Stop and tell me.**

### Setting the commit type

Every item that joins a rollout needs a groomed `commit_type` (`feat`, `fix`, `perf`, `refactor`, `test`, `docs` or `chore`): `plan_rollout` refuses items without it, the rollout reviewer is handed the exact squash subject built from it, and the worker checks the landed commit's type afterwards. It is the type the changelog sees, so decide it at grooming time: a change someone using the project could notice is `feat` or `fix`, never `chore`. The groom-to-ready workflow returns it alongside `build_engine`, and `agent-gtd add-item` / `update-item --from-json` carry it straight through (or use `update-item --commit-type <type>`). Like `build_engine`, it does not inherit; on a direct build it is advisory.

### Choosing a build engine

Model choice and harness choice are separate decisions, and both are set per item —
`build_engine` does **not** inherit, so set it explicitly on every GTD item before
dispatch (CLI-added items especially).

**Model lanes**, cheapest-capable first:

- **`glm-5.3-flash`** (`talos-glm-flash`) — the default for anything a Sonnet-class
  model would one-shot from a groomed spec: mirror, polish and integration items,
  eval sub-agents, answer-mode workflow agents, and anything with a lot of turns.
  321B MoE / 18B active, 1M context. On tier-2 evals it matches full glm-5.3 with
  better finish discipline at roughly a tenth of the cost.
- **`glm-5.3`** (`talos-glm`, `claude-code-glm`) — when the item needs the stronger
  model: novel work, cross-package changes, design-heavy specs, or after a flash
  miss.
- **Anthropic lanes** (`claude-code-sonnet`, `claude-code` = Opus, `talos-sonnet` /
  `talos-opus`) — reach for these when a run has missed twice on the cheaper lanes,
  when the task needs the Claude Code harness's tool surface specifically, or when
  the owner says so. Opus stays the pick for engine-core changes with subtle
  correctness stories, and for measurement work where a plausible-looking wrong
  method would produce a confident wrong conclusion.
- **`talos-qwen`** (local GPU, free) — one at a time, single GPU; roughly double the
  turns of a frontier model.

**Harness is a separate axis.** `talos-*` lanes self-verify against the project's
`gate_command` and are the cheaper harness; `claude-code-glm` is the *same model* as
`talos-glm` under the Claude Code harness — the fallback when a talos-glm run
misses, **not** a bigger model.

**Compensate for a cheaper model in the spec, not in the review.** A flash-tier run
does noticeably better when the judgement is written into the item — exact constants,
exact expected values, the pass tolerance stated — rather than left for the agent to
derive. If you would have to explain it to a reviewer afterwards, put it in the
acceptance criteria beforehand.

**Two talos-specific gotchas.** It commits once, so a *fixer* pre-commit hook
(`ruff --fix`, `black`, `prettier`) destroys a completed unit of work — the repo's
hooks must all be checkers (see the hook-unification note below). And a talos run can
report **`failed` while its work is complete and pushed**, typically when it attempts
a redundant final commit with nothing staged: **check the branch before re-dispatching
a failed talos run.**

**A talos run's transcript is keyed by ITEM id, not run id, so a re-dispatch destroys
the evidence for the run you are trying to explain.** Artifacts live on the dispatch
host at `~dispatch/.local/state/talos/<item-id>/` (`transcript.jsonl` + `run.sqlite`),
and the next run on that item overwrites them. This is backwards from what an operator
wants under failure, so: **before re-dispatching a failed or puzzling run, copy the
transcript off the host.** `scp <host>:/home/dispatch/.local/state/talos/<item-id>/transcript.jsonl .`
The terminal record alone settles most questions — `disposition`, `change`
(`TreeChanged` / `TreeUnchanged` / `Unobservable`), `edit_file_calls_ok`,
`mutating_iters`, `gates_green_at_exit` — and it has twice this week overturned a
diagnosis made from the worker's error string. Read the transcript before theorizing.

**Never write an AC that asks a talos agent to commit** — no pinned commit subject, no
"commit on the feature branch", nothing that reads as an instruction to run `git add` or
`git commit`. The dispatch worker owns the commit. An agent that commits leaves nothing
staged, so the worker's own commit fails, the run is marked `failed`, and it returns
**before the push** — discarding a complete, gate-green commit sitting right there in the
clone. This has burned two runs on one item, each one a verified Done. If you want a
particular commit subject, write it in the item title and let the worker derive it.

Log the engine on every `dispatch-performance-log` entry — it is a mandatory field —
and note token/cost when the run record shows them.

### Bias hard toward dispatch — protect the control plane

This session's context window is the scarce resource. Past ~60-65% usage,
inference slows noticeably and quality degrades. Every token spent reading
files, running searches, or doing implementation work inline is a token
the control plane can't spend later on orchestration, review, or
big-picture judgment that has to span dozens of features.

**Default: dispatch the work, don't do it inline.** This applies even
when "I could just do it" feels faster in the moment — the cost shows up
later as a session that can't keep going.

`dispatch_item` exposes two modes:
- `mode="build"` — implement, push a feature branch, comment back
- `mode="plan"` — groom a task: write acceptance criteria, identify
  files, ask clarifying questions. The agent's exploration tokens don't
  count against this session. **Use plan mode only for smaller tasks that
  just need a spec — not complex ones.** A plan dispatch is one agent, one
  pass, no adversarial check. For complex or high-stakes items (multi-file,
  cross-package, a formula/enum with soft members, anything where the spec
  doc might be ahead of the code), use the **grooming workflow** instead
  (see "Grooming complex items with a workflow" below).

**Do inline only when**:
- It's a trivial <5-line edit (faster to do than to groom + dispatch), OR
- It genuinely needs live conversation context (architectural decisions
  mid-discussion, debugging where the loop is "run, see, fix"), OR
- You're reviewing/merging a dispatched branch (that's the control plane's
  actual job)

Everything else — including "let me just read these files to understand X"
or "I'll do a quick refactor while I'm here" — should become a groomed
GTD task and a dispatch. Worktree-isolated local agents are a distant
second choice (they pause when the laptop sleeps); headless dispatch is
the default.

**Cross-repo work**: headless agents are locked into a single repo, so
research that spans projects (e.g. PQ + cleanr + flickrasync) needs
either (a) parallel plan-mode dispatches in each project's GTD with
results returned via comment, or (b) sub-agents via the `Agent` tool,
whose context lives outside this session and only the summary returns.
Either way, do NOT spread the cross-repo reads across this session
yourself.

The longer the control plane context lasts coherently, the more waves of
work it can oversee. Optimize for that.

### Backlog grooming ritual

All new tasks start in **new** status. Grooming moves them to **ready**. A task is
ready when acceptance criteria are clear and testable, files to modify are identified,
scope boundaries are explicit, and verification steps are defined.

During interactive sessions, prioritize grooming before dispatching. The pattern:
1. Review items in `new` status
2. For each: add acceptance criteria, file paths, patterns to follow, scope boundaries
3. Move to `ready` when the description is dispatch-ready
4. If the intent is unclear, ask me — don't guess

Well-groomed tasks get one-shotted by headless agents. Vague tasks waste turns.

**Check `repo_mode` before you groom.** GTD projects are `monorepo` or
`workspace`; a lead that assumes monorepo grooms wrong scope boundaries
("that's in the other repo — document it, don't fix it") when the build agent
would actually get **every** repo in `workspace_repos` cloned side by side.
Before writing scope/AC for any project you haven't confirmed this session,
read the project record (`get_project` / `list_projects`) and note
`repo_mode` + `workspace_repos`. For workspace items, `files_to_modify` paths
are repo-dir-prefixed (`agent_gtd/src/...`, `agent-gtd-dispatch/src/...`) and
cross-repo work belongs in ONE item, not split by repo. Pass the workspace
fact into any groom workflow's context args — the critics can't catch a
repo-boundary error if the lead feeds them the wrong boundary.

**But don't over-groom requests where I already expressed clear intent.** When my
ask is shaped as state-vs-outcome ("X currently does A, I want it to do B") or
feature-extension ("add Y like the existing Z"), the right move is to *slightly
enrich* my statement and dispatch in **plan mode** — not to open five files and
write 100+ lines of recommended JSX in the description yourself. The plan agent
has its own exploration tokens; that's the whole point of plan/build split.

What "slightly enrich" means: keep my intent intact, add only the bits a fresh
agent with no conversation memory wouldn't know — recently-added components or
features I'm referring to, the name of the relevant page/component if non-obvious,
cross-feature constraints ("match the disabled conditions of the existing X
button"). Don't paste recommended code, don't enumerate files, don't write the AC
checklist. Trust the plan agent. Its output becomes the build-mode spec.

Counter-signal you've gone too far: you're 100+ lines into a description and have
read more than two files just to write it. Back out and ship a 5-sentence enriched
intent instead.

Reserve full inline grooming for cases where the brief itself is genuinely
ambiguous, or load-bearing decisions need to happen in this session before any
agent can act.

**Overriding a groomed spec? Edit the acceptance criteria — a comment is not the
contract.** When you correct or narrow a spec someone else groomed (another
session's hand-off, a plan run's output, your own earlier disposition), the
correction has to land *in* the ACs and `files_to_modify`. A build agent reading a
comment that contradicts AC-2 will follow AC-2 — correctly, because the ACs are the
spec of record. The failure is silent and expensive: the run goes green against the
stale spec and you throw the branch away. It also applies to ground truth that
shrinks the work ("most of this already exists at X, extend it") — fold it into the
ACs, don't leave it as prose the agent may weigh against its instructions. Concrete
case: a lead-pinned Postgres auth model (socket peer auth) lived in a comment while
the ACs still said trust-auth-over-TCP; the agent shipped the ACs' version and the
whole run was discarded.

### Grooming complex items with a workflow (draft → critic → synthesize)

Plan-mode dispatch is one agent, one pass, no adversarial check. For **complex
or high-stakes items** — multi-file, cross-package, a formula or enum with soft
members, anything where the spec doc might be ahead of the code — that single
pass ships wrong specs: phantom file paths, stale signatures, "five moves are
possible" left un-enumerated, a prereq assumed-shipped that isn't. For those,
groom with a **`Workflow`** instead. (This is the deterministic, structured
version of hand-wiring a team of critic subagents — prefer it.)

The shape, per item, pipelined (draft→critic→synthesize, no barrier between
items):
1. **Draft** — one agent reads the cited design docs AND the actual repo, and
   returns a *structured* spec (acceptance_criteria, files_to_modify, scope_out,
   build_engine, readiness, open_questions, grounding_notes) via a JSON schema.
2. **Critic** — two parallel lenses on the draft:
   - *code-grounding / reality-check* — open every named file; confirm each
     path, symbol, signature, and prerequisite exists in the repo **today**.
     This is the lens that earns the workflow: it catches the wrong directory,
     the cross-package typecheck-breaker, the prereq that isn't built, the stale
     constant in your own prior disposition.
   - *concrete-by-default / spec-rigor* — every enum enumerated, every constant
     pinned to a literal, no "appropriate"/"as needed" ACs, a soft-values line.
3. **Synthesize** — fold the critic findings in, re-open any flagged file, set
   an honest `readiness` (ready vs blocked-on-prereq vs needs-decision).

The workflow **returns** the specs to the control plane; the control plane
reviews and writes them into GTD (AC/files/scope + `status=ready`, or keep
`new` with the blockers recorded if not ready). Do NOT have the workflow
write GTD directly — the review is the checkpoint, and where you make any
load-bearing call the critics surfaced.

**Write the specs with the `agent-gtd` CLI, not inline MCP calls.** `agent-gtd
add-item` / `update-item` accept the full spec as JSON via `--from-json FILE` or
`--stdin`, using the SAME field names the groom returns (`acceptance_criteria`,
`files_to_modify` `[{path, change}]`, `scope_out`, `title`, `description`).
`update-item` **auto-fetches the version and retries on conflict** when you omit
`--version` (no `get_item` round-trip); `add-item` prints the new UUID to stdout.
This keeps the big AC/files arrays OUT of the control-plane context — the MCP
`update_item`/`add_item` path pulls ~10KB/item back through your window, which is
exactly the context you're trying to protect. Pattern: groom writes `finals` to a
file → `jq` each spec out → `agent-gtd update-item <id> --from-json <spec>.json
--status ready`. For a large batch, a bounded local `Agent` subagent (or a plain
shell loop) runs these CLI writes from the workflow's output file — judgment-light,
zero context cost. Reserve inline MCP `update_item` for a one-off where you're
already holding the item. (Flags: `agent-gtd add-item --help` / `update-item
--help`.)

Ground rules that make it pay off:
- **Cite only what the build agent will have.** A fleet build agent works from a
  fresh clone of the target repo (plus `workspace_repos` for a workspace project)
  and nothing else. A spec that says "port byte-for-byte from
  `~/.claude/workflows/x.js`" or "mirror `~/git/other-repo/foo.rs`" is citing a
  file that does not exist where the work happens. The agent will correctly
  discover that and either stop or reconstruct from partial hints — one
  StoppedWithoutFinish run cost exactly this on 2026-09-19. Vendor the
  source into the repo (`reference/`), inline the needed text into the ACs, or
  drop the citation. Tell the code-grounding critic to verify paths against the
  **clone's** file set, not the lead's filesystem — the two differ precisely
  when it matters, because the critics run on your machine and the builder does
  not.
- **Ground in current code, not the design doc.** Tell the agents the docs may
  be ahead of (or behind) reality; a doc claim is a claim to verify. An honest
  "blocked-on-prereq" naming the exact missing code beats a confident "ready"
  against a phantom API.
- **Pass locked design dispositions as args** (pinned constants, enum members)
  so agents reconcile against them instead of re-deriving — and so the critics
  can catch when a *disposition itself* is stale.
- **Groom the contract owner first, then its consumers.** When a batch contains one item that OWNS shared artefacts (the files, types, DDL, constants or helpers the other items import) and several that CONSUME them, grooming them flat produces N mutually incompatible contracts: each consumer's draft and critics can only see the repo, never the owner's not-yet-written spec, so each one invents its own colour-constant name, its own argument shape, its own type name, its own DDL — every spec individually rigorous and "ready", the union unable to compile. Pass `owners: [<item id or slug>, ...]` and the workflow runs owners first, then the rest with each owner's FINAL synthesized spec injected as a contract of record; `contracts: "<text>"` pins the same thing by hand when the contract lives in a doc or a DDL block rather than in a sibling item. If a batch already ran flat, don't re-groom it — run a reconciliation pass instead: one agent per consumer, handed the owner's final spec, rewriting that consumer's ACs to the owner's names verbatim, and fold the lead decisions the consumers' critics surfaced (nullability, integer-vs-float, timestamp format) into the same pass.
- **Every decision needs an owning item.** Per-item grooming verifies a spec against the repo and against the doc section that item cites; nothing in it can notice that a numbered decision maps to NO item, which is exactly how four of six cross-item gaps arrived on one recent wave — a lazy-fill decision nobody implemented, a headline number nothing read, a wire field dropped during reconciliation, a data-horizon promise that left every chart ending in a fabricated zero. Pass `decisions: [{id, text}, ...]` (the doc's D-numbers) and the workflow adds a coverage agent that returns `{owned: [{decision, items, evidence}], unowned: [...]}` after synthesis. Every unowned decision is then a decision YOU make before dispatch: assign it to an item's ACs, or write it into the doc as explicitly out of scope — leaving it unassigned is how it becomes a seam gap. Do the same for any wire field a reconciliation pass dropped, and expect review-against-intent's integrate phase to re-check the same decision list against what landed.
- **Make the script arg-shape-tolerant**: `const ARGS = typeof args === "string"
  ? JSON.parse(args) : args` — the value can arrive stringified.

**Reusable starting point:** a project-agnostic version of this workflow ships in
this examples directory as `examples/workflows/groom-to-ready.workflow.js`. Once copied or
symlinked into `~/.claude/workflows/`, run it with
`Workflow({name: "groom-to-ready", args: {context, items}})`
— `context` is a free-text string of project specifics (stack, where-to-look,
ground-truth facts the agents should treat as authoritative); `items` is
`[{id, slug, title, seed, criticalConstraint?}]`. It returns `{finals: [spec,...]}`
for the control plane to review and write into GTD. Copy + specialize it when a
project needs bespoke lenses.

Cost is ~4 agents per item (1 draft + 2 critics + 1 synth), ~10 min and a few
hundred K tokens for a small batch — worth it whenever a wrong spec would cost a
full build-agent wave shipping the wrong shape. For a genuinely small task that
just needs a spec, plan mode is still the right, cheaper tool.

### Reviewing complex landed work with a workflow (the review counterpart)

Groom is the forward half (intent → spec); there's a backward half too. When a
complex feature ships as a **multi-item dispatch wave** — especially cross-repo,
or with deletions that change a default — do NOT declare it done on the strength
of green per-item dispatches. Decomposition manufactures **ownership gaps at the
seams**: capability that no single item owns, so every item is individually
"done" and all gates pass, yet the feature is broken end-to-end. Per-item reviews
(and you, the lead) are each scoped to one item and structurally cannot see this.
This is an **orchestration failure**, and the harness piece that closes it is a
review workflow.

**`review-against-intent` workflow** (ships in this examples directory as
`examples/workflows/review-against-intent.workflow.js`) — adversarial review of what
LANDED against the groomed intent + per-item specs. Once copied or symlinked
into `~/.claude/workflows/`, run it with
`Workflow({name: "review-against-intent",
args: {intent, repos, landed, items}})` — `intent` is the feature outcome + the
decision-of-record ref; `repos` is `[{name, path}]`; `landed` lists the
commits/ranges per repo; `items` is `[{id, title, repo, commits, gtd_board}]`
(items can carry inline `acceptance_criteria`, or omit them and the verify agent
fetches the spec from GTD by id — fetch-mode keeps control-plane args lean for
big waves). Four phases: **verify** (per item, re-grounded in real code + commit
diffs, file:line evidence — never trusts the dispatch self-report) → **refute**
(try to overturn each non-met finding so it doesn't cry wolf) → **integrate**
(barrier; 3 lenses — seam-coherence, intent-completeness, regression/scope — this
is where the between-items gaps surface) → **synthesize** (one verdict:
meets-intent / meets-with-gaps / does-not-meet, with fixes + ordered recs). It
WRITES nothing; the control plane reads the verdict and captures fixes. Cost
~9-15 agents. (Proven in practice: it returned does-not-meet on a 5-item feature
that was "100% green," catching two ship-blocking seam gaps unit tests had hidden.)

**Standing rule:** treat a `does-not-meet` / `meets-with-gaps` verdict as a gate —
a multi-item wave isn't done until review-against-intent is clean or the gaps are
captured. Reserve it for genuinely complex/multi-item/cross-repo waves; a single
well-scoped item doesn't need it.

### Capture and offer dispatch work as you go

During interactive sessions, watch for tasks that are clearly scoped and don't need real-time conversation: bug fixes with obvious root causes, test additions, mechanical refactors, small features with a clear pattern to follow. Capture each as a groomed GTD item in the right project at a natural breakpoint rather than interrupting flow. Exploration tokens you already spent become shovel-ready work almost for free.

**Offer to dispatch** whenever a groomed item doesn't conflict with the current interactive work: confirm it's groomed (clear ACs, file paths, scope boundaries), check it won't touch files you're actively editing, offer ("I can dispatch X while we continue on Y"), and on approval call `dispatch_item(item_id=...)` directly rather than sending the human to the UI. Prefer headless dispatch over worktree-isolated local agents: dispatch hosts keep working when the laptop sleeps, local agents don't.

After a dispatched branch is merged, delete it locally **and on origin** (`git branch -D feat/<branch>`; `git push origin --delete feat/<branch>`). Headless agents push feature branches to origin, and stale ones accumulate there.

### Two dispatch shapes — direct build or rollout

They differ in who merges, which changes the lead's per-completion cycle:

- **Direct build** — `dispatch_item(mode="build")`. The build agent implements the work and pushes a feature branch. **The lead reviews, merges and pushes.** Use for one-off items, or whenever you want to review the merge yourself.
- **Rollout** — `plan_rollout(item_ids=[...])` then `dispatch_rollout(rollout_id=...)` (the dedicated tool; `dispatch_item(mode="manage")` is rejected by the API). There is **no long-lived manager agent**: the dispatch service's own code drives the loop. It dispatches each ready item's build, waits for it, then launches a **short-lived reviewer agent for that one build**. The reviewer judges the work against the ACs, may make a small inline fix, **runs the squash-merge and `git push` itself**, and writes a verdict (`merge` / `re-dispatch` / `skip` / `halt`). The worker code acts on the verdict: it records the item's outcome, re-dispatches, or halts, then advances. **The lead does not touch git** for items a reviewer merged cleanly and only intervenes on halts. Run records and comments still carry legacy `manage` / `claude-manage-…` names for this loop; no manager agent is behind them.

**Default to rollouts for 2+ items in the same project**, and use **one rollout per project, not per wave**: the planner builds the dependency graph from blockers and file overlap and runs the waves inside it. Splitting a project's ready work into several rollouts just multiplies monitors and cleanup. Add explicit blockers only where order matters. Rollouts are project-scoped, and only `ready` items with `build_engine` set can join.

### The autonomous wave cycle

Once a feature is groomed into items, ship it end to end without interactive supervision: the human spends ~15-20 minutes planning, then the lead runs for hours while they work elsewhere. When the human says "manage dispatch autonomously", "get the feature to done", "dispatch wave 1 and keep going" or similar, this cycle is the default; don't ask them to respell cadence, wave boundaries or monitoring.

1. **Size each task**: inline only if it's a <5-line trivial edit or genuinely needs the live conversation. Everything else dispatches.
2. **Sequence for concurrency** from each item's `files_to_modify`: non-overlapping items run in parallel up to fleet capacity; overlaps and dependency chains become successive waves. Within a rollout the planner does this for you.
3. **Arm event-driven monitors** (see "Monitoring dispatched runs" below): one per direct build (`run-status`), or one per rollout (`rollout-status`), never one per rollout child.
4. **Per-completion cycle:**
   - **Direct build completes:** read the agent's final comment on the item. Diff the branch **against its merge-base, not against main**: a dispatch clone can be a commit or two behind, and `git diff main <branch>` then shows main's newer commits as mass deletions. Use `git show --stat <commit>` or `git diff $(git merge-base main <branch>) <branch>`; `git merge --squash` already does the right thing. Squash-merge with a clean conventional-commit message, fix lint/format/merge conflicts **inline** (redispatch only if the logic is wrong or missed scope), push main without tags, then `complete_item` and delete the local and remote branches.
   - **Rollout reaches a terminal state** (`completed`, `failed`, `halted`, `cancelled`): on `completed`, each reviewer has already merged and pushed its item, so spot-check `git log origin/main` for what landed, **including the commit types, which drive the changelog**, and delete leftover local branches. On `halted`/`failed`, read the halt reason (posted on the rollout and the offending item), then fix inline and advance, redispatch the item, or cancel the rest; a reviewer returns `halt` when unsure, by design. **Before trusting a halt reason, check the board and `origin/main`: a halt can follow work that actually landed.** On `cancelled`, reconcile state.
   - More dispatches still running: do nothing, wait for the next monitor wake. All done and the next wave unblocked: dispatch it, with new monitors.
5. **Between waves, don't deploy, release, or create tags** unless the human asks; those are their calls.
6. **Stop condition**: every item merged to origin main (by you or a reviewer) and every monitor stopped. End with a summary of what shipped, what's blocked, and what needs the human.

### Control-plane token discipline — don't narrate the play-by-play

The point of GTD + headless dispatch is asynchrony: groom for ~20 minutes, then agents grind for hours while the human runs other sessions. **During that grind nobody is watching.** Every line of play-by-play prose between tool calls is permanent conversation history — tokens spent narrating to an empty room, and a wall of text to wade through later. You don't need the narration to stay on track; your tool calls and results are already in context.

- **Default to near-silence during a wave.** Run the mechanical cycle (dispatch, monitor, fetch, review diff, merge, complete, delete branch) through tool calls with minimal commentary. A terse one-liner at a real milestone is plenty.
- **Surface only two things:** a **question or decision** that needs the human, promptly and unmissably; and a **concise summary** at the end of the wave or a genuine checkpoint.
- **Batch the bookkeeping** rather than announcing each step.

Optimize the control-plane session to last longer and stay coherent across many waves: fewer, denser, decision-oriented messages.

### Monitoring dispatched runs — event-driven, not polled

The `agent-gtd` CLI exposes dispatch status to the shell (same data as the MCP
`get_run_status` tool). The CLI has a **first-class blocking waiter** — `--wait`
on `run-status` / `rollout-status` — so you wake within one poll interval of a
dispatch finishing without hand-rolling a poll loop. Run that waiter inside a
`Monitor`, for the reason given below.
**Use this pattern. Do not set wakeup timers for dispatch monitoring.**

The CLI reads `AGENT_GTD_URL` + `AGENT_GTD_API_KEY` from the env. These
inherit through to the Bash tool when I launch Claude Code from a shell
that already has them sourced — usually true. If `agent-gtd run-status` ever
errors with auth/URL issues, ask me to check my env; do NOT try to source
`.envrc.secrets` autonomously (it pops a 1Password dialog).

#### The mechanism: native `--wait`

`--wait` blocks until the run/rollout reaches a terminal state, prints the final
status JSON, and exits with an **outcome-reflecting** code. It retries transient
fetch errors internally and only exits on a real terminal state or a fatal
auth/not-found error, so it has none of the false-DONE shape a hand-rolled poll
loop has.

```bash
agent-gtd run-status <run_id> --wait
```

Exit codes: **0** terminal success · **2** terminal failure
(`failed`/`cancelled`/`error`/`timeout`; rollouts also `halted`) · **124**
client `--timeout` exceeded (last JSON goes to stderr) · **1** operational error
(auth/network/not-found). `--poll-interval` defaults to 30s (5s floor);
`--timeout` defaults to 0 = wait until the server flips it terminal. For a
rollout, use `agent-gtd rollout-status <rollout_id> --wait` — same contract.

#### Where to host it: a background task, or `Monitor`

The waiter needs a host that outlives the turn. `run_in_background: true` on a
plain Bash call is the simplest one — the command exits when the run reaches a
terminal state and you get a single completion notification carrying its exit
code, with no re-arming.

`Monitor` is the alternative, and it is what to use on a machine where
long-lived background shells do not survive (see your own `CLAUDE.md` if that
applies to yours):

```
Monitor({
  description: "dispatch <item-slug> terminal status",
  timeout_ms: 1800000,
  command: "agent-gtd run-status <run_id> --wait",
})
```

The final status JSON arrives as one notification and the process exit ends the
watch, with its exit code reported — so a terminal failure and an auth error are
both visible rather than silent. Fan out one per run or per rollout.

**`Monitor` caps at 30 minutes, so a long run needs re-arming.** You get an
expiry notice; re-arm it. And whichever host you use: **a killed or expired
waiter says nothing whatever about the run it was watching**, and the
notification's wording invites you to read it as a result. Never treat a kill
or an expiry as information — check `agent-gtd run-status <run_id>` directly.

**No `ScheduleWakeup` for dispatch.** The waiter (or Monitor) is sufficient. A
rough sense of how long a run *should* take is now used only for **expectation
setting** — sanity-checking that a run isn't wildly stalled — not for picking
poll intervals.

### Sweep live clones for unpushed commits — the only rescue window there is

An agent that commits its own work leaves the clone with a clean tree and a moved HEAD. If the worker's own commit then finds nothing staged and returns before pushing, those commits exist **only in that clone** — and the clone is torn down at **run exit**, not at re-dispatch. By the time you read a failure notification the work is already deleted. Three sessions lost completed, gate-green work to this on 2026-09-19; one run had 60 successful edits and a self-run gate at 936 tests passing.

So on any **unattended** run, sweep the live clones. This is not a tip or a belt-and-braces habit — while a worker-side guard is undeployed it is the only thing between a finished run and deletion, and it fires far more often than you would guess (three rescues in one evening on one board).

**A worker-side rescue does not retire the sweep.** As of agent-gtd-dispatch 2.0.x the worker commits and pushes abandoned work to the run's own branch before teardown, which covers any run whose worker reaches its own teardown. Three cases it cannot cover, and the sweep is the only thing watching them: a worker that never reaches teardown at all (SIGKILL, OOM, power loss, a wedged service, a clone orphaned between workspace creation and run registration); **the entire span of a live run**, since teardown-time protection by definition does nothing for the hours before teardown; and uncommitted work, which neither mechanism can push. Treat the rescue as making the sweep *quieter*, never as replacing it — and remember that a quiet watchdog and a dead one look identical, so print a heartbeat line per pass and treat its absence as the loop having died rather than the fleet being clean.

```bash
# Per host, derived from the registry — never a hand-maintained host list.
# BOTH layouts: monorepo runs clone at repos-*/, workspace runs nest one deeper.
for d in /home/dispatch/workspace/repos-*/ /home/dispatch/workspace/ws-*/*/; do
  [ -d "$d/.git" ] || continue
  b=$(sudo -n -u dispatch git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null) || continue
  case "$b" in feat/*) ;; *) continue ;; esac
  local_sha=$(sudo -n -u dispatch git -C "$d" rev-parse HEAD 2>/dev/null)
  remote_sha=$(sudo -n -u dispatch git -C "$d" ls-remote origin "refs/heads/$b" 2>/dev/null | cut -f1)
  [ "$local_sha" = "$remote_sha" ] && continue
  # Counts commits reachable from HEAD that no remote ref has. Needs no
  # baseline argument, so it cannot be wrong about which baseline to use.
  n=$(sudo -n -u dispatch git -C "$d" rev-list --count HEAD --not --remotes 2>/dev/null)
  [ "${n:-0}" -gt 0 ] && echo "UNPUSHED $d ($b, $n commit(s))"
done
```

**Walk both clone layouts.** A monorepo run clones to `repos-<project>-<runid>/`; a **workspace run nests one level deeper** at `ws-<runid>/<repo>/`, one directory per repo in `workspace_repos`. A glob of `workspace/*/` matches the workspace ROOT, where there is no `.git` at all, so every repo of every workspace dispatch is skipped — silently, because the sweep just finds nothing there. On a board whose projects are mostly workspaces that is most of the surface.

**Prefer `git rev-list --count HEAD --not --remotes` to any `<base>..HEAD` range.** The range form makes you choose a baseline, and every wrong choice fails quietly: the clone's `origin/main` is frozen at clone time, and a "compare to the real remote ref" fix still needs a fallback for a branch that does not exist remotely yet — which is exactly where the frozen ref crept back in twice. `--not --remotes` takes no baseline, so there is no baseline to get wrong.

**Authorise per REMOTE, not per project.** A workspace run has several remotes side by side in one run, so a check keyed on the project authorises one of them and silently ignores the rest. Log an unauthorised remote; never push to it.

**Two details that are easy to get wrong, both learned by getting them wrong:**

**Compare against the real remote ref, not the clone's `origin/main`.** A dispatch clone's `origin/main` is frozen at clone time, so `git rev-list --count origin/main..HEAD` counts commits that are *already safely pushed* — you get a permanent false positive and re-report the same work on every sweep. Use `git ls-remote origin refs/heads/<branch>`.

**Rescue-push with `--no-verify`.** This is a *feature branch* push of work whose own gate has already run, and it gets fully re-verified at merge. A pre-push coverage hook can be minutes; at a short sweep interval that is most of the duty cycle spent re-proving something.

**The push is free even when unnecessary.** If the worker has already pushed, git refuses with a ref-lock rejection rather than doing damage — so there is no reason to hesitate over whether a rescue is needed.

**Know what this does NOT cover: uncommitted work.** The sweep can only rescue commits. Work sitting in the working tree is invisible to it — and mid-run that is the *normal* state, while for a talos run at failure it is the *guaranteed* state, because the harness owns the commit and the agent is forbidden to make one. A live check on one run showed **zero commits and 31 modified files across two clones**: nothing for a sweep to push, and everything to lose. Treat the sweep as covering one of two failure shapes, not both, and do not let it create a false sense of completeness.

**What covers uncommitted work is the worker's own pre-teardown rescue, and you need to know its exact boundary** (verified against the code and the live fleet 2026-09-20; re-verify rather than trusting this paragraph, since it describes another repo's behaviour). `rescue_abandoned_work` lives in each run's `finally` block, so it fires on every path the worker itself reaches: clean completion, gate failure, agent non-zero exit, timeout, cancellation, and the generic exception handler. On a dirty tree it runs `git add -A`, then `git commit --no-verify`, then `git push --no-verify -u origin <branch>` — deliberately skipping hooks, because the work is incomplete by definition and would usually fail them, and a blocked commit yields no tree at all rather than a cleaner one. **It is not a force-push** and it only ever writes the run's own `feat/*` branch, so it is a retry of an access the worker already has.

**The hole is anything that never runs `finally`: SIGKILL, OOM, power loss, a wedged service.** For those the only backstop is a sweep, and a sweep sees commits only — so for talos lanes specifically, where uncommitted is the guaranteed state, that combination remains a genuine gap. Size an unattended wave against that, not against "there is a rescue."

**The shutdown path is the one to check after any dispatch-service change.** Until 2.1.0 (`b2f155b`), `lifespan` cancelled every in-flight run's task and returned without awaiting, so the loop tore down before any `finally` could run its awaits — the rescue silently did not fire, and **every deploy destroyed exactly the work it was written to save**. The mechanism reported success while the thing it protected was gone. That is the same silent shape as the frozen-ref bug below, and it is the reason to distrust "a rescue exists" as an answer: ask which shutdown paths reach it.

**A workspace project has one run and MANY clones — key the sweep on every repo, not one per project.** A workspace dispatch clones every entry in `workspace_repos` side by side, so unpushed work can sit in any of them, and a sweep scoped to "one remote per project" silently misses the rest of the surface. This is not hypothetical: a single wave routinely has items that touch only repo A and items that touch only repo B. Enumerate the project's `workspace_repos` and cover each remote. Fails in the quiet direction, so nothing tells you.

**Fear the silent direction.** This check fails in two ways and they are not symmetric. A sweep that re-reports already-safe work is *annoying*, so it gets noticed and fixed within minutes. A sweep that silently misses work *looks perfect* — a quiet watchdog and a correct one are indistinguishable until the night you needed it. Both known bugs here fail silently: the frozen `origin/main` (reads like a live reference, is a snapshot) and missing a clone layout (`repos-*` for monorepo runs versus nested `ws-*/*` for workspace runs — walk both). When in doubt, make this check noisier than feels necessary.

**The bounding rule for a sweep that runs unattended: it may only do what the worker was already going to do.** A rescue push sends a `feat/*` branch to a remote the dispatch worker already pushes `feat/<item-id>-*` branches to on its success path — so it is a *retry of an existing access*, not a new one. That is why it needs no new trust from a repo's owner, and three sessions reached that framing independently before adopting it. It also draws the line in the right place: if you ever want the sweep to push to `main`, or to a branch the worker would not have created, this rule says stop. That is exactly the property you want in something running at 2am with nobody watching.

**Rescuing someone else's run:** a rescue push to a `feat/*` branch creates nothing anyone has to accept. Every branch is reviewed against its merge-base before it touches main, so an unreviewed commit on a feature branch costs the owner nothing while a destroyed one costs the whole run. Push it and tell them. Never to `main`, never a force-push, never a branch that isn't `feat/*`.

### Repo bootstrapping for headless agents

Every repo that may be dispatched to a headless agent needs a CLAUDE.md and README.md
so the agent can orient quickly without burning turns exploring. If you're working in a
repo that's missing either, add a lean one:

- **CLAUDE.md**: Build/test commands, project structure summary, key patterns, where to
  put new code. Keep it under a page — just enough to skip the exploration phase.
- **README.md**: Dev setup instructions (install deps, env vars, run tests). The agent
  clones fresh every time and needs to get productive in one read.

Don't over-document. These files exist to eliminate the 15-turn exploration tax that
kills headless agent productivity.

### Talos engines: set the project `gate_command` (compound for workspace)

Talos self-verifies before it returns success — the project's `gate_command` **is** the definition of Done (talos runs it and exits 0 only on green), so a talos dispatch requires a non-empty `gate_command` on the GTD project.

For a **workspace (multi-repo)** project, that single command must gate every repo an item touches. Talos runs it via `/bin/sh -c`, so chain it (`cd`, `&&`, pipes all work):

```
cd repoA && <repoA gate> && cd ../repoB && <repoB gate>
```

Per-session lead responsibility: set/confirm the project's `gate_command` (via `update_project`) before dispatching a workspace item to a talos engine — it is not auto-derived. A missing gate is a rejected dispatch; a too-narrow gate (only some repos) is a silent false-Done.

**Hook unification — gates and commit hooks CHECK, agents FIX.** In repos we own and dispatch to, enforce the quality bar with **checkers, never fixers**, and run the *same* checker set at both surfaces: the git pre-commit hook (which is Claude-Code's entire enforcement surface — a failed commit is CC's retry trigger) AND `gate_command` (talos's surface). Ideally `gate_command` literally invokes the hook runner (`lefthook run pre-commit` / `pre-commit run --all-files`) so the two can't drift. A **fixer** hook (`ruff --fix`, `black`, `prettier`, `end-of-file-fixer`, `trailing-whitespace`) mutates files and exits non-zero on the first commit — which is fine for CC (its commit-retry loop absorbs it) but silently destroys a completed unit of work for the talos worker, which commits once. Converting fixers to their `--check` variants keeps CC's failed-commit trigger intact (the checker still fails the commit; the agent runs the formatter itself) while removing the mutation that breaks talos. If you land in a repo whose pre-commit config still uses fixers, migrate it to `--check` variants and fold them into that project's `gate_command` — same as fixing a missing `release.sh`.
