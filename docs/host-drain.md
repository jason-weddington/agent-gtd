# Non-destructive host drain (rolling dispatch-side releases)

**Status:** design, awaiting review. Supersedes three competing drafts produced during design exploration.

## The problem

A dispatch-side fix cannot be deployed while the fleet is busy, because deploying restarts `dispatch-api`, and `main.py:284-293` cancels every in-flight run's task on shutdown while `db.py:173-196` then marks each one `failed` on the way back up. So a restart destroys live agent work and actively reports it as failed.

That produced a deadlock today. The re-adoption fix (`cb7491a` — a host adopting every rollout in the fleet on startup) was cut as 2.0.2 and could not ship, because all four hosts were busy. Two more fixes queued behind it. The fix for "deploys are dangerous" was itself blocked by deploys being dangerous.

The only existing way to take a host out of rotation is `DELETE /api/settings/dispatch/hosts/{id}`, which is destructive: it drops the row, loses the `api_key`, and orphans the in-flight runs whose records point at that host.

## Three corrections to the premise

Worth stating because they shrink the work considerably.

**`deploy.sh` is already serial and already per-host.** `deploy.sh:250-252` is a plain `for host in ${HOSTS}` loop that blocks on each host's health probe, and `deploy.sh:34-38` already honours `DISPATCH_HOST=<one>` to target a single host. The per-host deploy primitive exists. What is missing is any way to stop the *other* hosts taking new work while you use it.

**`active_runs` is an honest idle signal.** `_start_rollout_loop` registers its task in `_active_processes` (`agent-gtd-dispatch/main.py:2961-2964`), so a host driving a rollout counts as busy even when it is only waiting between waves. `active_runs == 0` genuinely means idle, including no rollout loop.

**The re-adoption bug is narrower than it looked.** 2.0.2 is already live on jason-precision, and the bug is startup-only. The residual exposure is an unattended `Restart=on-failure` bounce of a host still on 2.0.1 — which drain does **not** cover, because nobody is there to drain first.

## Design

One nullable column, one router clause, two CLI verbs. No new service, no state machine, no scheduler.

### Schema

`drain_reason TEXT` on `dispatch_hosts`. `NULL` means accepting work; any non-NULL string means out of rotation, and the string says why.

The reason string *is* the flag. Two states, no enum, no lifecycle. An unexplained drain is indistinguishable from a host that is quietly broken — which is precisely the confusion that cost camera-profiles two runs on a half-provisioned jason-precision this morning — so `--reason` is **mandatory** when draining a host that is not already drained.

It must be added in **three** places in `agent_gtd/src/agent_gtd/database.py`, and missing one fails *silently* because the router reads `host.get("drain_reason")` and a missing column yields `None`, which reads as "not drained":

1. `database.py:230-241` — the `CREATE TABLE dispatch_hosts` in `_SCHEMA_STATEMENTS` (fresh installs, SQLite local mode, and every test).
2. `database.py:492-503` — the duplicate `CREATE TABLE` in the migration path.
3. `database.py:520-536` — an `ALTER TABLE dispatch_hosts ADD COLUMN drain_reason TEXT` appended to `_MIGRATIONS`. Replay-safe: the runner at `database.py:642-648` catches and logs, which is the established idiom for every other `ALTER` in that list.

### Router

One skip clause in the **auto** branch of `pick_dispatch_host` only, placed after the existing `exclude_urls` filter.

The **pinned** branch (`--dispatch-host-id`) is deliberately untouched. That is how an operator exercises a freshly upgraded host, and it is the only way to verify a fix before returning the host to rotation. Drain means "no new *unpinned* work", never "unreachable".

### What drain must NOT break

**A drained host must keep serving `/runs/{id}` for its in-flight runs.** The status poller lives in agent_gtd and polls the host directly; drain is an admission-control decision on the board, and touches nothing on the host.

**A drained host must still return its `api_key` from `get_dispatch_hosts`.** `dispatch_worker.py:578-587` re-fetches the host list to authenticate reconciliation polls, and a drained host filtered out of that read path would strand its own in-flight runs. This is the trap most likely to be introduced by a careless implementation — it needs an explicit test that a drained host still returns its key.

**Peer visibility has to land on all three projections**, not just the local one: `DispatchHostResponse`, and both `mcp_backend` projections (`:1176` and `:2145`). Other sessions dispatch to this fleet concurrently and need to see that a host is parked and why. Test it in HTTP mode, not only local.

### What drain does not cover

**A pinned rollout defeats drain entirely** (`dispatch_service.py:129-134`). A rollout pinned to a host keeps dispatching its children there regardless. So **drained ≠ will-go-idle**, and the operator procedure has to say so.

**Board-side changes still need a board restart.** This covers dispatch-side fixes only. An `agent_gtd` change — like today's `reviewer-autonomous` fix — still bounces the board.

**An unattended crash-restart is not covered.** `Restart=on-failure` bounces a host with nobody there to drain it first.

## Operator sequence

```bash
agent-gtd list-dispatch-hosts          # shows draining + reason per host

agent-gtd drain-host pironman01   --reason "rolling deploy 2.0.2 (re-adoption fix cb7491a)"
agent-gtd drain-host r7-research  --reason "rolling deploy 2.0.2"
agent-gtd drain-host r7-server    --reason "rolling deploy 2.0.2"
```

Three hosts parked; in-flight runs continue untouched; jason-precision absorbs all new work.

Wait for a parked host to go idle. **Read `active_runs` twice, ~30s apart, before believing a zero** — `_pending_queue` (`main.py:139`) is an in-process list that is never exposed on `/info`, and `_try_start_pending` (`main.py:1011-1032`) promotes queued runs the instant a slot frees. A single zero can be a gap between two runs.

```bash
curl -s http://pironman01:8100/info | jq '{active_runs, max_concurrent_runs}'
DISPATCH_HOST=pironman01 EXPECT_VERSION=2.0.2 ./deploy.sh
agent-gtd dispatch-item <id> --dispatch-host-id <pironman01-id>   # verify while still drained
agent-gtd undrain-host pironman01
```

Repeat per host. The fleet never drops below one host accepting work.

Hosts should be addressable by **label**, not UUID — operators think in `pironman01`, the registry thinks in `c941111f-…`. A ~20-line resolver (exact id → unique label → unique URL substring → error listing candidates) removes a lookup from every command.

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
