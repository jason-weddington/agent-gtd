"""Tests for admin user management endpoints (list, promote, delete)."""

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
async def admin_user() -> tuple[str, str]:
    """Create an admin user. Returns (user_id, token)."""
    return await _make_admin()


@pytest.fixture
async def admin_headers(admin_user: tuple[str, str]) -> dict[str, str]:
    """Auth headers for an admin user."""
    _, token = admin_user
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_user_id(admin_user: tuple[str, str]) -> str:
    """Return the admin user's ID."""
    user_id, _ = admin_user
    return user_id


@pytest.fixture
async def regular_headers() -> dict[str, str]:
    """Auth headers for a regular (non-admin) user."""
    _, token = await _make_regular()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def target_user() -> tuple[str, str]:
    """Create a regular user as a deletion target. Returns (user_id, token)."""
    user = await register_user("target@example.com", "targetpass123")
    return user.id, create_token(user.id)


# ---------------------------------------------------------------------------
# GET /api/admin/users — list users
# ---------------------------------------------------------------------------


async def test_list_users_unauthenticated(client: AsyncClient) -> None:
    """GET without auth returns 401 or 403."""
    res = await client.get("/api/admin/users")
    assert res.status_code in (401, 403)


async def test_list_users_non_admin(
    client: AsyncClient,
    regular_headers: dict[str, str],
) -> None:
    """Non-admin gets 403."""
    res = await client.get("/api/admin/users", headers=regular_headers)
    assert res.status_code == 403


