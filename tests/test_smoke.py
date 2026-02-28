"""Smoke tests for Agent Gtd API."""

from httpx import AsyncClient


async def test_health(client: AsyncClient):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_register_and_login(client: AsyncClient):
    # Register
    res = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "test@example.com"

    # Login with same credentials
    res = await client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert res.status_code == 200
    assert "token" in res.json()


async def test_notes_crud(client: AsyncClient, auth_headers: dict[str, str]):
    # Create a note
    res = await client.post(
        "/api/notes",
        json={"title": "Test Note", "content": "Hello world", "tags": ["test"]},
        headers=auth_headers,
    )
    assert res.status_code == 201
    note = res.json()
    assert note["title"] == "Test Note"
    note_id = note["id"]

    # List notes
    res = await client.get("/api/notes", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1

    # Update the note
    res = await client.patch(
        f"/api/notes/{note_id}",
        json={"title": "Updated Note"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["title"] == "Updated Note"

    # Delete the note
    res = await client.delete(f"/api/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 204

    # Verify deletion
    res = await client.get("/api/notes", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 0
