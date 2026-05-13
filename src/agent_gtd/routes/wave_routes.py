"""Wave run API routes for the executor cycle and frontend UI.

Provides REST endpoints that mirror the wave manager MCP tools.  These
routes are used by HttpBackend so remote MCP clients (e.g. a Claude Code
session running on a laptop) can call wave operations over HTTP without
direct DB access.

Also provides frontend-facing routes for the wave banner, event feed, and
halt card UI.

Endpoints (planning + executor):
    POST /api/wave-runs                               → plan_wave result
    POST /api/wave-runs/{wave_run_id}/start           → updated wave run
    GET  /api/wave-runs/{wave_run_id}/advance         → advance_wave result
    POST /api/wave-runs/{wave_run_id}/complete-item   → complete_in_wave result
    POST /api/wave-runs/{wave_run_id}/halt            → updated wave run
    POST /api/wave-runs/{wave_run_id}/replan          → new plan info

Endpoints (frontend UI — AC-22, AC-23, AC-24):
    GET  /api/projects/{project_id}/active-wave       → active WaveRunResponse
    GET  /api/wave-runs/{id}/events                   → wave event list
    POST /api/wave-runs/{id}/resume                   → resume halted wave
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.models import ResumeWaveRequest, User
from agent_gtd.services import wave_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wave-runs", tags=["wave"])
project_wave_router = APIRouter(prefix="/api/projects", tags=["wave"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PlanWaveRequest(BaseModel):
    """Request body for POST /api/wave-runs."""

    item_ids: list[str]


class CompleteItemRequest(BaseModel):
    """Request body for POST /complete-item."""

    item_id: str
    outcome: str
    merge_actor: str = ""
    decision_rule: str = ""


class HaltWaveRequest(BaseModel):
    """Request body for POST /halt."""

    reason: str
    comment: str | None = None
    item_id: str | None = None


class CancelWaveRequest(BaseModel):
    """Request body for POST /cancel."""

    reason: str


class ReplanWaveRequest(BaseModel):
    """Request body for POST /replan."""

    from_item: str | None = None


class UpdateWaveStateRequest(BaseModel):
    """Request body for POST /state."""

    phase: str
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
async def plan_wave(
    body: PlanWaveRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Validate, plan, and persist a new wave run.

    Validates the legality contract, calls the dispatch service planner,
    persists the resulting DAG, and returns a plan summary.

    Args:
        body: item_ids to include in the wave.
        user: Injected authenticated user.

    Returns:
        Dict with wave_run_id, status, plan (nodes + edges), planner_model,
        item_count, and per_item summary.

    Raises:
        HTTPException 422: Legality contract failure (detail includes per-item
            failures) or another validation error.
        HTTPException 502: Planner subroutine raised (network, planner error).
    """
    db = await get_db()
    try:
        return await wave_service.plan_wave(db, user.id, body.item_ids)
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


