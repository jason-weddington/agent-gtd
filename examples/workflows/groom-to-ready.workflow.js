/**
 * groom-to-ready.workflow.js — reusable Claude Code Workflow script.
 *
 * Grooms one or more GTD items to dispatch-ready via draft → critic → synthesize,
 * grounding every acceptance criterion in the CURRENT codebase. Project-agnostic:
 * the universal grooming discipline is hardcoded; you supply project context and
 * the items at call time.
 *
 * USAGE (from a Claude Code session):
 *   Workflow({
 *     name: "groom-to-ready",   // resolves once this file is copied or symlinked into ~/.claude/workflows/
 *     args: {
 *       context: "Project: <name>. Stack: <...>. WHERE TO LOOK: <key dirs/files/docs>. " +
 *                "Ground-truth facts the agents should treat as authoritative: <...>",
 *       // optional: path to the project's seam-contract doc. The seam-check critic
 *       // reads it to ground temporal + structural seam verification. Omit → the
 *       // lens degrades to a first-principles seam check.
 *       seamDocPath: "docs/temporal-through-line.md",
 *       // optional: pinned CONTRACTS OF RECORD — an owner item's final spec, DDL,
 *       // wire types, shared constant names. Injected verbatim into the draft and
 *       // every critic lens; a conflict is a spec error to fix, not a disposition
 *       // to re-derive. String or array of strings (objects are JSON-stringified).
 *       contracts: "CREATE TABLE stats_daily (day date not null, views integer not null, ...)",
 *       // optional: ids or slugs of items that OWN shared artefacts (files, types,
 *       // DDL, helpers the other items consume). Present → the batch runs in TWO
 *       // phases: owners first, then the rest with each owner's FINAL spec appended
 *       // to `contracts`. Without this, consumer drafts each invent their own
 *       // incompatible version of the shared contract.
 *       owners: ["<gtd-uuid-of-the-owner-item>"],
 *       // optional: the design doc's numbered decisions. Present → one extra
 *       // coverage agent maps every decision to the item(s) whose ACs implement it,
 *       // so a decision that no item owns surfaces at groom time.
 *       decisions: [ { id: "D5", text: "uploaded_at is lazily filled via getInfo for non-PQ photos" } ],
 *       items: [
 *         { id: "<gtd-uuid>", slug: "short-slug", title: "<item title>",
 *           seed: "<the design intent / current state to verify / scope>",
 *           // optional, per-item steering for the critics:
 *           criticalConstraint: "<e.g. 'do NOT touch fileX (a rollout owns it)'>" }
 *       ]
 *     }
 *   })
 *
 * RETURNS: { finals: [ <SPEC per item> ] }, plus `coverage: { owned, unowned }`
 * when args.decisions was supplied. The control plane reviews each spec, then
 * writes it into GTD (update_item AC/files/scope + status), or keeps it `new`
 * with the blockers recorded if readiness != "ready". Unowned decisions are the
 * control plane's call: assign one to an item, or record it as out of scope in
 * the doc. Do NOT have the workflow write GTD directly — the review is the
 * checkpoint.
 *
 * COST: ~6 agents per item (1 draft + 4 critics + 1 synth), pipelined across
 * items, plus 1 coverage agent when args.decisions is set. An owner/consumer
 * split serializes the two phases, so wall-clock is roughly doubled.
 *
 * MODELS: draft + synthesize are pinned to Opus (capable enough, cheaper on usage);
 * only the critic lenses inherit the session model, so a Fable session spends Fable
 * exclusively on the adversarial pass that earns it.
 *
 * Notes: plain JS (no TS). No Date.now()/Math.random(). args may arrive stringified.
 */

