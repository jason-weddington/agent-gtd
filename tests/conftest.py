"""Shared test fixtures for Agent GTD."""

import os
import tempfile

# The client config file (~/.config/agent-gtd/agent-gtd.env) wins over the
# environment, and mcp_backend resolves it at import time. Point it at a path
# that cannot exist BEFORE agent_gtd is imported, so a developer's real file
# never leaks into the suite (it did: tests went to HTTP mode with a live key).
_NO_CLIENT_CONFIG = os.path.join(tempfile.mkdtemp(), "absent-agent-gtd.env")
os.environ["AGENT_GTD_CONFIG"] = _NO_CLIENT_CONFIG

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from agent_gtd.database import init_db  # noqa: E402
from agent_gtd.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_client_config(monkeypatch):
    """Keep every test off the developer's real client config file.

    Tests that exercise the file set AGENT_GTD_CONFIG (or delete it and point
    XDG_CONFIG_HOME/HOME at tmp_path) themselves.
    """
    monkeypatch.setenv("AGENT_GTD_CONFIG", _NO_CLIENT_CONFIG)


@pytest.fixture(autouse=True)
def _clear_agent_name_env(monkeypatch):
    """Unset AGENT_GTD_AGENT_NAME for each test.

    Tests needing specific attribution call monkeypatch.setenv() to set
    it explicitly (e.g. test_comment_attribution_from_env_variable).
    """
    monkeypatch.delenv("AGENT_GTD_AGENT_NAME", raising=False)


@pytest.fixture(autouse=True)
async def _setup_db(monkeypatch):
    """Init a fresh in-memory SQLite database for each test."""
    import agent_gtd.database as db_mod
    from agent_gtd.services.settings_service import set_setting
    from agent_gtd.sqlite_pool import SqlitePool

    sqlite_pool = SqlitePool()
    monkeypatch.setattr(db_mod, "_pool", sqlite_pool)

    await init_db()

    # Seed an explicit global engine so resolve_engine never raises in tests that
    # don't specifically test the unset-global path.  Mirrors the prod
    # _migrate_engine_default_to_sonnet seed that runs at startup.
    await set_setting(sqlite_pool, "dispatch.engine", "claude-code-sonnet")

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
    """Register a test user bypassing the invite system."""
    from agent_gtd.auth import create_token, register_user

    user = await register_user("test@example.com", "testpass123")
    token = create_token(user.id)
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
