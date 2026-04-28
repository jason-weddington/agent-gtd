"""Tests for admin-issued one-time password-reset links."""

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
async def target_user_id() -> str:
    """Create a regular user as the reset target. Returns their user_id."""
    user = await register_user("target@example.com", "oldpassword123")
    return user.id


# ---------------------------------------------------------------------------
# Issue endpoint — authorization
# ---------------------------------------------------------------------------


async def test_issue_unauthenticated(
    client: AsyncClient,
    target_user_id: str,
) -> None:
    """POST without auth returns 401/403."""
    res = await client.post(f"/api/admin/users/{target_user_id}/password-reset")
    assert res.status_code in (401, 403)


async def test_issue_non_admin(
    client: AsyncClient,
    regular_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """Non-admin gets 403."""
    res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=regular_headers,
    )
    assert res.status_code == 403


async def test_issue_unknown_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Admin issuing for a non-existent user gets 404."""
    res = await client.post(
        "/api/admin/users/00000000-0000-0000-0000-000000000000/password-reset",
        headers=admin_headers,
    )
    assert res.status_code == 404


async def test_issue_as_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """Admin can issue a reset link; response has token, url, expires_at."""
    res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=admin_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert "url" in data
    assert "reset-password?token=" in data["url"]
    assert "expires_at" in data


async def test_issue_url_uses_public_url_env(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """When AGENT_GTD_PUBLIC_URL is set, the issued URL uses it as the base."""
    monkeypatch.setenv("AGENT_GTD_PUBLIC_URL", "https://r7-research")
    res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=admin_headers,
    )
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("https://r7-research/reset-password?token=")


# ---------------------------------------------------------------------------
# Consume endpoint — happy path
# ---------------------------------------------------------------------------


async def test_consume_valid_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """Valid token → 204; old password rejected; new password works."""
    # Issue reset
    issue_res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=admin_headers,
    )
    assert issue_res.status_code == 200
    token = issue_res.json()["token"]

    # Consume the token with a new password
    consume_res = await client.post(
        "/api/auth/password-reset",
        json={"token": token, "new_password": "newpassword456"},
    )
    assert consume_res.status_code == 204

    # Old password should no longer work
    old_login = await client.post(
        "/api/auth/login",
        json={"email": "target@example.com", "password": "oldpassword123"},
    )
    assert old_login.status_code == 401

    # New password should work
    new_login = await client.post(
        "/api/auth/login",
        json={"email": "target@example.com", "password": "newpassword456"},
    )
    assert new_login.status_code == 200
    assert "token" in new_login.json()


# ---------------------------------------------------------------------------
# Consume endpoint — error cases
# ---------------------------------------------------------------------------


async def test_consume_missing_token(client: AsyncClient) -> None:
    """Non-existent token returns 400."""
    res = await client.post(
        "/api/auth/password-reset",
        json={"token": "does-not-exist", "new_password": "newpassword456"},
    )
    assert res.status_code == 400
    assert "Invalid reset token" in res.json()["detail"]


async def test_consume_used_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """Second use of the same token returns 410."""
    # Issue reset
    issue_res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=admin_headers,
    )
    assert issue_res.status_code == 200
    token = issue_res.json()["token"]

    # First consumption succeeds
    first = await client.post(
        "/api/auth/password-reset",
        json={"token": token, "new_password": "newpassword456"},
    )
    assert first.status_code == 204

    # Second consumption returns 410
    second = await client.post(
        "/api/auth/password-reset",
        json={"token": token, "new_password": "anotherpassword789"},
    )
    assert second.status_code == 410
    assert "already used" in second.json()["detail"]


async def test_consume_expired_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user_id: str,
) -> None:
    """Expired token returns 410."""
    # Issue reset
    issue_res = await client.post(
        f"/api/admin/users/{target_user_id}/password-reset",
        headers=admin_headers,
    )
    assert issue_res.status_code == 200
    token = issue_res.json()["token"]

    # Manually expire the token
    db = await get_db()
    await db.execute(
        "UPDATE password_resets SET expires_at = $1 WHERE token = $2",
        "2000-01-01T00:00:00+00:00",
        token,
    )

    # Attempt to consume the expired token
    res = await client.post(
        "/api/auth/password-reset",
        json={"token": token, "new_password": "newpassword456"},
    )
    assert res.status_code == 410
    assert "expired" in res.json()["detail"]
