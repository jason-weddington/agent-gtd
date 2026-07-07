"""Tests for the notes and comments CLI subcommands (cli_commands/notes_comments.py)."""

import argparse
import json
import sys
from typing import Any

import pytest

from agent_gtd.cli import main
from agent_gtd.cli_commands.notes_comments import (
    _do_add_comment,
    _do_add_note,
    _do_delete_note,
    _do_get_note,
    _do_list_comments,
    _do_list_notes,
    _do_update_comment,
    _do_update_note,
    _handle_add_comment,
    _handle_get_note,
    _handle_list_notes,
    _handle_update_note,
)

# ---------------------------------------------------------------------------
# Shared project / note / comment setup helpers
# ---------------------------------------------------------------------------


async def _make_project(name: str = "Test Project") -> str:
    """Create a project in the test DB and return its UUID string."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.services import project_service

    db = await get_db()
    project = await project_service.create_project(db, LOCAL_USER_ID, name=name)
    return str(project["id"])


async def _make_note(project_id: str, title: str = "Test Note") -> str:
    """Create a note in the test DB and return its UUID string."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.services import note_service

    db = await get_db()
    note = await note_service.create_note(db, LOCAL_USER_ID, project_id, title=title)
    return str(note["id"])


async def _make_comment(
    project_id: str | None = None,
    item_id: str | None = None,
    content: str = "Hello",
) -> str:
    """Create a comment in the test DB and return its UUID string."""
    from agent_gtd.database import LOCAL_USER_ID, get_db
    from agent_gtd.services import comment_service

    db = await get_db()
    comment = await comment_service.create_comment(
        db,
        LOCAL_USER_ID,
        project_id=project_id,
        item_id=item_id,
        content_markdown=content,
    )
    return str(comment["id"])


def _local_backend_session_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch backend_session and AGENT_GTD_URL for local-mode tests."""
    from agent_gtd.mcp_backend import LocalBackend

    monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    monkeypatch.setattr(
        "agent_gtd.cli_commands._shared.create_backend",
        lambda: LocalBackend(),
    )


# ---------------------------------------------------------------------------
# 1. Local-mode handler tests — one per command (async, calls _do_* directly)
# ---------------------------------------------------------------------------


async def test_do_add_note_creates_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """add-note creates a note with title and content and returns it."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()

    result = await _do_add_note(project_id, "My Note", "# Body", ["tag1"])

    assert result["title"] == "My Note"
    assert result["content_markdown"] == "# Body"
    assert result["project_id"] == project_id
    assert "tag1" in result["labels"]


async def test_do_get_note_returns_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """get-note returns the note dict by ID."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    note_id = await _make_note(project_id, title="Fetchable")

    result = await _do_get_note(note_id)

    assert result["id"] == note_id
    assert result["title"] == "Fetchable"


async def test_do_list_notes_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """list-notes returns a list of notes; project_id filter works."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    await _make_note(project_id, title="N1")
    await _make_note(project_id, title="N2")

    all_notes = await _do_list_notes(None)
    project_notes = await _do_list_notes(project_id)

    assert len(all_notes) >= 2
    assert len(project_notes) == 2
    titles = {n["title"] for n in project_notes}
    assert "N1" in titles
    assert "N2" in titles


async def test_do_update_note_updates_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """update-note updates title and content and returns updated note."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    note_id = await _make_note(project_id, title="Old Title")

    result = await _do_update_note(note_id, "New Title", "New body", None)

    assert result["id"] == note_id
    assert result["title"] == "New Title"
    assert result["content_markdown"] == "New body"


async def test_do_delete_note_removes_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete-note removes the note and returns a confirmation dict."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    note_id = await _make_note(project_id, title="Doomed")

    result = await _do_delete_note(note_id)

    assert isinstance(result, dict)
    # Note should no longer be retrievable.
    from agent_gtd.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await _do_get_note(note_id)


async def test_do_add_comment_creates_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """add-comment creates a comment on a project with created_by='cli'."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()

    result = await _do_add_comment(project_id, None, "Great work!")

    assert result["content_markdown"] == "Great work!"
    assert result["project_id"] == project_id
    assert result["created_by"] == "cli"


