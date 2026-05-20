"""Dispatch host router — selects the best host for a given engine + agent."""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
) -> dict[str, Any]:
    """Select the best dispatch host for the given engine and agent.

    Algorithm:
    1. Poll /info on all hosts concurrently (5s timeout, no cache — real-time).
    2. Filter: skip unreachable hosts, hosts missing the requested engine,
       and (if agent_name set) hosts missing the requested agent.
    3. Rank: pick the host with the most available capacity
       (max_concurrent_runs - active_runs).

    Args:
        hosts: List of host dicts with at least ``url`` and ``label`` keys.
        engine: Required engine name (must be in host's ``engines`` list).
        agent_name: Optional agent name (must be in host's ``agents`` list).

    Returns:
        The winning host dict.

    Raises:
        NoCompatibleHostError: If no host passes the filters.
    """
    infos = await _gather_host_info(hosts)

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for host, info in zip(hosts, infos, strict=False):
        host_label = host.get("label") or host.get("url", "unknown")
        if info is None:
            skipped.append({"host": host_label, "reason": "unreachable"})
            continue
        engines: list[str] = info.get("engines", [])
        if engine not in engines:
            skipped.append(
                {"host": host_label, "reason": f"engine '{engine}' not available"}
            )
            continue
        agents: list[str] = info.get("agents", [])
        if agent_name and agent_name not in agents:
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
