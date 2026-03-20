"""Bootstrap a seed user and project for MCP dogfooding."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent_gtd.auth import generate_api_key, hash_api_key, hash_password
from agent_gtd.database import close_db, get_db, init_db

SEED_EMAIL = "admin@local"
SEED_PASSWORD = "admin"
SEED_PROJECT_NAME = "agent-gtd-dev"
SEED_FILE = Path("data/seed.json")


async def main() -> None:
    await init_db()
    db = await get_db()

    # Ensure user exists
    row = await db.fetchrow(
        "SELECT id FROM users WHERE email = $1", SEED_EMAIL
    )
    if row:
        user_id = row["id"]
        print(f"User already exists: {user_id}")
    else:
        user_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "INSERT INTO users (id, email, hashed_password, created_at) VALUES ($1, $2, $3, $4)",
            user_id, SEED_EMAIL, hash_password(SEED_PASSWORD), now,
        )
        print(f"Created user: {user_id}")

    # Ensure project exists
    row = await db.fetchrow(
        "SELECT id FROM projects WHERE user_id = $1 AND name = $2",
        user_id, SEED_PROJECT_NAME,
    )
    if row:
        project_id = row["id"]
        print(f"Project already exists: {project_id}")
    else:
        project_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "INSERT INTO projects (id, user_id, name, description, status, area, created_at, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            project_id, user_id, SEED_PROJECT_NAME, "", "active", "", now, now,
        )
        print(f"Created project: {project_id}")

    # Ensure API key exists
    row = await db.fetchrow(
        "SELECT id, key_hash FROM api_keys WHERE user_id = $1", user_id
    )
    if row:
        api_key = None
        print(f"API key already exists (prefix: {row['key_hash'][:8]}...)")
    else:
        api_key = generate_api_key()
        h = hash_api_key(api_key)
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "INSERT INTO api_keys (id, user_id, key_hash, name, created_at)"
            " VALUES ($1, $2, $3, $4, $5)",
            str(uuid.uuid4()), user_id, h, "seed", now,
        )
        print(f"Created API key: {api_key}")

    # Write seed.json
    seed_data: dict[str, str] = {
        "user_id": user_id,
        "project_id": project_id,
    }
    if api_key:
        seed_data["api_key"] = api_key
    else:
        # Preserve existing api_key from seed.json if present
        if SEED_FILE.exists():
            existing = json.loads(SEED_FILE.read_text())
            if "api_key" in existing:
                seed_data["api_key"] = existing["api_key"]

    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEED_FILE.write_text(json.dumps(seed_data, indent=2) + "\n")
    print(f"\nSeed data written to {SEED_FILE}")
    print(f"  user_id:    {user_id}")
    print(f"  project_id: {project_id}")
    if api_key:
        print(f"  api_key:    {api_key}")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
