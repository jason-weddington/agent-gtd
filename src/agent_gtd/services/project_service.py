"""Project CRUD service functions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_gtd.database import decode_json_list, encode_json_list, row_to_dict
from agent_gtd.db_types import DbPool
from agent_gtd.event_bus import get_event_bus
from agent_gtd.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


def workspace_repo_dir(url: str) -> str:
    """Derive the checkout directory name from a git clone URL.

    Used for collision detection when validating workspace_repos lists.
    This is a pure function — it does not touch the filesystem.

    The formula mirrors the logic used by the dispatch host so both ends
    agree on the derived directory name without a round-trip.

    Examples:
        >>> workspace_repo_dir("https://github.com/org/repo.git")
        'repo'
        >>> workspace_repo_dir("git@github.com:org/repo.git")
        'repo'
        >>> workspace_repo_dir("https://github.com/org/repo/")
        'repo'

    Args:
        url: A git clone URL (HTTPS, SCP-style SSH, or local path).

    Returns:
        The bare directory name that ``git clone`` would create.
    """
    return url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git")


def _validate_workspace_fields(
    repo_mode: str | None,
    workspace_repos: list[str] | None,
    *,
    effective_mode: str,
    effective_repos: list[str],
) -> None:
    """Validate workspace fields and raise ValidationError on any violation.

    Validation cases (per spec):
    (a/b) effective mode 'workspace' requires at least one URL.
    (c)   any explicitly-provided list element must be non-blank after .strip().
    (d)   effective mode 'workspace': no duplicate derived dirs, no empty dir.
    (f)   provided repo_mode must be a valid RepoMode member.

    Args:
        repo_mode: The repo_mode value being set (may be None if not changing).
        workspace_repos: The workspace_repos list being set, or None if not
            changing.
        effective_mode: The post-update effective repo_mode string.
        effective_repos: The post-update effective workspace_repos list
            (already stripped).
    """
    # (f) validate repo_mode membership when provided
    if repo_mode is not None:
        from agent_gtd.models import RepoMode

        try:
            RepoMode(repo_mode)
        except ValueError as exc:
            raise ValidationError(
                f"Invalid repo_mode '{repo_mode}': must be 'monorepo' or 'workspace'"
            ) from exc

    # (c) every element in an explicitly-provided list must be non-blank
    if workspace_repos is not None:
        for url in workspace_repos:
            if not url.strip():
                raise ValidationError(
                    "workspace_repos: every element must be non-blank "
                    "after stripping whitespace"
                )

    # (a/b) workspace mode requires at least one URL
    if effective_mode == "workspace" and not effective_repos:
        raise ValidationError("workspace projects require at least one repository URL")

    # (d) dir collision and empty-dir checks (workspace mode only)
    if effective_mode == "workspace":
        seen_dirs: list[str] = []
        for url in effective_repos:
            d = workspace_repo_dir(url)
            if not d:
                raise ValidationError(
                    f"workspace_repos: URL '{url}' derives an empty checkout directory"
                )
            if d in seen_dirs:
                raise ValidationError(
                    f"workspace_repos: duplicate checkout directory '{d}'"
                )
            seen_dirs.append(d)


def _decode_project_workspace_repos(result: dict[str, Any]) -> dict[str, Any]:
    """Decode workspace_repos from JSON text to list[str] in-place.

    Handles three cases:
    - Already a list (pre-decoded by a join query): no-op.
    - A JSON text string (raw DB row): decoded via decode_json_list.
    - Missing or None: set to [].

    Args:
        result: Mutable project dict (modified in place).

    Returns:
        The same dict for chaining.
    """
    raw = result.get("workspace_repos")
    if isinstance(raw, list):
        pass  # already decoded
    elif raw:
        result["workspace_repos"] = decode_json_list(str(raw))
    else:
        result["workspace_repos"] = []
    return result


def _description_preview(description: str | None) -> str | None:
    """Return the first non-empty line of description, truncated to 80 chars.

    Args:
        description: Raw project description string, or None.

    Returns:
        First non-empty stripped line capped at 80 chars, or None if no such
        line exists (empty string, None, or whitespace-only input).
    """
    if not description:
        return None
    for line in description.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return None


async def accessible_project_ids(db: DbPool, user_id: str) -> list[str]:
    """Return all project IDs accessible to the user: owned + shared.

    A project is accessible if the user owns it (projects.user_id) or
    is listed in project_members.

    Args:
        db: Database pool.
        user_id: The calling user's ID.

    Returns:
        List of project ID strings the user can see.
    """
    rows = await db.fetch(
        "SELECT id FROM projects WHERE user_id = $1 "
        "UNION "
        "SELECT project_id FROM project_members WHERE user_id = $2",
        user_id,
        user_id,
    )
    return [str(r["id"]) for r in rows]


async def verify_project_ownership(db: DbPool, project_id: str, user_id: str) -> None:
    """Verify that a project exists and belongs to the user (owner check).

    Owner-only: use this for delete/update-metadata operations.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    row = await db.fetchrow(
        "SELECT id FROM projects WHERE id = $1 AND user_id = $2",
        project_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Project", project_id)


async def verify_project_access(db: DbPool, project_id: str, user_id: str) -> None:
    """Verify that a project exists and is accessible to the user.

    Accessible = owned by the user OR user is a project member.
    Use this for read/write-to-children operations.

    Raises:
        NotFoundError: If the project doesn't exist or isn't accessible.
    """
    row = await db.fetchrow(
        "SELECT id FROM projects WHERE id = $1 AND "
        "(user_id = $2 OR EXISTS "
        "(SELECT 1 FROM project_members WHERE project_id = $3 AND user_id = $4))",
        project_id,
        user_id,
        project_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Project", project_id)


async def list_projects(
    db: DbPool,
    user_id: str,
    *,
    status: str | None = None,
    area: str | None = None,
) -> list[dict[str, Any]]:
    """List projects for a user, with optional filters.

    Returns both owned projects and projects the user is a member of.
    """
    # Base: accessible projects (owned OR member).  $1 and $2 are both user_id;
    # using two separate params keeps the $N-to-? mapping simple for SQLite.
    clauses = [
        "(p.user_id = $1 OR p.id IN "
        "(SELECT project_id FROM project_members WHERE user_id = $2))"
    ]
    params: list[object] = [user_id, user_id]

    if status is not None:
        clauses.append(f"p.status = ${len(params) + 1}")
        params.append(status)
    if area is not None:
        clauses.append(f"p.area = ${len(params) + 1}")
        params.append(area)

    where = " AND ".join(clauses)
    rows = await db.fetch(
        f"SELECT p.*, u.email AS owner_email, "  # noqa: S608
        f"(SELECT COUNT(*) FROM project_members pm WHERE pm.project_id = p.id)"
        f" AS member_count, "
        f"(SELECT COUNT(*) FROM items i WHERE i.project_id = p.id"
        f" AND i.status != 'done')"
        f" AS total_items "
        f"FROM projects p JOIN users u ON u.id = p.user_id "
        f"WHERE {where} ORDER BY p.created_at DESC",
        *params,
    )
    results = [row_to_dict(r) for r in rows]
    for result in results:
        _decode_project_workspace_repos(result)
        result["description_preview"] = _description_preview(result.get("description"))
    return results


async def create_project(
    db: DbPool,
    user_id: str,
    *,
    name: str,
    description: str = "",
    status: str = "active",
    area: str = "",
    git_origin: str = "",
    kb_project_ref: str = "",
    repo_mode: str = "monorepo",
    workspace_repos: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new project and return its row data.

    Args:
        db: Database pool.
        user_id: Owner's user ID.
        name: Project name.
        description: Optional description.
        status: Initial status (default 'active').
        area: Optional area/category.
        git_origin: Optional git remote URL.
        kb_project_ref: Optional KB project reference.
        repo_mode: Repository mode — 'monorepo' (default) or 'workspace'.
        workspace_repos: Ordered list of git clone URLs for workspace mode.

    Returns:
        The created project row as a dict (workspace_repos decoded to list[str]).

    Raises:
        ValidationError: If the workspace fields fail validation.
    """
    # Strip URLs before validation and storage.
    stripped_repos = [u.strip() for u in (workspace_repos or [])]
    effective_mode = repo_mode

    _validate_workspace_fields(
        repo_mode,
        workspace_repos,
        effective_mode=effective_mode,
        effective_repos=stripped_repos,
    )

    now = datetime.now(UTC).isoformat()
    project_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO projects "
        "(id, user_id, name, description, status, area, git_origin,"
        " kb_project_ref, repo_mode, workspace_repos, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        project_id,
        user_id,
        name,
        description,
        status,
        area,
        git_origin,
        kb_project_ref,
        repo_mode,
        encode_json_list(stripped_repos),
        now,
        now,
    )

    row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)
    _decode_project_workspace_repos(result)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="project_created",
            entity_type="project",
            entity_id=project_id,
            project_id=project_id,
            payload=result,
        )
    except Exception:
        logger.exception("Failed to publish project_created event")

    return result


async def get_project(db: DbPool, user_id: str, project_id: str) -> dict[str, Any]:
    """Get a single project by ID.

    Returns the project if the user owns it or is a member of it.

    Raises:
        NotFoundError: If the project doesn't exist or isn't accessible.
    """
    row = await db.fetchrow(
        "SELECT p.*, u.email AS owner_email, "
        "(SELECT COUNT(*) FROM project_members pm WHERE pm.project_id = p.id)"
        " AS member_count, "
        "(SELECT COUNT(*) FROM items i WHERE i.project_id = p.id"
        " AND i.status != 'done')"
        " AS total_items "
        "FROM projects p JOIN users u ON u.id = p.user_id "
        "WHERE p.id = $1 AND "
        "(p.user_id = $2 OR EXISTS "
        "(SELECT 1 FROM project_members WHERE project_id = $3 AND user_id = $4))",
        project_id,
        user_id,
        project_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Project", project_id)
    result = row_to_dict(row)
    _decode_project_workspace_repos(result)
    result["description_preview"] = _description_preview(result.get("description"))
    return result


async def update_project(
    db: DbPool,
    user_id: str,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    area: str | None = None,
    git_origin: str | None = None,
    kb_project_ref: str | None = None,
    repo_mode: str | None = None,
    workspace_repos: list[str] | None = None,
    dispatch_max_turns: int | None = None,
    clear_dispatch_max_turns: bool = False,
    dispatch_timeout_minutes: int | None = None,
    clear_dispatch_timeout_minutes: bool = False,
    plan_dispatch_agent: str | None = None,
    clear_plan_dispatch_agent: bool = False,
    build_dispatch_agent: str | None = None,
    clear_build_dispatch_agent: bool = False,
) -> dict[str, Any]:
    """Update a project. Only non-None fields are changed.

    For nullable override columns (dispatch_max_turns, dispatch_timeout_minutes,
    plan_dispatch_agent, build_dispatch_agent):
    - Pass the value to set it.
    - Pass clear_dispatch_max_turns=True (with dispatch_max_turns=None) to set NULL.
    - Omit both to leave the column unchanged.

    For repo_mode and workspace_repos:
    - None = leave unchanged.
    - Non-None = set to that value.

    Raises:
        NotFoundError: If the project doesn't exist or isn't accessible.
        ValidationError: If the workspace fields fail validation.
    """
    # Fetch current row to (a) verify access and (b) compute effective state.
    current_row = await db.fetchrow(
        "SELECT * FROM projects WHERE id = $1 AND "
        "(user_id = $2 OR EXISTS "
        "(SELECT 1 FROM project_members WHERE project_id = $3 AND user_id = $4))",
        project_id,
        user_id,
        project_id,
        user_id,
    )
    if current_row is None:
        raise NotFoundError("Project", project_id)

    # Compute effective post-update workspace fields for validation.
    current_mode = str(current_row.get("repo_mode") or "monorepo")
    current_repos_raw = current_row.get("workspace_repos")
    if isinstance(current_repos_raw, list):
        current_repos: list[str] = current_repos_raw
    elif current_repos_raw:
        current_repos = decode_json_list(str(current_repos_raw))
    else:
        current_repos = []

    effective_mode = repo_mode if repo_mode is not None else current_mode
    stripped_repos = (
        [u.strip() for u in workspace_repos] if workspace_repos is not None else None
    )
    effective_repos = stripped_repos if stripped_repos is not None else current_repos

    _validate_workspace_fields(
        repo_mode,
        workspace_repos,
        effective_mode=effective_mode,
        effective_repos=effective_repos,
    )

    updates: list[str] = []
    params: list[object] = []

    if name is not None:
        params.append(name)
        updates.append(f"name = ${len(params)}")
    if description is not None:
        params.append(description)
        updates.append(f"description = ${len(params)}")
    if status is not None:
        params.append(status)
        updates.append(f"status = ${len(params)}")
    if area is not None:
        params.append(area)
        updates.append(f"area = ${len(params)}")
    if git_origin is not None:
        params.append(git_origin)
        updates.append(f"git_origin = ${len(params)}")
    if kb_project_ref is not None:
        params.append(kb_project_ref)
        updates.append(f"kb_project_ref = ${len(params)}")
    if repo_mode is not None:
        params.append(repo_mode)
        updates.append(f"repo_mode = ${len(params)}")
    if stripped_repos is not None:
        params.append(encode_json_list(stripped_repos))
        updates.append(f"workspace_repos = ${len(params)}")
    if dispatch_max_turns is not None:
        params.append(dispatch_max_turns)
        updates.append(f"dispatch_max_turns = ${len(params)}")
    elif clear_dispatch_max_turns:
        params.append(None)
        updates.append(f"dispatch_max_turns = ${len(params)}")
    if dispatch_timeout_minutes is not None:
        params.append(dispatch_timeout_minutes)
        updates.append(f"dispatch_timeout_minutes = ${len(params)}")
    elif clear_dispatch_timeout_minutes:
        params.append(None)
        updates.append(f"dispatch_timeout_minutes = ${len(params)}")
    if plan_dispatch_agent is not None:
        params.append(plan_dispatch_agent)
        updates.append(f"plan_dispatch_agent = ${len(params)}")
    elif clear_plan_dispatch_agent:
        params.append(None)
        updates.append(f"plan_dispatch_agent = ${len(params)}")
    if build_dispatch_agent is not None:
        params.append(build_dispatch_agent)
        updates.append(f"build_dispatch_agent = ${len(params)}")
    elif clear_build_dispatch_agent:
        params.append(None)
        updates.append(f"build_dispatch_agent = ${len(params)}")

    if updates:
        params.append(datetime.now(UTC).isoformat())
        updates.append(f"updated_at = ${len(params)}")
        params.append(project_id)

        sql = f"UPDATE projects SET {', '.join(updates)} WHERE id = ${len(params)}"  # noqa: S608
        await db.execute(sql, *params)

    row = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    assert row is not None  # noqa: S101
    result = row_to_dict(row)
    _decode_project_workspace_repos(result)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="project_updated",
            entity_type="project",
            entity_id=project_id,
            project_id=project_id,
            payload=result,
        )
    except Exception:
        logger.exception("Failed to publish project_updated event")

    return result


async def delete_project(db: DbPool, user_id: str, project_id: str) -> None:
    """Delete a project and cascade to items and notes.

    Raises:
        NotFoundError: If the project doesn't exist or isn't owned by user.
    """
    await verify_project_ownership(db, project_id, user_id)
    await db.execute("DELETE FROM projects WHERE id = $1", project_id)

    try:
        await get_event_bus().publish(
            db,
            user_id=user_id,
            event_type="project_deleted",
            entity_type="project",
            entity_id=project_id,
            project_id=project_id,
            payload={"id": project_id},
        )
    except Exception:
        logger.exception("Failed to publish project_deleted event")


async def add_project_member(
    db: DbPool,
    owner_user_id: str,
    project_id: str,
    member_email: str,
) -> dict[str, Any]:
    """Add a user to a project by email (owner-only, idempotent).

    If the user is already a member, returns the existing membership without
    creating a duplicate (idempotent).

    Args:
        db: Database pool.
        owner_user_id: Calling user's ID — must be the project owner.
        project_id: ID of the project to share.
        member_email: Email address of the user to add.

    Returns:
        Dict with user_id, email, and added_at.

    Raises:
        NotFoundError: If the project doesn't exist or caller isn't owner.
        NotFoundError: If member_email doesn't match any registered user.
        ValidationError: If trying to add the project owner as a member.
    """
    await verify_project_ownership(db, project_id, owner_user_id)

    user_row = await db.fetchrow(
        "SELECT id, email FROM users WHERE email = $1", member_email
    )
    if user_row is None:
        raise NotFoundError("User", member_email)

    member_user_id = str(user_row["id"])
    member_email_str = str(user_row["email"])

    if member_user_id == owner_user_id:
        raise ValidationError("Cannot add the project owner as a member")

    existing = await db.fetchrow(
        "SELECT added_at FROM project_members WHERE project_id = $1 AND user_id = $2",
        project_id,
        member_user_id,
    )
    if existing is not None:
        return {
            "user_id": member_user_id,
            "email": member_email_str,
            "added_at": str(existing["added_at"]),
            "blockers_purged": 0,
        }

    # Detect first-share transition BEFORE insert so idempotent re-adds don't
    # trigger a repeat purge.
    prior_count = await db.fetchrow(
        "SELECT COUNT(*) AS cnt FROM project_members WHERE project_id = $1",
        project_id,
    )
    is_first_member = prior_count is not None and int(prior_count["cnt"]) == 0

    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO project_members (project_id, user_id, added_at)"
        " VALUES ($1, $2, $3)",
        project_id,
        member_user_id,
        now,
    )

    # Purge cross-project blocker edges touching this project on first share.
    # After that, add_blocker enforces same-project so no new edges can form.
    blockers_purged = 0
    if is_first_member:
        rows = await db.fetch(
            """
            SELECT id.id
            FROM item_dependencies id
            JOIN items a ON id.item_id = a.id
            JOIN items b ON id.blocker_item_id = b.id
            WHERE (a.project_id = $1 OR b.project_id = $2)
              AND COALESCE(a.project_id, '') <> COALESCE(b.project_id, '')
            """,
            project_id,
            project_id,
        )
        for row in rows:
            await db.execute(
                "DELETE FROM item_dependencies WHERE id = $1",
                str(row["id"]),
            )
        blockers_purged = len(rows)
        if blockers_purged > 0:
            logger.info(
                "Purged %d cross-project blocker(s) when project %s was shared",
                blockers_purged,
                project_id,
            )

    return {
        "user_id": member_user_id,
        "email": member_email_str,
        "added_at": now,
        "blockers_purged": blockers_purged,
    }


async def remove_project_member(
    db: DbPool,
    owner_user_id: str,
    project_id: str,
    member_user_id: str,
) -> None:
    """Remove a member from a project (owner-only, no-op if not a member).

    Args:
        db: Database pool.
        owner_user_id: Calling user's ID — must be the project owner.
        project_id: ID of the project.
        member_user_id: ID of the user to remove.

    Raises:
        NotFoundError: If the project doesn't exist or caller isn't owner.
    """
    await verify_project_ownership(db, project_id, owner_user_id)
    await db.execute(
        "DELETE FROM project_members WHERE project_id = $1 AND user_id = $2",
        project_id,
        member_user_id,
    )


async def list_project_members(
    db: DbPool,
    user_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """List members of a project (accessible to owner and any member).

    Does NOT include the owner in the result.

    Args:
        db: Database pool.
        user_id: Calling user's ID — must be owner or member.
        project_id: ID of the project.

    Returns:
        List of dicts with user_id, email, added_at.

    Raises:
        NotFoundError: If caller can't access the project.
    """
    await verify_project_access(db, project_id, user_id)

    rows = await db.fetch(
        "SELECT pm.user_id, u.email, pm.added_at"
        " FROM project_members pm"
        " JOIN users u ON u.id = pm.user_id"
        " WHERE pm.project_id = $1"
        " ORDER BY pm.added_at",
        project_id,
    )
    return [
        {
            "user_id": str(r["user_id"]),
            "email": str(r["email"]),
            "added_at": str(r["added_at"]),
        }
        for r in rows
    ]
