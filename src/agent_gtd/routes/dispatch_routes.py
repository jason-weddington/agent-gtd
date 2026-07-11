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
    HostFullError,
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
from agent_gtd.services.settings_service import get_dispatch_hosts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])

# ---------------------------------------------------------------------------
# Capabilities cache (in-process, per user_id, 60-second TTL)
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
        engine=str(row["engine"]) if row.get("engine") else None,
        engine_actual=str(row["engine_actual"]) if row.get("engine_actual") else None,
        dispatch_host_url=(
            str(row["dispatch_host_url"]) if row.get("dispatch_host_url") else None
        ),
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
        engine=str(row["engine"]) if row.get("engine") else None,
        engine_actual=str(row["engine_actual"]) if row.get("engine_actual") else None,
        dispatch_host_url=(
            str(row["dispatch_host_url"]) if row.get("dispatch_host_url") else None
        ),
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
        engine=str(row["engine"]) if row.get("engine") else None,
        engine_actual=str(row["engine_actual"]) if row.get("engine_actual") else None,
        dispatch_host_url=(
            str(row["dispatch_host_url"]) if row.get("dispatch_host_url") else None
        ),
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
    """Pre-flight check: verify at least one dispatch host is configured and reachable.

    Uses ``get_dispatch_hosts`` so brand-new users who configured a host via the
    hosts API (without legacy ``user_settings`` keys) are not incorrectly blocked.

    Raises 503 if:
    - No hosts are configured for the user.
    - All configured hosts fail the ``/health`` check.
    """
    import asyncio

    hosts = await get_dispatch_hosts(db, user_id)
    if not hosts:
        raise HTTPException(
            status_code=503,
            detail="Project owner has not configured dispatch",
        )

    async def _ping_host(host: dict[str, str]) -> bool:
        """Return True if the host /health endpoint responds with HTTP 200."""
        try:
            async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
                resp = await client.get(
                    f"{host['url']}/health",
                    headers={"Authorization": f"Bearer {host['api_key']}"},
                    timeout=5.0,
                )
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            return False

    results = await asyncio.gather(*(_ping_host(h) for h in hosts))
    if not any(results):
        raise HTTPException(
            status_code=503,
            detail="Dispatch service is unreachable",
        )


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


async def _fetch_host_capabilities(host: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch /info from a single dispatch host for capabilities aggregation.

    Returns the parsed JSON dict on success, or None if the host is unreachable.
    This is a module-level function so tests can patch it.
    """
    url = host["url"]
    try:
        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            resp = await client.get(f"{url}/info", timeout=5.0)
            resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result
    except Exception:
        logger.warning("dispatch /info failed for %s", url)
        return None


@router.get(
    "/api/dispatch/capabilities",
    response_model=DispatchCapabilitiesResponse,
)
async def get_dispatch_capabilities(
    user: Annotated[User, Depends(get_current_user)],
) -> DispatchCapabilitiesResponse:
    """Proxy dispatch service capabilities: engine + agents + total capacity.

    Queries /info on ALL configured hosts concurrently. Deduplicates agents by name.
    Computes total_capacity as the sum of max_concurrent_runs from responding hosts.
    Always returns HTTP 200; failures degrade gracefully.
    Responses cached in-process for 60 seconds per user.
    """
    db = await get_db()
    hosts = await get_dispatch_hosts(db, user.id)
    if not hosts:
        return DispatchCapabilitiesResponse()

    # Short-circuit on cache hit (keyed by user_id)
    now = _now()
    cached = _capabilities_cache.get(user.id)
    if cached is not None and (now - cached[0]) < _CAPABILITIES_CACHE_TTL:
        logger.debug("dispatch capabilities cache hit for user %s", user.id)
        return cached[1]

    results = await asyncio.gather(
        *[_fetch_host_capabilities(h) for h in hosts],
        return_exceptions=True,
    )

    engines_seen: set[str] = set()
    versions_seen: set[str] = set()
    agents_seen: dict[str, DispatchAgentInfo] = {}
    total_capacity = 0

    for res in results:
        if isinstance(res, BaseException) or res is None:
            continue
        info = res
        if "engine" in info:
            engines_seen.add(str(info["engine"]))
        if "version" in info:
            versions_seen.add(str(info["version"]))
        # agents is list[str] in new /info shape
        for agent_name in info.get("agents", []):
            name_str = str(agent_name)
            if name_str not in agents_seen:
                agents_seen[name_str] = DispatchAgentInfo(name=name_str)
        # Sum capacity
        max_cap = info.get("max_concurrent_runs")
        if max_cap is not None:
            total_capacity += int(max_cap)

    agents = list(agents_seen.values())
    result = DispatchCapabilitiesResponse(
        engines=sorted(engines_seen),
        versions=sorted(versions_seen),
        agents=agents,
        total_capacity=total_capacity if total_capacity > 0 else None,
    )
    _capabilities_cache[user.id] = (now, result)
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

    # Validate dispatch_host_id when explicitly provided
    if body.dispatch_host_id is not None:
        hosts = await get_dispatch_hosts(db, owner_id)
        host_match = next((h for h in hosts if h["id"] == body.dispatch_host_id), None)
        if host_match is None:
            raise HTTPException(
                status_code=404,
                detail=f"Dispatch host {body.dispatch_host_id!r} not found",
            )
        # Check capacity via /info
        try:
            info = await _fetch_host_capabilities(host_match)
        except Exception:
            info = None
        if info is not None:
            available = info.get("max_concurrent_runs", 0) - info.get("active_runs", 0)
            if available <= 0:
                host_label = host_match.get("label", host_match["url"])
                raise HTTPException(
                    status_code=409,
                    detail=str(
                        HostFullError(
                            host_label,
                            int(info.get("max_concurrent_runs", 0)),
                        )
                    ),
                )

    try:
        row = await dispatch_service.create_run(
            db,
            user.id,
            item_id,
            max_turns=body.max_turns,
            mode=body.mode,
            rollout_id=body.rollout_id,
            dispatch_host_id=body.dispatch_host_id,
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