@router.get("/{wave_run_id}/advance")
async def advance_wave(
    wave_run_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the current readiness snapshot for a wave run.

    Args:
        wave_run_id: The wave run to inspect.
        user: Injected authenticated user.

    Returns:
        Dict with next_ready, in_progress, blocked, and graph_complete.
    """
    db = await get_db()
    try:
        return await wave_service.advance_wave(db, user.id, wave_run_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/complete-item")
async def complete_in_wave(
    wave_run_id: str,
    body: CompleteItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Mark a dispatched wave item as done and unblock downstream items.

    Args:
        wave_run_id: The wave run the item belongs to.
        body: item_id, outcome, optional merge_actor and decision_rule.
        user: Injected authenticated user.

    Returns:
        Dict with wave_plan_item (updated row) and newly_ready list.
    """
    db = await get_db()
    try:
        return await wave_service.complete_in_wave(
            db,
            user.id,
            wave_run_id,
            body.item_id,
            body.outcome,
            merge_actor=body.merge_actor,
            decision_rule=body.decision_rule,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/halt")
async def halt_wave(
    wave_run_id: str,
    body: HaltWaveRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Halt a running wave, releasing all locks and posting a comment.

    Args:
        wave_run_id: The wave run to halt.
        body: reason, optional comment, optional offending item_id.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_wave_runs row dict.
    """
    db = await get_db()
    try:
        return await wave_service.halt_wave(
            db,
            user.id,
            wave_run_id,
            body.reason,
            comment=body.comment,
            item_id=body.item_id,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/cancel")
async def cancel_wave(
    wave_run_id: str,
    body: CancelWaveRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Cancel a wave, marking any remaining items as skipped.

    Accepts waves in any non-terminal status (pending, planning, running,
    halted, crashed).  Idempotent for already-cancelled waves.

    Args:
        wave_run_id: The wave run to cancel.
        body: reason for cancellation.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_wave_runs row dict.
    """
    db = await get_db()
    try:
        return await wave_service.cancel_wave(
            db,
            user.id,
            wave_run_id,
            body.reason,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/start")
async def start_wave(
    wave_run_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Flip a pending wave to running without launching a manage agent.

    Useful for lead-as-manager debugging and human-driven rollouts.  Only
    accepts waves in ``pending`` status — rejects all others with 422.

    Args:
        wave_run_id: The wave run to start.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_wave_runs row dict.
    """
    db = await get_db()
    try:
        return await wave_service.start_wave(db, user.id, wave_run_id)
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/replan")
async def replan_wave(
    wave_run_id: str,
    body: ReplanWaveRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Re-plan the remaining subgraph for an in-progress wave.

    Args:
        wave_run_id: The wave run to replan.
        body: Optional from_item to restrict replanning to a subgraph.
        user: Injected authenticated user.

    Returns:
        Dict with old_version, new_version, and new_plan.
    """
    db = await get_db()
    try:
        return await wave_service.replan_wave(
            db,
            user.id,
            wave_run_id,
            from_item=body.from_item,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/state")
async def update_wave_state(
    wave_run_id: str,
    body: UpdateWaveStateRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Update the manager's current semantic state for a running wave.

    Called by the manage-mode agent (via HttpBackend) at each major workflow
    transition to publish semantic state to the dashboard.

    Args:
        wave_run_id: The wave run to update.
        body: phase, optional current_item_id, optional current_step.
        user: Injected authenticated user.

    Returns:
        Dict with wave_run_id, ts, phase, current_item_id, current_step.
    """
    db = await get_db()
    try:
        return await wave_service.update_wave_state(
            db,
            user.id,
            wave_run_id,
            phase=body.phase,
            current_item_id=body.current_item_id,
            current_step=body.current_step,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


# ---------------------------------------------------------------------------
# Frontend UI routes (AC-22, AC-23, AC-24)
# ---------------------------------------------------------------------------


@project_wave_router.get("/{project_id}/active-wave")
async def get_active_wave(
    project_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the most recent active wave run for a project.

    AC-22: Status in {pending, planning, running, halted, crashed} within
    the last 30 minutes for completed/crashed waves; ongoing for others.
    Includes total_count and done_count for the progress fraction.

    Args:
        project_id: The project to query.
        user: Injected authenticated user.

    Returns:
        WaveRunResponse dict with total_count and done_count.

    Raises:
        404 if no active wave found.
    """
    db = await get_db()
    try:
        wave = await wave_service.get_active_wave_for_project(db, project_id, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc

    if wave is None:
        raise HTTPException(status_code=404, detail="No active wave for this project")

    return wave


@router.get("/{wave_run_id}/events")
async def get_wave_events(
    wave_run_id: str,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return wave events for a run, newest first.

    AC-23: Ordered by seq descending. Requires auth; caller must own the wave.

    Args:
        wave_run_id: The wave run to query.
        user: Injected authenticated user.
        limit: Max events to return (1-200, default 50).

    Returns:
        Dict with ``events`` list.
    """
    db = await get_db()
    try:
        events = await wave_service.get_wave_events(
            db, wave_run_id, user.id, limit=limit
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc

    return {"events": events}


@router.get("/{wave_run_id}/activity")
async def get_wave_activity(
    wave_run_id: str,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=200),
    before_seq: int | None = Query(default=None),
) -> dict[str, Any]:
    """Return enriched activity events for a wave run, newest first.

    Excludes heartbeat events. Supports cursor-based pagination via before_seq.
    Each event is enriched with item_id, item_title, and run_id.

    Args:
        wave_run_id: The wave run to query.
        user: Injected authenticated user.
        limit: Max events to return (1-200, default 200).
        before_seq: If provided, return only events with seq < before_seq.

    Returns:
        Dict with ``events`` list and ``has_more`` boolean.
    """
    db = await get_db()
    try:
        return await wave_service.get_wave_activity(
            db, wave_run_id, user.id, limit=limit, before_seq=before_seq
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc


@router.post("/{wave_run_id}/resume")
async def resume_wave(
    wave_run_id: str,
    body: ResumeWaveRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Resume a halted wave by providing an answer or instruction.

    AC-24: Validates wave is halted, posts answer as comment, re-locks items,
    transitions halted plan items back to ready/pending, sets wave to running,
    emits SSE.

    Args:
        wave_run_id: The halted wave run to resume.
        body: The answer string to post as a comment.
        user: Injected authenticated user.

    Returns:
        Updated WaveRunResponse dict.

    Raises:
        404 if wave not found or caller doesn't own it.
        409 if wave is not halted.
    """
    db = await get_db()
    try:
        return await wave_service.resume_wave(db, wave_run_id, body.answer, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
