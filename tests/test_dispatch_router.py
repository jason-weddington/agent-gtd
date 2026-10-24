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


@pytest.mark.asyncio
async def test_parked_rollout_loops_reduce_available_slots() -> None:
    """max=4, active=1, parked=1 → 2 available slots in candidate ranking."""
    from agent_gtd.services import dispatch_router

    info = {
        **INFO_ALL_UP_A,
        "max_concurrent_runs": 4,
        "active_runs": 1,
        "parked_rollout_loops": 1,
    }
    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        AsyncMock(return_value=[info]),
    ):
        selected = await dispatch_router.pick_dispatch_host(
            [{**HOST_A, "drain_reason": None}],
            engine="claude-code",
            agent_name=None,
        )
    assert selected["id"] == "a"
    assert "(2 available)" in selected["_routing_rationale"]


@pytest.mark.asyncio
async def test_targeted_host_full_counts_parked_rollout_loops() -> None:
    """Targeted: max=1, active=0, parked=1 → HostFullError."""
    from agent_gtd.exceptions import HostFullError
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    info = {
        **INFO_ALL_UP_A,
        "max_concurrent_runs": 1,
        "active_runs": 0,
        "parked_rollout_loops": 1,
    }
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            return_value=info,
        ),
        pytest.raises(HostFullError),
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
        )


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


# ---------------------------------------------------------------------------
# Capability-label filtering (host capability labels vs. required labels)
# ---------------------------------------------------------------------------

HOST_C_TAURI = {
    "id": "c",
    "url": "http://host-c:8001",
    "api_key": "keyc",
    "label": "host-c",
    "capability_labels": ["tauri-linux"],
}


@pytest.mark.asyncio
async def test_label_filter_excludes_only_host_with_capacity() -> None:
    """A host lacking a required label is excluded even as the only candidate.

    Mirrors incident 2 from the design doc: no /info call should even be
    needed to reject HOST_A here — the label filter runs before any network
    call, so HOST_A (no capability_labels) never becomes a candidate despite
    being the only host in the pool.
    """
    from agent_gtd.services.dispatch_router import (
        UnmetCapabilityError,
        pick_dispatch_host,
    )

    with pytest.raises(UnmetCapabilityError) as exc_info:
        await pick_dispatch_host(
            [HOST_A],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"tauri-linux"}),
        )
    exc = exc_info.value
    assert exc.required_labels == ["tauri-linux"]
    assert len(exc.hosts_checked) == 1
    assert exc.hosts_checked[0]["host"] == "host-a"
    assert "tauri-linux" in exc.hosts_checked[0]["reason"]


@pytest.mark.asyncio
async def test_label_filter_passes_matching_host_and_records_rationale() -> None:
    """A host with the required label is a candidate and wins on capacity.

    The winning host dict carries a ``_routing_rationale`` explaining what it
    satisfied — this is what the caller persists on the run record.
    """
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    async def fake_gather(hosts):  # type: ignore[no-untyped-def]
        return [INFO_ALL_UP_A]

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [HOST_C_TAURI],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"tauri-linux"}),
        )
    assert selected["id"] == "c"
    assert "tauri-linux" in selected["_routing_rationale"]
    assert "ranked first on capacity" in selected["_routing_rationale"]


@pytest.mark.asyncio
async def test_label_matching_is_case_insensitive() -> None:
    """A host's differently-cased label still satisfies a lowercase requirement."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    host = {**HOST_C_TAURI, "capability_labels": ["Tauri-Linux"]}

    async def fake_gather(hosts):  # type: ignore[no-untyped-def]
        return [INFO_ALL_UP_A]

    with patch(
        "agent_gtd.services.dispatch_router._gather_host_info",
        new=fake_gather,
    ):
        selected = await pick_dispatch_host(
            [host],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"tauri-linux"}),
        )
    assert selected["id"] == "c"


@pytest.mark.asyncio
async def test_no_required_labels_is_pure_noop() -> None:
    """Explicit empty required_labels behaves exactly like the pre-label path."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_A, INFO_ALL_UP_B],
    ):
        selected = await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset(),
        )
    assert selected["id"] == "a"
    assert "_routing_rationale" in selected


