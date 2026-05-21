"""Rollout API routes for the executor cycle and frontend UI.

Provides REST endpoints that mirror the rollout manager MCP tools.  These
routes are used by HttpBackend so remote MCP clients (e.g. a Claude Code
session running on a laptop) can call wave operations over HTTP without
direct DB access.

Also provides frontend-facing routes for the rollout banner, event feed, and
halt card UI.

Endpoints (planning + executor):
    POST /api/rollouts                               → plan_rollout result
    POST /api/rollouts/{rollout_id}/start           → updated rollout
    GET  /api/rollouts/{rollout_id}/advance         → advance_rollout result
    POST /api/rollouts/{rollout_id}/complete-item   → complete_item_in_rollout result
    POST /api/rollouts/{rollout_id}/halt            → updated rollout
    POST /api/rollouts/{rollout_id}/replan          → new plan info

Endpoints (frontend UI — AC-22, AC-23, AC-24):
    GET  /api/projects/{project_id}/active-rollout       → active RolloutResponse
    GET  /api/rollouts/{id}/events                   → rollout event list
    POST /api/rollouts/{id}/resume                   → resume halted rollout
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.models import (
    ManagerPhase,
    MergeActor,
    ResumeRolloutRequest,
    RolloutFailureFeed,
    RolloutItemOutcome,
    RunResponse,
    User,
)
from agent_gtd.services import rollout_service
from agent_gtd.services.dispatch_service import dispatch_rollout_run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rollouts", tags=["rollout"])
project_rollout_router = APIRouter(prefix="/api/projects", tags=["rollout"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PlanRolloutRequest(BaseModel):
    """Request body for POST /api/rollouts."""

    item_ids: list[str]


class CompleteItemRequest(BaseModel):
    """Request body for POST /complete-item."""

    item_id: str
    outcome: RolloutItemOutcome
    merge_actor: MergeActor | Literal[""] = ""
    decision_rule: Literal["", "agent-judgment"] = ""


class HaltRolloutRequest(BaseModel):
    """Request body for POST /halt."""

    reason: str
    comment: str | None = None
    item_id: str | None = None


class CancelRolloutRequest(BaseModel):
    """Request body for POST /cancel."""

    reason: str


class ReplanRolloutRequest(BaseModel):
    """Request body for POST /replan."""

    from_item: str | None = None


class UpdateRolloutStateRequest(BaseModel):
    """Request body for POST /state."""

    phase: ManagerPhase
    current_item_id: str | None = None
    current_step: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_exc(exc: NotFoundError | ValidationError) -> HTTPException:
    """Convert domain exceptions to HTTP exceptions."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=exc.detail)
    return HTTPException(status_code=422, detail=exc.detail)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("")
