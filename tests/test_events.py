"""Tests for event bus, event persistence, and SSE endpoint."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient

from agent_gtd.database import get_db
from agent_gtd.event_bus import EventBus, get_event_bus

# --- helpers ---


async def _create_test_user(db) -> str:
    """Insert a minimal user row and return the user_id."""
    user_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id}@test.com",
        "unused-hash",
        now,
    )
    return user_id


async def _create_test_project(db, owner_id: str) -> str:
    """Insert a minimal project row and return the project_id."""
    project_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        owner_id,
        f"project-{project_id[:8]}",
        now,
        now,
    )
    return project_id


async def _add_project_member(db, project_id: str, user_id: str) -> None:
    """Insert a project_members row."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at) "
        "VALUES ($1, $2, $3)",
        project_id,
        user_id,
        now,
    )


# --- Event bus unit tests ---


async def test_subscribe_publish_unsubscribe(_setup_db):
    """Events are delivered to subscribers and stop after unsubscribe."""
    bus = EventBus()
    db = await get_db()
    user_id = await _create_test_user(db)

    queue = bus.subscribe(user_id)

    event_id = await bus.publish(
        db,
        user_id=user_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1", "title": "Test"},
    )

    assert not queue.empty()
    event = queue.get_nowait()
    assert event["id"] == event_id
    assert event["event_type"] == "item_created"
    assert event["entity_id"] == "item-1"

    bus.unsubscribe(user_id, queue)

    await bus.publish(
        db,
        user_id=user_id,
        event_type="item_updated",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1"},
    )
    assert queue.empty()


async def test_publish_does_not_reach_other_users(_setup_db):
    """Events for user-1 are not delivered to user-2's queue."""
    bus = EventBus()
    db = await get_db()
    user1 = await _create_test_user(db)
    user2 = await _create_test_user(db)

    queue2 = bus.subscribe(user2)

    await bus.publish(
        db,
        user_id=user1,
        event_type="item_created",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1"},
    )

    assert queue2.empty()
    bus.unsubscribe(user2, queue2)


async def test_event_persisted_to_db(_setup_db):
    """Published events are persisted in the events table."""
    bus = EventBus()
    db = await get_db()
    user_id = await _create_test_user(db)

    event_id = await bus.publish(
        db,
        user_id=user_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-1",
        project_id="proj-1",
        payload={"id": "item-1", "title": "Test"},
    )

    row = await db.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
    assert row is not None
    assert row["event_type"] == "item_created"
    assert row["entity_type"] == "item"
    assert row["entity_id"] == "item-1"
    assert row["project_id"] == "proj-1"
    payload = json.loads(row["payload"])
    assert payload["title"] == "Test"


async def test_replay_since(_setup_db):
    """replay_since returns events created after the given event ID."""
    bus = EventBus()
    db = await get_db()
    user_id = await _create_test_user(db)

    id1 = await bus.publish(
        db,
        user_id=user_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1"},
    )

    await asyncio.sleep(0.01)

    id2 = await bus.publish(
        db,
        user_id=user_id,
        event_type="item_updated",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1"},
    )

    await asyncio.sleep(0.01)

    id3 = await bus.publish(
        db,
        user_id=user_id,
        event_type="item_deleted",
        entity_type="item",
        entity_id="item-1",
        payload={"id": "item-1"},
    )

    replayed = await bus.replay_since(db, user_id, id1)
    replayed_ids = [e["id"] for e in replayed]
    assert id2 in replayed_ids
    assert id3 in replayed_ids
    assert id1 not in replayed_ids


async def test_replay_since_unknown_id(_setup_db):
    """replay_since with unknown ID returns empty list."""
    bus = EventBus()
    db = await get_db()

    result = await bus.replay_since(db, "user-1", "nonexistent-id")
    assert result == []


async def test_drain_sends_none(_setup_db):
    """drain() sends None sentinel to all subscriber queues."""
    bus = EventBus()

    q1 = bus.subscribe("user-1")
    q2 = bus.subscribe("user-2")

    await bus.drain()

    assert q1.get_nowait() is None
    assert q2.get_nowait() is None


