# Host drain — taking a dispatch host out of rotation without destroying it

Status: proposed, 2026-09-20. Scope: dispatch-host-side rolling upgrades. Spans `agent_gtd` (router, peer visibility) and `agent-gtd-dispatch` (host, deploy script).

## The deadlock this exists to break

A dispatch-side bug was found and fixed today (`cb7491a fix(rollout): only re-adopt rollouts this host actually drove`). It cannot be deployed. `deploy.sh` restarts `dispatch-api` on each host, and the lifespan shutdown at `main.py:284-293` cancels every entry in `_active_processes`, killing the agent subprocesses; then on the way back up `db.reconcile_orphans()` (`main.py:272`, implemented `db.py:173-196`) flips every `pending`/`running` row to `failed` with `"Service restarted while run was active"`. With six runs in flight, deploying costs six runs. So the fix for "deploys are dangerous" is blocked by "deploys are dangerous", and two more fixes are queued behind the same wall.

The missing primitive is narrow: **a way to stop the board sending NEW work to a host, without changing anything about the runs already on it.** Everything else needed for a rolling upgrade already exists — `deploy.sh:34-38` already honours `DISPATCH_HOST=<one-host>`, so a single-host deploy is one env var away. What does not exist is any way to stop the other three hosts receiving work while you wait for them to go idle.

## What this covers, and what it does not

It covers a fix that is **purely dispatch-side** — one where the new host code speaks the same HTTP contract to the board as the old code. All three queued fixes are that shape.

It does not cover a change to the board/host wire protocol, and it does not cover a change to `agent_gtd` itself. A board restart is a separate problem with a different shape: the board's run-status pollers are in-process asyncio tasks (`dispatch_worker.py:997-1017`) rebuilt at startup by `reconcile_active_runs`, so a board restart interrupts polling but does not kill agents. Draining hosts does not help there and is not claimed to.

It also does not attempt scheduling, queue draining, automatic fleet orchestration, or a host lifecycle state machine. There are two states: draining, or not.

## The design in one paragraph

The **host** owns its drain state, as a sentinel file it reads at `/info` request time and advertises as a boolean plus a free-text reason. The **board** owns the routing decision: `pick_dispatch_host`'s auto path gains one filter that skips draining hosts; the pinned path is deliberately left alone, so `--dispatch-host-id` still reaches a drained host and remains the way you verify a fix. `deploy.sh` drops the sentinel itself before restarting and removes it after the health probe passes, so drain-during-deploy is automatic rather than a thing an operator must remember.

## Why the host owns it, not the board

The obvious alternative is a `state` column on `dispatch_hosts`. It is worse here for three reasons, and the third is the one that decides it.

The plumbing cost is real and lopsided. `dispatch_hosts` has **no update path at all** — not in the service layer (`settings_service.py` has `get_dispatch_hosts` at :85, `add_dispatch_host` at :137, `remove_dispatch_host` at :176, and nothing else), not in the routes (`settings_routes.py` exposes GET at :194, POST at :213, DELETE at :254), not in `api.ts:328-331`, not in MCP, not in the CLI. The `updated_at` column exists (`database.py:237`) and has never been written outside insert. A board-held flag needs a genuinely new mutation verb plumbed through five surfaces, plus a column added in both copies of the DDL (`database.py:230-241` and `database.py:492-503`) *and* in the explicit column list in `get_dispatch_hosts` (`settings_service.py:100-102`, and again on the migration re-fetch at :128-131) — three places, and the consumers read by key (`dispatch_router.py:271` does `host.get("url")`), so missing one fails silently rather than loudly.

The truth is host-local. "This host is mid-upgrade" is a fact created by the deploy operation, on the host, by a script that is already SSHed in. Putting the flag on the host means the drain and the restart it protects are the same script, the same host, the same SSH session — they cannot drift apart, and there is no window where one has happened and the other has not.

And the decisive one: **host-asserted drain fails in the safe direction.** If a draining host is also unreachable, `/info` fails, `_classify_info_failure` returns a reason (`dispatch_router.py:107-129`), and the router skips it — the same outcome as if it had answered "draining". Every failure mode of the signal converges on "do not route here", which is what drain means. A board-held flag has a failure mode with no such convergence: board says drained, host is actually fine and idle, and the host sits out of rotation until someone notices the stale row.

The honest cost of that choice is in the failure-mode section below; it is a visibility cost, not a correctness one.

## Mechanism

### Dispatch side

