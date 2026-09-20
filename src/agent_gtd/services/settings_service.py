"""Settings service: app-level and per-user key-value stores."""

# TODO: encrypt dispatch.service_api_key at rest (not implemented; we trust our own DB)

import os
from datetime import UTC, datetime
from typing import Any

from agent_gtd.database import decode_json_list, encode_json_list, normalize_labels


def _decode_host_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decode a dispatch_hosts row's capability_labels from JSON text in-place."""
    raw = row.get("capability_labels")
    row["capability_labels"] = (
        raw if isinstance(raw, list) else (decode_json_list(str(raw)) if raw else [])
    )
    return row


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


async def get_dispatch_hosts(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Return dispatch hosts for a user, with lazy migration from user_settings.

    If no dispatch_hosts rows exist for the user but user_settings has
    dispatch.service_url + dispatch.service_api_key, silently migrates those
    to a single dispatch_hosts row with label="default". The user_settings
    rows are NOT deleted (backward compat).

    Returns:
        List of dicts with keys: id, url, api_key, label, capability_labels
        (decoded to list[str]).
    """
    import uuid
    from datetime import UTC, datetime

    rows = await db.fetch(
        "SELECT id, url, api_key, label, capability_labels, created_at "
        "FROM dispatch_hosts WHERE user_id = $1 ORDER BY created_at ASC",
        user_id,
    )
    if rows:
        return [_decode_host_row(dict(r)) for r in rows]

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
            "SELECT id, url, api_key, label, capability_labels, created_at "
            "FROM dispatch_hosts WHERE user_id = $1 ORDER BY created_at ASC",
            user_id,
        )
        return [_decode_host_row(dict(r)) for r in rows]

    return []


async def add_dispatch_host(
    db: Any,
    user_id: str,
    label: str,
    url: str,
    api_key: str,
    capability_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Add a new dispatch host for a user.

    Args:
        db: Database pool.
        user_id: Owner's user ID.
        label: Human-readable label for the host.
        url: Base URL of the dispatch host.
        api_key: API key for Bearer authentication against the host.
        capability_labels: Operator-set capability labels (e.g.
            'camera-data', 'tauri-linux'). Normalized (lowercase, stripped,
            deduped) on write. Never self-reported by the host.

    Returns:
        Dict with keys: id, user_id, label, url, api_key, capability_labels
        (decoded to list[str]), created_at, updated_at.

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
            "(id, user_id, label, url, api_key, capability_labels,"
            " created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            host_id,
            user_id,
            label,
            url,
            api_key,
            encode_json_list(normalize_labels(capability_labels or [])),
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
    return _decode_host_row(dict(row))


async def update_dispatch_host(
    db: Any, user_id: str, host_id: str, capability_labels: list[str]
) -> dict[str, Any] | None:
    """Replace a dispatch host's capability labels (operator-set, edit-only).

    Args:
        db: Database pool.
        user_id: Owner's user ID.
        host_id: ID of the dispatch host to update.
        capability_labels: The full replacement label list (empty list
            clears all labels). Normalized (lowercase, stripped, deduped)
            on write.

    Returns:
        The updated row (decoded), or None if the host doesn't exist or
        isn't owned by user_id.
    """
    from datetime import UTC, datetime

    existing = await db.fetchrow(
        "SELECT id FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    if existing is None:
        return None

    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE dispatch_hosts SET capability_labels = $1, updated_at = $2 "
        "WHERE id = $3 AND user_id = $4",
        encode_json_list(normalize_labels(capability_labels)),
        now,
        host_id,
        user_id,
    )
    row = await db.fetchrow("SELECT * FROM dispatch_hosts WHERE id = $1", host_id)
    assert row is not None  # noqa: S101
    return _decode_host_row(dict(row))


async def remove_dispatch_host(db: Any, user_id: str, host_id: str) -> str | None:
    """Remove a dispatch host owned by user_id.

    Returns:
        The URL of the deleted host on success, or None if not found.
    """
    # Check existence first (compatible with both asyncpg and SQLite)
    row = await db.fetchrow(
        "SELECT id, url FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    if row is None:
        return None
    await db.execute(
        "DELETE FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    return str(row["url"])


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
