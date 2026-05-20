"""Tests for pick_dispatch_host in dispatch_router.py."""

from unittest.mock import patch

import pytest

HOST_A = {"id": "a", "url": "http://host-a:8001", "api_key": "keya", "label": "host-a"}
HOST_B = {"id": "b", "url": "http://host-b:8001", "api_key": "keyb", "label": "host-b"}

INFO_ALL_UP_A = {
    "engine": "claude-code",
    "version": "1.9.0",
    "max_concurrent_runs": 10,
    "active_runs": 2,
    "engines": ["claude-code", "claude-code-sonnet"],
    "agents": ["tdd-pair", "code-reviewer"],
}
INFO_ALL_UP_B = {
    "engine": "claude-code",
    "version": "1.9.0",
    "max_concurrent_runs": 8,
    "active_runs": 5,
    "engines": ["claude-code"],
    "agents": ["code-reviewer"],
}


@pytest.mark.asyncio
async def test_all_up_picks_highest_capacity() -> None:
    """All hosts up: picks host with highest (max - active)."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    # A has 8 available, B has 3 available
    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_A, INFO_ALL_UP_B],
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "a"


@pytest.mark.asyncio
async def test_one_down_picks_responding_host() -> None:
    """One host down: picks the responding one."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    async def fake_gather(hosts):
        results = []
        for h in hosts:
            if h["url"] == HOST_A["url"]:
                results.append(None)
            else:
                results.append(INFO_ALL_UP_B)
        return results

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_engine_filter_skips_host_without_engine() -> None:
    """Host without requested engine is skipped."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    info_no_engine = {**INFO_ALL_UP_A, "engines": ["claude-code-haiku"]}

    async def fake_gather(hosts):
        return [info_no_engine, INFO_ALL_UP_B]

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_agent_filter_skips_host_without_agent() -> None:
    """Host without requested agent is skipped."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    info_no_agent = {**INFO_ALL_UP_A, "agents": ["other-agent"]}

    async def fake_gather(hosts):
        return [info_no_agent, INFO_ALL_UP_B]

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name="code-reviewer"
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_all_incompatible_raises_no_compatible_host() -> None:
    """All hosts incompatible: raises NoCompatibleHostError with skip reasons."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    async def fake_gather(hosts):
        return [None, None]

    with (
        patch(
            "agent_gtd.services.dispatch_router._gather_host_info",
            new=fake_gather,
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name=None
        )
    exc = exc_info.value
    assert exc.engine == "claude-code"
    assert len(exc.hosts_checked) == 2
    assert all(h["reason"] == "unreachable" for h in exc.hosts_checked)


@pytest.mark.asyncio
async def test_divergent_cluster_raises_no_compatible_host() -> None:
    """Divergent cluster: host-A has engine X not agent Y; host-B vice versa → error."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    info_engine_x_no_y = {
        **INFO_ALL_UP_A,
        "engines": ["engine-x"],
        "agents": ["some-agent"],
    }
    info_engine_z_agent_y = {
        **INFO_ALL_UP_B,
        "engines": ["engine-z"],
        "agents": ["agent-y"],
    }

    async def fake_gather(hosts):
        return [info_engine_x_no_y, info_engine_z_agent_y]

    with (
        patch(
            "agent_gtd.services.dispatch_router._gather_host_info",
            new=fake_gather,
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B], engine="engine-x", agent_name="agent-y"
        )
    exc = exc_info.value
    assert exc.engine == "engine-x"
    assert exc.agent_name == "agent-y"
    # Both hosts should be in skip reasons
    assert len(exc.hosts_checked) == 2
    reasons = {h["host"]: h["reason"] for h in exc.hosts_checked}
    # host-a has engine-x but not agent-y
    assert "agent-y" in reasons.get("host-a", "")
    # host-b doesn't have engine-x
    assert "engine-x" in reasons.get("host-b", "")