A sentinel file at `/etc/agent-gtd-dispatch/drain`, path overridable by `DISPATCH_DRAIN_FILE`, defaulting in `config.py` alongside the existing path constants (`config.py:26`, `:33`). The systemd unit (`templates/dispatch-api.service.tmpl`) sets no `ProtectSystem` or `ReadWritePaths`, so the service reads `/etc` without change.

It must be a **file read at request time**, not an env var. `MAX_CONCURRENT_RUNS` is the cautionary example: declared `config.py:57`, loaded from `DISPATCH_MAX_CONCURRENT_RUNS` at `config.py:280`, read once in `config.load()`. "Just set capacity to 0" requires editing the systemd EnvironmentFile and restarting — the exact operation this design exists to avoid. A file is settable with one SSH command and zero process impact.

`/etc` rather than `/run` deliberately: `/run` is tmpfs and would silently un-drain a deliberately-parked host across an unexpected reboot. Fail-closed is the right direction for a parked host.

`/info` (`main.py:4331-4347`) gains three fields on `InfoResponse` (`models.py:24-36`), all optional so an older board reading a newer host is unaffected:

- `draining: bool` — the sentinel exists
- `drain_reason: str` — the file's first line, trimmed and length-capped
- `pending_runs: int` — `len(_pending_queue)`

`pending_runs` is not decoration; see the idleness race below.

Two properties of `/info` to keep in mind. It is **unauthenticated** — `info()` takes no `Depends(_verify_api_key)`, unlike `/agents` at `main.py:4351-4352` — so drain reason is LAN-readable; keep it operational text, not secrets. And it **forks a subprocess on every request**: `main.py:4339` calls `run_list_agents_script()`, a real `create_subprocess_exec` with a 5s internal timeout (`agent_discovery.py:110-124`), against the router's own 5s timeout (`dispatch_router.py:94`, `:101`). The two are equal, which is a pre-existing fragility this design inherits but does not worsen — the sentinel read is a single `os.path.exists` and adds nothing measurable.

The host does **not** reject dispatches while draining. Drain is advisory at the host and enforced at the router. This is what keeps pinning working for free, and it is discussed as a race below.

### Board side

One filter in `pick_dispatch_host`'s auto path (`dispatch_router.py:264-307`), inside the existing `for host, info in zip(...)` loop, placed after the `isinstance(info, str)` reachability check and before the engine check:

```python
if info.get("draining"):
    reason = info.get("drain_reason") or "draining"
    skipped.append({"host": host_label, "reason": f"draining: {reason}"})
    continue
```

That is the entire enforcement change. It lands in the right place because host selection happens at **run-execution** time, not run-creation time: `create_run` (`services/dispatch_service.py:45`) writes a pending row and enqueues it (`dispatch_worker.py:1127-1131`), and `execute_run` calls the router when a worker pops it (`dispatch_worker.py:923-929`). One choke point covers direct builds, rollout child builds and manage runs alike — and usefully, **runs already sitting in the board's pending queue when you drain will respect the drain**, because they have not been routed yet.

The skip reason flows into `NoCompatibleHostError` (`dispatch_router.py:69-86`), whose message is truncated to 500 chars and written to the run's error field (`dispatch_worker.py:930-932`). So "every host is drained" produces a run failure that says so by name, which is the correct and legible outcome for a fleet you have parked.

The pinned path (`dispatch_router.py:205-262`) gets **no change**. It already bypasses ranking and `exclude_urls`; it will now also ignore drain. It still enforces engine, agent and `available <= 0 → HostFullError`, which is what you want: you can pin work at a drained host to test a fix, but you cannot overfill it.

There is a second, partial capacity gate on the HTTP route only — `dispatch_routes.py:386-411`, returning 409, best-effort and swallowing fetch failures at :397-398, and reached only by `POST /api/items/{id}/dispatch` and not by the rollout, MCP or CLI paths. It pre-validates an explicitly-supplied host id, which is the pinned case, so it correctly needs no drain check. Leaving it alone is deliberate, not an oversight.

### Peer visibility

`list_dispatch_hosts` in `mcp_backend.py:1166-1177` projects to `{id, label, url}` and never calls `/info`. That projection **is** the entire fleet view for peer Claude sessions and for `agent-gtd list-dispatch-hosts` (`cli_commands/dispatch.py:83-106`). Drain state added anywhere else is invisible to them.

So the projection gains `draining`, `drain_reason` and `available`, sourced by calling the existing `_gather_host_info` from `dispatch_router.py:132-156` — already written, already concurrent, already returns a discriminated failure string per host. Unreachable hosts surface that string as the reason. This is the one place worth spending a fan-out, because with peers dispatching to this fleet concurrently, a drain nobody can see is a drain that gets argued with.

