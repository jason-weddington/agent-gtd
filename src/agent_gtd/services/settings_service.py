"""Settings service: app-level and per-user key-value stores."""

# TODO: encrypt dispatch.service_api_key at rest (not implemented; we trust our own DB)

import os
from datetime import UTC, datetime
from typing import Any


async def get_setting(db: Any, key: str, default: str | None = None) -> str | None:
    """Retrieve a deployment-wide setting value by key.

    Returns *default* when the key has no stored value.
    """
    row = await db.fetchrow("SELECT value FROM app_settings WHERE key = $1", key)
    return str(row["value"]) if row else default


async def set_setting(db: Any, key: str, value: str) -> None:
    """Persist a deployment-wide setting value (upsert)."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO app_settings (key, value, updated_at) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (key) DO UPDATE "
        "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
        key,
        value,
        now,
    )


async def get_user_setting(db: Any, user_id: str, key: str) -> str | None:
    """Retrieve a per-user setting value by key.

    Returns None when the key has no stored value for the user.
    """
    row = await db.fetchrow(
        "SELECT value FROM user_settings WHERE user_id = $1 AND key = $2",
        user_id,
        key,
    )
    return str(row["value"]) if row else None


async def get_user_setting_last4(db: Any, user_id: str, key: str) -> str:
    """Return the last 4 chars of a per-user setting value, or '' if unset.

    Uses a custom SQL query so this function is literally incapable of
    returning more than 4 characters — a defense-in-depth guarantee for
    the settings API's read path.

    Compatible with both PostgreSQL (asyncpg) and the SQLite fallback; uses
    a CASE expression instead of GREATEST/MAX(a,b) which differ across
    dialects.
    """
    row = await db.fetchrow(
        "SELECT SUBSTR(value, "
        "CASE WHEN LENGTH(value) > 4 THEN LENGTH(value) - 3 ELSE 1 END"
        ") AS last4 "
        "FROM user_settings WHERE user_id = $1 AND key = $2",
        user_id,
        key,
    )
    if row is None:
        return ""
    return str(row["last4"])


async def set_user_setting(db: Any, user_id: str, key: str, value: str) -> None:
    """Persist a per-user setting value (upsert)."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO user_settings (user_id, key, value, updated_at) "
        "VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (user_id, key) DO UPDATE "
        "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
        user_id,
        key,
        value,
        now,
    )


async def get_dispatch_config(db: Any, user_id: str) -> dict[str, str] | None:
    """Return dispatch config for a user, or None if not configured.

    Returns ``{"url": ..., "api_key": ...}`` when both values are set.

    For the local admin user only (``LOCAL_USER_ID``), falls back to the
    ``DISPATCH_SERVICE_URL`` / ``DISPATCH_SERVICE_API_KEY`` environment variables
    for backward compatibility during rollout.  All other users must configure
    their own URL and key via Settings.
    """
    from agent_gtd.database import LOCAL_USER_ID

    url = await get_user_setting(db, user_id, "dispatch.service_url")
    api_key = await get_user_setting(db, user_id, "dispatch.service_api_key")

    if url and api_key:
        return {"url": url, "api_key": api_key}

    # Env-var fallback for the local admin user only.
    if user_id == LOCAL_USER_ID:
        url = url or os.environ.get("DISPATCH_SERVICE_URL", "")
        api_key = api_key or os.environ.get("DISPATCH_SERVICE_API_KEY", "")
        if url and api_key:
            return {"url": url, "api_key": api_key}

    return None
