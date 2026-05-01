"""Unit tests for dispatch_worker pure helper functions."""

import pytest

from agent_gtd.dispatch_worker import resolve_agent

# ---------------------------------------------------------------------------
# resolve_agent — parametrized matrix (5-arg form: no legacy fallback fields)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,project_plan,project_build,global_plan,global_build,expected",
    [
        # plan mode: project plan agent wins
        (
            "plan",
            "proj-plan-agent",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "proj-plan-agent",
        ),
        # build mode: project build agent wins
        (
            "build",
            "proj-plan-agent",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "proj-build-agent",
        ),
        # plan mode: no project plan → global plan wins
        (
            "plan",
            None,
            "proj-build-agent",
            "global-plan",
            "global-build",
            "global-plan",
        ),
        # build mode: no project build → global build wins
        (
            "build",
            "proj-plan-agent",
            None,
            "global-plan",
            "global-build",
            "global-build",
        ),
        # plan mode: no project plan or global plan → empty string
        ("plan", None, "proj-build-agent", "", "global-build", ""),
        # build mode: no project build or global build → empty string
        ("build", "proj-plan-agent", None, "global-plan", "", ""),
        # plan mode: all empty → empty string
        ("plan", None, None, "", "", ""),
        # build mode: all empty → empty string
        ("build", None, None, "", "", ""),
        # plan mode: empty string project plan (falsy) → falls through to global plan
        (
            "plan",
            "",
            "proj-build-agent",
            "global-plan",
            "global-build",
            "global-plan",
        ),
        # build mode: empty string project build (falsy) → falls through to global build
        (
            "build",
            "proj-plan-agent",
            "",
            "global-plan",
            "global-build",
            "global-build",
        ),
    ],
)
def test_resolve_agent(
    mode: str,
    project_plan: str | None,
    project_build: str | None,
    global_plan: str,
    global_build: str,
    expected: str,
) -> None:
    result = resolve_agent(
        mode=mode,
        project_plan_agent=project_plan,
        project_build_agent=project_build,
        global_plan_agent=global_plan,
        global_build_agent=global_build,
    )
    assert result == expected
