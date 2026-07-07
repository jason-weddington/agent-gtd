"""Tests for src/agent_gtd/cli_commands/projects.py.

Follows tests/test_cli.py conventions:
- Monkeypatch the backend_session seam at its point of use in the projects
  module namespace (agent_gtd.cli_commands.projects.backend_session).
- Use capsys to capture stdout/stderr.
- Use pytest.raises(SystemExit) for exit-code assertions.
- All handler tests are synchronous (handlers call asyncio.run() internally).
"""

from __future__ import annotations

import argparse
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_gtd.cli_commands.projects import (
    _cmd_add_project,
    _cmd_list_project_members,
    _cmd_list_projects,
    _cmd_share_project,
    _cmd_unshare_project,
    _cmd_update_project,
    register,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"


def _make_project(**overrides: Any) -> dict[str, Any]:
    """Return a minimal project dict suitable for testing."""
    proj: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": "Test Project",
        "description": "",
        "area": "",
        "status": "active",
        "git_origin": "",
        "kb_project_ref": "",
        "repo_mode": "monorepo",
        "workspace_repos": [],
        "dispatch_max_turns": None,
        "dispatch_timeout_minutes": None,
        "plan_dispatch_agent": None,
        "build_dispatch_agent": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    proj.update(overrides)
    return proj


def _make_member(**overrides: Any) -> dict[str, Any]:
    """Return a minimal project member dict."""
    member: dict[str, Any] = {
        "user_id": str(uuid.uuid4()),
        "email": "member@example.com",
        "added_at": "2026-01-01T00:00:00Z",
    }
    member.update(overrides)
    return member


def _fake_session(fake_backend: AsyncMock) -> Any:
    """Return a no-arg callable that yields (fake_backend, FAKE_USER_ID)."""

    @asynccontextmanager  # type: ignore[misc]
    async def _ctx() -> Any:
        yield fake_backend, _FAKE_USER_ID

    return _ctx


def _make_parser() -> argparse.ArgumentParser:
    """Build a minimal parser with the projects subcommands registered."""
    parser = argparse.ArgumentParser(prog="agent-gtd")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)
    return parser


# ---------------------------------------------------------------------------
# list-projects
# ---------------------------------------------------------------------------


def test_list_projects_happy_path(monkeypatch, capsys):
    """list-projects emits a JSON array and calls backend.list_projects."""
    projects = [_make_project(), _make_project(name="Second")]
    fake_backend = AsyncMock()
    fake_backend.list_projects.return_value = projects

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    _cmd_list_projects(argparse.Namespace(status=None))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 2
    fake_backend.list_projects.assert_called_once_with(_FAKE_USER_ID, status=None)


def test_list_projects_status_filter(monkeypatch, capsys):
    """list-projects passes the --status filter to backend.list_projects."""
    fake_backend = AsyncMock()
    fake_backend.list_projects.return_value = []

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    _cmd_list_projects(argparse.Namespace(status="completed"))

    fake_backend.list_projects.assert_called_once_with(
        _FAKE_USER_ID, status="completed"
    )


def test_list_projects_invalid_status_choice(capsys):
    """list-projects --status with an invalid choice exits 2 (argparse)."""
    parser = _make_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["list-projects", "--status", "invalid"])
    assert exc_info.value.code == 2


def test_list_projects_backend_error(monkeypatch, capsys):
    """list-projects exits 1 and prints 'Error:' to stderr on backend failure."""
    fake_backend = AsyncMock()
    fake_backend.list_projects.side_effect = RuntimeError("network failure")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_list_projects(argparse.Namespace(status=None))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "network failure" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# add-project
# ---------------------------------------------------------------------------


def test_add_project_happy_path(monkeypatch, capsys):
    """add-project emits the returned project dict as JSON."""
    proj = _make_project(name="My Project")
    fake_backend = AsyncMock()
    fake_backend.create_project.return_value = proj

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        name="My Project",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=None,
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )
    _cmd_add_project(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["name"] == "My Project"
    fake_backend.create_project.assert_called_once_with(
        _FAKE_USER_ID,
        name="My Project",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=None,
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )


def test_add_project_workspace_repos(monkeypatch, capsys):
    """add-project repeatable --workspace-repo -> list[str] forwarded correctly."""
    proj = _make_project(
        repo_mode="workspace",
        workspace_repos=["https://a.git", "https://b.git"],
    )
    fake_backend = AsyncMock()
    fake_backend.create_project.return_value = proj

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        name="WS Project",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="workspace",
        workspace_repos=["https://a.git", "https://b.git"],
        dispatch_max_turns=None,
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )
    _cmd_add_project(args)

    _, kwargs = fake_backend.create_project.call_args
    assert kwargs["workspace_repos"] == ["https://a.git", "https://b.git"]
    assert kwargs["repo_mode"] == "workspace"


