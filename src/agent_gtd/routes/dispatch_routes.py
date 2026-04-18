"""Dispatch run API routes for Claude Code headless agents."""

import logging
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError, RunActiveError
from agent_gtd.models import CreateRunRequest, RunResponse, RunStatus, User
from agent_gtd.services import dispatch_service
from agent_gtd.services.settings_service import get_dispatch_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])


def _run_response(row: dict[str, object]) -> RunResponse:
    return RunResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]),
        project_id=str(row["project_id"]),
        status=RunStatus(str(row["status"])),
        feature_branch=str(row.get("feature_branch", "")),
        workspace_dir=str(row.get("workspace_dir", "")),
        max_turns=int(str(row.get("max_turns", 50))),
        mode=str(row.get("mode", "build")),
        started_at=(
            datetime.fromisoformat(str(row["started_at"]))
            if row.get("started_at")
            else None
        ),
        finished_at=(
            datetime.fromisoformat(str(row["finished_at"]))
            if row.get("finished_at")
            else None
        ),
        error_msg=str(row.get("error_msg", "")),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


async def _check_dispatch_service(db: Any, user_id: str) -> None:
    """Pre-flight check: verify dispatch is configured and the service is reachable."""
    settings = await get_dispatch_config(db, user_id)
    if not settings:
        raise HTTPException(
            status_code=503,
            detail="Dispatch service not configured",
        )
    url = settings["url"]
    api_key = settings["api_key"]
    try:
        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            resp = await client.get(
                f"{url}/health",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5.0,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=503,
                    detail="Dispatch service returned an error",
                )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Dispatch service is unreachable",
        ) from None
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail="Dispatch service timed out",
        ) from None


@router.post(
    "/api/items/{item_id}/dispatch",
    response_model=RunResponse,
    status_code=201,
)
async def dispatch_item(
    item_id: str,
    body: CreateRunRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> RunResponse:
    """Dispatch a Claude Code agent to work on an item.

    Only the project owner may dispatch agents.  Project-less (inbox) items
    are always dispatchable by their owner.
    """
    db = await get_db()

    # --- Ownership guard ---
    # Fetch the item's project_id without an access filter (we need the raw
    # project_id to check ownership, even for members who can read the item).
    item_check = await db.fetchrow(
        "SELECT project_id FROM items WHERE id = $1", item_id
    )
    if item_check is not None and item_check["project_id"] is not None:
        project_check = await db.fetchrow(
            "SELECT user_id FROM projects WHERE id = $1",
            item_check["project_id"],
        )
        if project_check is not None and str(project_check["user_id"]) != user.id:
            raise HTTPException(
                status_code=403,
                detail="only the project owner can dispatch agents",
            )

    # Pre-flight: ensure dispatch service is configured and reachable
    await _check_dispatch_service(db, user.id)

    try:
        row = await dispatch_service.create_run(
            db, user.id, item_id, max_turns=body.max_turns, mode=body.mode
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except RunActiveError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None

    # Enqueue for background processing
    try:
        from agent_gtd.dispatch_worker import enqueue_run

        enqueue_run(str(row["id"]))
    except AssertionError:
        pass  # Worker not started (e.g. in tests)

    return _run_response(row)


@router.get(
    "/api/items/{item_id}/runs",
    response_model=list[RunResponse],
)
async def list_item_runs(
    item_id: str,
    user: Annotated[User, Depends(get_current_user)],
    status: str | None = None,
) -> list[RunResponse]:
    """List dispatch runs for an item."""
    db = await get_db()
    rows = await dispatch_service.list_runs(db, user.id, item_id=item_id, status=status)
    return [_run_response(r) for r in rows]


@router.get("/api/runs", response_model=list[RunResponse])
async def list_runs(
    user: Annotated[User, Depends(get_current_user)],
    item_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
) -> list[RunResponse]:
    """List dispatch runs, optionally filtered by item, project, and/or status."""
    db = await get_db()
    rows = await dispatch_service.list_runs(
        db, user.id, item_id=item_id, project_id=project_id, status=status
    )
    return [_run_response(r) for r in rows]


@router.get("/api/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> RunResponse:
    """Get a single dispatch run by ID."""
    db = await get_db()
    try:
        row = await dispatch_service.get_run(db, user.id, run_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Run not found") from None
    return _run_response(row)


@router.delete("/api/runs/{run_id}", status_code=204)
async def cancel_run(
    run_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Cancel an active dispatch run."""
    db = await get_db()
    try:
        await dispatch_service.cancel_run(db, user.id, run_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
