"""Dispatch host router — selects the best host for a given engine + agent."""

import asyncio
import logging
from typing import Any

import httpx

from agent_gtd.exceptions import HostFullError, NotFoundError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Host probe
# ---------------------------------------------------------------------------


async def probe_dispatch_host(
    url: str,
    api_key: str,
    timeout: float = 10.0,
) -> None:
    """Probe {url}/info with Bearer auth to verify the host is reachable and valid.

    Validates that the response is HTTP 200, parseable JSON, and contains an
    ``engine`` key.  All failures raise ``ValueError`` with a human-readable
    reason so callers can convert them into user-facing error messages.

    Args:
        url: Base URL of the dispatch host (e.g. ``'https://dispatch.example.com'``).
        api_key: API key for Bearer authentication.
        timeout: Request timeout in seconds (default 10).

    Raises:
        ValueError: With a descriptive reason on any probe failure.
    """
    try:
        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            resp = await client.get(
                f"{url}/info",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
    except httpx.TimeoutException as exc:
        raise ValueError(f"Timed out after {int(timeout)}s") from exc
    except httpx.ConnectError as exc:
        raise ValueError("Connection refused") from exc
    except httpx.RequestError as exc:
        raise ValueError(f"Request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code} {resp.reason_phrase}")

    try:
        data: object = resp.json()
    except Exception as exc:
        raise ValueError("Response is not valid JSON") from exc

    if not isinstance(data, dict) or "engine" not in data:
        raise ValueError("Response missing required field: engine")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NoCompatibleHostError(Exception):
    """No host in the pool is compatible with the requested engine + agent."""

    def __init__(
        self,
        engine: str,
        agent_name: str | None,
        hosts_checked: list[dict[str, str]],
    ) -> None:
        """Initialize with engine, agent_name, and per-host skip reasons."""
        self.engine = engine
        self.agent_name = agent_name
        self.hosts_checked = hosts_checked
        reasons = "; ".join(f"{h['host']}: {h['reason']}" for h in hosts_checked)
        super().__init__(
            f"No compatible host for engine={engine!r} agent={agent_name!r}. "
            f"Checked: {reasons}"
        )


# ---------------------------------------------------------------------------
# /info fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_host_info(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch /info from a dispatch host. No auth required.

    Returns the parsed JSON dict on success.
    Raises httpx exception on failure.
    """
    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        resp = await client.get(f"{url}/info", timeout=timeout)
        resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def _gather_host_info(
    hosts: list[dict[str, Any]],
) -> list[dict[str, Any] | None]:
    """Poll /info on all hosts concurrently. No caching — see commit message.

    Returns a list parallel to hosts; entry is None if host is unreachable/errored.

    The /info call is cheap (~15ms over LAN, ~200 bytes, no auth) and dispatch is
    not high-frequency. Caching here previously caused burst dispatches to pile
    on a single host because active_runs stayed stale within the TTL window.
    Real-time fetch is correct by construction.
    """

    async def _get_info(host: dict[str, Any]) -> dict[str, Any] | None:
        url = host["url"]
        try:
            return await _fetch_host_info(url)
        except Exception:
            logger.warning("Failed to fetch /info from %s", url)
            return None

    results = await asyncio.gather(*[_get_info(h) for h in hosts])
    return list(results)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


async def pick_dispatch_host(
    hosts: list[dict[str, Any]],
    *,
    engine: str,
    agent_name: str | None,
    target_host_id: str | None = None,
) -> dict[str, Any]:
    """Select the best dispatch host for the given engine and agent.

    When ``target_host_id`` is set, the host with that ID is used directly
    (after validation), bypassing capacity ranking.

    Algorithm (auto mode, target_host_id=None):
    1. Poll /info on all hosts concurrently (5s timeout, no cache — real-time).
    2. Filter: skip unreachable hosts, hosts missing the requested engine,
       and (if agent_name set) hosts missing the requested agent.
    3. Rank: pick the host with the most available capacity
       (max_concurrent_runs - active_runs).

    Args:
        hosts: List of host dicts with at least ``url`` and ``label`` keys.
        engine: Required engine name (must be in host's ``engines`` list).
        agent_name: Optional agent name (must be in host's ``agents`` list).
        target_host_id: Optional host UUID to pin this dispatch to a specific
            host. When set, the router validates compatibility and capacity for
            that host only and returns it directly.

    Returns:
        The winning host dict.

    Raises:
        NotFoundError: If target_host_id is set but not found in hosts list.
        NoCompatibleHostError: If target host fails engine/agent validation,
            or if no host passes the filters in auto mode.
        HostFullError: If target host is at maximum capacity.
    """
    if target_host_id is not None:
        # Targeted dispatch: find the host by ID
        target = next((h for h in hosts if h.get("id") == target_host_id), None)
        if target is None:
            raise NotFoundError("DispatchHost", target_host_id)

        host_label = target.get("label") or target.get("url", "unknown")

        # Fetch /info from the targeted host
        try:
            target_info: dict[str, Any] = await _fetch_host_info(target["url"])
        except Exception:
            raise NoCompatibleHostError(
                engine=engine,
                agent_name=agent_name,
                hosts_checked=[{"host": host_label, "reason": "unreachable"}],
            ) from None

        # Validate engine
        engines: list[str] = target_info.get("engines", [])
        if engine not in engines:
            raise NoCompatibleHostError(
                engine=engine,
                agent_name=agent_name,
                hosts_checked=[
                    {
                        "host": host_label,
                        "reason": f"engine '{engine}' not available",
                    }
                ],
            )

        # Validate agent
        agents: list[str] = target_info.get("agents", [])
        if agent_name and agent_name not in agents:
            raise NoCompatibleHostError(
                engine=engine,
                agent_name=agent_name,
                hosts_checked=[
                    {
                        "host": host_label,
                        "reason": f"agent '{agent_name}' not on this host",
                    }
                ],
            )

        # Check capacity
        target_available = target_info.get("max_concurrent_runs", 0) - target_info.get(
            "active_runs", 0
        )
        if target_available <= 0:
            raise HostFullError(
                host_label, int(target_info.get("max_concurrent_runs", 0))
            )

        return target

    infos = await _gather_host_info(hosts)

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for host, info in zip(hosts, infos, strict=False):
        host_label = host.get("label") or host.get("url", "unknown")
        if info is None:
            skipped.append({"host": host_label, "reason": "unreachable"})
            continue
        engines_list: list[str] = info.get("engines", [])
        if engine not in engines_list:
            skipped.append(
                {"host": host_label, "reason": f"engine '{engine}' not available"}
            )
            continue
        agents_list: list[str] = info.get("agents", [])
        if agent_name and agent_name not in agents_list:
            skipped.append(
                {
                    "host": host_label,
                    "reason": f"agent '{agent_name}' not on this host",
                }
            )
            continue
        available = info.get("max_concurrent_runs", 0) - info.get("active_runs", 0)
        entry = dict(info)
        entry["_host"] = host
        entry["_available"] = available
        candidates.append(entry)

    if not candidates:
        raise NoCompatibleHostError(
            engine=engine,
            agent_name=agent_name,
            hosts_checked=skipped,
        )

    best = max(candidates, key=lambda c: c["_available"])
    selected: dict[str, Any] = best["_host"]
    return selected
