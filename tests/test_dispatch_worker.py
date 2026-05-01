"""Unit tests for dispatch_worker pure helper functions."""

import pytest

from agent_gtd.dispatch_worker import resolve_agent

# ---------------------------------------------------------------------------
# resolve_agent — parametrized matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,project_plan,project_build,project_agent,global_plan,global_build,global_agent,expected",
    [
        # plan mode: project plan agent wins
        (
            "plan",
            "proj-plan-agent",
            "proj-build-agent",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "proj-plan-agent",
        ),
        # build mode: project build agent wins
        (
            "build",
            "proj-plan-agent",
            "proj-build-agent",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "proj-build-agent",
        ),
        # plan mode: no project plan → global plan wins
        (
            "plan",
            None,
            "proj-build-agent",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "global-plan",
        ),
        # build mode: no project build → global build wins
        (
            "build",
            "proj-plan-agent",
            None,
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "global-build",
        ),
        # plan mode: no project plan or global plan → project generic wins
        (
            "plan",
            None,
            "proj-build-agent",
            "proj-generic",
            "",
            "global-build",
            "global-default",
            "proj-generic",
        ),
        # build mode: no project build or global build → project generic wins
        (
            "build",
            "proj-plan-agent",
            None,
            "proj-generic",
            "global-plan",
            "",
            "global-default",
            "proj-generic",
        ),
        # plan mode: no mode-specific, no project generic → global default wins
        (
            "plan",
            None,
            None,
            None,
            "",
            "",
            "global-default",
            "global-default",
        ),
        # build mode: no mode-specific, no project generic → global default wins
        (
            "build",
            None,
            None,
            None,
            "",
            "",
            "global-default",
            "global-default",
        ),
        # all empty → empty string
        (
            "plan",
            None,
            None,
            None,
            "",
            "",
            "",
            "",
        ),
        (
            "build",
            None,
            None,
            None,
            "",
            "",
            "",
            "",
        ),
        # plan mode: empty string project plan (falsy) → falls through to global plan
        (
            "plan",
            "",
            "proj-build-agent",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "global-plan",
        ),
        # build mode: empty string project build (falsy) → falls through to global build
        (
            "build",
            "proj-plan-agent",
            "",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "global-build",
        ),
        # plan mode: project plan wins over everything
        (
            "plan",
            "plan-winner",
            "proj-build-agent",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "plan-winner",
        ),
        # build mode: project build wins over everything
        (
            "build",
            "proj-plan-agent",
            "build-winner",
            "proj-generic",
            "global-plan",
            "global-build",
            "global-default",
            "build-winner",
        ),
        # plan mode: no plan agents anywhere → project generic fallback
        (
            "plan",
            None,
            None,
            "proj-generic",
            "",
            "",
            "",
            "proj-generic",
        ),
        # build mode: no build agents anywhere → project generic fallback
        (
            "build",
            None,
            None,
            "proj-generic",
            "",
            "",
            "",
            "proj-generic",
        ),
    ],
)
def test_resolve_agent(
    mode: str,
    project_plan: str | None,
    project_build: str | None,
    project_agent: str | None,
    global_plan: str,
    global_build: str,
    global_agent: str,
    expected: str,
) -> None:
    result = resolve_agent(
        mode=mode,
        project_plan_agent=project_plan,
        project_build_agent=project_build,
        project_dispatch_agent=project_agent,
        global_plan_agent=global_plan,
        global_build_agent=global_build,
        global_agent_name=global_agent,
    )
    assert result == expected
