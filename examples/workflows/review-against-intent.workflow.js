/**
 * review-against-intent.workflow.js — reusable Claude Code Workflow script.
 *
 * The adversarial-REVIEW counterpart to groom-to-ready. Groom is forward
 * (intent -> spec); this is backward (intent + groomed specs -> verdict on what
 * LANDED). It verifies that the code now on disk — across POSSIBLY MANY commits
 * and repos — actually satisfies each groomed acceptance criterion, respects the
 * scope_out boundaries, and delivers the overarching feature intent, INCLUDING
 * the integration gaps that no single item owned.
 *
 * Use it for complex features / refactors that shipped as a multi-item wave,
 * where a single-agent review would miss cross-item seams or rubber-stamp an
 * agent's self-report. It does NOT trust dispatch comments — every verdict is
 * re-grounded in the actual files + commit diffs.
 *
 * USAGE (from a Claude Code session):
 *   Workflow({
 *     name: "review-against-intent",   // resolves once this file is copied or symlinked into ~/.claude/workflows/
 *     args: {
 *       intent: "Feature intent + where the decision-of-record lives. e.g. " +
 *               "'local mode = an auto-spawned no-auth SQLite singleton " +
 *               "of the web service; MCP is a thin HttpBackend everywhere.' " +
 *               "State the user-visible outcome the union of items must deliver.",
 *       repos: [ { name: "my-repo", path: "/path/to/my-repo" },
 *                { name: "web-service", path: "/path/to/web-service" } ],
 *       landed: "Commits/ranges that landed, per repo, so agents can read the diffs. " +
 *               "e.g. 'my-service: 8e06637,dc0c5c5,ec840bb,14ff626 (or base..main); " +
 *               "web-service: 8e06637,bae1678'. Agents git-show these + read files on main.",
 *       // optional: path to the project's seam-contract doc. The journey-seam-trace
 *       // integration lens reads it to check the landed change didn't break a
 *       // temporal/structural seam. Omit → the lens traces seams from first principles.
 *       seamDocPath: "docs/temporal-through-line.md",
 *       items: [
 *         { id: "<gtd-uuid-or-slug>", title: "...", repo: "my-service",
 *           acceptance_criteria: ["..."], files_to_modify: [{path, change}], scope_out: ["..."],
 *           commits: ["dc0c5c5"] (optional per-item commit hints) }
 *       ]
 *     }
 *   })
 *
 * RETURNS: a structured verdict report (see FINAL_SCHEMA). The control plane
 * reads it and decides what to fix / re-dispatch. The workflow writes nothing.
 *
 * COST: ~ (2 * N items) verify+refute, then 6 agents (5 integration lenses +
 * synthesis). Pipelined across items; one barrier before integration.
 *
 * MODELS: integrate + synthesize are pinned to Opus (capable enough, cheaper on
 * usage); the verify + refute passes inherit the session model, so a Fable
 * session spends Fable on the adversarial per-item grounding that earns it.
 *
 * Notes: plain JS (no TS). No Date.now()/Math.random(). args may arrive stringified.
 */

export const meta = {
  name: 'review-against-intent',
  description: 'Adversarially review what LANDED (across multiple commits/repos) against the groomed intent + per-item specs: per-AC verdicts grounded in real code, a refute pass, cross-item integration-gap hunting, and a synthesized verdict report.',
  phases: [
    { title: 'Verify', detail: 'per item: open the landed files + commit diffs, verdict every AC with file:line evidence' },
    { title: 'Refute', detail: 'adversarially try to OVERTURN each unmet / partial / scope-violation finding' },
    { title: 'Integrate', detail: 'cross-item union + intent completeness + regression + temporal/structural seam trace + instrumentation trace', model: 'opus' },
    { title: 'Synthesize', detail: 'fold verified findings into a single verdict report', model: 'opus' },
  ],
}

// ---- Schemas ---------------------------------------------------------------

