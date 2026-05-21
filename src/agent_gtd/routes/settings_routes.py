"""App settings API routes."""

import os
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.dispatch_constants import MAX_TIMEOUT_MINUTES, MIN_TIMEOUT_MINUTES
from agent_gtd.models import (
    AddDispatchHostRequest,
    BuildEngine,
    DispatchHostResponse,
    DispatchSettingsResponse,
    UpdateDispatchSettingsRequest,
    User,
)
from agent_gtd.routes.dispatch_routes import _capabilities_cache
from agent_gtd.services import settings_service
from agent_gtd.services.dispatch_router import probe_dispatch_host

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ENGINE_KEY = "dispatch.engine"
_AGENT_NAME_KEY = "dispatch.agent_name"
_PLAN_AGENT_NAME_KEY = "dispatch.plan_agent_name"
_BUILD_AGENT_NAME_KEY = "dispatch.build_agent_name"
_DEFAULT_MAX_TURNS_KEY = "dispatch.default_max_turns"
_DEFAULT_TIMEOUT_MINUTES_KEY = "dispatch.default_timeout_minutes"
_MANAGER_TIMEOUT_MINUTES_KEY = "dispatch.manager_default_timeout_minutes"
_MAX_AGENT_NAME_LEN = 64
_MIN_TURNS = 10
_MAX_TURNS = 500


def _mask_key(api_key: str) -> str:
    """Return '****' + last 4 chars of api_key, or '' if empty."""
    if not api_key:
        return ""
    suffix = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"****{suffix}"


async def _build_dispatch_response(db: Any, user_id: str) -> DispatchSettingsResponse:
    """Construct a DispatchSettingsResponse from DB state."""
    engine = await settings_service.get_setting(db, _ENGINE_KEY) or "claude-code"
    plan_agent_name = await settings_service.get_setting(db, _PLAN_AGENT_NAME_KEY) or ""
    build_agent_name = (
        await settings_service.get_setting(db, _BUILD_AGENT_NAME_KEY) or ""
    )

    turns_val = await settings_service.get_setting(db, _DEFAULT_MAX_TURNS_KEY)
    default_max_turns = (
        int(turns_val)
        if turns_val is not None
        else int(os.environ.get("DISPATCH_DEFAULT_MAX_TURNS", "100"))
    )

    timeout_val = await settings_service.get_setting(db, _DEFAULT_TIMEOUT_MINUTES_KEY)
    default_timeout_minutes = int(timeout_val) if timeout_val is not None else 30

    manager_timeout_val = await settings_service.get_setting(
        db, _MANAGER_TIMEOUT_MINUTES_KEY
    )
    manager_default_timeout_minutes = (
        int(manager_timeout_val) if manager_timeout_val is not None else 240
    )

    service_url = (
        await settings_service.get_user_setting(db, user_id, "dispatch.service_url")
        or ""
    )

    last4 = await settings_service.get_user_setting_last4(
        db, user_id, "dispatch.service_api_key"
    )
    preview = f"****{last4}" if last4 else ""

    return DispatchSettingsResponse(
        engine=BuildEngine(engine),
        plan_agent_name=plan_agent_name,
        build_agent_name=build_agent_name,
        default_max_turns=default_max_turns,
        default_timeout_minutes=default_timeout_minutes,
        manager_default_timeout_minutes=manager_default_timeout_minutes,
        service_url=service_url,
        service_api_key_preview=preview,
    )


@router.get("/dispatch", response_model=DispatchSettingsResponse)
async def get_dispatch_settings(
    user: Annotated[User, Depends(get_current_user)],
) -> DispatchSettingsResponse:
    """Return the caller's current dispatch settings.

    The ``service_api_key`` is never returned — only ``service_api_key_preview``
    (masked last 4 chars, e.g. ``****jL54``) is exposed, or ``""`` when unset.
    """
    db = await get_db()
    return await _build_dispatch_response(db, user.id)


