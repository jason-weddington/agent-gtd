"""Rollout manager service: legality validation, planner call, DAG persistence."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from agent_gtd.database import decode_file_specs, decode_json_list, row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.models import ManagerPhase, RolloutItemOutcome
from agent_gtd.services.item_service import get_item, get_unresolved_blockers
from agent_gtd.services.settings_service import get_dispatch_config
from agent_gtd.util.tasks import supervise_task

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(("completed", "halted", "skipped"))
_ACTIVE_ITEM_STATUSES = frozenset(("pending", "ready", "dispatched"))
_HALTED_FROM_STATUSES = ("pending", "ready", "dispatched")

# Terminal statuses for claude_runs rows.  A run is "in-flight" when its
# status is NOT in this set (i.e. pending / cloning / running).
_TERMINAL_RUN_STATUSES = frozenset(("success", "failed", "cancelled", "timeout"))


# ---------------------------------------------------------------------------
# Legality contract validation
# ---------------------------------------------------------------------------


async def validate_legality_contract(
    db: DbPool,
    user_id: str,
    item_ids: list[str],
) -> None:
    """Validate the legality contract for all items in a prospective wave.

    Checks **every** item before raising so the caller gets a complete picture
    of every failure.  Raises :class:`~agent_gtd.exceptions.LegalityContractError`
    if any item fails.

    Per-item rules:
        1. Item exists and is accessible to *user_id* (owned or shared project).
        2. ``item.status == "ready"``.
        3. ``acceptance_criteria`` structured field is non-empty.
        4. ``files_to_modify`` structured field is non-empty.
        4b. ``build_engine`` is set (required for groomed items).
        5. No unresolved blockers outside *item_ids*.

    Cross-set rules:
        6. All items belong to the same project.

    Args:
        db: Database connection pool.
        user_id: ID of the calling user.
        item_ids: IDs of the items to validate (must not be empty).

    Raises:
        LegalityContractError: If one or more items fail any rule.
    """
    item_id_set = set(item_ids)
    failures: list[dict[str, Any]] = []
    found_items: list[dict[str, Any]] = []

    for item_id in item_ids:
        item_failures: list[str] = []
        try:
            item = await get_item(db, user_id, item_id)
        except NotFoundError:
            failures.append(
                {
                    "item_id": item_id,
                    "title": "(unknown)",
                    "failures": ["Item not found or not accessible"],
                }
            )
            continue

        found_items.append(item)
        title = str(item.get("title", ""))

        # Rule 2: status must be "ready"
        if str(item.get("status", "")) != "ready":
            item_failures.append(f"status is '{item.get('status')}'; must be 'ready'")

        # Rule 3: acceptance_criteria structured field must be non-empty
        ac = decode_json_list(str(item.get("acceptance_criteria") or "[]"))
        if not ac:
            item_failures.append("acceptance_criteria is empty; item not yet groomed")

        # Rule 4: files_to_modify structured field must be non-empty
        ftm = decode_file_specs(str(item.get("files_to_modify") or "[]"))
        if not ftm:
            item_failures.append("files_to_modify is empty; item not yet groomed")

        # Rule 4b: build_engine must be set for groomed items (AC-4)
        if not item.get("build_engine"):
            item_failures.append("build_engine must be set for groomed items")

        # Rule 5: No unresolved external blockers (blockers in item_ids are OK)
        unresolved = await get_unresolved_blockers(db, item_id)
        external_blockers = [b for b in unresolved if b["id"] not in item_id_set]
        if external_blockers:
            blocker_list = ", ".join(
                f"'{b['title']}' ({b['status']})" for b in external_blockers
            )
            item_failures.append(f"has unresolved external blockers: {blocker_list}")

        if item_failures:
            failures.append(
                {"item_id": item_id, "title": title, "failures": item_failures}
            )

    # Rule 6: All items must share the same project_id
    project_ids = {str(item.get("project_id") or "") for item in found_items}
    if len(project_ids) > 1:
        # Multiple project IDs found — add a cross-project failure to each item
        for item in found_items:
            pid = str(item.get("project_id") or "")
            item_id = str(item["id"])
            mismatch_msg = f"project_id={pid!r} — all items must share the same project"
            existing = next((f for f in failures if f["item_id"] == item_id), None)
            if existing is not None:
                existing_failures = list(existing.get("failures") or [])
                if mismatch_msg not in existing_failures:
                    existing_failures.append(mismatch_msg)
                    existing["failures"] = existing_failures
            else:
                failures.append(
                    {
                        "item_id": item_id,
                        "title": str(item.get("title", "")),
                        "failures": [mismatch_msg],
                    }
                )

    if failures:
        raise LegalityContractError(failures)


# ---------------------------------------------------------------------------
# Planner HTTP call
# ---------------------------------------------------------------------------


async def call_planner(
    dispatch_url: str,
    api_key: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Call the remote planner endpoint and return the DAG.

    Sends ``{"item_ids": [...]}`` to ``POST {dispatch_url}/plan`` and returns
    the parsed response body.

    Args:
        dispatch_url: Base URL of the dispatch service (e.g.
            ``"https://dispatch.example.com"``).
        api_key: API key sent as ``Authorization: Bearer <api_key>``.
        item_ids: IDs of the items to plan.

    Returns:
        Planner response dict with shape::

            {
                "nodes": list[str],
                "edges": [{"from_item_id": str, "to_item_id": str}, ...],
                "planner_model": str,
            }

    Raises:
        RuntimeError: On HTTP error (non-2xx), network error, or timeout.
    """
    url = f"{dispatch_url.rstrip('/')}/plan"
    headers = {"Authorization": f"Bearer {api_key}"}
    body: dict[str, list[str]] = {"item_ids": item_ids}

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Planner HTTP error {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Planner request timed out: {exc}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Planner network error: {exc}") from exc


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def plan_rollout(
    db: DbPool,
    user_id: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Orchestrate the full plan_rollout flow.

    Validates the legality contract, checks dispatch configuration, creates a
    rollout, calls the remote planner, persists the DAG, and returns a plan
    summary for the lead to confirm before execution begins.

    Args:
        db: Database connection pool.
        user_id: ID of the calling user (the lead).
        item_ids: IDs of the items to include in the wave.

    Returns:
        Dict with keys: ``rollout_id``, ``status``, ``plan`` (nodes + edges),
        ``planner_model``, ``item_count``, ``per_item``.

    Raises:
        ValidationError: If ``item_ids`` is empty or dispatch service is not
            configured for the project owner.
        LegalityContractError: If any item fails the legality contract.
        RuntimeError: If the planner HTTP call fails.  The rollout is updated
            to ``status='failed'`` before the exception propagates.
    """
    if not item_ids:
        raise ValidationError("item_ids must not be empty")

    # Step 1: Validate legality contract for every item.
    # Raises LegalityContractError (with all failures collected) if any fail.
    await validate_legality_contract(db, user_id, item_ids)

    # Step 2: Fetch items to obtain project_id and item titles.
    items: list[dict[str, Any]] = []
    for item_id in item_ids:
        item = await get_item(db, user_id, item_id)
        items.append(item)

    project_id = str(items[0].get("project_id") or "")

    # Step 3: Look up dispatch config for the project owner.
    project_row = await db.fetchrow(
        "SELECT user_id FROM projects WHERE id = $1", project_id
    )
    if project_row is None:
        raise ValidationError(f"Project {project_id!r} not found")
    owner_user_id = str(project_row["user_id"])

    dispatch_config = await get_dispatch_config(db, owner_user_id)
    if dispatch_config is None:
        raise ValidationError("Dispatch service not configured")

    # Step 4: Create the rollout with status='planning'.
    rollout_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_rollouts "
        "(id, project_id, lead_user_id, status, started_at, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rollout_id,
        project_id,
        user_id,
        "planning",
        now,
        now,
        now,
    )

    # Step 5: Call the remote planner.
    try:
        planner_result = await call_planner(
            dispatch_config["url"],
            dispatch_config["api_key"],
            item_ids,
        )
    except RuntimeError as exc:
        error_detail = str(exc)
        err_now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE autonomous_rollouts "
            "SET status = $1, halt_reason = $2, updated_at = $3 "
            "WHERE id = $4",
            "failed",
            error_detail,
            err_now,
            rollout_id,
        )
        raise

    nodes: list[str] = planner_result["nodes"]
    edges: list[dict[str, str]] = planner_result["edges"]
    planner_model: str = planner_result["planner_model"]

    # Step 6: Persist the rollout_plans row.
    plan_id = str(uuid.uuid4())
    plan_now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO rollout_plans "
        "(id, rollout_id, version, nodes, edges, planner_model, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        1,
        json.dumps(nodes),
        json.dumps(edges),
        planner_model,
        plan_now,
    )

    # Step 7: Compute in-degree for each node (to determine ready vs pending).
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    for edge in edges:
        to_id = edge.get("to_item_id", "")
        if to_id in in_degree:
            in_degree[to_id] = in_degree[to_id] + 1

    # Step 8: Insert rollout_items rows.
    for node_id in nodes:
        item_status = "ready" if in_degree.get(node_id, 0) == 0 else "pending"
        await db.execute(
            "INSERT INTO rollout_items (rollout_id, item_id, status) "
            "VALUES ($1, $2, $3)",
            rollout_id,
            node_id,
            item_status,
        )

    # Step 9: Promote the rollout to 'pending'.
    done_now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE autonomous_rollouts SET status = $1, updated_at = $2 WHERE id = $3",
        "pending",
        done_now,
        rollout_id,
    )

    # Emit wave_planned event and publish via SSE (resolves TODO f0689a01).
    wave_planned_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_planned",
        actor="manager",
        payload={
            "item_count": len(nodes),
            "planner_model": planner_model,
            "plan_id": plan_id,
        },
    )
    _publish_rollout_event(db, user_id, wave_planned_event, project_id)

    # Step 10: Build per_item list with predecessor mapping.
    predecessors: dict[str, list[str]] = {nid: [] for nid in nodes}
    for edge in edges:
        to_id = edge.get("to_item_id", "")
        from_id = edge.get("from_item_id", "")
        if to_id in predecessors:
            predecessors[to_id].append(from_id)

    item_titles: dict[str, str] = {
        str(item["id"]): str(item.get("title", "")) for item in items
    }

    per_item = [
        {
            "item_id": node_id,
            "title": item_titles.get(node_id, ""),
            "predecessors": predecessors.get(node_id, []),
        }
        for node_id in nodes
    ]

    return {
        "rollout_id": rollout_id,
        "status": "pending",
        "plan": {"nodes": nodes, "edges": edges},
        "planner_model": planner_model,
        "item_count": len(nodes),
        "per_item": per_item,
    }


# ---------------------------------------------------------------------------
# In-flight build run helpers (derived-on-read, never persisted)
# ---------------------------------------------------------------------------


async def _fetch_in_flight_build_runs(
    db: DbPool,
    rollout_id: str,
) -> list[dict[str, Any]]:
    """Return non-terminal child build runs for *rollout_id*.

    Performs a JOIN of rollout_items -> claude_runs and filters to rows whose
    claude_runs.status is NOT in ``_TERMINAL_RUN_STATUSES`` (i.e. pending /
    cloning / running).  The result is a list of dicts with keys
    ``runId``, ``itemId``, and ``status`` — camelCase so the shape is
    identical for both the HTTP JSON response and the MCP tool dict.

    Args:
        db: Database pool.
        rollout_id: The rollout whose in-flight runs to fetch.

    Returns:
        List of ``{runId, itemId, status}`` dicts, possibly empty.
    """
    rows = await db.fetch(
        """
        SELECT cr.id AS run_id, ri.item_id, cr.status
        FROM rollout_items ri
        JOIN claude_runs cr ON cr.id = ri.claude_run_id
        WHERE ri.rollout_id = $1
          AND cr.status NOT IN ('success', 'failed', 'cancelled', 'timeout')
        """,
        rollout_id,
    )
    return [
        {
            "runId": str(r["run_id"]),
            "itemId": str(r["item_id"]),
            "status": str(r["status"]),
        }
        for r in rows
    ]


async def _fetch_in_flight_build_runs_batch(
    db: DbPool,
    rollout_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Batch variant of :func:`_fetch_in_flight_build_runs` for multiple rollouts.

    Returns a mapping of rollout_id -> list of ``{runId, itemId, status}`` dicts.
    Missing keys (no in-flight runs) map to empty lists.

    Args:
        db: Database pool.
        rollout_ids: The rollout IDs to query.

    Returns:
        Dict keyed by rollout_id.
    """
    result: dict[str, list[dict[str, Any]]] = {rid: [] for rid in rollout_ids}
    if not rollout_ids:
        return result

    placeholders = ", ".join(f"${i + 1}" for i in range(len(rollout_ids)))
    rows = await db.fetch(
        f"""
        SELECT ri.rollout_id, cr.id AS run_id, ri.item_id, cr.status
        FROM rollout_items ri
        JOIN claude_runs cr ON cr.id = ri.claude_run_id
        WHERE ri.rollout_id IN ({placeholders})
          AND cr.status NOT IN ('success', 'failed', 'cancelled', 'timeout')
        """,  # noqa: S608
        *rollout_ids,
    )
    for r in rows:
        rid = str(r["rollout_id"])
        if rid in result:
            result[rid].append(
                {
                    "runId": str(r["run_id"]),
                    "itemId": str(r["item_id"]),
                    "status": str(r["status"]),
                }
            )
    return result


# ---------------------------------------------------------------------------
# Executor helpers (advance/complete/halt/replan)
# ---------------------------------------------------------------------------


async def _get_rollout(db: DbPool, user_id: str, rollout_id: str) -> dict[str, Any]:
    """Fetch the rollout row and verify the caller owns it.

    Args:
        db: Database pool.
        user_id: The calling user's ID.
        rollout_id: The rollout to load.

    Returns:
        The rollout dict.

    Raises:
        NotFoundError: If not found or not owned by the caller.
    """
    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    if row is None:
        raise NotFoundError("Rollout", rollout_id)
    wave = row_to_dict(row)
    if wave["lead_user_id"] != user_id:
        raise NotFoundError("Rollout", rollout_id)
    return wave


async def _get_latest_plan(db: DbPool, rollout_id: str) -> dict[str, Any] | None:
    """Fetch the highest-version rollout_plans row for this run."""
    row = await db.fetchrow(
        "SELECT * FROM rollout_plans WHERE rollout_id = $1"
        " ORDER BY version DESC LIMIT 1",
        rollout_id,
    )
    return row_to_dict(row) if row else None


async def _next_event_seq(db: DbPool, rollout_id: str) -> int:
    """Return the next available sequence number for a wave event."""
    row = await db.fetchrow(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq"
        " FROM rollout_events WHERE rollout_id = $1",
        rollout_id,
    )
    return int(row["next_seq"]) if row else 1


async def _append_rollout_event(
    db: DbPool,
    rollout_id: str,
    kind: str,
    actor: str,
    payload: dict[str, Any],
    decision_rule: str = "",
) -> dict[str, Any]:
    """Append a row to rollout_events with an auto-incrementing seq.

    Args:
        db: Database pool.
        rollout_id: The rollout this event belongs to.
        kind: Event kind string (e.g. 'item_outcome', 'wave_halted').
        actor: Actor string (e.g. 'manager', 'human').
        payload: JSON-serialisable payload dict.
        decision_rule: Optional rule name that triggered an auto-approval
            (default empty string, stored in the decision_rule column).

    Returns:
        The inserted wave event as a dict with keys: id, rollout_id, seq,
        ts, kind, actor, decision_rule, payload.
    """
    event_id = str(uuid.uuid4())
    seq = await _next_event_seq(db, rollout_id)
    ts = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO rollout_events"
        " (id, rollout_id, seq, ts, kind, actor, decision_rule, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        event_id,
        rollout_id,
        seq,
        ts,
        kind,
        actor,
        decision_rule,
        json.dumps(payload),
    )
    return {
        "id": event_id,
        "rollout_id": rollout_id,
        "seq": seq,
        "ts": ts,
        "kind": kind,
        "actor": actor,
        "decision_rule": decision_rule,
        "payload": payload,
    }


def _publish_rollout_event(
    db: DbPool,
    lead_user_id: str,
    rollout_event: dict[str, Any],
    project_id: str,
) -> None:
    """Fire-and-forget SSE event publish for rollout events (best effort).

    Follows the same pattern as ``_publish_run_event`` in dispatch_worker.py.
    Wraps the publish coroutine in ``asyncio.create_task`` so callers are never
    blocked, and swallows any exceptions so rollout mutations are never affected.

    Args:
        db: Database pool (passed through to EventBus.publish for persistence).
        lead_user_id: The rollout's lead user ID (becomes the event owner).
        rollout_event: Full rollout event dict as returned by
            ``_append_rollout_event`` (keys: id, rollout_id, seq, ts, kind,
            actor, decision_rule, payload).
        project_id: The rollout's project ID — triggers project-member
            fan-out in the event bus.
    """
    from agent_gtd.event_bus import get_event_bus
    from agent_gtd.event_helpers import best_effort_publish

    bus = get_event_bus()
    supervise_task(
        asyncio.create_task(
            best_effort_publish(
                bus,
                db,
                user_id=lead_user_id,
                event_type="rollout_event",
                entity_type="rollout",
                entity_id=rollout_event["rollout_id"],
                project_id=project_id,
                payload=rollout_event,
                context={"rollout_id": rollout_event["rollout_id"]},
            )
        ),
        context={
            "rollout_id": rollout_event["rollout_id"],
            "event_type": "rollout_event",
        },
    )


def _build_predecessor_map(
    edges: list[dict[str, str]],
) -> dict[str, list[str]]:
    """Build item_id → [predecessor_ids] from DAG edge list.

    Edges have the shape ``{"from_item_id": pred_id, "to_item_id": succ_id}``.
    """
    preds: dict[str, list[str]] = {}
    for edge in edges:
        to_id = edge["to_item_id"]
        from_id = edge["from_item_id"]
        preds.setdefault(to_id, []).append(from_id)
    return preds


def _build_successor_map(
    edges: list[dict[str, str]],
) -> dict[str, list[str]]:
    """Build item_id → [successor_ids] from DAG edge list."""
    succs: dict[str, list[str]] = {}
    for edge in edges:
        from_id = edge["from_item_id"]
        to_id = edge["to_item_id"]
        succs.setdefault(from_id, []).append(to_id)
    return succs


def _dfs_descendants(item_id: str, succs: dict[str, list[str]]) -> set[str]:
    """Return all descendants of *item_id* (including itself) via DFS."""
    visited: set[str] = set()
    stack = [item_id]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(succs.get(node, []))
    return visited


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def advance_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Read-only graph traversal: classify wave items.

    Computes which items are ready to dispatch (next_ready), already running
    (in_progress), or blocked by unfinished predecessors (blocked).  Also
    reports whether the entire graph is complete.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to inspect.

    Returns:
        Dict with keys:
          - next_ready (list[str]): item IDs with pending/ready status whose
            predecessors are all in {completed, skipped}.
          - in_progress (list[str]): item IDs with status 'dispatched'.
          - blocked (list[str]): item IDs with status 'pending' whose
            predecessors include at least one non-terminal item.
          - graph_complete (bool): True if every item is in a terminal state.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not 'running'.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {rollout_id} is not running (status={wave['status']})"
        )

    rows = await db.fetch(
        "SELECT item_id, status FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    items: dict[str, str] = {r["item_id"]: r["status"] for r in rows}

    plan = await _get_latest_plan(db, rollout_id)
    edges: list[dict[str, str]] = json.loads(plan["edges"]) if plan else []
    preds = _build_predecessor_map(edges)

    next_ready: list[str] = []
    in_progress: list[str] = []
    blocked: list[str] = []

    for item_id, status in items.items():
        if status == "dispatched":
            in_progress.append(item_id)
        elif status in ("pending", "ready"):
            item_preds = preds.get(item_id, [])
            all_done = all(
                items.get(p, "pending") in _TERMINAL_STATUSES for p in item_preds
            )
            if all_done:
                next_ready.append(item_id)
            else:
                blocked.append(item_id)
        # Terminal items (completed, halted, skipped) are omitted from all lists.

    graph_complete = all(s in _TERMINAL_STATUSES for s in items.values())

    return {
        "next_ready": next_ready,
        "in_progress": in_progress,
        "blocked": blocked,
        "graph_complete": graph_complete,
    }


async def complete_item_in_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    item_id: str,
    outcome: RolloutItemOutcome | str,
    merge_actor: str = "",
    decision_rule: str = "",
) -> dict[str, Any]:
    """Mark a dispatched wave item as done and unblock downstream items.

    After the item is marked terminal, each downstream item whose only
    remaining blocking predecessor was this one is transitioned from
    ``pending`` → ``ready``.  If all items in the wave are now in terminal
    states the rollout itself is closed (status → 'completed').

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout.
        item_id: ID of the rollout_items row to complete.
        outcome: One of ``"completed"``, ``"halted"``, ``"skipped"``.
        merge_actor: Who merged the PR (``"human"``,
            ``"manager-allowlist"``, ``"manager+human-fixup"``, or empty).
            Stored on the rollout_items row.
        decision_rule: Allowlist rule name that triggered auto-approval
            (from the executor classifier). Stored in the event payload.

    Returns:
        Dict with keys:
          - wave_plan_item (dict): The updated rollout_items row.
          - newly_ready (list[str]): Item IDs transitioned to 'ready'.
          - graph_complete (bool): True when the wave closed as a result of
            this call (all items are now terminal); False otherwise.

    Raises:
        NotFoundError: If wave or item not found or caller doesn't own it.
        ValidationError: If the item is not in 'ready' or 'dispatched' status,
            or if outcome is invalid.

    State paths supported:
        - Child-build path: ``ready → dispatched → terminal`` (normal flow where
          a build agent is dispatched and completes the item).
        - Inline-management path: ``ready → terminal`` (manage agent handles the
          item directly without dispatching a child build, e.g. trivial changes).
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    project_id = str(wave["project_id"])

    item_row = await db.fetchrow(
        "SELECT * FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    if item_row is None:
        raise NotFoundError("RolloutItem", f"{rollout_id}/{item_id}")
    if item_row["status"] not in ("ready", "dispatched"):
        raise ValidationError(
            f"Item {item_id} has status '{item_row['status']}' — "
            "only 'ready' or 'dispatched' items can be completed in a rollout"
        )

    now = datetime.now(UTC).isoformat()

    if merge_actor:
        await db.execute(
            "UPDATE rollout_items"
            " SET status = $1, completed_at = $2, merge_actor = $3"
            " WHERE rollout_id = $4 AND item_id = $5",
            outcome,
            now,
            merge_actor,
            rollout_id,
            item_id,
        )
    else:
        await db.execute(
            "UPDATE rollout_items"
            " SET status = $1, completed_at = $2"
            " WHERE rollout_id = $3 AND item_id = $4",
            outcome,
            now,
            rollout_id,
            item_id,
        )

    # Release per-item wave lock
    from agent_gtd.services.rollout_lock_service import release_rollout_item

    await release_rollout_item(db, rollout_id, item_id)

    # Cascade GTD item status to 'done' when outcome is completed
    if outcome == "completed":
        from agent_gtd.services.item_service import complete_item

        await complete_item(db, user_id, item_id)

    updated_row = await db.fetchrow(
        "SELECT * FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
        rollout_id,
        item_id,
    )
    assert updated_row is not None  # noqa: S101

    # Reload all item statuses (including the just-updated item)
    all_rows = await db.fetch(
        "SELECT item_id, status FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    item_statuses: dict[str, str] = {r["item_id"]: r["status"] for r in all_rows}
    # The DB row was just updated; keep our view consistent.
    item_statuses[item_id] = outcome

    # Load DAG for downstream traversal
    plan = await _get_latest_plan(db, rollout_id)
    edges: list[dict[str, str]] = json.loads(plan["edges"]) if plan else []
    preds = _build_predecessor_map(edges)
    succs = _build_successor_map(edges)

    # Unblock downstream items whose last blocking predecessor was this item
    newly_ready: list[str] = []
    for downstream_id in succs.get(item_id, []):
        if item_statuses.get(downstream_id) != "pending":
            continue
        item_preds = preds.get(downstream_id, [])
        all_done = all(
            item_statuses.get(p, "pending") in _TERMINAL_STATUSES for p in item_preds
        )
        if all_done:
            await db.execute(
                "UPDATE rollout_items SET status = 'ready'"
                " WHERE rollout_id = $1 AND item_id = $2 AND status = 'pending'",
                rollout_id,
                downstream_id,
            )
            item_statuses[downstream_id] = "ready"
            newly_ready.append(downstream_id)

    # Close the wave if every item is now terminal
    graph_complete = all(s in _TERMINAL_STATUSES for s in item_statuses.values())
    if graph_complete:
        await db.execute(
            "UPDATE autonomous_rollouts"
            " SET status = 'completed', ended_at = $1, updated_at = $2"
            " WHERE id = $3",
            now,
            now,
            rollout_id,
        )

    # Emit item_outcome wave event and publish to SSE subscribers
    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="item_outcome",
        actor="manager",
        payload={
            "item_id": item_id,
            "outcome": outcome,
            "decision_rule": decision_rule,
        },
        decision_rule=decision_rule,
    )
    _publish_rollout_event(db, user_id, wave_event, project_id)

    # If all items are done, emit wave_completed lifecycle event (AC-5)
    if graph_complete:
        wave_completed_event = await _append_rollout_event(
            db,
            rollout_id,
            kind="wave_completed",
            actor="manager",
            payload={"total_items": len(item_statuses)},
        )
        _publish_rollout_event(db, user_id, wave_completed_event, project_id)

    return {
        "rollout_item": row_to_dict(updated_row),
        "newly_ready": newly_ready,
        "graph_complete": graph_complete,
    }


async def halt_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    reason: str,
    comment: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    """Terminal halt: stop the wave, release locks, post comment, emit event.

    Transitions all in-flight items to 'halted', releases all wave-scoped item
    locks, posts a GTD comment on the project, and appends a ``wave_halted``
    event whose payload includes the offending item ID (if any) and the ID of
    the created comment (for the halt card UI to display without a round trip).

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to halt.
        reason: Short machine-readable halt reason (e.g. ``"merge_rejected"``).
        comment: Optional human-readable context appended to the GTD comment.
        item_id: Optional ID of the item that triggered the halt.  Stored in
            the event payload so the halt card can wire the "Skip this item"
            button.

    Returns:
        The updated autonomous_rollouts row dict.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not 'running'.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    if wave["status"] not in {"running", "pending"}:
        raise ValidationError(
            f"Wave {rollout_id} is not running (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await db.execute(
        "UPDATE autonomous_rollouts"
        " SET status = 'halted', halt_reason = $1, ended_at = $2, updated_at = $3"
        " WHERE id = $4",
        reason,
        now,
        now,
        rollout_id,
    )

    await db.execute(
        "UPDATE rollout_items SET status = 'halted'"
        " WHERE rollout_id = $1 AND status IN ('pending', 'ready', 'dispatched')",
        rollout_id,
    )

    # Release all wave-scoped item locks (item c85cae60)
    from agent_gtd.services.rollout_lock_service import release_rollout_locks

    await release_rollout_locks(db, rollout_id)

    # Post a GTD comment on the project
    from agent_gtd.services.comment_service import create_comment

    content_parts = [f"Rollout halted: {reason}"]
    if comment:
        content_parts.append(comment)
    comment_md = "\n\n".join(content_parts)

    comment_result = await create_comment(
        db,
        user_id,
        project_id=str(wave["project_id"]),
        content_markdown=comment_md,
        created_by="wave-manager",
    )
    comment_id = str(comment_result["id"])

    # AC-4: additionally post a brief comment on the *offending item* so the
    # lead sees the halt when reviewing the item's comment thread.
    if item_id:
        item_comment_md = (
            f"Rollout halted ({reason}). "
            f"See project-level halt comment `{comment_id}` for full context."
        )
        try:
            await create_comment(
                db,
                user_id,
                item_id=item_id,
                content_markdown=item_comment_md,
                created_by="wave-manager",
            )
        except Exception:
            logger.warning(
                "halt_rollout: failed to post item-level halt comment "
                "(item_id=%s rollout_id=%s)",
                item_id,
                rollout_id,
                exc_info=True,
            )

    # Emit comment_posted event for the halt reason comment
    comment_posted_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="comment_posted",
        actor="manager",
        payload={
            "comment_id": comment_id,
            "comment_type": "halt_reason",
        },
    )
    _publish_rollout_event(db, user_id, comment_posted_event, str(wave["project_id"]))

    # Emit wave_halted event and publish to SSE subscribers
    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_halted",
        actor="manager",
        payload={
            "reason": reason,
            "item_id": item_id,
            "comment_id": comment_id,
        },
    )
    _publish_rollout_event(db, user_id, wave_event, str(wave["project_id"]))

    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def get_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Fetch a rollout by ID (caller must be the lead_user_id).

    Args:
        db: Database pool.
        user_id: Calling user's ID — must match lead_user_id.
        rollout_id: The rollout to fetch.

    Returns:
        The autonomous_rollouts row as a dict, augmented with the computed
        ``inFlightBuildRuns`` field (list of ``{runId, itemId, status}`` for
        child build runs that are currently non-terminal).

    Raises:
        NotFoundError: If not found or not owned by the caller.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    in_flight = await _fetch_in_flight_build_runs(db, rollout_id)
    return {**wave, "inFlightBuildRuns": in_flight}


