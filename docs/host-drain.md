# Non-destructive host drain (rolling dispatch-side releases)

**Status:** shipped and used in production. First full rolling deploy: agent-gtd-dispatch 2.5.0 across all four hosts on 2026-10-11, no in-flight run lost. Supersedes three competing drafts produced during design exploration.

Host names below (`host-a` through `host-d`) stand in for the four hosts of the fleet this was designed on.

## The problem

A dispatch-side fix cannot be deployed while the fleet is busy, because deploying restarts `dispatch-api`, and `main.py:284-293` cancels every in-flight run's task on shutdown while `db.py:173-196` then marks each one `failed` on the way back up. So a restart destroys live agent work and actively reports it as failed.

That produced a deadlock today. The re-adoption fix (`cb7491a` — a host adopting every rollout in the fleet on startup) was cut as 2.0.2 and could not ship, because all four hosts were busy. Two more fixes queued behind it. The fix for "deploys are dangerous" was itself blocked by deploys being dangerous.

The only existing way to take a host out of rotation is `DELETE /api/settings/dispatch/hosts/{id}`, which is destructive: it drops the row, loses the `api_key`, and orphans the in-flight runs whose records point at that host.

## Three corrections to the premise

Worth stating because they shrink the work considerably.

**`deploy.sh` is already serial and already per-host.** `deploy.sh:250-252` is a plain `for host in ${HOSTS}` loop that blocks on each host's health probe, and `deploy.sh:34-38` already honours `DISPATCH_HOST=<one>` to target a single host. The per-host deploy primitive exists. What is missing is any way to stop the *other* hosts taking new work while you use it.

**`active_runs` is an honest idle signal.** `_start_rollout_loop` registers its task in `_active_processes` (`agent-gtd-dispatch/main.py:2961-2964`), so a host driving a rollout counts as busy even when it is only waiting between waves. `active_runs == 0` genuinely means idle, including no rollout loop.

**The re-adoption bug is narrower than it looked.** 2.0.2 is already live on host-d, and the bug is startup-only. The residual exposure is an unattended `Restart=on-failure` bounce of a host still on 2.0.1 — which drain does **not** cover, because nobody is there to drain first.

## Design

One nullable column, one router clause, two CLI verbs. No new service, no state machine, no scheduler.

### Schema

`drain_reason TEXT` on `dispatch_hosts`. `NULL` means accepting work; any non-NULL string means out of rotation, and the string says why.

The reason string *is* the flag. Two states, no enum, no lifecycle. An unexplained drain is indistinguishable from a host that is quietly broken — which is precisely the confusion that cost camera-profiles two runs on a half-provisioned host-d this morning — so `--reason` is **mandatory** when draining a host that is not already drained.

It must be added in **three** places in `agent_gtd/src/agent_gtd/database.py`, and missing one fails *silently* because the router reads `host.get("drain_reason")` and a missing column yields `None`, which reads as "not drained":

1. `database.py:230-241` — the `CREATE TABLE dispatch_hosts` in `_SCHEMA_STATEMENTS` (fresh installs, SQLite local mode, and every test).
2. `database.py:492-503` — the duplicate `CREATE TABLE` in the migration path.
3. `database.py:520-536` — an `ALTER TABLE dispatch_hosts ADD COLUMN drain_reason TEXT` appended to `_MIGRATIONS`. Replay-safe: the runner at `database.py:642-648` catches and logs, which is the established idiom for every other `ALTER` in that list.

### Router

A skip clause in the **auto** branch of `pick_dispatch_host` — and a **refusal in the pinned branch too**.

**Drain is checked before capability labels.** `844f345` added capability-label filtering to this same function, which rejects a host that lacks a required label before engine, agent and capacity are considered, and raises `UnmetCapabilityError` naming what went unsatisfied. Drain sits ahead of that: a drained host is not a candidate whatever labels it carries. The ordering matters for the error a caller sees — a pool whose only capable host is drained must report *drained*, not *unmet capability*, because those call for opposite responses (wait for the host to come back, versus label another host or fix the requirement).

#### Drain must block pinned dispatch. This is the load-bearing decision.

An earlier draft of this design left `--dispatch-host-id` untouched, on the theory that pinning is how an operator tests a freshly upgraded host. That was wrong, and it would have defeated the entire feature in practice.

Pinning is not primarily an operator tool. It is how agents express **capability affinity**. camera-profiles pins to host-b because that is the only host where hundreds of gigabytes of sample images are staged; nowhere else can run those items at all. Those dispatches come from a peer session that has no idea a drain is in progress, and under the earlier design they would have kept landing on host-b indefinitely — so the host would never have gone idle, and drain would have silently failed to do the one thing it exists for.

So: **a pinned dispatch to a drained host is refused**, and the error carries the drain reason.

