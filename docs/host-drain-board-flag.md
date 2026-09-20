# Host drain, board-flag variant — taking a dispatch host out of rotation without deleting it

Status: proposed, 2026-09-20. Scope: `agent_gtd` only (no `agent-gtd-dispatch` change).

This is the **board-owned** variant of host drain: one nullable column on `dispatch_hosts` that the router respects. `docs/host-drain.md` proposes the **host-owned** variant — a sentinel file the host advertises on `/info`. The two designs disagree on exactly one question, ownership of the flag, and the section "Why this belongs in `agent_gtd`'s DB" below argues that side; the section "The honest cost" at the end concedes what the host-owned design is better at. Read them as a pair.

## The problem this solves

A dispatch-side bug shipped to all four hosts can only be fixed by `deploy.sh`, and `deploy.sh`'s per-host step is `sudo systemctl restart dispatch-api` (`agent-gtd-dispatch/deploy.sh:225`). A restart cancels every in-flight run's asyncio task (`main.py:284-293`) and then actively marks them failed on the way back up (`db.py:173-196`, `reconcile_orphans`). So with runs in flight you cannot deploy, and today the fleet almost always has runs in flight. The fix for the rollout re-adoption bug (`cb7491a`) has been sitting undeployable behind exactly this, with two more fixes queued behind it.

The missing primitive is small and specific: **a way to stop the board sending NEW work to a host, without touching the host.** Once a host stops receiving work it drains itself naturally, and when it reads idle you restart it in a moment when a restart costs nothing.

Everything else needed for a rolling fix already exists. `deploy.sh` is already serial, not parallel (`deploy.sh:250-252` is `for host in ${HOSTS}; do deploy_one "${host}"; done`), and it already has a single-host escape hatch — `DISPATCH_HOST=jason-precision ./deploy.sh` touches exactly one host (`deploy.sh:34-38`). Host selection already funnels through one function on the board (`pick_dispatch_host`, `services/dispatch_router.py:164`) with one production caller (`dispatch_worker.py:923`). The idle signal already exists and is honest: `/info`'s `active_runs` counts rollout manager loops as well as builds, because `_start_rollout_loop` registers its task in `_active_processes` (`main.py:2961-2964`), so `active_runs == 0` genuinely means "not even driving a rollout."

What is missing is one bit of state and one `if`.

## The design

**Add one nullable column to `dispatch_hosts`: `drain_reason TEXT`. NULL means the host accepts new work. Non-NULL means it does not, and the string says why. The auto-routing branch of `pick_dispatch_host` skips hosts with a non-NULL `drain_reason`. The pinned branch does not.**

That is the whole feature. Everything below is plumbing that one column through the surfaces that already exist, plus the operator procedure it enables.

### Why a nullable reason string rather than a boolean

A boolean answers "is this host taking work" and nothing else. The owner's own framing already asked for more than that: peer sessions "need to be able to SEE that a host is draining, and ideally why." A boolean gets you there only by adding a second column for the reason, at which point you have two columns that must agree — and two columns that can disagree is the beginning of a state machine.

A nullable TEXT is strictly one column, costs exactly one `ALTER TABLE` to add, and carries both facts in a form that cannot contradict itself: `drained = drain_reason is not None`. There is no valid state where a host is drained with no reason, or has a reason but is not drained.

