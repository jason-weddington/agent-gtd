"""Unit tests for actor identity helpers (pure functions, no DB)."""

import pytest

from agent_gtd.identity import (
    compute_lead_attribution,
    compute_run_attribution,
    get_current_actor_attribution,
)


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


# --- get_current_actor_attribution ---


def test_get_current_actor_attribution_no_email_no_env():
    """No human_email and no env var returns 'human' (backward compat)."""
    result = get_current_actor_attribution()
    assert result == "human"


def test_get_current_actor_attribution_with_email(monkeypatch):
    """human_email is returned when AGENT_GTD_AGENT_NAME is not set."""
    monkeypatch.delenv("AGENT_GTD_AGENT_NAME", raising=False)
    result = get_current_actor_attribution(human_email="alice@example.com")
    assert result == "alice@example.com"


def test_get_current_actor_attribution_env_overrides_email(monkeypatch):
    """AGENT_GTD_AGENT_NAME takes precedence over human_email."""
    monkeypatch.setenv("AGENT_GTD_AGENT_NAME", "claude-plan-abc12345")
    result = get_current_actor_attribution(human_email="alice@example.com")
    assert result == "claude-plan-abc12345"


def test_get_current_actor_attribution_none_email_returns_human(monkeypatch):
    """human_email=None falls back to 'human' (backward compat)."""
    monkeypatch.delenv("AGENT_GTD_AGENT_NAME", raising=False)
    result = get_current_actor_attribution(human_email=None)
    assert result == "human"
