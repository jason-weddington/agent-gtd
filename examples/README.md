# Examples: steering and workflows for running dispatch

These are reference copies of the steering and workflow scripts we use to run Agent GTD's headless dispatch day to day. They are a starting point to copy and adapt, not a dependency: nothing in Agent GTD loads them, and you can change them freely.

| File | What it is |
|---|---|
| `steering/headless-dispatch.md` | Steering for the Claude Code session that drives dispatch: when to dispatch versus work inline, grooming items to Ready, picking a build engine, direct builds versus rollouts, event-driven monitoring with `--wait`, rescuing unpushed work from live clones, and bootstrapping a repo for headless agents. |
| `workflows/groom-to-ready.workflow.js` | A Claude Code Workflow that grooms one or more GTD items to dispatch-ready: a draft agent writes a structured spec grounded in the current code, two critics attack it (code grounding and spec rigour), and a synthesis pass folds their findings in and sets an honest readiness. It returns the specs and writes nothing to GTD. |
| `workflows/review-against-intent.workflow.js` | A Claude Code Workflow that reviews a landed multi-item wave against the intent it was groomed from. It verifies each item against its spec with file and line evidence, tries to refute each finding, then looks across items for gaps at the seams that per-item reviews cannot see. It returns one verdict (meets-intent, meets-with-gaps or does-not-meet) and writes nothing. |

## Prerequisites

You need an Agent GTD board with the `agent-gtd` MCP server registered in Claude Code and the `agent-gtd` CLI on your `PATH` (see the main README), plus at least one dispatch host running the `agent-gtd-dispatch` service. The workflows need a Claude Code version that has the `Workflow` tool.

## Using the steering

Claude Code loads every `.md` file in `~/.claude/rules/` into every session, so the simplest install is a copy:

```bash
mkdir -p ~/.claude/rules
cp examples/steering/headless-dispatch.md ~/.claude/rules/
```

To scope it to one project instead, paste it into that repo's `CLAUDE.md`. If you share it across people or machines, keep it in its own git repo and symlink it into `~/.claude/rules/` so everyone picks up edits.

## Using the workflows

Copy or symlink the scripts into `~/.claude/workflows/`, and Claude Code resolves them by name:

```bash
mkdir -p ~/.claude/workflows
cp examples/workflows/*.workflow.js ~/.claude/workflows/
```

Then ask the session to run one, or call it directly. Each script's header comment documents every argument; the minimal calls are:

```js
Workflow({name: "groom-to-ready", args: {
  context: "Project: <name>. Stack: <...>. Where to look: <dirs, docs>. Ground-truth facts: <...>",
  items: [{id: "<gtd item id>", slug: "short-name", title: "...", seed: "what the item should do"}],
}})

Workflow({name: "review-against-intent", args: {
  intent: "<the feature outcome, and where its decision record lives>",
  repos: [{name: "my-service", path: "/abs/path/to/my-service"}],
  landed: "my-service: <commit range or list>",
  items: [{id: "<gtd item id>", title: "...", repo: "my-service", commits: ["<sha>"]}],
}})
```

`groom-to-ready` returns `{finals: [spec, ...]}`. Review the specs, then write each one into GTD with the CLI, which keeps the large acceptance-criteria arrays out of your session's context: `agent-gtd update-item <id> --from-json spec.json --status ready`. Delete keys the item schema does not accept (such as `readiness`, `open_questions` and `grounding_notes`) before you pass the file. `review-against-intent` returns a verdict with evidence, fixes and ordered recommendations, which you turn into follow-up items.

## Adapting them

- **Build engines.** The engine lanes named in the steering (`claude-code`, `claude-code-sonnet`, `talos-*` and so on) are the ones our dispatch fleet runs. Replace the "Choosing a build engine" section with the engines your hosts actually offer and your own rules for which model fits which work.
- **Host layout.** The clone-sweep script in the steering assumes the dispatch service's default two-user layout, with the agent's workspace under `/home/dispatch/workspace/`. Change the paths if your hosts run single-user mode or a different workspace root.
- **Your own house rules.** Add anything your team has learned the hard way, such as cost rules, release discipline or repos that need special handling, as further sections or separate files in `~/.claude/rules/`. Keep steering that every session must follow before acting separate from reference material agents look up when they need it.
- **Specialising a workflow.** Both scripts are project-agnostic: the discipline is in the script, and the project specifics arrive in `args`. When a project needs a different critic or verification lens, copy the script under a new name and edit the lens prompts rather than piling options into the shared copy. Leaf agents can be pinned to a cheaper model; keep the stronger model for synthesis and adversarial passes.
- **Workspace projects.** For a GTD project in `workspace` mode, tell the groom workflow in `context` that build agents receive every repo in `workspace_repos`, and use repo-prefixed paths in `files_to_modify`. Otherwise the critics will scope cross-repo work wrongly.