The refusal must read as *wait*, not as *re-route*. A caller pinning for affinity cannot fall back to auto-routing — the data is not on the other hosts — so an error that nudges toward "try another host" sends them somewhere the work cannot run. The message should name the host, say it is draining, quote the reason, and say the work should be retried when it returns. This is what makes the mandatory `--reason` pay for itself: camera-profiles sees `host-b is draining: rolling deploy 2.0.2` and knows to hold rather than guess.

#### Drain is absolute. There is no override in the CLI contract.

An intermediate draft proposed an `--allow-drained` flag for operator verification. That is also wrong, and for a sharper reason: **anything in the public CLI contract that can reach a drained host is a hole, because any agent can find it and use it.** A flag documented in `--help` is not an operator tool, it is an affordance — and the whole point of drain is that callers who do not know about the drain cannot defeat it. A drain an agent can opt out of is not a drain.

So there is no flag, no header, no env var, no escape hatch. Every board-side path — MCP `dispatch_item`, the REST route, the CLI, and rollout child dispatch — refuses a drained host, and the refusal lives at the single chokepoint rather than being re-implemented per caller.

**The chokepoint is `pick_dispatch_host`.** It has exactly one caller, `dispatch_worker.py:923`, and every dispatch path funnels through it, so the check cannot be routed around. That is the one that must be correct, because it is the one nothing can bypass.

A second, friendlier rejection belongs earlier, so a caller is told before a run row exists rather than after. **Correction to an earlier draft of this doc, caught by the groom's code-grounding pass:** `create_run` does **not** validate a pinned `dispatch_host_id` today — it performs no pin validation at all. The two surfaces that do are `dispatch_service.dispatch_rollout_run` and the REST pre-flight in `dispatch_routes.py`. So the early rejection is NEW code rather than an extension of an existing check, and whichever surface it lands on, it is a convenience: it must never be the only refusal, because a caller that reaches the worker by another path would sail past it.

Line numbers are deliberately omitted here. Host capability labels landed in `844f345` and moved this code; cite symbols and verify against the tree at implementation time.

#### Then how do you verify a host after upgrading it?

**On the host, as an admin action — not through the board.** Health-checking a machine you are administering is a thing you do by logging into it, and routing it through the public dispatch API is what created the need for an override in the first place.

`deploy.sh --smoke` already covers the layer that actually breaks on a bad deploy: the service starts, `/health` and `/info` return 200, and `EXPECT_VERSION` asserts the installed wheel is the one you meant. Beyond that, an operator on the host has `journalctl -u dispatch-api`, `curl localhost:8100/info`, and the ability to exercise the agent toolchain directly as the `dispatch` user — which is how this morning's umask failure was diagnosed, and it needed no board involvement at all.

The deeper "can it really run an agent end-to-end" question is answered by undraining and watching the first real run, which is the honest test anyway: a synthetic smoke dispatch exercises a path slightly different from production and can pass while production fails.

#### The durable fix is capability labels, not pinning

The root problem is that pinning is being used to express a *requirement* ("this item needs the sample-image dataset") because there is no way to say so directly. That conflation is what makes drain awkward.

Item `1bfbfbc4` — host capability labels, letting projects and items declare what a host must provide — landed today and is in review. Once it ships, camera-profiles declares a requirement instead of pinning a host id, the router satisfies it, and drain composes naturally: a drained host simply stops being an eligible candidate, and an item whose only capable host is drained waits for a host rather than failing. No override needed, because nobody is pinning.

This design should be read as the interim: refuse-and-explain now, and expect pinning itself to become rare as capability labels take over the affinity cases. The end state is that nothing pins, so nothing needs to be refused.

### What drain must NOT break

**A drained host must keep serving `/runs/{id}` for its in-flight runs.** The status poller lives in agent_gtd and polls the host directly; drain is an admission-control decision on the board, and touches nothing on the host.

**A drained host must still return its `api_key` from `get_dispatch_hosts`.** `dispatch_worker.py:578-587` re-fetches the host list to authenticate reconciliation polls, and a drained host filtered out of that read path would strand its own in-flight runs. This is the trap most likely to be introduced by a careless implementation — it needs an explicit test that a drained host still returns its key.

**Peer visibility has to land on all three projections**, not just the local one: `DispatchHostResponse`, and both `mcp_backend` projections (`:1176` and `:2145`). Other sessions dispatch to this fleet concurrently and need to see that a host is parked and why. Test it in HTTP mode, not only local.

### Pinned rollouts need a decision, not a caveat

A rollout pinned to a host keeps dispatching its children there (`dispatch_service.py:129-134`). With pinned dispatch now refused, those child dispatches would start failing mid-wave — and a failed child currently halts the rollout, which is the blast-radius problem filed as `9f00b5f1`.

That is not acceptable as a side effect of draining. The rollout loop must treat "host is draining" as a reason to **wait**, not to fail and not to halt: hold the wave, publish the drain reason as the manager's current step so it is visible on the board, and resume when the host returns.

