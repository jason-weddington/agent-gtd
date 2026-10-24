"""Tests for the dispatch host drain column and its service functions.

Grounded in docs/host-drain.md: one nullable column on dispatch_hosts,
drain/undrain service functions, read-path guard, schema tripwires.
"""

import logging

import pytest
from httpx import ASGITransport

import agent_gtd.database as db_mod
from agent_gtd.database import LOCAL_USER_ID, get_db, init_db
from agent_gtd.exceptions import NotFoundError, ValidationError
from agent_gtd.main import app
from agent_gtd.mcp_backend import HttpBackend, LocalBackend
from agent_gtd.services.settings_service import (
    add_dispatch_host as _service_add_dispatch_host,
)
from agent_gtd.services.settings_service import (
    clear_dispatch_host_drain,
    drain_dispatch_host,
    get_dispatch_hosts,
    resolve_dispatch_host,
    set_dispatch_host_drain,
    set_user_setting,
    undrain_dispatch_host,
    update_dispatch_host,
)

TRIPWIRE_MSG = (
    "drain_reason missing from dispatch_hosts: "
    "drain is inert and every host reads as not-drained"
)

DRAIN_ALTER = "ALTER TABLE dispatch_hosts ADD COLUMN drain_reason TEXT"

LEGACY_CREATE = """
    CREATE TABLE dispatch_hosts (
        id TEXT NOT NULL PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL,
        api_key TEXT NOT NULL,
        capability_labels TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (user_id, url)
    )
"""


async def add_dispatch_host(*args, **kwargs):
    """Service add_dispatch_host, defaulting to in-rotation (not drained)."""
    kwargs.setdefault("start_drained", False)
    return await _service_add_dispatch_host(*args, **kwargs)


async def _add_host(
    db: object,
    label: str = "host-a",
    url: str = "http://host:8100",
    api_key: str = "key-abc",
) -> dict:
    """Add a dispatch host for the local test user."""
    return await add_dispatch_host(db, LOCAL_USER_ID, label, url, api_key)


async def _drop_and_recreate_legacy(db: object) -> None:
    """Drop dispatch_hosts and re-create it WITHOUT drain_reason (plain CREATE)."""
    await db.execute("DROP TABLE dispatch_hosts")
    await db.execute(LEGACY_CREATE)


# ---------------------------------------------------------------------------
# SCHEMA — fresh DB
# ---------------------------------------------------------------------------


async def test_fresh_db_has_nullable_drain_reason():
    db = await get_db()
    cols = await db.fetch("PRAGMA table_info(dispatch_hosts)")
    drain = [r for r in cols if r["name"] == "drain_reason"]
    assert len(drain) == 1
    assert drain[0]["notnull"] == 0
    assert drain[0]["dflt_value"] is None

    host = await _add_host(db)
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw is not None
    assert raw["drain_reason"] is None


# ---------------------------------------------------------------------------
# SCHEMA — migrated DB (legacy table without the column)
# ---------------------------------------------------------------------------


async def test_migration_adds_drain_reason_to_legacy_table():
    db = await get_db()
    await _drop_and_recreate_legacy(db)

    cols = [r["name"] for r in await db.fetch("PRAGMA table_info(dispatch_hosts)")]
    assert "drain_reason" not in cols  # pre-init guard against a vacuous pass

    await db.execute(
        "INSERT INTO dispatch_hosts (id, user_id, label, url, api_key,"
        " capability_labels, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        "legacy-host-1",
        LOCAL_USER_ID,
        "host-d",
        "http://legacy:8100",
        "legacy-key",
        "[]",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
    )

    await init_db()  # must not raise

    cols = [r["name"] for r in await db.fetch("PRAGMA table_info(dispatch_hosts)")]
    assert "drain_reason" in cols
    row = await db.fetchrow(
        "SELECT drain_reason, api_key, capability_labels FROM dispatch_hosts"
        " WHERE id = $1",
        "legacy-host-1",
    )
    assert row is not None
    assert row["drain_reason"] is None
    assert row["api_key"] == "legacy-key"
    assert row["capability_labels"] == "[]"  # capability ALTER replayed fine


