"""Wave manager service: legality validation, planner call, DAG persistence."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from agent_gtd.database import row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.services.item_service import get_item, get_unresolved_blockers
from agent_gtd.services.settings_service import get_dispatch_config

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(("completed", "halted", "skipped"))
_ACTIVE_ITEM_STATUSES = frozenset(("pending", "ready", "dispatched"))
_HALTED_FROM_STATUSES = ("pending", "ready", "dispatched")


# ---------------------------------------------------------------------------
# Description section parsers
# ---------------------------------------------------------------------------


def _section_lines(description: str, heading: str) -> list[str]:
    """Return non-blank body lines under *heading* up to the next ## heading.

    Args:
        description: Item description in Markdown.
        heading: The exact heading string to search for (e.g. ``"## Files to Modify"``).

    Returns:
        List of non-blank stripped lines after the heading, up to the next
        ``##`` heading or end of string.
    """
    lines = description.splitlines()
    in_section = False
    result: list[str] = []
    target = heading.strip()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if stripped == target:
                in_section = True
                continue
            elif in_section:
                break
        elif in_section and stripped:
            result.append(stripped)
    return result


def parse_declared_files(description: str) -> list[str]:
    """Extract non-blank lines from the ``## Files to Modify`` section.

    Used for legality validation only — the content is checked for presence,
    not passed to the planner.

    Args:
        description: Item description in Markdown.

    Returns:
        List of non-blank lines from the section.  Empty if the section is
        absent or contains only blank lines.
    """
    return _section_lines(description, "## Files to Modify")


def has_acceptance_criteria(description: str) -> bool:
    """Return True if ``## Acceptance Criteria`` section is non-empty.

    Args:
        description: Item description in Markdown.

    Returns:
        ``True`` if the section exists and has at least one non-blank
        line after the heading.
    """
    return bool(_section_lines(description, "## Acceptance Criteria"))


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
        3. Description has a non-empty ``## Acceptance Criteria`` section.
        4. Description has a non-empty ``## Files to Modify`` section.
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
        description = str(item.get("description", ""))

        # Rule 2: status must be "ready"
        if str(item.get("status", "")) != "ready":
            item_failures.append(f"status is '{item.get('status')}'; must be 'ready'")

        # Rule 3: Acceptance Criteria section must exist and be non-empty
        if not has_acceptance_criteria(description):
            item_failures.append("missing non-empty ## Acceptance Criteria section")

        # Rule 4: Files to Modify section must exist and be non-empty
        if not parse_declared_files(description):
            item_failures.append("missing non-empty ## Files to Modify section")

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


async def plan_wave(
    db: DbPool,
    user_id: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Orchestrate the full plan_wave flow.

    Validates the legality contract, checks dispatch configuration, creates a
    wave run, calls the remote planner, persists the DAG, and returns a plan
    summary for the lead to confirm before execution begins.

    Args:
        db: Database connection pool.
        user_id: ID of the calling user (the lead).
        item_ids: IDs of the items to include in the wave.

    Returns:
        Dict with keys: ``wave_run_id``, ``status``, ``plan`` (nodes + edges),
        ``planner_model``, ``item_count``, ``per_item``.

    Raises:
        ValidationError: If ``item_ids`` is empty or dispatch service is not
            configured for the project owner.
        LegalityContractError: If any item fails the legality contract.
        RuntimeError: If the planner HTTP call fails.  The wave run is updated
            to ``status='crashed'`` before the exception propagates.
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

    # Step 4: Create the wave run with status='planning'.
    wave_run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO autonomous_wave_runs "
        "(id, project_id, lead_user_id, status, started_at, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        wave_run_id,
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
            "UPDATE autonomous_wave_runs "
            "SET status = $1, halt_reason = $2, updated_at = $3 "
            "WHERE id = $4",
            "crashed",
            error_detail,
            err_now,
            wave_run_id,
        )
        raise

    nodes: list[str] = planner_result["nodes"]
    edges: list[dict[str, str]] = planner_result["edges"]
    planner_model: str = planner_result["planner_model"]

    # Step 6: Persist the wave_plans row.
    plan_id = str(uuid.uuid4())
    plan_now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO wave_plans "
        "(id, wave_run_id, version, nodes, edges, planner_model, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        wave_run_id,
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

    # Step 8: Insert wave_plan_items rows.
    for node_id in nodes:
        item_status = "ready" if in_degree.get(node_id, 0) == 0 else "pending"
        await db.execute(
            "INSERT INTO wave_plan_items (wave_run_id, item_id, status) "
            "VALUES ($1, $2, $3)",
            wave_run_id,
            node_id,
            item_status,
        )

    # Step 9: Promote the wave run to 'pending'.
    done_now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE autonomous_wave_runs SET status = $1, updated_at = $2 WHERE id = $3",
        "pending",
        done_now,
        wave_run_id,
    )

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
        "wave_run_id": wave_run_id,
        "status": "pending",
        "plan": {"nodes": nodes, "edges": edges},
        "planner_model": planner_model,
        "item_count": len(nodes),
        "per_item": per_item,
    }


# ---------------------------------------------------------------------------
# Executor helpers (advance/complete/halt/replan)
# ---------------------------------------------------------------------------


async def _get_wave_run(db: DbPool, user_id: str, wave_run_id: str) -> dict[str, Any]:
    """Fetch the wave run row and verify the caller owns it.

    Args:
        db: Database pool.
        user_id: The calling user's ID.
        wave_run_id: The wave run to load.

    Returns:
        The wave run dict.

    Raises:
        NotFoundError: If not found or not owned by the caller.
    """
    row = await db.fetchrow(
        "SELECT * FROM autonomous_wave_runs WHERE id = $1", wave_run_id
    )
    if row is None:
        raise NotFoundError("WaveRun", wave_run_id)
    wave = row_to_dict(row)
    if wave["lead_user_id"] != user_id:
        raise NotFoundError("WaveRun", wave_run_id)
    return wave


async def _get_latest_plan(db: DbPool, wave_run_id: str) -> dict[str, Any] | None:
    """Fetch the highest-version wave_plans row for this run."""
    row = await db.fetchrow(
        "SELECT * FROM wave_plans WHERE wave_run_id = $1 ORDER BY version DESC LIMIT 1",
        wave_run_id,
    )
    return row_to_dict(row) if row else None


async def _next_event_seq(db: DbPool, wave_run_id: str) -> int:
    """Return the next available sequence number for a wave event."""
    row = await db.fetchrow(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq"
        " FROM wave_events WHERE wave_run_id = $1",
        wave_run_id,
    )
    return int(row["next_seq"]) if row else 1


async def _append_wave_event(
    db: DbPool,
    wave_run_id: str,
    kind: str,
    actor: str,
    payload: dict[str, Any],
    decision_rule: str = "",
) -> dict[str, Any]:
    """Append a row to wave_events with an auto-incrementing seq.

    Args:
        db: Database pool.
        wave_run_id: The wave run this event belongs to.
        kind: Event kind string (e.g. 'item_outcome', 'wave_halted').
        actor: Actor string (e.g. 'manager', 'human').
        payload: JSON-serialisable payload dict.
        decision_rule: Optional rule name that triggered an auto-approval
            (default empty string, stored in the decision_rule column).

    Returns:
        The inserted wave event as a dict with keys: id, wave_run_id, seq,
        ts, kind, actor, decision_rule, payload.
    """
    event_id = str(uuid.uuid4())
    seq = await _next_event_seq(db, wave_run_id)
    ts = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO wave_events"
        " (id, wave_run_id, seq, ts, kind, actor, decision_rule, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        event_id,
        wave_run_id,
        seq,
        ts,
        kind,
        actor,
        decision_rule,
        json.dumps(payload),
    )
    return {
        "id": event_id,
        "wave_run_id": wave_run_id,
        "seq": seq,
        "ts": ts,
        "kind": kind,
        "actor": actor,
        "decision_rule": decision_rule,
        "payload": payload,
    }


def _publish_wave_event(
    db: DbPool,
    lead_user_id: str,
    wave_event: dict[str, Any],
    project_id: str,
) -> None:
    """Fire-and-forget SSE event publish for wave events (best effort).

    Follows the same pattern as ``_publish_run_event`` in dispatch_worker.py.
    Wraps the publish coroutine in ``asyncio.create_task`` so callers are never
    blocked, and swallows any exceptions so wave mutations are never affected.

    Args:
        db: Database pool (passed through to EventBus.publish for persistence).
        lead_user_id: The wave run's lead user ID (becomes the event owner).
        wave_event: Full wave event dict as returned by ``_append_wave_event``
            (keys: id, wave_run_id, seq, ts, kind, actor, decision_rule,
            payload).
        project_id: The wave run's project ID — triggers project-member
            fan-out in the event bus.
    """
    try:
        from agent_gtd.event_bus import get_event_bus

        bus = get_event_bus()
        asyncio.create_task(  # noqa: RUF006
            bus.publish(
                db,
                user_id=lead_user_id,
                event_type="wave_event",
                entity_type="wave_run",
                entity_id=wave_event["wave_run_id"],
                project_id=project_id,
                payload=wave_event,
            )
        )
    except Exception:
        logger.exception("Failed to publish wave_event SSE event")


# TODO: f0689a01 — call _publish_wave_event after plan_wave writes wave_events
# NOTE: reaper (ad6e62ca) must also call _publish_wave_event after wave_events INSERTs


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


async def advance_wave(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
) -> dict[str, Any]:
    """Read-only graph traversal: classify wave items.

    Computes which items are ready to dispatch (next_ready), already running
    (in_progress), or blocked by unfinished predecessors (blocked).  Also
    reports whether the entire graph is complete.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        wave_run_id: ID of the wave run to inspect.

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
    wave = await _get_wave_run(db, user_id, wave_run_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {wave_run_id} is not running (status={wave['status']})"
        )

    rows = await db.fetch(
        "SELECT item_id, status FROM wave_plan_items WHERE wave_run_id = $1",
        wave_run_id,
    )
    items: dict[str, str] = {r["item_id"]: r["status"] for r in rows}

    plan = await _get_latest_plan(db, wave_run_id)
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


