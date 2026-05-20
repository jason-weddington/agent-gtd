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


async def get_dispatch_hosts(db: Any, user_id: str) -> list[dict[str, str]]:
    """Return dispatch hosts for a user, with lazy migration from user_settings.

    If no dispatch_hosts rows exist for the user but user_settings has
    dispatch.service_url + dispatch.service_api_key, silently migrates those
    to a single dispatch_hosts row with label="default". The user_settings
    rows are NOT deleted (backward compat).

    Returns:
        List of dicts with keys: id, url, api_key, label.
    """
    import uuid
    from datetime import UTC, datetime

    rows = await db.fetch(
        "SELECT id, url, api_key, label, created_at FROM dispatch_hosts "
        "WHERE user_id = $1 ORDER BY created_at ASC",
        user_id,
    )
    if rows:
        return [dict(r) for r in rows]

    # Lazy migration from legacy single-host user_settings
    url = await get_user_setting(db, user_id, "dispatch.service_url")
    api_key = await get_user_setting(db, user_id, "dispatch.service_api_key")
    if url and api_key:
        host_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "INSERT INTO dispatch_hosts "
            "(id, user_id, label, url, api_key, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "ON CONFLICT (user_id, url) DO NOTHING",
            host_id,
            user_id,
            "default",
            url,
            api_key,
            now,
            now,
        )
        # Re-fetch to return the canonical row
        rows = await db.fetch(
            "SELECT id, url, api_key, label, created_at FROM dispatch_hosts "
            "WHERE user_id = $1 ORDER BY created_at ASC",
            user_id,
        )
        return [dict(r) for r in rows]

    return []


async def add_dispatch_host(
    db: Any, user_id: str, label: str, url: str, api_key: str
) -> dict[str, str]:
    """Add a new dispatch host for a user.

    Returns:
        Dict with keys: id, user_id, label, url, api_key, created_at, updated_at.

    Raises:
        ValueError: If a host with the same URL already exists for this user.
    """
    import uuid
    from datetime import UTC, datetime

    host_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    try:
        await db.execute(
            "INSERT INTO dispatch_hosts "
            "(id, user_id, label, url, api_key, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            host_id,
            user_id,
            label,
            url,
            api_key,
            now,
            now,
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper() or "unique" in str(exc).lower():
            msg = f"A dispatch host with URL '{url}' already exists"
            raise ValueError(msg) from exc
        raise
    row = await db.fetchrow("SELECT * FROM dispatch_hosts WHERE id = $1", host_id)
    assert row is not None  # noqa: S101
    return dict(row)


async def remove_dispatch_host(db: Any, user_id: str, host_id: str) -> bool:
    """Remove a dispatch host owned by user_id.

    Returns:
        True if a row was deleted, False if not found.
    """
    # Check existence first (compatible with both asyncpg and SQLite)
    row = await db.fetchrow(
        "SELECT id FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    return True


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
