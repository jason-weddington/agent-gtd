"""Transport-agnostic domain exceptions for Agent GTD.

Routes map these to HTTP status codes; MCP tools map them to ToolError.
"""

from typing import Any


class AgentGTDError(Exception):
    """Base exception for Agent GTD domain errors."""

    def __init__(self, detail: str = "") -> None:
        """Initialize with a human-readable detail message."""
        self.detail = detail
        super().__init__(detail)


class NotFoundError(AgentGTDError):
    """Entity not found or not owned by user."""

    def __init__(self, entity_type: str = "Entity", entity_id: str = "") -> None:
        """Initialize with the entity type and optional ID."""
        self.entity_type = entity_type
        self.entity_id = entity_id
        msg = (
            f"{entity_type} not found: {entity_id}"
            if entity_id
            else f"{entity_type} not found"
        )
        super().__init__(msg)


class VersionConflictError(AgentGTDError):
    """Optimistic lock failure — version mismatch."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        expected: int,
        actual: int,
    ) -> None:
        """Initialize with version details for the conflict."""
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Version conflict on {entity_type} {entity_id}: "
            f"expected {expected}, got {actual}"
        )


class AlreadyClaimedError(AgentGTDError):
    """Item is already claimed by another agent."""

    def __init__(self, item_id: str, claimed_by: str) -> None:
        """Initialize with the item ID and current claimant."""
        self.item_id = item_id
        self.claimed_by = claimed_by
        super().__init__(f"Item {item_id} already claimed by {claimed_by}")


class NotRegisteredError(AgentGTDError):
    """MCP tool called before register_agent."""

    def __init__(self) -> None:
        """Initialize with a fixed message."""
        super().__init__("Agent not registered — call register_agent first")


class RunActiveError(AgentGTDError):
    """A dispatch run is already active for this item."""

    def __init__(self, item_id: str, run_id: str) -> None:
        """Initialize with the item and existing run IDs."""
        self.item_id = item_id
        self.run_id = run_id
        super().__init__(f"Item {item_id} already has an active run: {run_id}")


class WaveItemLockedError(AgentGTDError):
    """Item is locked by an active wave run and cannot be dispatched."""

    def __init__(self, item_id: str, wave_run_id: str) -> None:
        """Initialize with the item ID and the wave run that holds the lock."""
        self.item_id = item_id
        self.wave_run_id = wave_run_id
        super().__init__(
            f"Item {item_id} is locked by wave {wave_run_id} — "
            "dispatch is blocked until the wave completes or is halted"
        )


class ValidationError(AgentGTDError):
    """A domain validation rule was violated."""

    def __init__(self, detail: str) -> None:
        """Initialize with a human-readable detail message."""
        super().__init__(detail)


class BlockersUnresolvedError(AgentGTDError):
    """Item has unresolved blockers that prevent this action."""

    def __init__(self, action: str, blockers: list[dict[str, str]]) -> None:
        """Initialize with the blocked action and list of unresolved blockers."""
        self.action = action
        self.blockers = blockers  # [{"id": ..., "title": ..., "status": ...}, ...]
        count = len(blockers)
        items_str = ", ".join(f"'{b['title']}' ({b['status']})" for b in blockers)
        super().__init__(
            f"Cannot {action}: {count} unresolved blocker(s) — {items_str}"
        )


class LegalityContractError(AgentGTDError):
    """One or more items failed the wave legality contract.

    ``failures`` is a list of per-item dicts:
    ``[{"item_id": str, "title": str, "failures": list[str]}, ...]``
    """

    def __init__(self, failures: list[dict[str, Any]]) -> None:
        """Initialize with a list of per-item failure dicts.

        Args:
            failures: List of ``{item_id, title, failures: list[str]}`` dicts.
        """
        self.failures = failures
        count = len(failures)
        summary = "; ".join(
            f"{str(f.get('item_id', ''))[:8]} ({str(f.get('title', ''))[:40]}): "
            f"{', '.join(str(x) for x in (f.get('failures') or []))}"
            for f in failures
        )
        super().__init__(f"Legality contract failed for {count} item(s) — {summary}")
