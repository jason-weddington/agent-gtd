"""MCP backend abstraction — local (DB-direct) and HTTP implementations."""

# ruff: noqa: D102

from __future__ import annotations

import os
import ssl
from typing import Any, Literal, Protocol

import httpx
import truststore
from fastmcp.exceptions import ToolError

# ---------------------------------------------------------------------------
# Board-snapshot constants (mirrors item_service._TRACKED_STATUSES et al.)
# ---------------------------------------------------------------------------

_TRACKED_STATUSES = ("new", "ready", "next_action", "active", "review", "waiting_for")
_ID_PREFIX_LEN = 8
_TITLE_LEN = 60
_PER_COLUMN_CAP = 10


def _format_board_snapshot(
    items: list[dict[str, Any]],
    project_id: str,
    project_name: str,
    *,
    per_column_cap: int = _PER_COLUMN_CAP,
) -> dict[str, Any]:
    """Build a compact board-state snapshot dict from a flat list of items.

    Used by :class:`HttpBackend` which receives items from the REST API.
    Items are re-sorted by (sort_order ASC, created_at ASC) before grouping.

    Args:
        items: Raw item dicts (as returned by the REST API).
        project_id: Project ID to embed in the snapshot.
        project_name: Project name to embed in the snapshot.
        per_column_cap: Max items per column (default 10).

    Returns:
        Snapshot dict with project_id, project_name, and one list per tracked
        status.
    """
    sorted_items = sorted(
        items,
        key=lambda x: (
            float(x.get("sort_order") or 0),
            str(x.get("created_at", "")),
        ),
    )

    columns: dict[str, list[list[str]]] = {s: [] for s in _TRACKED_STATUSES}
    for item in sorted_items:
        status = str(item.get("status", ""))
        if status in columns:
            item_id = str(item["id"])
            title_trunc = str(item.get("title", ""))[:_TITLE_LEN]
            columns[status].append([item_id, title_trunc])

    snapshot: dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_name,
    }
    for status in _TRACKED_STATUSES:
        col = columns[status]
        total = len(col)
        if total > per_column_cap:
            more = f"__more__ {total - per_column_cap}"
            entries: list[Any] = [*col[:per_column_cap], more]
        else:
            entries = list(col)
        snapshot[status] = entries

    return snapshot