# ---------------------------------------------------------------------------
# SCHEMA — replay (double init_db)
# ---------------------------------------------------------------------------


async def test_replay_logs_suppressed_drain_alter_and_keeps_single_column(caplog):
    db = await get_db()
    with caplog.at_level(logging.WARNING, logger="agent_gtd.database"):
        await init_db()
        first = list(caplog.records)
        await init_db()
        second = [r for r in caplog.records if r not in first]

    for run_records in (first, second):
        suppressed = [
            r
            for r in run_records
            if r.getMessage().startswith("Migration suppressed (replay/SQLite no-op)")
            and DRAIN_ALTER in r.getMessage()
        ]
        assert suppressed, run_records

    cols = [r["name"] for r in await db.fetch("PRAGMA table_info(dispatch_hosts)")]
    assert cols.count("drain_reason") == 1


# ---------------------------------------------------------------------------
# SCHEMA — startup tripwire
# ---------------------------------------------------------------------------


async def test_init_db_tripwire_fires_error_when_column_missing(monkeypatch, caplog):
    db = await get_db()

    # Companion: the normal fixture path emits no such ERROR record.
    with caplog.at_level(logging.ERROR, logger="agent_gtd.database"):
        await init_db()
    assert not [r for r in caplog.records if TRIPWIRE_MSG in r.getMessage()]

    await _drop_and_recreate_legacy(db)
    monkeypatch.setattr(db_mod, "_MIGRATIONS", [])

    with caplog.at_level(logging.ERROR, logger="agent_gtd.database"):
        await init_db()  # must not raise

    errors = [
        r
        for r in caplog.records
        if r.levelname == "ERROR" and r.name == "agent_gtd.database"
    ]
    assert len(errors) == 1
    assert errors[0].getMessage() == TRIPWIRE_MSG


# ---------------------------------------------------------------------------
# DRAIN semantics
# ---------------------------------------------------------------------------


async def test_drain_stores_reason():
    db = await get_db()
    host = await _add_host(db)
    row = await drain_dispatch_host(
        db, LOCAL_USER_ID, host["id"], "rolling deploy 2.0.2"
    )
    assert row is not None
    assert row["drain_reason"] == "rolling deploy 2.0.2"
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] == "rolling deploy 2.0.2"


async def test_drain_strips_whitespace_reason():
    db = await get_db()
    host = await _add_host(db)
    row = await drain_dispatch_host(
        db, LOCAL_USER_ID, host["id"], "  rolling deploy 2.0.2  "
    )
    assert row is not None
    assert row["drain_reason"] == "rolling deploy 2.0.2"


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_drain_requires_reason_when_not_drained(reason):
    db = await get_db()
    host = await _add_host(db)
    with pytest.raises(ValueError, match=host["id"]):
        await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], reason)


async def test_drain_unknown_host_returns_none_even_without_reason():
    db = await get_db()
    assert await drain_dispatch_host(db, LOCAL_USER_ID, "no-such-host", None) is None


async def test_drain_wrong_owner_returns_none():
    db = await get_db()
    host = await _add_host(db)
    assert await drain_dispatch_host(db, "someone-else", host["id"], "reason") is None


async def test_drain_already_drained_blank_reason_keeps_existing():
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "first reason")
    before = await db.fetchrow(
        "SELECT drain_reason, updated_at FROM dispatch_hosts WHERE id = $1",
        host["id"],
    )
    import asyncio

    await asyncio.sleep(0.01)
    for reason in (None, "", "   "):
        row = await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], reason)
        assert row is not None
        assert row["drain_reason"] == "first reason"
    after = await db.fetchrow(
        "SELECT drain_reason, updated_at FROM dispatch_hosts WHERE id = $1",
        host["id"],
    )
    assert after["drain_reason"] == "first reason"
    assert after["updated_at"] == before["updated_at"]  # no bump


async def test_drain_already_drained_with_reason_replaces():
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "old reason")
    before = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    import asyncio

    await asyncio.sleep(0.01)
    row = await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "new reason")
    assert row is not None
    assert row["drain_reason"] == "new reason"
    after = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert after["updated_at"] != before["updated_at"]  # bumped