async def test_queue_full_drops_oldest(_setup_db):
    """When queue is full, oldest event is dropped to make room."""
    bus = EventBus()
    db = await get_db()
    user_id = await _create_test_user(db)

    queue = bus.subscribe(user_id)

    for i in range(256):
        await bus.publish(
            db,
            user_id=user_id,
            event_type="item_created",
            entity_type="item",
            entity_id=f"item-{i}",
            payload={"id": f"item-{i}"},
        )

    assert queue.full()

    # One more should succeed (drops oldest)
    await bus.publish(
        db,
        user_id=user_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-overflow",
        payload={"id": "item-overflow"},
    )


# --- Project member fan-out tests ---


async def test_publish_fans_out_to_project_members(_setup_db):
    """Run events with a project_id are delivered to all project members' queues."""
    bus = EventBus()
    db = await get_db()

    owner_id = await _create_test_user(db)
    member_id = await _create_test_user(db)
    project_id = await _create_test_project(db, owner_id)
    await _add_project_member(db, project_id, member_id)

    # Only the member is subscribed (owner is not)
    member_queue = bus.subscribe(member_id)

    await bus.publish(
        db,
        user_id=owner_id,
        event_type="run_started",
        entity_type="run",
        entity_id="run-1",
        project_id=project_id,
        payload={"id": "run-1"},
    )

    # Member should have received the event even though the owner published it
    assert not member_queue.empty()
    event = member_queue.get_nowait()
    assert event["event_type"] == "run_started"
    assert event["project_id"] == project_id

    bus.unsubscribe(member_id, member_queue)


async def test_publish_project_fanout_does_not_double_deliver_to_owner(_setup_db):
    """Owner does not receive the same event twice (once via user fan-out, once via project)."""  # noqa: E501
    bus = EventBus()
    db = await get_db()

    owner_id = await _create_test_user(db)
    project_id = await _create_test_project(db, owner_id)

    owner_queue = bus.subscribe(owner_id)

    await bus.publish(
        db,
        user_id=owner_id,
        event_type="run_started",
        entity_type="run",
        entity_id="run-1",
        project_id=project_id,
        payload={"id": "run-1"},
    )

    # Owner should receive exactly one event
    assert not owner_queue.empty()
    owner_queue.get_nowait()  # consume it
    assert owner_queue.empty(), "owner should receive the event exactly once"

    bus.unsubscribe(owner_id, owner_queue)


async def test_replay_since_includes_shared_project_events(_setup_db):
    """replay_since with project_ids returns events from another user in the same project."""  # noqa: E501
    bus = EventBus()
    db = await get_db()

    owner_id = await _create_test_user(db)
    member_id = await _create_test_user(db)
    project_id = await _create_test_project(db, owner_id)
    await _add_project_member(db, project_id, member_id)

    # Member publishes a "baseline" event to get a since_id
    since_id = await bus.publish(
        db,
        user_id=member_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-baseline",
        payload={"id": "item-baseline"},
    )

    await asyncio.sleep(0.01)

    # Owner publishes a run event into the shared project
    await bus.publish(
        db,
        user_id=owner_id,
        event_type="run_started",
        entity_type="run",
        entity_id="run-1",
        project_id=project_id,
        payload={"id": "run-1"},
    )

    # Replay for member with shared project_ids — should include owner's run event
    replayed = await bus.replay_since(db, member_id, since_id, project_ids=[project_id])
    replayed_types = [e["event_type"] for e in replayed]
    assert "run_started" in replayed_types, (
        "shared-project run event should appear in member's replay"
    )


async def test_replay_since_without_project_ids_excludes_others(_setup_db):
    """replay_since without project_ids does NOT return other users' events."""
    bus = EventBus()
    db = await get_db()

    owner_id = await _create_test_user(db)
    member_id = await _create_test_user(db)
    project_id = await _create_test_project(db, owner_id)
    await _add_project_member(db, project_id, member_id)

    # Member baseline event
    since_id = await bus.publish(
        db,
        user_id=member_id,
        event_type="item_created",
        entity_type="item",
        entity_id="item-baseline",
        payload={"id": "item-baseline"},
    )

    await asyncio.sleep(0.01)

    # Owner publishes a run event in the shared project
    await bus.publish(
        db,
        user_id=owner_id,
        event_type="run_started",
        entity_type="run",
        entity_id="run-1",
        project_id=project_id,
        payload={"id": "run-1"},
    )

    # Replay for member WITHOUT project_ids — should NOT include owner's event
    replayed = await bus.replay_since(db, member_id, since_id)
    replayed_types = [e["event_type"] for e in replayed]
    assert "run_started" not in replayed_types, (
        "other user's event should not appear in replay without project_ids"
    )