async def test_do_list_comments_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """list-comments returns comments filtered by project."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    await _make_comment(project_id=project_id, content="First")
    await _make_comment(project_id=project_id, content="Second")

    result = await _do_list_comments(project_id, None)

    assert len(result) == 2
    contents = {c["content_markdown"] for c in result}
    assert "First" in contents
    assert "Second" in contents


async def test_do_update_comment_updates_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update-comment updates content_markdown and returns updated comment."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    comment_id = await _make_comment(project_id=project_id, content="Old content")

    result = await _do_update_comment(comment_id, "New content")

    assert result["id"] == comment_id
    assert result["content_markdown"] == "New content"


# ---------------------------------------------------------------------------
# 2. main()-dispatch tests — one read command, one write command
# ---------------------------------------------------------------------------


def test_main_list_notes_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() routes 'list-notes' through args.func fall-through and emits JSON."""
    expected_notes = [{"id": "n1", "title": "Dispatched Note"}]

    async def _fake_do_list_notes(project_id: str | None) -> list[dict[str, Any]]:
        return expected_notes

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_list_notes",
        _fake_do_list_notes,
    )
    monkeypatch.setattr(sys, "argv", ["agent-gtd", "list-notes"])

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == expected_notes


def test_main_add_note_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() routes 'add-note' through args.func fall-through and emits JSON."""
    project_id = "proj-uuid-123"
    expected_note: dict[str, Any] = {
        "id": "note-uuid-1",
        "project_id": project_id,
        "title": "CLI Note",
        "content_markdown": "",
    }

    async def _fake_do_add_note(
        pid: str,
        title: str,
        content_markdown: str,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        assert pid == project_id
        assert title == "CLI Note"
        return expected_note

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fake_do_add_note,
    )
    monkeypatch.setattr(
        sys, "argv", ["agent-gtd", "add-note", project_id, "--title", "CLI Note"]
    )

    main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["title"] == "CLI Note"
    assert data["project_id"] == project_id


# ---------------------------------------------------------------------------
# 3. add-comment argument-guard tests
# ---------------------------------------------------------------------------


def test_add_comment_guard_neither_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """add-comment exits 1: neither --project-id nor --item-id given."""
    args = argparse.Namespace(
        content_markdown="some text",
        from_json=None,
        stdin=False,
        project_id=None,
        item_id=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_comment(args)

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_add_comment_guard_both_targets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """add-comment exits 1 when both --project-id and --item-id are given."""
    args = argparse.Namespace(
        content_markdown="some text",
        from_json=None,
        stdin=False,
        project_id="proj-uuid",
        item_id="item-uuid",
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_comment(args)

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_add_comment_guard_absent_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """add-comment exits 1 when neither flag nor payload provides content."""
    args = argparse.Namespace(
        content_markdown=None,
        from_json=None,
        stdin=False,
        project_id="proj-uuid",
        item_id=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_comment(args)

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_add_comment_empty_string_content_passes_through(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """add-comment with an explicit empty string does NOT trigger the content guard."""
    expected: dict[str, Any] = {"id": "c1", "content_markdown": ""}

    async def _fake_do(
        project_id: str | None,
        item_id: str | None,
        content_markdown: str,
    ) -> dict[str, Any]:
        assert content_markdown == ""
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_comment",
        _fake_do,
    )

    args = argparse.Namespace(
        content_markdown="",  # empty string is NOT None — must pass through
        from_json=None,
        stdin=False,
        project_id="proj-uuid",
        item_id=None,
    )

    _handle_add_comment(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["content_markdown"] == ""


# ---------------------------------------------------------------------------
# 4. --content-markdown flag wins over payload key for add-comment
# ---------------------------------------------------------------------------


def test_add_comment_content_markdown_flag_wins(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--content-markdown TEXT overrides 'content_markdown' key in JSON payload."""
    captured_cm: list[str] = []

    async def _fake_do(
        project_id: str | None,
        item_id: str | None,
        content_markdown: str,
    ) -> dict[str, Any]:
        captured_cm.append(content_markdown)
        return {"id": "c1", "content_markdown": content_markdown}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_comment",
        _fake_do,
    )
    # load_json_payload returns a payload that also has content_markdown.
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"content_markdown": "from-payload"},
    )

    args = argparse.Namespace(
        content_markdown="from-flag",  # must win
        from_json=None,
        stdin=False,
        project_id="proj-uuid",
        item_id=None,
    )

    _handle_add_comment(args)

    assert captured_cm == ["from-flag"], (
        "--content-markdown flag should override the payload key"
    )


# ---------------------------------------------------------------------------
# 5. update-note no-op: zero field inputs → unchanged note returned, exit 0
# ---------------------------------------------------------------------------