async def list_rollouts(
    db: DbPool,
    user_id: str,
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List rollouts owned by the caller, with optional filters.

    Args:
        db: Database pool.
        user_id: Calling user's ID — only rollouts with this lead_user_id
            are returned.
        project_id: If provided, return only rollouts for this project.
        status: If provided, return only rollouts with this status
            (e.g. ``"running"``, ``"halted"``, ``"completed"``).
        limit: Maximum number of rollouts to return (default 20, max 100).

    Returns:
        List of autonomous_rollouts row dicts ordered by created_at DESC.
        Each dict includes the computed ``inFlightBuildRuns`` field
        (list of ``{runId, itemId, status}`` for non-terminal child build runs).
    """
    clamped_limit = min(max(1, limit), 100)

    query = "SELECT * FROM autonomous_rollouts WHERE lead_user_id = $1"
    params: list[Any] = [user_id]
    idx = 2

    if project_id is not None:
        query += f" AND project_id = ${idx}"
        params.append(project_id)
        idx += 1

    if status is not None:
        query += f" AND status = ${idx}"
        params.append(status)
        idx += 1

    query += f" ORDER BY created_at DESC LIMIT ${idx}"
    params.append(clamped_limit)

    rows = await db.fetch(query, *params)
    waves = [row_to_dict(r) for r in rows]

    # Batch-fetch in-flight build runs for all rollouts in one query.
    rollout_ids = [w["id"] for w in waves]
    in_flight_map = await _fetch_in_flight_build_runs_batch(db, rollout_ids)

    return [{**w, "inFlightBuildRuns": in_flight_map[w["id"]]} for w in waves]


async def get_rollout_plan(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Fetch the latest rollout plan with per-item progress and titles.

    Returns the DAG (nodes, edges) from the latest rollout_plans row along
    with a joined list of rollout_items enriched with item titles and
    derived predecessor lists.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must match lead_user_id.
        rollout_id: The rollout to fetch the plan for.

    Returns:
        Dict with keys:
          - rollout_id (str)
          - plan_version (int)
          - planner_model (str)
          - nodes (list[str]): Ordered item IDs from the plan.
          - edges (list[dict]): Each dict has from_item_id and to_item_id.
          - items (list[dict]): Each has item_id, title, rollout_status,
            and predecessors (list[str] of item_ids that must complete first).

    Raises:
        NotFoundError: If rollout not found, not owned by caller, or has no
            plan yet.
    """
    # Verify ownership
    await _get_rollout(db, user_id, rollout_id)

    plan = await _get_latest_plan(db, rollout_id)
    if plan is None:
        raise NotFoundError("RolloutPlan", rollout_id)

    # Decode JSON columns
    nodes: list[str] = (
        json.loads(plan["nodes"]) if isinstance(plan["nodes"], str) else plan["nodes"]
    )
    edges: list[dict[str, str]] = (
        json.loads(plan["edges"]) if isinstance(plan["edges"], str) else plan["edges"]
    )

    # Build predecessor map: to_item_id → list of from_item_ids
    predecessor_map: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        to_id = edge["to_item_id"]
        from_id = edge["from_item_id"]
        if to_id in predecessor_map:
            predecessor_map[to_id].append(from_id)

    # Fetch rollout_items joined with item titles
    item_rows = await db.fetch(
        "SELECT ri.item_id, ri.status, i.title"
        " FROM rollout_items ri"
        " JOIN items i ON i.id = ri.item_id"
        " WHERE ri.rollout_id = $1",
        rollout_id,
    )

    items = [
        {
            "item_id": str(row["item_id"]),
            "title": row["title"],
            "rollout_status": row["status"],
            "predecessors": predecessor_map.get(str(row["item_id"]), []),
        }
        for row in item_rows
    ]

    return {
        "rollout_id": rollout_id,
        "plan_version": plan["version"],
        "planner_model": plan.get("planner_model", ""),
        "nodes": nodes,
        "edges": edges,
        "items": items,
    }


async def relaunch_manage_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Atomically increment manage_retry_count and emit a manage_relaunched event.

    Called by the dispatch service when a manage subprocess exits unexpectedly
    and a new manage agent will be started.  The incremented count is used by
    the dispatch service to decide whether to retry or halt.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the rollout's lead_user_id.
        rollout_id: The rollout whose manager is being relaunched.

    Returns:
        The updated autonomous_rollouts row as a dict (includes manage_retry_count).

    Raises:
        NotFoundError: If not found or not owned by the caller.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    project_id = str(wave["project_id"])

    now = datetime.now(UTC).isoformat()
    row = await db.fetchrow(
        "UPDATE autonomous_rollouts"
        " SET manage_retry_count = manage_retry_count + 1, updated_at = $1"
        " WHERE id = $2"
        " RETURNING *",
        now,
        rollout_id,
    )
    assert row is not None  # noqa: S101
    updated = row_to_dict(row)

    new_count = int(updated["manage_retry_count"])

    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="manage_relaunched",
        actor="dispatch",
        payload={"retry_count": new_count},
    )
    _publish_rollout_event(db, user_id, wave_event, project_id)

    return updated


