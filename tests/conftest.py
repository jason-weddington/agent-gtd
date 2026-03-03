"""Shared test fixtures for Agent GTD."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gtd.database import close_db, get_db, init_db
from agent_gtd.main import app


@pytest.fixture(autouse=True)
async def _setup_db(request, monkeypatch):
    """Init a fresh test database for each test.

    Skipped when SKIP_DB_TESTS=1 is set (useful for offline / slow-network work).
    """
    import agent_gtd.database as db_mod

    if os.environ.get("SKIP_DB_TESTS") == "1":
        # Skip any test that actually needs the DB (has async fixtures or
        # uses client/auth_headers/project_id). Pure sync tests survive.
        if request.node.get_closest_marker("asyncio") or _is_async_test(request):
            pytest.skip("SKIP_DB_TESTS=1")
        yield
        return

    # Point at the test database
    test_url = os.environ.get("AGENT_GTD_TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("AGENT_GTD_TEST_DATABASE_URL not set")

    monkeypatch.setenv("AGENT_GTD_DATABASE_URL", test_url)
    monkeypatch.setattr(db_mod, "_pool", None)

    await init_db()

    yield

    # Truncate all tables in dependency order.
    # The pool may already be closed (e.g. MCP lifespan teardown),
    # so reconnect if needed.
    pool = db_mod._pool
    if pool is None or pool._closed:
        db_mod._pool = None
        pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE events, notes, items, projects, users CASCADE")
    await close_db()


def _is_async_test(request) -> bool:
    """Check if the test function is a coroutine (async def)."""
    import asyncio

    return asyncio.iscoroutinefunction(request.node.obj)


@pytest.fixture
async def client():
    """Async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a test user and return auth headers."""
    res = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    """Create a test project and return its ID."""
    res = await client.post(
        "/api/projects",
        json={"name": "Test Project", "description": "A test project"},
        headers=auth_headers,
    )
    return res.json()["id"]
