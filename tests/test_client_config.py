"""Tests for the client config resolver (the env file first, then the environment)."""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

import pytest

from agent_gtd import client_config
from agent_gtd.client_config import (
    config_path,
    missing_api_key_message,
    resolve_client_config,
)

SECRET = "agtd_supersecret"  # noqa: S105
URL = "https://board.example.com"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for var in ("AGENT_GTD_URL", "AGENT_GTD_API_KEY", "AGENT_GTD_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    client_config._warned_paths.clear()
    return tmp_path


def _write(path: Path, text: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_file_wins_over_env(monkeypatch, tmp_path):
    _write(
        tmp_path / "xdg/agent-gtd/agent-gtd.env",
        f"AGENT_GTD_URL={URL}\nAGENT_GTD_API_KEY=filekey\n",
    )
    monkeypatch.setenv("AGENT_GTD_URL", "http://env")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "envkey")
    assert resolve_client_config() == (URL, "filekey")


def test_env_used_when_file_missing(monkeypatch):
    monkeypatch.setenv("AGENT_GTD_URL", URL)
    monkeypatch.setenv("AGENT_GTD_API_KEY", "envkey")
    assert resolve_client_config() == (URL, "envkey")


def test_file_used_when_env_unset(tmp_path):
    _write(
        tmp_path / "xdg/agent-gtd/agent-gtd.env",
        f"AGENT_GTD_URL={URL}\nAGENT_GTD_API_KEY={SECRET}\n",
    )
    assert resolve_client_config() == (URL, SECRET)


def test_per_variable_fallthrough_to_env(monkeypatch, tmp_path):
    _write(
        tmp_path / "xdg/agent-gtd/agent-gtd.env",
        f"AGENT_GTD_URL={URL}\nAGENT_GTD_API_KEY=\n",
    )
    monkeypatch.setenv("AGENT_GTD_URL", "http://env")
    monkeypatch.setenv("AGENT_GTD_API_KEY", "envkey")
    assert resolve_client_config() == (URL, "envkey")


def test_home_default_path(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config_path() == tmp_path / ".config/agent-gtd/agent-gtd.env"


def test_config_override(monkeypatch, tmp_path):
    other = _write(tmp_path / "custom.env", f"AGENT_GTD_URL={URL}\n")
    _write(tmp_path / "xdg/agent-gtd/agent-gtd.env", "AGENT_GTD_URL=http://wrong\n")
    monkeypatch.setenv("AGENT_GTD_CONFIG", str(other))
    assert config_path() == other
    assert resolve_client_config() == (URL, "")


def test_parsing_comments_export_quotes(tmp_path):
    _write(
        tmp_path / "xdg/agent-gtd/agent-gtd.env",
        '# comment\n\nOTHER=ignored\nexport AGENT_GTD_URL="https://q.example.com"\n'
        "AGENT_GTD_API_KEY='key with = sign'\n",
    )
    assert resolve_client_config() == ("https://q.example.com", "key with = sign")


def test_missing_file_is_local_mode():
    assert resolve_client_config() == ("", "")


def test_permission_warning(capsys, tmp_path):
    path = _write(
        tmp_path / "xdg/agent-gtd/agent-gtd.env",
        f"AGENT_GTD_API_KEY={SECRET}\n",
        mode=0o644,
    )
    assert resolve_client_config() == ("", SECRET)
    err = capsys.readouterr().err
    assert str(path) in err and "chmod 600" in err
    assert SECRET not in err
    resolve_client_config()
    assert capsys.readouterr().err == ""


def test_no_warning_at_600(capsys, tmp_path):
    _write(tmp_path / "xdg/agent-gtd/agent-gtd.env", f"AGENT_GTD_API_KEY={SECRET}\n")
    resolve_client_config()
    assert capsys.readouterr().err == ""


def test_missing_key_message_names_both_sources(tmp_path):
    msg = missing_api_key_message()
    assert "AGENT_GTD_API_KEY" in msg
    assert str(tmp_path / "xdg/agent-gtd/agent-gtd.env") in msg
