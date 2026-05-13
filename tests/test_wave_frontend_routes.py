"""Tests for wave frontend API routes.

Covers:
- GET /api/projects/{project_id}/active-wave (AC-22)
- GET /api/wave-runs/{id}/events (AC-23)
- POST /api/wave-runs/{id}/resume (AC-24)
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers (shared with test_wave_executor.py pattern)
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _make_user(db: Any, email: str = "wave-test@example.com") -> str:
    """Insert a user row and return its ID."""
    from agent_gtd.auth import hash_password

    user_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        email,
        hash_password("pass"),
        now,
    )
    return user_id


async def _make_project(db: Any, user_id: str, name: str = "Wave Test Project") -> str:
    """Insert a project row and return its ID."""
    project_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        name,
        now,
        now,
    )
    return project_id


async def _make_item(
    db: Any, user_id: str, project_id: str, title: str = "Task"
) -> str:
    """Insert a GTD item and return its ID."""
    item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user_id,
        title,
        "next_action",
        now,
        now,
    )
    return item_id


async def _make_wave_run(
    db: Any,
    user_id: str,
    project_id: str,
    status: str = "running",
    halt_reason: str | None = None,
) -> str:
    """Insert a wave_run row and return its ID."""
    wave_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_wave_runs"
        " (id, project_id, lead_user_id, status, halt_reason,"
        " started_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        wave_id,
        project_id,
        user_id,
        status,
        halt_reason,
        now,
        now,
        now,
    )
    return wave_id


async def _make_wave_item(
    db: Any, wave_run_id: str, item_id: str, status: str = "pending"
) -> None:
    """Insert a wave_plan_items row."""
    await db.execute(
        "INSERT INTO wave_plan_items (wave_run_id, item_id, status)"
        " VALUES ($1, $2, $3)",
        wave_run_id,
        item_id,
        status,
    )


async def _make_wave_event(
    db: Any,
    wave_run_id: str,
    kind: str = "item_dispatched",
    actor: str = "manager",
    seq: int = 1,
) -> str:
    """Insert a wave_events row and return its ID."""
    event_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO wave_events (id, wave_run_id, seq, ts, kind, actor, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        event_id,
        wave_run_id,
        seq,
        now,
        kind,
        actor,
        json.dumps({"test": True}),
    )
    return event_id


async def _make_wave_plan(
    db: Any, wave_run_id: str, nodes: list[str], edges: list[dict[str, str]]
) -> str:
    """Insert a wave_plans row and return its ID."""
    plan_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO wave_plans"
        " (id, wave_run_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        wave_run_id,
        1,
        json.dumps(nodes),
        json.dumps(edges),
        "test-model",
        _now(),
    )
    return plan_id


# ---------------------------------------------------------------------------
# Fixture: wave with two items
# ---------------------------------------------------------------------------


@pytest.fixture
async def wave_setup(client: AsyncClient, auth_headers: dict[str, str]):
    """Provide a running wave with one item for testing.

    Yields dict with: wave_run_id, item_id, user_id, project_id, db, headers.
    """
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("wave-ui@example.com", "pass123")
    token = create_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = await _make_project(db, user.id)
    item_id = await _make_item(db, user.id, project_id)
    wave_run_id = await _make_wave_run(db, user.id, project_id, status="running")
    await _make_wave_item(db, wave_run_id, item_id, status="dispatched")
    await _make_wave_plan(db, wave_run_id, [item_id], [])

    yield {
        "wave_run_id": wave_run_id,
        "item_id": item_id,
        "user_id": user.id,
        "project_id": project_id,
        "db": db,
        "headers": headers,
    }


# ---------------------------------------------------------------------------
# AC-22: GET /api/projects/{project_id}/active-wave
# ---------------------------------------------------------------------------


class TestGetActiveWave:
    async def test_returns_running_wave(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Active running wave returns 200 with progress counts."""
        resp = await client.get(
            f"/api/projects/{wave_setup['project_id']}/active-wave",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == wave_setup["wave_run_id"]
        assert data["status"] == "running"
        assert data["total_count"] == 1
        assert data["done_count"] == 0

    async def test_404_when_no_active_wave(
        self, client: AsyncClient, auth_headers: dict[str, str], project_id: str
    ) -> None:
        """Returns 404 when no active wave exists for the project."""
        resp = await client.get(
            f"/api/projects/{project_id}/active-wave",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_counts_done_items_correctly(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """done_count reflects completed and skipped items."""
        db = wave_setup["db"]
        wave_run_id = wave_setup["wave_run_id"]
        project_id = wave_setup["project_id"]
        user_id = wave_setup["user_id"]

        # Add a second item (completed)
        item2 = await _make_item(db, user_id, project_id, "Task 2")
        await _make_wave_item(db, wave_run_id, item2, status="completed")

        # Add a third item (skipped)
        item3 = await _make_item(db, user_id, project_id, "Task 3")
        await _make_wave_item(db, wave_run_id, item3, status="skipped")

        resp = await client.get(
            f"/api/projects/{project_id}/active-wave",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 3
        assert data["done_count"] == 2

    async def test_returns_halted_wave(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Halted wave (non-old) is returned as active."""
        from agent_gtd.database import get_db

        db = await get_db()
        # Get the user_id from auth_headers by calling /api/auth/me
        me_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]

        proj_id = await _make_project(db, user_id, "Halted Project")
        item_id = await _make_item(db, user_id, proj_id)
        wave_id = await _make_wave_run(
            db, user_id, proj_id, status="halted", halt_reason="test failure"
        )
        await _make_wave_item(db, wave_id, item_id, status="halted")

        resp = await client.get(
            f"/api/projects/{proj_id}/active-wave",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halted"
        assert data["halt_reason"] == "test failure"

    async def test_returns_404_for_nonexistent_project(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Non-existent project returns 404."""
        resp = await client.get(
            "/api/projects/no-such-project/active-wave",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_requires_auth(self, client: AsyncClient, project_id: str) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.get(f"/api/projects/{project_id}/active-wave")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# AC-23: GET /api/wave-runs/{id}/events
# ---------------------------------------------------------------------------


class TestGetWaveEvents:
    async def test_returns_events_newest_first(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Events are ordered newest first (seq DESC)."""
        db = wave_setup["db"]
        wave_run_id = wave_setup["wave_run_id"]
        headers = wave_setup["headers"]

        await _make_wave_event(db, wave_run_id, kind="item_dispatched", seq=1)
        await _make_wave_event(db, wave_run_id, kind="item_outcome", seq=2)

        resp = await client.get(
            f"/api/wave-runs/{wave_run_id}/events",
            headers=headers,
        )
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[0]["seq"] == 2  # newest first
        assert events[1]["seq"] == 1

    async def test_respects_limit_param(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """limit query param caps the number of events returned."""
        db = wave_setup["db"]
        wave_run_id = wave_setup["wave_run_id"]
        headers = wave_setup["headers"]

        for i in range(5):
            await _make_wave_event(db, wave_run_id, seq=i + 1)

        resp = await client.get(
            f"/api/wave-runs/{wave_run_id}/events?limit=3",
            headers=headers,
        )
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 3

    async def test_empty_feed_returns_empty_list(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Wave with no events returns empty list."""
        resp = await client.get(
            f"/api/wave-runs/{wave_setup['wave_run_id']}/events",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["events"] == []

    async def test_404_for_unknown_wave(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Unknown wave_run_id returns 404."""
        resp = await client.get(
            "/api/wave-runs/no-such-wave/events",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_requires_auth(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.get(f"/api/wave-runs/{wave_setup['wave_run_id']}/events")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# AC-24: POST /api/wave-runs/{id}/resume
# ---------------------------------------------------------------------------


class TestResumeWave:
    @pytest.fixture
    async def halted_wave(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> dict[str, Any]:
        """Provide a halted wave with one halted item."""
        from agent_gtd.database import get_db

        db = await get_db()
        me_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]

        proj_id = await _make_project(db, user_id, "Halted Resume Project")
        item_id = await _make_item(db, user_id, proj_id)
        wave_id = await _make_wave_run(
            db, user_id, proj_id, status="halted", halt_reason="merge failure"
        )
        await _make_wave_item(db, wave_id, item_id, status="halted")
        await _make_wave_plan(db, wave_id, [item_id], [])

        return {
            "wave_run_id": wave_id,
            "item_id": item_id,
            "project_id": proj_id,
            "user_id": user_id,
            "db": db,
            "headers": auth_headers,
        }

    async def test_resume_transitions_to_running(
        self, client: AsyncClient, halted_wave: dict[str, Any]
    ) -> None:
        """Resume sets wave status back to 'running'."""
        resp = await client.post(
            f"/api/wave-runs/{halted_wave['wave_run_id']}/resume",
            json={"answer": "Please retry the failing CI step"},
            headers=halted_wave["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    async def test_resume_posts_comment(
        self, client: AsyncClient, halted_wave: dict[str, Any]
    ) -> None:
        """Resume posts the answer as a comment on the project."""
        resp = await client.post(
            f"/api/wave-runs/{halted_wave['wave_run_id']}/resume",
            json={"answer": "My answer text"},
            headers=halted_wave["headers"],
        )
        assert resp.status_code == 200

        # Verify comment was created
        comments_resp = await client.get(
            f"/api/projects/{halted_wave['project_id']}/comments",
            headers=halted_wave["headers"],
        )
        assert comments_resp.status_code == 200
        comments = comments_resp.json()
        assert any("My answer text" in c["content_markdown"] for c in comments)

    async def test_resume_transitions_halted_items_to_ready(
        self, client: AsyncClient, halted_wave: dict[str, Any]
    ) -> None:
        """Resume transitions halted items with no predecessors to 'ready'."""
        db = halted_wave["db"]
        wave_run_id = halted_wave["wave_run_id"]
        item_id = halted_wave["item_id"]

        resp = await client.post(
            f"/api/wave-runs/{wave_run_id}/resume",
            json={"answer": "Let's go"},
            headers=halted_wave["headers"],
        )
        assert resp.status_code == 200

        row = await db.fetchrow(
            "SELECT status FROM wave_plan_items"
            " WHERE wave_run_id = $1 AND item_id = $2",
            wave_run_id,
            item_id,
        )
        assert row is not None
        assert row["status"] == "ready"

    async def test_resume_409_when_not_halted(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Resume returns 409 when wave is not halted."""
        resp = await client.post(
            f"/api/wave-runs/{wave_setup['wave_run_id']}/resume",
            json={"answer": "This should fail"},
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 409

    async def test_resume_requires_auth(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.post(
            f"/api/wave-runs/{wave_setup['wave_run_id']}/resume",
            json={"answer": "nope"},
        )
        assert resp.status_code in (401, 403)

    async def test_resume_returns_progress_counts(
        self, client: AsyncClient, halted_wave: dict[str, Any]
    ) -> None:
        """Resume response includes total_count and done_count."""
        resp = await client.post(
            f"/api/wave-runs/{halted_wave['wave_run_id']}/resume",
            json={"answer": "Let's resume"},
            headers=halted_wave["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_count" in data
        assert "done_count" in data
        assert data["total_count"] == 1
        assert data["done_count"] == 0
