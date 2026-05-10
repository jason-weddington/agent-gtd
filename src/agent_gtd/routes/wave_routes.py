"""Wave run API routes for the executor cycle.

Provides REST endpoints that mirror the four wave manager MCP tools.  These
routes are used by HttpBackend so remote executor agents can call them over
HTTP without direct DB access.

Endpoints:
    GET  /api/wave-runs/{wave_run_id}/advance         → advance_wave result
    POST /api/wave-runs/{wave_run_id}/complete-item   → complete_in_wave result
    POST /api/wave-runs/{wave_run_id}/halt            → updated wave run
    POST /api/wave-runs/{wave_run_id}/replan          → new plan info
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError, ValidationError
from agent_gtd.models import User
from agent_gtd.services import wave_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wave-runs", tags=["wave"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


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


class ReplanWaveRequest(BaseModel):
    """Request body for POST /replan."""

    from_item: str | None = None


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