async def test_drain_never_writes_empty_string():
    db = await get_db()
    host = await _add_host(db)
    for reason in (None, "", "   "):
        with pytest.raises(ValueError, match=host["id"]):
            await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], reason)
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] is None


# ---------------------------------------------------------------------------
# UNDRAIN semantics
# ---------------------------------------------------------------------------


async def test_undrain_clears_reason():
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "deploy 2.0.2")
    row = await undrain_dispatch_host(db, LOCAL_USER_ID, host["id"])
    assert row is not None
    assert row["drain_reason"] is None
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] is None


async def test_undrain_unknown_host_returns_none():
    db = await get_db()
    assert await undrain_dispatch_host(db, LOCAL_USER_ID, "no-such-host") is None


async def test_undrain_wrong_owner_returns_none():
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "deploy")
    assert await undrain_dispatch_host(db, "someone-else", host["id"]) is None
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] == "deploy"


async def test_undrain_is_idempotent():
    db = await get_db()
    host = await _add_host(db)
    first = await undrain_dispatch_host(db, LOCAL_USER_ID, host["id"])
    assert first is not None
    assert first["drain_reason"] is None
    second = await undrain_dispatch_host(db, LOCAL_USER_ID, host["id"])
    assert second is not None
    assert second["drain_reason"] is None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


async def test_drain_logs(caplog):
    db = await get_db()
    host = await _add_host(db, api_key="key-abc")
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "rolling deploy 2.0.2")
    records = [
        r
        for r in caplog.records
        if r.getMessage().startswith("Drained dispatch host id=")
    ]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "rolling deploy 2.0.2" in msg
    assert host["id"] in msg
    assert "host-a" in msg
    assert "key-abc" not in caplog.text  # api_key is never logged


async def test_drain_keep_logs_kept_reason(caplog):
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "existing reason")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], None)
    kept = [r for r in caplog.records if "kept" in r.getMessage()]
    assert len(kept) == 1
    assert "existing reason" in kept[0].getMessage()


async def test_drain_replace_logs_old_and_new_reason(caplog):
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "old reason")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "new reason")
    replaced = [r for r in caplog.records if "old reason" in r.getMessage()]
    assert len(replaced) == 1
    assert "new reason" in replaced[0].getMessage()


async def test_undrain_logs_prior_reason(caplog):
    db = await get_db()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], "prior reason")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await undrain_dispatch_host(db, LOCAL_USER_ID, host["id"])
    records = [
        r
        for r in caplog.records
        if r.getMessage().startswith("Undrained dispatch host id=")
    ]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "prior reason" in msg
    assert "host-a" in msg


# ---------------------------------------------------------------------------
# READ PATH
# ---------------------------------------------------------------------------


async def test_read_path_guard():
    db = await get_db()
    a = await _add_host(db, label="alpha", url="http://a:8100", api_key="key-a")
    b = await _add_host(db, label="beta", url="http://b:8100", api_key="key-b")

    def by_id(hosts):
        return {h["id"]: h for h in hosts}

    # Never-drained host reads as not-drained, key intact.
    hosts = by_id(await get_dispatch_hosts(db, LOCAL_USER_ID))
    assert hosts[a["id"]]["drain_reason"] is None
    assert hosts[a["id"]]["api_key"] == "key-a"

    # Drained host keeps its reason AND its api_key (reconciliation auth).
    await drain_dispatch_host(db, LOCAL_USER_ID, a["id"], "rolling deploy 2.0.2")
    hosts = by_id(await get_dispatch_hosts(db, LOCAL_USER_ID))
    assert hosts[a["id"]]["drain_reason"] == "rolling deploy 2.0.2"
    assert hosts[a["id"]]["api_key"] == "key-a"

    # Undrained again.
    await undrain_dispatch_host(db, LOCAL_USER_ID, a["id"])
    hosts = by_id(await get_dispatch_hosts(db, LOCAL_USER_ID))
    assert hosts[a["id"]]["drain_reason"] is None
    assert hosts[a["id"]]["api_key"] == "key-a"

    # A label edit does not clobber a drain.
    await drain_dispatch_host(db, LOCAL_USER_ID, b["id"], "hold for 2.0.3")
    await update_dispatch_host(db, LOCAL_USER_ID, b["id"], ["camera-data"])
    hosts = by_id(await get_dispatch_hosts(db, LOCAL_USER_ID))
    assert hosts[b["id"]]["drain_reason"] == "hold for 2.0.3"
    assert hosts[b["id"]]["capability_labels"] == ["camera-data"]