@pytest.mark.asyncio
async def test_pinned_host_missing_label_fails_fast_no_network() -> None:
    """A pin to a host lacking a required label fails before any /info probe.

    Validates the pin rather than bypassing the requirement — pinning names
    which host, not that the requirement no longer applies.
    """
    from agent_gtd.services.dispatch_router import (
        UnmetCapabilityError,
        pick_dispatch_host,
    )

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("must not probe a label-failing pin"),
        ),
        pytest.raises(UnmetCapabilityError) as exc_info,
    ):
        await pick_dispatch_host(
            [HOST_A, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
            required_labels=frozenset({"gpu"}),
        )
    exc = exc_info.value
    assert exc.required_labels == ["gpu"]
    assert exc.hosts_checked[0]["host"] == "host-a"
    assert "gpu" in exc.hosts_checked[0]["reason"]


@pytest.mark.asyncio
async def test_pinned_host_with_required_label_succeeds() -> None:
    """A pin to a host that DOES have the required label still validates and wins."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        return_value=INFO_ALL_UP_A,
    ):
        selected = await pick_dispatch_host(
            [HOST_C_TAURI, HOST_B],
            engine="claude-code",
            agent_name=None,
            target_host_id="c",
            required_labels=frozenset({"tauri-linux"}),
        )
    assert selected["id"] == "c"
    assert "explicitly pinned" in selected["_routing_rationale"]
    assert "tauri-linux" in selected["_routing_rationale"]


# ---------------------------------------------------------------------------
# effective_required_labels (project + item union semantics)
# ---------------------------------------------------------------------------


def test_effective_required_labels_unions_project_and_item() -> None:
    """The effective requirement is the union — an item adds, never relaxes."""
    from agent_gtd.services.dispatch_service import effective_required_labels

    project = {"required_labels": ["camera-data"]}
    item = {"required_labels": ["tauri-linux"]}
    assert effective_required_labels(project, item) == ["camera-data", "tauri-linux"]


def test_effective_required_labels_tolerates_raw_json_text() -> None:
    """Raw DB-row dicts (JSON text, not yet decoded) are handled transparently."""
    from agent_gtd.services.dispatch_service import effective_required_labels

    project = {"required_labels": '["camera-data"]'}
    item = {"required_labels": '["tauri-linux", "camera-data"]'}
    assert effective_required_labels(project, item) == ["camera-data", "tauri-linux"]


def test_effective_required_labels_no_requirement_is_empty() -> None:
    """An un-labelled project and item produce an empty requirement — a no-op."""
    from agent_gtd.services.dispatch_service import effective_required_labels

    assert effective_required_labels({}, {}) == []
    assert effective_required_labels(None, None) == []


# ---------------------------------------------------------------------------
# Host drain (docs/host-drain.md) — drained hosts are refused, never routed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_draining_error_message_single_entry() -> None:
    """AC1: single drained host names the host and quotes the reason verbatim."""
    from agent_gtd.services.dispatch_router import HostDrainingError

    exc = HostDrainingError(
        hosts_checked=[{"host": "host-b", "reason": "rolling deploy 2.0.2"}]
    )
    text = str(exc)
    assert "host-b" in text
    assert "rolling deploy 2.0.2" in text
    assert "is draining" in text
    assert "retry when the host returns to rotation" in text
    assert exc.hosts_checked == [{"host": "host-b", "reason": "rolling deploy 2.0.2"}]


@pytest.mark.asyncio
async def test_host_draining_error_message_multi_entry() -> None:
    """AC1: two drained hosts join as 'label: reason' with '; ' separators."""
    from agent_gtd.services.dispatch_router import HostDrainingError

    exc = HostDrainingError(
        hosts_checked=[
            {"host": "host-b", "reason": "rolling deploy 2.0.2"},
            {"host": "host-d", "reason": "kernel upgrade"},
        ]
    )
    text = str(exc)
    assert "host-b" in text
    assert "host-d" in text
    assert "rolling deploy 2.0.2" in text
    assert "kernel upgrade" in text
    for text in (str(exc),):
        assert "try another host" not in text
        assert "re-route" not in text
        assert "no compatible host" not in text


@pytest.mark.asyncio
async def test_host_draining_error_never_says_try_another_host() -> None:
    """AC1: the single-entry message must not nudge toward re-routing."""
    from agent_gtd.services.dispatch_router import HostDrainingError

    exc = HostDrainingError(
        hosts_checked=[{"host": "host-b", "reason": "rolling deploy 2.0.2"}]
    )
    text = str(exc)
    assert "try another host" not in text
    assert "re-route" not in text
    assert "no compatible host" not in text


@pytest.mark.asyncio
async def test_pinned_drained_host_refused_before_labels_no_probe() -> None:
    """AC2: a drained pin is refused before labels and before any /info probe."""
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        pick_dispatch_host,
    )

    host = {
        "id": "r7-uuid",
        "label": "host-b",
        "url": "http://host-b:8100",
        "api_key": "k",
        "capability_labels": [],
        "drain_reason": "rolling deploy 2.0.2",
    }
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("must not probe a draining pin"),
        ),
        pytest.raises(HostDrainingError) as exc_info,
    ):
        await pick_dispatch_host(
            [host],
            engine="claude-code",
            agent_name=None,
            target_host_id="r7-uuid",
            required_labels=frozenset({"camera-data"}),
        )
    text = str(exc_info.value)
    assert "host-b" in text
    assert "rolling deploy 2.0.2" in text


@pytest.mark.asyncio
async def test_auto_all_drained_raises_host_draining_not_unmet_capability() -> None:
    """AC3a: a pool whose only host is drained reports drained, not unmet labels."""
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        pick_dispatch_host,
    )

    host = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
        "capability_labels": ["camera-data"],
        "drain_reason": "rolling deploy 2.0.2",
    }
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("must not probe a fully-drained pool"),
        ),
        pytest.raises(HostDrainingError) as exc_info,
    ):
        await pick_dispatch_host(
            [host],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"camera-data"}),
        )
    text = str(exc_info.value)
    assert "host-a" in text
    assert "rolling deploy 2.0.2" in text


@pytest.mark.asyncio
async def test_empty_pool_still_raises_no_compatible_host() -> None:
    """AC3b: zero hosts, zero drained — still the empty-pool NoCompatibleHostError."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    with pytest.raises(NoCompatibleHostError) as exc_info:
        await pick_dispatch_host([], engine="claude-code", agent_name=None)
    assert exc_info.value.hosts_checked == []


@pytest.mark.asyncio
async def test_mixed_drain_and_label_reports_drained_capable_host() -> None:
    """AC4: only capable host drained → HostDrainingError, not UnmetCapabilityError."""
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        pick_dispatch_host,
    )

    drained_capable = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
        "capability_labels": ["camera-data"],
        "drain_reason": "rolling deploy 2.0.2",
    }
    up_unlabeled = {
        "id": "b",
        "url": "http://host-b:8001",
        "api_key": "keyb",
        "label": "host-b",
        "capability_labels": [],
    }
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("must not probe when the pool refuses"),
        ),
        pytest.raises(HostDrainingError) as exc_info,
    ):
        await pick_dispatch_host(
            [drained_capable, up_unlabeled],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"camera-data"}),
        )
    text = str(exc_info.value)
    assert "host-a" in text
    assert "rolling deploy 2.0.2" in text