export const meta = {
  name: 'groom-to-ready',
  description: 'Groom GTD items to dispatch-ready via draft→critic→synthesize, grounding every AC in the current codebase. Pass project context in args.context and the items (with seeds) in args.items.',
  phases: [
    { title: 'Draft (owners)', detail: 'draft the items that own shared files/types/DDL — their specs become the contract of record', model: 'opus' },
    { title: 'Critic (owners)', detail: 'the four critic lenses over each owner draft' },
    { title: 'Synthesize (owners)', detail: 'finalize each owner spec before any consumer is groomed', model: 'opus' },
    { title: 'Draft', detail: 'read the cited docs + actual repo, draft a code-grounded spec per item', model: 'opus' },
    { title: 'Critic', detail: 'code-grounding + concrete-by-default + seam-check + instrumentation lenses per draft' },
    { title: 'Synthesize', detail: 'fold critiques into a final spec with an honest readiness verdict', model: 'opus' },
    { title: 'Coverage', detail: 'map every numbered decision to the item(s) that own it; report the unowned ones', model: 'opus' },
  ],
}

const SPEC_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    item_id: { type: 'string' },
    title: { type: 'string' },
    readiness: { type: 'string', enum: ['ready', 'blocked-on-prereq', 'needs-decision'] },
    blocking_prereqs: { type: 'array', items: { type: 'string' } },
    acceptance_criteria: { type: 'array', items: { type: 'string' }, minItems: 1 },
    files_to_modify: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { path: { type: 'string' }, change: { type: 'string' } },
        required: ['path', 'change'],
      },
      minItems: 1,
    },
    scope_out: { type: 'array', items: { type: 'string' } },
    build_engine: { type: 'string' },
    commit_type: { type: 'string', enum: ['feat', 'fix', 'perf', 'refactor', 'test', 'docs', 'chore'] },
    open_questions: { type: 'array', items: { type: 'string' } },
    grounding_notes: { type: 'string' },
  },
  required: ['item_id', 'title', 'readiness', 'blocking_prereqs', 'acceptance_criteria', 'files_to_modify', 'scope_out', 'build_engine', 'commit_type', 'open_questions', 'grounding_notes'],
}

const CRITIQUE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    ready: { type: 'boolean' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          issue: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'issue', 'fix'],
      },
    },
  },
  required: ['lens', 'ready', 'findings'],
}

const COVERAGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    owned: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          decision: { type: 'string' },
          items: { type: 'array', items: { type: 'string' } },
          evidence: { type: 'string' },
        },
        required: ['decision', 'items', 'evidence'],
      },
    },
    unowned: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['owned', 'unowned', 'notes'],
}

const UNIVERSAL = [
  'You are GROOMING a GTD item to dispatch-ready. You are NOT implementing it. Do NOT modify any files; read only.',
  '',
  'CARDINAL RULE: ground every claim in the CURRENT codebase. Design docs may be ahead of (or behind) reality — a doc claim is a claim to VERIFY by opening the file. Before an AC says "replace X with Y", confirm BOTH that X exists where claimed AND that Y exists. If a prerequisite the item depends on does not exist yet, that is the single most important thing to report.',
  '',
  'HONEST READINESS (the readiness field):',
  '- "ready" — every prerequisite exists in the code today and a build agent could one-shot it.',
  '- "blocked-on-prereq" — depends on code that does NOT exist yet; list exactly what is missing in blocking_prereqs. Still produce the best AC you can, but be explicit it cannot dispatch until the prereq lands.',
  '- "needs-decision" — a real design ambiguity needs the human before grooming can finish.',
  'Do NOT inflate readiness. A confident "ready" against a phantom API is the worst possible outcome — it sends a build agent to implement against something that is not there.',
  '',
  'QUALITY BAR (concrete-by-default): enums are enumerated with members + semantics; formulas/constants are pinned to literals (a starting value, never "an appropriate value"); EVERY files_to_modify path and EVERY symbol/function/schema an AC names is verified by opening the file; no "appropriate"/"correct"/"as needed" acceptance criteria — each must be a testable assertion; end grounding_notes with a "soft values / deferrals" line listing anything not pinned.',
  '',
  'build_engine convention: prefer "talos-glm-flash" for anything a Sonnet-class model would one-shot from a groomed spec (mirror, polish, integration, well-scoped execution); "talos-glm" for novel, cross-package, or design-heavy work; an Anthropic lane ("claude-code-sonnet", "claude-code") only when the task needs the Claude Code tool surface or the context you were given says so.',
  'commit_type convention: the conventional-commit type the squash commit will carry; it drives the changelog and version bump, and plan_rollout refuses items without it. feat = adds or changes something a user, operator or calling agent can observe (endpoint, CLI verb, MCP tool, config option, UI, behaviour); fix = corrects wrong behaviour; perf = same behaviour, faster or cheaper; refactor = no observable change; test = only tests or fixtures; docs = only documentation; chore = anything else (deps, build, tooling). A change someone using the project could notice is feat or fix, never chore.',
].join('\n')