async def complete_in_wave(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
    item_id: str,
    outcome: str,
    merge_actor: str = "",
    decision_rule: str = "",
) -> dict[str, Any]:
    """Mark a dispatched wave item as done and unblock downstream items.

    After the item is marked terminal, each downstream item whose only
    remaining blocking predecessor was this one is transitioned from
    ``pending`` → ``ready``.  If all items in the wave are now in terminal
    states the wave run itself is closed (status → 'completed').

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        wave_run_id: ID of the wave run.
        item_id: ID of the wave_plan_items row to complete.
        outcome: One of ``"completed"``, ``"halted"``, ``"skipped"``.
        merge_actor: Who merged the PR (``"human"``,
            ``"manager-allowlist"``, ``"manager+human-fixup"``, or empty).
            Stored on the wave_plan_items row.
        decision_rule: Allowlist rule name that triggered auto-approval
            (from the executor classifier). Stored in the event payload.

    Returns:
        Dict with keys:
          - wave_plan_item (dict): The updated wave_plan_items row.
          - newly_ready (list[str]): Item IDs transitioned to 'ready'.

    Raises:
        NotFoundError: If wave or item not found or caller doesn't own it.
        ValidationError: If the item is not in 'dispatched' status, or if
            outcome is invalid.
    """
    valid_outcomes = ("completed", "halted", "skipped")
    if outcome not in valid_outcomes:
        raise ValidationError(
            f"Invalid outcome '{outcome}' — must be one of: "
            + ", ".join(valid_outcomes)
        )

    wave = await _get_wave_run(db, user_id, wave_run_id)
    project_id = str(wave["project_id"])

    item_row = await db.fetchrow(
        "SELECT * FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_id,
    )
    if item_row is None:
        raise NotFoundError("WavePlanItem", f"{wave_run_id}/{item_id}")
    if item_row["status"] != "dispatched":
        raise ValidationError(
            f"Item {item_id} has status '{item_row['status']}' — "
            "only 'dispatched' items can be completed"
        )

    now = datetime.now(UTC).isoformat()

    if merge_actor:
        await db.execute(
            "UPDATE wave_plan_items"
            " SET status = $1, completed_at = $2, merge_actor = $3"
            " WHERE wave_run_id = $4 AND item_id = $5",
            outcome,
            now,
            merge_actor,
            wave_run_id,
            item_id,
        )
    else:
        await db.execute(
            "UPDATE wave_plan_items"
            " SET status = $1, completed_at = $2"
            " WHERE wave_run_id = $3 AND item_id = $4",
            outcome,
            now,
            wave_run_id,
            item_id,
        )

    # Release per-item wave lock
    from agent_gtd.services.wave_lock_service import release_wave_item

    await release_wave_item(db, wave_run_id, item_id)

    updated_row = await db.fetchrow(
        "SELECT * FROM wave_plan_items WHERE wave_run_id = $1 AND item_id = $2",
        wave_run_id,
        item_id,
    )
    assert updated_row is not None  # noqa: S101

    # Reload all item statuses (including the just-updated item)
    all_rows = await db.fetch(
        "SELECT item_id, status FROM wave_plan_items WHERE wave_run_id = $1",
        wave_run_id,
    )
    item_statuses: dict[str, str] = {r["item_id"]: r["status"] for r in all_rows}
    # The DB row was just updated; keep our view consistent.
    item_statuses[item_id] = outcome

    # Load DAG for downstream traversal
    plan = await _get_latest_plan(db, wave_run_id)
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
                "UPDATE wave_plan_items SET status = 'ready'"
                " WHERE wave_run_id = $1 AND item_id = $2 AND status = 'pending'",
                wave_run_id,
                downstream_id,
            )
            item_statuses[downstream_id] = "ready"
            newly_ready.append(downstream_id)

    # Close the wave if every item is now terminal
    if all(s in _TERMINAL_STATUSES for s in item_statuses.values()):
        await db.execute(
            "UPDATE autonomous_wave_runs"
            " SET status = 'completed', ended_at = $1, updated_at = $2"
            " WHERE id = $3",
            now,
            now,
            wave_run_id,
        )

    # Emit item_outcome wave event and publish to SSE subscribers
    wave_event = await _append_wave_event(
        db,
        wave_run_id,
        kind="item_outcome",
        actor="manager",
        payload={
            "item_id": item_id,
            "outcome": outcome,
            "decision_rule": decision_rule,
        },
        decision_rule=decision_rule,
    )
    _publish_wave_event(db, user_id, wave_event, project_id)

    return {
        "wave_plan_item": row_to_dict(updated_row),
        "newly_ready": newly_ready,
    }