@pytest.mark.asyncio
async def test_mixed_drain_and_label_unmet_lists_drained_first() -> None:
    """AC4: no label-qualified drained host → UnmetCapabilityError, drained first."""
    from agent_gtd.services.dispatch_router import (
        UnmetCapabilityError,
        pick_dispatch_host,
    )

    drained_unlabeled = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
        "capability_labels": [],
        "drain_reason": "rolling deploy 2.0.2",
    }
    up_unlabeled = {
        "id": "b",
        "url": "http://host-b:8001",
        "api_key": "keyb",
        "label": "host-b",
        "capability_labels": [],
    }
    with pytest.raises(UnmetCapabilityError) as exc_info:
        await pick_dispatch_host(
            [drained_unlabeled, up_unlabeled],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"camera-data"}),
        )
    checked = exc_info.value.hosts_checked
    assert checked[0] == {"host": "host-a", "reason": "draining: rolling deploy 2.0.2"}
    assert checked[1]["host"] == "host-b"


@pytest.mark.asyncio
async def test_auto_partial_drain_drained_entry_is_first_in_hosts_checked() -> None:
    """AC5: drained hosts precede label/network skips in NoCompatibleHostError."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    drained = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
        "capability_labels": ["camera-data"],
        "drain_reason": "rolling deploy 2.0.2",
    }
    up_wrong_engine = {
        "id": "b",
        "url": "http://host-b:8001",
        "api_key": "keyb",
        "label": "host-b",
        "capability_labels": ["camera-data"],
    }
    info_b_no_engine = {**INFO_ALL_UP_B, "engines": ["other-engine"]}

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=[info_b_no_engine],
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [drained, up_wrong_engine],
            engine="claude-code",
            agent_name=None,
            required_labels=frozenset({"camera-data"}),
        )
    checked = exc_info.value.hosts_checked
    assert checked[0] == {"host": "host-a", "reason": "draining: rolling deploy 2.0.2"}


@pytest.mark.asyncio
async def test_drained_host_skipped_even_when_winning_on_capacity() -> None:
    """AC6: a drained host is skipped even when it would win on capacity."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    drained = {**HOST_A, "drain_reason": "rolling deploy 2.0.2"}
    # Only the remaining (undrained) host is probed — A has 10 free, B has 3.
    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_B],
    ):
        selected = await pick_dispatch_host(
            [drained, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_pinned_empty_drain_reason_still_refused() -> None:
    """AC7a: drain_reason='' is a drained host in the pinned branch too."""
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        pick_dispatch_host,
    )

    host = {**HOST_A, "drain_reason": ""}
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("must not probe a draining pin"),
        ),
        pytest.raises(HostDrainingError) as exc_info,
    ):
        await pick_dispatch_host(
            [host],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
        )
    assert "host-a" in str(exc_info.value)