const ARGS = typeof args === 'string' ? JSON.parse(args) : args
const ITEMS = Array.isArray(ARGS) ? ARGS : (ARGS && ARGS.items)
if (!Array.isArray(ITEMS)) {
  throw new Error('groom-to-ready: expected args.items array, got: ' + JSON.stringify(args).slice(0, 200))
}
const CONTEXT = ARGS && ARGS.context ? String(ARGS.context) : ''
const BASE = CONTEXT
  ? UNIVERSAL + '\n\n## Project context (where to look, conventions, ground-truth facts to treat as authoritative)\n' + CONTEXT
  : UNIVERSAL

// Normalize a string | array | object arg into a list of non-empty text blocks.
const asBlocks = (v) => (v == null ? [] : (Array.isArray(v) ? v : [v]))
  .map((x) => (typeof x === 'string' ? x : JSON.stringify(x, null, 2)))
  .filter((s) => s && s.trim())

// ---- Contracts of record (args.contracts + any owner spec from phase 1) ----
const PINNED = asBlocks(ARGS && ARGS.contracts)

const CONTRACT_RULE = [
  '## CONTRACTS OF RECORD — pinned, do NOT re-derive',
  'The text below is authoritative for every artefact SHARED across this batch: file names, type/interface names, constant names, function signatures (including positional-vs-object argument shape), DDL table + column names and types, wire field names, enum members and literal values.',
  'Use those names VERBATIM in acceptance_criteria and files_to_modify. If the repo, a design doc, your own draft or a critic finding disagrees with a pinned contract, that is a SPEC ERROR to correct in favour of the contract — not a disposition to re-derive and not an open_question. The single exception: a pinned contract that is impossible against the current code is a genuine conflict — say exactly why in grounding_notes and set readiness to "needs-decision".',
].join('\n')

const sharedWith = (extra) => {
  const blocks = PINNED.concat(extra || [])
  return blocks.length ? BASE + '\n\n' + CONTRACT_RULE + '\n\n' + blocks.join('\n\n---\n\n') : BASE
}

// Optional seam-contract doc for the seam-check lens. Workflow scripts have no
// filesystem access, so we pass the PATH and let the (tool-capable) critic agent
// open it. Absent → the lens degrades to a first-principles seam check.
const SEAM_DOC_PATH = ARGS && ARGS.seamDocPath ? String(ARGS.seamDocPath) : ''
const SEAM_LENS_INTRO = SEAM_DOC_PATH
  ? `The project maintains a SEAM-CONTRACT doc at \`${SEAM_DOC_PATH}\` — READ IT FIRST (open the file) and ground every seam claim against its tables: which signal must cross each TEMPORAL seam (stage→stage over time) wired vs broken, and the STRUCTURAL couplings (change subsystem X → sibling Y must change). If this feature touches a seam the doc marks broken or at-risk, the spec MUST address or explicitly capture it.`
  : `This project supplied no seam-contract doc (args.seamDocPath). Do a best-effort seam check from first principles: for every seam this feature touches, open the code on BOTH sides.`

