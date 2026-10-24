"""Streamable HTTP MCP endpoint served by the board at ``/mcp``.

The board serves the same tool set as the stdio ``agent-gtd-mcp`` server, so
every MCP client can point at one always-current URL.  Request flow:

1. ``McpEndpoint`` (a raw ASGI app mounted as a Starlette ``Route``)
   authenticates the bearer token exactly as the REST API does, resolves the
   ``created_by`` attribution server-side, and stores a ``CallContext`` on the
   request scope.
2. The inner FastMCP app (stateless, JSON responses) runs the tool; the tool
   reads its principal back through ``mcp_server._resolve_call``.

``mcp_http_lifespan`` builds a fresh FastMCP server per application lifespan
and runs its session-manager lifespan inside the board's own.
"""

import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as mt
from fastapi import FastAPI, HTTPException
from fastapi.security.utils import get_authorization_scheme_param
from fastmcp.exceptions import FastMCPError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from agent_gtd import database, identity
from agent_gtd.auth import (
    RunTokenContext,
    authenticate_bearer_token,
    get_local_user,
    run_context_from_token,
)
from agent_gtd.mcp_backend import LocalBackend
from agent_gtd.mcp_server import CallContext, create_mcp_server
from agent_gtd.services import attachment_storage

logger = logging.getLogger(__name__)

AGENT_NAME_HEADER = "x-agent-name"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Any
Send = Any


# --- Attribution ---


def resolve_agent_name(
    user_id: str,
    run_ctx: RunTokenContext | None,
    header_value: str | None,
) -> tuple[str, str]:
    """Compute the ``created_by`` name for one HTTP request.

    Rules, in order: a run-scoped token always wins (the header is ignored);
    otherwise a well-formed ``X-Agent-Name`` header is used; otherwise the
    caller is attributed as the interactive lead.

    Args:
        user_id: Authenticated user.
        run_ctx: Run identity carried by the bearer token, if any.
        header_value: Raw ``X-Agent-Name`` header, or None when absent.

    Returns:
        ``(name, source)`` where source is one of ``run_token``,
        ``header_ignored_run_token``, ``header``, ``header_rejected`` and
        ``lead_default``.
    """
    if run_ctx is not None:
        name = identity.compute_run_attribution(run_ctx.mode, run_ctx.run_id)
        if header_value is not None and header_value != name:
            return name, "header_ignored_run_token"
        return name, "run_token"
    if header_value is not None and AGENT_NAME_PATTERN.fullmatch(header_value):
        return header_value, "header"
    if header_value is not None:
        return identity.compute_lead_attribution(user_id), "header_rejected"
    return identity.compute_lead_attribution(user_id), "lead_default"


# --- In-process backend with REST-equivalent guards ---


class BoardBackend(LocalBackend):
    """LocalBackend plus the guards the REST routes apply around it."""

    async def dispatch_item(
        self,
        user_id: str,
        item_id: str,
        *,
        max_turns: int | None = None,
        mode: str = "build",
        rollout_id: str | None = None,
        dispatch_host_id: str | None = None,
        allow_drained_host: bool = False,
    ) -> dict[str, Any]:
        """Run the REST dispatch pre-flight, then create the run."""
        from agent_gtd.routes.dispatch_routes import dispatch_preflight

        db = await database.get_db()
        await dispatch_preflight(
            db,
            user_id,
            item_id,
            dispatch_host_id,
            allow_drained_host=allow_drained_host,
        )
        return await super().dispatch_item(
            user_id,
            item_id,
            max_turns=max_turns,
            mode=mode,
            rollout_id=rollout_id,
            dispatch_host_id=dispatch_host_id,
            allow_drained_host=allow_drained_host,
        )

    async def delete_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Delete the item, then its attachment files (as the REST route does)."""
        result = await super().delete_item(user_id, item_id)
        attachment_storage.delete_item_files(item_id)
        return result


# --- Per-call logging ---


class ToolCallLogMiddleware(Middleware):
    """Log one ``mcp_http.tool_call`` record per tool call on the HTTP server."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Time the call and log its outcome."""
        tool = context.message.name
        start = time.monotonic()

        def _log(level: int, outcome: str, error: str | None, **kw: Any) -> None:
            logger.log(
                level,
                "mcp-http tool %s %s",
                tool,
                outcome,
                extra={
                    "event": "mcp_http.tool_call",
                    "tool": tool,
                    "outcome": outcome,
                    "error": error,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                },
                **kw,
            )

        try:
            result = await call_next(context)
        except ToolError as exc:
            cause = exc.__cause__
            if cause is not None and not isinstance(cause, FastMCPError):
                # FastMCP wraps an unexpected exception as ToolError(...) from
                # exc before middleware sees it: report the real failure.
                _log(
                    logging.ERROR,
                    "exception",
                    str(cause)[:200],
                    exc_info=(type(cause), cause, cause.__traceback__),
                )
            else:
                _log(logging.INFO, "tool_error", str(exc)[:200])
            raise
        except Exception as exc:
            _log(logging.ERROR, "exception", str(exc)[:200], exc_info=True)
            raise
        _log(logging.INFO, "ok", None)
        return result