Worth noting what this incidentally fixes: the board already computes a per-host skip reason on every routing decision and throws it away unless *every* host fails. Surfacing it makes today's silent failures legible — see `jason-precision` below.

### deploy.sh

`deploy_one` (`deploy.sh:77-247`) is already strictly serial (`deploy.sh:250-252`), and already blocks on each host's health probe. Three changes:

**Refuse to restart a busy host.** Before the install, probe `/health` and read `active_runs`; if non-zero and `--force` was not passed, print loudly and **skip this host, continuing to the next**. Not `exit 1` — with `set -euo pipefail` at `deploy.sh:2` an abort would strand the rest of the fleet, and the whole point is to deploy the idle ones now. This single guard is the highest-value change in the document: today `deploy.sh` will cheerfully restart a host with six runs on it.

**Auto-drain around the restart.** Drop the sentinel before the install, remove it after the health probe passes. The restart is seconds away regardless, so this costs nothing and closes the window where the board routes a run at a host that is about to die.

**Only un-drain what you drained.** Check for the sentinel before creating it; if it already existed, leave it in place at the end. Otherwise a deploy silently reverses an operator's deliberate park. Three lines of shell, and the kind of thing that breaks quietly if skipped.

A separate `drain.sh <host> [reason]` / `undrain.sh <host>` pair, or one script with a flag, covers the manual case. Passwordless sudo on the deploying user is already established — `deploy.sh` runs `sudo systemctl restart` and `sudo -u dispatch-svc` inside a no-TTY `ssh host bash -s` heredoc (`deploy.sh:82`, `:95`, `:225`).

## Operator workflow — the rolling fix

```bash
./drain.sh pironman01 r7-research r7-server "rolling upgrade to 2.0.2 (re-adoption fix)"
DISPATCH_HOST=jason-precision ./deploy.sh
```

The first command parks three hosts; their in-flight runs continue untouched and their `/runs/{id}` polls keep being served. The second upgrades the one idle host, which is un-drained automatically when its health probe passes — so the whole fleet's new work now lands on the upgraded host, and the parked hosts bleed down as their runs finish.

Verify the fix on the upgraded host by pinning:

```bash
agent-gtd dispatch-item <id> --dispatch-host-id fd7c044a-a015-4bac-8377-f1aa14697229
```

Then, as each parked host reaches idle, deploy it — the busy-host guard means you can simply attempt the whole fleet and let it skip what is still working:

```bash
agent-gtd list-dispatch-hosts    # shows draining + available per host
./deploy.sh                      # skips busy hosts, upgrades and un-drains idle ones
```

Repeat until clean. Nothing in this sequence kills a run.

## Failure modes, honestly

**A host is unreachable while draining.** The router skips it with a `_classify_info_failure` reason instead of the drain reason. Routing is correct — skipped either way — but the *explanation* is wrong, and an operator cannot distinguish "parked" from "broken" from the board. This is the genuine cost of host-asserted state and I am not going to pretend otherwise. It is mitigated, not eliminated, by the peer-visibility change: the fleet listing shows the failure string, so the host at least reads as *something is wrong here* rather than vanishing. If this proves painful in practice the fix is a board-side annotation, not a board-side source of truth — but do not build it until it hurts.

**This is already happening, undiagnosed.** `jason-precision` is wedged right now: `systemctl is-active dispatch-api` reports active, it is LISTENing on 8100 with 65 connections stuck in the accept backlog, and `/health` — a dict length — did not answer in 45 seconds from the host itself; its journal shows normal `GET /runs/<id> 200 OK` until 12:11:23 then a `sudo … git commit` for a talos run, after which the event loop stopped answering. The router classifies it via `dispatch_router.py:121-122` as `"no /info response within 5s (host may be at capacity / saturated)"` and skips it. **The fleet has already accidentally drained a host, by the mechanism indistinguishable from death, with zero operator visibility.** The fleet is effectively three hosts today and nothing said so. That is an argument for the visibility change independent of drain.

**Race: run routed just before the drain lands.** The router fetches `/info` with no cache (`dispatch_router.py:141-145` records why — a TTL cache previously piled burst dispatches onto one host), so the window between reading "not draining" and the host receiving the dispatch is one HTTP round trip. Lose the race and you get one extra run on a host you were about to park, which you then wait out. The alternative — having the host hard-reject dispatches while draining — would break pinning, which is a stated requirement, and would need a bypass header to un-break it. Advisory-at-host, enforced-at-router is the cheaper correct answer.