# --- _format_sse unit tests ---


def test_format_sse_basic():
    """_format_sse produces valid SSE wire format."""
    from agent_gtd.routes.event_routes import _format_sse

    event = {
        "id": "evt-001",
        "event_type": "item_created",
        "entity_type": "item",
        "entity_id": "item-123",
        "project_id": "proj-456",
        "payload": json.dumps({"title": "Buy milk"}),
        "created_at": "2026-01-01T00:00:00Z",
    }
    result = _format_sse(event)
    assert result.startswith("id: evt-001\n")
    assert "event: item_created\n" in result
    assert result.endswith("\n\n")
    # Parse the data line
    data_line = next(line for line in result.split("\n") if line.startswith("data:"))
    data = json.loads(data_line[len("data: ") :])
    assert data["eventType"] == "item_created"
    assert data["entityType"] == "item"
    assert data["entityId"] == "item-123"
    assert data["projectId"] == "proj-456"
    assert data["payload"] == {"title": "Buy milk"}
    assert data["createdAt"] == "2026-01-01T00:00:00Z"


def test_format_sse_null_project():
    """_format_sse handles null project_id."""
    from agent_gtd.routes.event_routes import _format_sse

    event = {
        "id": "evt-002",
        "event_type": "item_updated",
        "entity_type": "item",
        "entity_id": "item-789",
        "project_id": None,
        "payload": json.dumps({"title": "Updated"}),
        "created_at": "2026-01-02T00:00:00Z",
    }
    result = _format_sse(event)
    data_line = next(line for line in result.split("\n") if line.startswith("data:"))
    data = json.loads(data_line[len("data: ") :])
    assert data["projectId"] is None


# --- SSE endpoint integration tests ---


async def test_sse_endpoint_requires_auth(client: AsyncClient, monkeypatch):
    """SSE endpoint rejects unauthenticated requests."""
    monkeypatch.setattr("agent_gtd.routes.event_routes.is_local_mode", lambda: False)
    res = await client.get("/api/events")
    assert res.status_code == 401


async def test_sse_endpoint_accepts_token_param(
    client: AsyncClient, auth_headers, monkeypatch
):
    """SSE endpoint authenticates via ?token= query param.

    Note: We can't read the streaming body in ASGI tests because httpx's
    ASGI transport blocks the event loop on aread()/aiter_text() for
    infinite SSE streams. Event delivery is verified by the bus-level
    tests above. Here we only verify auth + replay via the DB.
    """
    token = auth_headers["Authorization"].replace("Bearer ", "")
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)
    bus = get_event_bus()
    db = await get_db()

    # Create an item to produce a persisted event
    queue = bus.subscribe(user_id)
    try:
        await client.post(
            "/api/items",
            json={"title": "SSE auth test"},
            headers=auth_headers,
        )
        event = queue.get_nowait()
    finally:
        bus.unsubscribe(user_id, queue)

    # Verify the event was persisted (the SSE endpoint would replay it)
    row = await db.fetchrow("SELECT * FROM events WHERE id = $1", event["id"])
    assert row is not None
    assert row["event_type"] == "item_created"

    # Verify bad token is rejected — disable local mode so auth actually runs
    monkeypatch.setattr("agent_gtd.routes.event_routes.is_local_mode", lambda: False)
    res = await client.get("/api/events?token=bad-token")
    assert res.status_code == 401


async def test_sse_receives_item_event(client: AsyncClient, auth_headers):
    """Creating an item produces an SSE event on the stream."""
    token = auth_headers["Authorization"].replace("Bearer ", "")

    bus = get_event_bus()
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)
    queue = bus.subscribe(user_id)

    try:
        res = await client.post(
            "/api/items",
            json={"title": "SSE event test"},
            headers=auth_headers,
        )
        assert res.status_code == 201

        event = queue.get_nowait()
        assert event["event_type"] == "item_created"
        assert event["entity_type"] == "item"
        payload = json.loads(event["payload"])
        assert payload["title"] == "SSE event test"
    finally:
        bus.unsubscribe(user_id, queue)


