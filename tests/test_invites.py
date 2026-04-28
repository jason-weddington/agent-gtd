"""Tests for admin invite system and gated registration."""

import pytest
from httpx import AsyncClient

from agent_gtd.auth import create_token, register_user
from agent_gtd.database import get_db

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


async def _make_admin() -> tuple[str, str]:
    """Create a user and promote them to admin. Returns (user_id, token)."""
    user = await register_user("admin@example.com", "adminpass123")
    db = await get_db()
    await db.execute("UPDATE users SET is_admin = 1 WHERE id = $1", user.id)
    return user.id, create_token(user.id)


async def _make_regular() -> tuple[str, str]:
    """Create a regular (non-admin) user. Returns (user_id, token)."""
    user = await register_user("regular@example.com", "regularpass123")
    return user.id, create_token(user.id)


@pytest.fixture
async def admin_headers() -> dict[str, str]:
    """Auth headers for an admin user."""
    _, token = await _make_admin()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def regular_headers() -> dict[str, str]:
    """Auth headers for a regular (non-admin) user."""
    _, token = await _make_regular()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def valid_invite_token(
    client: AsyncClient, admin_headers: dict[str, str]
) -> str:
    """Create an unused invite via the admin endpoint. Returns the token."""
    res = await client.post(
        "/api/admin/invites",
        json={"note": "test invite"},
        headers=admin_headers,
    )
    assert res.status_code == 201
    return str(res.json()["token"])


# ---------------------------------------------------------------------------
# Registration gating
# ---------------------------------------------------------------------------


async def test_register_without_invite_token_returns_400(
    client: AsyncClient,
) -> None:
    """POST /api/auth/register without invite_token should return 422 (validation)."""
    res = await client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "pw123"},
    )
    # Missing required field → FastAPI validation error
    assert res.status_code == 422


async def test_register_with_invalid_invite_token_returns_400(
    client: AsyncClient,
) -> None:
    """POST /api/auth/register with a non-existent token returns 400."""
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "password": "pw123",
            "invite_token": "does-not-exist",
        },
    )
    assert res.status_code == 400
    assert "Invalid invite token" in res.json()["detail"]


async def test_register_with_valid_invite_token_succeeds(
    client: AsyncClient,
    valid_invite_token: str,
) -> None:
    """POST /api/auth/register with a valid invite returns 201 and a JWT."""
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "pw123",
            "invite_token": valid_invite_token,
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "newuser@example.com"
    assert data["user"]["is_admin"] is False


async def test_register_marks_invite_as_used(
    client: AsyncClient,
    valid_invite_token: str,
    admin_headers: dict[str, str],
) -> None:
    """After registration, the invite's used_at is set."""
    await client.post(
        "/api/auth/register",
        json={
            "email": "consumer@example.com",
            "password": "pw123",
            "invite_token": valid_invite_token,
        },
    )
    res = await client.get("/api/admin/invites", headers=admin_headers)
    invite = next(
        (i for i in res.json() if i["token"] == valid_invite_token), None
    )
    assert invite is not None
    assert invite["used_at"] is not None
    assert invite["used_by"] is not None


async def test_register_with_used_invite_token_returns_410(
    client: AsyncClient,
    valid_invite_token: str,
) -> None:
    """Second use of the same invite returns 410 Gone."""
    payload = {
        "email": "first@example.com",
        "password": "pw123",
        "invite_token": valid_invite_token,
    }
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post(
        "/api/auth/register",
        json={
            "email": "second@example.com",
            "password": "pw123",
            "invite_token": valid_invite_token,
        },
    )
    assert second.status_code == 410
    assert "already used" in second.json()["detail"]


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------