async def test_get_dispatch_hosts_empty_drain_reason_warns(caplog):
    db = await get_db()
    host = await _add_host(db)
    await db.execute(
        "UPDATE dispatch_hosts SET drain_reason = '' WHERE id = $1", host["id"]
    )
    with caplog.at_level(logging.WARNING, logger="agent_gtd.services.settings_service"):
        hosts = await get_dispatch_hosts(db, LOCAL_USER_ID)
    warned = [
        r
        for r in caplog.records
        if host["id"] in r.getMessage() and "empty drain_reason" in r.getMessage()
    ]
    assert len(warned) == 1
    assert warned[0].levelno == logging.WARNING
    row = next(h for h in hosts if h["id"] == host["id"])
    assert row["drain_reason"] == ""


async def test_lazy_migration_refetch_includes_drain_reason():
    db = await get_db()
    await set_user_setting(db, LOCAL_USER_ID, "dispatch.service_url", "http://l:8001")
    await set_user_setting(db, LOCAL_USER_ID, "dispatch.service_api_key", "legacy-key")
    hosts = await get_dispatch_hosts(db, LOCAL_USER_ID)
    assert len(hosts) == 1
    assert hosts[0]["drain_reason"] is None
    assert hosts[0]["api_key"] == "legacy-key"


# ---------------------------------------------------------------------------
# RESOLVER — resolve_dispatch_host (id → unique label → unique url substring)
# ---------------------------------------------------------------------------


async def _add_two_hosts(db: object) -> tuple[dict, dict]:
    """Add the canonical two-host fleet: host-a + host-d."""
    first = await _add_host(
        db,
        label="host-a",
        url="http://host-a.local:8100",
        api_key="key-1",
    )
    second = await add_dispatch_host(
        db,
        LOCAL_USER_ID,
        "host-d",
        "http://host-d.local:8100",
        "key-2",
    )
    return first, second


async def _add_other_user() -> str:
    """Register a second user and return its id (dispatch_hosts FKs users)."""
    from agent_gtd.auth import register_user

    user = await register_user("other-owner@example.com", "testpass123")
    return user.id


async def test_resolve_by_exact_id():
    db = await get_db()
    host, _ = await _add_two_hosts(db)
    resolved, resolved_by = await resolve_dispatch_host(db, LOCAL_USER_ID, host["id"])
    assert resolved["id"] == host["id"]
    assert resolved_by == "id"


async def test_resolve_id_beats_label():
    db = await get_db()
    host_a, _ = await _add_two_hosts(db)
    # host_b's label is the string equal to host_a's id — id must win.
    await add_dispatch_host(db, LOCAL_USER_ID, host_a["id"], "http://x:8100", "key-3")
    resolved, resolved_by = await resolve_dispatch_host(db, LOCAL_USER_ID, host_a["id"])
    assert resolved["id"] == host_a["id"]
    assert resolved_by == "id"


async def test_resolve_by_unique_label():
    db = await get_db()
    first, _ = await _add_two_hosts(db)
    resolved, resolved_by = await resolve_dispatch_host(db, LOCAL_USER_ID, "host-a")
    assert resolved["id"] == first["id"]
    assert resolved_by == "label"


async def test_resolve_by_unique_url_substring():
    db = await get_db()
    first, _ = await _add_two_hosts(db)
    resolved, resolved_by = await resolve_dispatch_host(
        db, LOCAL_USER_ID, "host-a.local"
    )
    assert resolved["id"] == first["id"]
    assert resolved_by == "url-substring"


