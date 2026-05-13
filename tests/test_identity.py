"""Unit tests for actor identity helpers (pure functions, no DB)."""

import pytest

from agent_gtd.identity import compute_lead_attribution, compute_run_attribution


@pytest.mark.parametrize("mode", ["build", "plan", "manage"])
def test_compute_run_attribution_modes(mode):
    result = compute_run_attribution(mode, "abc12345-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    assert result == f"claude-{mode}-abc12345"


def test_compute_run_attribution_truncates_to_8():
    result = compute_run_attribution("build", "a" * 36)
    assert result == "claude-build-aaaaaaaa"
    assert len(result.split("-")[-1]) == 8


def test_compute_lead_attribution():
    result = compute_lead_attribution("11223344-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    assert result == "claude-lead-11223344"


def test_compute_lead_attribution_truncates_to_8():
    result = compute_lead_attribution("b" * 36)
    assert result == "claude-lead-bbbbbbbb"
