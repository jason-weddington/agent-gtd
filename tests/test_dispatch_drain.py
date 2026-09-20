"""Tests for the dispatch host drain column and its service functions.

Grounded in docs/host-drain.md: one nullable column on dispatch_hosts,
drain/undrain service functions, read-path guard, schema tripwires.
"""

import logging

import pytest

import agent_gtd.database as db_mod
from agent_gtd.database import LOCAL_USER_ID, get_db, init_db
from agent_gtd.services.settings_service import (
    add_dispatch_host,
    drain_dispatch_host,
    get_dispatch_hosts,
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


async def _add_host(
    db: object,
    label: str = "pironman01",
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
        "jason-precision",
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
    assert "pironman01" in msg
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
    assert "pironman01" in msg


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
