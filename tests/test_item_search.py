"""Tests for GET /api/items/search endpoint."""

import pytest
from httpx import AsyncClient


async def test_search_returns_matching_items(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Basic match: search finds items whose title contains the query."""
    await client.post(
        "/api/items",
        json={"title": "Buy groceries", "status": "next_action"},
        headers=auth_headers,
    )
    await client.post(
        "/api/items",
        json={"title": "Send report"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "groc"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["title"] == "Buy groceries"


async def test_search_no_match_returns_empty_list(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """No match: endpoint returns an empty list, not a 404."""
    await client.post(
        "/api/items",
        json={"title": "Buy groceries"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "zzznomatch"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json() == []


async def test_search_excludes_done_items(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Done items must not appear in search results."""
    await client.post(
        "/api/items",
        json={"title": "Finished task", "status": "done"},
        headers=auth_headers,
    )
    await client.post(
        "/api/items",
        json={"title": "Finished draft", "status": "next_action"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "Finished"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["title"] == "Finished draft"
    for item in data:
        assert item["status"] != "done"


async def test_search_case_insensitive(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Search is case-insensitive."""
    await client.post(
        "/api/items",
        json={"title": "Deploy to Production", "status": "active"},
        headers=auth_headers,
    )

    for q in ["deploy", "DEPLOY", "Deploy", "production"]:
        res = await client.get(
            "/api/items/search", params={"q": q}, headers=auth_headers
        )
        assert res.status_code == 200, f"Failed for q={q!r}"
        data = res.json()
        assert len(data) == 1, f"Expected 1 result for q={q!r}, got {len(data)}"
        assert data[0]["title"] == "Deploy to Production"


async def test_search_prefix_matches_rank_first(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Prefix matches must appear before substring-only matches."""
    # "alpha" appears as prefix in "alpha thing", as substring in "do alpha later"
    await client.post(
        "/api/items",
        json={"title": "do alpha later", "status": "next_action"},
        headers=auth_headers,
    )
    await client.post(
        "/api/items",
        json={"title": "alpha thing", "status": "next_action"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "alpha"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    # prefix match should come first
    assert data[0]["title"] == "alpha thing"
    assert data[1]["title"] == "do alpha later"


async def test_search_ownership_isolation(
    client: AsyncClient,
):
    """User A cannot see User B's items in search results."""
    # Register user A
    res_a = await client.post(
        "/api/auth/register",
        json={"email": "user_a@example.com", "password": "pass123"},
    )
    headers_a = {"Authorization": f"Bearer {res_a.json()['token']}"}

    # Register user B
    res_b = await client.post(
        "/api/auth/register",
        json={"email": "user_b@example.com", "password": "pass123"},
    )
    headers_b = {"Authorization": f"Bearer {res_b.json()['token']}"}

    # User A creates an item
    await client.post(
        "/api/items",
        json={"title": "Secret plan", "status": "next_action"},
        headers=headers_a,
    )

    # User B searches — must not see User A's item
    res = await client.get(
        "/api/items/search", params={"q": "Secret"}, headers=headers_b
    )
    assert res.status_code == 200
    assert res.json() == []


async def test_search_includes_project_info(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
):
    """Search results include project_id and project_name when available."""
    await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Project task", "status": "next_action"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "Project task"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["project_id"] == project_id
    assert data[0]["project_name"] == "Test Project"


async def test_search_null_project_when_no_project(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Items without a project have null project_id and project_name."""
    await client.post(
        "/api/items",
        json={"title": "Standalone task", "status": "next_action"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "Standalone"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["project_id"] is None
    assert data[0]["project_name"] is None


async def test_search_query_too_short(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """q shorter than 2 chars is rejected with 422."""
    res = await client.get("/api/items/search", params={"q": "a"}, headers=auth_headers)
    assert res.status_code == 422


async def test_search_query_too_long(client: AsyncClient, auth_headers: dict[str, str]):
    """q longer than 100 chars is rejected with 422."""
    res = await client.get(
        "/api/items/search", params={"q": "x" * 101}, headers=auth_headers
    )
    assert res.status_code == 422


async def test_search_limit_too_large(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """limit > 25 is rejected with 422."""
    res = await client.get(
        "/api/items/search", params={"q": "test", "limit": 26}, headers=auth_headers
    )
    assert res.status_code == 422


async def test_search_limit_default_is_ten(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """When limit is omitted, at most 10 results are returned."""
    for i in range(15):
        await client.post(
            "/api/items",
            json={"title": f"Searchable item {i:02d}", "status": "next_action"},
            headers=auth_headers,
        )

    res = await client.get(
        "/api/items/search", params={"q": "Searchable"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert len(res.json()) == 10


async def test_search_custom_limit(client: AsyncClient, auth_headers: dict[str, str]):
    """Custom limit is respected."""
    for i in range(5):
        await client.post(
            "/api/items",
            json={"title": f"Widget item {i}", "status": "next_action"},
            headers=auth_headers,
        )

    res = await client.get(
        "/api/items/search",
        params={"q": "Widget", "limit": 3},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert len(res.json()) == 3


async def test_search_requires_auth(client: AsyncClient):
    """Unauthenticated request is rejected with 401 or 403."""
    res = await client.get("/api/items/search", params={"q": "test"})
    assert res.status_code in (401, 403)


async def test_search_response_shape(client: AsyncClient, auth_headers: dict[str, str]):
    """Each result has the expected BlockerSummary fields."""
    await client.post(
        "/api/items",
        json={"title": "Shape check item", "status": "active"},
        headers=auth_headers,
    )

    res = await client.get(
        "/api/items/search", params={"q": "Shape"}, headers=auth_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    item = data[0]
    assert set(item.keys()) == {"id", "title", "status", "project_id", "project_name"}
    assert item["status"] == "active"


@pytest.mark.parametrize("limit", [1, 5, 25])
async def test_search_valid_limit_values(
    client: AsyncClient, auth_headers: dict[str, str], limit: int
):
    """Valid limit values (1-25) are accepted."""
    res = await client.get(
        "/api/items/search",
        params={"q": "anything", "limit": limit},
        headers=auth_headers,
    )
    assert res.status_code == 200
