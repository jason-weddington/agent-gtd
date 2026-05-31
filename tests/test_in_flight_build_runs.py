"""Tests for the inFlightBuildRuns computed field on rollout read endpoints.

Covers AC-5:
  (a) rollout with a running child build -> inFlightBuildRuns contains
      {runId, itemId, status}.
  (b) rollout whose only child build is terminal -> empty list.
  (c) terminal-set classification is correct for each claude_runs status value.

Both GET /api/rollouts/{id} and GET /api/rollouts?status=running are tested.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _make_user(db: Any, email: str | None = None) -> str:
    """Insert a user row and return its ID."""
    from agent_gtd.auth import hash_password

    user_id = str(uuid.uuid4())
    now = _now()
    email = email or f"{user_id[:8]}@test.com"
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        email,
        hash_password("pass"),
        now,
    )
    return user_id


async def _make_project(db: Any, user_id: str) -> str:
    """Insert a project row and return its ID."""
    project_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Test Project",
        now,
        now,
    )
    return project_id


async def _make_item(db: Any, user_id: str, project_id: str) -> str:
    """Insert a GTD item row and return its ID."""
    item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        "Test Item",
        "active",
        now,
        now,
    )
    return item_id


async def _make_rollout(
    db: Any, user_id: str, project_id: str, *, status: str = "running"
) -> str:
    """Insert an autonomous_rollouts row and return its ID."""
    rollout_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, started_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rollout_id,
        project_id,
        user_id,
        status,
        now,
        now,
        now,
    )
    return rollout_id


async def _make_claude_run(
    db: Any,
    user_id: str,
    project_id: str,
    item_id: str,
    *,
    run_status: str,
    rollout_id: str | None = None,
) -> str:
    """Insert a claude_runs row and return its ID."""
    run_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  workspace_dir, max_turns, mode, rollout_id, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        run_id,
        item_id,
        project_id,
        user_id,
        run_status,
        "feat/test",
        "/tmp/workspace",  # noqa: S108
        100,
        "build",
        rollout_id,
        now,
        now,
    )
    return run_id


async def _make_rollout_item(
    db: Any,
    rollout_id: str,
    item_id: str,
    *,
    status: str = "dispatched",
    claude_run_id: str | None = None,
) -> None:
    """Insert a rollout_items row, optionally linking a claude_run."""
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status, claude_run_id)"
        " VALUES ($1, $2, $3, $4)",
        rollout_id,
        item_id,
        status,
        claude_run_id,
    )


# ---------------------------------------------------------------------------
# Fixture: auth + DB shortcut
# ---------------------------------------------------------------------------


@pytest.fixture
async def ctx(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, Any]:
    """Provide authenticated user, project, and db handle."""
    from agent_gtd.database import get_db

    db = await get_db()
    me_resp = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    project_id = await _make_project(db, user_id)
    return {
        "db": db,
        "user_id": user_id,
        "project_id": project_id,
        "headers": auth_headers,
    }


# ---------------------------------------------------------------------------
# AC-5a: Running child build appears in inFlightBuildRuns
# ---------------------------------------------------------------------------


class TestInFlightBuildRunsGetSingle:
    """GET /api/rollouts/{id} returns inFlightBuildRuns."""

    async def test_running_child_build_in_flight(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """A dispatched item with a running run appears in inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status="running",
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="dispatched", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "inFlightBuildRuns" in data
        in_flight = data["inFlightBuildRuns"]
        assert len(in_flight) == 1
        entry = in_flight[0]
        assert entry["runId"] == run_id
        assert entry["itemId"] == item_id
        assert entry["status"] == "running"

    async def test_pending_child_build_in_flight(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """A dispatched item with a pending run appears in inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status="pending",
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="dispatched", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["inFlightBuildRuns"]) == 1
        assert resp.json()["inFlightBuildRuns"][0]["status"] == "pending"

    async def test_cloning_child_build_in_flight(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """A dispatched item with a cloning run appears in inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status="cloning",
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="dispatched", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["inFlightBuildRuns"]) == 1
        assert resp.json()["inFlightBuildRuns"][0]["status"] == "cloning"

    # -----------------------------------------------------------------------
    # AC-5b: Terminal child build -> empty
    # -----------------------------------------------------------------------

    @pytest.mark.parametrize(
        "terminal_status",
        ["success", "failed", "cancelled", "timeout"],
    )
    async def test_terminal_child_build_empty(
        self,
        client: AsyncClient,
        ctx: dict[str, Any],
        terminal_status: str,
    ) -> None:
        """A run with a terminal status does NOT appear in inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status=terminal_status,
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="completed", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "inFlightBuildRuns" in data
        assert data["inFlightBuildRuns"] == [], (
            f"Expected empty inFlightBuildRuns for terminal status {terminal_status!r}"
        )

    async def test_no_dispatched_items_empty(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """A rollout with no dispatched child runs returns an empty list."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        # rollout_item exists but has no claude_run_id
        await _make_rollout_item(
            db, rollout_id, item_id, status="pending", claude_run_id=None
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["inFlightBuildRuns"] == []

    async def test_mixed_runs_only_non_terminal_included(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """With two items, only the one with a non-terminal run appears."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")

        # Item A: running -> should appear
        item_a = await _make_item(db, user_id, project_id)
        run_a = await _make_claude_run(
            db, user_id, project_id, item_a, run_status="running", rollout_id=rollout_id
        )
        await _make_rollout_item(
            db, rollout_id, item_a, status="dispatched", claude_run_id=run_a
        )

        # Item B: success -> should NOT appear
        item_b = await _make_item(db, user_id, project_id)
        run_b = await _make_claude_run(
            db, user_id, project_id, item_b, run_status="success", rollout_id=rollout_id
        )
        await _make_rollout_item(
            db, rollout_id, item_b, status="completed", claude_run_id=run_b
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        in_flight = resp.json()["inFlightBuildRuns"]
        assert len(in_flight) == 1
        assert in_flight[0]["runId"] == run_a
        assert in_flight[0]["itemId"] == item_a


# ---------------------------------------------------------------------------
# List endpoint: GET /api/rollouts?status=running
# ---------------------------------------------------------------------------


class TestInFlightBuildRunsList:
    """GET /api/rollouts?status=running includes inFlightBuildRuns per rollout."""

    async def test_list_includes_in_flight_runs(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """Rollouts returned by the list endpoint carry inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status="running",
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="dispatched", claude_run_id=run_id
        )

        resp = await client.get(
            "/api/rollouts", params={"status": "running"}, headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        # Find our rollout
        rollout = next(r for r in data if r["id"] == rollout_id)
        assert "inFlightBuildRuns" in rollout
        in_flight = rollout["inFlightBuildRuns"]
        assert len(in_flight) == 1
        assert in_flight[0]["runId"] == run_id
        assert in_flight[0]["itemId"] == item_id
        assert in_flight[0]["status"] == "running"

    async def test_list_empty_in_flight_when_no_active_runs(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """Rollout with no active runs shows empty inFlightBuildRuns in list."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status="success",
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="completed", claude_run_id=run_id
        )

        resp = await client.get(
            "/api/rollouts", params={"status": "running"}, headers=headers
        )
        assert resp.status_code == 200
        rollout = next(r for r in resp.json() if r["id"] == rollout_id)
        assert rollout["inFlightBuildRuns"] == []

    async def test_list_without_status_filter_also_has_field(
        self, client: AsyncClient, ctx: dict[str, Any]
    ) -> None:
        """Unfiltered list endpoint also carries inFlightBuildRuns."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")

        resp = await client.get("/api/rollouts", headers=headers)
        assert resp.status_code == 200
        rollout = next(r for r in resp.json() if r["id"] == rollout_id)
        assert "inFlightBuildRuns" in rollout
        assert rollout["inFlightBuildRuns"] == []


# ---------------------------------------------------------------------------
# AC-5c: Terminal classification for every LocalRunStatus value
# ---------------------------------------------------------------------------


class TestTerminalRunStatusClassification:
    """Verify the terminal-vs-non-terminal boundary for all known run statuses."""

    @pytest.mark.parametrize("run_status", ["pending", "cloning", "running"])
    async def test_non_terminal_statuses_appear(
        self,
        client: AsyncClient,
        ctx: dict[str, Any],
        run_status: str,
    ) -> None:
        """Non-terminal statuses (pending/cloning/running) are included."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status=run_status,
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="dispatched", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        in_flight = resp.json()["inFlightBuildRuns"]
        assert len(in_flight) == 1, (
            f"Status {run_status!r} should be non-terminal (in-flight)"
        )
        assert in_flight[0]["status"] == run_status

    @pytest.mark.parametrize(
        "run_status", ["success", "failed", "cancelled", "timeout"]
    )
    async def test_terminal_statuses_excluded(
        self,
        client: AsyncClient,
        ctx: dict[str, Any],
        run_status: str,
    ) -> None:
        """Terminal statuses (success/failed/cancelled/timeout) are excluded."""
        db, user_id, project_id, headers = (
            ctx["db"],
            ctx["user_id"],
            ctx["project_id"],
            ctx["headers"],
        )
        rollout_id = await _make_rollout(db, user_id, project_id, status="running")
        item_id = await _make_item(db, user_id, project_id)
        run_id = await _make_claude_run(
            db,
            user_id,
            project_id,
            item_id,
            run_status=run_status,
            rollout_id=rollout_id,
        )
        await _make_rollout_item(
            db, rollout_id, item_id, status="completed", claude_run_id=run_id
        )

        resp = await client.get(f"/api/rollouts/{rollout_id}", headers=headers)
        assert resp.status_code == 200
        in_flight = resp.json()["inFlightBuildRuns"]
        msg = f"Status {run_status!r} should be terminal"
        assert in_flight == [], msg