async def test_resolve_ambiguous_label_pinned_detail():
    db = await get_db()
    a = await add_dispatch_host(db, LOCAL_USER_ID, "edge", "http://edge-a:8100", "k1")
    b = await add_dispatch_host(db, LOCAL_USER_ID, "edge", "http://edge-b:8100", "k2")
    with pytest.raises(ValidationError) as exc_info:
        await resolve_dispatch_host(db, LOCAL_USER_ID, "edge")
    detail = str(exc_info.value.detail)
    assert detail.startswith("Multiple dispatch hosts match 'edge':")
    assert f"label=edge id={a['id']} url=http://edge-a:8100" in detail
    assert f"label=edge id={b['id']} url=http://edge-b:8100" in detail
    # Candidates are joined with '; ' and ordered created_at ASC.
    assert detail.index(a["id"]) < detail.index(b["id"])
    assert "; " in detail


async def test_resolve_ambiguous_url_substring():
    db = await get_db()
    await add_dispatch_host(db, LOCAL_USER_ID, "one", "http://edge-a:8100", "k1")
    await add_dispatch_host(db, LOCAL_USER_ID, "two", "http://edge-b:8100", "k2")
    with pytest.raises(ValidationError) as exc_info:
        await resolve_dispatch_host(db, LOCAL_USER_ID, "edge-")
    assert "Multiple dispatch hosts match 'edge-':" in str(exc_info.value.detail)


async def test_resolve_unknown_ref_raises_not_found():
    db = await get_db()
    await _add_two_hosts(db)
    with pytest.raises(NotFoundError):
        await resolve_dispatch_host(db, LOCAL_USER_ID, "no-such-host")


async def test_resolve_owner_scoping():
    db = await get_db()
    other_id = await _add_other_user()
    await add_dispatch_host(db, other_id, "host-a", "http://p:8100", "k9")
    with pytest.raises(NotFoundError):
        await resolve_dispatch_host(db, LOCAL_USER_ID, "host-a")


# ---------------------------------------------------------------------------
# SET / CLEAR — set_dispatch_host_drain, clear_dispatch_host_drain
# ---------------------------------------------------------------------------


async def test_set_drain_by_label_stores_stripped_reason():
    db = await get_db()
    host = await _add_host(db)
    row = await set_dispatch_host_drain(
        db, LOCAL_USER_ID, "host-a", "  rolling deploy 2.0.2  "
    )
    assert row["id"] == host["id"]
    assert row["drain_reason"] == "rolling deploy 2.0.2"
    assert row["api_key"] == "key-abc"  # reconciliation read path stays intact
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] == "rolling deploy 2.0.2"


async def test_set_drain_missing_reason_on_not_drained_raises_validation():
    db = await get_db()
    host = await _add_host(db)
    for reason in (None, "", "   "):
        with pytest.raises(ValidationError, match="--reason"):
            await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", reason)
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert raw["drain_reason"] is None


async def test_set_drain_noop_on_already_drained_keeps_reason():
    db = await get_db()
    host = await _add_host(db)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "first reason")
    before = await db.fetchrow(
        "SELECT drain_reason, updated_at FROM dispatch_hosts WHERE id = $1",
        host["id"],
    )
    for reason in (None, "", "   "):
        row = await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", reason)
        assert row["drain_reason"] == "first reason"
    after = await db.fetchrow(
        "SELECT drain_reason, updated_at FROM dispatch_hosts WHERE id = $1",
        host["id"],
    )
    assert after["drain_reason"] == "first reason"
    assert after["updated_at"] == before["updated_at"]  # no bump on no-op


async def test_set_drain_overwrites_existing_reason():
    db = await get_db()
    await _add_host(db)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "old reason")
    row = await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "new reason")
    assert row["drain_reason"] == "new reason"
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", row["id"]
    )
    assert raw["drain_reason"] == "new reason"


async def test_set_drain_sets_updated_at_on_write():
    db = await get_db()
    host = await _add_host(db)
    before = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    import asyncio

    await asyncio.sleep(0.01)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    after = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert after["updated_at"] != before["updated_at"]


async def test_set_drain_wrong_owner_raises_not_found():
    db = await get_db()
    other = await _add_other_user()
    await add_dispatch_host(db, other, "host-a", "http://p:8100", "k")
    with pytest.raises(NotFoundError):
        await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")


