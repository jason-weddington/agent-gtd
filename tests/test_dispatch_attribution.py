"""Regression tests for shared-project dispatch attribution.

Covers the bug where a project member dispatching an item saw all agent
subprocess comments attributed as ``"human"`` instead of the correct
``"claude-<mode>-<run_id_short>"`` value.

Root cause: the ``or`` operator in ``comment_routes.py`` treated an explicitly
passed empty ``created_by=""`` as falsy, falling through to
``get_current_actor_attribution()`` (which returns ``"human"`` server-side).
Compound trigger: the login MCP tool did not guard against ``agent_name=""``
propagating into the session and then the comment body.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastmcp import Client
from httpx import ASGITransport, AsyncClient

from agent_gtd.auth import create_token, generate_api_key, hash_api_key, register_user
from agent_gtd.database import get_db
from agent_gtd.main import app
from agent_gtd.mcp_backend import HttpBackend, LocalBackend
from agent_gtd.mcp_server import _show_login, mcp
from agent_gtd.services import project_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_api_key(user_id: str) -> str:
    """Insert an API key for user_id; return the plaintext key."""
    db = await get_db()
    key = generate_api_key()
    h = hash_api_key(key)
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        str(uuid.uuid4()),
        user_id,
        h,
        "test-key",
        now,
    )
    return key


async def _add_member(project_id: str, user_id: str) -> None:
    """Add user_id as a project member (direct SQL, no invite)."""
    db = await get_db()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        user_id,
        datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner():
    """Project owner user."""
    return await register_user("owner@attrib-test.com", "password123")


@pytest.fixture
async def member():
    """Project member user (non-owner)."""
    return await register_user("member@attrib-test.com", "password123")


@pytest.fixture
async def shared_project(owner):
    """Project owned by owner, to be shared with member in individual tests."""
    db = await get_db()
    return await project_service.create_project(db, owner.id, name="Shared Project")


@pytest.fixture
async def shared_item(owner, shared_project):
    """An item in the shared project."""
    from agent_gtd.services import item_service

    db = await get_db()
    return await item_service.create_item(
        db, owner.id, title="Dispatch target", project_id=shared_project["id"]
    )


# ---------------------------------------------------------------------------
# HttpBackend fixture (wired to the ASGI test app)
# ---------------------------------------------------------------------------


@pytest.fixture
async def http_backend():
    """HttpBackend wired to the ASGI test app."""
    transport = ASGITransport(app=app)
    be = HttpBackend(base_url="http://test")
    be._client = be._client.__class__(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    )
    yield be
    await be.close()


# ---------------------------------------------------------------------------
# AC-3: Member dispatches → agent subprocess comment attributed correctly
#
# Simulates the agent subprocess posting a comment while
# AGENT_GTD_AGENT_NAME=claude-plan-abc12345 is set in the environment.
# Uses HttpBackend (the code path dispatched agents use in production).
# ---------------------------------------------------------------------------


async def test_member_dispatch_comment_attribution_via_http_backend(
    http_backend: HttpBackend,
    owner,
    member,
    shared_project,
    shared_item,
):
    """Agent subprocess (member) comment is attributed claude-plan-<id>, not human.

    This is the core AC-3 regression: a member's dispatch run must produce the
    correct created_by on all agent-subprocess MCP comments.
    """
    # Share the project with the member
    await _add_member(shared_project["id"], member.id)

    # Create an API key for the member (as the dispatch service would do)
    member_api_key = await _create_api_key(member.id)

    # Simulate the dispatch-service forwarding AGENT_GTD_AGENT_NAME to the subprocess
    agent_name = "claude-plan-abc12345"

    # Log in as member with the correct agent_name (as the subprocess does via env)
    await http_backend.login(member_api_key, agent_name)

    # Post a comment as the agent subprocess would
    result = await http_backend.create_comment(
        member.id,
        item_id=shared_item["id"],
        content_markdown="Planning...",
        created_by=agent_name,
    )

    assert result["created_by"] == agent_name, (
        f"Expected created_by={agent_name!r}, got {result['created_by']!r}. "
        "Member dispatch comment was not attributed correctly."
    )


async def test_owner_dispatch_comment_attribution_unchanged(
    http_backend: HttpBackend,
    owner,
    shared_project,
    shared_item,
):
    """AC-2: Owner's own dispatches still attribute correctly (no regression)."""
    owner_api_key = await _create_api_key(owner.id)
    agent_name = "claude-build-abc12345"

    await http_backend.login(owner_api_key, agent_name)

    result = await http_backend.create_comment(
        owner.id,
        item_id=shared_item["id"],
        content_markdown="Building...",
        created_by=agent_name,
    )

    assert result["created_by"] == agent_name