async def cancel_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    reason: str,
) -> dict[str, Any]:
    """Cancel a wave, marking remaining items as skipped.

    Transitions the wave to ``cancelled`` status and marks any non-terminal
    wave plan items as ``skipped``.  Accepts waves in any non-terminal status
    (pending, planning, running, halted, failed).  Idempotent — cancelling an
    already-cancelled wave returns success without error.

    The active-waves query (``get_active_wave_for_project``) does not include
    ``cancelled`` waves, so the halt card disappears from the dashboard once
    this operation completes.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to cancel.
        reason: Short human-readable reason for cancellation.

    Returns:
        The updated autonomous_rollouts row dict.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave is in a terminal non-cancellable status
            (``done`` / ``completed``).
    """
    wave = await _get_rollout(db, user_id, rollout_id)

    # Idempotent: already cancelled is a no-op success.
    if wave["status"] == "cancelled":
        row = await db.fetchrow(
            "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
        )
        assert row is not None  # noqa: S101
        return row_to_dict(row)

    cancellable_statuses = {"pending", "planning", "running", "halted", "failed"}
    if wave["status"] not in cancellable_statuses:
        raise ValidationError(
            f"Wave {rollout_id} cannot be cancelled (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await db.execute(
        "UPDATE autonomous_rollouts"
        " SET status = 'cancelled', halt_reason = $1, ended_at = $2, updated_at = $3"
        " WHERE id = $4",
        reason,
        now,
        now,
        rollout_id,
    )

    # Mark all non-terminal wave plan items as skipped.
    await db.execute(
        "UPDATE rollout_items SET status = 'skipped'"
        " WHERE rollout_id = $1"
        "   AND status IN ('pending', 'ready', 'dispatched', 'halted')",
        rollout_id,
    )

    # Release any remaining wave-scoped item locks (best effort).
    from agent_gtd.services.rollout_lock_service import release_rollout_locks

    await release_rollout_locks(db, rollout_id)

    # Emit wave_cancelled event and publish to SSE subscribers.
    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_cancelled",
        actor="human",
        payload={"reason": reason},
    )
    _publish_rollout_event(db, user_id, wave_event, str(wave["project_id"]))

    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def start_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    *,
    actor: str = "lead",
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flip a wave from pending → running.

    Provides a way to start a wave without launching a manage agent —
    useful for lead-as-manager debugging and human-driven rollouts.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to start.
        actor: Attribution actor for the ``wave_started`` event (default
            ``"lead"``; dispatch path passes ``"manager"``).
        extra_payload: Additional keys merged into the event payload
            (default ``None`` → empty payload ``{}``).

    Returns:
        The updated autonomous_rollouts row dict.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not ``"pending"``.
    """
    wave = await _get_rollout(db, user_id, rollout_id)

    if wave["status"] != "pending":
        raise ValidationError(
            f"Wave {rollout_id} cannot be started (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await db.execute(
        "UPDATE autonomous_rollouts"
        " SET status = 'running', started_at = $1, updated_at = $2"
        " WHERE id = $3",
        now,
        now,
        rollout_id,
    )

    payload: dict[str, Any] = {}
    if extra_payload:
        payload.update(extra_payload)

    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_started",
        actor=actor,
        payload=payload,
    )
    _publish_rollout_event(db, user_id, wave_event, str(wave["project_id"]))

    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def _call_planner(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Call the dispatch-worker planner to generate a plan for the given items.

    # Uses the same dispatch-worker planner mechanism as plan_rollout.

    Args:
        db: Database pool.
        user_id: Calling user's ID (used to look up dispatch config).
        rollout_id: The rollout being replanned (sent to planner for context).
        item_ids: List of remaining item IDs to plan for.

    Returns:
        Dict from the planner with at least ``nodes``, ``edges``, and
        ``planner_model`` keys.

    Raises:
        ValidationError: If dispatch service is not configured or planner fails.
    """
    import httpx

    from agent_gtd.services.settings_service import get_dispatch_config

    config = await get_dispatch_config(db, user_id)
    if config is None:
        raise ValidationError(
            "Dispatch service not configured — cannot call planner for replan_rollout"
        )

    url = str(config.get("url", "")).rstrip("/")
    api_key = str(config.get("api_key", ""))

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/plan",
            json={"rollout_id": rollout_id, "item_ids": item_ids},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    if resp.status_code != 200:
        raise ValidationError(f"Planner returned {resp.status_code}: {resp.text[:200]}")

    data: dict[str, Any] = resp.json()
    return data


