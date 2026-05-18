"""Tests for the runs/rollouts failure feed endpoints (AC-1 through AC-7).

Covers:
- GET /api/runs/failures  (AC-1, AC-7)
- GET /api/runs/stale      (AC-5, AC-6, AC-7)
- GET /api/rollouts/{id}/rollout_failures  (AC-2, AC-7)
- Rollout halt dual-comment (AC-4, AC-7)
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ts(offset_hours: int = 0) -> str:
    """ISO timestamp shifted by *offset_hours* relative to now."""
    return (datetime.now(UTC) + timedelta(hours=offset_hours)).isoformat()


async def _make_user(db: Any) -> str:
    """Insert a test user and return its ID."""
    user_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id[:8]}@test.com",
        "hashed",
        now,
    )
    return user_id


async def _make_project(db: Any, user_id: str, name: str = "Test Project") -> str:
    """Insert a test project and return its ID."""
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
    db: Any,
    user_id: str,
    project_id: str,
    *,
    title: str = "Test Item",
    status: str = "active",
) -> str:
    """Insert a test item and return its ID."""
    from agent_gtd.database import encode_file_specs, encode_json_list

    item_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO items"
        " (id, project_id, user_id, title, description, status,"
        "  labels, acceptance_criteria, files_to_modify, scope_out,"
        "  created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        item_id,
        project_id,
        user_id,
        title,
        "",
        status,
        encode_json_list([]),
        encode_json_list([]),
        encode_file_specs([]),
        encode_json_list([]),
        now,
        now,
    )
    return item_id


async def _make_run(
    db: Any,
    user_id: str,
    project_id: str,
    *,
    item_id: str | None = None,
    status: str = "failed",
    mode: str = "build",
    error_msg: str = "test error",
    rollout_id: str | None = None,
    finished_at: str | None = None,
) -> str:
    """Insert a claude_run row and return its ID."""
    run_id = str(uuid.uuid4())
    now = _now()
    fin = finished_at if finished_at is not None else now
    await db.execute(
        "INSERT INTO claude_runs"
        " (id, item_id, project_id, user_id, status, feature_branch,"
        "  workspace_dir, max_turns, mode, error_msg, rollout_id,"
        "  finished_at, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
        run_id,
        item_id,
        project_id,
        user_id,
        status,
        "feat/test-branch",
        "",
        100,
        mode,
        error_msg,
        rollout_id,
        fin,
        now,
        now,
    )
    return run_id


async def _make_rollout(
    db: Any,
    user_id: str,
    project_id: str,
    *,
    status: str = "running",
) -> str:
    """Insert an autonomous_rollout row and return its ID."""
    rollout_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        rollout_id,
        project_id,
        user_id,
        status,
        now,
        now,
    )
    return rollout_id


async def _make_rollout_event(
    db: Any,
    rollout_id: str,
    *,
    kind: str = "wave_halted",
    actor: str = "manager",
    payload: dict | None = None,
) -> str:
    """Insert a rollout_event row and return its ID."""
    event_id = str(uuid.uuid4())
    now = _now()
    # Use a simple incrementing seq based on existing rows
    row = await db.fetchrow(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq"
        " FROM rollout_events WHERE rollout_id = $1",
        rollout_id,
    )
    seq = int(row["next_seq"]) if row else 1
    await db.execute(
        "INSERT INTO rollout_events"
        " (id, rollout_id, seq, ts, kind, actor, decision_rule, payload)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        event_id,
        rollout_id,
        seq,
        now,
        kind,
        actor,
        "",
        json.dumps(payload or {}),
    )
    return event_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    from agent_gtd.database import get_db

    return await get_db()


# ---------------------------------------------------------------------------
# AC-7: Auth guard — 401 without token
# ---------------------------------------------------------------------------


async def test_failed_runs_auth_guard(client: AsyncClient):
    """GET /api/runs/failures returns 401 without authentication."""
    res = await client.get("/api/runs/failures")
    assert res.status_code == 401


async def test_stale_runs_auth_guard(client: AsyncClient):
    """GET /api/runs/stale returns 401 without authentication."""
    res = await client.get("/api/runs/stale")
    assert res.status_code == 401


async def test_rollout_failures_auth_guard(client: AsyncClient):
    """GET /api/rollouts/{id}/rollout_failures returns 401 without auth."""
    res = await client.get(f"/api/rollouts/{uuid.uuid4()}/rollout_failures")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# AC-1 / AC-7: GET /api/runs/failures endpoint shape
# ---------------------------------------------------------------------------


async def test_failed_runs_empty_for_new_user(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """New user with no failed runs gets an empty list."""
    res = await client.get("/api/runs/failures", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_failed_runs_endpoint_shape(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """GET /api/runs/failures returns enriched failed run with expected fields."""
    project_id = await _make_project(db, user_id, name="Failure Feed Project")
    item_id = await _make_item(db, user_id, project_id, title="Failing Task")
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="failed",
        error_msg="agent exited with non-zero code",
    )

    res = await client.get("/api/runs/failures", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1

    # Find the run we just created
    run = next((r for r in data if r["id"] == run_id), None)
    assert run is not None, f"run_id {run_id} not found in response: {data}"

    # Required fields (backend JSON uses snake_case)
    assert run["id"] == run_id
    assert run["item_id"] == item_id
    assert run["project_id"] == project_id
    assert run["status"] == "failed"
    assert run["error_msg"] == "agent exited with non-zero code"
    assert run["item_title"] == "Failing Task"
    assert run["project_name"] == "Failure Feed Project"


async def test_failed_runs_includes_timeout_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """GET /api/runs/failures includes runs with status='timeout'."""
    project_id = await _make_project(db, user_id)
    run_id = await _make_run(db, user_id, project_id, status="timeout")

    res = await client.get("/api/runs/failures", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert run_id in ids


async def test_failed_runs_excludes_success(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """GET /api/runs/failures does not include success runs."""
    project_id = await _make_project(db, user_id)
    success_run_id = await _make_run(db, user_id, project_id, status="success")

    res = await client.get("/api/runs/failures", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert success_run_id not in ids


async def test_failed_runs_no_access_to_other_users(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db: Any,
):
    """Failed runs from other users' projects are not returned."""
    other_user_id = await _make_user(db)
    other_project_id = await _make_project(db, other_user_id, name="Other Project")
    other_run_id = await _make_run(db, other_user_id, other_project_id, status="failed")

    res = await client.get("/api/runs/failures", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert other_run_id not in ids


# ---------------------------------------------------------------------------
# AC-5 / AC-6 / AC-7: GET /api/runs/stale
# ---------------------------------------------------------------------------


async def test_stale_runs_empty_for_new_user(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """New user with no stale runs gets an empty list."""
    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_stale_runs_query(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """AC-6: Successful run whose item status wasn't advanced appears in stale feed."""
    project_id = await _make_project(db, user_id, name="Stale Project")
    item_id = await _make_item(
        db, user_id, project_id, title="Stale Item", status="active"
    )
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="success",
        mode="build",
        error_msg="",
        finished_at=_ts(-1),  # 1 hour ago, within 72h window
    )

    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()

    run = next((r for r in data if r["id"] == run_id), None)
    assert run is not None, f"stale run {run_id} not found in response: {data}"

    # Required fields (backend JSON uses snake_case)
    assert run["item_id"] == item_id
    assert run["status"] == "success"
    assert run["item_title"] == "Stale Item"
    assert run["project_name"] == "Stale Project"
    assert run["item_status"] == "active"


async def test_stale_runs_excludes_advanced_item(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """Successful run whose item is in 'review' does NOT appear in stale feed."""
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(
        db, user_id, project_id, title="Advanced Item", status="review"
    )
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="success",
        mode="build",
        finished_at=_ts(-1),
    )

    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert run_id not in ids


async def test_stale_runs_excludes_done_item(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """Successful run whose item is in 'done' does NOT appear in stale feed."""
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="done")
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="success",
        mode="build",
        finished_at=_ts(-1),
    )

    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert run_id not in ids


async def test_stale_runs_excludes_old_runs(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """Successful run finished >72h ago does NOT appear in stale feed."""
    project_id = await _make_project(db, user_id)
    item_id = await _make_item(db, user_id, project_id, status="active")
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="success",
        mode="build",
        finished_at=_ts(-73),  # 73 hours ago, outside default 72h window
    )

    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert run_id not in ids


async def test_stale_runs_excludes_manage_mode(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """Manage-mode runs are not included in the stale feed (build-mode only)."""
    project_id = await _make_project(db, user_id)
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=None,  # manage-mode has no item
        status="success",
        mode="manage",
        finished_at=_ts(-1),
    )

    res = await client.get("/api/runs/stale", headers=auth_headers)
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert run_id not in ids


# ---------------------------------------------------------------------------
# AC-2 / AC-7: GET /api/rollouts/{rollout_id}/rollout_failures
# ---------------------------------------------------------------------------


async def test_rollout_failures_endpoint_shape(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """GET /api/rollouts/{id}/rollout_failures returns wave_halts and failed_runs."""
    project_id = await _make_project(db, user_id, name="Rollout Failures Project")
    rollout_id = await _make_rollout(db, user_id, project_id, status="halted")
    item_id = await _make_item(db, user_id, project_id, title="Rollout Item")

    # A wave_halted event
    await _make_rollout_event(
        db,
        rollout_id,
        kind="wave_halted",
        payload={"reason": "merge_rejected", "item_id": item_id, "comment_id": "c1"},
    )

    # A failed run linked to this rollout
    run_id = await _make_run(
        db,
        user_id,
        project_id,
        item_id=item_id,
        status="failed",
        rollout_id=rollout_id,
        error_msg="build failed",
    )

    res = await client.get(
        f"/api/rollouts/{rollout_id}/rollout_failures",
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()

    # Backend JSON uses snake_case
    assert "wave_halts" in data
    assert "failed_runs" in data

    # Wave halts
    halts = data["wave_halts"]
    assert len(halts) == 1
    halt = halts[0]
    assert halt["rollout_id"] == rollout_id
    assert halt["kind"] == "wave_halted"
    payload = halt["payload"]
    assert payload["reason"] == "merge_rejected"
    assert payload["item_id"] == item_id

    # Failed runs
    runs = data["failed_runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == run_id
    assert run["status"] == "failed"
    assert run["item_id"] == item_id
    assert run["error_msg"] == "build failed"
    assert run["item_title"] == "Rollout Item"


async def test_rollout_failures_404_for_unknown_rollout(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    """GET /api/rollouts/{id}/rollout_failures returns 404 for non-existent rollout."""
    fake_id = str(uuid.uuid4())
    res = await client.get(
        f"/api/rollouts/{fake_id}/rollout_failures",
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_rollout_failures_404_other_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db: Any,
):
    """GET /api/rollouts/{id}/rollout_failures returns 404 for another user's rollout.

    Verifies access control: a user cannot see another user's rollout failures.
    """
    other_user_id = await _make_user(db)
    other_project_id = await _make_project(db, other_user_id)
    other_rollout_id = await _make_rollout(db, other_user_id, other_project_id)

    res = await client.get(
        f"/api/rollouts/{other_rollout_id}/rollout_failures",
        headers=auth_headers,
    )
    assert res.status_code == 404


async def test_rollout_failures_empty_feed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    db: Any,
):
    """Rollout with no halts and no failed runs returns empty lists."""
    project_id = await _make_project(db, user_id)
    rollout_id = await _make_rollout(db, user_id, project_id, status="completed")

    res = await client.get(
        f"/api/rollouts/{rollout_id}/rollout_failures",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    # Backend JSON uses snake_case field names
    assert data["wave_halts"] == []
    assert data["failed_runs"] == []


# ---------------------------------------------------------------------------
# AC-4 / AC-7: Dual-comment halt — project + item
# ---------------------------------------------------------------------------


async def test_halt_posts_item_comment(
    db: Any,
    user_id: str,
):
    """AC-4: halt_rollout with item_id posts two comments — project and item."""
    from agent_gtd.services.rollout_service import halt_rollout

    project_id = await _make_project(db, user_id, name="Halt Project")
    item_id = await _make_item(db, user_id, project_id, title="Halted Item")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    await halt_rollout(
        db,
        user_id,
        rollout_id,
        reason="merge_rejected",
        comment="Reviewer rejected the PR",
        item_id=item_id,
    )

    # Two comment rows should exist: one project-level, one item-level
    rows = await db.fetch(
        "SELECT project_id, item_id, content_markdown FROM comments"
        " WHERE created_by = 'wave-manager'",
    )
    assert len(rows) == 2, f"Expected 2 wave-manager comments, got {len(rows)}: " + str(
        [dict(r) for r in rows]
    )

    project_comments = [r for r in rows if r["project_id"] == project_id]
    item_comments = [r for r in rows if r["item_id"] == item_id]

    assert len(project_comments) == 1, "Expected exactly 1 project-level halt comment"
    assert len(item_comments) == 1, "Expected exactly 1 item-level halt comment"

    # Item comment should reference the project comment id
    item_comment_text = item_comments[0]["content_markdown"]
    assert "Rollout halted" in item_comment_text
    assert "merge_rejected" in item_comment_text
    # Verify it references the project-level comment id
    project_comment_id = (
        project_comments[0]["id"] if hasattr(project_comments[0], "id") else None
    )
    if project_comment_id is None:
        # fetchrow returns a dict-like object; get the id via select
        proj_row = await db.fetchrow(
            "SELECT id FROM comments"
            " WHERE project_id = $1 AND created_by = 'wave-manager'",
            project_id,
        )
        project_comment_id = str(proj_row["id"])
    assert project_comment_id in item_comment_text


async def test_halt_without_item_id_posts_only_project_comment(
    db: Any,
    user_id: str,
):
    """halt_rollout without item_id only posts the project-level comment.

    When no item_id is in halt context, no item-level comment should be created.
    """
    from agent_gtd.services.rollout_service import halt_rollout

    project_id = await _make_project(db, user_id, name="No Item Halt Project")
    rollout_id = await _make_rollout(db, user_id, project_id, status="running")

    await halt_rollout(
        db,
        user_id,
        rollout_id,
        reason="manual_halt",
        item_id=None,  # No offending item
    )

    rows = await db.fetch(
        "SELECT project_id, item_id FROM comments WHERE created_by = 'wave-manager'",
    )
    assert len(rows) == 1, f"Expected 1 wave-manager comment, got {len(rows)}"
    assert rows[0]["project_id"] == project_id
    assert rows[0]["item_id"] is None
