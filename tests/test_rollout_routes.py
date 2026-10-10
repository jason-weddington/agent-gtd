class TestReviewerAutonomousMergeActor:
    """The reviewer is a distinct merge actor and must be accepted by the route.

    The worker-driven wave loop launches a short-lived reviewer per item and
    records the merge as `reviewer-autonomous`. That value was missing from
    `MergeActor`, so every completion the new loop attempted came back 422 —
    and because the merge had ALREADY landed by then, the failure was pure
    bookkeeping: real work on main, rollout reported `halted`, two unrelated
    items stopped as collateral.
    """

    def test_reviewer_autonomous_is_a_valid_merge_actor(self) -> None:
        from agent_gtd.models import MergeActor

        assert MergeActor("reviewer-autonomous") is MergeActor.REVIEWER_AUTONOMOUS

    def test_complete_item_request_accepts_the_reviewer_payload(self) -> None:
        """The exact payload the dispatch worker sends must validate."""
        from agent_gtd.routes.rollout_routes import CompleteItemRequest

        req = CompleteItemRequest.model_validate(
            {
                "item_id": "96013869-0000-0000-0000-000000000000",
                "outcome": "completed",
                "merge_actor": "reviewer-autonomous",
                "decision_rule": "agent-judgment",
                "merge_note": "reviewed and merged",
            }
        )
        assert req.merge_actor == "reviewer-autonomous"
        assert req.decision_rule == "agent-judgment"


async def test_complete_item_twice_is_idempotent(client) -> None:
    """Two identical POSTs to /complete-item both return 200."""
    import uuid
    from datetime import UTC, datetime

    from agent_gtd.auth import create_token, register_user
    from agent_gtd.database import get_db

    user = await register_user("idem@example.com", "testpass123")
    headers = {"Authorization": f"Bearer {create_token(user.id)}"}
    db = await get_db()
    now = datetime.now(UTC).isoformat()
    project_id, item_id, rollout_id = (str(uuid.uuid4()) for _ in range(3))
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user.id,
        "P",
        now,
        now,
    )
    await db.execute(
        "INSERT INTO items (id, project_id, user_id, title, status,"
        " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        item_id,
        project_id,
        user.id,
        "I",
        "review",
        now,
        now,
    )
    await db.execute(
        "INSERT INTO autonomous_rollouts"
        " (id, project_id, lead_user_id, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, 'running', $4, $5)",
        rollout_id,
        project_id,
        user.id,
        now,
        now,
    )
    await db.execute(
        "INSERT INTO rollout_items (rollout_id, item_id, status)"
        " VALUES ($1, $2, 'dispatched')",
        rollout_id,
        item_id,
    )
    body = {"item_id": item_id, "outcome": "completed"}
    url = f"/api/rollouts/{rollout_id}/complete-item"
    first = await client.post(url, json=body, headers=headers)
    second = await client.post(url, json=body, headers=headers)
    assert first.status_code == 200
    assert first.json()["already_recorded"] is False
    assert second.status_code == 200
    assert second.json()["already_recorded"] is True
