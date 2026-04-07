"""Dispatch run API routes for Claude Code headless agents."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import NotFoundError, RunActiveError
from agent_gtd.models import CreateRunRequest, RunResponse, RunStatus, User
from agent_gtd.services import dispatch_service

router = APIRouter(tags=["dispatch"])


def _run_response(row: dict[str, object]) -> RunResponse:
    return RunResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]),
        project_id=str(row["project_id"]),
        status=RunStatus(str(row["status"])),
        feature_branch=str(row.get("feature_branch", "")),
        workspace_dir=str(row.get("workspace_dir", "")),
        max_turns=int(str(row.get("max_turns", 20))),
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
    """Dispatch a Claude Code agent to work on an item."""
    db = await get_db()
    try:
        row = await dispatch_service.create_run(
            db, user.id, item_id, max_turns=body.max_turns
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
        run = await dispatch_service.cancel_run(db, user.id, run_id)
        # Kill the subprocess if it's running
        pid = run.get("pid")
        if pid:
            import contextlib
            import os
            import signal

            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(int(str(pid))), signal.SIGTERM)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
