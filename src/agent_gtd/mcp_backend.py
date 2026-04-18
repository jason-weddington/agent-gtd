"""MCP backend abstraction — local (DB-direct) and HTTP implementations."""

# ruff: noqa: D102

from __future__ import annotations

import os
import ssl
from typing import Any, Protocol

import httpx
import truststore
from fastmcp.exceptions import ToolError


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
    ) -> dict[str, Any]: ...

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
    ) -> list[dict[str, Any]]: ...

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
    ) -> dict[str, Any]: ...

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

    async def claim_item(
        self, user_id: str, item_id: str, agent_name: str
    ) -> dict[str, Any]: ...

    async def release_item(self, user_id: str, item_id: str) -> dict[str, Any]: ...

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
        created_by: str = "human",
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
    ) -> dict[str, Any]: ...

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]: ...

    async def list_runs(
        self,
        user_id: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
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
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import project_service

        db = await get_db()
        return await project_service.create_project(
            db,
            user_id,
            name=name,
            description=description,
            area=area,
            status=status,
            git_origin=git_origin,
            kb_project_ref=kb_project_ref,
        )

    async def _build_project_map(self, user_id: str) -> dict[str, str]:
        projects = await self.list_projects(user_id)
        return {p["id"]: p["name"] for p in projects}

    def _format_item(
        self, row: dict[str, Any], project_map: dict[str, str]
    ) -> dict[str, Any]:
        from agent_gtd.database import decode_json_list

        result = {**row, "labels": decode_json_list(str(row["labels"]))}
        if row.get("project_id"):
            result["project_name"] = project_map.get(row["project_id"], "")
        return result

    def _format_note(
        self, row: dict[str, Any], project_map: dict[str, str]
    ) -> dict[str, Any]:
        from agent_gtd.database import decode_json_list

        result = {**row, "labels": decode_json_list(str(row["labels"]))}
        if row.get("project_id"):
            result["project_name"] = project_map.get(row["project_id"], "")
        return result

    async def list_items(
        self,
        user_id: str,
        *,
        status: str | None = None,
        project_id: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
    ) -> list[dict[str, Any]]:
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
        return [self._format_item(r, pm) for r in rows]

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.get_item(db, user_id, item_id)
        blocker_rows = await item_service.list_blockers(db, user_id, item_id)
        pm = await self._build_project_map(user_id)
        result = self._format_item(row, pm)
        result["blockers"] = blocker_rows
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
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
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
        )
        pm = await self._build_project_map(user_id)
        return self._format_item(row, pm)

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
            version=version,
        )
        pm = await self._build_project_map(user_id)
        return self._format_item(row, pm)

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.complete_item(db, user_id, item_id)
        pm = await self._build_project_map(user_id)
        return self._format_item(row, pm)

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        await item_service.delete_item(db, user_id, item_id)
        return {"status": "deleted", "item_id": item_id}

    async def claim_item(
        self, user_id: str, item_id: str, agent_name: str
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.claim_item(db, user_id, item_id, agent_name)
        pm = await self._build_project_map(user_id)
        return self._format_item(row, pm)

    async def release_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import item_service

        db = await get_db()
        row = await item_service.release_item(db, user_id, item_id)
        pm = await self._build_project_map(user_id)
        return self._format_item(row, pm)

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
        return self._format_item(row, pm)

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
        return self._format_note(row, pm)

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
        return self._format_note(row, pm)

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
        return self._format_note(row, pm)

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
        created_by: str = "human",
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import comment_service

        db = await get_db()
        return await comment_service.create_comment(
            db,
            user_id,
            project_id=project_id,
            item_id=item_id,
            content_markdown=content_markdown,
            created_by=created_by,
        )

    async def update_comment(
        self,
        user_id: str,
        comment_id: str,
        *,
        content_markdown: str | None = None,
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services import comment_service

        db = await get_db()
        return await comment_service.update_comment(
            db, user_id, comment_id, content_markdown=content_markdown
        )

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
    ) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import create_run

        db = await get_db()
        return await create_run(db, user_id, item_id, max_turns=max_turns, mode=mode)

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]:
        from agent_gtd.database import get_db
        from agent_gtd.services.dispatch_service import get_run

        db = await get_db()
        return await get_run(db, user_id, run_id)

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
        self._project_cache: dict[str, str] | None = None

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

    async def _get_project_map(self) -> dict[str, str]:
        if self._project_cache is not None:
            return self._project_cache
        resp = await self._client.get("/api/projects", headers=self._headers())
        self._check(resp)
        projects = resp.json()
        self._project_cache = {p["id"]: p["name"] for p in projects}
        return self._project_cache

    def _enrich_item(self, item: dict[str, Any], pm: dict[str, str]) -> dict[str, Any]:
        if item.get("project_id"):
            item["project_name"] = pm.get(item["project_id"], "")
        return item

    def _enrich_note(self, note: dict[str, Any], pm: dict[str, str]) -> dict[str, Any]:
        if note.get("project_id"):
            note["project_name"] = pm.get(note["project_id"], "")
        return note

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
    ) -> dict[str, Any]:
        body: dict[str, str] = {
            "name": name,
            "description": description,
            "area": area,
            "status": status,
        }
        if git_origin:
            body["git_origin"] = git_origin
        if kb_project_ref:
            body["kb_project_ref"] = kb_project_ref
        resp = await self._client.post(
            "/api/projects",
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
    ) -> list[dict[str, Any]]:
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
        return [self._enrich_item(i, pm) for i in items]

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/items/{item_id}", headers=self._headers())
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

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
        resp = await self._client.post(
            "/api/items",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

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
        resp = await self._client.patch(
            f"/api/items/{item_id}",
            json=body,
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

    async def complete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/items/{item_id}/complete", headers=self._headers()
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.delete(
            f"/api/items/{item_id}", headers=self._headers()
        )
        self._check(resp)
        return {"status": "deleted", "item_id": item_id}

    async def claim_item(
        self, user_id: str, item_id: str, agent_name: str
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/items/{item_id}/claim",
            json={"agent_name": agent_name},
            headers=self._headers(),
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

    async def release_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"/api/items/{item_id}/release", headers=self._headers()
        )
        self._check(resp)
        item = resp.json()
        pm = await self._get_project_map()
        return self._enrich_item(item, pm)

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
        return self._enrich_item(item, pm)

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
        return self._enrich_note(note, pm)

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
        return self._enrich_note(note, pm)

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
        return self._enrich_note(note, pm)

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
        created_by: str = "human",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content_markdown": content_markdown,
            "created_by": created_by,
        }
        if project_id:
            path = f"/api/projects/{project_id}/comments"
        elif item_id:
            path = f"/api/items/{item_id}/comments"
        else:
            raise ToolError("Either project_id or item_id is required")
        resp = await self._client.post(path, json=body, headers=self._headers())
        self._check(resp)
        result: dict[str, Any] = resp.json()
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
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"mode": mode}
        if max_turns is not None:
            body["max_turns"] = max_turns
        resp = await self._client.post(
            f"/api/items/{item_id}/dispatch", json=body, headers=self._headers()
        )
        self._check(resp)
        result: dict[str, Any] = resp.json()
        return result

    async def get_run(self, user_id: str, run_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/runs/{run_id}", headers=self._headers())
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
