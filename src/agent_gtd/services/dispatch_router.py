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


class UnmetCapabilityError(Exception):
    """No host in the pool satisfies the effective capability-label requirement.

    Raised BEFORE engine/agent/capacity are ever consulted — a host missing a
    required label is never a candidate, regardless of what else it offers.
    Deliberately distinct from ``NoCompatibleHostError`` so the failure names
    the actual routing problem (which labels went unsatisfied, on which
    hosts) instead of a generic "no compatible host" message. This is the
    guardrail against an agent confidently misdiagnosing a routing failure
    (missing dataset / missing toolchain) as something else from the inside.
    """

    def __init__(
        self,
        required_labels: list[str],
        hosts_checked: list[dict[str, str]],
    ) -> None:
        """Initialize with the unmet required labels and per-host reasons."""
        self.required_labels = required_labels
        self.hosts_checked = hosts_checked
        reasons = "; ".join(f"{h['host']}: {h['reason']}" for h in hosts_checked)
        super().__init__(
            f"No host satisfies required capability label(s) {required_labels!r}. "
            f"Checked: {reasons}"
        )


class HostDrainingError(Exception):
    """Every candidate host is draining — dispatch must wait, not re-route.

    Raised BEFORE engine/agent/capacity are ever consulted: a host with a
    non-NULL ``drain_reason`` is out of rotation whatever capability labels
    it carries, so it is partitioned out of the pool before anything else.
    The message deliberately names the host(s) and quotes the drain reason
    and NEVER nudges toward re-routing — a caller pinning for capability
    affinity cannot fall back to auto-routing (the data lives only on the
    drained host), so "try another host" would send it somewhere the work
    cannot run. The honest reading is: wait for the host to come back.
    """

    def __init__(self, hosts_checked: list[dict[str, str]]) -> None:
        """Initialize with the per-host drain entries ({'host', 'reason'})."""
        self.hosts_checked = hosts_checked
        if len(hosts_checked) == 1:
            entry = hosts_checked[0]
            # Skip entries carry a "draining: " prefix (for NoCompatibleHostError
            # hosts_checked); strip it so the single-host message reads naturally.
            reason = entry["reason"].removeprefix("draining: ")
            message = (
                f"Dispatch host '{entry['host']}' is draining: {reason}. "
                "Dispatch refused; retry when the host returns to rotation."
            )
        else:
            reasons = "; ".join(f"{h['host']}: {h['reason']}" for h in hosts_checked)
            message = (
                f"All dispatch hosts are draining: {reasons}. "
                "Retry when a host returns to rotation."
            )
        super().__init__(message)


# ---------------------------------------------------------------------------
# Capability-label matching
# ---------------------------------------------------------------------------


def _norm_label(label: str) -> str:
    """Normalize a label for comparison: lowercase, stripped."""
    return label.strip().lower()


def _host_capability_labels(host: dict[str, Any]) -> frozenset[str]:
    """Return a host's normalized capability labels (operator-set, static)."""
    return frozenset(
        _norm_label(str(label)) for label in host.get("capability_labels") or []
    )


def _missing_labels(required: frozenset[str], host: dict[str, Any]) -> frozenset[str]:
    """Return the subset of ``required`` this host's labels do not cover."""
    return required - _host_capability_labels(host)


def _pin_rationale(host_label: str, required: frozenset[str]) -> str:
    """Build the routing-rationale string for an explicitly pinned host."""
    if required:
        return (
            f"explicitly pinned to '{host_label}' "
            f"(satisfies required label(s): {', '.join(sorted(required))})"
        )
    return f"explicitly pinned to '{host_label}'"


def _auto_rationale(host_label: str, required: frozenset[str], available: int) -> str:
    """Build the routing-rationale string for an auto-ranked host."""
    if required:
        return (
            f"'{host_label}' satisfied required label(s) "
            f"{', '.join(sorted(required))} and ranked first on capacity "
            f"({available} available)"
        )
    return f"'{host_label}' ranked first on capacity ({available} available)"


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