_COMPACT_ITEM_KEYS = (
    "id",
    "title",
    "status",
    "priority",
    "build_engine",
    "project_id",
    "project_name",
    "project_repo_mode",
    "labels",
    "assigned_to",
    "created_by",
    "created_at",
    "updated_at",
)
_DESCRIPTION_SNIPPET_LEN = 140


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a compact representation of an item with a 16-key whitelist.

    Computes ac_count, files_count, and description_snippet from the full
    item dict.  Accepts acceptance_criteria and files_to_modify as either
    raw JSON strings (LocalBackend) or already-decoded lists (HttpBackend).

    Args:
        item: Full item dict from _format_item or _enrich_item.

    Returns:
        Dict with exactly 16 keys: the 13 whitelist columns plus ac_count,
        files_count, and description_snippet.
    """
    import json as _json

    def _count_json_or_list(val: Any) -> int:
        if val is None:
            return 0
        if isinstance(val, list):
            return len(val)
        if isinstance(val, str):
            try:
                parsed = _json.loads(val)
                return len(parsed) if isinstance(parsed, list) else 0
            except (ValueError, TypeError):
                return 0
        return 0

    ac_count = _count_json_or_list(item.get("acceptance_criteria"))
    files_count = _count_json_or_list(item.get("files_to_modify"))

    raw_desc = item.get("description") or ""
    if len(raw_desc) > _DESCRIPTION_SNIPPET_LEN:
        description_snippet = raw_desc[:_DESCRIPTION_SNIPPET_LEN] + "…"
    else:
        description_snippet = raw_desc

    compact: dict[str, Any] = {k: item.get(k) for k in _COMPACT_ITEM_KEYS}
    compact["ac_count"] = ac_count
    compact["files_count"] = files_count
    compact["description_snippet"] = description_snippet
    return compact


class McpBackend(Protocol):
    """Protocol for MCP backend implementations."""

    async def login(self, api_key: str, agent_name: str) -> dict[str, str]: ...

    async def get_project(self, user_id: str, project_id: str) -> dict[str, Any]: ...

    async def list_projects(
        self, user_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def create_project(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        area: str = "",
        status: str = "active",
        git_origin: str = "",
        kb_project_ref: str = "",
        repo_mode: str = "monorepo",
        workspace_repos: list[str] | None = None,
        dispatch_max_turns: int | None = None,
        dispatch_timeout_minutes: int | None = None,
        plan_dispatch_agent: str | None = None,
        build_dispatch_agent: str | None = None,
        gate_command: str | None = None,
    ) -> dict[str, Any]: ...

    async def update_project(
        self,
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
        gate_command: str | None = None,
        clear_gate_command: bool = False,
    ) -> dict[str, Any]: ...

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        detail: bool = False,
    ) -> dict[str, Any]: ...

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

    async def create_item(
        self,
        user_id: str,
        *,
        title: str,
        description: str = "",
        priority: str = "normal",
        status: str = "inbox",
        labels: list[str] | None = None,
        project_id: str | None = None,
        created_by: str = "human",
        due_date: str | None = None,
        build_engine: str | None = None,
    ) -> dict[str, Any]: ...

    async def update_item(
        self,
        user_id: str,
        item_id: str,
        *,
        version: int,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        due_date_set: bool = False,
        build_engine: str | None = None,
        build_engine_set: bool = False,
        acceptance_criteria: list[str] | None = None,
        files_to_modify: list[dict[str, Any]] | None = None,
        scope_out: list[str] | None = None,
        project_id: str | None = None,
        project_id_set: bool = False,
    ) -> dict[str, Any]: ...

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

    async def inbox_capture(
        self, user_id: str, title: str, *, created_by: str = "human"
    ) -> dict[str, Any]: ...

    async def list_notes(
        self, user_id: str, *, project_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def get_note(self, user_id: str, note_id: str) -> dict[str, Any]: ...

    async def create_note(
        self,
        user_id: str,
        project_id: str,
        *,
        title: str = "",
        content_markdown: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def update_note(
        self,
        user_id: str,
        note_id: str,
        *,
        title: str | None = None,
        content_markdown: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def delete_note(self, user_id: str, note_id: str) -> dict[str, Any]: ...

    async def list_comments(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def create_comment(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        content_markdown: str = "",
        created_by: str | None = None,
    ) -> dict[str, Any]: ...

    async def update_comment(
        self,
        user_id: str,
        comment_id: str,
        *,
        content_markdown: str | None = None,
    ) -> dict[str, Any]: ...

    async def delete_comment(self, user_id: str, comment_id: str) -> None: ...

    async def dispatch_item(
        self,
        user_id: str,
        item_id: str,
        *,
        max_turns: int | None = None,
        mode: str = "build",
        rollout_id: str | None = None,
        dispatch_host_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def dispatch_rollout(
        self, user_id: str, rollout_id: str
    ) -> dict[str, Any]: ...

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]: ...

    async def get_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]: ...

    async def list_rollouts(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...

    async def get_rollout_plan(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]: ...

    async def list_runs(
        self,
        user_id: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list_dispatch_hosts(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]: ...

    async def add_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> dict[str, Any]: ...

    async def remove_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> None: ...

    async def list_blockers(
        self,
        user_id: str,
        item_id: str,
    ) -> list[dict[str, Any]]: ...

    async def add_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> dict[str, Any]: ...

    async def remove_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> None: ...

    async def list_project_members(
        self,
        user_id: str,
        project_id: str,
    ) -> list[dict[str, Any]]: ...

    async def plan_rollout(
        self,
        user_id: str,
        item_ids: list[str],
    ) -> dict[str, Any]: ...

    async def advance_rollout(
        self, user_id: str, rollout_id: str
    ) -> dict[str, Any]: ...

    async def complete_item_in_rollout(
        self,
        user_id: str,
        rollout_id: str,
        item_id: str,
        outcome: Literal["completed", "halted", "skipped"],
        *,
        merge_actor: Literal[
            "human",
            "manager-allowlist",
            "manager-autonomous",
            "manager+human-fixup",
            "",
        ] = "",
        decision_rule: Literal["", "agent-judgment"] = "",
    ) -> dict[str, Any]: ...

    async def halt_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
        *,
        comment: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def cancel_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
    ) -> dict[str, Any]: ...

    async def replan_rollout(
        self,
        user_id: str,
        rollout_id: str,
        *,
        from_item: str | None = None,
    ) -> dict[str, Any]: ...

    async def start_rollout(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]: ...

    async def update_rollout_state(
        self,
        user_id: str,
        rollout_id: str,
        phase: Literal[
            "warm_up",
            "dispatching",
            "polling",
            "reviewing",
            "merging",
            "reconciling_ac",
            "halted",
        ],
        current_item_id: str | None = None,
        current_step: str | None = None,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Local backend — direct database access via service layer
# ---------------------------------------------------------------------------


class LocalBackend:
    """Backend that calls the service layer directly (DB access)."""

    async def login(self, api_key: str, agent_name: str) -> dict[str, str]:
        from agent_gtd.auth import hash_api_key
        from agent_gtd.database import get_db

        db = await get_db()
        h = hash_api_key(api_key)
        row = await db.fetchrow("SELECT user_id FROM api_keys WHERE key_hash = $1", h)
        if row is None:
            raise ToolError("Invalid API key")

        user_id = row["user_id"]
        user_row = await db.fetchrow("SELECT email FROM users WHERE id = $1", user_id)
        if user_row is None:
            raise ToolError("User not found for this API key")

        return {
            "user_id": user_id,
            "agent_name": agent_name,
            "email": user_row["email"],
        }

    async def get_project(self, user_id: str, project_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        return await project_service.get_project(db, user_id, project_id)

    async def list_projects(
        self, user_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        return await project_service.list_projects(db, user_id, status=status)

    async def create_project(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        area: str = "",
        status: str = "active",
        git_origin: str = "",
        kb_project_ref: str = "",
        repo_mode: str = "monorepo",
        workspace_repos: list[str] | None = None,
        dispatch_max_turns: int | None = None,
        dispatch_timeout_minutes: int | None = None,
        plan_dispatch_agent: str | None = None,
        build_dispatch_agent: str | None = None,
        gate_command: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        result = await project_service.create_project(
            db,
            user_id,
            name=name,
            description=description,
            area=area,
            status=status,
            git_origin=git_origin,
            kb_project_ref=kb_project_ref,
            repo_mode=repo_mode,
            workspace_repos=workspace_repos,
            gate_command=gate_command,
        )
        # Apply dispatch overrides immediately after creation if any are provided.
        if any(
            f is not None
            for f in [
                dispatch_max_turns,
                dispatch_timeout_minutes,
                plan_dispatch_agent,
                build_dispatch_agent,
            ]
        ):
            project_id = str(result["id"])
            result = await project_service.update_project(
                db,
                user_id,
                project_id,
                dispatch_max_turns=dispatch_max_turns,
                dispatch_timeout_minutes=dispatch_timeout_minutes,
                plan_dispatch_agent=plan_dispatch_agent,
                build_dispatch_agent=build_dispatch_agent,
            )
        return result

    async def update_project(
        self,
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
        gate_command: str | None = None,
        clear_gate_command: bool = False,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.exceptions import ValidationError
        from agent_gtd.services import project_service

        db = await get_db()

        # Ownership guard: only the project owner may change dispatch-only fields
        # (dispatch overrides + clone-target fields that control which repos agents
        # clone/push to: git_origin, repo_mode, workspace_repos).
        dispatch_only_touched = (
            dispatch_max_turns is not None
            or clear_dispatch_max_turns
            or dispatch_timeout_minutes is not None
            or clear_dispatch_timeout_minutes
            or plan_dispatch_agent is not None
            or clear_plan_dispatch_agent
            or build_dispatch_agent is not None
            or clear_build_dispatch_agent
            or gate_command is not None
            or clear_gate_command
            or git_origin is not None
            or repo_mode is not None
            or workspace_repos is not None
        )
        if dispatch_only_touched:
            row = await db.fetchrow(
                "SELECT user_id FROM projects WHERE id = $1", project_id
            )
            if row is None or str(row["user_id"]) != user_id:
                raise ValidationError(
                    "Only the project owner can edit dispatch settings"
                )

        return await project_service.update_project(
            db,
            user_id,
            project_id,
            name=name,
            description=description,
            status=status,
            area=area,
            git_origin=git_origin,
            kb_project_ref=kb_project_ref,
            repo_mode=repo_mode,
            workspace_repos=workspace_repos,
            dispatch_max_turns=dispatch_max_turns,
            clear_dispatch_max_turns=clear_dispatch_max_turns,
            dispatch_timeout_minutes=dispatch_timeout_minutes,
            clear_dispatch_timeout_minutes=clear_dispatch_timeout_minutes,
            plan_dispatch_agent=plan_dispatch_agent,
            clear_plan_dispatch_agent=clear_plan_dispatch_agent,
            build_dispatch_agent=build_dispatch_agent,
            clear_build_dispatch_agent=clear_build_dispatch_agent,
            gate_command=gate_command,
            clear_gate_command=clear_gate_command,
        )

    async def _build_project_map(self, user_id: str) -> dict[str, dict[str, Any]]:
        result = await self.list_projects(user_id)
        return {
            p["id"]: {
                "name": p["name"],
                "repo_mode": p.get("repo_mode"),
                "workspace_repos": p.get("workspace_repos") or [],
            }
            for p in result
        }

    async def _board_snapshot(
        self, db: Any, user_id: str, project_id: str
    ) -> dict[str, Any]:
        from agent_gtd.services import item_service

        return await item_service.board_snapshot(db, user_id, project_id)

    async def _inbox_pending_count(self, db: Any, user_id: str) -> int:
        from agent_gtd.services import item_service

        return await item_service.inbox_pending_count(db, user_id)

    def _format_item(
        self, row: dict[str, Any], project_map: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        from agent_gtd.services.item_service import item_row_to_response_dict

        result = item_row_to_response_dict(row)
        pid = row.get("project_id")
        if pid:
            entry = project_map.get(pid)
            result["project_name"] = entry["name"] if entry else ""
            result["project_repo_mode"] = entry["repo_mode"] if entry else None
        else:
            result["project_repo_mode"] = None
        return result

    def _format_note(
        self, row: dict[str, Any], project_map: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        from agent_gtd.database import decode_json_list

        result = {**row, "labels": decode_json_list(str(row["labels"]))}
        pid = row.get("project_id")
        if pid:
            entry = project_map.get(pid)
            result["project_name"] = entry["name"] if entry else ""
        return result

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        detail: bool = False,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        rows = await item_service.list_items(
            db,
            user_id,
            status=status,
            project_id=project_id,
            priority=priority,
            assigned_to=assigned_to,
        )
        pm = await self._build_project_map(user_id)
        formatted = [self._format_item(r, pm) for r in rows]
        items = formatted if detail else [_compact_item(x) for x in formatted]
        result: dict[str, Any] = {"items": items}
        if project_id is None:
            result["inbox_pending_count"] = await self._inbox_pending_count(db, user_id)
        return result

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.get_item(db, user_id, item_id)
        blocker_rows = await item_service.list_blockers(db, user_id, item_id)
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        result["blockers"] = blocker_rows
        pid = row.get("project_id")
        if pid:
            entry = pm.get(str(pid))
            if entry and entry.get("repo_mode") == "workspace":
                result["workspace_repos"] = list(entry.get("workspace_repos") or [])
            result["board_state"] = await self._board_snapshot(
                db, user_id, str(row["project_id"])
            )
        return result

    async def create_item(
        self,
        user_id: str,
        *,
        title: str,
        description: str = "",
        priority: str = "normal",
        status: str = "inbox",
        labels: list[str] | None = None,
        project_id: str | None = None,
        created_by: str = "human",
        due_date: str | None = None,
        build_engine: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        # Treat "" (clear/no-engine sentinel) the same as None so the item is
        # created with no engine (inherits global default).
        row = await item_service.create_item(
            db,
            user_id,
            title=title,
            description=description,
            project_id=project_id,
            status=status,
            priority=priority,
            created_by=created_by,
            labels=labels,
            due_date=due_date,
            build_engine=build_engine or None,
        )
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        if project_id is not None:
            result["board_state"] = await self._board_snapshot(db, user_id, project_id)
        else:
            result["inbox_pending_count"] = await self._inbox_pending_count(db, user_id)
        return result

    async def update_item(
        self,
        user_id: str,
        item_id: str,
        *,
        version: int,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        due_date_set: bool = False,
        build_engine: str | None = None,
        build_engine_set: bool = False,
        acceptance_criteria: list[str] | None = None,
        files_to_modify: list[dict[str, Any]] | None = None,
        scope_out: list[str] | None = None,
        project_id: str | None = None,
        project_id_set: bool = False,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.update_item(
            db,
            user_id,
            item_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            labels=labels,
            due_date=due_date,
            due_date_set=due_date_set,
            build_engine=build_engine,
            build_engine_set=build_engine_set,
            acceptance_criteria=acceptance_criteria,
            files_to_modify=files_to_modify,
            scope_out=scope_out,
            project_id=project_id,
            project_id_set=project_id_set,
            version=version,
        )
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        if row.get("project_id"):
            result["board_state"] = await self._board_snapshot(
                db, user_id, str(row["project_id"])
            )
        return result

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.complete_item(db, user_id, item_id)
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        if row.get("project_id"):
            result["board_state"] = await self._board_snapshot(
                db, user_id, str(row["project_id"])
            )
        return result

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        # Fetch project_id before deletion (for post-deletion snapshot)
        existing = await item_service.get_item(db, user_id, item_id)
        project_id = str(existing["project_id"]) if existing.get("project_id") else None
        await item_service.delete_item(db, user_id, item_id)
        result: dict[str, Any] = {"status": "deleted", "item_id": item_id}
        if project_id:
            result["board_state"] = await self._board_snapshot(db, user_id, project_id)
        return result

    async def inbox_capture(
        self, user_id: str, title: str, *, created_by: str = "human"
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.inbox_capture(
            db,
            user_id,
            title,
            created_by=created_by,
        )
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        result["inbox_pending_count"] = await self._inbox_pending_count(db, user_id)
        return result

    async def list_notes(
        self, user_id: str, *, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import note_service

        db = await get_db()
        if project_id is not None:
            rows = await note_service.list_project_notes(db, user_id, project_id)
        else:
            rows = await note_service.list_user_notes(db, user_id)
        pm = await self._build_project_map(user_id)
        return [self._format_note(r, pm) for r in rows]

    async def get_note(self, user_id: str, note_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import note_service

        db = await get_db()
        row = await note_service.get_note(db, user_id, note_id)
        pm = await self._build_project_map(user_id)
        result = self._format_note(row, pm)
        if row.get("project_id"):
            result["board_state"] = await self._board_snapshot(
                db, user_id, str(row["project_id"])
            )
        return result

    async def create_note(
        self,
        user_id: str,
        project_id: str,
        *,
        title: str = "",
        content_markdown: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import note_service

        db = await get_db()
        row = await note_service.create_note(
            db,
            user_id,
            project_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
        pm = await self._build_project_map(user_id)
        result = self._format_note(row, pm)
        result["board_state"] = await self._board_snapshot(db, user_id, project_id)
        return result

    async def update_note(
        self,
        user_id: str,
        note_id: str,
        *,
        title: str | None = None,
        content_markdown: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import note_service

        db = await get_db()
        row = await note_service.update_note(
            db,
            user_id,
            note_id,
            title=title,
            content_markdown=content_markdown,
            labels=labels,
        )
        pm = await self._build_project_map(user_id)
        result = self._format_note(row, pm)
        if row.get("project_id"):
            result["board_state"] = await self._board_snapshot(
                db, user_id, str(row["project_id"])
            )
        return result

    async def delete_note(self, user_id: str, note_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import note_service

        db = await get_db()
        await note_service.delete_note(db, user_id, note_id)
        return {"deleted": True, "note_id": note_id}

    async def list_comments(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import comment_service

        db = await get_db()
        return await comment_service.list_comments(
            db, user_id, project_id=project_id, item_id=item_id
        )

    async def create_comment(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        content_markdown: str = "",
        created_by: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.identity import get_current_actor_attribution
        from agent_gtd.services import comment_service, item_service

        db = await get_db()
        resolved_by = (
            created_by if created_by is not None else get_current_actor_attribution()
        )
        result = await comment_service.create_comment(
            db,
            user_id,
            project_id=project_id,
            item_id=item_id,
            content_markdown=content_markdown,
            created_by=resolved_by,
        )
        # Inject board_state when commenting on an item that belongs to a project
        if item_id is not None:
            item_row = await item_service.get_item(db, user_id, item_id)
            item_project_id = item_row.get("project_id")
            if item_project_id:
                result["board_state"] = await self._board_snapshot(
                    db, user_id, str(item_project_id)
                )
        return result

    async def update_comment(
        self,
        user_id: str,
        comment_id: str,
        *,
        content_markdown: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import comment_service, item_service

        db = await get_db()
        result = await comment_service.update_comment(
            db, user_id, comment_id, content_markdown=content_markdown
        )
        # Inject board_state when this is a comment on an item in a project
        comment_item_id = result.get("item_id")
        if comment_item_id:
            item_row = await item_service.get_item(db, user_id, str(comment_item_id))
            item_project_id = item_row.get("project_id")
            if item_project_id:
                result["board_state"] = await self._board_snapshot(
                    db, user_id, str(item_project_id)
                )
        return result

    async def delete_comment(self, user_id: str, comment_id: str) -> None:
        from agent_gtd.database import get_db
        from agent_gtd.services import comment_service

        db = await get_db()
        await comment_service.delete_comment(db, user_id, comment_id)

    async def dispatch_item(
        self,
        user_id: str,
        item_id: str,
        *,
        max_turns: int | None = None,
        mode: str = "build",
        rollout_id: str | None = None,
        dispatch_host_id: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import create_run

        db = await get_db()
        return await create_run(
            db,
            user_id,
            item_id,
            max_turns=max_turns,
            mode=mode,
            rollout_id=rollout_id,
            dispatch_host_id=dispatch_host_id,
        )

    async def dispatch_rollout(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import dispatch_rollout_run

        db = await get_db()
        return await dispatch_rollout_run(db, user_id, rollout_id)

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import get_run

        db = await get_db()
        return await get_run(db, user_id, run_id)

    async def get_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.rollout_service import get_rollout

        db = await get_db()
        return await get_rollout(db, user_id, rollout_id)

    async def list_rollouts(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.list_rollouts(
            db, user_id, project_id=project_id, status=status, limit=limit
        )

    async def get_rollout_plan(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.get_rollout_plan(db, user_id, rollout_id)

    async def list_runs(
        self,
        user_id: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import list_runs

        db = await get_db()
        return await list_runs(db, user_id, item_id=item_id, status=status)

    async def list_dispatch_hosts(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import settings_service

        db = await get_db()
        hosts = await settings_service.get_dispatch_hosts(db, user_id)
        # Project down to non-secret fields only — never return api_key.
        return [{"id": h["id"], "label": h["label"], "url": h["url"]} for h in hosts]

    async def add_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        return await item_service.add_blocker(db, user_id, item_id, blocker_item_id)

    async def remove_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> None:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        await item_service.remove_blocker(db, user_id, item_id, blocker_item_id)

    async def list_blockers(
        self,
        user_id: str,
        item_id: str,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        return await item_service.list_blockers(db, user_id, item_id)

    async def add_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        return await project_service.add_project_member(db, user_id, project_id, email)

    async def remove_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> None:
        from agent_gtd.database import get_db
        from agent_gtd.exceptions import NotFoundError
        from agent_gtd.services import project_service

        db = await get_db()
        row = await db.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if row is None:
            raise NotFoundError("User", email)
        member_user_id = str(row["id"])
        await project_service.remove_project_member(
            db, user_id, project_id, member_user_id
        )

    async def list_project_members(
        self,
        user_id: str,
        project_id: str,
    ) -> list[dict[str, Any]]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        return await project_service.list_project_members(db, user_id, project_id)

    async def plan_rollout(
        self,
        user_id: str,
        item_ids: list[str],
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.plan_rollout(db, user_id, item_ids)

    async def advance_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.advance_rollout(db, user_id, rollout_id)

    async def complete_item_in_rollout(
        self,
        user_id: str,
        rollout_id: str,
        item_id: str,
        outcome: Literal["completed", "halted", "skipped"],
        *,
        merge_actor: Literal[
            "human",
            "manager-allowlist",
            "manager-autonomous",
            "manager+human-fixup",
            "",
        ] = "",
        decision_rule: Literal["", "agent-judgment"] = "",
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.complete_item_in_rollout(
            db,
            user_id,
            rollout_id,
            item_id,
            outcome,
            merge_actor=merge_actor,
            decision_rule=decision_rule,
        )

    async def halt_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
        *,
        comment: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.halt_rollout(
            db,
            user_id,
            rollout_id,
            reason,
            comment=comment,
            item_id=item_id,
        )

    async def start_rollout(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.start_rollout(db, user_id, rollout_id)

    async def cancel_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.cancel_rollout(db, user_id, rollout_id, reason)

    async def replan_rollout(
        self,
        user_id: str,
        rollout_id: str,
        *,
        from_item: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.replan_rollout(
            db, user_id, rollout_id, from_item=from_item
        )

    async def update_rollout_state(
        self,
        user_id: str,
        rollout_id: str,
        phase: Literal[
            "warm_up",
            "dispatching",
            "polling",
            "reviewing",
            "merging",
            "reconciling_ac",
            "halted",
        ],
        current_item_id: str | None = None,
        current_step: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import rollout_service

        db = await get_db()
        return await rollout_service.update_rollout_state(
            db,
            user_id,
            rollout_id,
            phase=phase,
            current_item_id=current_item_id,
            current_step=current_step,
        )

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# HTTP backend — calls the FastAPI HTTP API
# ---------------------------------------------------------------------------


class HttpBackend:
    """Backend that calls the FastAPI HTTP API via httpx."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        """Initialize with base URL and optional API key."""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        self._project_cache: dict[str, dict[str, Any]] | None = None

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ToolError("Not logged in — call login first")
        return {"Authorization": f"Bearer {self._api_key}"}

    def _check(self, resp: httpx.Response) -> None:
        """Raise ToolError for non-2xx responses."""
        if resp.is_success:
            return
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ToolError(f"{detail}")

    async def _get_project_map(self) -> dict[str, dict[str, Any]]:
        if self._project_cache is not None:
            return self._project_cache
        resp = await self._client.get("/api/projects", headers=self._headers())
        self._check(resp)
        projects = resp.json()
        self._project_cache = {
            p["id"]: {
                "name": p["name"],
                "repo_mode": p.get("repo_mode"),
                "workspace_repos": p.get("workspace_repos") or [],
            }
            for p in projects
        }
        return self._project_cache

    def _enrich_item(
        self, item: dict[str, Any], pm: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        pid = item.get("project_id")
        if pid:
            entry = pm.get(pid)
            item["project_name"] = entry["name"] if entry else ""
            item["project_repo_mode"] = entry["repo_mode"] if entry else None
        else:
            item["project_repo_mode"] = None
        return item

    def _enrich_note(
        self, note: dict[str, Any], pm: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        pid = note.get("project_id")
        if pid:
            entry = pm.get(pid)
            note["project_name"] = entry["name"] if entry else ""
        return note

    async def _board_snapshot(self, project_id: str) -> dict[str, Any]:
        """Build a board snapshot via HTTP: fetch project + items, then format."""
        proj_resp = await self._client.get(
            f"/api/projects/{project_id}", headers=self._headers()
        )
        self._check(proj_resp)
        project_name: str = proj_resp.json().get("name", "")

        items_resp = await self._client.get(
            "/api/items",
            params={"project_id": project_id},
            headers=self._headers(),
        )
        self._check(items_resp)
        items: list[dict[str, Any]] = items_resp.json()
        return _format_board_snapshot(items, project_id, project_name)

    async def _inbox_pending_count(self) -> int:
        """Return the number of inbox items for the authenticated user."""
        resp = await self._client.get(
            "/api/items",
            params={"status": "inbox"},
            headers=self._headers(),
        )
        self._check(resp)
        return len(resp.json())

    async def login(self, api_key: str, agent_name: str) -> dict[str, str]:
        self._api_key = api_key
        self._project_cache = None
        resp = await self._client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._check(resp)
        user = resp.json()
        return {
            "user_id": user["id"],
            "agent_name": agent_name,
            "email": user["email"],
        }

    async def get_project(self, user_id: str, project_id: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"/api/projects/{project_id}", headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def list_projects(
        self, user_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        resp = await self._client.get(
            "/api/projects", params=params, headers=self._headers()
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def create_project(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        area: str = "",
        status: str = "active",
        git_origin: str = "",
        kb_project_ref: str = "",
        repo_mode: str = "monorepo",
        workspace_repos: list[str] | None = None,
        dispatch_max_turns: int | None = None,
        dispatch_timeout_minutes: int | None = None,
        plan_dispatch_agent: str | None = None,
        build_dispatch_agent: str | None = None,
        gate_command: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "description": description,
            "area": area,
            "status": status,
        }
        if git_origin:
            body["git_origin"] = git_origin
        if kb_project_ref:
            body["kb_project_ref"] = kb_project_ref
        # Include workspace fields only when non-default (keeps old-payload bodies
        # byte-identical so hosts and app can deploy at different times).
        if repo_mode != "monorepo":
            body["repo_mode"] = repo_mode
        if workspace_repos is not None:
            body["workspace_repos"] = workspace_repos
        if gate_command is not None:
            body["gate_command"] = gate_command
        resp = await self._client.post(
            "/api/projects",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        self._project_cache = None  # invalidate cache
        result: dict[str, Any] = resp.json()
        # Apply dispatch overrides via PATCH if any are provided.
        if any(
            f is not None
            for f in [
                dispatch_max_turns,
                dispatch_timeout_minutes,
                plan_dispatch_agent,
                build_dispatch_agent,
            ]
        ):
            result = await self.update_project(
                user_id,
                result["id"],
                dispatch_max_turns=dispatch_max_turns,
                dispatch_timeout_minutes=dispatch_timeout_minutes,
                plan_dispatch_agent=plan_dispatch_agent,
                build_dispatch_agent=build_dispatch_agent,
            )
        return result

    async def update_project(
        self,
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
        gate_command: str | None = None,
        clear_gate_command: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if status is not None:
            body["status"] = status
        if area is not None:
            body["area"] = area
        if git_origin is not None:
            body["git_origin"] = git_origin
        if kb_project_ref is not None:
            body["kb_project_ref"] = kb_project_ref
        # Workspace fields: include only when explicitly provided (not None).
        if repo_mode is not None:
            body["repo_mode"] = repo_mode
        if workspace_repos is not None:
            body["workspace_repos"] = workspace_repos
        # Dispatch override fields: send value to set, send null to clear,
        # omit to leave unchanged.  The REST API uses model_fields_set to
        # distinguish "explicit null" (clear) from "absent" (unchanged).
        if dispatch_max_turns is not None:
            body["dispatch_max_turns"] = dispatch_max_turns
        elif clear_dispatch_max_turns:
            body["dispatch_max_turns"] = None
        if dispatch_timeout_minutes is not None:
            body["dispatch_timeout_minutes"] = dispatch_timeout_minutes
        elif clear_dispatch_timeout_minutes:
            body["dispatch_timeout_minutes"] = None
        if plan_dispatch_agent is not None:
            body["plan_dispatch_agent"] = plan_dispatch_agent
        elif clear_plan_dispatch_agent:
            body["plan_dispatch_agent"] = None
        if build_dispatch_agent is not None:
            body["build_dispatch_agent"] = build_dispatch_agent
        elif clear_build_dispatch_agent:
            body["build_dispatch_agent"] = None
        if gate_command is not None:
            body["gate_command"] = gate_command
        elif clear_gate_command:
            body["gate_command"] = None
        resp = await self._client.patch(
            f"/api/projects/{project_id}",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        self._project_cache = None  # invalidate cache
        result: dict[str, Any] = resp.json()
        return result

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        detail: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if project_id:
            params["project_id"] = project_id
        if priority:
            params["priority"] = priority
        if assigned_to:
            params["assigned_to"] = assigned_to
        resp = await self._client.get(
            "/api/items", params=params, headers=self._headers()
        )
        self._check(resp)
        items = resp.json()
        pm = await self._get_project_map()
        enriched = [self._enrich_item(i, pm) for i in items]
        formatted_items = enriched if detail else [_compact_item(x) for x in enriched]
        result: dict[str, Any] = {"items": formatted_items}
        if project_id is None:
            result["inbox_pending_count"] = await self._inbox_pending_count()
        return result

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/items/{item_id}", headers=self._headers())
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_item(item, pm)
        pid = item.get("project_id")
        if pid:
            entry = pm.get(str(pid))
            if entry and entry.get("repo_mode") == "workspace":
                result["workspace_repos"] = list(entry.get("workspace_repos") or [])
            result["board_state"] = await self._board_snapshot(str(item["project_id"]))
        return result

    async def create_item(
        self,
        user_id: str,
        *,
        title: str,
        description: str = "",
        priority: str = "normal",
        status: str = "inbox",
        labels: list[str] | None = None,
        project_id: str | None = None,
        created_by: str = "human",
        due_date: str | None = None,
        build_engine: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "priority": priority,
            "status": status,
            "created_by": created_by,
        }
        if labels is not None:
            body["labels"] = labels
        if project_id is not None:
            body["project_id"] = project_id
        if due_date is not None:
            body["due_date"] = due_date
        # Treat "" (clear/no-engine sentinel) the same as None: omit from the
        # body so the item is created with no engine (inherits global default).
        if build_engine:
            body["build_engine"] = build_engine
        resp = await self._client.post(
            "/api/items",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_item(item, pm)
        if project_id is not None:
            result["board_state"] = await self._board_snapshot(project_id)
        else:
            result["inbox_pending_count"] = await self._inbox_pending_count()
        return result

    async def update_item(
        self,
        user_id: str,
        item_id: str,
        *,
        version: int,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        due_date_set: bool = False,
        build_engine: str | None = None,
        build_engine_set: bool = False,
        acceptance_criteria: list[str] | None = None,
        files_to_modify: list[dict[str, Any]] | None = None,
        scope_out: list[str] | None = None,
        project_id: str | None = None,
        project_id_set: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"version": version}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if status is not None:
            body["status"] = status
        if priority is not None:
            body["priority"] = priority
        if assigned_to is not None:
            body["assigned_to"] = assigned_to
        if labels is not None:
            body["labels"] = labels
        if due_date_set:
            body["due_date"] = due_date
        if build_engine_set:
            body["build_engine"] = build_engine
        if acceptance_criteria is not None:
            body["acceptance_criteria"] = acceptance_criteria
        if files_to_modify is not None:
            body["files_to_modify"] = files_to_modify
        if scope_out is not None:
            body["scope_out"] = scope_out
        if project_id_set:
            body["project_id"] = project_id
        resp = await self._client.patch(
            f"/api/items/{item_id}",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_item(item, pm)
        if item.get("project_id"):
            result["board_state"] = await self._board_snapshot(str(item["project_id"]))
        return result

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/items/{item_id}/complete", headers=self._headers()
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_item(item, pm)
        if item.get("project_id"):
            result["board_state"] = await self._board_snapshot(str(item["project_id"]))
        return result

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        # Fetch project_id before deletion (for post-deletion snapshot)
        get_resp = await self._client.get(
            f"/api/items/{item_id}", headers=self._headers()
        )
        self._check(get_resp)
        project_id: str | None = get_resp.json().get("project_id")

        resp = await self._client.delete(
            f"/api/items/{item_id}", headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = {"status": "deleted", "item_id": item_id}
        if project_id:
            result["board_state"] = await self._board_snapshot(project_id)
        return result

    async def inbox_capture(
        self, user_id: str, title: str, *, created_by: str = "human"
    ) -> dict[str, Any]:
        body = {"title": title, "created_by": created_by}
        resp = await self._client.post(
            "/api/inbox",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_item(item, pm)
        result["inbox_pending_count"] = await self._inbox_pending_count()
        return result

    async def list_notes(
        self, user_id: str, *, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        resp = await self._client.get(
            "/api/notes", params=params, headers=self._headers()
        )
        self._check(resp)
        notes = resp.json()
        pm = await self._get_project_map()
        return [self._enrich_note(n, pm) for n in notes]

    async def get_note(self, user_id: str, note_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/notes/{note_id}", headers=self._headers())
        self._check(resp)
        note = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_note(note, pm)
        if note.get("project_id"):
            result["board_state"] = await self._board_snapshot(str(note["project_id"]))
        return result

    async def create_note(
        self,
        user_id: str,
        project_id: str,
        *,
        title: str = "",
        content_markdown: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "content_markdown": content_markdown,
        }
        if labels is not None:
            body["labels"] = labels
        resp = await self._client.post(
            f"/api/projects/{project_id}/notes",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        note = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_note(note, pm)
        result["board_state"] = await self._board_snapshot(project_id)
        return result

    async def update_note(
        self,
        user_id: str,
        note_id: str,
        *,
        title: str | None = None,
        content_markdown: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if content_markdown is not None:
            body["content_markdown"] = content_markdown
        if labels is not None:
            body["labels"] = labels
        resp = await self._client.patch(
            f"/api/notes/{note_id}",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        note = resp.json()
        pm = await self._get_project_map()
        result = self._enrich_note(note, pm)
        if note.get("project_id"):
            result["board_state"] = await self._board_snapshot(str(note["project_id"]))
        return result

    async def delete_note(self, user_id: str, note_id: str) -> dict[str, Any]:
        resp = await self._client.delete(
            f"/api/notes/{note_id}", headers=self._headers()
        )
        self._check(resp)
        return {"deleted": True, "note_id": note_id}

    async def list_comments(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if item_id:
            params["item_id"] = item_id
        resp = await self._client.get(
            "/api/comments", params=params, headers=self._headers()
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def create_comment(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        content_markdown: str = "",
        created_by: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content_markdown": content_markdown}
        # Only include created_by when explicitly provided — omitting it lets the
        # server apply its own fallback (get_current_actor_attribution), while
        # providing it (even as an empty string) is taken as the caller's intent.
        if created_by is not None:
            body["created_by"] = created_by
        if project_id:
            path = f"/api/projects/{project_id}/comments"
        elif item_id:
            path = f"/api/items/{item_id}/comments"
        else:
            raise ToolError("Either project_id or item_id is required")
        resp = await self._client.post(path, json=body, headers=self._headers())
        self._check(resp)
        result: dict[str, Any] = resp.json()
        # Inject board_state when commenting on an item in a project
        if item_id is not None:
            item_resp = await self._client.get(
                f"/api/items/{item_id}", headers=self._headers()
            )
            self._check(item_resp)
            item_project_id: str | None = item_resp.json().get("project_id")
            if item_project_id:
                result["board_state"] = await self._board_snapshot(item_project_id)
        return result

    async def update_comment(
        self,
        user_id: str,
        comment_id: str,
        *,
        content_markdown: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if content_markdown is not None:
            body["content_markdown"] = content_markdown
        resp = await self._client.patch(
            f"/api/comments/{comment_id}", json=body, headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        # Inject board_state when this comment belongs to a project-scoped item
        comment_item_id: str | None = result.get("item_id")
        if comment_item_id:
            item_resp = await self._client.get(
                f"/api/items/{comment_item_id}", headers=self._headers()
            )
            self._check(item_resp)
            item_project_id: str | None = item_resp.json().get("project_id")
            if item_project_id:
                result["board_state"] = await self._board_snapshot(item_project_id)
        return result

    async def delete_comment(self, user_id: str, comment_id: str) -> None:
        resp = await self._client.delete(
            f"/api/comments/{comment_id}", headers=self._headers()
        )
        self._check(resp)

    async def dispatch_item(
        self,
        user_id: str,
        item_id: str,
        *,
        max_turns: int | None = None,
        mode: str = "build",
        rollout_id: str | None = None,
        dispatch_host_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"mode": mode}
        if max_turns is not None:
            body["max_turns"] = max_turns
        if rollout_id is not None:
            body["rollout_id"] = rollout_id
        if dispatch_host_id is not None:
            body["dispatch_host_id"] = dispatch_host_id
        resp = await self._client.post(
            f"/api/items/{item_id}/dispatch", json=body, headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def dispatch_rollout(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/dispatch",
            json={},
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/runs/{run_id}", headers=self._headers())
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def get_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"/api/rollouts/{rollout_id}", headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def list_rollouts(
        self,
        user_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = project_id
        if status is not None:
            params["status"] = status
        resp = await self._client.get(
            "/api/rollouts", params=params, headers=self._headers()
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def get_rollout_plan(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        resp = await self._client.get(
            f"/api/rollouts/{rollout_id}/plan", headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def list_runs(
        self,
        user_id: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if item_id is not None:
            params["item_id"] = item_id
        if status is not None:
            params["status"] = status
        resp = await self._client.get(
            "/api/runs", params=params, headers=self._headers()
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def list_dispatch_hosts(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        resp = await self._client.get(
            "/api/settings/dispatch/hosts", headers=self._headers()
        )
        self._check(resp)
        hosts: list[dict[str, Any]] = resp.json()
        # Project down to non-secret fields only — drop api_key_preview/created_at.
        return [{"id": h["id"], "label": h["label"], "url": h["url"]} for h in hosts]

    async def add_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/items/{item_id}/blockers",
            json={"blocker_item_id": blocker_item_id},
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def remove_blocker(
        self,
        user_id: str,
        item_id: str,
        blocker_item_id: str,
    ) -> None:
        resp = await self._client.delete(
            f"/api/items/{item_id}/blockers/{blocker_item_id}",
            headers=self._headers(),
        )
        self._check(resp)

    async def list_blockers(
        self,
        user_id: str,
        item_id: str,
    ) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"/api/items/{item_id}/blockers",
            headers=self._headers(),
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def add_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/projects/{project_id}/members",
            json={"email": email},
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def remove_project_member(
        self,
        user_id: str,
        project_id: str,
        email: str,
    ) -> None:
        members = await self.list_project_members(user_id, project_id)
        member = next((m for m in members if m["email"] == email), None)
        if member is None:
            return
        resp = await self._client.delete(
            f"/api/projects/{project_id}/members/{member['user_id']}",
            headers=self._headers(),
        )
        self._check(resp)

    async def list_project_members(
        self,
        user_id: str,
        project_id: str,
    ) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"/api/projects/{project_id}/members",
            headers=self._headers(),
        )
        self._check(resp)
        result: list[dict[str, Any]] = resp.json()
        return result

    async def plan_rollout(
        self,
        user_id: str,
        item_ids: list[str],
    ) -> dict[str, Any]:
        from agent_gtd.exceptions import LegalityContractError

        resp = await self._client.post(
            "/api/rollouts",
            json={"item_ids": item_ids},
            headers=self._headers(),
            # Planner can take 30-60s for medium rollouts; default httpx timeout
            # is 5s. Bump to 5min.
            timeout=300.0,
        )
        # Special-case the legality contract failure so the MCP tool gets the
        # same exception type it would from LocalBackend (preserves the
        # structured failures payload for the formatted error message).
        if resp.status_code == 422:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = None
            if (
                isinstance(detail, dict)
                and detail.get("kind") == "legality_contract_failed"
                and isinstance(detail.get("failures"), list)
            ):
                raise LegalityContractError(detail["failures"])
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def advance_rollout(self, user_id: str, rollout_id: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"/api/rollouts/{rollout_id}/advance",
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def complete_item_in_rollout(
        self,
        user_id: str,
        rollout_id: str,
        item_id: str,
        outcome: Literal["completed", "halted", "skipped"],
        *,
        merge_actor: Literal[
            "human",
            "manager-allowlist",
            "manager-autonomous",
            "manager+human-fixup",
            "",
        ] = "",
        decision_rule: Literal["", "agent-judgment"] = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "item_id": item_id,
            "outcome": outcome,
        }
        if merge_actor:
            body["merge_actor"] = merge_actor
        if decision_rule:
            body["decision_rule"] = decision_rule
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/complete-item",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def halt_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
        *,
        comment: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"reason": reason}
        if comment is not None:
            body["comment"] = comment
        if item_id is not None:
            body["item_id"] = item_id
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/halt",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def start_rollout(
        self,
        user_id: str,
        rollout_id: str,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/start",
            json={},
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def cancel_rollout(
        self,
        user_id: str,
        rollout_id: str,
        reason: str,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/cancel",
            json={"reason": reason},
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def replan_rollout(
        self,
        user_id: str,
        rollout_id: str,
        *,
        from_item: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if from_item is not None:
            body["from_item"] = from_item
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/replan",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def update_rollout_state(
        self,
        user_id: str,
        rollout_id: str,
        phase: Literal[
            "warm_up",
            "dispatching",
            "polling",
            "reviewing",
            "merging",
            "reconciling_ac",
            "halted",
        ],
        current_item_id: str | None = None,
        current_step: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/rollouts/{rollout_id}/state",
            json={
                "phase": phase,
                "current_item_id": current_item_id,
                "current_step": current_step,
            },
            headers=self._headers(),
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_AGENT_GTD_URL = os.environ.get("AGENT_GTD_URL", "")


def create_backend() -> LocalBackend | HttpBackend:
    """Create the appropriate backend based on environment variables."""
    if _AGENT_GTD_URL:
        api_key = os.environ.get("AGENT_GTD_API_KEY", "")
        return HttpBackend(base_url=_AGENT_GTD_URL, api_key=api_key)
    return LocalBackend()