async def test_clear_drain_returns_null_reason():
    db = await get_db()
    await _add_host(db)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    row = await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")
    assert row["drain_reason"] is None
    raw = await db.fetchrow(
        "SELECT drain_reason FROM dispatch_hosts WHERE id = $1", row["id"]
    )
    assert raw["drain_reason"] is None


async def test_clear_drain_never_drained_is_noop():
    db = await get_db()
    host = await _add_host(db)
    row = await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")
    assert row["id"] == host["id"]
    assert row["drain_reason"] is None


async def test_clear_drain_noop_leaves_updated_at_byte_identical():
    db = await get_db()
    host = await _add_host(db)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")
    before = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    row = await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")
    assert row["drain_reason"] is None
    after = await db.fetchrow(
        "SELECT updated_at FROM dispatch_hosts WHERE id = $1", host["id"]
    )
    assert after["updated_at"] == before["updated_at"]  # byte-identical no-op


async def test_clear_drain_wrong_owner_raises_not_found():
    db = await get_db()
    other = await _add_other_user()
    await add_dispatch_host(db, other, "host-a", "http://p:8100", "k")
    with pytest.raises(NotFoundError):
        await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")


# ---------------------------------------------------------------------------
# INSTRUMENTATION — caplog on resolve_by, INFO/WARNING branches, tripwire
# ---------------------------------------------------------------------------


def _drain_records(caplog, levelno: int | None = None) -> list:
    """Filter caplog records for the ref-resolved drain log records."""
    return [
        r
        for r in caplog.records
        if r.getMessage().startswith("Dispatch host drain")
        and (levelno is None or r.levelno == levelno)
    ]


def _undrain_records(caplog, levelno: int | None = None) -> list:
    return [
        r
        for r in caplog.records
        if r.getMessage().startswith("Dispatch host undrain")
        and (levelno is None or r.levelno == levelno)
    ]


async def test_set_drain_logs_resolved_by_label(caplog):
    db = await get_db()
    await _add_host(db)
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    records = list(_drain_records(caplog, logging.INFO))
    assert len(records) == 1
    rec = records[0]
    assert rec.resolved_by == "label"
    assert rec.host_ref == "host-a"  # exactly as supplied, un-resolved
    assert rec.user_id == LOCAL_USER_ID
    assert rec.host_id
    assert rec.label == "host-a"
    assert rec.previous_drain_reason is None
    assert rec.new_drain_reason == "deploy"


async def test_set_drain_logs_resolved_by_url_substring(caplog):
    db = await get_db()
    await _add_host(db, url="http://host-a.local:8100")
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a.local", "  deploy  ")
    records = list(_drain_records(caplog, logging.INFO))
    assert len(records) == 1
    rec = records[0]
    assert rec.resolved_by == "url-substring"
    assert rec.new_drain_reason == "deploy"  # stripped


async def test_set_drain_noop_logs_warning(caplog):
    db = await get_db()
    await _add_host(db)
    await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", None)
    warned = _drain_records(caplog, logging.WARNING)
    assert len(warned) == 1
    rec = warned[0]
    assert rec.resolved_by == "label"
    assert rec.previous_drain_reason == "deploy"
    assert rec.new_drain_reason == "deploy"


async def test_clear_drain_noop_logs_warning(caplog):
    db = await get_db()
    await _add_host(db)
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        await clear_dispatch_host_drain(db, LOCAL_USER_ID, "host-a")
    warned = _undrain_records(caplog, logging.WARNING)
    assert len(warned) == 1
    rec = warned[0]
    assert rec.resolved_by == "label"
    assert rec.new_drain_reason is None


async def test_set_drain_tripwire_warns_when_readback_differs(monkeypatch, caplog):
    db = await get_db()
    await _add_host(db)

    async def _hosts_without_drain(db_arg: object, user_id: str) -> list[dict]:
        hosts = await get_dispatch_hosts(db_arg, user_id)
        return [{k: v for k, v in h.items() if k != "drain_reason"} for h in hosts]

    monkeypatch.setattr(
        "agent_gtd.services.settings_service.get_dispatch_hosts",
        _hosts_without_drain,
    )
    with caplog.at_level(logging.INFO, logger="agent_gtd.services.settings_service"):
        row = await set_dispatch_host_drain(db, LOCAL_USER_ID, "host-a", "deploy")
    tripwire = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "read-back" in r.getMessage()
    ]
    assert len(tripwire) == 1
    assert row["drain_reason"] == "deploy"  # still returns the written host dict