async def plan_rollout(
    body: PlanRolloutRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Validate, plan, and persist a new wave run.

    Validates the legality contract, calls the dispatch service planner,
    persists the resulting DAG, and returns a plan summary.

    Args:
        body: item_ids to include in the wave.
        user: Injected authenticated user.

    Returns:
        Dict with rollout_id, status, plan (nodes + edges), planner_model,
        item_count, and per_item summary.

    Raises:
        HTTPException 422: Legality contract failure (detail includes per-item
            failures) or another validation error.
        HTTPException 502: Planner subroutine raised (network, planner error).
    """
    db = await get_db()
    try:
        return await rollout_service.plan_rollout(db, user.id, body.item_ids)
    except LegalityContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "kind": "legality_contract_failed",
                "message": exc.detail,
                "failures": exc.failures,
            },
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except RuntimeError as exc:
        # wave_service raises RuntimeError on planner HTTP failure
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{rollout_id}/advance")
async def advance_rollout(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the current readiness snapshot for a wave run.

    Args:
        rollout_id: The wave run to inspect.
        user: Injected authenticated user.

    Returns:
        Dict with next_ready, in_progress, blocked, and graph_complete.
    """
    db = await get_db()
    try:
        return await rollout_service.advance_rollout(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/complete-item")
async def complete_item_in_rollout(
    rollout_id: str,
    body: CompleteItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Mark a dispatched wave item as done and unblock downstream items.

    Args:
        rollout_id: The wave run the item belongs to.
        body: item_id, outcome, optional merge_actor and decision_rule.
        user: Injected authenticated user.

    Returns:
        Dict with wave_plan_item (updated row) and newly_ready list.
    """
    db = await get_db()
    try:
        return await rollout_service.complete_item_in_rollout(
            db,
            user.id,
            rollout_id,
            body.item_id,
            body.outcome,
            merge_actor=body.merge_actor,
            decision_rule=body.decision_rule,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/halt")
async def halt_rollout(
    rollout_id: str,
    body: HaltRolloutRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Halt a running wave, releasing all locks and posting a comment.

    Args:
        rollout_id: The wave run to halt.
        body: reason, optional comment, optional offending item_id.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict.
    """
    db = await get_db()
    try:
        return await rollout_service.halt_rollout(
            db,
            user.id,
            rollout_id,
            body.reason,
            comment=body.comment,
            item_id=body.item_id,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/cancel")
async def cancel_rollout(
    rollout_id: str,
    body: CancelRolloutRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Cancel a wave, marking any remaining items as skipped.

    Accepts waves in any non-terminal status (pending, planning, running,
    halted, failed).  Idempotent for already-cancelled waves.

    Args:
        rollout_id: The wave run to cancel.
        body: reason for cancellation.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict.
    """
    db = await get_db()
    try:
        return await rollout_service.cancel_rollout(
            db,
            user.id,
            rollout_id,
            body.reason,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/start")
async def start_rollout(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Flip a pending wave to running without launching a manage agent.

    Useful for lead-as-manager debugging and human-driven rollouts.  Only
    accepts waves in ``pending`` status — rejects all others with 422.

    Args:
        rollout_id: The wave run to start.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict.
    """
    db = await get_db()
    try:
        return await rollout_service.start_rollout(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/replan")
async def replan_rollout(
    rollout_id: str,
    body: ReplanRolloutRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Re-plan the remaining subgraph for an in-progress wave.

    Args:
        rollout_id: The wave run to replan.
        body: Optional from_item to restrict replanning to a subgraph.
        user: Injected authenticated user.

    Returns:
        Dict with old_version, new_version, and new_plan.
    """
    db = await get_db()
    try:
        return await rollout_service.replan_rollout(
            db,
            user.id,
            rollout_id,
            from_item=body.from_item,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/state")
async def update_rollout_state(
    rollout_id: str,
    body: UpdateRolloutStateRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Update the manager's current semantic state for a running wave.

    Called by the manage-mode agent (via HttpBackend) at each major workflow
    transition to publish semantic state to the dashboard.

    Args:
        rollout_id: The wave run to update.
        body: phase, optional current_item_id, optional current_step.
        user: Injected authenticated user.

    Returns:
        Dict with rollout_id, ts, phase, current_item_id, current_step.
    """
    db = await get_db()
    try:
        return await rollout_service.update_rollout_state(
            db,
            user.id,
            rollout_id,
            phase=body.phase,
            current_item_id=body.current_item_id,
            current_step=body.current_step,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


# ---------------------------------------------------------------------------
# Frontend UI routes (AC-22, AC-23, AC-24)
# ---------------------------------------------------------------------------


@project_rollout_router.get("/{project_id}/active-rollout")
async def get_active_rollout(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the most recent active wave run for a project.

    AC-22: Status in {pending, planning, running, halted, failed} within
    the last 30 minutes for completed/failed waves; ongoing for others.
    Includes total_count and done_count for the progress fraction.

    Args:
        project_id: The project to query.
        user: Injected authenticated user.

    Returns:
        RolloutResponse dict with total_count and done_count.

    Raises:
        404 if no active wave found.
    """
    db = await get_db()
    try:
        wave = await rollout_service.get_active_rollout_for_project(
            db, project_id, user.id
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc

    if wave is None:
        raise HTTPException(status_code=404, detail="No active wave for this project")

    return wave


@router.get("/{rollout_id}/events")
async def get_rollout_events(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return wave events for a run, newest first.

    AC-23: Ordered by seq descending. Requires auth; caller must own the wave.

    Args:
        rollout_id: The wave run to query.
        user: Injected authenticated user.
        limit: Max events to return (1-200, default 50).

    Returns:
        Dict with ``events`` list.
    """
    db = await get_db()
    try:
        events = await rollout_service.get_rollout_events(
            db, rollout_id, user.id, limit=limit
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc

    return {"events": events}


@router.get("/{rollout_id}/activity")
async def get_rollout_activity(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=200),
    before_seq: int | None = Query(default=None),
) -> dict[str, Any]:
    """Return enriched activity events for a wave run, newest first.

    Excludes heartbeat events. Supports cursor-based pagination via before_seq.
    Each event is enriched with item_id, item_title, and run_id.

    Args:
        rollout_id: The wave run to query.
        user: Injected authenticated user.
        limit: Max events to return (1-200, default 200).
        before_seq: If provided, return only events with seq < before_seq.

    Returns:
        Dict with ``events`` list and ``has_more`` boolean.
    """
    db = await get_db()
    try:
        return await rollout_service.get_rollout_activity(
            db, rollout_id, user.id, limit=limit, before_seq=before_seq
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/resume")
async def resume_rollout(
    rollout_id: str,
    body: ResumeRolloutRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Resume a halted wave by providing an answer or instruction.

    AC-24: Validates wave is halted, posts answer as comment, re-locks items,
    transitions halted plan items back to ready/pending, sets wave to running,
    emits SSE.

    Args:
        rollout_id: The halted wave run to resume.
        body: The answer string to post as a comment.
        user: Injected authenticated user.

    Returns:
        Updated RolloutResponse dict.

    Raises:
        404 if wave not found or caller doesn't own it.
        409 if wave is not halted.
    """
    db = await get_db()
    try:
        return await rollout_service.resume_rollout(
            db, rollout_id, body.answer, user.id
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.get("")
async def list_rollouts(
    user: Annotated[User, Depends(get_current_user)],
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List rollouts for the authenticated user, with optional filters.

    Args:
        user: Injected authenticated user.
        project_id: Optional filter by project.
        status: Optional filter by rollout status (e.g. ``"running"``).
        limit: Maximum number of results (default 20, max 100).

    Returns:
        List of rollout dicts ordered by created_at DESC.
    """
    db = await get_db()
    return await rollout_service.list_rollouts(
        db,
        user.id,
        project_id=project_id,
        status=status,
        limit=limit,
    )


@router.get("/{rollout_id}/plan")
async def get_rollout_plan(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the latest plan for a rollout with per-item progress.

    Args:
        rollout_id: The rollout to fetch the plan for.
        user: Injected authenticated user.

    Returns:
        Dict with rollout_id, plan_version, planner_model, nodes, edges,
        and items (each with item_id, title, rollout_status, predecessors).

    Raises:
        404 if rollout not found, caller doesn't own it, or no plan exists.
    """
    db = await get_db()
    try:
        return await rollout_service.get_rollout_plan(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.get("/{rollout_id}")
async def get_rollout(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the autonomous_rollouts row for this rollout.

    Args:
        rollout_id: The rollout to fetch.
        user: Injected authenticated user.

    Returns:
        The rollout dict including status, manage_retry_count, halt_reason, etc.

    Raises:
        404 if rollout not found or caller doesn't own it.
    """
    db = await get_db()
    try:
        return await rollout_service.get_rollout(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/dismiss")
async def dismiss_rollout(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Dismiss a halted rollout by transitioning it to cancelled.

    No request body required.  Useful when the operator wants to clear the
    warning banner even if some items remain incomplete — semantically lighter
    than Abort (no confirmation dialog needed).

    Args:
        rollout_id: The rollout to dismiss (typically halted).
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict.

    Raises:
        404 if rollout not found or caller doesn't own it.
        422 if rollout is already completed (non-cancellable).
    """
    db = await get_db()
    try:
        return await rollout_service.cancel_rollout(
            db,
            user.id,
            rollout_id,
            "Dismissed by operator",
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/relaunch-manage")
async def relaunch_manage(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Atomically increment manage_retry_count and emit a manage_relaunched event.

    Called by the dispatch service when a manage subprocess exits unexpectedly.

    Args:
        rollout_id: The rollout whose manager is being relaunched.
        user: Injected authenticated user.

    Returns:
        The updated rollout dict (includes manage_retry_count).

    Raises:
        404 if rollout not found or caller doesn't own it.
    """
    db = await get_db()
    try:
        return await rollout_service.relaunch_manage_rollout(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{rollout_id}/dispatch", status_code=201)
async def dispatch_rollout(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> RunResponse:
    """Dispatch the wave manager agent for this rollout.

    Creates a manage-mode claude_runs row with item_id=NULL, scoped to the
    rollout. Transitions the rollout from pending → running.

    Args:
        rollout_id: The rollout to dispatch.
        user: Injected authenticated user.

    Returns:
        201 RunResponse with the created run.

    Raises:
        404 if rollout not found or caller doesn't own it.
        409 if rollout is not in pending status.
    """
    db = await get_db()
    try:
        row = await dispatch_rollout_run(db, user.id, rollout_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc

    # Enqueue for background processing
    try:
        from agent_gtd.dispatch_worker import enqueue_run

        enqueue_run(str(row["id"]))
    except AssertionError:
        pass  # Worker not started (e.g. in tests)

    return RunResponse(**row)


@router.get("/{rollout_id}/rollout_failures", response_model=RolloutFailureFeed)
async def get_rollout_failures(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> RolloutFailureFeed:
    """Return the failure feed for a rollout.

    Aggregates wave halt events and failed/timeout runs for this rollout.
    Wave halt events include the decoded payload (reason, item_id, comment_id).
    Failed runs are enriched with item_title and project_name.

    Args:
        rollout_id: The rollout to fetch failures for.
        user: Injected authenticated user.

    Returns:
        RolloutFailureFeed with wave_halts and failed_runs.

    Raises:
        404 if rollout not found or caller doesn't own it.
    """
    db = await get_db()
    from agent_gtd.routes.dispatch_routes import _failed_run_response

    try:
        feed = await rollout_service.get_rollout_failure_feed(db, user.id, rollout_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc

    failed_runs = [_failed_run_response(r) for r in feed["failed_runs"]]
    return RolloutFailureFeed(
        wave_halts=feed["wave_halts"],
        failed_runs=failed_runs,
    )