async def replan_rollout(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    from_item: str | None = None,
) -> dict[str, Any]:
    """Re-plan the remaining subgraph for an in-progress rollout.

    Calls the dispatch-worker planner (same mechanism as plan_rollout) scoped
    to the remaining pending/ready items, persists a new rollout_plans version,
    updates item readiness, and emits a ``rollout_replanned`` event.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to replan.
        from_item: Optional item ID to restrict replanning to its downstream
            subgraph (depth-first traversal).

    Returns:
        Dict with keys:
          - old_version (int): The previous plan version.
          - new_version (int): The newly created plan version.
          - new_plan (dict): The new rollout_plans row.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave is not running, there are no remaining items,
            or the planner call fails.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {rollout_id} is not running (status={wave['status']})"
        )

    remaining_rows = await db.fetch(
        "SELECT item_id FROM rollout_items"
        " WHERE rollout_id = $1 AND status IN ('pending', 'ready')",
        rollout_id,
    )
    remaining_ids = [r["item_id"] for r in remaining_rows]
    if not remaining_ids:
        raise ValidationError(f"Wave {rollout_id} has no remaining items to replan")

    # If from_item is given, restrict to its downstream subgraph
    if from_item is not None:
        plan = await _get_latest_plan(db, rollout_id)
        edges_raw: list[dict[str, str]] = json.loads(plan["edges"]) if plan else []
        succs = _build_successor_map(edges_raw)
        descendants = _dfs_descendants(from_item, succs)
        remaining_ids = [i for i in remaining_ids if i in descendants]
        if not remaining_ids:
            raise ValidationError(
                f"No remaining items in the downstream subgraph of {from_item}"
            )

    # Determine next version
    version_row = await db.fetchrow(
        "SELECT COALESCE(MAX(version), 0) AS max_version"
        " FROM rollout_plans WHERE rollout_id = $1",
        rollout_id,
    )
    old_version = int(version_row["max_version"]) if version_row else 0
    new_version = old_version + 1

    # Call the planner for the remaining items
    planner_result = await _call_planner(db, user_id, rollout_id, remaining_ids)

    new_nodes: list[str] = planner_result.get("nodes", remaining_ids)
    new_edges: list[dict[str, str]] = planner_result.get("edges", [])
    planner_model: str = planner_result.get("planner_model", "")

    # Persist new rollout_plans row
    plan_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
        new_version,
        json.dumps(new_nodes),
        json.dumps(new_edges),
        planner_model,
        now,
    )

    # Update readiness of remaining items based on new DAG
    new_preds = _build_predecessor_map(new_edges)
    all_rows = await db.fetch(
        "SELECT item_id, status FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    all_statuses: dict[str, str] = {r["item_id"]: r["status"] for r in all_rows}

    for rid in remaining_ids:
        item_preds = new_preds.get(rid, [])
        all_preds_done = all(
            all_statuses.get(p, "pending") in _TERMINAL_STATUSES for p in item_preds
        )
        if all_preds_done:
            await db.execute(
                "UPDATE rollout_items SET status = 'ready'"
                " WHERE rollout_id = $1 AND item_id = $2 AND status = 'pending'",
                rollout_id,
                rid,
            )
        else:
            # If the new plan re-blocks an item that was 'ready', revert it.
            await db.execute(
                "UPDATE rollout_items SET status = 'pending'"
                " WHERE rollout_id = $1 AND item_id = $2 AND status = 'ready'",
                rollout_id,
                rid,
            )

    # Emit wave_replanned event and publish to SSE subscribers
    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_replanned",
        actor="manager",
        payload={
            "old_version": old_version,
            "new_version": new_version,
        },
    )
    _publish_rollout_event(db, user_id, wave_event, str(wave["project_id"]))

    new_plan_row = await db.fetchrow(
        "SELECT * FROM rollout_plans WHERE id = $1", plan_id
    )
    assert new_plan_row is not None  # noqa: S101

    return {
        "old_version": old_version,
        "new_version": new_version,
        "new_plan": row_to_dict(new_plan_row),
    }


# ---------------------------------------------------------------------------
# Manager state heartbeat (semantic observability)
# ---------------------------------------------------------------------------


async def update_rollout_state(
    db: DbPool,
    user_id: str,
    rollout_id: str,
    phase: ManagerPhase | str,
    current_item_id: str | None = None,
    current_step: str | None = None,
) -> dict[str, Any]:
    """Record the manager's current semantic state for a running wave.

    The manage-mode agent calls this at each major workflow transition so the
    dashboard can display "Manager: merging · working on <item> · last updated
    2 min ago" instead of just elapsed time.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        rollout_id: ID of the rollout to update.
        phase: Current execution phase. Must be one of
            ``warm_up | dispatching | polling | reviewing | merging |
            reconciling_ac | halted``.
        current_item_id: The item ID the manager is currently acting on,
            or ``None`` if not item-specific.
        current_step: Short free-form description of the current step,
            e.g. ``"Merging feat/abc → main"``.

    Returns:
        Dict with keys ``rollout_id``, ``ts``, ``phase``,
        ``current_item_id``, ``current_step``.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not ``'running'``.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {rollout_id} is not running (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        UPDATE autonomous_rollouts
        SET manager_phase = $1,
            manager_current_item_id = $2,
            manager_current_step = $3,
            manager_state_updated_at = $4,
            updated_at = $5
        WHERE id = $6
        """,
        phase,
        current_item_id,
        current_step,
        now,
        now,
        rollout_id,
    )

    rollout_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="manager_state_update",
        actor="manager",
        payload={
            "phase": phase,
            "current_item_id": current_item_id,
            "current_step": current_step,
        },
    )
    # AC-6: publish manager_state_update to SSE subscribers so the banner
    # refreshes in real-time without waiting for the next unrelated event.
    _publish_rollout_event(db, user_id, rollout_event, str(wave["project_id"]))

    return {
        "rollout_id": rollout_id,
        "ts": now,
        "phase": phase,
        "current_item_id": current_item_id,
        "current_step": current_step,
    }


# ---------------------------------------------------------------------------
# Frontend-facing service functions (active wave query, events list, resume)
# ---------------------------------------------------------------------------


async def get_active_rollout_for_project(
    db: DbPool,
    project_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    """Return the most recent active rollout for a project with progress counts.

    An "active" wave has status in {pending, planning, running, halted, failed}.
    Completed/failed waves older than 30 minutes are excluded via the caller's
    interpretation (the route returns 404 if None).

    Args:
        db: Database pool.
        project_id: The project to query.
        user_id: The calling user's ID — must own or be a member of the project.

    Returns:
        Dict with all rollout columns plus ``total_count`` and ``done_count``,
        or ``None`` if no active wave exists.

    Raises:
        NotFoundError: If the project does not exist or the caller cannot access it.
    """
    proj_row = await db.fetchrow(
        "SELECT id, user_id FROM projects WHERE id = $1",
        project_id,
    )
    if proj_row is None:
        raise NotFoundError("Project", project_id)
    owner_id = str(proj_row["user_id"])

    if owner_id != user_id:
        member_row = await db.fetchrow(
            "SELECT 1 FROM project_members WHERE project_id = $1 AND user_id = $2",
            project_id,
            user_id,
        )
        if member_row is None:
            raise NotFoundError("Project", project_id)

    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()

    row = await db.fetchrow(
        """
        SELECT wr.*, i.title AS manager_current_item_title
        FROM autonomous_rollouts wr
        LEFT JOIN items i ON wr.manager_current_item_id = i.id
        WHERE wr.project_id = $1
          AND (
            wr.status IN ('pending', 'planning', 'running', 'halted')
            OR (wr.status IN ('completed', 'failed') AND wr.created_at >= $2)
          )
        ORDER BY wr.created_at DESC
        LIMIT 1
        """,
        project_id,
        cutoff,
    )
    if row is None:
        return None

    wave = row_to_dict(row)

    count_rows = await db.fetch(
        "SELECT status FROM rollout_items WHERE rollout_id = $1",
        wave["id"],
    )
    total_count = len(count_rows)
    done_count = sum(1 for r in count_rows if r["status"] in ("completed", "skipped"))

    return {**wave, "total_count": total_count, "done_count": done_count}


async def get_rollout_events(
    db: DbPool,
    rollout_id: str,
    user_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return wave events for a rollout, ordered by seq descending.

    Args:
        db: Database pool.
        rollout_id: The rollout to query.
        user_id: The calling user's ID — must own the wave's project.
        limit: Maximum number of events to return (capped at 200).

    Returns:
        List of wave_event dicts (newest first).

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
    """
    await _get_rollout(db, user_id, rollout_id)

    effective_limit = min(max(1, limit), 200)
    rows = await db.fetch(
        "SELECT * FROM rollout_events WHERE rollout_id = $1 ORDER BY seq DESC LIMIT $2",
        rollout_id,
        effective_limit,
    )
    result = []
    for r in rows:
        d = row_to_dict(r)
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
        result.append(d)
    return result


async def resume_rollout(
    db: DbPool,
    rollout_id: str,
    answer: str,
    user_id: str,
) -> dict[str, Any]:
    """Resume a halted wave by providing an answer to the blocking question.

    Steps:
    1. Validates wave status is 'halted'.
    2. Posts the answer text as a comment on the project.
    3. Re-locks items that were released during halt.
    4. Transitions halted rollout_items back to 'ready' (if predecessors are
       terminal) or 'pending' (if predecessors are still non-terminal).
    5. Sets rollout.status = 'running'.
    6. Appends a 'wave_resumed' wave_event and emits SSE.

    Args:
        db: Database pool.
        rollout_id: ID of the rollout to resume.
        answer: The human's answer or instruction (posted as a comment).
        user_id: The calling user's ID — must be the wave's lead_user_id.

    Returns:
        Dict with rollout fields plus total_count and done_count.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not 'halted'.
    """
    wave = await _get_rollout(db, user_id, rollout_id)
    if wave["status"] != "halted":
        raise ValidationError(
            f"Wave {rollout_id} is not halted (status={wave['status']})"
        )

    project_id = str(wave["project_id"])
    now = datetime.now(UTC).isoformat()

    from agent_gtd.services.comment_service import create_comment

    resume_comment_result = await create_comment(
        db,
        user_id,
        project_id=project_id,
        content_markdown=answer,
        created_by="human",
    )
    resume_comment_id = str(resume_comment_result["id"])

    # Emit comment_posted event for the resume answer comment
    resume_comment_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="comment_posted",
        actor="human",
        payload={
            "comment_id": resume_comment_id,
            "comment_type": "resume_answer",
        },
    )
    _publish_rollout_event(db, user_id, resume_comment_event, project_id)

    item_rows = await db.fetch(
        "SELECT item_id, status FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    item_statuses: dict[str, str] = {r["item_id"]: r["status"] for r in item_rows}

    plan = await _get_latest_plan(db, rollout_id)
    edges: list[dict[str, str]] = json.loads(plan["edges"]) if plan else []
    preds = _build_predecessor_map(edges)

    newly_ready: list[str] = []
    newly_pending: list[str] = []
    for item_id, status in item_statuses.items():
        if status == "halted":
            item_preds = preds.get(item_id, [])
            all_done = all(
                item_statuses.get(p, "pending") in _TERMINAL_STATUSES
                for p in item_preds
            )
            if all_done:
                newly_ready.append(item_id)
            else:
                newly_pending.append(item_id)

    for item_id in newly_ready:
        await db.execute(
            "UPDATE rollout_items SET status = 'ready'"
            " WHERE rollout_id = $1 AND item_id = $2",
            rollout_id,
            item_id,
        )
    for item_id in newly_pending:
        await db.execute(
            "UPDATE rollout_items SET status = 'pending'"
            " WHERE rollout_id = $1 AND item_id = $2",
            rollout_id,
            item_id,
        )

    from agent_gtd.services.rollout_lock_service import lock_items_for_rollout

    non_terminal_items = [
        item_id
        for item_id, status in item_statuses.items()
        if status not in _TERMINAL_STATUSES
    ]
    if non_terminal_items:
        await lock_items_for_rollout(db, rollout_id, non_terminal_items)

    await db.execute(
        "UPDATE autonomous_rollouts"
        " SET status = 'running', halt_reason = NULL,"
        " ended_at = NULL, updated_at = $1"
        " WHERE id = $2",
        now,
        rollout_id,
    )

    wave_event = await _append_rollout_event(
        db,
        rollout_id,
        kind="wave_resumed",
        actor="human",
        payload={
            "newly_ready": newly_ready,
            "newly_pending": newly_pending,
        },
    )
    _publish_rollout_event(db, user_id, wave_event, project_id)

    row = await db.fetchrow(
        "SELECT * FROM autonomous_rollouts WHERE id = $1", rollout_id
    )
    assert row is not None  # noqa: S101
    wave_data = row_to_dict(row)

    count_rows = await db.fetch(
        "SELECT status FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    total_count = len(count_rows)
    done_count = sum(1 for r in count_rows if r["status"] in ("completed", "skipped"))
    return {**wave_data, "total_count": total_count, "done_count": done_count}


async def get_rollout_activity(
    db: DbPool,
    rollout_id: str,
    user_id: str,
    limit: int = 200,
    before_seq: int | None = None,
) -> dict[str, Any]:
    """Return enriched activity events for a rollout, ordered by seq descending.

    Excludes ``heartbeat`` events (operational noise).  Supports cursor-based
    pagination via ``before_seq``.  Each event is enriched with ``item_id``,
    ``item_title``, and ``run_id`` extracted from the payload / joined tables.

    Args:
        db: Database pool.
        rollout_id: The rollout to query.
        user_id: The calling user's ID — must own the wave.
        limit: Maximum number of events to return (capped at 200).
        before_seq: If provided, return only events with ``seq < before_seq``
            (cursor pagination, most-recent-first order).

    Returns:
        Dict with ``events`` list and ``has_more`` boolean.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
    """
    await _get_rollout(db, user_id, rollout_id)

    effective_limit = min(max(1, limit), 200)
    # Fetch one extra to detect has_more
    fetch_limit = effective_limit + 1

    if before_seq is not None:
        rows = await db.fetch(
            "SELECT * FROM rollout_events"
            " WHERE rollout_id = $1 AND kind != 'heartbeat' AND seq < $2"
            " ORDER BY seq DESC LIMIT $3",
            rollout_id,
            before_seq,
            fetch_limit,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM rollout_events"
            " WHERE rollout_id = $1 AND kind != 'heartbeat'"
            " ORDER BY seq DESC LIMIT $2",
            rollout_id,
            fetch_limit,
        )

    has_more = len(rows) > effective_limit
    rows = rows[:effective_limit]

    # Parse events and decode payloads
    events: list[dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r)
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
        events.append(d)

    # Collect item_ids referenced in payloads
    item_ids: set[str] = set()
    for e in events:
        payload = e.get("payload")
        if isinstance(payload, dict):
            raw_id = payload.get("item_id") or payload.get("current_item_id")
            if raw_id and isinstance(raw_id, str):
                item_ids.add(raw_id)

    # Batch-fetch item titles
    item_titles: dict[str, str] = {}
    if item_ids:
        id_list = list(item_ids)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(id_list)))
        item_rows = await db.fetch(
            f"SELECT id, title FROM items WHERE id IN ({placeholders})",  # noqa: S608
            *id_list,
        )
        item_titles = {str(r["id"]): str(r["title"]) for r in item_rows}

    # Fetch run_ids from rollout_items for item linkage
    plan_rows = await db.fetch(
        "SELECT item_id, claude_run_id FROM rollout_items WHERE rollout_id = $1",
        rollout_id,
    )
    item_run_ids: dict[str, str] = {
        str(r["item_id"]): str(r["claude_run_id"])
        for r in plan_rows
        if r["claude_run_id"]
    }

    # Build enriched event dicts
    result: list[dict[str, Any]] = []
    for e in events:
        payload = e.get("payload") or {}
        raw_item_id = payload.get("item_id") or payload.get("current_item_id")
        item_id_str: str | None = str(raw_item_id) if raw_item_id else None
        decision_rule_val = e.get("decision_rule")
        result.append(
            {
                "id": e["id"],
                "rollout_id": e["rollout_id"],
                "seq": e["seq"],
                "ts": e["ts"],
                "actor": e["actor"],
                "event_type": e["kind"],
                "item_id": item_id_str,
                "item_title": item_titles.get(item_id_str) if item_id_str else None,
                "run_id": item_run_ids.get(item_id_str) if item_id_str else None,
                "decision_rule": decision_rule_val if decision_rule_val else None,
                "payload": payload,
            }
        )

    return {"events": result, "has_more": has_more}