def test_add_project_dispatch_max_turns_too_low(capsys):
    """add-project rejects out-of-range --dispatch-max-turns (exit 1, no backend)."""
    fake_backend = AsyncMock()

    args = argparse.Namespace(
        name="X",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=5,  # below MIN_TURNS=10
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_add_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "dispatch_max_turns" in captured.err
    fake_backend.create_project.assert_not_called()


def test_add_project_dispatch_max_turns_too_high(capsys):
    """add-project rejects --dispatch-max-turns above MAX_TURNS (exit 1)."""
    args = argparse.Namespace(
        name="X",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=9999,  # above MAX_TURNS=500
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_add_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_add_project_dispatch_timeout_out_of_range(capsys):
    """add-project rejects out-of-range --dispatch-timeout-minutes (exit 1)."""
    args = argparse.Namespace(
        name="X",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=None,
        dispatch_timeout_minutes=2,  # below MIN_TIMEOUT_MINUTES=5
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_add_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "dispatch_timeout_minutes" in captured.err


def test_add_project_backend_error(monkeypatch, capsys):
    """add-project exits 1 with 'Error:' on stderr when backend raises."""
    fake_backend = AsyncMock()
    fake_backend.create_project.side_effect = RuntimeError("create failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        name="X",
        description="",
        area="",
        status="active",
        git_origin="",
        kb_project_ref="",
        repo_mode="monorepo",
        workspace_repos=None,
        dispatch_max_turns=None,
        dispatch_timeout_minutes=None,
        plan_dispatch_agent=None,
        build_dispatch_agent=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_add_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# update-project
# ---------------------------------------------------------------------------


def test_update_project_happy_path(monkeypatch, capsys):
    """update-project emits the updated project dict as JSON."""
    proj = _make_project(name="Renamed")
    fake_backend = AsyncMock()
    fake_backend.update_project.return_value = proj
    project_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        project_id=project_id,
        name="Renamed",
        description=None,
        status=None,
        area=None,
        git_origin=None,
        kb_project_ref=None,
        repo_mode=None,
        workspace_repos=None,
        dispatch_max_turns=None,
        clear_dispatch_max_turns=False,
        dispatch_timeout_minutes=None,
        clear_dispatch_timeout_minutes=False,
        plan_dispatch_agent=None,
        clear_plan_dispatch_agent=False,
        build_dispatch_agent=None,
        clear_build_dispatch_agent=False,
    )
    _cmd_update_project(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["name"] == "Renamed"
    fake_backend.update_project.assert_called_once_with(
        _FAKE_USER_ID,
        project_id,
        name="Renamed",
        description=None,
        status=None,
        area=None,
        git_origin=None,
        kb_project_ref=None,
        repo_mode=None,
        workspace_repos=None,
        dispatch_max_turns=None,
        clear_dispatch_max_turns=False,
        dispatch_timeout_minutes=None,
        clear_dispatch_timeout_minutes=False,
        plan_dispatch_agent=None,
        clear_plan_dispatch_agent=False,
        build_dispatch_agent=None,
        clear_build_dispatch_agent=False,
    )


def test_update_project_clear_dispatch_max_turns(monkeypatch, capsys):
    """update-project --clear-dispatch-max-turns forwards True to backend."""
    proj = _make_project()
    fake_backend = AsyncMock()
    fake_backend.update_project.return_value = proj
    project_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        project_id=project_id,
        name=None,
        description=None,
        status=None,
        area=None,
        git_origin=None,
        kb_project_ref=None,
        repo_mode=None,
        workspace_repos=None,
        dispatch_max_turns=None,
        clear_dispatch_max_turns=True,  # the clear flag
        dispatch_timeout_minutes=None,
        clear_dispatch_timeout_minutes=False,
        plan_dispatch_agent=None,
        clear_plan_dispatch_agent=False,
        build_dispatch_agent=None,
        clear_build_dispatch_agent=False,
    )
    _cmd_update_project(args)

    _, kwargs = fake_backend.update_project.call_args
    assert kwargs["clear_dispatch_max_turns"] is True
    assert kwargs["dispatch_max_turns"] is None


def test_update_project_mutually_exclusive_turns(capsys):
    """--dispatch-max-turns and --clear-dispatch-max-turns are mutually exclusive."""
    parser = _make_parser()
    project_id = str(uuid.uuid4())
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "update-project",
                project_id,
                "--dispatch-max-turns",
                "100",
                "--clear-dispatch-max-turns",
            ]
        )
    assert exc_info.value.code == 2


def test_update_project_dispatch_out_of_range(capsys):
    """update-project rejects out-of-range --dispatch-max-turns (exit 1)."""
    args = argparse.Namespace(
        project_id=str(uuid.uuid4()),
        name=None,
        description=None,
        status=None,
        area=None,
        git_origin=None,
        kb_project_ref=None,
        repo_mode=None,
        workspace_repos=None,
        dispatch_max_turns=5,  # below MIN_TURNS=10
        clear_dispatch_max_turns=False,
        dispatch_timeout_minutes=None,
        clear_dispatch_timeout_minutes=False,
        plan_dispatch_agent=None,
        clear_plan_dispatch_agent=False,
        build_dispatch_agent=None,
        clear_build_dispatch_agent=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_update_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "dispatch_max_turns" in captured.err


def test_update_project_backend_error(monkeypatch, capsys):
    """update-project exits 1 with 'Error:' on stderr when backend raises."""
    fake_backend = AsyncMock()
    fake_backend.update_project.side_effect = RuntimeError("update failed")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(
        project_id=str(uuid.uuid4()),
        name="X",
        description=None,
        status=None,
        area=None,
        git_origin=None,
        kb_project_ref=None,
        repo_mode=None,
        workspace_repos=None,
        dispatch_max_turns=None,
        clear_dispatch_max_turns=False,
        dispatch_timeout_minutes=None,
        clear_dispatch_timeout_minutes=False,
        plan_dispatch_agent=None,
        clear_plan_dispatch_agent=False,
        build_dispatch_agent=None,
        clear_build_dispatch_agent=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_update_project(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# share-project
# ---------------------------------------------------------------------------


def test_share_project_happy_path(monkeypatch, capsys):
    """share-project emits the returned member dict as JSON."""
    member = _make_member(email="alice@example.com")
    fake_backend = AsyncMock()
    fake_backend.add_project_member.return_value = member
    project_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(project_id=project_id, email="alice@example.com")
    _cmd_share_project(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["email"] == "alice@example.com"
    fake_backend.add_project_member.assert_called_once_with(
        _FAKE_USER_ID, project_id, "alice@example.com"
    )


def test_share_project_backend_error(monkeypatch, capsys):
    """share-project exits 1 with 'Error:' on stderr when backend raises."""
    fake_backend = AsyncMock()
    fake_backend.add_project_member.side_effect = RuntimeError("user not found")

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_share_project(argparse.Namespace(project_id="proj-1", email="x@x.com"))

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# unshare-project
# ---------------------------------------------------------------------------


def test_unshare_project_happy_path(monkeypatch, capsys):
    """unshare-project emits {\"ok\": true} as JSON."""
    fake_backend = AsyncMock()
    fake_backend.remove_project_member.return_value = None
    project_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    args = argparse.Namespace(project_id=project_id, email="alice@example.com")
    _cmd_unshare_project(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data == {"ok": True}
    fake_backend.remove_project_member.assert_called_once_with(
        _FAKE_USER_ID, project_id, "alice@example.com"
    )


# ---------------------------------------------------------------------------
# list-project-members
# ---------------------------------------------------------------------------


def test_list_project_members_happy_path(monkeypatch, capsys):
    """list-project-members emits the members list as JSON."""
    members = [_make_member(email="a@a.com"), _make_member(email="b@b.com")]
    fake_backend = AsyncMock()
    fake_backend.list_project_members.return_value = members
    project_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "agent_gtd.cli_commands.projects.backend_session",
        _fake_session(fake_backend),
    )

    _cmd_list_project_members(argparse.Namespace(project_id=project_id))

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 2
    fake_backend.list_project_members.assert_called_once_with(_FAKE_USER_ID, project_id)


# ---------------------------------------------------------------------------
# register() — subparser registration
# ---------------------------------------------------------------------------


def test_register_adds_six_subcommands():
    """register() adds exactly the six expected subcommands to the parser."""
    parser = _make_parser()
    # All six subcommands should be parseable without errors.
    project_id = str(uuid.uuid4())
    for cmd in [
        ["list-projects"],
        ["add-project", "My Project"],
        ["update-project", project_id],
        ["share-project", project_id, "a@a.com"],
        ["unshare-project", project_id, "a@a.com"],
        ["list-project-members", project_id],
    ]:
        ns = parser.parse_args(cmd)
        assert callable(ns.func), f"{cmd[0]} handler not set"
