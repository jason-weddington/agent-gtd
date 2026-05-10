"""Wave manager service: legality validation, planner call, DAG persistence."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from agent_gtd.db_types import DbPool
from agent_gtd.exceptions import LegalityContractError, ValidationError
from agent_gtd.services.item_service import get_item, get_unresolved_blockers
from agent_gtd.services.settings_service import get_dispatch_config

logger = logging.getLogger(__name__)


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
    from agent_gtd.exceptions import NotFoundError

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
            item_failures.append(
                f"status is '{item.get('status')}'; must be 'ready'"
            )

        # Rule 3: Acceptance Criteria section must exist and be non-empty
        if not has_acceptance_criteria(description):
            item_failures.append(
                "missing non-empty ## Acceptance Criteria section"
            )

        # Rule 4: Files to Modify section must exist and be non-empty
        if not parse_declared_files(description):
            item_failures.append(
                "missing non-empty ## Files to Modify section"
            )

        # Rule 5: No unresolved external blockers (blockers in item_ids are OK)
        unresolved = await get_unresolved_blockers(db, item_id)
        external_blockers = [b for b in unresolved if b["id"] not in item_id_set]
        if external_blockers:
            blocker_list = ", ".join(
                f"'{b['title']}' ({b['status']})" for b in external_blockers
            )
            item_failures.append(
                f"has unresolved external blockers: {blocker_list}"
            )

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
            mismatch_msg = (
                f"project_id={pid!r} — all items must share the same project"
            )
            existing = next(
                (f for f in failures if f["item_id"] == item_id), None
            )
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
        "UPDATE autonomous_wave_runs SET status = $1, updated_at = $2 "
        "WHERE id = $3",
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
