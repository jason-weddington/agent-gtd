"""Shared test fixtures for Agent GTD."""

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gtd.database import init_db
from agent_gtd.main import app


@pytest.fixture(autouse=True)
async def _setup_db(monkeypatch):
    """Init a fresh in-memory SQLite database for each test."""
    import agent_gtd.database as db_mod
    from agent_gtd.sqlite_pool import SqlitePool

    sqlite_pool = SqlitePool()
    monkeypatch.setattr(db_mod, "_pool", sqlite_pool)

    await init_db()

    yield

    await sqlite_pool.close()


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


@pytest.fixture
async def user_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    """Return the authenticated test user's ID."""
    res = await client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    return res.json()["id"]