const AC_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    item_id: { type: 'string' },
    ac_verdicts: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ac: { type: 'string' }, // short paraphrase of the acceptance criterion
          verdict: { type: 'string', enum: ['met', 'partial', 'unmet', 'cannot-verify'] },
          evidence: { type: 'string' }, // file:line or commit + what was found (or what's missing)
        },
        required: ['ac', 'verdict', 'evidence'],
      },
    },
    scope_violations: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          file: { type: 'string' },
          issue: { type: 'string' }, // what landed that scope_out said not to touch
        },
        required: ['file', 'issue'],
      },
    },
    item_summary: { type: 'string' },
  },
  required: ['item_id', 'ac_verdicts', 'scope_violations', 'item_summary'],
}

const REFUTE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    claim: { type: 'string' },
    upheld: { type: 'boolean' }, // true = the finding STANDS after a real refute attempt; false = overturned
    reason: { type: 'string' }, // the file:line / counter-evidence that upholds or overturns it
  },
  required: ['claim', 'upheld', 'reason'],
}

const INTEGRATION_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    intent_met: { type: 'string', enum: ['yes', 'partial', 'no'] },
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          gap: { type: 'string' },
          evidence: { type: 'string' }, // grounded in code — the seam that doesn't connect
          counter_evidence_considered: { type: 'string' }, // what you checked before asserting the gap is real
        },
        required: ['severity', 'gap', 'evidence', 'counter_evidence_considered'],
      },
    },
    notes: { type: 'string' },
  },
  required: ['lens', 'intent_met', 'gaps', 'notes'],
}

const FINAL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    overall_verdict: { type: 'string', enum: ['meets-intent', 'meets-with-gaps', 'does-not-meet'] },
    summary: { type: 'string' },
    confirmed_met: { type: 'array', items: { type: 'string' } },
    unmet_or_partial: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          item_id: { type: 'string' },
          finding: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          fix: { type: 'string' },
        },
        required: ['item_id', 'finding', 'severity', 'fix'],
      },
    },
    integration_gaps: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          gap: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'gap', 'fix'],
      },
    },
    scope_violations: { type: 'array', items: { type: 'string' } },
    recommendations: { type: 'array', items: { type: 'string' } },
  },
  required: ['overall_verdict', 'summary', 'confirmed_met', 'unmet_or_partial', 'integration_gaps', 'scope_violations', 'recommendations'],
}

// ---- Shared preamble -------------------------------------------------------

const UNIVERSAL = [
  'You are REVIEWING work that already LANDED, against the groomed spec and the overarching feature intent. You are NOT implementing anything. Read only — do not modify files.',
  '',
  'CARDINAL RULE: ground every verdict in the ACTUAL code as it exists NOW (on the current branch) plus the cited commit diffs. Open the files. Read the diffs with git. DO NOT trust the build agent\'s self-report or dispatch comments — they are claims to verify, not evidence. A "met" verdict REQUIRES you to cite the file:line (or commit) that satisfies the criterion. If you cannot find the satisfying code, the verdict is "unmet" or "cannot-verify", never "met".',
  '',
  'ADVERSARIAL BIAS: actively hunt for (a) an acceptance criterion that is claimed-done but is not actually in the code; (b) a scope_out boundary that was crossed (a file changed that the spec said not to touch); (c) a regression or broken seam introduced by the change. Default to skepticism: a confident "everything landed fine" that misses a real gap is the worst outcome — that is the entire reason this review exists instead of a single rubber-stamp pass.',
  '',
  'BUILDS AND TESTS ARE ISOLATED: reading code and git history is the default. If you do compile or run tests, NEVER do it in the repo checkout you were given, or with its build output dir (target/, node_modules/.cache, dist/, .venv): other agents in this review run there concurrently, and the lead\'s own gate runs there afterwards, so a shared build dir leaves stale artifacts that break the next build. Make your own worktree OUTSIDE /tmp (it is a small tmpfs and a full one truncates this workflow\'s output): `git worktree add ~/.cache/review-against-intent/<repo>-<short-label> <commit>`, give it its own build dir (e.g. CARGO_TARGET_DIR inside that worktree), and remove it with `git worktree remove --force` before you return.',
  '',
  'EVIDENCE QUALITY: cite concrete locations (path:line, symbol name, or commit hash), not vibes. "Looks implemented" is not evidence; "ensure_daemon() at daemon.py:210 spawns kb-service serve --port, satisfying the spawn AC" is.',
].join('\n')

// ---- Arg parsing -----------------------------------------------------------

