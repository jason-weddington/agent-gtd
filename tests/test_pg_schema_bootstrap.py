"""PostgreSQL schema-bootstrap integration test.

Guarded by AGENT_GTD_TEST_DATABASE_URL so the default in-memory-SQLite
test environment is completely unaffected.  When the variable is set,
_SCHEMA_STATEMENTS is executed in full against a real PostgreSQL instance
inside an isolated temporary schema.

Why this matters
----------------
SQLite defers FK resolution, so a ``REFERENCES`` clause naming a table that
does not yet exist in _SCHEMA_STATEMENTS passes silently.  PostgreSQL
enforces FK ordering at DDL time and rejects the same statement.  This test
makes that class of bug fail in CI rather than on a user's first production
install.

Running locally::

    AGENT_GTD_TEST_DATABASE_URL=postgresql://user:pass@localhost/dbname \\
        uv run pytest tests/test_pg_schema_bootstrap.py -v
"""

import os
import uuid

import pytest

from agent_gtd.database import _SCHEMA_STATEMENTS

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGENT_GTD_TEST_DATABASE_URL"),
    reason=(
        "AGENT_GTD_TEST_DATABASE_URL not set — skipping PostgreSQL bootstrap tests; "
        "set it to a connectable DSN (e.g. 'postgresql://user:pass@host/dbname') "
        "to run this suite."
    ),
)

_DSN = os.environ.get("AGENT_GTD_TEST_DATABASE_URL", "")


async def test_schema_bootstraps_on_postgresql():
    """All _SCHEMA_STATEMENTS execute against a live PostgreSQL without error.

    A FK forward-reference bug — referencing a table that hasn't been
    created yet in the list — would raise asyncpg.PostgresError here and
    fail this test.  The same SQL passes silently on SQLite, so this test
    closes that coverage gap.

    This test would have failed before the FK ordering was fixed in
    _SCHEMA_STATEMENTS (fix: commit b55b228).
    """
    import asyncpg

    schema_name = f"test_bootstrap_{uuid.uuid4().hex}"
    conn: asyncpg.Connection = await asyncpg.connect(_DSN)
    try:
        await conn.execute(f'CREATE SCHEMA "{schema_name}"')
        await conn.execute(f'SET search_path TO "{schema_name}"')
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)
        # Reaching here means every DDL statement executed without error.
        # A schema with FK forward-references would have raised before this point.
    finally:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await conn.close()


async def test_postgresql_enforces_fk_creation_order():
    """PostgreSQL rejects a FK reference to a table that does not yet exist.

    This validates the test environment: if this assertion passes we know the
    engine enforces DDL creation order, and therefore that
    test_schema_bootstraps_on_postgresql would have caught the pre-fix FK
    forward-reference bug that the SQLite suite silently ignored.
    """
    import asyncpg

    schema_name = f"test_fk_order_{uuid.uuid4().hex}"
    conn: asyncpg.Connection = await asyncpg.connect(_DSN)
    try:
        await conn.execute(f'CREATE SCHEMA "{schema_name}"')
        await conn.execute(f'SET search_path TO "{schema_name}"')
        with pytest.raises(asyncpg.PostgresError):
            # "child_first" references "parent_not_yet_created" which does not
            # exist at this point.  PostgreSQL must reject this; SQLite would
            # silently accept it (deferred FK resolution).
            await conn.execute(
                "CREATE TABLE child_first ("
                "  id TEXT PRIMARY KEY,"
                "  parent_id TEXT NOT NULL REFERENCES parent_not_yet_created(id)"
                ")"
            )
    finally:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await conn.close()
