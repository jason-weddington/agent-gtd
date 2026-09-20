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
