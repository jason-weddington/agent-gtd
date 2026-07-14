"""Tests for pick_dispatch_host in dispatch_router.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
                results.append("unreachable (connection refused)")
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
        return [
            "unreachable (connection refused)",
            "unreachable (connection refused)",
        ]

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
    assert all("connection refused" in h["reason"] for h in exc.hosts_checked)


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


@pytest.mark.asyncio
async def test_fetch_host_info_success() -> None:
    """_fetch_host_info returns parsed JSON dict on HTTP 200 response."""
    from agent_gtd.services.dispatch_router import _fetch_host_info

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"engine": "claude-code", "active_runs": 1}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "agent_gtd.services.dispatch_router.httpx.AsyncClient",
        return_value=mock_ctx,
    ):
        result = await _fetch_host_info("http://host:8001")

    assert result["engine"] == "claude-code"
    assert result["active_runs"] == 1


@pytest.mark.asyncio
async def test_gather_host_info_fetch_error_returns_reason() -> None:
    """_gather_host_info returns a discriminated reason str on fetch failure."""
    from agent_gtd.services.dispatch_router import _gather_host_info

    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        results = await _gather_host_info([HOST_A])

    assert len(results) == 1
    assert isinstance(results[0], str)
    assert "connection refused" in results[0]


# ---------------------------------------------------------------------------
# Targeted dispatch tests (target_host_id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_targeted_host_exact_match() -> None:
    """Targeted host: engine+agent match, capacity available → returns that host."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        return_value=INFO_ALL_UP_A,
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name="tdd-pair",
            target_host_id="a",
        )
    assert selected["id"] == "a"


@pytest.mark.asyncio
async def test_targeted_host_not_found() -> None:
    """target_host_id not in hosts list → raises NotFoundError."""
    from agent_gtd.exceptions import NotFoundError
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    with pytest.raises(NotFoundError) as exc_info:
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="nonexistent",
        )
    assert "nonexistent" in str(exc_info.value)


@pytest.mark.asyncio
async def test_targeted_host_engine_mismatch() -> None:
    """Targeted host: engine not in host's engines → raises NoCompatibleHostError."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    info_no_engine = {**INFO_ALL_UP_A, "engines": ["claude-code-haiku"]}

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            return_value=info_no_engine,
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
        )
    exc = exc_info.value
    assert exc.engine == "claude-code"
    assert len(exc.hosts_checked) == 1
    assert "not available" in exc.hosts_checked[0]["reason"]


@pytest.mark.asyncio
async def test_targeted_host_full() -> None:
    """Targeted host: active_runs >= max_concurrent_runs → raises HostFullError."""
    from agent_gtd.exceptions import HostFullError
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    info_full = {**INFO_ALL_UP_A, "max_concurrent_runs": 5, "active_runs": 5}

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            return_value=info_full,
        ),
        pytest.raises(HostFullError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
        )
    exc = exc_info.value
    assert exc.max_concurrent_runs == 5
    assert "host-a" in exc.host_label


# ---------------------------------------------------------------------------
# exclude_urls tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclude_urls_skips_host() -> None:
    """exclude_urls: host-A excluded → host-B selected."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    async def fake_gather(hosts):  # type: ignore[no-untyped-def]
        return [INFO_ALL_UP_A, INFO_ALL_UP_B]

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            exclude_urls=frozenset({HOST_A["url"]}),
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_all_excluded_raises_no_compatible() -> None:
    """All hosts in exclude_urls → NoCompatibleHostError with both in hosts_checked."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    async def fake_gather(hosts):  # type: ignore[no-untyped-def]
        return [INFO_ALL_UP_A, INFO_ALL_UP_B]

    with (
        patch(
            "agent_gtd.services.dispatch_router._gather_host_info",
            new=fake_gather,
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            exclude_urls=frozenset({HOST_A["url"], HOST_B["url"]}),
        )
    exc = exc_info.value
    assert len(exc.hosts_checked) == 2
    assert all(h["reason"] == "at capacity" for h in exc.hosts_checked)


# ---------------------------------------------------------------------------
# /info fetch-failure discrimination tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_timeout_reports_saturated() -> None:
    """Auto mode: a host whose /info times out reports the saturated reason."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=httpx.TimeoutException("timed out"),
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host([HOST_A], engine="claude-code", agent_name=None)
    exc = exc_info.value
    assert len(exc.hosts_checked) == 1
    assert "saturated" in exc.hosts_checked[0]["reason"]


@pytest.mark.asyncio
async def test_auto_mode_connect_error_reports_connection_refused() -> None:
    """Auto mode: a host refusing connection reports the connection-refused reason."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=httpx.ConnectError("connection refused"),
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host([HOST_A], engine="claude-code", agent_name=None)
    exc = exc_info.value
    assert len(exc.hosts_checked) == 1
    assert "connection refused" in exc.hosts_checked[0]["reason"]


@pytest.mark.asyncio
async def test_auto_mode_mixed_failures_distinct_reasons() -> None:
    """Mixed two-host case: timeout vs connect-refused produce distinct reasons.

    Pins the ordering hazard — a saturated host must be distinguishable from a
    down host, not collapsed into the generic 'request error' wording.
    """
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    async def fake_fetch(url, timeout=5.0):
        if url == HOST_A["url"]:
            raise httpx.TimeoutException("timed out")
        raise httpx.ConnectError("connection refused")

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            new=fake_fetch,
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B], engine="claude-code", agent_name=None
        )
    exc = exc_info.value
    assert len(exc.hosts_checked) == 2
    reasons = {h["host"]: h["reason"] for h in exc.hosts_checked}
    assert "saturated" in reasons["host-a"]
    assert "connection refused" in reasons["host-b"]
    # The two reasons are distinct.
    assert reasons["host-a"] != reasons["host-b"]
    # The timeout reason must NOT be the generic 'request error' wording.
    assert "request error" not in reasons["host-a"]


@pytest.mark.asyncio
async def test_targeted_host_timeout_reports_saturated() -> None:
    """Targeted path: a saturated/slow target reports the timeout reason."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=httpx.TimeoutException("timed out"),
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
        )
    exc = exc_info.value
    assert len(exc.hosts_checked) == 1
    assert "saturated" in exc.hosts_checked[0]["reason"]


@pytest.mark.parametrize(
    ("exc", "expect"),
    [
        (httpx.TimeoutException("t"), "saturated"),
        (httpx.ConnectError("c"), "connection refused"),
        (
            httpx.HTTPStatusError(
                "h",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(503),
            ),
            "HTTP 503",
        ),
        (httpx.RequestError("r"), "request error"),
        (ValueError("bad json"), "invalid /info response"),
    ],
)
def test_classify_info_failure_discriminates(exc, expect):
    """Every branch of _classify_info_failure returns its discriminated reason."""
    from agent_gtd.services.dispatch_router import _classify_info_failure

    assert expect in _classify_info_failure(exc)