_TERMINAL_ITEM_STATUSES = frozenset(("done", "cancelled"))


async def check_halted_rollout_completion(db: DbPool, item_id: str) -> None:
    """Auto-close halted rollouts whose every GTD item has reached terminal status.

    Called best-effort after a GTD item status changes to ``done`` or
    ``cancelled``.  Finds any ``halted`` rollout that contains *item_id* via
    rollout_items, then checks whether **all** GTD items belonging to that
    rollout (joined through rollout_items → items) are in ``{done, cancelled}``.
    If so, transitions the rollout to ``completed``, stamps ``ended_at``, and
    emits a ``wave_completed`` event with actor ``human``.

    Only acts on ``halted`` rollouts — running, planning, and pending rollouts
    are ignored (AC-7).

    This function is intentionally best-effort: callers must wrap it in
    ``try/except`` and log failures rather than letting them surface.

    Args:
        db: Database pool.
        item_id: ID of the GTD item whose status just changed.
    """
    # Find halted rollouts that contain this item
    rollout_rows = await db.fetch(
        """
        SELECT ar.id, ar.project_id, ar.lead_user_id
        FROM autonomous_rollouts ar
        JOIN rollout_items ri ON ri.rollout_id = ar.id
        WHERE ri.item_id = $1
          AND ar.status = 'halted'
        """,
        item_id,
    )

    for rollout_row in rollout_rows:
        rollout_id = str(rollout_row["id"])
        project_id = str(rollout_row["project_id"])
        lead_user_id = str(rollout_row["lead_user_id"])

        # Fetch all GTD item statuses for this rollout
        item_rows = await db.fetch(
            """
            SELECT i.status
            FROM rollout_items ri
            JOIN items i ON i.id = ri.item_id
            WHERE ri.rollout_id = $1
            """,
            rollout_id,
        )

        if not item_rows:
            continue

        all_terminal = all(
            str(row["status"]) in _TERMINAL_ITEM_STATUSES for row in item_rows
        )

        if not all_terminal:
            continue

        # Transition rollout to completed (WHERE status='halted' prevents double-apply)
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE autonomous_rollouts"
            " SET status = 'completed', ended_at = $1, updated_at = $2"
            " WHERE id = $3 AND status = 'halted'",
            now,
            now,
            rollout_id,
        )

        # Confirm the update took effect before emitting the event
        updated = await db.fetchrow(
            "SELECT status FROM autonomous_rollouts WHERE id = $1", rollout_id
        )
        if updated is None or str(updated["status"]) != "completed":
            logger.debug(
                "check_halted_rollout_completion: rollout %s already transitioned,"
                " skipping event",
                rollout_id,
            )
            continue

        # Emit wave_completed event
        wave_completed_event = await _append_rollout_event(
            db,
            rollout_id,
            kind="wave_completed",
            actor="human",
            payload={"auto_closed": True, "trigger_item_id": item_id},
        )
        _publish_rollout_event(db, lead_user_id, wave_completed_event, project_id)

        logger.info(
            "check_halted_rollout_completion: rollout %s auto-closed"
            " (all GTD items are terminal)",
            rollout_id,
        )