# --- ASGI endpoint ---


def _token_sha8(token: str | None) -> str:
    if not token:
        return "-"
    return hashlib.sha256(token.encode()).hexdigest()[:8]


class McpEndpoint:
    """Raw ASGI app: authenticate, attach the principal, delegate to FastMCP."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one request to ``/mcp``."""
        headers = Headers(scope=scope)
        scheme, credential = get_authorization_scheme_param(
            headers.get("authorization")
        )
        has_auth_header = headers.get("authorization") is not None
        token = credential if scheme.lower() == "bearer" and credential else None

        local = database.is_local_mode()
        if local:
            user = await get_local_user()
        elif token is None:
            reason = "bad_scheme" if has_auth_header else "no_token"
            await self._deny(scope, receive, send, 401, "Not authenticated", reason)
            return
        else:
            try:
                user = await authenticate_bearer_token(token)
            except HTTPException as exc:
                await self._deny(
                    scope,
                    receive,
                    send,
                    exc.status_code,
                    exc.detail,
                    "invalid_token",
                    token=token,
                )
                return

        run_ctx = run_context_from_token(token) if token is not None else None

        app = scope["app"]
        inner = getattr(app.state, "mcp_http_app", None)
        if inner is None:
            await self._deny(
                scope,
                receive,
                send,
                503,
                "MCP endpoint not started",
                "not_started",
                token=token,
            )
            return

        header_value = headers.get(AGENT_NAME_HEADER)
        agent_name, source = resolve_agent_name(user.id, run_ctx, header_value)
        if local:
            auth_method = "local"
        elif run_ctx is not None:
            auth_method = "run_jwt"
        elif token is not None and token.startswith("agtd_"):
            auth_method = "api_key"
        else:
            auth_method = "user_jwt"
        logger.info(
            "mcp-http principal",
            extra={
                "event": "mcp_http.principal",
                "auth_method": auth_method,
                "user8": user.id[:8],
                "run8": run_ctx.run_id[:8] if run_ctx else None,
                "run_mode": run_ctx.mode if run_ctx else None,
                "agent_name": agent_name,
                "agent_name_source": source,
            },
        )
        if source == "header_ignored_run_token":
            logger.warning(
                "mcp-http X-Agent-Name ignored for run token",
                extra={"event": "mcp_http.agent_name_header_ignored"},
            )
        elif source == "header_rejected" and header_value is not None:
            logger.warning(
                "mcp-http X-Agent-Name rejected",
                extra={
                    "event": "mcp_http.agent_name_header_rejected",
                    "header_len": len(header_value),
                    "header_head": repr(header_value[:16]),
                },
            )

        scope.setdefault("state", {})["agtd_mcp_call"] = CallContext(
            user_id=user.id,
            agent_name=agent_name,
            backend=app.state.mcp_backend,
            run_id=run_ctx.run_id if run_ctx else None,
            run_mode=run_ctx.mode if run_ctx else None,
        )
        await inner(scope, receive, send)

    @staticmethod
    async def _deny(
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: Any,
        reason: str,
        *,
        token: str | None = None,
    ) -> None:
        logger.info(
            "mcp-http auth denied",
            extra={
                "event": "mcp_http.auth_denied",
                "status": status,
                "reason": reason,
                "token_sha8": _token_sha8(token),
            },
        )
        resp_headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        response = JSONResponse(
            {"detail": detail}, status_code=status, headers=resp_headers
        )
        await response(scope, receive, send)


# --- Lifespan ---


@asynccontextmanager
async def mcp_http_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build a fresh HTTP MCP server and run its lifespan inside the board's."""
    try:
        server = create_mcp_server(transport="http")
        app.state.mcp_backend = BoardBackend()
        app.state.mcp_http_app = server.http_app(
            path="/mcp", stateless_http=True, json_response=True
        )
        n_tools = len(await server.list_tools())
        local = database.is_local_mode()
        auth_mode = "local-unauthenticated" if local else "bearer"
        logger.log(
            logging.WARNING if local else logging.INFO,
            "mcp-http started path=/mcp tools=%d auth=%s",
            n_tools,
            auth_mode,
            extra={
                "event": "mcp_http.started",
                "tools": n_tools,
                "auth_mode": auth_mode,
            },
        )
        inner = app.state.mcp_http_app
        async with inner.lifespan(inner):
            yield
    except BaseExceptionGroup as group:
        logger.error(
            "mcp-http lifespan failed",
            extra={"event": "mcp_http.lifespan_failed"},
            exc_info=True,
        )
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from None
        raise
    finally:
        app.state.mcp_http_app = None
        logger.info("mcp-http stopped", extra={"event": "mcp_http.stopped"})
