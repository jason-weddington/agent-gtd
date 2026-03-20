"""Integration tests for API key endpoints and dual-path auth."""

import pytest
from httpx import AsyncClient


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a test user and return JWT auth headers."""
    res = await client.post(
        "/api/auth/register",
        json={"email": "apikey@example.com", "password": "testpass123"},
    )
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def test_create_api_key(client: AsyncClient, auth_headers):
    res = await client.post(
        "/api/auth/api-keys",
        json={"name": "test-key"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["api_key"].startswith("agtd_")
    assert data["name"] == "test-key"


async def test_create_api_key_empty_name(client: AsyncClient, auth_headers):
    res = await client.post(
        "/api/auth/api-keys",
        json={"name": ""},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["name"] == ""


async def test_list_api_keys(client: AsyncClient, auth_headers):
    # Create two keys
    await client.post(
        "/api/auth/api-keys",
        json={"name": "key-1"},
        headers=auth_headers,
    )
    await client.post(
        "/api/auth/api-keys",
        json={"name": "key-2"},
        headers=auth_headers,
    )

    res = await client.get("/api/auth/api-keys", headers=auth_headers)
    assert res.status_code == 200
    keys = res.json()["keys"]
    assert len(keys) == 2
    names = {k["name"] for k in keys}
    assert names == {"key-1", "key-2"}
    # Each key has an 8-char hash prefix
    for k in keys:
        assert len(k["hash_prefix"]) == 8
        assert "id" in k
        assert "created_at" in k


async def test_revoke_api_key(client: AsyncClient, auth_headers):
    # Create a key
    create_res = await client.post(
        "/api/auth/api-keys",
        json={"name": "disposable"},
        headers=auth_headers,
    )
    api_key = create_res.json()["api_key"]

    # List to get the key ID
    list_res = await client.get("/api/auth/api-keys", headers=auth_headers)
    key_id = list_res.json()["keys"][0]["id"]

    # Revoke it
    del_res = await client.delete(f"/api/auth/api-keys/{key_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # List should be empty
    list_res = await client.get("/api/auth/api-keys", headers=auth_headers)
    assert len(list_res.json()["keys"]) == 0

    # Using the revoked key should fail
    res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert res.status_code == 401


async def test_revoke_nonexistent_key(client: AsyncClient, auth_headers):
    res = await client.delete("/api/auth/api-keys/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_dual_path_auth_with_api_key(client: AsyncClient, auth_headers):
    """API key works as Bearer token for regular API endpoints."""
    # Create an API key
    create_res = await client.post(
        "/api/auth/api-keys",
        json={"name": "dual-auth-test"},
        headers=auth_headers,
    )
    api_key = create_res.json()["api_key"]

    # Use the API key to access /me
    res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "apikey@example.com"


async def test_dual_path_auth_jwt_still_works(client: AsyncClient, auth_headers):
    """JWT continues to work after API key support is added."""
    res = await client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "apikey@example.com"


async def test_invalid_bearer_token(client: AsyncClient):
    """Neither a valid JWT nor a valid API key."""
    res = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer totally_invalid_token"},
    )
    assert res.status_code == 401
