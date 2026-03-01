"""Transport-agnostic domain exceptions for Agent GTD.

Routes map these to HTTP status codes; MCP tools map them to ToolError.
"""


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