const ARGS = typeof args === 'string' ? JSON.parse(args) : args
if (!ARGS || typeof ARGS !== 'object') {
  throw new Error('review-against-intent: expected args object with {intent, items, repos, landed}')
}
const INTENT = ARGS.intent ? String(ARGS.intent) : '(no intent provided)'
const ITEMS = Array.isArray(ARGS.items) ? ARGS.items : null
if (!ITEMS) {
  throw new Error('review-against-intent: expected args.items array, got: ' + JSON.stringify(ARGS).slice(0, 200))
}
const REPOS = Array.isArray(ARGS.repos) ? ARGS.repos : []
const LANDED = ARGS.landed ? String(ARGS.landed) : '(no commit list provided — inspect current branch state)'

// Optional seam-contract doc for the journey-seam-trace integration lens. Workflow
// scripts have no filesystem access, so we pass the PATH and let the (tool-capable)
// lens agent open it. Absent → the lens traces seams from first principles.
const SEAM_DOC_PATH = ARGS.seamDocPath ? String(ARGS.seamDocPath) : ''
const SEAM_LENS_INTRO = SEAM_DOC_PATH
  ? `The project maintains a SEAM-CONTRACT doc at \`${SEAM_DOC_PATH}\` — READ IT FIRST (open the file) and use its seam tables (TEMPORAL stage→stage crossings; STRUCTURAL subsystem couplings) as the map of which seams exist and which are already known-broken. Trace every seam this landed change touches against it.`
  : `This project supplied no seam-contract doc (args.seamDocPath). Trace seams from first principles: for each seam the change touches, open the code on BOTH sides.`

const REPO_BLOCK = REPOS.length
  ? 'REPOS (read all from disk):\n' + REPOS.map((r) => `- ${r.name || '?'}: ${r.path || '?'}`).join('\n')
  : '(no repo paths provided)'

const SHARED = [
  UNIVERSAL,
  '',
  '## Feature intent (the user-visible outcome the UNION of items must deliver)',
  INTENT,
  '',
  '## ' + REPO_BLOCK,
  '',
  '## What landed (git-show these commits / read the diffs to see what actually changed)',
  LANDED,
].join('\n')

// ---- Phase Verify + Refute (pipelined per item) ----------------------------

const itemResults = await pipeline(
  ITEMS,
  // Stage 1: VERIFY — per-AC verdict grounded in landed code
  (item) => {
    const hasInlineSpec = Array.isArray(item.acceptance_criteria) && item.acceptance_criteria.length > 0
    // The groomed spec is either passed inline, or it lives in GTD and the agent
    // fetches it itself (keeps the control-plane args lean for large waves).
    const specBlock = hasInlineSpec
      ? [
          'ACCEPTANCE CRITERIA (verdict EACH one against the real code):',
          JSON.stringify(item.acceptance_criteria, null, 2),
          '',
          'FILES THE SPEC EXPECTED TO CHANGE:',
          JSON.stringify(item.files_to_modify || [], null, 2),
          '',
          'SCOPE_OUT (these must NOT have been touched — flag any that were):',
          JSON.stringify(item.scope_out || [], null, 2),
        ].join('\n')
      : [
          'FETCH THE GROOMED SPEC FROM GTD: the acceptance_criteria, files_to_modify, and',
          `scope_out for this item live in GTD item ${item.id}` + (item.gtd_board ? ` on board ${item.gtd_board}` : '') + '.',
          'Load the get_item tool first with ToolSearch query "select:mcp__agent-gtd__get_item",',
          `then call it with item_id="${item.id}". Read the returned acceptance_criteria,`,
          'files_to_modify, and scope_out arrays — those are the spec you verify against.',
          'If the fetch fails, set every verdict to "cannot-verify" and say so in item_summary.',
        ].join('\n')
    return agent(
      [
        SHARED,
        '',
        `## Verify item: ${item.title || item.id} (repo: ${item.repo || 'unspecified'})`,
        `item_id: ${item.id}`,
        item.commits ? `Cited commits for this item: ${JSON.stringify(item.commits)}` : '',
        '',
        specBlock,
        '',
        'TASK: For each acceptance criterion, open the relevant file(s) (and `git show` the cited commits) and assign a verdict — met / partial / unmet / cannot-verify — with concrete file:line or commit evidence. Then check every scope_out boundary against what actually changed and record any violation. Be specific and skeptical; a "met" needs a citation.',
      ].join('\n'),
      { label: `verify:${item.id}`, phase: 'Verify', schema: AC_VERDICT_SCHEMA },
    )
  },
  // Stage 2: REFUTE — adversarially try to overturn each non-"met" finding
  (verdict, item) => {
    const flagged = []
    for (const v of (verdict && verdict.ac_verdicts) || []) {
      if (v.verdict === 'unmet' || v.verdict === 'partial' || v.verdict === 'cannot-verify') {
        flagged.push(`[${item.id}] AC "${v.ac}" was judged ${v.verdict}: ${v.evidence}`)
      }
    }
    for (const sv of (verdict && verdict.scope_violations) || []) {
      flagged.push(`[${item.id}] scope violation in ${sv.file}: ${sv.issue}`)
    }
    if (!flagged.length) return { item, verdict, refutations: [] }
    return parallel(
      flagged.map((claim) => () => agent(
        [
          SHARED,
          '',
          `## Refute pass — try to OVERTURN this review finding for "${item.title || item.id}"`,
          '',
          'FINDING:',
          claim,
          '',
          'TASK: A first reviewer flagged this. Try HARD to prove it WRONG — open the files and search the WHOLE repo (and the other repos) for code that actually satisfies the criterion elsewhere (a different file, a renamed symbol, a sibling item that covered it, a commit the first reviewer did not read). Set upheld=true ONLY if, after a genuine search, the finding still stands (the satisfying code truly is absent / the boundary truly was crossed). Set upheld=false if you found the criterion is actually met (cite where). Default to upheld=true only when you genuinely cannot find satisfying evidence.',
        ].join('\n'),
        { label: `refute:${item.id}`, phase: 'Refute', schema: REFUTE_SCHEMA },
      )),
    ).then((refutations) => ({ item, verdict, refutations: refutations.filter(Boolean) }))
  },
)