It also has a second, less obvious payoff. The `NoCompatibleHostError` message is the only operator-facing explanation of a routing decision that exists anywhere in this system (`dispatch_router.py:69-86`, truncated into the run's error at `dispatch_worker.py:930-932`). Today, a host that is wedged, a host that is slow, and a host that is deliberately out of rotation all produce the same unhelpful skip reason. With a reason string, the error a failed dispatch leaves behind reads `pironman01: draining: deploying re-adoption fix (cb7491a)` — which is not a diagnostic you have to go and find, it is the diagnosis, already written down by the person who caused it.

### Why NOT an enum or a status column

`status TEXT NOT NULL DEFAULT 'active'` is the shape that turns into eight states. The moment the column can hold an arbitrary token, someone adds `'draining'` separate from `'drained'`, then `'maintenance'`, then `'quarantined'`, and now the router has a match statement and you own a lifecycle. Two states expressed as NULL / non-NULL cannot grow a third by accident — adding one requires a schema change and a visible argument about it. Keep the door shut.

### Why this belongs in `agent_gtd`'s DB and NOT on the host's `/info`

This is the sharpest call in the design, and there are four independent reasons, the first of which is decisive on its own.

**It cannot bootstrap.** A drain flag advertised by the host on `/info` is dispatch-side code. Shipping it requires `deploy.sh`, which requires restarting all four hosts, which is the operation the entire feature exists to avoid. The `/info` design is blocked by the exact deadlock it is meant to break. The board-side design is not: `agent_gtd` restarts do not kill agent processes on hosts — the board's status pollers die with the process and `reconcile_active_runs` rebuilds them at startup from `claude_runs.dispatch_host_url` (`dispatch_worker.py:510-614`). One board restart, once, buys unlimited host restarts afterwards.

**It fails in the wrong direction.** Drain state on `/info` is asserted by the host about itself, and the host you most need to hear from is the one that is broken. `jason-precision` is the live proof: it is wedged right now, listening on 8100 with a full accept backlog, `systemctl is-active` reporting `active`, and `/health` not answering from the host itself. The router already skips it under `_classify_info_failure` with the reason `"no /info response within 5s (host may be at capacity / saturated)"` (`dispatch_router.py:121-122`). The fleet has already accidentally drained a host, by the one mechanism that is indistinguishable from "the host is dead," with no operator record of why. A wedged host cannot tell you it is draining. The board can.

**`/info` is unauthenticated and has no write path.** Neither `info()` (`main.py:4331`) nor `health()` (`main.py:4324`) carries `Depends(_verify_api_key)`, unlike `/agents` (`main.py:4351-4352`). To set drain state on a host you would have to build a new authenticated mutation endpoint on the dispatch service — more code, on the side you cannot deploy.

**`/info` is not a cheap read.** Every request forks a subprocess: `main.py:4339` awaits `run_list_agents_script()`, which is a real `create_subprocess_exec` with its own 5s timeout (`agent_discovery.py:110-124`), against a router fetch timeout that is also 5.0s (`dispatch_router.py:94`, `:101`). Those being equal is already a latent nondeterminism. Hanging drain state off that path inherits the fragility for no gain.

### The honest cost

The strongest argument for the host-owned variant is that it converges: if a draining host is also unreachable, `/info` fails, the router skips it anyway, and every failure mode of the signal lands on "do not route here." A board-held flag has one failure mode with no such convergence — the board says drained, the host is actually fine and idle, and it sits out of rotation until someone notices the stale row. That is real, and it is the price of this design. The mitigation is not clever: the reason string is visible in the Settings host list, in `agent-gtd list-dispatch-hosts`, and in every peer session's `list_dispatch_hosts`, so a stale drain is a visible stale drain rather than a silent one. A host-owned flag is more robust *once deployed*; a board-owned flag is the one you can deploy.

The second real argument for host-ownership is that the truth is host-local — the deploy script is already SSHed in and can drop the flag and restart in the same session, with no window between them. Also true. The counter is that the flag is needed on the *other three* hosts, which that SSH session is not touching, and on a host that has stopped answering, which no SSH session can reliably reach.

The remaining counter-arguments are weaker. Host-asserted state would survive loss of the board's DB, and would let a host drain *itself* — on SIGTERM, say, or when it detects its own trouble. Neither is wanted here. The operator is the one who knows a fix is needed, and the failure mode being designed against is a host that is too broken to have opinions about itself.

A fair reading is that the two designs are not exclusive and the ordering is what matters: ship the board flag first because it is the one that works today, and if the host-owned sentinel is still wanted afterwards, it rides out on the very first rolling deploy the board flag makes possible.

### Why the filter goes in the router, not in the caller

`pick_dispatch_host` takes `hosts` as an argument, so the drained hosts could simply be filtered out by `execute_run` before the call. Don't. Filtering in the caller throws away the reason string — the skipped host vanishes from `NoCompatibleHostError.hosts_checked` and the run's failure message loses the one piece of information worth having. Filter inside the router, where the skip list is built.

## Exact changes

Ten files, most of them one to three lines. Ordered by how load-bearing they are.

### 1. The router — the actual feature (`services/dispatch_router.py`)

In the auto-mode candidate loop that begins at `dispatch_router.py:269`, insert three lines as the **first** check in the body, above the `exclude_urls` check:

```python
for host, info in zip(hosts, infos, strict=False):
    host_label = host.get("label") or host.get("url", "unknown")
    if host.get("drain_reason"):                                      # NEW
        skipped.append(                                               # NEW
            {"host": host_label, "reason": f"draining: {host['drain_reason']}"}
        )                                                             # NEW
        continue                                                      # NEW
    if exclude_urls and host.get("url") in exclude_urls:
        ...
```

First in the loop, deliberately: a drained host is very often also unreachable (that is frequently why you drained it), and `draining: wedged, event loop blocked` is a strictly better operator message than `unreachable (connection refused)`. Intent beats symptom.

The pinned branch (`dispatch_router.py:205-262`) is **not** changed. Zero lines. That is how you dispatch a test build at the host you just fixed — `dispatch_item(dispatch_host_id=...)` reaches a drained host and still enforces engine, agent and capacity, exactly as it does today. The best property of putting the check only in the auto branch is that keeping pinning working requires writing nothing at all. The second pin-only capacity gate on the HTTP route (`routes/dispatch_routes.py:386-411`, the 409) is likewise untouched, for the same reason.

Drained hosts are still probed by `_gather_host_info` under this shape, which wastes a concurrent `/info` fetch. Leave it. The gather is concurrent and already bounded at 5s, so the wall-clock cost is unchanged from today, and pre-filtering the list means `zip(hosts, infos)` no longer lines up and the skip list has to be assembled in two places. Not worth four extra lines. (If the 5s stall on a wedged drained host ever actually bites, the two-line variant is to split `hosts` into drained and live before the gather.)

### 2. Schema (`database.py`) — three edits, and missing one fails silently

`dispatch_hosts` is declared twice, and `get_dispatch_hosts` uses an explicit column list, so a new column needs adding in three places or it silently never reaches the router.

- `database.py:230-241`, `_SCHEMA_STATEMENTS` — add `drain_reason TEXT` to the `CREATE TABLE` (fresh installs).
- `database.py:492-503`, the duplicate `CREATE TABLE` inside `_MIGRATIONS` — add the same column, to keep the two copies identical.
- Append to the tail of `_MIGRATIONS` (near `database.py:528`): `"ALTER TABLE dispatch_hosts ADD COLUMN drain_reason TEXT"`. The `CREATE TABLE IF NOT EXISTS` copy does nothing for an existing table; this is what actually adds the column on the running Postgres deployment. Migrations are applied idempotently with failures logged and suppressed (`database.py:642-650`), so the replay is safe.

Nullable with no default, which makes "not drained" the value every existing row already has.

### 3. Reading it back (`services/settings_service.py`)

`get_dispatch_hosts` selects an explicit column list in two places — the main fetch at `settings_service.py:100-102` and the post-migration re-fetch at `:128-131`. Add `drain_reason` to **both**.

This is the silent-failure seam. The router reads `host.get("drain_reason")`, so a missed column yields `None`, which reads as "not drained," and drain quietly does nothing while looking installed. Close it with a test rather than with care: assert in `tests/test_dispatch_hosts.py` that `get_dispatch_hosts` returns a `drain_reason` key.

### 4. Writing it (`services/settings_service.py`) — the first UPDATE in the module

The module has `get` / `add` / `remove` and no mutation path at all; `updated_at` exists (`database.py:237`) but has only ever been written at insert (`settings_service.py:116`, `:157`). Add one function, roughly twenty lines, in the shape of `remove_dispatch_host` (`settings_service.py:176-195`) — existence check scoped to `user_id`, then the update:

```python
async def set_dispatch_host_drain(
    db: Any, user_id: str, host_id: str, reason: str | None
) -> dict[str, str] | None:
    """Drain (reason set) or undrain (reason None) a host. None if not found."""
```

It writes `drain_reason` and `updated_at`, and returns the updated row or `None`.

### 5. The wire model (`models.py`) — and a correction worth reading

Add `drain_reason: str | None = None` to `DispatchHostResponse` (`models.py:1042-1050`), and a new `UpdateDispatchHostRequest` with the single field `drain_reason: str | None`.

The correction: it is tempting to think `DispatchHostResponse` is the frontend's model and that peer visibility runs through the MCP backend's own projection. That is only true in local-DB mode. Peer sessions on the fleet run with `AGENT_GTD_URL` set, which selects `HttpBackend` (`mcp_backend.py:2398-2405`), and its `list_dispatch_hosts` projects from the REST response (`mcp_backend.py:2135-2146`). **`DispatchHostResponse` is on the peer-visibility path.** Skip it and every peer session sees nothing.

### 6. The REST route (`routes/settings_routes.py`)

One new route beside the existing three (`GET` at `:194`, `POST` at `:213`, `DELETE` at `:254`):

```
PATCH /api/settings/dispatch/hosts/{host_id}   body: {"drain_reason": "..." | null}
```

404 when the host is not found; returns the updated `DispatchHostResponse`. Pop `_capabilities_cache` for the user, matching what add (`:243`) and delete (`:266`) already do. Also add `drain_reason=h.get("drain_reason")` to the two existing `DispatchHostResponse` constructions in the GET-list and POST handlers.

Nothing special about PATCH here: there is simply no update verb on this resource yet, and this is one.

### 7. Peer visibility (`mcp_backend.py`)

Add `drain_reason` to both projections — local at `mcp_backend.py:1166-1177` and HTTP at `:2135-2146`. Both currently emit `{id, label, url}`; make it `{id, label, url, drain_reason}`. `api_key` stays out, unchanged.

This projection *is* the peer sessions' entire view of the fleet, through `list_dispatch_hosts` in MCP (`mcp_server.py:1406-1424`) and `agent-gtd list-dispatch-hosts` in the CLI (`cli_commands/dispatch.py:83-106`). Four extra characters per host and a concurrent lead can see that `r7-server` is out and why, without asking anyone.

### 8. The operator verb (`cli_commands/dispatch.py`) — CLI only, no MCP tool

Two subcommands:

```
agent-gtd drain-host <host_id> --reason "deploying re-adoption fix cb7491a"
agent-gtd undrain-host <host_id>
```

Both call a new `set_dispatch_host_drain` on the backend protocol (`mcp_backend.py:359` region), implemented in both the local and HTTP backends; the HTTP one is a `PATCH` to the route above.

**No MCP write tool.** `tests/test_cli_parity.py` enforces parity in *both* directions, with a sanctioned escape hatch: `CLI_ONLY_EXTRAS = {"promote-admin"}`, described as "a local operational command (direct DB update), not a GTD tool." Drain is precisely that shape. Add `drain-host` and `undrain-host` to `CLI_ONLY_EXTRAS` — one line — rather than growing the MCP surface by two write tools. A lead agent performing a rolling deploy reaches this through Bash, which is already the house pattern for context-cheap writes. Reading drain state stays on the MCP surface, where peers need it; setting it does not need to be.

### 9. Frontend (`types.ts`, `api.ts`, `Settings.tsx`)

`DispatchHost` gains `drainReason: string | null` (`types.ts:305-313`; the API client converts snake to camel automatically). `api.dispatchHosts` gains a `setDrain(hostId, reason)` calling the PATCH (`api.ts:327-331`). The host list at `Settings.tsx:543-560` renders a chip when `drainReason` is set, showing the reason, and a menu action to drain/undrain.

This is the one part that is genuinely optional for the mechanism to work and genuinely not optional in practice — the fleet is reviewed from a phone, and `nano` over SSH is not a fleet console.

### 10. Tests

Three that matter, in files that already exist:

- `tests/test_dispatch_router.py` — a drained host is skipped in auto mode, and the skip reason contains the reason string.
- `tests/test_dispatch_router.py` — a drained host is still returned for a pinned dispatch. This is the regression that would quietly remove your only way to test a fix.
- `tests/test_dispatch_hosts.py` — `get_dispatch_hosts` returns the `drain_reason` key, and a PATCH round-trips through set and clear.

## The operator procedure

For a dispatch-side fix, with `<fix>` already released to the homelab index.

**1. Drain three of the four hosts, leaving one taking work.**

```bash
agent-gtd list-dispatch-hosts | jq -r '.[] | "\(.id) \(.label)"'
agent-gtd drain-host <pironman01-id>   --reason "rolling deploy 2.0.2 (re-adoption fix cb7491a)"
agent-gtd drain-host <r7-research-id>  --reason "rolling deploy 2.0.2 (re-adoption fix cb7491a)"
agent-gtd drain-host <r7-server-id>    --reason "rolling deploy 2.0.2 (re-adoption fix cb7491a)"
```

Leave at least one host undrained — see the footgun below.

**2. Wait for a drained host to go idle.** `active_runs` on `/info` is the signal, and it counts rollout loops as well as builds:

```bash
curl -s http://pironman01:8100/info | jq '{active_runs, max_concurrent_runs}'
```

Read it twice, thirty seconds apart, before believing a zero. `_pending_queue` (`main.py:139`) is a bare in-process list exposed on no endpoint, and `_try_start_pending` (`main.py:1011-1032`) promotes a queued run the instant a slot frees. It only ever drains downward once the host is drained — no new work arrives from the board — but a single sample can catch the gap between a run finishing and its successor starting.

**3. Deploy that one host, with the single-host escape hatch that already exists:**

```bash
cd ~/git/agent-gtd-dispatch && DISPATCH_HOST=pironman01 EXPECT_VERSION=2.0.2 ./deploy.sh
```

`EXPECT_VERSION` is implemented (`deploy.sh:106-114`) though undocumented in the script's own header block, and it is worth setting: it gates on the *installed* version and turns a silently-stale `uv tool install` into a loud failure.

**4. Undrain it and confirm it is taking work again:**

```bash
agent-gtd undrain-host <pironman01-id>
curl -s http://pironman01:8100/info | jq .version
```

**5. Repeat for the next host.** The fleet never drops below one host accepting work, and no restart ever lands on a host with a live run.

**Optional, and the reason pinning is exempt:** between steps 3 and 4, dispatch a real item at the freshly-fixed host while it is still drained, with `dispatch_item(dispatch_host_id=<pironman01-id>)`. It is the only host running the new code and nothing else can be routed to it. That is a canary, on production, with a blast radius of one item.

### The footgun: draining every host fails dispatches, it does not queue them

If every host is drained, `pick_dispatch_host` raises `NoCompatibleHostError` and `execute_run` marks the run **failed** (`dispatch_worker.py:930-932`) — there is no board-side queue to absorb it.

No guard is proposed for this, deliberately. A "refuse to drain the last host" check is four lines that will one day block a legitimate full-fleet maintenance window, and the failure is already self-explaining: the run's error message will read `pironman01: draining: rolling deploy 2.0.2; r7-research: draining: rolling deploy 2.0.2; ...`, naming every host and the reason you typed. That is a better error than most of this system produces on purpose. The procedure is "always leave one host up"; the error tells you immediately when you didn't.

## What this does not cover

**Board-side fixes.** A fix that changes `agent_gtd` needs the board restarted, and drain does nothing for that. The queued 422 fix is in this category. The mitigating fact is that a board restart is survivable in a way a host restart is not — it does not kill agent processes, and `reconcile_active_runs` (`dispatch_worker.py:510-614`) rebuilds the pollers from `claude_runs.dispatch_host_url`. Shipping *this feature* costs exactly one such board restart.

**Dispatch-side fixes that change the wire protocol.** Rolling a fix host-by-host means running a mixed-version fleet for the duration. That is fine only if the new version is wire-compatible with the board that is talking to both versions. `cb7491a` is purely internal to the host's own startup sweep, so it rolls cleanly. The queued failure-taxonomy change needs checking against this before it is rolled rather than deployed — if it alters what the host reports on `/runs/{id}`, it is not a rolling candidate. This is the real scope boundary, and it is narrower than "dispatch-side versus board-side."

**Anything automatic.** There is no watcher that drains a host, waits for idle, deploys, and undrains. That is a scheduler, it is a new daemon with new failure modes, and its first bug would be restarting a host whose `active_runs` transiently read zero across the pending-queue gap described above. The procedure is four commands per host and it is run by a human or a lead agent who is already watching. Do not build the daemon.

**Detecting that a host needs draining.** Drain is a record of a decision, not a detector. `jason-precision` is wedged right now and nothing in this design notices that; it only gives you somewhere to write `wedged 2026-09-20, event loop blocked mid-git-commit` so that the next person — or the next session — is not re-diagnosing it from scratch. Turning a silent skip into a documented one is most of the value here, and it is a separate piece of work to make the silence itself detectable.

**Stopping in-flight work, and stopping rollout loops.** A drained host keeps running everything it already has, and keeps serving `GET /runs/{id}` to the board's pollers — which is required, not incidental. More subtly, a drained host driving a rollout keeps *generating* work: child builds inherit a host only when the rollout carries a non-NULL pin (`services/dispatch_service.py:129-134`), so an unpinned rollout on a drained host scatters its builds across the hosts that are still up. That is correct — it is what lets the rollout finish so the host can go idle — but it means drain stops a host receiving work, not producing it.

**Preventing rollout re-adoption on the restart itself.** `_readopt_running_rollouts` (`main.py:2967-3042`) runs unconditionally from lifespan and drain does not gate it. In this procedure it does not matter, because you only ever restart an idle host, and idle means no rollout loop. Worth knowing while the fleet is mixed-version: a host still on 2.0.1 keeps the mis-adoption bug until its turn comes, and it can only fire on that host's next restart — which, under this procedure, is the restart that fixes it.

## Cost

Ten files in `agent_gtd`, zero in `agent-gtd-dispatch`. Roughly 150-250 lines including tests, and no file gains a new concept — one column, one `if`, one UPDATE function, one route, two CLI verbs, and four projections that each grow by one field. One groomed item, cheap engine, and the only judgement call in it (pinned path exempt from the check) is stated in the acceptance criteria rather than left to be derived.

It costs one board restart to ship, at a moment of your choosing. After that the four hosts can be fixed one at a time, forever, without killing a single run.