def _classify_info_failure(exc: Exception) -> str:
    """Classify a caught /info-fetch exception into a discriminated skip reason.

    The wording strings are a soft value; the DISCRIMINATION and the isinstance
    branch ORDER are load-bearing. Branches are ordered most-specific-first
    because httpx.TimeoutException and httpx.ConnectError are both subclasses
    of httpx.RequestError (via TransportError), and httpx.HTTPStatusError
    derives from httpx.HTTPError (NOT RequestError) — so the specific
    TimeoutException/ConnectError/HTTPStatusError branches MUST precede the
    generic httpx.RequestError branch, and the bare-Exception catch-all MUST be
    strictly last. A RequestError-first ordering would silently collapse every
    timeout and connect-refused into the generic bucket and defeat the entire
    discrimination.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "no /info response within 5s (host may be at capacity / saturated)"
    if isinstance(exc, httpx.ConnectError):
        return "unreachable (connection refused)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"/info returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "unreachable (request error)"
    return "invalid /info response"


async def _gather_host_info(
    hosts: list[dict[str, Any]],
) -> list[dict[str, Any] | str]:
    """Poll /info on all hosts concurrently. No caching — see commit message.

    Returns a list parallel to ``hosts``: each entry is the parsed /info dict on
    success, or a discriminated failure-reason string (the output of
    ``_classify_info_failure``) on error — parallel to the hosts list.

    The /info call is cheap (~15ms over LAN, ~200 bytes, no auth) and dispatch is
    not high-frequency. Caching here previously caused burst dispatches to pile
    on a single host because active_runs stayed stale within the TTL window.
    Real-time fetch is correct by construction.
    """

    async def _get_info(host: dict[str, Any]) -> dict[str, Any] | str:
        url = host["url"]
        try:
            return await _fetch_host_info(url)
        except Exception as exc:
            logger.warning("Failed to fetch /info from %s", url)
            return _classify_info_failure(exc)

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
    exclude_urls: frozenset[str] | None = None,
    required_labels: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Select the best dispatch host for the given engine and agent.

    When ``target_host_id`` is set, the host with that ID is used directly
    (after validation), bypassing capacity ranking.

    Algorithm (auto mode, target_host_id=None):
    0. Partition out hosts with a non-NULL ``drain_reason`` (checked before
       capability labels and before any network call — a drained host is
       not a candidate whatever labels it carries). If no host remains,
       raise :class:`HostDrainingError` naming each drained host and its
       reason. Hosts partitioned out are carried into
       ``NoCompatibleHostError.hosts_checked`` with reason
       ``"draining: <reason>"`` when routing later fails.
    1. Filter by capability label next, using the static, operator-set
       ``capability_labels`` on each host record — no network call needed.
       A host missing any label in ``required_labels`` is never a candidate,
       regardless of capacity. Empty/unset ``required_labels`` is a pure
       no-op (every host proceeds to step 2, matching pre-label behaviour).
       If the label filter empties the pool but a drained host WAS
       label-qualified, :class:`HostDrainingError` is raised instead — the
       pool's only capable host is draining, which asks the caller to wait.
    2. Poll /info on the label-qualified hosts concurrently (5s timeout, no
       cache — real-time).
    3. Filter: skip unreachable hosts, hosts missing the requested engine,
       hosts in ``exclude_urls`` (at-capacity hosts excluded by caller),
       and (if agent_name set) hosts missing the requested agent.
    4. Rank: pick the host with the most available capacity
       (max_concurrent_runs - active_runs).

    The winning host dict carries an extra ``_routing_rationale`` key (a
    human-readable string explaining why it was chosen) for the caller to
    persist on the run record — a transient key, not a column on the host
    record itself.

    Args:
        hosts: List of host dicts with at least ``url`` and ``label`` keys.
            ``capability_labels`` (list[str], operator-set) defaults to
            empty when absent.
        engine: Required engine name (must be in host's ``engines`` list).
        agent_name: Optional agent name (must be in host's ``agents`` list).
        target_host_id: Optional host UUID to pin this dispatch to a specific
            host. When set, the router validates compatibility and capacity for
            that host only and returns it directly.
        exclude_urls: Optional set of host URLs to skip (hosts known to be at
            capacity). Excluded hosts appear in ``NoCompatibleHostError.hosts_checked``
            with reason ``"at capacity"``. Only used in auto mode.
        required_labels: Optional set of capability labels every candidate
            host must have (the effective union of a project's and an
            item's required labels). A pin that lacks a required label
            fails the same way an auto-routed dispatch would — pinning
            names which host, not that the requirement no longer applies.

    Returns:
        The winning host dict (with a transient ``_routing_rationale`` key).

    Raises:
        NotFoundError: If target_host_id is set but not found in hosts list.
        HostDrainingError: If the pinned host is draining, or if every host
            in the pool is draining, or if the label filter empties the
            pool while a label-qualified drained host exists. Checked
            before capability labels and before any network call; there is
            no override.
        UnmetCapabilityError: If no host (or the pinned host) satisfies
            ``required_labels``. Raised before any engine/agent/capacity
            check — a labels failure is a distinct, more specific failure
            than a generic "no compatible host".
        NoCompatibleHostError: If target host fails engine/agent validation,
            or if no label-qualified host passes the filters in auto mode.
        HostFullError: If target host is at maximum capacity.
    """
    effective_required = frozenset(
        _norm_label(label) for label in (required_labels or ())
    )

    if target_host_id is not None:
        # Targeted dispatch: find the host by ID
        target = next((h for h in hosts if h.get("id") == target_host_id), None)
        if target is None:
            raise NotFoundError("DispatchHost", target_host_id)

        host_label = target.get("label") or target.get("url", "unknown")

        # Drain is absolute and is checked BEFORE capability labels: a host
        # with a non-NULL drain_reason is out of rotation, so a drained pin
        # is refused before ANY network call — fail fast with the drain
        # reason, never a generic routing error (docs/host-drain.md).
        if "drain_reason" not in target:
            logger.error(
                "drain_reason missing from host row for %s — drain filter "
                "silently inactive; schema/SELECT wiring is broken",
                host_label,
            )
        target_drain_reason = target.get("drain_reason")
        if target_drain_reason is not None:
            raise HostDrainingError(
                hosts_checked=[{"host": host_label, "reason": str(target_drain_reason)}]
            )

        # Capability labels are operator-set and static — validate before any
        # network call. Pinning names which host, not that the requirement no
        # longer applies, so a pinned host lacking a required label fails
        # fast with the same named-requirement error as auto-routing would.
        missing = _missing_labels(effective_required, target)
        if missing:
            raise UnmetCapabilityError(
                required_labels=sorted(effective_required),
                hosts_checked=[
                    {
                        "host": host_label,
                        "reason": (
                            f"missing required label(s): {', '.join(sorted(missing))}"
                        ),
                    }
                ],
            )

        # Fetch /info from the targeted host
        try:
            target_info: dict[str, Any] = await _fetch_host_info(target["url"])
        except Exception as exc:
            raise NoCompatibleHostError(
                engine=engine,
                agent_name=agent_name,
                hosts_checked=[
                    {"host": host_label, "reason": _classify_info_failure(exc)}
                ],
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
        target_available = (
            target_info.get("max_concurrent_runs", 0)
            - target_info.get("active_runs", 0)
            - target_info.get("parked_rollout_loops", 0)
        )
        if target_available <= 0:
            raise HostFullError(
                host_label, int(target_info.get("max_concurrent_runs", 0))
            )

        target["_routing_rationale"] = _pin_rationale(host_label, effective_required)
        return target

    # Auto mode, step 0: partition out drained hosts — before capability
    # labels, before any network call. A host with a non-NULL drain_reason
    # is not a candidate whatever labels it carries, and a pool whose only
    # capable host is drained must report *drained* (wait) rather than
    # *unmet capability* (fix the requirement) — those call for opposite
    # responses (docs/host-drain.md).
    drain_skipped: list[dict[str, str]] = []
    drained_hosts: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for host in hosts:
        host_label = host.get("label") or host.get("url", "unknown")
        if "drain_reason" not in host:
            # Fail-open but LOUD: a missing key reads as not-drained, which
            # is exactly the silent no-op a missing column or a SELECT that
            # omits drain_reason produces. No test can catch it (test DBs
            # come from _SCHEMA_STATEMENTS; production upgrades through the
            # suppressed _MIGRATIONS runner), so make it the loudest log
            # line the router can emit.
            logger.error(
                "drain_reason missing from host row for %s — drain filter "
                "silently inactive; schema/SELECT wiring is broken",
                host_label,
            )
            remaining.append(host)
            continue
        drain_reason = host.get("drain_reason")
        if drain_reason is not None:
            drained_hosts.append(host)
            drain_skipped.append(
                {"host": host_label, "reason": f"draining: {drain_reason}"}
            )
        else:
            remaining.append(host)
    if drain_skipped and not remaining:
        raise HostDrainingError(drain_skipped)
    if drain_skipped:
        logger.info(
            "Drain filter excluded host(s) %s: %s; routing among %d remaining",
            ", ".join(e["host"] for e in drain_skipped),
            "; ".join(e["reason"] for e in drain_skipped),
            len(remaining),
        )
    hosts = remaining

    # Auto mode: filter by capability label first — before any network call —
    # so a host missing a required label is never a candidate regardless of
    # capacity, and the failure (if total) names the unmet labels rather than
    # falling through to a generic "no compatible host" message.
    label_skipped: list[dict[str, str]] = []
    if effective_required:
        label_ok_hosts: list[dict[str, Any]] = []
        for host in hosts:
            host_label = host.get("label") or host.get("url", "unknown")
            missing = _missing_labels(effective_required, host)
            if missing:
                label_skipped.append(
                    {
                        "host": host_label,
                        "reason": (
                            f"missing required label(s): {', '.join(sorted(missing))}"
                        ),
                    }
                )
            else:
                label_ok_hosts.append(host)
        if not label_ok_hosts:
            # Drain composes with labels here: if some drained host WAS
            # label-qualified, the pool's only capable host is draining —
            # report *drained* (wait), not *unmet capability* (fix labels),
            # because those call for opposite responses.
            if drain_skipped:
                qualified_drained = [
                    h
                    for h in drained_hosts
                    if _missing_labels(effective_required, h) == frozenset()
                ]
                if qualified_drained:
                    raise HostDrainingError(
                        [
                            {
                                "host": h.get("label") or h.get("url", "unknown"),
                                "reason": f"draining: {h['drain_reason']}",
                            }
                            for h in qualified_drained
                        ]
                    )
                # No drained host qualified either — the unmet-label failure
                # must still list the drained hosts, drained entries first.
                raise UnmetCapabilityError(
                    required_labels=sorted(effective_required),
                    hosts_checked=drain_skipped + label_skipped,
                )
            raise UnmetCapabilityError(
                required_labels=sorted(effective_required),
                hosts_checked=label_skipped,
            )
        hosts = label_ok_hosts

    infos = await _gather_host_info(hosts)

    candidates: list[dict[str, Any]] = []
    # Drained hosts precede label/network skips so NoCompatibleHostError's
    # hosts_checked reads [drained…, label-skipped…, network-stage…].
    skipped: list[dict[str, str]] = list(drain_skipped)
    skipped.extend(label_skipped)

    for host, info in zip(hosts, infos, strict=False):
        host_label = host.get("label") or host.get("url", "unknown")
        if exclude_urls and host.get("url") in exclude_urls:
            skipped.append({"host": host_label, "reason": "at capacity"})
            continue
        if isinstance(info, str):
            skipped.append({"host": host_label, "reason": info})
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
        available = (
            info.get("max_concurrent_runs", 0)
            - info.get("active_runs", 0)
            - info.get("parked_rollout_loops", 0)
        )
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
    host_label = selected.get("label") or selected.get("url", "unknown")
    selected["_routing_rationale"] = _auto_rationale(
        host_label, effective_required, int(best["_available"])
    )
    return selected
