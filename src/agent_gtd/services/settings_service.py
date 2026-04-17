"""App-level settings service (key-value store backed by app_settings table)."""

from datetime import UTC, datetime
from typing import Any


async def get_setting(db: Any, key: str, default: str | None = None) -> str | None:
    """Retrieve a setting value by key.

    Returns *default* when the key has no stored value.
    """
    row = await db.fetchrow("SELECT value FROM app_settings WHERE key = $1", key)
    return str(row["value"]) if row else default


async def set_setting(db: Any, key: str, value: str) -> None:
    """Persist a setting value (upsert)."""
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