# ---------------------------------------------------------------------------
# REST — POST /api/settings/dispatch/hosts/drain and /undrain
# ---------------------------------------------------------------------------

REASON = "rolling deploy 2.0.2"


async def _seed_rest_host(client, auth_headers, user_id) -> dict:
    db = await get_db()
    return await add_dispatch_host(
        db, user_id, "host-a", "http://host-a.local:8100", "key-abc"
    )


async def test_rest_drain_happy_path(client, auth_headers, user_id):
    host = await _seed_rest_host(client, auth_headers, user_id)
    resp = await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "host-a", "reason": REASON},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["drain_reason"] == REASON
    assert data["id"] == host["id"]


async def test_rest_drain_unknown_ref_404(client, auth_headers, user_id):
    await _seed_rest_host(client, auth_headers, user_id)
    resp = await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "no-such-host", "reason": REASON},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "no-such-host" in resp.json()["detail"]


async def test_rest_drain_ambiguous_ref_422(client, auth_headers, user_id):
    await _seed_rest_host(client, auth_headers, user_id)
    db = await get_db()
    await add_dispatch_host(db, user_id, "host-a", "http://dup:8100", "k2")
    resp = await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "host-a", "reason": REASON},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "Multiple dispatch hosts match" in resp.json()["detail"]


async def test_rest_drain_without_reason_on_not_drained_422(
    client, auth_headers, user_id
):
    await _seed_rest_host(client, auth_headers, user_id)
    resp = await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "host-a"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "--reason" in resp.json()["detail"]
    listing = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    assert listing.json()[0]["drain_reason"] is None


async def test_rest_drain_without_reason_on_drained_keeps_reason(
    client, auth_headers, user_id
):
    await _seed_rest_host(client, auth_headers, user_id)
    db = await get_db()
    await set_dispatch_host_drain(db, user_id, "host-a", REASON)
    resp = await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "host-a"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["drain_reason"] == REASON