// ---- The draft → critic → synthesize pipeline, run once per phase ----------
const groomBatch = (items, SHARED, suffix) => pipeline(
  items,
  // ---- Stage 1: DRAFT ----
  (item) => agent(
    [
      SHARED,
      '',
      `## Item to groom: ${item.title || item.slug || item.id}`,
      `GTD id: ${item.id}${item.priority ? ` | priority: ${item.priority}` : ''}`,
      '',
      'Seed (the design intent / current state to verify / scope — this is intent to STRUCTURE and VERIFY, not ground truth about the code):',
      item.seed || '(none provided)',
      item.criticalConstraint ? `\nItem-specific constraint:\n${item.criticalConstraint}` : '',
      '',
      'TASK: Read the cited docs AND the actual repo. First determine readiness (do the prerequisites exist in the repo today?). Then produce the groomed spec: testable acceptance_criteria tied to real code; files_to_modify each verified to exist (or marked NEW); scope_out boundaries; build_engine; commit_type; blocking_prereqs (exact missing code, if any); open_questions (only genuine human decisions); grounding_notes citing the specific files you opened and what you found.',
    ].join('\n'),
    { label: `draft:${item.slug || item.id}`, phase: 'Draft' + suffix, schema: SPEC_SCHEMA, model: 'opus' },
  ),
  // ---- Stage 2: CRITIC (four parallel lenses) ----
  (draft, item) => parallel([
    () => agent(
      [
        SHARED,
        '',
        `LENS: code-grounding / reality-check. Review this DRAFT groomed spec for "${item.title || item.slug}".`,
        '',
        'DRAFT SPEC:',
        JSON.stringify(draft, null, 2),
        '',
        'Open the actual files. Verify: (1) the readiness verdict is honest — if it says "ready" but a named prerequisite is NOT in the repo, downgrade it and say so; (2) every files_to_modify path exists (or is correctly marked NEW); (3) every symbol/function/type/schema the ACs name actually exists with the implied signature; (4) the blocking_prereqs list is complete and accurate; (5) every file the spec tells the BUILD agent to read or port from exists INSIDE the repository being groomed — the build agent works from a fresh clone of this repo and nothing else, so a citation of a file on the lead\'s machine (a home directory, a sibling repo, a ~/.claude or ~/git path) is a phantom for the builder even though it opens fine for you; flag it and require the source be vendored into the repo or its needed text inlined into the AC; (6) if CONTRACTS OF RECORD were pinned above, every shared name/signature/column/field in this draft matches them verbatim — report each divergence as a critical finding with the pinned name as the fix. Flag phantom paths, wrong signatures, stale-design-doc assumptions. Set ready=true only if the spec is fully grounded AND its readiness verdict is honest.',
      ].join('\n'),
      { label: `critic:grounding:${item.slug || item.id}`, phase: 'Critic' + suffix, schema: CRITIQUE_SCHEMA },
    ),
    () => agent(
      [
        SHARED,
        '',
        `LENS: concrete-by-default / spec-rigor. Review this DRAFT groomed spec for "${item.title || item.slug}".`,
        '',
        'DRAFT SPEC:',
        JSON.stringify(draft, null, 2),
        '',
        'Find every place the spec is soft where it must be concrete: an enum member missing or its semantics unstated; a constant/format left as prose instead of a literal; an AC using "appropriate"/"correct"/"as needed" instead of a testable assertion; a missing test for a stated behavior; a missing soft-values/deferrals note. If CONTRACTS OF RECORD were pinned above, treat any shared name the draft restates loosely (a paraphrased type name, a re-invented constant, a signature in a different shape) as a rigor defect and give the pinned form as the fix. Two self-consistency checks: (a) if the spec says existing tests or files stay unchanged or byte-identical, cross-check that promise against every edit its OWN ACs force (a new required parameter, a renamed field, a bumped version constant, a changed default) and report each contradiction with the fix (allow-list the forced edit explicitly); (b) if the item snapshots or publishes a contract another consumer reads (golden fixtures, schemas, vendored files, a contract README), check that it encodes every behaviour rule that the CONTRACTS OF RECORD, the DECISIONS, or sibling items in this batch introduce, as both an example and a stated invariant; a rule that lives only in prose docs or in a sibling spec, but not in the published artifact, is a finding. For each finding give the EXACT fix. Set ready=true only if a build agent could one-shot this with zero design guesses (assuming prereqs are met).',
      ].join('\n'),
      { label: `critic:rigor:${item.slug || item.id}`, phase: 'Critic' + suffix, schema: CRITIQUE_SCHEMA },
    ),
    () => agent(
      [
        SHARED,
        '',
        `LENS: temporal + structural SEAM-CHECK. Review this DRAFT groomed spec for "${item.title || item.slug}".`,
        SEAM_LENS_INTRO,
        '',
        'DRAFT SPEC:',
        JSON.stringify(draft, null, 2),
        '',
        'The recurring failure this catches: a feature built into ONE surface that silently breaks a SEAM to another, so it passes its own gate yet is broken end-to-end. Check BOTH axes:',
        '(1) TEMPORAL (across journey stages over time): for every signal this feature CONSUMES from an earlier stage, does the spec confirm the upstream WRITE exists AND is read here? For every signal it PRODUCES that a later stage depends on, is there a real consumer that the value survives to? A required field with no downstream consumer, or an emitter that persists nothing, is a seam break.',
        '(2) STRUCTURAL (across co-existing subsystems at one moment): when this feature changes one subsystem, which SIBLING subsystem must change with it to stay coherent? Watch for: a volume/number change that must also reshape a structural shell; an invariant that must hold at EVERY emit/render surface, not just the one the spec touches; and DRIFT between a thing and its parallel twin — a local harness vs the prod path it must mirror, a flag-gated/dead code path vs the live one, a client body vs the server schema.',
        'For each seam the feature touches, the spec must PROVE it wired on both ends (cite the code) or explicitly capture the gap. Report every unproven seam as a finding with the exact both-ends fix. Set ready=true only if every seam the feature touches is proven on both ends or its gap is captured.',
      ].join('\n'),
      { label: `critic:seams:${item.slug || item.id}`, phase: 'Critic' + suffix, schema: CRITIQUE_SCHEMA },
    ),
    () => agent(
      [
        SHARED,
        '',
        `LENS: instrumentation / observability. Review this DRAFT groomed spec for "${item.title || item.slug}".`,
        '',
        'DRAFT SPEC:',
        JSON.stringify(draft, null, 2),
        '',
        'The failure this catches: critical-path code that ships correct-looking logic but NO way to see, post-hoc, whether it did the right thing on a real input no test covered. A test proves the logic for its cases; production runs on inputs no test covers. So for any change that shapes a user-facing OUTCOME or a load-bearing DECISION, the spec must require the instrumentation to verify it in the wild. Ask: (1) does the spec name a log/event/metric that would let someone confirm post-hoc this did the right thing on an untested input — and surface WRONG behavior, not merely record that it ran? (2) does it log the DECISION (the branch taken + the inputs that drove it), not just the outcome? (3) where the code is correct-by-construction (an invariant that "cannot" breach), is there a runtime AUDIT that logs a violation if it ever does — the tripwire that construction regressed? (4) is it structured/queryable (not free-text console noise), and for LLM calls cost-aware (token/latency/cache)? If the change is NOT on a critical path (pure refactor, test-only, cosmetic, internal tooling), say so and pass. Otherwise give the exact log/event/metric to add for each gap. Set ready=true only if a reviewer could confirm this working in prod from its telemetry alone.',
      ].join('\n'),
      { label: `critic:instrumentation:${item.slug || item.id}`, phase: 'Critic' + suffix, schema: CRITIQUE_SCHEMA },
    ),
  ]).then((critiques) => ({ draft, item, critiques: critiques.filter(Boolean) })),
  // ---- Stage 3: SYNTHESIZE ----
  (bundle) => agent(
    [
      SHARED,
      '',
      `## Finalize the dispatch-ready spec for "${bundle.item.title || bundle.item.slug}" (id ${bundle.item.id})`,
      '',
      'DRAFT:',
      JSON.stringify(bundle.draft, null, 2),
      '',
      'CRITIC FINDINGS (apply every actionable one; re-open any file a critic flagged to confirm the correction):',
      JSON.stringify(bundle.critiques, null, 2),
      '',
      'Produce the FINAL spec. acceptance_criteria testable + tied to verified code; files_to_modify confirmed (mark NEW clearly); scope_out explicit; build_engine set; commit_type set; item_id = the GTD id above. Every shared name covered by a pinned CONTRACT OF RECORD appears verbatim. Set readiness honestly per the rules: "ready" only if all prereqs exist in the repo today; otherwise "blocked-on-prereq" with the exact missing code in blocking_prereqs. open_questions empty unless a real human decision remains. grounding_notes: what you verified + the readiness rationale + a soft-values/deferrals line.',
    ].join('\n'),
    { label: `synth:${bundle.item.slug || bundle.item.id}`, phase: 'Synthesize' + suffix, schema: SPEC_SCHEMA, model: 'opus' },
  ),
)

