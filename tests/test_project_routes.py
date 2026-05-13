"""Tests for project route response shape — additive field checks."""

from httpx import AsyncClient


async def test_list_projects_includes_description_preview(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """GET /api/projects responses include description_preview (None until SMOKE-5)."""
    await client.post(
        "/api/projects",
        json={"name": "Preview Test Project", "description": "Some description"},
        headers=auth_headers,
    )

    res = await client.get("/api/projects", headers=auth_headers)
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    assert "description_preview" in projects[0]
    assert projects[0]["description_preview"] is None