**Idleness is racy if you watch only `active_runs`.** `_pending_queue` (`main.py:139`) is a bare in-process list, appended at `main.py:4690`, drained by `_try_start_pending` (`main.py:1011-1032`) the instant a slot frees, and exposed nowhere. A host can read `active_runs: 0` at the moment it promotes three queued runs. On a *drained* host the queue is monotonically draining, so this converges — but the sample can still land wrong, which is precisely the moment `deploy.sh` would decide it is safe to restart. Hence `pending_runs` on `/info`, and an idle check that requires both to be zero.

**A rollout keeps a host busy.** `_start_rollout_loop` registers its task in `_active_processes` (`main.py:2961-2964`), so a host driving a rollout correctly reads as busy and will not be restarted by the guard. It does not, however, park the host indefinitely: the wave loop dispatches child builds by calling **the board** (`gtd_client.dispatch_item` → `POST /api/items/{id}/dispatch`, `gtd_client.py:312-332`), so those children route through `pick_dispatch_host` and land on non-drained hosts. A drained host's rollout finishes, scattering its work elsewhere, and then the host goes idle. That is the desired behaviour and it falls out for free.

**Drain does not stop re-adoption.** `_readopt_running_rollouts` runs unconditionally from lifespan (`main.py:283`) and its guard is "does a local run row exist for this rollout" (`main.py:3014`), checked after `reconcile_orphans` has already flipped those rows to failed. A drained host that restarts will resume rollouts it previously drove. This is correct — drain means "no new work from the board", not "abandon your own responsibilities" — but it means *drained* and *idle* are different properties, and a host can go from drained-and-idle back to drained-and-busy across a restart. With `cb7491a` deployed, it re-adopts only its own rollouts, which is the whole reason that commit is urgent.

**Deleting the host row remains destructive, and worse than advertised.** Beyond losing the `api_key`, a deleted row causes `reconcile_active_runs` to fail that host's in-flight runs: it reads `dispatch_host_url` off the run (`dispatch_worker.py:559`), looks the URL up in `get_dispatch_hosts` to recover the key, and on no match marks the run `failed` with `"Dispatch host no longer configured; cannot reconcile run"` (`dispatch_worker.py:578-587`). Delayed trigger — it fires on the next board restart, not at delete time. Drain replaces this entirely for the rotation use case.

**A stale mechanism this design deliberately does not lean on.** The `503 = at capacity` retry at `dispatch_worker.py:963-972` no longer means what its comment says: the host queues at capacity and returns **200** (`main.py:4685-4708`), and its only 503s are upstream-unreachable errors (`main.py:4459`, `:4502`, `:4560`, `:4600`). That path is the only existing caller of `exclude_urls`, the router's one pre-existing "skip this host" primitive. Drain gets its own filter rather than reusing `exclude_urls`, so it does not inherit that confusion, and the skip reasons stay distinguishable (`"at capacity"` vs `"draining: …"`). Fixing the stale comment is a separate small cleanup.

## Cost

Dispatch side: one config constant, one `os.path.exists` plus a file read in `/info`, three optional fields on `InfoResponse`, and about twenty lines of shell across `deploy.sh` and a `drain.sh`.

Board side: five lines in `dispatch_router.py`, and a `_gather_host_info` call plus three fields in the `mcp_backend` projection.

No schema change. No migration. No new endpoint on either side. No new service, no scheduler, no state machine. Two host states, one filter, one sentinel file.

## What was considered and rejected

**A `state` column on `dispatch_hosts`.** Rejected on plumbing cost (five surfaces, three DDL/query sites, all failing silently) and on failure direction — see above. If drain later needs to be settable from the UI by someone without SSH, revisit; that is a real requirement this does not serve.

**Setting `max_concurrent_runs` to 0.** Requires editing the systemd EnvironmentFile and restarting, which is the operation being avoided. Also conflates capacity with policy, and would break pinning.

**Having `deploy.sh` block until a host goes idle.** It is serial across hosts with `set -e`; one busy host would stall the fleet for hours. Skip-and-continue plus a re-run is strictly better and simpler.

**Having the host reject dispatches while draining.** Breaks pinned dispatch, which is the mechanism for verifying a fix on a drained host. Would need a bypass header to restore, which is more machinery than the race it closes is worth.

**Auto-undrain on a timer.** A parked host silently rejoining the rotation is the failure mode you least want at 2am. Un-drain is explicit, or done by the deploy that drained it.
