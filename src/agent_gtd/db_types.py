"""Shared type definitions for Agent GTD."""

from typing import Any, Protocol


class DbPool(Protocol):
    """Protocol for database connection pools.

    Both asyncpg.Pool and SqlitePool satisfy this structurally.
    """

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        """Fetch all matching rows."""
        ...

    async def fetchrow(self, sql: str, *args: Any) -> Any | None:
        """Fetch a single row, or None."""
        ...

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute a SQL statement."""
        ...

    def acquire(self) -> Any:
        """Acquire a connection (context manager)."""
        ...

    async def close(self) -> None:
        """Close the pool."""
        ...