async def test_do_update_note_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """update-note with all-None fields is a valid no-op; unchanged note returned."""
    _local_backend_session_patch(monkeypatch)
    project_id = await _make_project()
    note_id = await _make_note(project_id, title="Stable Title")

    result = await _do_update_note(note_id, None, None, None)

    assert result["id"] == note_id
    assert result["title"] == "Stable Title"


def test_handle_update_note_noop_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """update-note with no field inputs prints unchanged note JSON and exits 0."""
    unchanged: dict[str, Any] = {"id": "n1", "title": "Stable", "content_markdown": ""}

    async def _fake_do(
        note_id: str,
        title: str | None,
        content_markdown: str | None,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        assert title is None
        assert content_markdown is None
        assert labels is None
        return unchanged

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_note",
        _fake_do,
    )

    args = argparse.Namespace(
        note_id="n1",
        title=None,
        labels=None,
        from_json=None,
        stdin=False,
    )

    # Should not raise SystemExit.
    _handle_update_note(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == unchanged


# ---------------------------------------------------------------------------
# 6. Miscellaneous handler tests for get-note and list-notes (sync dispatch)
# ---------------------------------------------------------------------------


def test_handle_get_note_emits_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_get_note prints the note dict as JSON on stdout."""
    expected: dict[str, Any] = {"id": "note-1", "title": "The Note"}

    async def _fake_do(note_id: str) -> dict[str, Any]:
        assert note_id == "note-1"
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_get_note",
        _fake_do,
    )

    _handle_get_note(argparse.Namespace(note_id="note-1"))

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected


def test_handle_list_notes_emits_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_list_notes prints the list as JSON on stdout."""
    expected: list[dict[str, Any]] = [{"id": "n1"}, {"id": "n2"}]

    async def _fake_do(project_id: str | None) -> list[dict[str, Any]]:
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_list_notes",
        _fake_do,
    )

    _handle_list_notes(argparse.Namespace(project_id=None))

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected


# ---------------------------------------------------------------------------
# 7. Additional handler tests — sync handlers for delete/list/update-comment
# ---------------------------------------------------------------------------


def test_handle_delete_note_emits_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_delete_note prints the confirmation dict as JSON."""
    from agent_gtd.cli_commands.notes_comments import _handle_delete_note

    expected: dict[str, Any] = {"deleted": True, "id": "note-1"}

    async def _fake_do(note_id: str) -> dict[str, Any]:
        assert note_id == "note-1"
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_delete_note",
        _fake_do,
    )

    _handle_delete_note(argparse.Namespace(note_id="note-1"))

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected


def test_handle_list_comments_emits_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_list_comments prints the list as JSON on stdout."""
    from agent_gtd.cli_commands.notes_comments import _handle_list_comments

    expected: list[dict[str, Any]] = [{"id": "c1"}, {"id": "c2"}]

    async def _fake_do(
        project_id: str | None, item_id: str | None
    ) -> list[dict[str, Any]]:
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_list_comments",
        _fake_do,
    )

    _handle_list_comments(argparse.Namespace(project_id=None, item_id=None))

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected


def test_handle_update_comment_with_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_comment with --content-markdown flag updates the comment."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_comment

    expected: dict[str, Any] = {"id": "c1", "content_markdown": "Updated"}
    captured_cm: list[str | None] = []

    async def _fake_do(comment_id: str, content_markdown: str | None) -> dict[str, Any]:
        captured_cm.append(content_markdown)
        return expected

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_comment",
        _fake_do,
    )

    _handle_update_comment(
        argparse.Namespace(
            comment_id="c1",
            content_markdown="Updated",
            from_json=None,
            stdin=False,
        )
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    assert captured_cm == ["Updated"]


def test_handle_update_comment_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_comment reads content_markdown from the JSON payload."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_comment

    captured_cm: list[str | None] = []

    async def _fake_do(comment_id: str, content_markdown: str | None) -> dict[str, Any]:
        captured_cm.append(content_markdown)
        return {"id": "c1", "content_markdown": content_markdown}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_comment",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"content_markdown": "from-payload"},
    )

    _handle_update_comment(
        argparse.Namespace(
            comment_id="c1",
            content_markdown=None,
            from_json=None,
            stdin=False,
        )
    )

    assert captured_cm == ["from-payload"]


def test_handle_update_comment_noop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_comment with no content passes content_markdown=None (no-op)."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_comment

    captured_cm: list[str | None] = []

    async def _fake_do(comment_id: str, content_markdown: str | None) -> dict[str, Any]:
        captured_cm.append(content_markdown)
        return {"id": "c1", "content_markdown": "unchanged"}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_comment",
        _fake_do,
    )

    _handle_update_comment(
        argparse.Namespace(
            comment_id="c1",
            content_markdown=None,
            from_json=None,
            stdin=False,
        )
    )

    assert captured_cm == [None]


