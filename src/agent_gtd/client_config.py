"""Client-side configuration: where the CLI and stdio MCP server find the board.

``AGENT_GTD_URL`` and ``AGENT_GTD_API_KEY`` are resolved per variable, in order:

1. the per-tool env file (``$AGENT_GTD_CONFIG``, else
   ``$XDG_CONFIG_HOME/agent-gtd/agent-gtd.env``, else
   ``~/.config/agent-gtd/agent-gtd.env``), when it sets the variable to a
   non-empty value;
2. the process environment;
3. unset (empty string).

The file wins so that writing it fixes a machine whatever its shell exports.
A dispatch host must therefore NOT have this file in the agent user's home:
the dispatch service hands each run its dispatching user's key through the
environment, and the file would override it.

The file holds plain ``KEY=value`` lines and is parsed, never executed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

URL_VAR = "AGENT_GTD_URL"
API_KEY_VAR = "AGENT_GTD_API_KEY"
_WANTED = (URL_VAR, API_KEY_VAR)

_warned_paths: set[str] = set()


def config_path() -> Path:
    """Return the config file path (it may not exist)."""
    override = os.environ.get("AGENT_GTD_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "agent-gtd" / "agent-gtd.env"


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in _WANTED:
            continue
        values[key] = _unquote(value.strip())
    return values


def _read_file() -> dict[str, str]:
    path = config_path()
    try:
        mode = path.stat().st_mode
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if mode & 0o077 and str(path) not in _warned_paths:
        _warned_paths.add(str(path))
        print(
            f"warning: {path} is readable by group or others; run: chmod 600 {path}",
            file=sys.stderr,
        )
    return _parse(text)


def resolve_client_config() -> tuple[str, str]:
    """Return ``(url, api_key)``; each is ``""`` when unset everywhere."""
    from_file = _read_file()
    url = from_file.get(URL_VAR, "") or os.environ.get(URL_VAR, "")
    key = from_file.get(API_KEY_VAR, "") or os.environ.get(API_KEY_VAR, "")
    return url, key


def missing_api_key_message() -> str:
    """Error text for a missing API key, naming both sources (never values)."""
    return (
        f"{API_KEY_VAR} is required: add it to {config_path()} "
        "or set the environment variable"
    )