async def halt_wave(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
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
        wave_run_id: ID of the wave run to halt.
        reason: Short machine-readable halt reason (e.g. ``"merge_rejected"``).
        comment: Optional human-readable context appended to the GTD comment.
        item_id: Optional ID of the item that triggered the halt.  Stored in
            the event payload so the halt card can wire the "Skip this item"
            button.

    Returns:
        The updated autonomous_wave_runs row dict.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not 'running'.
    """
    wave = await _get_wave_run(db, user_id, wave_run_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {wave_run_id} is not running (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await db.execute(
        "UPDATE autonomous_wave_runs"
        " SET status = 'halted', halt_reason = $1, ended_at = $2, updated_at = $3"
        " WHERE id = $4",
        reason,
        now,
        now,
        wave_run_id,
    )

    await db.execute(
        "UPDATE wave_plan_items SET status = 'halted'"
        " WHERE wave_run_id = $1 AND status IN ('pending', 'ready', 'dispatched')",
        wave_run_id,
    )

    # Release all wave-scoped item locks (item c85cae60)
    from agent_gtd.services.wave_lock_service import release_wave_locks

    await release_wave_locks(db, wave_run_id)

    # Post a GTD comment on the project
    from agent_gtd.services.comment_service import create_comment

    content_parts = [f"Wave halted: {reason}"]
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

    # Emit wave_halted event and publish to SSE subscribers
    wave_event = await _append_wave_event(
        db,
        wave_run_id,
        kind="wave_halted",
        actor="manager",
        payload={
            "reason": reason,
            "item_id": item_id,
            "comment_id": comment_id,
        },
    )
    _publish_wave_event(db, user_id, wave_event, str(wave["project_id"]))

    row = await db.fetchrow(
        "SELECT * FROM autonomous_wave_runs WHERE id = $1", wave_run_id
    )
    assert row is not None  # noqa: S101
    return row_to_dict(row)


async def _call_planner(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Call the dispatch-worker planner to generate a plan for the given items.

    # TODO: coordinate with f0689a01 (plan_wave) for the exact planner call
    # shape.  plan_wave establishes the HTTP client helper and request format;
    # replan_wave must use the same mechanism.  Until plan_wave is merged this
    # function makes a best-effort call using the dispatch service config.

    Args:
        db: Database pool.
        user_id: Calling user's ID (used to look up dispatch config).
        wave_run_id: The wave run being replanned (sent to planner for context).
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
            "Dispatch service not configured — cannot call planner for replan_wave"
        )

    url = str(config.get("url", "")).rstrip("/")
    api_key = str(config.get("api_key", ""))

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/plan",
            json={"wave_run_id": wave_run_id, "item_ids": item_ids},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    if resp.status_code != 200:
        raise ValidationError(f"Planner returned {resp.status_code}: {resp.text[:200]}")

    data: dict[str, Any] = resp.json()
    return data


async def replan_wave(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
    from_item: str | None = None,
) -> dict[str, Any]:
    """Re-plan the remaining subgraph for an in-progress wave.

    Calls the dispatch-worker planner (same mechanism as plan_wave) scoped
    to the remaining pending/ready items, persists a new wave_plans version,
    updates item readiness, and emits a ``wave_replanned`` event.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        wave_run_id: ID of the wave run to replan.
        from_item: Optional item ID to restrict replanning to its downstream
            subgraph (depth-first traversal).

    Returns:
        Dict with keys:
          - old_version (int): The previous plan version.
          - new_version (int): The newly created plan version.
          - new_plan (dict): The new wave_plans row.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave is not running, there are no remaining items,
            or the planner call fails.
    """
    wave = await _get_wave_run(db, user_id, wave_run_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {wave_run_id} is not running (status={wave['status']})"
        )

    remaining_rows = await db.fetch(
        "SELECT item_id FROM wave_plan_items"
        " WHERE wave_run_id = $1 AND status IN ('pending', 'ready')",
        wave_run_id,
    )
    remaining_ids = [r["item_id"] for r in remaining_rows]
    if not remaining_ids:
        raise ValidationError(f"Wave {wave_run_id} has no remaining items to replan")

    # If from_item is given, restrict to its downstream subgraph
    if from_item is not None:
        plan = await _get_latest_plan(db, wave_run_id)
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
        " FROM wave_plans WHERE wave_run_id = $1",
        wave_run_id,
    )
    old_version = int(version_row["max_version"]) if version_row else 0
    new_version = old_version + 1

    # Call the planner for the remaining items
    planner_result = await _call_planner(db, user_id, wave_run_id, remaining_ids)

    new_nodes: list[str] = planner_result.get("nodes", remaining_ids)
    new_edges: list[dict[str, str]] = planner_result.get("edges", [])
    planner_model: str = planner_result.get("planner_model", "")

    # Persist new wave_plans row
    plan_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO wave_plans"
        " (id, wave_run_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        wave_run_id,
        new_version,
        json.dumps(new_nodes),
        json.dumps(new_edges),
        planner_model,
        now,
    )

    # Update readiness of remaining items based on new DAG
    new_preds = _build_predecessor_map(new_edges)
    all_rows = await db.fetch(
        "SELECT item_id, status FROM wave_plan_items WHERE wave_run_id = $1",
        wave_run_id,
    )
    all_statuses: dict[str, str] = {r["item_id"]: r["status"] for r in all_rows}

    for rid in remaining_ids:
        item_preds = new_preds.get(rid, [])
        all_preds_done = all(
            all_statuses.get(p, "pending") in _TERMINAL_STATUSES for p in item_preds
        )
        if all_preds_done:
            await db.execute(
                "UPDATE wave_plan_items SET status = 'ready'"
                " WHERE wave_run_id = $1 AND item_id = $2 AND status = 'pending'",
                wave_run_id,
                rid,
            )
        else:
            # If the new plan re-blocks an item that was 'ready', revert it.
            await db.execute(
                "UPDATE wave_plan_items SET status = 'pending'"
                " WHERE wave_run_id = $1 AND item_id = $2 AND status = 'ready'",
                wave_run_id,
                rid,
            )

    # Emit wave_replanned event and publish to SSE subscribers
    wave_event = await _append_wave_event(
        db,
        wave_run_id,
        kind="wave_replanned",
        actor="manager",
        payload={
            "old_version": old_version,
            "new_version": new_version,
        },
    )
    _publish_wave_event(db, user_id, wave_event, str(wave["project_id"]))

    new_plan_row = await db.fetchrow("SELECT * FROM wave_plans WHERE id = $1", plan_id)
    assert new_plan_row is not None  # noqa: S101

    return {
        "old_version": old_version,
        "new_version": new_version,
        "new_plan": row_to_dict(new_plan_row),
    }


# ---------------------------------------------------------------------------
# Heartbeat / liveness ping (AC-5)
# ---------------------------------------------------------------------------

_VALID_PHASES = frozenset(
    ("", "planning", "dispatching", "monitoring", "merging", "halted")
)


async def ping_wave(
    db: DbPool,
    user_id: str,
    wave_run_id: str,
    phase: str = "",
    waiting_on: str = "",
) -> dict[str, Any]:
    """Record a heartbeat event for a running wave and reset the reaper clock.

    The lead executor calls this during idle wait loops to prove liveness.
    Inserts a ``heartbeat`` wave event whose payload stores ``phase`` and
    ``waiting_on`` for the UI feed and apt-style display.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be the wave's lead_user_id.
        wave_run_id: ID of the wave run to ping.
        phase: Current phase of the executor.  One of ``""``,
            ``"planning"``, ``"dispatching"``, ``"monitoring"``,
            ``"merging"``, ``"halted"``.
        waiting_on: Item ID (or empty string) the executor is currently
            waiting on.

    Returns:
        Dict with keys ``wave_run_id``, ``ts``, ``phase``, ``waiting_on``.

    Raises:
        NotFoundError: If wave not found or caller doesn't own it.
        ValidationError: If wave status is not ``'running'`` or phase is
            invalid.
    """
    if phase not in _VALID_PHASES:
        raise ValidationError(
            f"Invalid phase '{phase}' — must be one of: "
            + ", ".join(sorted(_VALID_PHASES))
        )

    wave = await _get_wave_run(db, user_id, wave_run_id)
    if wave["status"] != "running":
        raise ValidationError(
            f"Wave {wave_run_id} is not running (status={wave['status']})"
        )

    now = datetime.now(UTC).isoformat()

    await _append_wave_event(
        db,
        wave_run_id,
        kind="heartbeat",
        actor="manager",
        payload={"phase": phase, "waiting_on": waiting_on},
    )

    await db.execute(
        "UPDATE autonomous_wave_runs SET updated_at = $1 WHERE id = $2",
        now,
        wave_run_id,
    )

    return {
        "wave_run_id": wave_run_id,
        "ts": now,
        "phase": phase,
        "waiting_on": waiting_on,
    }
