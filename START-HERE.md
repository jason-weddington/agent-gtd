# Start Here — Agent Onboarding Map

You are (probably) a coding agent setting up this system on a fresh machine.
This page is the map; each step links to the doc that owns it. Follow in order.

**The system is two repos:**

| Repo | What it is |
|---|---|
| [agent_gtd](https://github.com/jason-weddington/agent-gtd) (this repo) | The GTD app: FastAPI backend, React frontend, MCP server, dispatch client |
| [agent-gtd-dispatch](https://github.com/jason-weddington/agent-gtd-dispatch) | The dispatch worker: runs headless build agents on a host, called by the app over HTTP |

You can run the app alone (steps 1–2). Dispatch (steps 3–4) is what makes it a
factory.

## 0. Porting? Fork first

If you are standing up an internal port: fork **both** repos to your git host,
then rewrite one line — the protocol dependency pin in `pyproject.toml` — to
point at your fork. Exact instructions:
[README → Internal dependency](README.md#internal-dependency-agent-gtd-dispatch-protocol)
(Override form A). If you're just evaluating, skip this; the default pin
resolves from public GitHub anonymously.

## 1. App dev setup (this repo)

Follow [README → Prerequisites + Quick Start](README.md). Local mode needs no
database. Three traps the docs call out — believe them:

- **`.env` is NOT auto-loaded.** Export it: `set -a; source .env; set +a`
- **PostgreSQL 15+/16**: the role must *own* the database (`createdb -O`) —
  `GRANT ALL` is not enough. Working recipe in
  [docs/setup.md](docs/setup.md) (the deep-dive runbook).
- The seed user is **not** an admin — `agent-gtd promote-admin admin@local`.

Verify: `uv run pytest` green (no DB server needed), app up via `./start.sh`.

## 2. Multi-user mode + API keys (optional, needed for dispatch)

[docs/setup.md](docs/setup.md) covers Postgres mode, invite minting, and both
MCP client configurations (stdio and HTTP).

## 3. Dispatch host setup (second repo)

Clone `agent-gtd-dispatch` and follow
[docs/install.md](https://github.com/jason-weddington/agent-gtd-dispatch/blob/main/docs/install.md).

For a dev machine, use **single-user mode** — no service users, no sudoers:

```bash
sudo --preserve-env=DISPATCH_SINGLE_USER DISPATCH_SINGLE_USER=1 ./setup-dispatch-host.sh --dry-run   # preview
sudo --preserve-env=DISPATCH_SINGLE_USER DISPATCH_SINGLE_USER=1 ./setup-dispatch-host.sh             # apply
```

The installer is idempotent (re-run it to true-up a host) and mints the
`DISPATCH_API_KEY` for you, printing an ACTION REQUIRED banner. Read the
"Side effects on your account" subsection before the first run.

**Corporate / Bedrock environments:** if your hosts can't call the Anthropic
API directly, route the rollout planner (the LLM that builds dependency DAGs
for managed rollouts) through Amazon Bedrock — in the host's env file set:

```bash
DISPATCH_PLANNER_PROVIDER=bedrock
AWS_REGION=us-east-1        # required — the SDK does NOT read ~/.aws/config for region
# credentials via the standard AWS chain (AWS_PROFILE, instance role, etc.)
# optional: DISPATCH_PLANNER_BEDROCK_MODEL=us.anthropic.claude-sonnet-4-6  (regional/CRIS)
```

Default model is `global.anthropic.claude-sonnet-4-6`. In bedrock mode
`ANTHROPIC_API_KEY` is not required for the planner. Note the scope: this
covers the planner LLM call only — the build agents themselves run Claude
Code, authenticated separately in step 4.

## 4. Pair the two halves

[install.md → Authentication & pairing](https://github.com/jason-weddington/agent-gtd-dispatch/blob/main/docs/install.md#authentication--pairing)
covers all three credentials:

1. `CLAUDE_CODE_OAUTH_TOKEN` — authenticates the headless agent (`claude setup-token`)
2. `AGENT_GTD_API_KEY` — the host's credential *to* the app
3. `DISPATCH_API_KEY` — the app's credential *to* the host (minted in step 3;
   register it in the app's dispatch settings UI)

Verify end-to-end: create a project with a `git_origin`, add a trivial task
("comment on this task with your working directory"), dispatch it in build
mode, and watch the agent comment back.

## 5. How to actually run this thing

Setup gets you a working factory; the operating doctrine — lead sessions as
control plane, grooming, dispatch waves, monitoring, performance logging —
lives in the **Headless Dispatch Steering Guide** distributed alongside this
system (`headless-dispatch-steering.md`, with the reusable
`groom-to-ready.workflow.js` grooming workflow).

---

*This page, the READMEs, and the runbooks it links to were written, audited
against the code, and cold-read-tested by coding agents. If an instruction
fails on your machine, that's a bug — file it, don't route around it.*
