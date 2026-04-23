"""Tests for file attachment backend — storage helpers and read/delete endpoints."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from agent_gtd.database import get_db
from agent_gtd.models import Attachment
from agent_gtd.services import attachment_service
from agent_gtd.services.attachment_storage import sanitize_filename

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def attachments_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp attachments root and point the env var at it."""
    root = tmp_path / "attachments"
    root.mkdir()
    monkeypatch.setenv("AGENT_GTD_ATTACHMENTS_ROOT", str(root))
    return root


@pytest.fixture
async def item_id(
    client: AsyncClient, auth_headers: dict[str, str], project_id: str
) -> str:
    """Create a project item and return its ID."""
    res = await client.post(
        f"/api/projects/{project_id}/items",
        json={"title": "Test Item"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _make_attachment(
    item_id: str,
    filename: str = "test.png",
    mime_type: str = "image/png",
    size_bytes: int = 42,
    storage_path: str | None = None,
) -> Attachment:
    """Insert an attachment row and return the domain object."""
    attachment_id = str(uuid.uuid4())
    sp = storage_path or f"{item_id}/{attachment_id}-{filename}"
    attachment = Attachment(
        id=attachment_id,
        item_id=item_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        storage_path=sp,
        created_at=datetime.now(UTC),
    )
    db = await get_db()
    await attachment_service.insert(db, attachment)
    return attachment


def _write_fixture_file(
    attachments_root: Path, attachment: Attachment, content: bytes = b"fake bytes"
) -> Path:
    """Write a fixture file to disk for the given attachment and return its path."""
    file_path = attachments_root / attachment.storage_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path


# ---------------------------------------------------------------------------
# sanitize_filename unit tests
# ---------------------------------------------------------------------------


def test_sanitize_normal():
    assert sanitize_filename("screenshot.png") == "screenshot.png"


def test_sanitize_empty():
    assert sanitize_filename("") == "file"


def test_sanitize_dots_only():
    # Dots are in the allowed set, so "..." is kept as-is
    result = sanitize_filename("...")
    assert "/" not in result
    assert "\\" not in result


def test_sanitize_traversal():
    # Path separators must be removed — the critical security property.
    # Dots are allowed by the spec ([A-Za-z0-9._-]), so "../../etc/passwd"
    # becomes something like "....etcpasswd" (slashes stripped), which is a
    # safe filename when stored as `<item_id>/<uuid>-<name>`.
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result
    assert "\\" not in result


def test_sanitize_unicode():
    result = sanitize_filename("résumé.pdf")
    assert result.endswith(".pdf")
    # Non-ASCII stripped
    assert "é" not in result
    # At minimum the extension survives
    assert len(result) > 0


def test_sanitize_oversize():
    long_name = "a" * 250 + ".png"
    result = sanitize_filename(long_name)
    assert len(result) <= 200
    assert result.endswith(".png")


def test_sanitize_no_valid_base():
    # Name part is all non-allowed chars, but ext is valid
    result = sanitize_filename("!!!.jpg")
    assert result == "file.jpg"


def test_sanitize_path_separators_stripped():
    result = sanitize_filename("some/path/file.txt")
    assert "/" not in result


def test_sanitize_windows_separators_stripped():
    result = sanitize_filename(r"some\path\file.txt")
    assert "\\" not in result


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


async def test_list_attachments_empty(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    res = await client.get(f"/api/items/{item_id}/attachments", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_list_attachments_happy(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    a1 = await _make_attachment(item_id, filename="a.png")
    a2 = await _make_attachment(item_id, filename="b.txt", mime_type="text/plain")

    res = await client.get(f"/api/items/{item_id}/attachments", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    ids = {d["id"] for d in data}
    assert a1.id in ids
    assert a2.id in ids
    # storage_path must not appear in response
    for d in data:
        assert "storage_path" not in d


async def test_list_attachments_item_not_found(
    client: AsyncClient,
    auth_headers: dict[str, str],
    attachments_root: Path,
):
    res = await client.get(
        f"/api/items/{uuid.uuid4()}/attachments", headers=auth_headers
    )
    assert res.status_code == 404


async def test_list_attachments_cross_user_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    """A second user cannot list another user's item's attachments."""
    # Register a second user
    res = await client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "pass1234"},
    )
    other_headers = {"Authorization": f"Bearer {res.json()['token']}"}

    res2 = await client.get(f"/api/items/{item_id}/attachments", headers=other_headers)
    assert res2.status_code == 404


# ---------------------------------------------------------------------------
# Get (download) endpoint
# ---------------------------------------------------------------------------


async def test_get_attachment_happy(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    content = b"\x89PNG\r\n\x1a\n" + b"fake"
    attachment = await _make_attachment(
        item_id, filename="img.png", mime_type="image/png"
    )
    _write_fixture_file(attachments_root, attachment, content=content)

    res = await client.get(f"/api/attachments/{attachment.id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.content == content
    assert res.headers["content-type"].startswith("image/png")
    assert "inline" in res.headers["content-disposition"]
    assert "img.png" in res.headers["content-disposition"]


async def test_get_attachment_not_found(
    client: AsyncClient,
    auth_headers: dict[str, str],
    attachments_root: Path,
):
    res = await client.get(f"/api/attachments/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404


async def test_get_attachment_cross_user_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    """A second user cannot download another user's attachment."""
    attachment = await _make_attachment(item_id, filename="private.png")
    _write_fixture_file(attachments_root, attachment)

    res = await client.post(
        "/api/auth/register",
        json={"email": "thief@example.com", "password": "pass1234"},
    )
    other_headers = {"Authorization": f"Bearer {res.json()['token']}"}

    res2 = await client.get(f"/api/attachments/{attachment.id}", headers=other_headers)
    assert res2.status_code == 404


async def test_get_attachment_file_missing_on_disk(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    """Row exists in DB but the file was deleted off disk → 404."""
    attachment = await _make_attachment(item_id, filename="gone.png")
    # Do NOT write the file to disk

    res = await client.get(f"/api/attachments/{attachment.id}", headers=auth_headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Delete endpoint
# ---------------------------------------------------------------------------


async def test_delete_attachment_happy(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    attachment = await _make_attachment(item_id, filename="del.png")
    file_path = _write_fixture_file(attachments_root, attachment)

    res = await client.delete(f"/api/attachments/{attachment.id}", headers=auth_headers)
    assert res.status_code == 204

    # Row gone
    db = await get_db()
    assert await attachment_service.get(db, attachment.id) is None
    # File gone
    assert not file_path.exists()


async def test_delete_attachment_not_found(
    client: AsyncClient,
    auth_headers: dict[str, str],
    attachments_root: Path,
):
    res = await client.delete(f"/api/attachments/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404


async def test_delete_attachment_cross_user_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    """A second user cannot delete another user's attachment."""
    attachment = await _make_attachment(item_id, filename="owned.png")
    _write_fixture_file(attachments_root, attachment)

    res = await client.post(
        "/api/auth/register",
        json={"email": "attacker@example.com", "password": "pass1234"},
    )
    other_headers = {"Authorization": f"Bearer {res.json()['token']}"}

    res2 = await client.delete(
        f"/api/attachments/{attachment.id}", headers=other_headers
    )
    assert res2.status_code == 404

    # Row still present
    db = await get_db()
    assert await attachment_service.get(db, attachment.id) is not None


# ---------------------------------------------------------------------------
# Cascade: deleting the item removes attachment rows and files dir
# ---------------------------------------------------------------------------


async def test_cascade_on_item_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    item_id: str,
    attachments_root: Path,
):
    attachment = await _make_attachment(item_id, filename="cascade.png")
    _write_fixture_file(attachments_root, attachment)

    item_dir = attachments_root / item_id

    # Delete the item
    res = await client.delete(f"/api/items/{item_id}", headers=auth_headers)
    assert res.status_code == 204

    # Attachment row gone (cascaded)
    db = await get_db()
    assert await attachment_service.get(db, attachment.id) is None

    # Files directory removed
    assert not item_dir.exists()
