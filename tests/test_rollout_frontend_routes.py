"""Tests for rollout frontend API routes.

Covers:
- GET /api/projects/{project_id}/active-rollout (AC-22)
- GET /api/rollouts/{id}/events (AC-23)
- POST /api/rollouts/{id}/resume (AC-24)
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


async def _make_user(db: Any, email: str = "rollout-test@example.com") -> str:
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


async def _make_rollout(
    db: Any,
    user_id: str,
    project_id: str,
    status: str = "running",
    halt_reason: str | None = None,
) -> str:
    """Insert an autonomous_rollouts row and return its ID."""
    rollout_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, halt_reason,"
        " started_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        rollout_id,
        project_id,
        user_id,
        status,
        halt_reason,
        now,
        now,
        now,
    )
    return rollout_id


async def _make_wave_item(
    db: Any, rollout_id: str, item_id: str, status: str = "pending"
) -> None:
    """Insert a rollout_items row."""
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status) VALUES ($1, $2, $3)",
        rollout_id,
        item_id,
        status,
    )


async def _make_wave_event(
    db: Any,
    rollout_id: str,
    kind: str = "item_dispatched",
    actor: str = "manager",
    seq: int = 1,
) -> str:
    """Insert a rollout_events row and return its ID."""
    event_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO rollout_events (id, rollout_id, seq, ts, kind, actor, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        event_id,
        rollout_id,
        seq,
        now,
        kind,
        actor,
        json.dumps({"test": True}),
    )
    return event_id


async def _make_merge_note_event(
    db: Any,
    rollout_id: str,
    item_id: str,
    note: str,
    seq: int,
) -> str:
    """Insert a merge_note rollout_events row and return its ID."""
    from agent_gtd.services.rollout_service import MERGE_NOTE_EVENT_KIND

    event_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO rollout_events (id, rollout_id, seq, ts, kind, actor, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        event_id,
        rollout_id,
        seq,
        _now(),
        MERGE_NOTE_EVENT_KIND,
        "manager",
        json.dumps({"item_id": item_id, "outcome": "completed", "note": note}),
    )
    return event_id


async def _make_wave_plan(
    db: Any, rollout_id: str, nodes: list[str], edges: list[dict[str, str]]
) -> str:
    """Insert a rollout_plans row and return its ID."""
    plan_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO rollout_plans"
        " (id, rollout_id, version, nodes, edges, planner_model, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)",
        plan_id,
        rollout_id,
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

    Yields dict with: rollout_id, item_id, user_id, project_id, db, headers.
    """
    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    db = await get_db()
    user = await register_user("rollout-ui@example.com", "pass123")
    token = create_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = await _make_project(db, user.id)
    item_id = await _make_item(db, user.id, project_id)
    rollout_id = await _make_rollout(db, user.id, project_id, status="running")
    await _make_wave_item(db, rollout_id, item_id, status="dispatched")
    await _make_wave_plan(db, rollout_id, [item_id], [])

    yield {
        "rollout_id": rollout_id,
        "item_id": item_id,
        "user_id": user.id,
        "project_id": project_id,
        "db": db,
        "headers": headers,
    }


# ---------------------------------------------------------------------------
# AC-22: GET /api/projects/{project_id}/active-rollout
# ---------------------------------------------------------------------------


