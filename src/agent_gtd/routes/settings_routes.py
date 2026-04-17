"""App settings API routes."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_gtd.auth import get_current_user
from agent_gtd.database import get_db
from agent_gtd.models import MaxConcurrentRequest, User
from agent_gtd.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])

_MAX_CONCURRENT_KEY = "dispatch.max_concurrent"
_MIN_VALUE = 1
_MAX_VALUE = 20


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