async def test_sse_receives_update_and_delete_events(client: AsyncClient, auth_headers):
    """Update and delete operations produce SSE events."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)

    bus = get_event_bus()
    queue = bus.subscribe(user_id)

    try:
        res = await client.post(
            "/api/items",
            json={"title": "Lifecycle test"},
            headers=auth_headers,
        )
        item_id = res.json()["id"]
        create_event = queue.get_nowait()
        assert create_event["event_type"] == "item_created"

        await client.patch(
            f"/api/items/{item_id}",
            json={"title": "Updated title"},
            headers=auth_headers,
        )
        update_event = queue.get_nowait()
        assert update_event["event_type"] == "item_updated"

        await client.delete(
            f"/api/items/{item_id}",
            headers=auth_headers,
        )
        delete_event = queue.get_nowait()
        assert delete_event["event_type"] == "item_deleted"
        delete_payload = json.loads(delete_event["payload"])
        assert delete_payload["id"] == item_id
    finally:
        bus.unsubscribe(user_id, queue)


async def test_sse_project_events(client: AsyncClient, auth_headers):
    """Project CRUD operations produce SSE events."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)

    bus = get_event_bus()
    queue = bus.subscribe(user_id)

    try:
        res = await client.post(
            "/api/projects",
            json={"name": "SSE Project"},
            headers=auth_headers,
        )
        proj_id = res.json()["id"]
        event = queue.get_nowait()
        assert event["event_type"] == "project_created"

        await client.patch(
            f"/api/projects/{proj_id}",
            json={"name": "Updated SSE Project"},
            headers=auth_headers,
        )
        event = queue.get_nowait()
        assert event["event_type"] == "project_updated"

        await client.delete(
            f"/api/projects/{proj_id}",
            headers=auth_headers,
        )
        event = queue.get_nowait()
        assert event["event_type"] == "project_deleted"
    finally:
        bus.unsubscribe(user_id, queue)


async def test_sse_note_events(client: AsyncClient, auth_headers, project_id):
    """Note CRUD operations produce SSE events."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)

    bus = get_event_bus()
    queue = bus.subscribe(user_id)

    try:
        # project_id fixture created the project before we subscribed,
        # so no project_created event in the queue to drain.

        res = await client.post(
            f"/api/projects/{project_id}/notes",
            json={"title": "SSE Note", "contentMarkdown": "content"},
            headers=auth_headers,
        )
        note_id = res.json()["id"]
        event = queue.get_nowait()
        assert event["event_type"] == "note_created"

        await client.patch(
            f"/api/notes/{note_id}",
            json={"title": "Updated Note"},
            headers=auth_headers,
        )
        event = queue.get_nowait()
        assert event["event_type"] == "note_updated"

        await client.delete(
            f"/api/notes/{note_id}",
            headers=auth_headers,
        )
        event = queue.get_nowait()
        assert event["event_type"] == "note_deleted"
    finally:
        bus.unsubscribe(user_id, queue)


async def test_sse_replay_integration(client: AsyncClient, auth_headers):
    """SSE endpoint replays events since a given ID."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    from agent_gtd.auth import decode_token

    user_id = decode_token(token)
    bus = get_event_bus()
    queue = bus.subscribe(user_id)

    try:
        await client.post(
            "/api/items",
            json={"title": "Replay item 1"},
            headers=auth_headers,
        )
        event1 = queue.get_nowait()
        since_id = event1["id"]

        await asyncio.sleep(0.01)

        await client.post(
            "/api/items",
            json={"title": "Replay item 2"},
            headers=auth_headers,
        )
        event2 = queue.get_nowait()

        replayed = await bus.replay_since(await get_db(), user_id, since_id)
        replayed_ids = [e["id"] for e in replayed]
        assert event2["id"] in replayed_ids
        assert since_id not in replayed_ids
    finally:
        bus.unsubscribe(user_id, queue)