@pytest.mark.asyncio
async def test_auto_empty_drain_reason_skips_with_verbatim_empty_reason() -> None:
    """AC7b: '' is non-NULL → skipped, with 'draining: ' as the verbatim reason."""
    from agent_gtd.services.dispatch_router import (
        NoCompatibleHostError,
        pick_dispatch_host,
    )

    drained = {**HOST_A, "drain_reason": ""}
    up_wrong_engine = {
        "id": "b",
        "url": "http://host-b:8001",
        "api_key": "keyb",
        "label": "host-b",
    }
    info_b_no_engine = {**INFO_ALL_UP_B, "engines": ["other-engine"]}

    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=[info_b_no_engine],
        ),
        pytest.raises(NoCompatibleHostError) as exc_info,
    ):
        await pick_dispatch_host(
            [drained, up_wrong_engine], engine="claude-code", agent_name=None
        )
    assert exc_info.value.hosts_checked[0]["reason"] == "draining: "


@pytest.mark.asyncio
async def test_auto_empty_drain_reason_undrained_host_still_wins() -> None:
    """AC7b: pool of one ''-drained and one undrained → the undrained host wins."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    drained = {**HOST_A, "drain_reason": ""}
    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_B],
    ):
        selected = await pick_dispatch_host(
            [drained, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "b"


@pytest.mark.asyncio
async def test_drain_reason_none_routes_exactly_as_before() -> None:
    """AC7c: an explicitly None drain_reason routes exactly like the pre-drain code."""
    from agent_gtd.services.dispatch_router import pick_dispatch_host

    host_a = {**HOST_A, "drain_reason": None}
    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_A, INFO_ALL_UP_B],
    ):
        selected = await pick_dispatch_host(
            [host_a, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "a"


@pytest.mark.asyncio
async def test_missing_drain_reason_key_logs_tripwire_but_routes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC8: a host row without the drain_reason KEY routes but logs one ERROR."""
    import logging

    from agent_gtd.services.dispatch_router import pick_dispatch_host

    host = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
    }  # drain_reason KEY absent entirely
    with patch(
        "agent_gtd.services.dispatch_router._fetch_host_info",
        side_effect=[INFO_ALL_UP_A],
    ):
        selected = await pick_dispatch_host(
            [host], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "a"  # fail-open: still routes
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and "host-a" in r.getMessage()
    ]
    assert len(errors) == 1
    assert "drain_reason missing from host row" in errors[0].getMessage()


@pytest.mark.asyncio
async def test_no_override_combination_reaches_a_drained_host() -> None:
    """AC14: no argument combination routes work to a drained host."""
    from agent_gtd.services.dispatch_router import (
        HostDrainingError,
        pick_dispatch_host,
    )

    drained = {
        "id": "a",
        "url": "http://host-a:8001",
        "api_key": "keya",
        "label": "host-a",
        "capability_labels": ["camera-data"],
        "drain_reason": "rolling deploy 2.0.2",
    }
    with (
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=AssertionError("no override may reach a drained host"),
        ),
        pytest.raises(HostDrainingError),
    ):
        await pick_dispatch_host(
            [drained],
            engine="claude-code",
            agent_name=None,
            target_host_id="a",
            required_labels=frozenset({"camera-data"}),
            exclude_urls=frozenset(),
        )


@pytest.mark.asyncio
async def test_drain_partition_emits_info_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC15: a partial drain logs which hosts the drain filter excluded."""
    import logging

    from agent_gtd.services.dispatch_router import pick_dispatch_host

    drained = {**HOST_A, "drain_reason": "rolling deploy 2.0.2"}
    with (
        caplog.at_level(logging.INFO, logger="agent_gtd.services.dispatch_router"),
        patch(
            "agent_gtd.services.dispatch_router._fetch_host_info",
            side_effect=[INFO_ALL_UP_B],
        ),
    ):
        selected = await pick_dispatch_host(
            [drained, HOST_B], engine="claude-code", agent_name=None
        )
    assert selected["id"] == "b"
    infos = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "Drain filter excluded" in r.getMessage()
        and "host-a" in r.getMessage()
        and "rolling deploy 2.0.2" in r.getMessage()
    ]
    assert len(infos) == 1