// ---- Owner-first phasing ---------------------------------------------------
// An OWNER item creates the shared files/types/DDL/helpers the others consume.
// Groomed flat, each consumer invents its own incompatible version of that
// contract, so owners run first and their FINAL specs become the
// contract of record for everyone else.
const OWNER_KEYS = new Set(asBlocks(ARGS && ARGS.owners).map((s) => s.trim()))
const isOwner = (item) => OWNER_KEYS.size > 0 && (OWNER_KEYS.has(String(item.id)) || OWNER_KEYS.has(String(item.slug || '')))
const OWNER_ITEMS = ITEMS.filter(isOwner)
const REST_ITEMS = ITEMS.filter((item) => !isOwner(item))

const results = new Array(ITEMS.length)
let ownerFinals = []
if (OWNER_ITEMS.length) {
  log(`Phase 1: grooming ${OWNER_ITEMS.length} contract-owner item(s) first`)
  ownerFinals = await groomBatch(OWNER_ITEMS, sharedWith([]), ' (owners)')
  OWNER_ITEMS.forEach((item, i) => { results[ITEMS.indexOf(item)] = ownerFinals[i] })
}
const ownerContracts = ownerFinals.filter(Boolean).map((spec) => [
  `OWNER ITEM FINAL SPEC — "${spec.title || spec.item_id}". This is the contract of record for every shared artefact it creates; consumers match its names exactly.`,
  JSON.stringify(spec, null, 2),
].join('\n'))