async def test_rest_drain_then_undrain_then_list(client, auth_headers, user_id):
    await _seed_rest_host(client, auth_headers, user_id)
    await client.post(
        "/api/settings/dispatch/hosts/drain",
        json={"host": "host-a", "reason": REASON},
        headers=auth_headers,
    )
    resp = await client.post(
        "/api/settings/dispatch/hosts/undrain",
        json={"host": "host-a"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["drain_reason"] is None
    listing = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    hosts = listing.json()
    assert len(hosts) == 1
    assert hosts[0]["drain_reason"] is None
    assert hosts[0]["api_key_preview"].startswith("****")
    assert "api_key" not in hosts[0]


async def test_rest_undrain_non_drained_is_200(client, auth_headers, user_id):
    await _seed_rest_host(client, auth_headers, user_id)
    resp = await client.post(
        "/api/settings/dispatch/hosts/undrain",
        json={"host": "host-a"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["drain_reason"] is None


async def test_rest_undrain_unknown_ref_404(client, auth_headers, user_id):
    await _seed_rest_host(client, auth_headers, user_id)
    resp = await client.post(
        "/api/settings/dispatch/hosts/undrain",
        json={"host": "no-such-host"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_rest_list_does_not_filter_drained_and_carries_reason(
    client, auth_headers, user_id
):
    """GET /hosts returns EVERY host — drained or not — with drain_reason."""
    await _seed_rest_host(client, auth_headers, user_id)
    db = await get_db()
    await add_dispatch_host(db, user_id, "host-d", "http://j:8100", "k2")
    await set_dispatch_host_drain(db, user_id, "host-a", REASON)
    resp = await client.get("/api/settings/dispatch/hosts", headers=auth_headers)
    hosts = resp.json()
    assert len(hosts) == 2  # drained host is NOT filtered out
    by_label = {h["label"]: h for h in hosts}
    assert by_label["host-a"]["drain_reason"] == REASON
    assert by_label["host-d"]["drain_reason"] is None


# ---------------------------------------------------------------------------
# PEER VISIBILITY — backend projections and drain/undrain methods
# ---------------------------------------------------------------------------


async def test_local_backend_list_carries_drain_reason():
    db = await get_db()
    backend = LocalBackend()
    host = await _add_host(db)
    await drain_dispatch_host(db, LOCAL_USER_ID, host["id"], REASON)
    hosts = await backend.list_dispatch_hosts(LOCAL_USER_ID)
    assert len(hosts) == 1
    returned = hosts[0]
    assert returned["drain_reason"] == REASON
    assert set(returned.keys()) == {
        "id",
        "label",
        "url",
        "capability_labels",
        "drain_reason",
    }


async def test_local_backend_drain_returns_secret_free_dict():
    db = await get_db()
    await _add_host(db)
    backend = LocalBackend()
    result = await backend.drain_dispatch_host(
        LOCAL_USER_ID, "host-a", "rolling deploy 2.0.2"
    )
    assert result["drain_reason"] == "rolling deploy 2.0.2"
    assert set(result.keys()) == {
        "id",
        "label",
        "url",
        "capability_labels",
        "drain_reason",
    }
    assert "api_key" not in result
    assert "api_key_preview" not in result


async def test_local_backend_undrain_returns_secret_free_dict():
    db = await get_db()
    await _add_host(db)
    backend = LocalBackend()
    await backend.drain_dispatch_host(LOCAL_USER_ID, "host-a", "deploy")
    result = await backend.undrain_dispatch_host(LOCAL_USER_ID, "host-a")
    assert result["drain_reason"] is None
    assert set(result.keys()) == {
        "id",
        "label",
        "url",
        "capability_labels",
        "drain_reason",
    }


# ---------------------------------------------------------------------------
# HTTP-MODE HttpBackend roundtrip (the only end-to-end HttpBackend drain test)
# ---------------------------------------------------------------------------


@pytest.fixture
async def drain_http_backend():
    """HttpBackend wired to the FastAPI app via ASGI transport, logged in.

    Yields ``(backend, user_id)`` — ``HttpBackend.login`` does not retain the
    user id, so the fixture surfaces it alongside the logged-in backend.
    """
    from agent_gtd.auth import create_token, register_user

    transport = ASGITransport(app=app)
    be = HttpBackend(base_url="http://test")
    be._client = be._client.__class__(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    )
    user = await register_user("drain@example.com", "testpass123")
    token = create_token(user.id)
    resp = await be._client.post(
        "/api/auth/api-keys",
        json={"name": "drain-test-key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await be.login(resp.json()["api_key"], "drain-test-agent")
    yield be, user.id
    await be.close()


async def test_http_backend_drain_undrain_roundtrip(drain_http_backend):
    from agent_gtd.database import get_db as _get_db

    backend, user_id = drain_http_backend
    db = await _get_db()
    await add_dispatch_host(
        db, user_id, "host-a", "http://host-a.local:8100", "super-secret-key"
    )
    drained = await backend.drain_dispatch_host(user_id, "host-a", REASON)
    assert drained["drain_reason"] == REASON
    assert set(drained.keys()) == {
        "id",
        "label",
        "url",
        "capability_labels",
        "drain_reason",
    }
    assert "api_key" not in drained
    assert "api_key_preview" not in drained

    # The drained host is NOT filtered out of the list projection.
    while_drained = await backend.list_dispatch_hosts(user_id)
    entry = next(h for h in while_drained if h["label"] == "host-a")
    assert entry["drain_reason"] == REASON

    undrained = await backend.undrain_dispatch_host(user_id, "host-a")
    assert undrained["drain_reason"] is None
    assert set(undrained.keys()) == {
        "id",
        "label",
        "url",
        "capability_labels",
        "drain_reason",
    }


async def test_http_backend_drain_missing_reason_propagates_detail(
    drain_http_backend,
):
    from agent_gtd.database import get_db as _get_db

    backend, user_id = drain_http_backend
    db = await _get_db()
    await add_dispatch_host(db, user_id, "host-a", "http://host-a.local:8100", "k")
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="--reason"):
        await backend.drain_dispatch_host(user_id, "host-a", None)