async def get_rollout_failure_feed(
    db: DbPool,
    user_id: str,
    rollout_id: str,
) -> dict[str, Any]:
    """Return the failure feed for a rollout.

    Aggregates:
    - ``wave_halts``: all ``wave_halted`` events for this rollout, with the
      ``payload`` JSON decoded.
    - ``failed_runs``: all ``claude_runs`` with ``status IN ('failed',
      'timeout')`` and ``rollout_id`` matching, enriched with item_title
      and project_name.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must own the rollout's project.
        rollout_id: The rollout to fetch failures for.

    Returns:
        Dict with ``wave_halts`` and ``failed_runs`` lists.

    Raises:
        NotFoundError: If rollout not found or caller doesn't own it.
    """
    await _get_rollout(db, user_id, rollout_id)

    # Wave halt events
    event_rows = await db.fetch(
        "SELECT * FROM rollout_events"
        " WHERE rollout_id = $1 AND kind = 'wave_halted'"
        " ORDER BY seq DESC",
        rollout_id,
    )
    wave_halts: list[dict[str, Any]] = []
    for r in event_rows:
        d = row_to_dict(r)
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
        wave_halts.append(d)

    # Failed / timeout runs for this rollout
    run_rows = await db.fetch(
        "SELECT r.*, i.title AS item_title, p.name AS project_name"
        " FROM claude_runs r"
        " LEFT JOIN items i ON i.id = r.item_id"
        " JOIN projects p ON p.id = r.project_id"
        " WHERE r.rollout_id = $1"
        " AND r.status IN ('failed', 'timeout')"
        " ORDER BY r.finished_at DESC",
        rollout_id,
    )
    failed_runs = [row_to_dict(r) for r in run_rows]

    return {"wave_halts": wave_halts, "failed_runs": failed_runs}
