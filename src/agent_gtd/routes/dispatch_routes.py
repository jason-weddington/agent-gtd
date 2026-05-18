"""Dispatch run API routes for Claude Code headless agents."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.exceptions import (
    BlockersUnresolvedError,
    NotFoundError,
    RolloutItemLockedError,
    RunActiveError,
    ValidationError,
)
from agent_gtd.models import (
    CreateRunRequest,
    DispatchAgentInfo,
    DispatchCapabilitiesResponse,
    DispatchMode,
    FailedRunResponse,
    LocalRunStatus,
    RunResponse,
    StaleRunResponse,
    User,
)
from agent_gtd.services import dispatch_service, project_service
from agent_gtd.services.settings_service import get_dispatch_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])

# ---------------------------------------------------------------------------
# Capabilities cache (in-process, per dispatch URL, 60-second TTL)
# ---------------------------------------------------------------------------

_capabilities_cache: dict[str, tuple[float, DispatchCapabilitiesResponse]] = {}
_CAPABILITIES_CACHE_TTL = 60.0


def _now() -> float:
    """Return current monotonic time.  Isolated for testability."""
    return time.monotonic()


def _run_response(row: dict[str, object]) -> RunResponse:
    return RunResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]) if row.get("item_id") else None,
        project_id=str(row["project_id"]),
        status=LocalRunStatus(str(row["status"])),
        feature_branch=str(row.get("feature_branch", "")),
        workspace_dir=str(row.get("workspace_dir", "")),
        max_turns=int(str(row.get("max_turns", 50))),
        mode=DispatchMode(str(row.get("mode", "build"))),
        rollout_id=str(row["rollout_id"]) if row.get("rollout_id") else None,
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
        dispatched_by_email=(
            str(row["dispatched_by_email"]) if row.get("dispatched_by_email") else None
        ),
    )


def _failed_run_response(row: dict[str, object]) -> FailedRunResponse:
    """Build a FailedRunResponse from an enriched row.

    Includes item_title and project_name from JOIN.
    """
    return FailedRunResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]) if row.get("item_id") else None,
        project_id=str(row["project_id"]),
        status=LocalRunStatus(str(row["status"])),
        feature_branch=str(row.get("feature_branch", "")),
        workspace_dir=str(row.get("workspace_dir", "")),
        max_turns=int(str(row.get("max_turns", 50))),
        mode=DispatchMode(str(row.get("mode", "build"))),
        rollout_id=str(row["rollout_id"]) if row.get("rollout_id") else None,
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
        dispatched_by_email=(
            str(row["dispatched_by_email"]) if row.get("dispatched_by_email") else None
        ),
        item_title=str(row["item_title"]) if row.get("item_title") else None,
        project_name=str(row.get("project_name", "")),
    )


def _stale_run_response(row: dict[str, object]) -> StaleRunResponse:
    """Build a StaleRunResponse from an enriched row.

    Includes item_title, project_name, and item_status from JOIN.
    """
    return StaleRunResponse(
        id=str(row["id"]),
        item_id=str(row["item_id"]) if row.get("item_id") else None,
        project_id=str(row["project_id"]),
        status=LocalRunStatus(str(row["status"])),
        feature_branch=str(row.get("feature_branch", "")),
        workspace_dir=str(row.get("workspace_dir", "")),
        max_turns=int(str(row.get("max_turns", 50))),
        mode=DispatchMode(str(row.get("mode", "build"))),
        rollout_id=str(row["rollout_id"]) if row.get("rollout_id") else None,
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
        dispatched_by_email=(
            str(row["dispatched_by_email"]) if row.get("dispatched_by_email") else None
        ),
        item_title=str(row["item_title"]) if row.get("item_title") else None,
        project_name=str(row.get("project_name", "")),
        item_status=str(row.get("item_status", "")),
    )


async def _check_dispatch_service(db: Any, user_id: str) -> None:
    """Pre-flight check: verify dispatch is configured and the service is reachable."""
    settings = await get_dispatch_config(db, user_id)
    if not settings:
        raise HTTPException(
            status_code=503,
            detail="Project owner has not configured dispatch",
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


async def _fetch_dispatch_info(url: str, api_key: str) -> dict[str, str | None]:
    """Fetch engine/version from the dispatch service ``/info`` endpoint.

    Raises any ``httpx`` exception on failure so callers can handle gracefully.
    """
    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        resp = await client.get(
            f"{url}/info",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5.0,
        )
        resp.raise_for_status()
    data: dict[str, object] = resp.json()
    return {
        "engine": str(data["engine"]) if "engine" in data else None,
        "version": str(data["version"]) if "version" in data else None,
    }


async def _fetch_dispatch_agents(url: str, api_key: str) -> list[dict[str, object]]:
    """Fetch the agents list from the dispatch service ``/agents`` endpoint.

    The dispatch service returns ``{"agents": [...]}``; this helper unwraps
    the envelope and returns the inner list. Raises any ``httpx`` exception
    on failure so callers can handle gracefully.
    """
    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        resp = await client.get(
            f"{url}/agents",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5.0,
        )
        resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        agents = data.get("agents", [])
        if isinstance(agents, list):
            return agents
    return []


@router.get(
    "/api/dispatch/capabilities",
    response_model=DispatchCapabilitiesResponse,
)
async def get_dispatch_capabilities(
    user: Annotated[User, Depends(get_current_user)],
) -> DispatchCapabilitiesResponse:
    """Proxy dispatch service capabilities: engine identity + available agents.

    Always returns HTTP 200.  If dispatch is not configured, or if upstream
    calls fail, the corresponding fields are null / empty rather than raising
    a 5xx error.  Responses are cached in-process for 60 seconds per URL.
    """
    db = await get_db()
    settings = await get_dispatch_config(db, user.id)
    if not settings:
        return DispatchCapabilitiesResponse()

    url = settings["url"]
    api_key = settings["api_key"]

    # Short-circuit on cache hit
    now = _now()
    cached = _capabilities_cache.get(url)
    if cached is not None and (now - cached[0]) < _CAPABILITIES_CACHE_TTL:
        logger.debug("dispatch capabilities cache hit for %s", url)
        return cached[1]

    # Parallel upstream calls — failures degrade gracefully, never propagate
    info_result: dict[str, str | None] | BaseException
    agents_result: list[dict[str, object]] | BaseException
    (
        info_result,
        agents_result,
    ) = await asyncio.gather(
        _fetch_dispatch_info(url, api_key),
        _fetch_dispatch_agents(url, api_key),
        return_exceptions=True,
    )

    engine: str | None = None
    version: str | None = None
    agents: list[DispatchAgentInfo] = []

    if isinstance(info_result, BaseException):
        logger.warning("dispatch /info failed for %s: %s", url, info_result)
    else:
        engine = info_result.get("engine")
        version = info_result.get("version")

    if isinstance(agents_result, BaseException):
        logger.warning("dispatch /agents failed for %s: %s", url, agents_result)
    else:
        agents = [DispatchAgentInfo.model_validate(a) for a in agents_result]

    result = DispatchCapabilitiesResponse(engine=engine, version=version, agents=agents)
    _capabilities_cache[url] = (now, result)
    return result


@router.post(
    "/api/items/{item_id}/dispatch",
    response_model=RunResponse,
    status_code=201,
)
async def dispatch_item(
    item_id: str,
    body: CreateRunRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> RunResponse | Response:
    """Dispatch a Claude Code agent to work on an item.

    Only the project owner may dispatch agents.  Project-less (inbox) items
    are always dispatchable by their owner.
    """
    db = await get_db()

    # --- Access check + owner discovery ---
    # Fetch the item's project_id without an access filter (we need the raw
    # project_id to check membership, even for items whose project the caller
    # only belongs to as a member).
    owner_id = user.id  # default for inbox items
    item_check = await db.fetchrow(
        "SELECT project_id FROM items WHERE id = $1", item_id
    )
    if item_check is not None and item_check["project_id"] is not None:
        project_check = await db.fetchrow(
            "SELECT user_id FROM projects WHERE id = $1 AND "
            "(user_id = $2 OR EXISTS "
            "(SELECT 1 FROM project_members WHERE project_id = $3 AND user_id = $4))",
            str(item_check["project_id"]),
            user.id,
            str(item_check["project_id"]),
            user.id,
        )
        if project_check is None:
            raise HTTPException(
                status_code=403,
                detail="only project members can dispatch agents",
            )
        # Dispatch config always comes from the project owner, not the caller.
        owner_id = str(project_check["user_id"])

    # Pre-flight: ensure the project owner's dispatch service is configured
    await _check_dispatch_service(db, owner_id)

    try:
        row = await dispatch_service.create_run(
            db,
            user.id,
            item_id,
            max_turns=body.max_turns,
            mode=body.mode,
            rollout_id=body.rollout_id,
        )
    except RolloutItemLockedError as e:
        raise HTTPException(status_code=409, detail=e.detail) from None
    except BlockersUnresolvedError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": e.detail, "blockers": e.blockers},
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except RunActiveError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValidationError as e:
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
    scope: str | None = None,
) -> list[RunResponse]:
    """List dispatch runs, optionally filtered by item, project, and/or status.

    The ``scope`` query parameter controls whose runs are returned:

    - ``user``: only runs dispatched by the caller.
    - ``accessible_projects``: runs in all projects the caller can access
      (owned or shared), regardless of who dispatched them.
    - omitted (default): behaves as ``user`` unless ``project_id`` refers to a
      shared project, in which case it auto-elevates to ``accessible_projects``
      so members see all activity in the project.
    """
    if scope is not None and scope not in ("user", "accessible_projects"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Must be 'user' or 'accessible_projects'.",
        )
    db = await get_db()

    # When the caller has not pinned a scope, auto-detect: shared projects
    # get "accessible_projects" so members see all runs in the project.
    # An explicit scope=user or scope=accessible_projects is always honoured.
    if scope is None:
        effective_scope: Literal["user", "accessible_projects"] = "user"
        if project_id is not None:
            try:
                proj = await project_service.get_project(db, user.id, project_id)
                is_shared = (proj.get("member_count") or 0) > 0 or proj.get(
                    "user_id"
                ) != user.id
                if is_shared:
                    effective_scope = "accessible_projects"
            except NotFoundError:
                raise HTTPException(
                    status_code=404, detail="Project not found"
                ) from None
    else:
        effective_scope = cast("Literal['user', 'accessible_projects']", scope)

    rows = await dispatch_service.list_runs(
        db,
        user.id,
        item_id=item_id,
        project_id=project_id,
        status=status,
        scope=effective_scope,
    )
    return [_run_response(r) for r in rows]


@router.get("/api/runs/failures", response_model=list[FailedRunResponse])
async def list_failed_runs(
    user: Annotated[User, Depends(get_current_user)],
    limit: int = 100,
) -> list[FailedRunResponse]:
    """List failed and timeout runs across the user's accessible projects.

    Returns up to ``limit`` (max 100) failed/timeout runs enriched with
    ``item_title`` and ``project_name``, ordered by ``finished_at`` DESC.

    This endpoint is declared before ``/{run_id}`` to avoid FastAPI
    path-collision — FastAPI matches routes in declaration order.
    """
    db = await get_db()
    rows = await dispatch_service.list_failed_runs(db, user.id, limit=limit)
    return [_failed_run_response(r) for r in rows]


@router.get("/api/runs/stale", response_model=list[StaleRunResponse])
async def list_stale_runs(
    user: Annotated[User, Depends(get_current_user)],
    hours: int = 72,
    limit: int = 100,
) -> list[StaleRunResponse]:
    """List successful build-mode runs whose item status was not advanced.

    Surfaces the "agent completed but skipped the status-flip" scenario:
    runs with ``status='success'`` and ``finished_at`` within the past
    ``hours`` hours whose linked item is still in a non-terminal status
    (not review / done / cancelled).

    This endpoint is declared before ``/{run_id}`` to avoid FastAPI
    path-collision — FastAPI matches routes in declaration order.
    """
    db = await get_db()
    rows = await dispatch_service.list_stale_completed_runs(
        db, user.id, hours=hours, limit=limit
    )
    return [_stale_run_response(r) for r in rows]


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