async def test_require_admin_rejects_non_admin(
    client: AsyncClient,
    regular_headers: dict[str, str],
) -> None:
    """Admin routes return 403 for authenticated non-admin users."""
    res = await client.get("/api/admin/invites", headers=regular_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == "Admin only"


async def test_require_admin_rejects_unauthenticated(client: AsyncClient) -> None:
    """Admin routes return 401/403 for unauthenticated requests."""
    res = await client.get("/api/admin/invites")
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/admin/invites
# ---------------------------------------------------------------------------


async def test_create_invite_as_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Admin can create an invite; response includes token, url, note, created_at."""
    res = await client.post(
        "/api/admin/invites",
        json={"note": "for alice"},
        headers=admin_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert "url" in data
    assert "register?token=" in data["url"]
    assert data["note"] == "for alice"
    assert "created_at" in data


async def test_create_invite_url_uses_public_url_env(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """When AGENT_GTD_PUBLIC_URL is set, the issued invite URL uses it as the base."""
    monkeypatch.setenv("AGENT_GTD_PUBLIC_URL", "https://r7-research")
    res = await client.post(
        "/api/admin/invites",
        json={"note": "for alice"},
        headers=admin_headers,
    )
    assert res.status_code == 201
    url = res.json()["url"]
    assert url.startswith("https://r7-research/register?token=")


async def test_create_invite_as_non_admin_returns_403(
    client: AsyncClient,
    regular_headers: dict[str, str],
) -> None:
    """Non-admin cannot create an invite."""
    res = await client.post(
        "/api/admin/invites",
        json={"note": "hack"},
        headers=regular_headers,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/admin/invites
# ---------------------------------------------------------------------------


async def test_list_invites_as_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
    valid_invite_token: str,
) -> None:
    """Admin can list invites; returned list includes the created token."""
    res = await client.get("/api/admin/invites", headers=admin_headers)
    assert res.status_code == 200
    tokens = [i["token"] for i in res.json()]
    assert valid_invite_token in tokens


async def test_list_invites_as_non_admin_returns_403(
    client: AsyncClient,
    regular_headers: dict[str, str],
) -> None:
    """Non-admin cannot list invites."""
    res = await client.get("/api/admin/invites", headers=regular_headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/admin/invites/{token}
# ---------------------------------------------------------------------------


async def test_revoke_invite_as_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
    valid_invite_token: str,
) -> None:
    """Admin can revoke an unused invite."""
    res = await client.delete(
        f"/api/admin/invites/{valid_invite_token}",
        headers=admin_headers,
    )
    assert res.status_code == 204

    # Confirm it is gone from the list
    list_res = await client.get("/api/admin/invites", headers=admin_headers)
    tokens = [i["token"] for i in list_res.json()]
    assert valid_invite_token not in tokens


async def test_revoke_used_invite_returns_409(
    client: AsyncClient,
    admin_headers: dict[str, str],
    valid_invite_token: str,
) -> None:
    """Revoking a used invite returns 409 Conflict."""
    # Consume the invite
    await client.post(
        "/api/auth/register",
        json={
            "email": "consumer2@example.com",
            "password": "pw123",
            "invite_token": valid_invite_token,
        },
    )
    res = await client.delete(
        f"/api/admin/invites/{valid_invite_token}",
        headers=admin_headers,
    )
    assert res.status_code == 409
    assert "already used" in res.json()["detail"]


async def test_revoke_nonexistent_invite_returns_404(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Revoking a non-existent invite returns 404."""
    res = await client.delete(
        "/api/admin/invites/does-not-exist",
        headers=admin_headers,
    )
    assert res.status_code == 404


async def test_revoke_invite_as_non_admin_returns_403(
    client: AsyncClient,
    regular_headers: dict[str, str],
    valid_invite_token: str,
) -> None:
    """Non-admin cannot revoke an invite."""
    res = await client.delete(
        f"/api/admin/invites/{valid_invite_token}",
        headers=regular_headers,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# /api/auth/me includes is_admin
# ---------------------------------------------------------------------------


async def test_me_includes_is_admin_false_for_regular_user(
    client: AsyncClient,
    regular_headers: dict[str, str],
) -> None:
    """GET /api/auth/me returns is_admin: false for regular users."""
    res = await client.get("/api/auth/me", headers=regular_headers)
    assert res.status_code == 200
    assert res.json()["is_admin"] is False


async def test_me_includes_is_admin_true_for_admin_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """GET /api/auth/me returns is_admin: true for admin users."""
    res = await client.get("/api/auth/me", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["is_admin"] is True