class TestGetActiveRollout:
    async def test_returns_running_rollout(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Active running rollout returns 200 with progress counts."""
        resp = await client.get(
            f"/api/projects/{wave_setup['project_id']}/active-rollout",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == wave_setup["rollout_id"]
        assert data["status"] == "running"
        assert data["total_count"] == 1
        assert data["done_count"] == 0

    async def test_404_when_no_active_rollout(
        self, client: AsyncClient, auth_headers: dict[str, str], project_id: str
    ) -> None:
        """Returns 404 when no active rollout exists for the project."""
        resp = await client.get(
            f"/api/projects/{project_id}/active-rollout",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_counts_done_items_correctly(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """done_count reflects completed and skipped items."""
        db = wave_setup["db"]
        rollout_id = wave_setup["rollout_id"]
        project_id = wave_setup["project_id"]
        user_id = wave_setup["user_id"]

        # Add a second item (completed)
        item2 = await _make_item(db, user_id, project_id, "Task 2")
        await _make_wave_item(db, rollout_id, item2, status="completed")

        # Add a third item (skipped)
        item3 = await _make_item(db, user_id, project_id, "Task 3")
        await _make_wave_item(db, rollout_id, item3, status="skipped")

        resp = await client.get(
            f"/api/projects/{project_id}/active-rollout",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 3
        assert data["done_count"] == 2

    async def test_returns_halted_rollout(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Halted rollout (non-old) is returned as active."""
        from agent_gtd.database import get_db

        db = await get_db()
        # Get the user_id from auth_headers by calling /api/auth/me
        me_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]

        proj_id = await _make_project(db, user_id, "Halted Project")
        item_id = await _make_item(db, user_id, proj_id)
        rollout_id = await _make_rollout(
            db, user_id, proj_id, status="halted", halt_reason="test failure"
        )
        await _make_wave_item(db, rollout_id, item_id, status="halted")

        resp = await client.get(
            f"/api/projects/{proj_id}/active-rollout",
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
            "/api/projects/no-such-project/active-rollout",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_requires_auth(self, client: AsyncClient, project_id: str) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.get(f"/api/projects/{project_id}/active-rollout")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# AC-23: GET /api/rollouts/{id}/events
# ---------------------------------------------------------------------------


class TestGetRolloutEvents:
    async def test_returns_events_newest_first(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Events are ordered newest first (seq DESC)."""
        db = wave_setup["db"]
        rollout_id = wave_setup["rollout_id"]
        headers = wave_setup["headers"]

        await _make_wave_event(db, rollout_id, kind="item_dispatched", seq=1)
        await _make_wave_event(db, rollout_id, kind="item_outcome", seq=2)

        resp = await client.get(
            f"/api/rollouts/{rollout_id}/events",
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
        rollout_id = wave_setup["rollout_id"]
        headers = wave_setup["headers"]

        for i in range(5):
            await _make_wave_event(db, rollout_id, seq=i + 1)

        resp = await client.get(
            f"/api/rollouts/{rollout_id}/events?limit=3",
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
            f"/api/rollouts/{wave_setup['rollout_id']}/events",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["events"] == []

    async def test_404_for_unknown_rollout(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Unknown rollout_id returns 404."""
        resp = await client.get(
            "/api/rollouts/no-such-wave/events",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_requires_auth(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.get(f"/api/rollouts/{wave_setup['rollout_id']}/events")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/rollouts/{id}/merge-notes
# ---------------------------------------------------------------------------


class TestGetRolloutMergeNotes:
    async def test_returns_notes_newest_first(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        db = wave_setup["db"]
        rollout_id = wave_setup["rollout_id"]

        await _make_merge_note_event(db, rollout_id, "item-a", "renamed Foo", seq=1)
        await _make_merge_note_event(db, rollout_id, "item-b", "new key x.y", seq=2)

        resp = await client.get(
            f"/api/rollouts/{rollout_id}/merge-notes",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        notes = resp.json()["merge_notes"]
        assert [n["item_id"] for n in notes] == ["item-b", "item-a"]
        assert notes[0]["note"] == "new key x.y"

    async def test_ignores_non_merge_note_events(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        db = wave_setup["db"]
        rollout_id = wave_setup["rollout_id"]

        await _make_wave_event(db, rollout_id, kind="item_outcome", seq=1)
        await _make_merge_note_event(db, rollout_id, "item-a", "renamed Foo", seq=2)

        resp = await client.get(
            f"/api/rollouts/{rollout_id}/merge-notes",
            headers=wave_setup["headers"],
        )
        assert [n["item_id"] for n in resp.json()["merge_notes"]] == ["item-a"]

    async def test_respects_limit_param(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        db = wave_setup["db"]
        rollout_id = wave_setup["rollout_id"]

        for i in range(5):
            await _make_merge_note_event(db, rollout_id, f"item-{i}", "n", seq=i + 1)

        resp = await client.get(
            f"/api/rollouts/{rollout_id}/merge-notes?limit=2",
            headers=wave_setup["headers"],
        )
        assert len(resp.json()["merge_notes"]) == 2

    async def test_404_for_unknown_rollout(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get(
            "/api/rollouts/no-such-rollout/merge-notes",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_requires_auth(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        resp = await client.get(f"/api/rollouts/{wave_setup['rollout_id']}/merge-notes")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# AC-24: POST /api/rollouts/{id}/resume
# ---------------------------------------------------------------------------


class TestResumeWave:
    @pytest.fixture
    async def halted_rollout(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> dict[str, Any]:
        """Provide a halted rollout with one halted item."""
        from agent_gtd.database import get_db

        db = await get_db()
        me_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]

        proj_id = await _make_project(db, user_id, "Halted Resume Project")
        item_id = await _make_item(db, user_id, proj_id)
        rollout_id = await _make_rollout(
            db, user_id, proj_id, status="halted", halt_reason="merge failure"
        )
        await _make_wave_item(db, rollout_id, item_id, status="halted")
        await _make_wave_plan(db, rollout_id, [item_id], [])

        return {
            "rollout_id": rollout_id,
            "item_id": item_id,
            "project_id": proj_id,
            "user_id": user_id,
            "db": db,
            "headers": auth_headers,
        }

    async def test_resume_transitions_to_running(
        self, client: AsyncClient, halted_rollout: dict[str, Any]
    ) -> None:
        """Resume sets rollout status back to 'running'."""
        resp = await client.post(
            f"/api/rollouts/{halted_rollout['rollout_id']}/resume",
            json={"answer": "Please retry the failing CI step"},
            headers=halted_rollout["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    async def test_resume_posts_comment(
        self, client: AsyncClient, halted_rollout: dict[str, Any]
    ) -> None:
        """Resume posts the answer as a comment on the project."""
        resp = await client.post(
            f"/api/rollouts/{halted_rollout['rollout_id']}/resume",
            json={"answer": "My answer text"},
            headers=halted_rollout["headers"],
        )
        assert resp.status_code == 200

        # Verify comment was created
        comments_resp = await client.get(
            f"/api/projects/{halted_rollout['project_id']}/comments",
            headers=halted_rollout["headers"],
        )
        assert comments_resp.status_code == 200
        comments = comments_resp.json()
        assert any("My answer text" in c["content_markdown"] for c in comments)

    async def test_resume_transitions_halted_items_to_ready(
        self, client: AsyncClient, halted_rollout: dict[str, Any]
    ) -> None:
        """Resume transitions halted items with no predecessors to 'ready'."""
        db = halted_rollout["db"]
        rollout_id = halted_rollout["rollout_id"]
        item_id = halted_rollout["item_id"]

        resp = await client.post(
            f"/api/rollouts/{rollout_id}/resume",
            json={"answer": "Let's go"},
            headers=halted_rollout["headers"],
        )
        assert resp.status_code == 200

        row = await db.fetchrow(
            "SELECT status FROM rollout_items WHERE rollout_id = $1 AND item_id = $2",
            rollout_id,
            item_id,
        )
        assert row is not None
        assert row["status"] == "ready"

    async def test_resume_409_when_not_halted(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Resume returns 409 when wave is not halted."""
        resp = await client.post(
            f"/api/rollouts/{wave_setup['rollout_id']}/resume",
            json={"answer": "This should fail"},
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 409

    async def test_resume_requires_auth(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unauthenticated request is rejected."""
        resp = await client.post(
            f"/api/rollouts/{wave_setup['rollout_id']}/resume",
            json={"answer": "nope"},
        )
        assert resp.status_code in (401, 403)

    async def test_resume_returns_progress_counts(
        self, client: AsyncClient, halted_rollout: dict[str, Any]
    ) -> None:
        """Resume response includes total_count and done_count."""
        resp = await client.post(
            f"/api/rollouts/{halted_rollout['rollout_id']}/resume",
            json={"answer": "Let's resume"},
            headers=halted_rollout["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_count" in data
        assert "done_count" in data
        assert data["total_count"] == 1
        assert data["done_count"] == 0


# ---------------------------------------------------------------------------
# GET /api/rollouts  (list_rollouts route, AC-2)
# ---------------------------------------------------------------------------


class TestListRollouts:
    async def test_returns_list_of_rollouts(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Authenticated user gets their rollouts as a JSON list."""
        resp = await client.get(
            "/api/rollouts",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [r["id"] for r in data]
        assert wave_setup["rollout_id"] in ids

    async def test_status_filter_excludes_non_matching(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """status filter returns only matching rollouts."""
        resp = await client.get(
            "/api/rollouts?status=completed",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        assert wave_setup["rollout_id"] not in [r["id"] for r in resp.json()]


# ---------------------------------------------------------------------------
# GET /api/rollouts/{id}/plan  (get_rollout_plan route, AC-3)
# ---------------------------------------------------------------------------


class TestGetRolloutPlan:
    async def test_returns_plan_with_items(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Authenticated owner gets the DAG plan for their rollout."""
        resp = await client.get(
            f"/api/rollouts/{wave_setup['rollout_id']}/plan",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rollout_id"] == wave_setup["rollout_id"]
        assert "nodes" in data
        assert "edges" in data
        assert "items" in data

    async def test_404_for_unknown_rollout(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unknown rollout ID returns 404."""
        resp = await client.get(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/plan",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/rollouts/{id}  (get_rollout route, AC-1)
# ---------------------------------------------------------------------------


class TestGetRollout:
    async def test_returns_rollout_row(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Authenticated owner gets the rollout row as JSON."""
        resp = await client.get(
            f"/api/rollouts/{wave_setup['rollout_id']}",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == wave_setup["rollout_id"]
        assert data["status"] == "running"

    async def test_404_for_unknown_rollout(
        self, client: AsyncClient, wave_setup: dict[str, Any]
    ) -> None:
        """Unknown rollout ID returns 404."""
        resp = await client.get(
            "/api/rollouts/00000000-0000-0000-0000-000000000000",
            headers=wave_setup["headers"],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-1, AC-2: POST /api/rollouts — plan_rollout error branches (lines 144-156)
# ---------------------------------------------------------------------------


class TestPlanRolloutErrorBranches:
    async def test_plan_rollout_422_on_validation_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """plan_rollout raises ValidationError → HTTP 422."""
        from unittest.mock import AsyncMock, patch

        from agent_gtd.exceptions import ValidationError as GTDValidationError

        with patch(
            "agent_gtd.routes.rollout_routes.rollout_service.plan_rollout",
            new_callable=AsyncMock,
            side_effect=GTDValidationError("invalid items"),
        ):
            resp = await client.post(
                "/api/rollouts",
                json={"item_ids": ["some-id"]},
                headers=auth_headers,
            )
        assert resp.status_code == 422

    async def test_plan_rollout_502_on_runtime_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """plan_rollout raises RuntimeError → HTTP 502."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "agent_gtd.routes.rollout_routes.rollout_service.plan_rollout",
            new_callable=AsyncMock,
            side_effect=RuntimeError("planner down"),
        ):
            resp = await client.post(
                "/api/rollouts",
                json={"item_ids": ["some-id"]},
                headers=auth_headers,
            )
        assert resp.status_code == 502

    async def test_plan_rollout_422_on_cyclic_dag(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """plan_rollout raises ValueError (cyclic blockers) → HTTP 422."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "agent_gtd.routes.rollout_routes.rollout_service.plan_rollout",
            new_callable=AsyncMock,
            side_effect=ValueError("cyclic dependency detected in rollout plan"),
        ):
            resp = await client.post(
                "/api/rollouts",
                json={"item_ids": ["some-id"]},
                headers=auth_headers,
            )
        assert resp.status_code == 422
        assert "cyclic dependency detected" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# AC-3: POST /api/rollouts/{id}/cancel — 404 branch (lines 252-261)
# ---------------------------------------------------------------------------


class TestCancelRollout:
    async def test_cancel_rollout_404_unknown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST to nonexistent rollout ID returns 404."""
        resp = await client.post(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/cancel",
            json={"reason": "test cancel"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-4: POST /api/rollouts/{id}/start — 404 branch (lines 281-285)
# ---------------------------------------------------------------------------


class TestStartRollout:
    async def test_start_rollout_404_unknown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST to nonexistent rollout ID returns 404."""
        resp = await client.post(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/start",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-5: POST /api/rollouts/{id}/resume — 404 branch (line 478)
# ---------------------------------------------------------------------------


class TestResumeRollout404:
    async def test_resume_rollout_404_unknown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST to nonexistent rollout ID returns 404."""
        resp = await client.post(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/resume",
            json={"answer": "test"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/rollouts/{id}/relaunch-manage — retired with the resident manager
# ---------------------------------------------------------------------------


class TestRelaunchManageRouteRetired:
    async def test_relaunch_manage_route_is_gone(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """No route exists: nothing may relaunch a manager any more."""
        from agent_gtd.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        assert "/api/rollouts/{rollout_id}/relaunch-manage" not in paths
        resp = await client.post(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/relaunch-manage",
            headers=auth_headers,
        )
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# AC-3: POST /api/rollouts/{id}/dismiss
# ---------------------------------------------------------------------------


class TestDismissRollout:
    @pytest.fixture
    async def halted_rollout_setup(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> dict[str, Any]:
        """Provide a halted rollout for dismiss tests."""
        from agent_gtd.database import get_db

        db = await get_db()
        me_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]

        proj_id = await _make_project(db, user_id, "Dismiss Test Project")
        item_id = await _make_item(db, user_id, proj_id)
        rollout_id = await _make_rollout(
            db, user_id, proj_id, status="halted", halt_reason="sensitive-area review"
        )
        await _make_wave_item(db, rollout_id, item_id, status="halted")

        return {
            "rollout_id": rollout_id,
            "item_id": item_id,
            "project_id": proj_id,
            "user_id": user_id,
            "db": db,
            "headers": auth_headers,
        }

    async def test_dismiss_transitions_to_cancelled(
        self, client: AsyncClient, halted_rollout_setup: dict[str, Any]
    ) -> None:
        """POST /api/rollouts/{id}/dismiss transitions halted rollout to cancelled."""
        rollout_id = halted_rollout_setup["rollout_id"]
        headers = halted_rollout_setup["headers"]

        resp = await client.post(
            f"/api/rollouts/{rollout_id}/dismiss",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"

    async def test_dismiss_hides_banner(
        self, client: AsyncClient, halted_rollout_setup: dict[str, Any]
    ) -> None:
        """After dismiss, GET active-rollout returns 404 (banner gone)."""
        rollout_id = halted_rollout_setup["rollout_id"]
        project_id = halted_rollout_setup["project_id"]
        headers = halted_rollout_setup["headers"]

        resp = await client.post(
            f"/api/rollouts/{rollout_id}/dismiss",
            headers=headers,
        )
        assert resp.status_code == 200

        # Banner endpoint should now 404
        banner_resp = await client.get(
            f"/api/projects/{project_id}/active-rollout",
            headers=headers,
        )
        assert banner_resp.status_code == 404

    async def test_dismiss_rollout_nonexistent_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST to nonexistent rollout ID returns 404."""
        resp = await client.post(
            "/api/rollouts/00000000-0000-0000-0000-000000000000/dismiss",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/rollouts/{id}/resume — loop relaunch on the owning host
# ---------------------------------------------------------------------------


async def _make_host(
    db: Any,
    user_id: str,
    url: str,
    *,
    drain_reason: str | None = None,
) -> str:
    host_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO dispatch_hosts"
        " (id, user_id, label, url, api_key, drain_reason, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        host_id,
        user_id,
        f"host-{url[-4:]}",
        url,
        "sk-test",
        drain_reason,
        now,
        now,
    )
    return host_id


async def _make_manage_run(
    db: Any,
    user_id: str,
    project_id: str,
    rollout_id: str,
    *,
    status: str = "failed",
    host_url: str = "",
    created_at: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    ts = created_at or _now()
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch, max_turns,"
        "  mode, rollout_id, dispatch_host_url, created_at, updated_at)"
        " VALUES ($1, NULL, $2, $3, $4, 'b', 10, 'manage', $5, $6, $7, $8)",
        run_id,
        project_id,
        user_id,
        status,
        rollout_id,
        host_url,
        ts,
        ts,
    )
    return run_id


class TestResumeRelaunch:
    @pytest.fixture
    async def setup(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> dict[str, Any]:
        """A halted rollout whose loop last ran on host A."""
        from agent_gtd.database import get_db

        db = await get_db()
        user_id = (await client.get("/api/auth/me", headers=auth_headers)).json()["id"]
        proj_id = await _make_project(db, user_id, "Relaunch Project")
        item_id = await _make_item(db, user_id, proj_id)
        rollout_id = await _make_rollout(
            db, user_id, proj_id, status="halted", halt_reason="merge failure"
        )
        await _make_wave_item(db, rollout_id, item_id, status="halted")
        await _make_wave_plan(db, rollout_id, [item_id], [])
        host_a = await _make_host(db, user_id, "http://host-a:9000")
        host_b = await _make_host(db, user_id, "http://host-b:9000")
        prior = await _make_manage_run(
            db,
            user_id,
            proj_id,
            rollout_id,
            host_url="http://host-a:9000",
            created_at="2026-01-02T00:00:00+00:00",
        )
        # An older run on host B must not win: latest by created_at decides.
        await _make_manage_run(
            db,
            user_id,
            proj_id,
            rollout_id,
            host_url="http://host-b:9000",
            created_at="2026-01-01T00:00:00+00:00",
        )
        return {
            "db": db,
            "user_id": user_id,
            "project_id": proj_id,
            "rollout_id": rollout_id,
            "host_a": host_a,
            "host_b": host_b,
            "prior": prior,
            "headers": auth_headers,
        }

    @staticmethod
    async def _manage_runs(db: Any, rollout_id: str) -> list[dict[str, Any]]:
        rows = await db.fetch(
            "SELECT * FROM claude_runs WHERE rollout_id = $1 AND mode = 'manage'",
            rollout_id,
        )
        return [dict(r) for r in rows]

    @staticmethod
    async def _assert_untouched(
        db: Any, s: dict[str, Any], client: AsyncClient
    ) -> None:
        row = await db.fetchrow(
            "SELECT status FROM autonomous_rollouts WHERE id = $1", s["rollout_id"]
        )
        assert row["status"] == "halted"
        assert len(await TestResumeRelaunch._manage_runs(db, s["rollout_id"])) == 2
        comments = (
            await client.get(
                f"/api/projects/{s['project_id']}/comments", headers=s["headers"]
            )
        ).json()
        assert comments == []

    async def test_halted_resume_relaunches_pinned_to_prior_host(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        from unittest.mock import patch

        s = setup
        with patch("agent_gtd.dispatch_worker.enqueue_run") as enqueue:
            resp = await client.post(
                f"/api/rollouts/{s['rollout_id']}/resume",
                json={"answer": "merged by hand"},
                headers=s["headers"],
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "running"
        loop_run_id = data["loop_run_id"]
        assert loop_run_id
        enqueue.assert_called_once_with(loop_run_id)

        runs = await self._manage_runs(s["db"], s["rollout_id"])
        new = [r for r in runs if r["id"] == loop_run_id]
        assert len(runs) == 3 and len(new) == 1
        assert new[0]["status"] == "pending"
        assert new[0]["item_id"] is None
        assert new[0]["dispatch_host_id"] == s["host_a"]

        rollout = await s["db"].fetchrow(
            "SELECT dispatch_host_id FROM autonomous_rollouts WHERE id = $1",
            s["rollout_id"],
        )
        assert rollout["dispatch_host_id"] is None

        ev = await s["db"].fetch(
            "SELECT actor, payload FROM rollout_events"
            " WHERE rollout_id = $1 AND kind = 'manage_relaunched'",
            s["rollout_id"],
        )
        assert len(ev) == 1
        assert ev[0]["actor"] == "human"
        assert json.loads(ev[0]["payload"]) == {
            "loop_run_id": loop_run_id,
            "dispatch_host_id": s["host_a"],
            "prior_run_id": s["prior"],
        }

    async def test_rollout_pin_wins_over_prior_run_host(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE autonomous_rollouts SET dispatch_host_id = $1 WHERE id = $2",
            s["host_b"],
            s["rollout_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 200, resp.text
        run = await s["db"].fetchrow(
            "SELECT dispatch_host_id FROM claude_runs WHERE id = $1",
            resp.json()["loop_run_id"],
        )
        assert run["dispatch_host_id"] == s["host_b"]

    async def test_unresolvable_host_refuses_and_leaves_rollout_halted(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute("DELETE FROM dispatch_hosts WHERE id = $1", s["host_a"])
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        assert "http://host-a:9000" in resp.json()["detail"]
        await self._assert_untouched(s["db"], s, client)

    async def test_draining_host_refuses_and_leaves_rollout_halted(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE dispatch_hosts SET drain_reason = 'kernel upgrade' WHERE id = $1",
            s["host_a"],
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        assert "draining: kernel upgrade" in resp.json()["detail"]
        await self._assert_untouched(s["db"], s, client)

    async def test_pending_manage_run_refuses_and_leaves_rollout_halted(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE claude_runs SET status = 'pending' WHERE id = $1", s["prior"]
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        assert "pending" in resp.json()["detail"]
        await self._assert_untouched(s["db"], s, client)

    async def test_never_dispatched_rollout_resumes_with_null_loop_run(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "DELETE FROM claude_runs WHERE rollout_id = $1", s["rollout_id"]
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "running"
        assert resp.json()["loop_run_id"] is None
        assert await self._manage_runs(s["db"], s["rollout_id"]) == []

    async def test_running_rollout_relaunch_creates_run_without_state_change(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE autonomous_rollouts SET status = 'running' WHERE id = $1",
            s["rollout_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={},
            headers=s["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["loop_run_id"]
        item = await s["db"].fetchrow(
            "SELECT status FROM rollout_items WHERE rollout_id = $1",
            s["rollout_id"],
        )
        assert item["status"] == "halted"  # untouched: no resume transition
        comments = (
            await client.get(
                f"/api/projects/{s['project_id']}/comments", headers=s["headers"]
            )
        ).json()
        assert comments == []
        kinds = [
            r["kind"]
            for r in await s["db"].fetch(
                "SELECT kind FROM rollout_events WHERE rollout_id = $1",
                s["rollout_id"],
            )
        ]
        assert "wave_resumed" not in kinds
        assert "manage_relaunched" in kinds

    async def test_running_rollout_without_loop_or_relaunch_is_refused(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE autonomous_rollouts SET status = 'running' WHERE id = $1",
            s["rollout_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"relaunch": False},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        assert "nothing to do" in resp.json()["detail"]

        await s["db"].execute(
            "DELETE FROM claude_runs WHERE rollout_id = $1", s["rollout_id"]
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        assert "never had a rollout loop" in resp.json()["detail"]

    async def test_relaunch_false_on_halted_behaves_as_before(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go", "relaunch": False},
            headers=s["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "running"
        assert resp.json()["loop_run_id"] is None
        assert len(await self._manage_runs(s["db"], s["rollout_id"])) == 2

    async def test_halted_resume_requires_an_answer(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "   "},
            headers=s["headers"],
        )
        assert resp.status_code == 409
        await self._assert_untouched(s["db"], s, client)

    async def test_relaunch_keeps_the_settled_reviewer_engine(
        self, client: AsyncClient, setup: dict[str, Any]
    ) -> None:
        s = setup
        await s["db"].execute(
            "UPDATE autonomous_rollouts SET reviewer_engine = 'claude-code-opus'"
            " WHERE id = $1",
            s["rollout_id"],
        )
        resp = await client.post(
            f"/api/rollouts/{s['rollout_id']}/resume",
            json={"answer": "go"},
            headers=s["headers"],
        )
        assert resp.status_code == 200, resp.text
        row = await s["db"].fetchrow(
            "SELECT reviewer_engine FROM autonomous_rollouts WHERE id = $1",
            s["rollout_id"],
        )
        assert row["reviewer_engine"] == "claude-code-opus"
