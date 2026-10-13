"""Settings service: app-level and per-user key-value stores."""

# TODO: encrypt dispatch.service_api_key at rest (not implemented; we trust our own DB)

import logging
import os
from datetime import UTC, datetime
from typing import Any

from agent_gtd.database import decode_json_list, encode_json_list, normalize_labels
from agent_gtd.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


def _decode_host_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decode a dispatch_hosts row's capability_labels from JSON text in-place."""
    raw = row.get("capability_labels")
    row["capability_labels"] = (
        raw if isinstance(raw, list) else (decode_json_list(str(raw)) if raw else [])
    )
    return row


def _warn_on_out_of_band_empty_drain(row: dict[str, Any]) -> dict[str, Any]:
    """Warn when a read host carries an empty drain_reason.

    The service layer refuses to write an empty drain_reason (drained-but-
    says-nothing), so '' can only arrive via direct-to-DB edits. Any
    non-NULL still means drained (fails closed); return the row unchanged.
    """
    if row.get("drain_reason") == "":
        logger.warning(
            "dispatch host %s has empty drain_reason written outside the "
            "service layer; treating as drained with no explanation",
            row["id"],
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
        (decoded to list[str]), drain_reason (str | None — NULL/None means
        accepting work, any non-NULL string means out of rotation).
    """
    import uuid
    from datetime import UTC, datetime

    rows = await db.fetch(
        "SELECT id, url, api_key, label, capability_labels, drain_reason, "
        "created_at FROM dispatch_hosts WHERE user_id = $1 ORDER BY created_at ASC",
        user_id,
    )
    if rows:
        return [
            _warn_on_out_of_band_empty_drain(_decode_host_row(dict(r))) for r in rows
        ]

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
            "SELECT id, url, api_key, label, capability_labels, drain_reason, "
            "created_at FROM dispatch_hosts WHERE user_id = $1 ORDER BY created_at ASC",
            user_id,
        )
        return [
            _warn_on_out_of_band_empty_drain(_decode_host_row(dict(r))) for r in rows
        ]

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


async def drain_dispatch_host(
    db: Any, user_id: str, host_id: str, reason: str | None = None
) -> dict[str, Any] | None:
    """Take a dispatch host out of rotation (operator action).

    Args:
        db: Database pool.
        user_id: Owner's user ID.
        host_id: ID of the dispatch host to drain.
        reason: Why the host is out of rotation. MANDATORY unless the host
            is already drained — a non-NULL empty string must never be
            written (drained-but-says-nothing). Whitespace is stripped on
            write. When the host is already drained and no (or a blank)
            reason is given, the existing reason is kept untouched.

    Returns:
        The updated row (decoded), or None if the host doesn't exist or
        isn't owned by user_id.

    Raises:
        ValueError: If the host is not already drained and no non-blank
            reason was supplied.
    """
    from datetime import UTC, datetime

    # Owner-scoped existence check first, before any reason validation —
    # and it carries the current drain_reason so the branch needs no second
    # read.
    existing = await db.fetchrow(
        "SELECT id, drain_reason FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    if existing is None:
        return None

    current = existing["drain_reason"]
    trimmed = reason.strip() if isinstance(reason, str) else None

    if current is None:
        # Mandatory-reason rule applies only to hosts not already drained.
        if not trimmed:
            msg = (
                f"Dispatch host '{host_id}' is not drained: a reason is "
                "required to drain it"
            )
            raise ValueError(msg)
    elif not trimmed:
        # Already drained with no (or a blank) reason: keep the existing
        # reason unchanged — no UPDATE, no updated_at bump, no error.
        row = await db.fetchrow("SELECT * FROM dispatch_hosts WHERE id = $1", host_id)
        assert row is not None  # noqa: S101
        kept = _decode_host_row(dict(row))
        logger.info(
            "Drained dispatch host id=%s label=%s by user=%s kept existing reason=%r",
            host_id,
            row["label"],
            user_id,
            kept["drain_reason"],
        )
        return kept

    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE dispatch_hosts SET drain_reason = $1, updated_at = $2 "
        "WHERE id = $3 AND user_id = $4",
        trimmed,
        now,
        host_id,
        user_id,
    )
    row = await db.fetchrow("SELECT * FROM dispatch_hosts WHERE id = $1", host_id)
    assert row is not None  # noqa: S101
    result = _decode_host_row(dict(row))
    if current is None:
        logger.info(
            "Drained dispatch host id=%s label=%s by user=%s reason=%r",
            host_id,
            row["label"],
            user_id,
            result["drain_reason"],
        )
    else:
        logger.info(
            "Drained dispatch host id=%s label=%s by user=%s replaced "
            "reason=%r with reason=%r",
            host_id,
            row["label"],
            user_id,
            current,
            result["drain_reason"],
        )
    return result


async def undrain_dispatch_host(
    db: Any, user_id: str, host_id: str
) -> dict[str, Any] | None:
    """Return a drained dispatch host to rotation (clears drain_reason).

    Idempotent: undraining an already-undrained host returns its row and
    raises nothing.

    Returns:
        The updated row (decoded), or None if the host doesn't exist or
        isn't owned by user_id.
    """
    from datetime import UTC, datetime

    # Owner-scoped existence check first; also captures the prior reason
    # for the log record.
    existing = await db.fetchrow(
        "SELECT id, drain_reason FROM dispatch_hosts WHERE id = $1 AND user_id = $2",
        host_id,
        user_id,
    )
    if existing is None:
        return None

    prior = existing["drain_reason"]
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE dispatch_hosts SET drain_reason = NULL, updated_at = $1 "
        "WHERE id = $2 AND user_id = $3",
        now,
        host_id,
        user_id,
    )
    row = await db.fetchrow("SELECT * FROM dispatch_hosts WHERE id = $1", host_id)
    assert row is not None  # noqa: S101
    result = _decode_host_row(dict(row))
    logger.info(
        "Undrained dispatch host id=%s label=%s by user=%s prior_reason=%r",
        host_id,
        row["label"],
        user_id,
        prior,
    )
    return result


async def resolve_dispatch_host(
    db: Any, user_id: str, host_ref: str
) -> tuple[dict[str, Any], str]:
    """Resolve a host reference (id, label, or URL substring) to a host row.

    Operators think in labels (``host-a``), the registry thinks in UUIDs.
    Resolution order, each step scoped to the caller's own hosts in
    ``created_at`` ASC order (the order :func:`get_dispatch_hosts` returns):

    1. Exact case-sensitive equality on ``id``.
    2. Exact case-sensitive equality on ``label`` — only if exactly one host
       matches.
    3. Unique case-sensitive Python substring match via ``host_ref in url``.

    Args:
        db: Database pool.
        user_id: Owner's user ID (hosts owned by others are invisible).
        host_ref: The reference exactly as supplied — never resolved,
            never normalized.

    Returns:
        ``(host_dict, resolved_by)`` where ``resolved_by`` is one of the
        exact strings ``'id'``, ``'label'``, ``'url-substring'``.

    Raises:
        NotFoundError: If no host matches at any step.
        ValidationError: If a label or URL substring matches more than one
            host — the detail lists every candidate in created_at ASC order.
    """
    hosts = await get_dispatch_hosts(db, user_id)

    def _candidates(matches: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"label={h.get('label', '')} id={h['id']} url={h['url']}" for h in matches
        )

    # Step 1: exact id — always unambiguous by primary key, and beats label.
    for host in hosts:
        if host["id"] == host_ref:
            return host, "id"

    # Step 2: exact label, only when unique.
    label_matches = [h for h in hosts if h["label"] == host_ref]
    if len(label_matches) == 1:
        return label_matches[0], "label"
    if len(label_matches) > 1:
        raise ValidationError(
            f"Multiple dispatch hosts match '{host_ref}': {_candidates(label_matches)}"
        )

    # Step 3: unique URL substring.
    url_matches = [h for h in hosts if host_ref in h["url"]]
    if len(url_matches) == 1:
        return url_matches[0], "url-substring"
    if len(url_matches) > 1:
        raise ValidationError(
            f"Multiple dispatch hosts match '{host_ref}': {_candidates(url_matches)}"
        )

    raise NotFoundError("DispatchHost", host_ref)


async def set_dispatch_host_drain(
    db: Any, user_id: str, host_ref: str, reason: str | None = None
) -> dict[str, Any]:
    """Drain a dispatch host by reference (id, label, or URL substring).

    Thin reference-resolving wrapper over :func:`drain_dispatch_host` that
    adds the operator-facing logging (resolved_by, host_ref as supplied)
    and a write-time read-back tripwire: the drain_reason column must be
    declared in all three schema places, and a missed one fails silently
    because the router reads ``host.get("drain_reason")``. Re-fetching
    through the exact read path dispatch_worker consumes turns that silent
    misconfiguration into a loud one while the operator is watching.

    Returns:
        The full decoded host row (secret-trimming happens at the backend
        layer, never here).

    Raises:
        NotFoundError: If the reference resolves to no host owned by
            *user_id*.
        ValidationError: If the host is not drained and no non-blank reason
            was supplied (detail contains ``--reason``), or if the reference
            is ambiguous.
    """
    host, resolved_by = await resolve_dispatch_host(db, user_id, host_ref)
    previous = host.get("drain_reason")
    trimmed = reason.strip() if isinstance(reason, str) else None
    reason_present = bool(trimmed)

    if previous is None and not reason_present:
        raise ValidationError(
            f"Dispatch host '{host.get('label', '')}' ({host['id']}) is not "
            "drained: pass --reason to drain it"
        )

    no_op = previous is not None and not reason_present
    record = {
        "user_id": user_id,
        "host_ref": host_ref,
        "resolved_by": resolved_by,
        "host_id": host["id"],
        "label": host.get("label", ""),
        "previous_drain_reason": previous,
        "new_drain_reason": trimmed if reason_present else previous,
    }

    # The mandatory-reason branch is pre-validated above (as ValidationError),
    # so drain_dispatch_host cannot raise its ValueError here — all four
    # reason/state branches are already accounted for.
    result = await drain_dispatch_host(db, user_id, host["id"], reason)
    assert result is not None  # noqa: S101 — just resolved, must exist

    if no_op:
        # The most likely mistaken invocation — say so at WARNING.
        logger.warning(
            "Dispatch host drain no-op: already drained, existing reason kept",
            extra=record,
        )
    else:
        logger.info("Dispatch host drain applied by reference", extra=record)

    # Write-time tripwire: read back through the exact read path dispatch_worker
    # reconciliation consumes and compare against what we just wrote.
    written = result["drain_reason"]
    read_back = {h["id"]: h for h in await get_dispatch_hosts(db, user_id)}.get(
        host["id"], {}
    ).get("drain_reason")
    if read_back != written:
        logger.warning(
            "drain_reason read-back mismatch for host %s: wrote %r, read back %r "
            "— the column may be missing from the schema the reader sees",
            host["id"],
            written,
            read_back,
        )

    return result


async def clear_dispatch_host_drain(
    db: Any, user_id: str, host_ref: str
) -> dict[str, Any]:
    """Undrain a dispatch host by reference (id, label, or URL substring).

    Clears ``drain_reason`` when set; a no-op when the host is not drained
    (no ``updated_at`` bump, no error). Returns the full decoded host row.
    """
    host, resolved_by = await resolve_dispatch_host(db, user_id, host_ref)
    previous = host.get("drain_reason")
    record = {
        "user_id": user_id,
        "host_ref": host_ref,
        "resolved_by": resolved_by,
        "host_id": host["id"],
        "label": host.get("label", ""),
        "previous_drain_reason": previous,
        "new_drain_reason": None,
    }

    if previous is None:
        # The most likely mistaken invocation — already undrained.
        logger.warning("Dispatch host undrain no-op: host is not drained", extra=record)
        return host

    result = await undrain_dispatch_host(db, user_id, host["id"])
    logger.info("Dispatch host undrain applied by reference", extra=record)
    assert result is not None  # noqa: S101 — just resolved, must exist
    return result


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