# ---------------------------------------------------------------------------
# 8. Payload-key path tests for add-note and update-note
# ---------------------------------------------------------------------------


def test_handle_add_note_title_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note reads title from JSON payload when --title not given."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        project_id: str,
        title: str,
        content_markdown: str,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["title"] = title
        return {"id": "n1", "title": title}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"title": "Payload Title", "content_markdown": "body"},
    )

    _handle_add_note(
        argparse.Namespace(
            project_id="proj-1",
            title=None,  # not given — should come from payload
            labels=None,
            from_json=None,
            stdin=False,
        )
    )

    assert captured["title"] == "Payload Title"


def test_handle_add_note_labels_from_flag_wins(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note: --labels flag overrides labels key in payload."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        project_id: str,
        title: str,
        content_markdown: str,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["labels"] = labels
        return {"id": "n1"}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"labels": ["from-payload"]},
    )

    _handle_add_note(
        argparse.Namespace(
            project_id="proj-1",
            title="T",
            labels=["from-flag,extra"],  # flag wins; comma-split applied
            from_json=None,
            stdin=False,
        )
    )

    assert captured["labels"] == ["from-flag", "extra"]


def test_handle_add_note_labels_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note reads labels from JSON payload when --labels not given."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        project_id: str,
        title: str,
        content_markdown: str,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["labels"] = labels
        return {"id": "n1"}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"labels": ["tag1", "tag2"]},
    )

    _handle_add_note(
        argparse.Namespace(
            project_id="proj-1",
            title="T",
            labels=None,  # not given — read from payload
            from_json=None,
            stdin=False,
        )
    )

    assert captured["labels"] == ["tag1", "tag2"]


def test_handle_update_note_title_and_content_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_note reads title and content_markdown from payload."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        note_id: str,
        title: str | None,
        content_markdown: str | None,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["title"] = title
        captured["content_markdown"] = content_markdown
        captured["labels"] = labels
        return {"id": note_id}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {
            "title": "Payload Title",
            "content_markdown": "Payload body",
            "labels": ["p-tag"],
        },
    )

    _handle_update_note(
        argparse.Namespace(
            note_id="n1",
            title=None,  # none — read from payload
            labels=None,  # none — read from payload
            from_json=None,
            stdin=False,
        )
    )

    assert captured["title"] == "Payload Title"
    assert captured["content_markdown"] == "Payload body"
    assert captured["labels"] == ["p-tag"]


def test_handle_update_note_title_flag_wins(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_note: --title flag overrides title in payload."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        note_id: str,
        title: str | None,
        content_markdown: str | None,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["title"] = title
        return {"id": note_id}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"title": "Payload Title"},
    )

    _handle_update_note(
        argparse.Namespace(
            note_id="n1",
            title="Flag Title",  # wins
            labels=None,
            from_json=None,
            stdin=False,
        )
    )

    assert captured["title"] == "Flag Title"


def test_handle_update_note_labels_flag_wins(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_note: --labels flag overrides labels in payload."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        note_id: str,
        title: str | None,
        content_markdown: str | None,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["labels"] = labels
        return {"id": note_id}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_note",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"labels": ["payload-tag"]},
    )

    _handle_update_note(
        argparse.Namespace(
            note_id="n1",
            title=None,
            labels=["flag-tag"],  # wins
            from_json=None,
            stdin=False,
        )
    )

    assert captured["labels"] == ["flag-tag"]


def test_handle_add_comment_content_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_comment reads content_markdown from payload when flag absent."""
    captured_cm: list[str] = []

    async def _fake_do(
        project_id: str | None,
        item_id: str | None,
        content_markdown: str,
    ) -> dict[str, Any]:
        captured_cm.append(content_markdown)
        return {"id": "c1"}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_comment",
        _fake_do,
    )
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: {"content_markdown": "from-payload-only"},
    )

    _handle_add_comment(
        argparse.Namespace(
            content_markdown=None,  # absent — read from payload
            from_json=None,
            stdin=False,
            project_id="proj-1",
            item_id=None,
        )
    )

    assert captured_cm == ["from-payload-only"]


# ---------------------------------------------------------------------------
# 9. Exception path tests (error propagation → fail() → SystemExit)
# ---------------------------------------------------------------------------


def test_handle_add_note_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    async def _fail_do(*_args: Any, **_kw: Any) -> dict[str, Any]:
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_note(
            argparse.Namespace(
                project_id="p1",
                title="T",
                labels=None,
                from_json=None,
                stdin=False,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_get_note_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_get_note exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_get_note

    async def _fail_do(note_id: str) -> dict[str, Any]:
        raise RuntimeError("not found")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_get_note",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_get_note(argparse.Namespace(note_id="missing"))

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_list_notes_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_list_notes exits 1 and prints Error: when the backend raises."""

    async def _fail_do(project_id: str | None) -> list[dict[str, Any]]:
        raise RuntimeError("DB down")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_list_notes",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_list_notes(argparse.Namespace(project_id=None))

    assert exc_info.value.code != 0


