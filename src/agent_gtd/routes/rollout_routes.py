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

Endpoints (frontend UI — AC-22, AC-23, AC-24):
    GET  /api/projects/{project_id}/active-rollout       → active RolloutResponse
    GET  /api/rollouts/{id}/events                   → rollout event list
    GET  /api/rollouts/{id}/merge-notes              → recent merge notes
    POST /api/rollouts/{id}/resume                   → resume halted rollout
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import LegalityContractError, NotFoundError, ValidationError
from agent_gtd.models import (
    BuildEngine,
    ManagerPhase,
    MergeActor,
    ResumeRolloutRequest,
    RolloutFailureFeed,
    RolloutItemOutcome,
    RunResponse,
    User,
    reviewer_engine_rejection,
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
    merge_note: str = ""


class HaltRolloutRequest(BaseModel):
    """Request body for POST /halt."""

    reason: str
    comment: str | None = None
    item_id: str | None = None


class CancelRolloutRequest(BaseModel):
    """Request body for POST /cancel."""

    reason: str


class DispatchRolloutRequest(BaseModel):
    """Optional request body for POST /{rollout_id}/dispatch."""

    dispatch_host_id: str | None = None
    # Engine for this rollout's short-lived merge REVIEWERS. None = inherit
    # projects.reviewer_engine, then the deployment default (Sonnet).
    # See dispatch_worker.resolve_reviewer_engine for the resolution order.
    reviewer_engine: BuildEngine | None = None

    @field_validator("reviewer_engine")
    @classmethod
    def _validate_reviewer_engine(cls, v: BuildEngine | None) -> BuildEngine | None:
        """Reject non-review-capable engines at the API boundary (422, not 409).

        Mirrors ``UpdateProjectRequest._validate_reviewer_engine``: the enum
        already rejects unknown engines, so this catches the
        registered-but-not-review-capable ones (talos, kiro) before the rollout
        is touched.  The service layer re-checks — this is the friendly error,
        not the guard.
        """
        if v is None:
            return v
        rejection = reviewer_engine_rejection(v.value)
        if rejection is not None:
            raise ValueError(rejection)
        return v


class ResetRolloutItemRequest(BaseModel):
    """Request body for POST /{rollout_id}/reset-item."""

    item_id: str


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

    Validates the legality contract, derives the DAG from the items' blockers
    plus file-overlap serialisation, persists it, and returns a plan summary.

    Args:
        body: item_ids to include in the wave.
        user: Injected authenticated user.

    Returns:
        Dict with rollout_id, status, plan (nodes + edges), planner_model,
        item_count, and per_item summary.

    Raises:
        HTTPException 422: Legality contract failure (detail includes per-item
            failures), another validation error, or a cyclic dependency graph.
        HTTPException 502: A subroutine raised RuntimeError.
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
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        # Derived DAG contained a cycle — the items' blockers need fixing.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        body: item_id, outcome, optional merge_actor, decision_rule and
            merge_note.
        user: Injected authenticated user.

    Idempotent: a repeat of the same terminal outcome returns 200 with
    ``already_recorded: true`` and changes nothing. A different outcome for an
    already-terminal item is a 422.

    Returns:
        Dict with rollout_item (updated row), newly_ready list,
        graph_complete and already_recorded.
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
            merge_note=body.merge_note,
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

    Child builds already on a dispatch host keep running (non-destructive);
    only not-yet-routed child runs are cancelled.

    Args:
        rollout_id: The wave run to halt.
        body: reason, optional comment, optional offending item_id.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict plus ``cancelled_run_ids``
        and ``in_flight_run_ids``.
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
    halted, failed).  Idempotent for already-cancelled waves.  Cancels every
    active child build run (forwarded to its dispatch host).

    Args:
        rollout_id: The wave run to cancel.
        body: reason for cancellation.
        user: Injected authenticated user.

    Returns:
        The updated autonomous_rollouts row dict plus ``cancelled_run_ids``.
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


@router.get("/{rollout_id}/merge-notes")
async def get_rollout_merge_notes(
    rollout_id: str,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Return the most recent merge notes for a rollout, newest first.

    Merge notes are the durable record of what each merged item changed that
    could invalidate a later item's spec.  The dispatch service reads this to
    feed the last N notes into each subsequent manage prompt.

    Args:
        rollout_id: The rollout to query.
        user: Injected authenticated user.
        limit: Max notes to return (1-50, default 10).

    Returns:
        Dict with a ``merge_notes`` list.
    """
    db = await get_db()
    try:
        notes = await rollout_service.get_recent_merge_notes(
            db, rollout_id, user.id, limit=limit
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc

    return {"merge_notes": notes}


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
    body: DispatchRolloutRequest | None = None,
) -> RunResponse:
    """Dispatch the wave manager agent for this rollout.

    Creates a manage-mode claude_runs row with item_id=NULL, scoped to the
    rollout. Transitions the rollout from pending → running.

    The request body is optional: send ``{"dispatch_host_id": "<uuid>"}`` to
    pin execution to a specific dispatch host (the pin is stored on the
    rollout and inherited by child build runs). A bodyless request or
    ``{}`` auto-routes the run.

    Send ``{"reviewer_engine": "claude-code-haiku"}`` to override the engine
    this rollout's merge reviewers run on.  Omitted/null falls through to
    ``projects.reviewer_engine`` and then to the deployment default (Sonnet).

    Args:
        rollout_id: The rollout to dispatch.
        user: Injected authenticated user.
        body: Optional DispatchRolloutRequest with dispatch_host_id and/or
            reviewer_engine.

    Returns:
        201 RunResponse with the created run.

    Raises:
        404 if rollout not found or caller doesn't own it.
        404 if the pinned dispatch host doesn't exist.
        409 if rollout is not in pending status.
    """
    db = await get_db()
    try:
        row = await dispatch_rollout_run(
            db,
            user.id,
            rollout_id,
            dispatch_host_id=body.dispatch_host_id if body is not None else None,
            reviewer_engine=(
                body.reviewer_engine.value
                if body is not None and body.reviewer_engine is not None
                else None
            ),
        )
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


@router.post("/{rollout_id}/reset-item")
async def reset_rollout_item(
    rollout_id: str,
    body: ResetRolloutItemRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return a dispatched rollout item to ``ready`` so it can be re-dispatched.

    Called by the dispatch worker when a reviewer returns a ``re-dispatch``
    verdict.  Without this, the re-dispatch would be a silent no-op: the wave
    linkage in ``dispatch_item`` is guarded by ``AND status = 'ready'`` (which
    is exactly what stops the startup re-adoption sweep double-dispatching an
    in-flight item), so an item still sitting in ``dispatched`` never gets
    relinked to the new run.

    Args:
        rollout_id: The rollout the item belongs to.
        body: ResetRolloutItemRequest naming the item.
        user: Injected authenticated user.

    Returns:
        ``{rollout_id, item_id, status, previous_run_id}``.

    Raises:
        404 if the rollout or the rollout item is not found.
        422 if the rollout is not running or the item is not dispatched.
    """
    db = await get_db()
    try:
        return await rollout_service.reset_rollout_item(
            db, user.id, rollout_id, body.item_id
        )
    except (NotFoundError, ValidationError) as exc:
        raise _map_exc(exc) from exc
