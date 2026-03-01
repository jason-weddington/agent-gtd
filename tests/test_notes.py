"""Tests for project notes CRUD API."""

from httpx import AsyncClient


async def test_create_note(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Meeting Notes", "content_markdown": "# Notes\n\nSome text"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Meeting Notes"
    assert data["content_markdown"] == "# Notes\n\nSome text"
    assert data["project_id"] == project_id
    assert data["labels"] == []


async def test_create_note_with_labels(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Tagged", "labels": ["important", "review"]},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["labels"] == ["important", "review"]


async def test_create_note_project_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/projects/nonexistent/notes",
        json={"title": "Orphan"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_list_project_notes(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Note 1"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Note 2"},
        headers=auth_headers,
    )

    res = await client.get(f"/api/projects/{project_id}/notes", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2


async def test_list_notes_project_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.get("/api/projects/nonexistent/notes", headers=auth_headers)
    assert res.status_code == 404


async def test_get_note(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "My Note"},
        headers=auth_headers,
    )
    note_id = res.json()["id"]

    res = await client.get(f"/api/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["title"] == "My Note"


async def test_get_note_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.get("/api/notes/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_update_note(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Original"},
        headers=auth_headers,
    )
    note_id = res.json()["id"]

    res = await client.patch(
        f"/api/notes/{note_id}",
        json={"title": "Updated", "content_markdown": "New content"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Updated"
    assert data["content_markdown"] == "New content"


async def test_update_note_labels(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "Note"},
        headers=auth_headers,
    )
    note_id = res.json()["id"]

    res = await client.patch(
        f"/api/notes/{note_id}",
        json={"labels": ["tag1", "tag2"]},
        headers=auth_headers,
    )
    assert res.json()["labels"] == ["tag1", "tag2"]


async def test_update_note_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.patch(
        "/api/notes/nonexistent",
        json={"title": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_delete_note(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"title": "To delete"},
        headers=auth_headers,
    )
    note_id = res.json()["id"]

    res = await client.delete(f"/api/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 204

    res = await client.get(f"/api/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_delete_note_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.delete("/api/notes/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_note_ownership_isolation(client: AsyncClient):
    # Register two users
    res1 = await client.post(
        "/api/auth/register",
        json={"email": "user1@example.com", "password": "pass123"},
    )
    headers1 = {"Authorization": f"Bearer {res1.json()['token']}"}

    res2 = await client.post(
        "/api/auth/register",
        json={"email": "user2@example.com", "password": "pass123"},
    )
    headers2 = {"Authorization": f"Bearer {res2.json()['token']}"}

    # User 1 creates a project and note
    res = await client.post("/api/projects", json={"name": "Private"}, headers=headers1)
    pid = res.json()["id"]

    res = await client.post(
        f"/api/projects/{pid}/notes",
        json={"title": "Secret Note"},
        headers=headers1,
    )
    nid = res.json()["id"]

    # User 2 cannot access the note
    res = await client.get(f"/api/notes/{nid}", headers=headers2)
    assert res.status_code == 404