if (REST_ITEMS.length) {
  if (OWNER_ITEMS.length) log(`Phase 2: grooming ${REST_ITEMS.length} consumer item(s) against the owner specs`)
  const restFinals = await groomBatch(REST_ITEMS, sharedWith(ownerContracts), '')
  REST_ITEMS.forEach((item, i) => { results[ITEMS.indexOf(item)] = restFinals[i] })
}

const finals = results.filter(Boolean)

// ---- Decision coverage -----------------------------------------------------
// Per-item critics verify a spec against the repo and the doc section that item
// cites; none of them can see that a numbered decision maps to NO item.
const DECISIONS = asBlocks(ARGS && ARGS.decisions).length
  ? (Array.isArray(ARGS.decisions) ? ARGS.decisions : [ARGS.decisions])
    .map((d, i) => (typeof d === 'string'
      ? { id: `D${i + 1}`, text: d }
      : { id: String((d && d.id) || `D${i + 1}`), text: String((d && d.text) || '') }))
    .filter((d) => d.text.trim())
  : []

let coverage = null
if (DECISIONS.length && finals.length) {
  coverage = await agent(
    [
      sharedWith(ownerContracts),
      '',
      'LENS: DECISION COVERAGE. You are not reviewing any single spec — you are checking that the BATCH covers the decisions of record.',
      '',
      'DECISIONS OF RECORD:',
      JSON.stringify(DECISIONS, null, 2),
      '',
      'FINAL GROOMED SPECS:',
      JSON.stringify(finals, null, 2),
      '',
      'TASK: For every decision, find the item(s) whose acceptance_criteria actually IMPLEMENT it and list their item_ids in `owned`, with one line of `evidence` quoting the AC that carries it. A decision is owned only if an AC would fail review when the decision is not honoured — an item that merely touches the same file, or mentions the topic in grounding_notes or scope_out, does NOT own it. Anything with no such item goes in `unowned`, quoted enough that the control plane can act on it.',
      'Hunt hardest for the shapes that hide: a decision whose implementation falls BETWEEN two items so each one reasonably assumed the other had it; a field or capability that an earlier reconciliation pass dropped from the wire while making the specs consistent; a decision the doc states outside the API-surface section that every item therefore skipped. Open the repo to check whether an apparently unowned decision is already implemented today — if it is, say so in `notes` rather than calling it unowned.',
      '`notes`: anything the control plane must weigh when assigning the unowned ones, including decisions that look owned but only weakly.',
    ].join('\n'),
    { label: 'coverage:decisions', phase: 'Coverage', schema: COVERAGE_SCHEMA, model: 'opus' },
  )
}

return coverage ? { finals, coverage } : { finals }