// ---- Phase Integrate (barrier: needs ALL item results + intent together) ----

const RESULTS_DIGEST = JSON.stringify(
  itemResults.filter(Boolean).map((r) => ({
    item_id: r.item.id,
    title: r.item.title,
    ac_verdicts: r.verdict && r.verdict.ac_verdicts,
    scope_violations: r.verdict && r.verdict.scope_violations,
    refutations: r.refutations,
  })),
  null,
  2,
)

const INTEGRATION_LENSES = [
  {
    key: 'seam-coherence',
    prompt: 'LENS: cross-item SEAM coherence. The items shipped separately; verify they actually connect. For every hand-off between items (a contract one item produces and another consumes — endpoints, env vars, ports, file paths, function signatures, constants), open BOTH sides and confirm they match. Report any seam where producer and consumer disagree, or where a contract one item assumed was never actually shipped by another.',
  },
  {
    key: 'intent-completeness',
    prompt: 'LENS: intent COMPLETENESS. Re-read the feature intent. Ask: what would a user EXPECT from this feature that the union of items does NOT actually deliver? Hunt specifically for gaps that fall BETWEEN items — capability that no single item owned, so every item is individually "done" yet the feature is incomplete. (E.g. a "zero-config" intent where every item shipped but a required default was never set anywhere.) Then do it decision-by-decision: walk every numbered decision / explicit promise in the intent and its decision-of-record doc, name the landed item that implements it with file:line, and report any decision that no item owns — the most common shape is a decision stated outside the section each item cited, or a field dropped while the specs were reconciled with each other.',
  },
  {
    key: 'regression-and-scope',
    prompt: 'LENS: regression + scope drift across the whole change set. Did the union break something that previously worked (a now-orphaned caller, a deleted symbol still imported somewhere, a behavior change in a path the spec said to leave alone)? Aggregate the scope_violations the per-item reviewers found and judge whether any indicate real drift vs. benign. Check the OTHER repos for references to anything deleted here.',
  },
  {
    key: 'journey-seam-trace',
    prompt: [
      'LENS: temporal + structural JOURNEY-SEAM trace (distinct from the cross-item seam-coherence lens above — that checks wave-internal item↔item hand-offs; THIS checks the app\'s own journey seams).',
      SEAM_LENS_INTRO,
      'For every temporal or structural seam the LANDED change touches, re-ground it in the code as it exists NOW: (1) TEMPORAL (across journey stages over time) — if the change adds or uses a signal that must cross a stage→stage seam (a field written at one stage and read at a later one), confirm BOTH the upstream WRITE and the downstream READ actually landed and carry the value. A new field with no consumer, or a consumer of a value nothing writes, is a broken seam even though every item is individually "met". (2) STRUCTURAL (across co-existing subsystems) — if the change alters one subsystem, confirm the SIBLING subsystem that must stay coherent was ALSO updated: a volume/number change that should reshape a structural shell; an invariant that must hold at EVERY emit/render surface (not just the one touched); a local harness / dead-code path / client that must not drift from its prod / live / server twin. Report each seam the change touched but left broken or unproven on one end, grounded in file:line on both sides.',
    ].join('\n'),
  },
  {
    key: 'instrumentation-trace',
    prompt: 'LENS: instrumentation / observability of what LANDED. For the critical-path parts of this change (anything shaping a user-facing outcome or a load-bearing decision), verify the code actually emits the telemetry to confirm post-hoc it behaves correctly in production on inputs no test covered. Open the landed code: (1) is there a log/event/metric on the key DECISION (the branch taken + the inputs that drove it), not just the outcome? (2) where the change claims correct-by-construction, is there a runtime AUDIT that logs a violation if the invariant ever breaks — the tripwire that construction regressed? (3) is it structured/queryable (not free-text console noise), and for LLM calls cost-aware (token/latency/cache)? Report as gaps any critical-path decision that landed with NO way to observe it in the wild — a reviewer weeks from now should be able to answer "did this do the right thing for real users?" from telemetry alone. Pure-refactor / test-only / cosmetic changes: note and pass.',
  },
]

