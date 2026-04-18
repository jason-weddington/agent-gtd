"""App settings API routes."""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.models import (
    DispatchSettingsResponse,
    MaxConcurrentRequest,
    UpdateDispatchSettingsRequest,
    User,
)
from agent_gtd.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])

_MAX_CONCURRENT_KEY = "dispatch.max_concurrent"
_ENGINE_KEY = "dispatch.engine"
_AGENT_NAME_KEY = "dispatch.agent_name"
_MIN_VALUE = 1
_MAX_VALUE = 20
_VALID_ENGINES = {"claude", "kiro"}
_MAX_AGENT_NAME_LEN = 64


async def _build_dispatch_response(db: Any, user_id: str) -> DispatchSettingsResponse:
    """Construct a DispatchSettingsResponse from DB state."""
    val = await settings_service.get_setting(db, _MAX_CONCURRENT_KEY)
    max_concurrent = (
        int(val)
        if val is not None
        else int(os.environ.get("DISPATCH_MAX_CONCURRENT", "6"))
    )

    engine = await settings_service.get_setting(db, _ENGINE_KEY) or "claude"
    agent_name = await settings_service.get_setting(db, _AGENT_NAME_KEY) or ""

    service_url = (
        await settings_service.get_user_setting(db, user_id, "dispatch.service_url")
        or ""
    )

    last4 = await settings_service.get_user_setting_last4(
        db, user_id, "dispatch.service_api_key"
    )
    preview = f"****{last4}" if last4 else ""

    return DispatchSettingsResponse(
        engine=engine,
        agent_name=agent_name,
        max_concurrent=max_concurrent,
        service_url=service_url,
        service_api_key_preview=preview,
    )


@router.get("/dispatch/max-concurrent")
async def get_max_concurrent(
    _user: Annotated[User, Depends(get_current_user)],
) -> dict[str, int]:
    """Return the current dispatch concurrency cap.

    Falls back to the ``DISPATCH_MAX_CONCURRENT`` env var (default 6) when no
    DB row has been stored yet.
    """
    db = await get_db()
    val = await settings_service.get_setting(db, _MAX_CONCURRENT_KEY)
    if val is None:
        val = os.environ.get("DISPATCH_MAX_CONCURRENT", "6")
    return {"value": int(val)}


@router.patch("/dispatch/max-concurrent")
async def set_max_concurrent(
    body: MaxConcurrentRequest,
    _user: Annotated[User, Depends(get_current_user)],
) -> dict[str, int]:
    """Update the dispatch concurrency cap (1-20).

    The new value takes effect after the next service restart.
    """
    if not (_MIN_VALUE <= body.value <= _MAX_VALUE):
        raise HTTPException(
            status_code=422,
            detail=f"value must be between {_MIN_VALUE} and {_MAX_VALUE}",
        )
    db = await get_db()
    await settings_service.set_setting(db, _MAX_CONCURRENT_KEY, str(body.value))
    return {"value": body.value}


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
        if body.engine not in _VALID_ENGINES:
            raise HTTPException(
                status_code=422,
                detail=f"engine must be one of {sorted(_VALID_ENGINES)}",
            )
        await settings_service.set_setting(db, _ENGINE_KEY, body.engine)
    if body.agent_name is not None:
        if len(body.agent_name) > _MAX_AGENT_NAME_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"agent_name must be at most {_MAX_AGENT_NAME_LEN} chars",
            )
        await settings_service.set_setting(db, _AGENT_NAME_KEY, body.agent_name)
    if body.service_url is not None:
        await settings_service.set_user_setting(
            db, user.id, "dispatch.service_url", body.service_url
        )
    if body.service_api_key is not None:
        await settings_service.set_user_setting(
            db, user.id, "dispatch.service_api_key", body.service_api_key
        )

    return await _build_dispatch_response(db, user.id)
