"""Static AST scanner: gate against broad silent-swallow sites in src/."""

import ast
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BROAD_NAMES = frozenset({"Exception", "BaseException"})

SRC_DIR = Path(__file__).parent.parent / "src" / "agent_gtd"

# ---------------------------------------------------------------------------
# Detection helpers (pure, no src imports)
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A detected broad-swallow site."""

    path: str
    lineno: int
    kind: str  # "except" or "suppress"
    text: str


def _is_pass_or_ellipsis(stmt: ast.stmt) -> bool:
    """Return True if *stmt* is a lone ``pass`` or a bare ``...`` expression."""
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _is_broad_type(node: ast.expr | None) -> bool:
    """Return True if *node* is None (bare except) or an ast.Name in _BROAD_NAMES."""
    if node is None:
        return True
    return isinstance(node, ast.Name) and node.id in _BROAD_NAMES


def _is_broad_suppress_call(call: ast.Call) -> bool:
    """Return True if *call* is a broad suppress() call.

    Matches ``suppress(Exception)`` (ast.Name id 'suppress') and
    ``contextlib.suppress(Exception)`` (ast.Attribute attr 'suppress').
    Checks positional args only; kwargs are ignored.
    """
    func = call.func
    is_suppress = (isinstance(func, ast.Name) and func.id == "suppress") or (
        isinstance(func, ast.Attribute) and func.attr == "suppress"
    )
    return is_suppress and any(
        isinstance(arg, ast.Name) and arg.id in _BROAD_NAMES for arg in call.args
    )


def _is_allowlisted(lines: list[str], lineno: int) -> bool:
    """Return True if broad-suppress-ok appears on *lineno* or its predecessor."""
    marker = "broad-suppress-ok"
    return marker in lines[lineno - 1] or (lineno > 1 and marker in lines[lineno - 2])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_broad_swallows(source: str, path: str) -> list[Finding]:
    """Parse *source* and return all non-allowlisted broad-swallow sites.

    Detected patterns
    -----------------
    EXCEPT-HANDLER: ``ast.ExceptHandler`` whose body is exactly one ``pass``
    or ``...`` statement, and whose ``type`` is ``None`` (bare ``except:``)
    or an ``ast.Name`` with id in ``{Exception, BaseException}``.
    Tuple-form handlers are intentionally NOT detected.

    SUPPRESS: a ``with``/``async with`` item whose context expression is an
    ``ast.Call`` matching ``suppress`` or ``contextlib.suppress`` (and
    variants), with any positional arg being an ``ast.Name`` in
    ``{Exception, BaseException}``.  Detection is independent of the
    with-body.

    Allowlist
    ---------
    A site is skipped when the token ``broad-suppress-ok`` appears on the
    flagged node's own source line or on the immediately preceding line.
    The flagged node's line is ``ExceptHandler.lineno`` for the except
    pattern and the suppress ``ast.Call.lineno`` for the suppress pattern.

    SyntaxError in *source* produces an empty result (file skipped).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if (
                len(node.body) == 1
                and _is_pass_or_ellipsis(node.body[0])
                and _is_broad_type(node.type)
                and not _is_allowlisted(lines, node.lineno)
            ):
                findings.append(
                    Finding(
                        path=path,
                        lineno=node.lineno,
                        kind="except",
                        text=f"broad silent except at {path}:{node.lineno}",
                    )
                )
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Call)
                    and _is_broad_suppress_call(ctx)
                    and not _is_allowlisted(lines, ctx.lineno)
                ):
                    findings.append(
                        Finding(
                            path=path,
                            lineno=ctx.lineno,
                            kind="suppress",
                            text=f"broad suppress at {path}:{ctx.lineno}",
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_broad_swallows_in_src() -> None:
    """Full src scan: assert zero non-allowlisted broad swallows in src/agent_gtd/."""
    all_findings: list[Finding] = []
    for py_file in sorted(SRC_DIR.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        all_findings.extend(find_broad_swallows(source, str(py_file)))

    assert all_findings == [], (
        "Broad silent-swallow sites found in src/agent_gtd/ — narrow the "
        "exception type or add a '# broad-suppress-ok: ...' comment:\n"
        + "\n".join(f"  {f.path}:{f.lineno} ({f.kind})" for f in all_findings)
    )


def test_narrow_suppress_not_flagged() -> None:
    """Narrow exception types in suppress() must never be flagged.

    Exercises the attribute form ``contextlib.suppress(X)`` for all real src
    sites; also exercises the asyncio attribute-arg form.
    """
    narrow_cases = [
        # Attribute form: contextlib.suppress(ValueError) — event_bus.py:39
        "with contextlib.suppress(ValueError):\n    pass\n",
        # Attribute form: contextlib.suppress(asyncio.QueueEmpty) — event_bus.py:98
        "with contextlib.suppress(asyncio.QueueEmpty):\n    pass\n",
        # Attribute form: contextlib.suppress(asyncio.QueueFull) — event_bus.py:100
        "with contextlib.suppress(asyncio.QueueFull):\n    pass\n",
        # Attribute form: contextlib.suppress(FileNotFoundError) — attachment_storage.py
        "with contextlib.suppress(FileNotFoundError):\n    pass\n",
    ]
    for src in narrow_cases:
        result = find_broad_swallows(src, "<test>")
        assert result == [], f"False positive for narrow suppress: {src!r}"


def test_non_silent_except_not_flagged() -> None:
    """except Exception: handlers that log, raise, or assign must not be flagged."""
    # Logger call in body — single non-pass statement
    log_src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "try:\n"
        "    pass\n"
        "except Exception:\n"
        "    logger.exception('oops')\n"
    )
    assert find_broad_swallows(log_src, "<test>") == []

    # raise in body
    raise_src = "try:\n    pass\nexcept Exception:\n    raise\n"
    assert find_broad_swallows(raise_src, "<test>") == []

    # assignment in body
    assign_src = "try:\n    pass\nexcept Exception:\n    x = 1\n"
    assert find_broad_swallows(assign_src, "<test>") == []

    # multi-statement body that includes pass — not a lone pass
    multi_src = "try:\n    pass\nexcept Exception:\n    x = 1\n    pass\n"
    assert find_broad_swallows(multi_src, "<test>") == []


def test_broad_swallows_detected() -> None:
    """Self-test: one broad suppress + one broad except (no marker) → 2 findings."""
    source = (
        "import contextlib\n"
        "with contextlib.suppress(Exception):\n"
        "    pass\n"
        "try:\n"
        "    pass\n"
        "except Exception:\n"
        "    pass\n"
    )
    findings = find_broad_swallows(source, "<test>")
    assert len(findings) == 2


def test_allowlist_marker_suppresses_findings() -> None:
    """broad-suppress-ok on the preceding line allowlists the site (→ 0 findings)."""
    # Preceding-line marker for suppress
    suppress_src = (
        "import contextlib\n"
        "# broad-suppress-ok: intentional in test\n"
        "with contextlib.suppress(Exception):\n"
        "    pass\n"
    )
    assert find_broad_swallows(suppress_src, "<test>") == []

    # Preceding-line marker for except
    except_src = (
        "try:\n"
        "    pass\n"
        "# broad-suppress-ok: intentional in test\n"
        "except Exception:\n"
        "    pass\n"
    )
    assert find_broad_swallows(except_src, "<test>") == []

    # Own-line marker for suppress (marker on same line as the with)
    own_line_src = (
        "import contextlib\n"
        "with contextlib.suppress(Exception):  # broad-suppress-ok: inline\n"
        "    pass\n"
    )
    assert find_broad_swallows(own_line_src, "<test>") == []