async def test_list_users_as_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Admin gets 200 with a list; each item has the expected fields."""
    res = await client.get("/api/admin/users", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    user = data[0]
    assert "id" in user
    assert "email" in user
    assert "is_admin" in user
    assert "created_at" in user


async def test_list_users_most_recent_first(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Users are returned most-recent-first."""
    # Create a second user
    await register_user("second@example.com", "secondpass123")
    res = await client.get("/api/admin/users", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 2
    # Verify descending order
    for i in range(len(data) - 1):
        assert data[i]["created_at"] >= data[i + 1]["created_at"]


# ---------------------------------------------------------------------------
# POST /api/admin/users/{id}/promote
# ---------------------------------------------------------------------------


async def test_promote_as_non_admin(
    client: AsyncClient,
    regular_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Non-admin gets 403."""
    user_id, _ = target_user
    res = await client.post(
        f"/api/admin/users/{user_id}/promote", headers=regular_headers
    )
    assert res.status_code == 403


async def test_promote_unknown_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Promoting a non-existent user returns 404."""
    res = await client.post(
        "/api/admin/users/00000000-0000-0000-0000-000000000000/promote",
        headers=admin_headers,
    )
    assert res.status_code == 404


async def test_promote_success(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Promoting a user returns 200 with is_admin=true."""
    user_id, user_token = target_user
    res = await client.post(
        f"/api/admin/users/{user_id}/promote", headers=admin_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is True
    assert data["id"] == user_id

    # Verify via /api/auth/me that the token's user is now admin
    me_res = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert me_res.status_code == 200
    assert me_res.json()["is_admin"] is True


async def test_promote_idempotent(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Promoting the same user twice both return 200."""
    user_id, _ = target_user
    for _ in range(2):
        res = await client.post(
            f"/api/admin/users/{user_id}/promote", headers=admin_headers
        )
        assert res.status_code == 200
        assert res.json()["is_admin"] is True


# ---------------------------------------------------------------------------
# DELETE /api/admin/users/{id}
# ---------------------------------------------------------------------------


async def test_delete_unauthenticated(
    client: AsyncClient,
    target_user: tuple[str, str],
) -> None:
    """DELETE without auth returns 401 or 403."""
    user_id, _ = target_user
    res = await client.delete(f"/api/admin/users/{user_id}")
    assert res.status_code in (401, 403)


async def test_delete_as_non_admin(
    client: AsyncClient,
    regular_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Non-admin gets 403."""
    user_id, _ = target_user
    res = await client.delete(
        f"/api/admin/users/{user_id}", headers=regular_headers
    )
    assert res.status_code == 403


async def test_delete_unknown_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Deleting a non-existent user returns 404."""
    res = await client.delete(
        "/api/admin/users/00000000-0000-0000-0000-000000000000",
        headers=admin_headers,
    )
    assert res.status_code == 404


async def test_delete_self(
    client: AsyncClient,
    admin_user_id: str,
    admin_headers: dict[str, str],
) -> None:
    """Admin cannot delete their own account — returns 400."""
    res = await client.delete(
        f"/api/admin/users/{admin_user_id}", headers=admin_headers
    )
    assert res.status_code == 400
    assert "Cannot delete your own account" in res.json()["detail"]


async def test_delete_user_with_projects(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Delete returns 409 if the target user owns projects."""
    user_id, user_token = target_user
    # Create a project as the target user
    proj_res = await client.post(
        "/api/projects",
        json={"name": "Target's Project"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert proj_res.status_code == 201

    res = await client.delete(
        f"/api/admin/users/{user_id}", headers=admin_headers
    )
    assert res.status_code == 409
    assert "projects" in res.json()["detail"]


async def test_delete_user_with_items(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Delete returns 409 if the target user owns items."""
    user_id, user_token = target_user
    # Create an inbox item as the target user
    item_res = await client.post(
        "/api/inbox",
        json={"title": "Target's item"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert item_res.status_code == 201

    res = await client.delete(
        f"/api/admin/users/{user_id}", headers=admin_headers
    )
    assert res.status_code == 409
    assert "items" in res.json()["detail"]


async def test_delete_success(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Admin can delete a user with no projects or items — returns 204."""
    user_id, _ = target_user
    res = await client.delete(
        f"/api/admin/users/{user_id}", headers=admin_headers
    )
    assert res.status_code == 204

    # User should no longer appear in the user list
    list_res = await client.get("/api/admin/users", headers=admin_headers)
    assert list_res.status_code == 200
    ids = [u["id"] for u in list_res.json()]
    assert user_id not in ids


async def test_delete_cleans_up_invites(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Deleting a user also removes invites they issued."""
    user_id, user_token = target_user
    # Promote target user to admin so they can issue invites
    promote_res = await client.post(
        f"/api/admin/users/{user_id}/promote", headers=admin_headers
    )
    assert promote_res.status_code == 200

    # Issue an invite as the target user
    invite_res = await client.post(
        "/api/admin/invites",
        json={"note": "test invite"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert invite_res.status_code == 201
    invite_token = invite_res.json()["token"]

    # Delete the target user
    del_res = await client.delete(
        f"/api/admin/users/{user_id}", headers=admin_headers
    )
    assert del_res.status_code == 204

    # Verify the invite is gone from the database
    db = await get_db()
    row = await db.fetchrow("SELECT token FROM invites WHERE token = $1", invite_token)
    assert row is None


async def test_delete_cleans_up_password_resets(
    client: AsyncClient,
    admin_headers: dict[str, str],
    target_user: tuple[str, str],
) -> None:
    """Deleting a user also removes their password_resets rows."""
    user_id, _ = target_user
    # Issue a password reset for the target user
    reset_res = await client.post(
        f"/api/admin/users/{user_id}/password-reset",
        headers=admin_headers,
    )
    assert reset_res.status_code == 200
    reset_token = reset_res.json()["token"]

    # Delete the target user
    del_res = await client.delete(
        f"/api/admin/users/{user_id}", headers=admin_headers
    )
    assert del_res.status_code == 204

    # Verify the password_resets row is gone
    db = await get_db()
    row = await db.fetchrow(
        "SELECT token FROM password_resets WHERE token = $1", reset_token
    )
    assert row is None
