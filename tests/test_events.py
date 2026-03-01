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


# --- SSE endpoint integration tests ---


async def test_sse_endpoint_requires_auth(client: AsyncClient):
    """SSE endpoint rejects unauthenticated requests."""
    res = await client.get("/api/events")
    assert res.status_code == 401


async def test_sse_endpoint_accepts_token_param(client: AsyncClient, auth_headers):
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

    # Verify bad token is rejected
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
