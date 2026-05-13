"""Tests for comments CRUD API."""

import asyncio

from httpx import AsyncClient


async def _create_item(
    client: AsyncClient, headers: dict[str, str], project_id: str, title: str = "Task"
) -> str:
    """Helper: create an item in a project and return its ID."""
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": title},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


# --- Project comments ---


async def test_create_project_comment(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Looks good!"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["content_markdown"] == "Looks good!"
    assert data["project_id"] == project_id
    assert data["item_id"] is None
    assert data["created_by"] == "human"


async def test_create_project_comment_with_created_by(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Agent note", "created_by": "claude-code"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["created_by"] == "claude-code"


async def test_comment_created_by_build_attribution(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Regression: build-mode attribution created_by is stored and returned."""
    attribution = "claude-build-abc12345"
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Build agent comment", "created_by": attribution},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["created_by"].startswith("claude-build-")
    assert res.json()["created_by"] == attribution


async def test_create_project_comment_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/projects/nonexistent/comments",
        json={"content_markdown": "Orphan"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_list_project_comments(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "First"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Second"},
        headers=auth_headers,
    )

    res = await client.get(f"/api/projects/{project_id}/comments", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2


# --- Item comments ---


async def test_create_item_comment(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    item_id = await _create_item(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/comments",
        json={"content_markdown": "Working on this"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["content_markdown"] == "Working on this"
    assert data["item_id"] == item_id
    assert data["project_id"] is None


async def test_create_item_comment_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/items/nonexistent/comments",
        json={"content_markdown": "Orphan"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_list_item_comments(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    item_id = await _create_item(client, auth_headers, project_id)

    await client.post(
        f"/api/items/{item_id}/comments",
        json={"content_markdown": "Comment 1"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/items/{item_id}/comments",
        json={"content_markdown": "Comment 2"},
        headers=auth_headers,
    )

    res = await client.get(f"/api/items/{item_id}/comments", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2


# --- Chronological ordering ---


async def test_comments_chronological_order(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    for text in ["First", "Second", "Third"]:
        await client.post(
            f"/api/projects/{project_id}/comments",
            json={"content_markdown": text},
            headers=auth_headers,
        )
        await asyncio.sleep(0.01)  # ensure distinct timestamps

    res = await client.get(f"/api/projects/{project_id}/comments", headers=auth_headers)
    contents = [c["content_markdown"] for c in res.json()]
    assert contents == ["First", "Second", "Third"]


# --- Direct comment endpoints ---


async def test_get_comment(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Hello"},
        headers=auth_headers,
    )
    comment_id = res.json()["id"]

    res = await client.get(f"/api/comments/{comment_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["content_markdown"] == "Hello"


async def test_get_comment_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.get("/api/comments/nonexistent", headers=auth_headers)
    assert res.status_code == 404


async def test_update_comment(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "Original"},
        headers=auth_headers,
    )
    comment_id = res.json()["id"]

    res = await client.patch(
        f"/api/comments/{comment_id}",
        json={"content_markdown": "Updated"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["content_markdown"] == "Updated"


async def test_update_comment_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.patch(
        "/api/comments/nonexistent",
        json={"content_markdown": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_delete_comment(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    res = await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "To delete"},
        headers=auth_headers,
    )
    comment_id = res.json()["id"]

    res = await client.delete(f"/api/comments/{comment_id}", headers=auth_headers)
    assert res.status_code == 204

    res = await client.get(f"/api/comments/{comment_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_delete_comment_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.delete("/api/comments/nonexistent", headers=auth_headers)
    assert res.status_code == 404


# --- Cascade deletion ---


async def test_cascade_on_project_delete(
    client: AsyncClient, auth_headers: dict[str, str]
):
    res = await client.post(
        "/api/projects", json={"name": "Temp Project"}, headers=auth_headers
    )
    pid = res.json()["id"]

    res = await client.post(
        f"/api/projects/{pid}/comments",
        json={"content_markdown": "Project comment"},
        headers=auth_headers,
    )
    comment_id = res.json()["id"]

    await client.delete(f"/api/projects/{pid}", headers=auth_headers)

    res = await client.get(f"/api/comments/{comment_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_cascade_on_item_delete(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    item_id = await _create_item(client, auth_headers, project_id)

    res = await client.post(
        f"/api/items/{item_id}/comments",
        json={"content_markdown": "Item comment"},
        headers=auth_headers,
    )
    comment_id = res.json()["id"]

    await client.delete(f"/api/items/{item_id}", headers=auth_headers)

    res = await client.get(f"/api/comments/{comment_id}", headers=auth_headers)
    assert res.status_code == 404


# --- Ownership isolation ---


async def test_comment_ownership_isolation(client: AsyncClient):
    from agent_gtd.auth import create_token, register_user

    # Create two users directly (bypass invite system)
    u1 = await register_user("comment_user1@example.com", "pass123")
    headers1 = {"Authorization": f"Bearer {create_token(u1.id)}"}
    u2 = await register_user("comment_user2@example.com", "pass123")
    headers2 = {"Authorization": f"Bearer {create_token(u2.id)}"}

    # User 1 creates a project and comment
    res = await client.post("/api/projects", json={"name": "Private"}, headers=headers1)
    pid = res.json()["id"]

    res = await client.post(
        f"/api/projects/{pid}/comments",
        json={"content_markdown": "Secret comment"},
        headers=headers1,
    )
    cid = res.json()["id"]

    # User 2 cannot access the comment
    res = await client.get(f"/api/comments/{cid}", headers=headers2)
    assert res.status_code == 404


# --- Flat listing with filters ---


async def test_list_comments_filtered_by_project(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    await client.post(
        f"/api/projects/{project_id}/comments",
        json={"content_markdown": "In project"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/comments", params={"project_id": project_id}, headers=auth_headers
    )
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["content_markdown"] == "In project"


async def test_list_comments_filtered_by_item(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    item_id = await _create_item(client, auth_headers, project_id)

    await client.post(
        f"/api/items/{item_id}/comments",
        json={"content_markdown": "On item"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/comments", params={"item_id": item_id}, headers=auth_headers
    )
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["content_markdown"] == "On item"


async def test_list_project_comments_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Listing comments for a non-existent project returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.get(f"/api/projects/{fake_id}/comments", headers=auth_headers)
    assert res.status_code == 404


async def test_list_item_comments_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Listing comments for a non-existent item returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.get(f"/api/items/{fake_id}/comments", headers=auth_headers)
    assert res.status_code == 404


async def test_list_comments_nonexistent_project_filter(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Filtering /comments by non-existent project_id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.get(
        "/api/comments", params={"project_id": fake_id}, headers=auth_headers
    )
    assert res.status_code == 404
