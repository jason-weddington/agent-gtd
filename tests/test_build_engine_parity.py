"""Guard the hand-maintained copies of the build-engine names against drift.

The MCP tool Literals and the frontend lists are written out by hand; these
tests fail when any of them diverges from ``agent_gtd.models.BuildEngine``.
"""

from __future__ import annotations

import inspect
import re
import typing
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agent_gtd import mcp_server
from agent_gtd.models import BuildEngine

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]


def _expected() -> set[str]:
    return {m.value for m in BuildEngine}


def test_build_engine_has_twelve_members() -> None:
    assert len(_expected()) == 12


@pytest.mark.parametrize("fn", [mcp_server.add_item, mcp_server.update_item])
def test_mcp_build_engine_literal_matches_enum(fn: Callable[..., object]) -> None:
    ann = inspect.signature(fn).parameters["build_engine"].annotation
    lit = next(a for a in typing.get_args(ann) if a is not type(None))
    assert set(typing.get_args(lit)) == _expected() | {""}


def test_frontend_types_build_engine_union_matches_enum() -> None:
    text = (ROOT / "frontend/src/types.ts").read_text()
    match = re.search(r"export type BuildEngine =(.*?)\nexport ", text, re.S)
    assert match is not None
    vals = re.findall(r"'([^']+)'", match.group(1))
    assert len(vals) == 12
    assert len(set(vals)) == 12
    assert set(vals) == _expected()


def test_frontend_build_engine_options_match_enum() -> None:
    text = (ROOT / "frontend/src/engineLabels.ts").read_text()
    match = re.search(
        r"export const BUILD_ENGINE_OPTIONS[^=]*=\s*\[(.*?)\n\]", text, re.S
    )
    assert match is not None
    vals = re.findall(r"value: '([^']+)'", match.group(1))
    assert len(vals) == 12
    assert len(set(vals)) == 12
    assert set(vals) == _expected()


def test_build_engine_is_shared_protocol_enum() -> None:
    import agent_gtd_dispatch_protocol

    from agent_gtd import models

    assert models.BuildEngine is agent_gtd_dispatch_protocol.BuildEngine