@router.patch("/dispatch", response_model=DispatchSettingsResponse)
async def update_dispatch_settings(
    body: UpdateDispatchSettingsRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> DispatchSettingsResponse:
    """Update the caller's per-user dispatch configuration.

    Only provided fields are modified.  The ``service_api_key`` is stored
    as-is in ``user_settings`` and never returned in responses.
    """
    db = await get_db()

    if body.engine is not None:
        await settings_service.set_setting(db, _ENGINE_KEY, body.engine)
    if body.plan_agent_name is not None:
        if len(body.plan_agent_name) > _MAX_AGENT_NAME_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"plan_agent_name must be at most {_MAX_AGENT_NAME_LEN} chars",
            )
        await settings_service.set_setting(
            db, _PLAN_AGENT_NAME_KEY, body.plan_agent_name
        )
    if body.build_agent_name is not None:
        if len(body.build_agent_name) > _MAX_AGENT_NAME_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"build_agent_name must be at most {_MAX_AGENT_NAME_LEN} chars",
            )
        await settings_service.set_setting(
            db, _BUILD_AGENT_NAME_KEY, body.build_agent_name
        )
    if body.default_max_turns is not None:
        if not (_MIN_TURNS <= body.default_max_turns <= _MAX_TURNS):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"default_max_turns must be between {_MIN_TURNS} and {_MAX_TURNS}"
                ),
            )
        await settings_service.set_setting(
            db, _DEFAULT_MAX_TURNS_KEY, str(body.default_max_turns)
        )
    if body.default_timeout_minutes is not None:
        if not (
            MIN_TIMEOUT_MINUTES <= body.default_timeout_minutes <= MAX_TIMEOUT_MINUTES
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"default_timeout_minutes must be between "
                    f"{MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}"
                ),
            )
        await settings_service.set_setting(
            db, _DEFAULT_TIMEOUT_MINUTES_KEY, str(body.default_timeout_minutes)
        )
    if body.manager_default_timeout_minutes is not None:
        if not (
            MIN_TIMEOUT_MINUTES
            <= body.manager_default_timeout_minutes
            <= MAX_TIMEOUT_MINUTES
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"manager_default_timeout_minutes must be between "
                    f"{MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES}"
                ),
            )
        await settings_service.set_setting(
            db,
            _MANAGER_TIMEOUT_MINUTES_KEY,
            str(body.manager_default_timeout_minutes),
        )
    if body.service_url is not None:
        await settings_service.set_user_setting(
            db, user.id, "dispatch.service_url", body.service_url
        )
    if body.service_api_key is not None:
        await settings_service.set_user_setting(
            db, user.id, "dispatch.service_api_key", body.service_api_key
        )

    return await _build_dispatch_response(db, user.id)


@router.get("/dispatch/hosts", response_model=list[DispatchHostResponse])
async def list_dispatch_hosts(
    user: Annotated[User, Depends(get_current_user)],
) -> list[DispatchHostResponse]:
    """List the caller's configured dispatch hosts."""
    db = await get_db()
    hosts = await settings_service.get_dispatch_hosts(db, user.id)
    return [
        DispatchHostResponse(
            id=h["id"],
            label=h.get("label", ""),
            url=h["url"],
            api_key_preview=_mask_key(h["api_key"]),
            created_at=datetime.fromisoformat(h["created_at"]),
        )
        for h in hosts
    ]


@router.post(
    "/dispatch/hosts",
    response_model=DispatchHostResponse,
    status_code=201,
)
async def add_dispatch_host(
    body: AddDispatchHostRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> DispatchHostResponse:
    """Add a new dispatch host."""
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="url must be non-empty")
    if not body.api_key:
        raise HTTPException(status_code=422, detail="api_key must be non-empty")

    try:
        await probe_dispatch_host(url, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db = await get_db()
    try:
        host = await settings_service.add_dispatch_host(
            db, user.id, body.label, url, body.api_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Invalidate capabilities cache so the next GET reflects the new host
    _capabilities_cache.pop(user.id, None)

    return DispatchHostResponse(
        id=host["id"],
        label=host.get("label", ""),
        url=host["url"],
        api_key_preview=_mask_key(host["api_key"]),
        created_at=datetime.fromisoformat(host["created_at"]),
    )


@router.delete("/dispatch/hosts/{host_id}", status_code=204)
async def delete_dispatch_host(
    host_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Delete a dispatch host."""
    db = await get_db()
    deleted_url = await settings_service.remove_dispatch_host(db, user.id, host_id)
    if deleted_url is None:
        raise HTTPException(status_code=404, detail="Host not found")

    # Invalidate capabilities cache so the next GET reflects the removed host
    _capabilities_cache.pop(user.id, None)

    return Response(status_code=204)