def test_handle_update_note_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_note exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_note

    async def _fail_do(*_args: Any, **_kw: Any) -> dict[str, Any]:
        raise RuntimeError("update failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_note",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_update_note(
            argparse.Namespace(
                note_id="n1",
                title=None,
                labels=None,
                from_json=None,
                stdin=False,
            )
        )

    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 10. Exception path tests — load_json_payload failure in handlers
# ---------------------------------------------------------------------------


def test_handle_add_note_payload_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note exits 1 when load_json_payload raises (e.g. bad JSON)."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: (_ for _ in ()).throw(ValueError("bad JSON")),
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_note(
            argparse.Namespace(
                project_id="p1",
                title=None,
                labels=None,
                from_json=None,
                stdin=True,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_add_note_no_title_no_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_note uses empty string for title when no flag or payload sets it."""
    from agent_gtd.cli_commands.notes_comments import _handle_add_note

    captured: dict[str, Any] = {}

    async def _fake_do(
        project_id: str,
        title: str,
        content_markdown: str,
        labels: list[str] | None,
    ) -> dict[str, Any]:
        captured["title"] = title
        return {"id": "n1", "title": title}

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_note",
        _fake_do,
    )

    _handle_add_note(
        argparse.Namespace(
            project_id="proj-1",
            title=None,  # no flag
            labels=None,
            from_json=None,
            stdin=False,  # no payload either
        )
    )

    assert captured["title"] == ""


def test_handle_update_note_payload_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_note exits 1 when load_json_payload raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_note

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: (_ for _ in ()).throw(ValueError("bad JSON")),
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_update_note(
            argparse.Namespace(
                note_id="n1",
                title=None,
                labels=None,
                from_json=None,
                stdin=True,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_delete_note_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_delete_note exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_delete_note

    async def _fail_do(note_id: str) -> dict[str, Any]:
        raise RuntimeError("delete failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_delete_note",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_delete_note(argparse.Namespace(note_id="missing"))

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_add_comment_payload_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_comment exits 1 when load_json_payload raises."""
    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: (_ for _ in ()).throw(ValueError("bad JSON")),
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_comment(
            argparse.Namespace(
                content_markdown=None,
                from_json=None,
                stdin=True,
                project_id="p1",
                item_id=None,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_add_comment_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_add_comment exits 1 and prints Error: when the backend raises."""

    async def _fail_do(*_args: Any, **_kw: Any) -> dict[str, Any]:
        raise RuntimeError("comment backend error")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_add_comment",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_add_comment(
            argparse.Namespace(
                content_markdown="text",
                from_json=None,
                stdin=False,
                project_id="p1",
                item_id=None,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_list_comments_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_list_comments exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_list_comments

    async def _fail_do(
        project_id: str | None, item_id: str | None
    ) -> list[dict[str, Any]]:
        raise RuntimeError("list failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_list_comments",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_list_comments(argparse.Namespace(project_id=None, item_id=None))

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_update_comment_payload_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_comment exits 1 when load_json_payload raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_comment

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments.load_json_payload",
        lambda *_a: (_ for _ in ()).throw(ValueError("bad JSON")),
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_update_comment(
            argparse.Namespace(
                comment_id="c1",
                content_markdown=None,
                from_json=None,
                stdin=True,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_handle_update_comment_backend_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_handle_update_comment exits 1 and prints Error: when the backend raises."""
    from agent_gtd.cli_commands.notes_comments import _handle_update_comment

    async def _fail_do(comment_id: str, content_markdown: str | None) -> dict[str, Any]:
        raise RuntimeError("update comment failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.notes_comments._do_update_comment",
        _fail_do,
    )

    with pytest.raises(SystemExit) as exc_info:
        _handle_update_comment(
            argparse.Namespace(
                comment_id="c1",
                content_markdown="new",
                from_json=None,
                stdin=False,
            )
        )

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "Error:" in captured.err