# ---------------------------------------------------------------------------
# AC-4: login MCP tool with empty agent_name must NOT produce session[""]
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _show_login, reason="login tool not registered")
async def test_login_with_empty_agent_name_falls_back_to_lead_attribution(
    monkeypatch,
):
    """Calling login with agent_name='' must not propagate empty string to session.

    This is the defensive fix: if the dispatch service or caller omits agent_name,
    the session must still carry a meaningful non-empty attribution rather than
    silently allowing created_by="" → server 'human' fallback.
    """
    import agent_gtd.database as db_mod
    import agent_gtd.mcp_server as srv

    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", "")
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: False)

    # Register a user and create an API key
    user = await register_user("empty-agent@test.com", "password123")
    api_key = await _create_api_key(user.id)

    async with Client(mcp) as c:
        result = await c.call_tool(
            "login",
            {"api_key": api_key, "agent_name": ""},
        )
        # The resolved agent_name in the response must be non-empty
        data = result.data if isinstance(result.data, dict) else {}
        resolved_name = data.get("agent_name", "")
        assert resolved_name, (
            "login with empty agent_name must produce non-empty agent_name via "
            "compute_lead_attribution fallback, got empty string"
        )
        assert resolved_name != "", "agent_name must not be empty string"
        # Must be the lead-style attribution, not empty
        assert resolved_name.startswith("claude-lead-"), (
            f"Expected claude-lead-<id>, got {resolved_name!r}"
        )


# ---------------------------------------------------------------------------
# Comment-route None-check: body.created_by=None falls back to server attr
# ---------------------------------------------------------------------------


async def test_comment_routes_none_created_by_falls_back_to_server_attribution(
    owner,
    shared_project,
    monkeypatch,
):
    """body.created_by=None → server-side get_current_actor_attribution() fallback.

    When created_by is absent from the request body (None after Pydantic default),
    the route must use get_current_actor_attribution(human_email=user.email).
    Without AGENT_GTD_AGENT_NAME set, that returns the authenticated user's email.
    """
    # Ensure env var is absent (conftest already does this, but be explicit)
    monkeypatch.delenv("AGENT_GTD_AGENT_NAME", raising=False)

    transport = ASGITransport(app=app)
    token = create_token(owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{shared_project['id']}/comments",
            json={"content_markdown": "No attribution provided"},
            headers=headers,
        )
    assert res.status_code == 201
    assert res.json()["created_by"] == owner.email


async def test_comment_routes_empty_string_created_by_preserved(
    owner,
    shared_project,
):
    """body.created_by='' is NOT treated as absent — the empty string passes through.

    After the None-check fix, explicitly passing created_by='' must not fall
    through to the 'human' fallback. The server stores whatever the client sends.
    """
    transport = ASGITransport(app=app)
    token = create_token(owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/projects/{shared_project['id']}/comments",
            json={"content_markdown": "Empty attribution", "created_by": ""},
            headers=headers,
        )
    assert res.status_code == 201
    # Empty string is preserved — the server does NOT override it with "human"
    assert res.json()["created_by"] == ""


async def test_comment_routes_item_none_created_by_falls_back(
    owner,
    shared_project,
    shared_item,
    monkeypatch,
):
    """Item comment with created_by=None falls back to authenticated user's email."""
    monkeypatch.delenv("AGENT_GTD_AGENT_NAME", raising=False)

    transport = ASGITransport(app=app)
    token = create_token(owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/items/{shared_item['id']}/comments",
            json={"content_markdown": "No attribution"},
            headers=headers,
        )
    assert res.status_code == 201
    assert res.json()["created_by"] == owner.email


async def test_comment_routes_item_agent_name_env_attribution(
    owner,
    shared_project,
    shared_item,
    monkeypatch,
):
    """Item comment with AGENT_GTD_AGENT_NAME set derives attribution from env."""
    agent_name = "claude-plan-xyz99999"
    monkeypatch.setenv("AGENT_GTD_AGENT_NAME", agent_name)

    transport = ASGITransport(app=app)
    token = create_token(owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/items/{shared_item['id']}/comments",
            json={"content_markdown": "With env attribution"},
            headers=headers,
        )
    assert res.status_code == 201
    assert res.json()["created_by"] == agent_name


# ---------------------------------------------------------------------------
# MCP add_comment auto-login path: _ENV_AGENT_NAME set → correct attribution
# ---------------------------------------------------------------------------


async def test_mcp_add_comment_with_env_agent_name_attributed_correctly(
    owner,
    shared_project,
    shared_item,
    monkeypatch,
):
    """MCP add_comment with _ENV_AGENT_NAME set produces correct created_by.

    This tests the full MCP → LocalBackend → comment_routes path using the
    in-process LocalBackend, verifying the attribution chain end-to-end.
    """
    import agent_gtd.database as db_mod
    import agent_gtd.mcp_server as srv

    agent_name = "claude-plan-def45678"
    api_key = await _create_api_key(owner.id)

    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", "")
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)
    monkeypatch.setattr(srv, "_ENV_AGENT_NAME", agent_name)

    async with Client(mcp) as c:
        result = await c.call_tool(
            "add_comment",
            {
                "content_markdown": "Agent progress update",
                "item_id": shared_item["id"],
            },
        )

    import json

    data = (
        result.data
        if isinstance(result.data, dict)
        else json.loads(result.content[0].text)
    )
    assert data["created_by"] == agent_name, (
        f"Expected created_by={agent_name!r}, got {data['created_by']!r}"
    )