const integration = (await parallel(
  INTEGRATION_LENSES.map((lens) => () => agent(
    [
      SHARED,
      '',
      lens.prompt,
      '',
      'GROOMED ITEMS UNDER REVIEW (titles + their per-AC verdicts + refutations from the first pass):',
      RESULTS_DIGEST,
      '',
      'TASK: Ground every gap you report in the actual code — open the files on both sides of each seam. For each gap, fill counter_evidence_considered with what you checked before deciding the gap is real (so you do not cry wolf on something covered elsewhere). intent_met is your lens-level judgment of whether the feature meets its intent.',
    ].join('\n'),
    { label: `integrate:${lens.key}`, phase: 'Integrate', schema: INTEGRATION_SCHEMA, model: 'opus' },
  )),
)).filter(Boolean)

// ---- Phase Synthesize ------------------------------------------------------

const report = await agent(
  [
    UNIVERSAL,
    '',
    '## Synthesize the final review verdict',
    '',
    '## Feature intent',
    INTENT,
    '',
    'PER-ITEM VERDICTS + REFUTATIONS:',
    RESULTS_DIGEST,
    '',
    'CROSS-ITEM INTEGRATION FINDINGS:',
    JSON.stringify(integration, null, 2),
    '',
    'TASK: Produce ONE verdict report. Rules:',
    '- An AC finding counts as a real problem ONLY if its refutation upheld it (upheld=true) OR it had no refutation because it was already "met". Drop findings the refute pass overturned (upheld=false).',
    '- An integration gap counts only if it is grounded in code and survived its own counter_evidence_considered check; fold duplicates across lenses.',
    '- confirmed_met: the ACs/seams you are confident actually landed correctly.',
    '- unmet_or_partial: surviving per-item findings, each with item_id, severity, and a concrete fix.',
    '- integration_gaps: surviving cross-item gaps, each with severity + fix.',
    '- scope_violations: any real (non-overturned) boundary crossings.',
    '- overall_verdict: meets-intent (no critical/major problems), meets-with-gaps (works but has major findings), or does-not-meet (a critical AC or seam is broken).',
    '- recommendations: the ordered next actions (new GTD items / fixes) the control plane should take.',
    'Be honest and specific. The value of this report is catching what the individual dispatch reviews could not.',
  ].join('\n'),
  { label: 'synthesize', phase: 'Synthesize', schema: FINAL_SCHEMA, model: 'opus' },
)

return report