This is the one place drain needs real logic rather than a filter, and it is dispatch-side, so it ships in the same wave as the column. Until it exists, **do not drain a host that owns a running rollout** — the operator procedure must check, and `drain-host` should warn when the host has one.

### What drain does not cover

**Board-side changes still need a board restart.** This covers dispatch-side fixes only. An `agent_gtd` change — like today's `reviewer-autonomous` fix — still bounces the board.

**An unattended crash-restart is not covered.** `Restart=on-failure` bounces a host with nobody there to drain it first.

## Operator sequence

```bash
agent-gtd list-dispatch-hosts          # shows draining + reason per host

agent-gtd drain-host host-a --reason "rolling deploy 2.0.2 (re-adoption fix cb7491a)"
agent-gtd drain-host host-b --reason "rolling deploy 2.0.2"
agent-gtd drain-host host-c --reason "rolling deploy 2.0.2"
```

Three hosts parked; in-flight runs continue untouched; host-d absorbs all new work.

Wait for a parked host to go idle. **Read `active_runs` twice, ~30s apart, before believing a zero** — `_pending_queue` (`main.py:139`) is an in-process list that is never exposed on `/info`, and `_try_start_pending` (`main.py:1011-1032`) promotes queued runs the instant a slot frees. A single zero can be a gap between two runs.

```bash
curl -s http://host-a:8100/info | jq '{active_runs, max_concurrent_runs}'
DISPATCH_HOST=host-a EXPECT_VERSION=2.0.2 ./deploy.sh   # --smoke asserts /health, /info, version
```

Verify on the host, as an admin — there is no board-side way to reach a drained host and that is deliberate:

```bash
ssh host-a 'journalctl -u dispatch-api -n 50 --no-pager; curl -s localhost:8100/info | jq'
```

Then return it to rotation and watch the first real run land:

```bash
agent-gtd undrain-host host-a
```

Peer sessions pinning to a drained host get a refusal naming the host and quoting the reason, and should hold rather than re-route — a caller pinning for capability affinity has nowhere else to go.

Repeat per host. The fleet never drops below one host accepting work.

**Cutting the release and deploying the first host together.** `release.sh` ends by calling `deploy.sh`, which honours `DISPATCH_HOST`, so `DISPATCH_HOST=<idle-host> ./release.sh` publishes the wheels and deploys only that host. Drain it first. Once it is verified and undrained, drain every host still on the old version so the upgraded host takes all new work, then deploy each one with `DISPATCH_HOST=<host> EXPECT_VERSION=<ver> ./deploy.sh` as it goes idle.

**A host driving a rollout loop can be drained when the rollout is not pinned** (`dispatch_host_id` null on the rollout). Its child builds auto-route to other hosts. The loop itself counts in `active_runs`, so that host only goes idle when the rollout finishes.

Hosts should be addressable by **label**, not UUID — operators think in `host-a`, the registry thinks in `c941111f-…`. A ~20-line resolver (exact id → unique label → unique URL substring → error listing candidates) removes a lookup from every command.

### A guard in `deploy.sh`

Refuse to restart a host whose `active_runs > 0`, and **skip-and-continue rather than `exit 1`** — `set -euo pipefail` at `deploy.sh:2` would otherwise strand the rest of the fleet behind one busy host. This is independent of drain and worth shipping in the same wave: without it, an operator who forgets to wait still destroys an afternoon.

## Rejected: host-owned sentinel file

The competing design had the host own its drain state in a file and advertise it on `/info`, with no schema change at all. Its fail-safe argument is genuinely stronger — a host that knows it is mid-upgrade cannot be handed work by a board that has forgotten.

It is rejected on one point: **it cannot bootstrap.** Installing it requires deploying to every host, which requires the restart that drain exists to make safe. A design that cannot be installed without the operation it exists to protect has not solved the problem.

The sequencing both board-held drafts reached independently: ship the column now, and if the sentinel is still wanted it rides out on the first rolling deploy the column makes possible, as a second disjunct on the same clause — `if host.get("drain_reason") or info.get("draining")`. The two designs stop competing and the fail-safe direction comes for free.

## Deliberately not included

- **No `--wait` blocking CLI verb.** A board-side live count is the better *idea* (it does not lie when a host wedges), but two `curl`s and an `agent-gtd list-runs` answer the same question in a four-host homelab. Revisit if waiting out a wedged host by hand ever becomes annoying.
- **No "last host" guard.** Draining the whole fleet is a legitimate thing to want, and a guard that second-guesses it costs more than it saves.
- **No UI drain button.** Read-only chip showing state and reason; draining is an operator action with a reason string, which belongs on the CLI.

## Does this generalize?

The KB session asked whether the same pattern could park a KB instance during a deploy. Partly. The column and the mandatory-reason ergonomics transfer directly. The router clause does not: this design assumes an interchangeable *pool* where work can go to any member, and the KB hosts serve different KBs, so draining there means "this instance is unavailable" rather than "route elsewhere" — a different problem that needs callers to tolerate absence, not a router that picks another host.
