"""Shared test fixtures for Agent GTD."""

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gtd.database import close_db, init_db
from agent_gtd.main import app


@pytest.fixture(autouse=True)
async def _setup_db(tmp_path, monkeypatch):
    """Init a fresh test database for each test."""
    import agent_gtd.database as db_mod

    monkeypatch.setattr(db_mod, "_DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_db", None)
    await init_db()
    yield
    await close_db()


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
