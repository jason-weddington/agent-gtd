"""Tests for the board's streamable HTTP MCP endpoint at /mcp (mcp_http.py)."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from httpx import ASGITransport, AsyncClient
from starlette.routing import Mount, Route

import agent_gtd.database as db_mod
import agent_gtd.mcp_server as srv
from agent_gtd.auth import (
    RunTokenContext,
    create_token,
    generate_api_key,
    hash_api_key,
    register_user,
)
from agent_gtd.database import (
    LOCAL_USER_ID,
    encode_file_specs,
    encode_json_list,
    get_db,
)
from agent_gtd.main import app
from agent_gtd.mcp_backend import LocalBackend
from agent_gtd.mcp_http import (
    AGENT_NAME_PATTERN,
    BoardBackend,
    mcp_http_lifespan,
    resolve_agent_name,
)
from agent_gtd.mcp_server import create_mcp_server, mcp
from agent_gtd.services import project_service
from agent_gtd.services.settings_service import (
    add_dispatch_host,
    drain_dispatch_host,
)

NOW = datetime.now(UTC).isoformat()

_BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


# --- Fixtures and helpers ---


@pytest.fixture(autouse=True)
def _postgres_mode(monkeypatch):
    """Exercise the authenticated (multi-user) path unless a test overrides it."""
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: False)


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger="agent_gtd")
    return caplog


def _events(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == event]


async def _make_key(user_id: str) -> str:
    """Create an API key row as tests/test_mcp_tools.py does."""
    db = await get_db()
    key = generate_api_key()
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        str(uuid.uuid4()),
        user_id,
        hash_api_key(key),
        "test-key",
        NOW,
    )
    return key


@pytest.fixture
async def user():
    return await register_user("http-mcp@example.com", "testpass123")


@pytest.fixture
async def user_id(user) -> str:
    return str(user.id)


@pytest.fixture
async def api_key(user_id) -> str:
    return await _make_key(user_id)


@pytest.fixture
async def started() -> AsyncIterator[Any]:
    """Run mcp_http_lifespan(app) (not the full app lifespan: no worker).

    The lifespan is entered and exited inside one dedicated task because
    anyio cancel scopes must exit in the task that entered them, and
    pytest-asyncio runs fixture setup and teardown in different tasks.
    """
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def _run() -> None:
        async with mcp_http_lifespan(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(_run())
    waiter = asyncio.create_task(ready.wait())
    await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    if task.done():
        waiter.cancel()
        task.result()
    yield app
    stop.set()
    await task


@pytest.fixture
async def http() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=10.0
    ) as c:
        yield c


def _headers(
    token: str | None = None, agent_name: str | None = None, **extra: str
) -> dict[str, str]:
    h = dict(_BASE_HEADERS)
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if agent_name is not None:
        h["X-Agent-Name"] = agent_name
    h.update(extra)
    return h


async def _rpc(
    http: AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await http.post("/mcp", json=body, headers=headers or _headers())


def _initialize_params(version: str = "2025-11-25") -> dict[str, Any]:
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }


async def _call(
    http: AsyncClient, tool: str, args: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """Call a tool over HTTP and return the JSON-RPC ``result`` object."""
    res = await _rpc(http, "tools/call", {"name": tool, "arguments": args}, headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "result" in payload, payload
    result: dict[str, Any] = payload["result"]
    return result


def _text(result: dict[str, Any]) -> str:
    return " ".join(c.get("text", "") for c in result.get("content", []))


def _data(result: dict[str, Any]) -> Any:
    assert not result.get("isError"), _text(result)
    return json.loads(result["content"][0]["text"])


async def _create_project(user_id: str, name: str = "HTTP MCP Project") -> str:
    db = await get_db()
    project = await project_service.create_project(
        db, user_id, name=name, git_origin="git@github.com:test/repo.git"
    )
    return str(project["id"])


async def _create_item(
    user_id: str,
    project_id: str | None,
    *,
    status: str = "next_action",
    build_engine: str | None = None,
    commit_type: str = "",
) -> str:
    """Insert an item with structured fields (mirrors test_mcp_rollout's helper)."""
    db = await get_db()
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, acceptance_criteria, files_to_modify, scope_out, "
        " build_engine, commit_type, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
        item_id,
        project_id,
        user_id,
        "HTTP item",
        "Background context.",
        status,
        encode_json_list([]),
        encode_json_list(["AC-1: The feature works correctly."]),
        encode_file_specs([{"path": "src/agent_gtd/main.py", "change": "x"}]),
        encode_json_list([]),
        build_engine,
        commit_type,
        NOW,
        NOW,
    )
    return item_id


async def _count_runs(item_id: str) -> int:
    db = await get_db()
    row = await db.fetchrow(
        "SELECT COUNT(*) AS n FROM claude_runs WHERE item_id = $1", item_id
    )
    return int(row["n"])


# --- AC-2: one /mcp route, not a Mount ---


def test_mcp_is_a_single_route_not_a_mount():
    routes = [r for r in app.routes if getattr(r, "path", None) == "/mcp"]
    assert len(routes) == 1
    assert isinstance(routes[0], Route)
    assert not isinstance(routes[0], Mount)


# --- AC-12: endpoint auth ---


async def test_no_authorization_is_401(started, http, logs):
    res = await _rpc(http, "initialize", _initialize_params())
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    denied = _events(logs, "mcp_http.auth_denied")
    assert [r.reason for r in denied] == ["no_token"]
    assert denied[0].token_sha8 == "-"  # noqa: S105 - placeholder, not a secret


async def test_bogus_api_key_is_401(started, http, logs):
    res = await _rpc(http, "initialize", _initialize_params(), _headers("agtd_bogus"))
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    denied = _events(logs, "mcp_http.auth_denied")
    assert [r.reason for r in denied] == ["invalid_token"]
    sha8 = denied[0].token_sha8
    assert len(sha8) == 8 and sha8 != "-"
    assert all("agtd_bogus" not in r.getMessage() for r in logs.records)


async def test_basic_scheme_is_401_not_authenticated(started, http, logs):
    res = await _rpc(
        http, "initialize", _initialize_params(), _headers(Authorization="Basic x")
    )
    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}
    assert res.headers["www-authenticate"] == "Bearer"
    denied = _events(logs, "mcp_http.auth_denied")
    assert [r.reason for r in denied] == ["bad_scheme"]


async def test_valid_api_key_initializes(started, http, api_key):
    res = await _rpc(http, "initialize", _initialize_params(), _headers(api_key))
    assert res.status_code == 200
    assert res.json()["result"]["serverInfo"]["name"] == "Agent GTD"


async def test_build_callback_jwt_initializes(started, http, user_id):
    token = create_token(user_id, run_id=str(uuid.uuid4()), run_mode="build")
    res = await _rpc(http, "initialize", _initialize_params(), _headers(token))
    assert res.status_code == 200
    assert "result" in res.json()


async def test_not_started_is_503(http, api_key, logs):
    app.state.mcp_http_app = None
    res = await _rpc(http, "initialize", _initialize_params(), _headers(api_key))
    assert res.status_code == 503
    assert res.json() == {"detail": "MCP endpoint not started"}
    denied = _events(logs, "mcp_http.auth_denied")
    assert [r.reason for r in denied] == ["not_started"]


async def test_authenticated_get_is_405(started, http, api_key):
    res = await http.get("/mcp", headers=_headers(api_key))
    assert res.status_code == 405


async def test_local_mode_needs_no_authorization(started, http, monkeypatch):
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: True)
    res = await _rpc(http, "initialize", _initialize_params())
    assert res.status_code == 200
    assert "result" in res.json()


# --- AC-16: protocol versions ---


@pytest.mark.parametrize("version", ["2025-11-25", "2025-03-26"])
async def test_protocol_version_negotiation(started, http, api_key, version):
    res = await _rpc(http, "initialize", _initialize_params(version), _headers(api_key))
    assert res.status_code == 200
    assert res.json()["result"]["protocolVersion"] == version


# --- AC-7 / AC-13: attribution ---


_R = "0123abcd-1111-2222-3333-444455556666"
_USER = "feedbeef-0000-0000-0000-000000000000"


@pytest.mark.parametrize(
    ("run_ctx", "header", "expected"),
    [
        (RunTokenContext(_R, "build"), None, ("claude-build-0123abcd", "run_token")),
        (
            RunTokenContext(_R, "build"),
            "claude-build-0123abcd",
            ("claude-build-0123abcd", "run_token"),
        ),
        (
            RunTokenContext(_R, "build"),
            "someone-else",
            ("claude-build-0123abcd", "header_ignored_run_token"),
        ),
        (None, "claude-build-deadbeef", ("claude-build-deadbeef", "header")),
        (None, "bad name!", ("claude-lead-feedbeef", "header_rejected")),
        (None, "a" * 65, ("claude-lead-feedbeef", "header_rejected")),
        (None, "a" * 64, ("a" * 64, "header")),
        (None, "", ("claude-lead-feedbeef", "header_rejected")),
        (None, "${AGENT_GTD_AGENT_NAME}", ("claude-lead-feedbeef", "header_rejected")),
        (None, None, ("claude-lead-feedbeef", "lead_default")),
        (None, "claude-plan-cafef00d", ("claude-plan-cafef00d", "header")),
    ],
)
def test_resolve_agent_name_table(run_ctx, header, expected):
    assert resolve_agent_name(_USER, run_ctx, header) == expected


def test_agent_name_pattern_max_length_is_64():
    assert AGENT_NAME_PATTERN.fullmatch("a" * 64)
    assert not AGENT_NAME_PATTERN.fullmatch("a" * 65)
    assert not AGENT_NAME_PATTERN.fullmatch("-leading-dash")


async def _comment_created_by(
    http: AsyncClient, headers: dict[str, str], item_id: str
) -> str:
    result = await _call(
        http,
        "add_comment",
        {"content_markdown": "attributed", "item_id": item_id},
        headers,
    )
    comment = _data(result)
    db = await get_db()
    row = await db.fetchrow(
        "SELECT created_by FROM comments WHERE id = $1", comment["id"]
    )
    return str(row["created_by"])


def _token(kind: str, user_id: str, run_id: str, api_key: str) -> str:
    if kind == "build_jwt":
        return create_token(user_id, run_id=run_id, run_mode="build")
    if kind == "user_jwt":
        return create_token(user_id)
    return api_key


@pytest.mark.parametrize(
    ("kind", "header", "expect", "source"),
    [
        ("build_jwt", None, "run", "run_token"),
        ("build_jwt", "someone-else", "run", "header_ignored_run_token"),
        ("api_key", "claude-build-deadbeef", "claude-build-deadbeef", "header"),
        ("api_key", "bad name!", "lead", "header_rejected"),
        ("api_key", "a" * 65, "lead", "header_rejected"),
        ("api_key", None, "lead", "lead_default"),
        ("user_jwt", "claude-plan-cafef00d", "claude-plan-cafef00d", "header"),
        ("user_jwt", None, "lead", "lead_default"),
    ],
)
async def test_http_attribution(
    started, http, user_id, api_key, logs, kind, header, expect, source
):
    run_id = str(uuid.uuid4())
    item_id = await _create_item(user_id, None)
    headers = _headers(_token(kind, user_id, run_id, api_key), header)

    created_by = await _comment_created_by(http, headers, item_id)

    expected = {
        "run": f"claude-build-{run_id[:8]}",
        "lead": f"claude-lead-{user_id[:8]}",
    }.get(expect, expect)
    assert created_by == expected
    principal = _events(logs, "mcp_http.principal")
    assert principal, "no mcp_http.principal record"
    assert principal[-1].agent_name_source == source
    assert principal[-1].agent_name == expected
    expected_method = {"build_jwt": "run_jwt"}.get(kind, kind)
    assert principal[-1].auth_method == expected_method
    if source == "header_ignored_run_token":
        assert len(_events(logs, "mcp_http.agent_name_header_ignored")) == 1
    if source == "header_rejected":
        rejected = _events(logs, "mcp_http.agent_name_header_rejected")
        assert len(rejected) == 1
        assert rejected[0].header_len == len(header)


async def test_local_mode_attribution(started, http, monkeypatch, logs):
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: True)
    item_id = await _create_item(LOCAL_USER_ID, None)

    created_by = await _comment_created_by(http, _headers(), item_id)
    assert created_by == f"claude-lead-{LOCAL_USER_ID[:8]}"
    assert _events(logs, "mcp_http.principal")[-1].auth_method == "local"

    run_id = str(uuid.uuid4())
    token = create_token(LOCAL_USER_ID, run_id=run_id, run_mode="build")
    created_by = await _comment_created_by(
        http, _headers(token, "someone-else"), item_id
    )
    assert created_by == f"claude-build-{run_id[:8]}"


# --- AC-9: REST-equivalent dispatch pre-flight and delete cleanup ---


async def _dispatch_refusal(
    http: AsyncClient, headers: dict[str, str], args: dict[str, Any]
) -> str:
    result = await _call(http, "dispatch_item", args, headers)
    assert result["isError"] is True
    return _text(result)


async def test_dispatch_refused_for_non_member(started, http, user_id, logs):
    project_id = await _create_project(user_id)
    item_id = await _create_item(user_id, project_id)
    other = await register_user("other@example.com", "testpass123")
    other_key = await _make_key(other.id)

    text = await _dispatch_refusal(http, _headers(other_key), {"item_id": item_id})

    assert "only project members can dispatch agents" in text
    assert await _count_runs(item_id) == 0
    refused = _events(logs, "mcp_http.dispatch_refused")
    assert len(refused) == 1
    assert refused[0].status == 403


async def test_dispatch_refused_without_dispatch_hosts(
    started, http, user_id, api_key, logs
):
    project_id = await _create_project(user_id)
    item_id = await _create_item(user_id, project_id)

    text = await _dispatch_refusal(http, _headers(api_key), {"item_id": item_id})

    assert "Project owner has not configured dispatch" in text
    assert await _count_runs(item_id) == 0
    assert len(_events(logs, "mcp_http.dispatch_refused")) == 1


async def test_dispatch_refused_for_draining_host(
    started, http, user_id, api_key, logs, monkeypatch
):
    import agent_gtd.routes.dispatch_routes as dr

    monkeypatch.setattr(dr, "_check_dispatch_service", AsyncMock(return_value=None))
    project_id = await _create_project(user_id)
    item_id = await _create_item(user_id, project_id)
    db = await get_db()
    # Host helpers as in tests/test_dispatch_drain.py (add + drain).
    host = await add_dispatch_host(db, user_id, "host-a", "http://h:8100", "k")
    await drain_dispatch_host(db, user_id, host["id"], "rolling deploy 2.0.2")

    text = await _dispatch_refusal(
        http,
        _headers(api_key),
        {"item_id": item_id, "dispatch_host_id": host["id"]},
    )

    assert "is draining" in text
    assert await _count_runs(item_id) == 0
    refused = _events(logs, "mcp_http.dispatch_refused")
    assert len(refused) == 1
    assert refused[0].status == 409


async def test_stdio_dispatch_has_no_membership_preflight(user_id, monkeypatch):
    """The stdio LocalBackend path is unchanged: no REST pre-flight runs."""
    project_id = await _create_project(user_id)
    item_id = await _create_item(user_id, project_id)
    other = await register_user("other@example.com", "testpass123")
    other_key = await _make_key(other.id)
    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", other_key)
    monkeypatch.setattr(srv, "_ENV_AGENT_NAME", None)

    async with Client(mcp) as c:
        result = await c.call_tool(
            "dispatch_item", {"item_id": item_id}, raise_on_error=False
        )
    text = " ".join(getattr(b, "text", "") for b in result.content)
    assert "only project members can dispatch agents" not in text


async def test_delete_item_cleans_attachment_files(
    started, http, user_id, api_key, monkeypatch
):
    from agent_gtd.services import attachment_storage

    deleted: list[str] = []
    monkeypatch.setattr(attachment_storage, "delete_item_files", deleted.append)
    item_id = await _create_item(user_id, None)

    result = await _call(http, "delete_item", {"item_id": item_id}, _headers(api_key))

    assert _data(result)["status"] == "deleted"
    assert deleted == [item_id]


# --- AC-10: run context reaches the plan-mode engine guard ---


async def _engine(item_id: str) -> str:
    db = await get_db()
    row = await db.fetchrow("SELECT build_engine FROM items WHERE id = $1", item_id)
    return str(row["build_engine"])


async def _version(item_id: str) -> int:
    db = await get_db()
    row = await db.fetchrow("SELECT version FROM items WHERE id = $1", item_id)
    return int(row["version"])


@pytest.mark.parametrize("local", [False, True])
async def test_plan_run_cannot_change_build_engine(
    started, http, user_id, monkeypatch, logs, local
):
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: local)
    owner = LOCAL_USER_ID if local else user_id
    item_id = await _create_item(owner, None, build_engine="claude-code-sonnet")
    token = create_token(owner, run_id=str(uuid.uuid4()), run_mode="plan")

    result = await _call(
        http,
        "update_item",
        {
            "item_id": item_id,
            "version": await _version(item_id),
            "build_engine": "claude-code",
        },
        _headers(token),
    )

    assert result["isError"] is True
    assert "Plan-mode run may not change build_engine" in _text(result)
    assert await _engine(item_id) == "claude-code-sonnet"
    refused = _events(logs, "mcp_http.plan_engine_override_refused")
    assert len(refused) == 1
    assert refused[0].levelno == logging.WARNING


async def test_api_key_can_change_build_engine(started, http, user_id, api_key):
    item_id = await _create_item(user_id, None, build_engine="claude-code-sonnet")

    result = await _call(
        http,
        "update_item",
        {
            "item_id": item_id,
            "version": await _version(item_id),
            "build_engine": "claude-code",
        },
        _headers(api_key),
    )

    assert _data(result)["build_engine"] == "claude-code"
    assert await _engine(item_id) == "claude-code"


# --- AC-11: enqueue parity ---


async def _configure_dispatch(user_id: str) -> None:
    """Per-user dispatch config, as tests/test_mcp_rollout.py::_configure_dispatch."""
    db = await get_db()
    for key, value in [
        ("dispatch.service_url", "http://dispatch.test:8100"),
        ("dispatch.service_api_key", "test-api-key"),
    ]:
        await db.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at) "
            "VALUES ($1, $2, $3, $4)",
            user_id,
            key,
            value,
            NOW,
        )


async def test_dispatch_tools_enqueue_over_http(
    started, http, user_id, api_key, monkeypatch
):
    import agent_gtd.dispatch_worker as worker
    import agent_gtd.routes.dispatch_routes as dr

    enqueued: list[str] = []
    monkeypatch.setattr(worker, "enqueue_run", enqueued.append)
    monkeypatch.setattr(dr, "_check_dispatch_service", AsyncMock(return_value=None))
    headers = _headers(api_key)
    project_id = await _create_project(user_id)

    item_id = await _create_item(user_id, project_id)
    run = _data(await _call(http, "dispatch_item", {"item_id": item_id}, headers))
    assert enqueued == [str(run["id"])]

    # Rollout setup uses the same ready-item insert and dispatch config as
    # tests/test_mcp_rollout.py (_create_ready_item / _configure_dispatch),
    # then the plan_rollout tool itself.
    enqueued.clear()
    await _configure_dispatch(user_id)
    ready = await _create_item(
        user_id,
        project_id,
        status="ready",
        build_engine="claude-code-sonnet",
        commit_type="feat",
    )
    plan = _data(await _call(http, "plan_rollout", {"item_ids": [ready]}, headers))
    rollout_run = _data(
        await _call(
            http, "dispatch_rollout", {"rollout_id": plan["rollout_id"]}, headers
        )
    )
    assert enqueued == [str(rollout_run["id"])]


async def test_enqueue_failure_is_logged_on_board(
    started, http, user_id, api_key, monkeypatch, logs
):
    import agent_gtd.dispatch_worker as worker
    import agent_gtd.routes.dispatch_routes as dr

    def _boom(run_id: str) -> None:
        raise AssertionError("worker not started")

    monkeypatch.setattr(worker, "enqueue_run", _boom)
    monkeypatch.setattr(dr, "_check_dispatch_service", AsyncMock(return_value=None))
    project_id = await _create_project(user_id)
    item_id = await _create_item(user_id, project_id)

    run = _data(
        await _call(http, "dispatch_item", {"item_id": item_id}, _headers(api_key))
    )

    assert run["id"]
    failed = _events(logs, "mcp_http.enqueue_failed")
    assert len(failed) == 1
    assert failed[0].run_id == str(run["id"])
    assert failed[0].tool == "dispatch_item"


# --- AC-14: tool-table parity ---


async def test_tool_table_parity(started, http, api_key):
    stdio = {t.name: t for t in await mcp.list_tools()}
    http_tools = {
        t.name: t for t in await create_mcp_server(transport="http").list_tools()
    }

    assert set(http_tools) == set(stdio) - {"login"}
    assert "login" not in http_tools
    for name, tool in http_tools.items():
        twin = stdio[name]
        assert tool.name == twin.name
        assert tool.description == twin.description, name
        assert tool.parameters == twin.parameters, name
        assert tool.output_schema == twin.output_schema, name
        assert tool.annotations == twin.annotations, name

    res = await _rpc(http, "tools/list", {}, _headers(api_key))
    served = {t["name"]: t for t in res.json()["result"]["tools"]}
    assert set(served) == set(http_tools)
    for name, tool in served.items():
        assert tool["inputSchema"] == http_tools[name].parameters, name


# --- AC-15: one call sequence through both transports ---

# Volatile keys dropped before comparison: ids, *_id, *_at, board_state.
# "created_by" is NOT dropped: both legs must attribute to claude-lead-<user8>.
_DROP_KEYS = {"id", "board_state"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if k not in _DROP_KEYS and not k.endswith(("_id", "_at"))
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


async def _sequence(call: Any) -> list[Any]:
    """add_project -> add_item -> update_item -> add_comment -> list -> get.

    The comment tool's text parameter is ``content_markdown`` (there is no
    ``body`` parameter on add_comment).
    """
    out: list[Any] = []
    project = await call("add_project", {"name": "parity"})
    out.append(project)
    item = await call("add_item", {"title": "parity item", "project_id": project["id"]})
    out.append(item)
    out.append(
        await call(
            "update_item",
            {
                "item_id": item["id"],
                "status": "next_action",
                "version": item["version"],
            },
        )
    )
    out.append(
        await call("add_comment", {"item_id": item["id"], "content_markdown": "hello"})
    )
    out.append(await call("list_comments", {"item_id": item["id"]}))
    out.append(await call("get_item", {"item_id": item["id"]}))
    return out


async def test_shared_call_sequence_matches_across_transports(
    started, http, user_id, api_key, monkeypatch
):
    monkeypatch.setattr(srv, "_backend", LocalBackend())
    monkeypatch.setattr(srv, "_HTTP_MODE", False)
    monkeypatch.setattr(srv, "_ENV_API_KEY", api_key)
    monkeypatch.setattr(srv, "_ENV_AGENT_NAME", f"claude-lead-{user_id[:8]}")

    async def http_call(tool: str, args: dict[str, Any]) -> Any:
        result = await _call(http, tool, args, _headers(api_key))
        assert not result.get("isError"), _text(result)
        return result["structuredContent"]

    http_results = await _sequence(http_call)

    async with Client(mcp) as client:

        async def stdio_call(tool: str, args: dict[str, Any]) -> Any:
            result = await client.call_tool(tool, args)
            return result.structured_content

        stdio_results = await _sequence(stdio_call)

    assert len(http_results) == len(stdio_results) == 6
    for step, (h, s) in enumerate(zip(http_results, stdio_results, strict=True)):
        assert _scrub(h) == _scrub(s), f"step {step}"


# --- AC-17: fresh server per lifespan entry; ExceptionGroup unwrap ---


async def test_sequential_lifespans_build_fresh_servers(http, api_key, logs):
    expected = len({t.name for t in await mcp.list_tools()} - {"login"})
    seen = []
    for _ in range(2):
        async with mcp_http_lifespan(app):
            seen.append(app.state.mcp_http_app)
            res = await _rpc(http, "tools/list", {}, _headers(api_key))
            assert len(res.json()["result"]["tools"]) == expected
        assert app.state.mcp_http_app is None

    assert seen[0] is not seen[1]
    started_records = _events(logs, "mcp_http.started")
    assert len(started_records) == 2
    for record in started_records:
        assert record.tools == expected
        assert record.auth_mode == "bearer"
        assert record.levelno == logging.INFO
    assert len(_events(logs, "mcp_http.stopped")) == 2


async def test_local_mode_lifespan_logs_warning(monkeypatch, logs):
    monkeypatch.setattr(db_mod, "is_local_mode", lambda: True)
    async with mcp_http_lifespan(app):
        pass
    (record,) = _events(logs, "mcp_http.started")
    assert record.levelno == logging.WARNING
    assert record.auth_mode == "local-unauthenticated"


async def test_lifespan_unwraps_single_exception_group(monkeypatch, logs):
    import agent_gtd.mcp_http as mh

    class _FailingApp:
        @asynccontextmanager
        async def lifespan(self, _app: Any) -> AsyncIterator[None]:
            raise ExceptionGroup("g", [ValueError("boom")])
            yield  # pragma: no cover

    class _FakeServer:
        def http_app(self, **_kw: Any) -> _FailingApp:
            return _FailingApp()

        async def list_tools(self) -> list[Any]:
            return []

    monkeypatch.setattr(mh, "create_mcp_server", lambda **_kw: _FakeServer())

    with pytest.raises(ValueError, match="boom"):
        async with mcp_http_lifespan(app):
            pass  # pragma: no cover

    assert app.state.mcp_http_app is None
    failed = _events(logs, "mcp_http.lifespan_failed")
    assert len(failed) == 1
    assert failed[0].levelno == logging.ERROR


async def test_lifespan_reraises_multi_exception_group(monkeypatch):
    import agent_gtd.mcp_http as mh

    class _FailingApp:
        @asynccontextmanager
        async def lifespan(self, _app: Any) -> AsyncIterator[None]:
            raise ExceptionGroup("g", [ValueError("a"), KeyError("b")])
            yield  # pragma: no cover

    class _FakeServer:
        def http_app(self, **_kw: Any) -> _FailingApp:
            return _FailingApp()

        async def list_tools(self) -> list[Any]:
            return []

    monkeypatch.setattr(mh, "create_mcp_server", lambda **_kw: _FakeServer())

    with pytest.raises(ExceptionGroup):
        async with mcp_http_lifespan(app):
            pass  # pragma: no cover
    assert app.state.mcp_http_app is None


# --- AC-18: the HTTP server fails closed without a principal ---


async def test_http_server_without_principal_fails_closed(logs):
    server = create_mcp_server(transport="http")
    async with Client(server) as client:
        result = await client.call_tool(
            "add_project", {"name": "should-not-exist"}, raise_on_error=False
        )

    assert result.is_error
    text = " ".join(getattr(b, "text", "") for b in result.content)
    assert "without an authenticated principal" in text
    db = await get_db()
    row = await db.fetchrow(
        "SELECT COUNT(*) AS n FROM projects WHERE name = 'should-not-exist'"
    )
    assert int(row["n"]) == 0
    missing = _events(logs, "mcp_http.principal_missing")
    assert len(missing) == 1
    assert missing[0].levelno == logging.ERROR


# --- AC-19: stdio deprecation warning for remote boards ---


_DEPRECATION = "agent-gtd stdio MCP server is deprecated for remote boards"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://gtd.example.com/", "https://gtd.example.com/mcp"),
        ("http://127.0.0.1:8000", None),
        ("http://localhost:8000/", None),
        (None, None),
    ],
)
def test_stdio_main_deprecation_warning(monkeypatch, logs, url, expected):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(srv.mcp, "run", lambda **kw: calls.append(kw))
    if url is None:
        monkeypatch.delenv("AGENT_GTD_URL", raising=False)
    else:
        monkeypatch.setenv("AGENT_GTD_URL", url)

    srv.main()

    assert calls == [{"transport": "stdio"}]
    warnings = [
        r
        for r in logs.records
        if r.name == "agent_gtd.mcp_server" and _DEPRECATION in r.getMessage()
    ]
    if expected is None:
        assert warnings == []
    else:
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING
        message = warnings[0].getMessage()
        assert f"register {expected} as a streamable HTTP MCP server" in message
        assert 'header "Authorization: Bearer <key>" instead' in message


# --- AC-22: per-call tool logging ---


async def test_tool_call_records(started, http, user_id, api_key, logs):
    item_id = await _create_item(user_id, None, build_engine="claude-code-sonnet")
    await _call(
        http,
        "add_comment",
        {"content_markdown": "hi", "item_id": item_id},
        _headers(api_key),
    )
    token = create_token(user_id, run_id=str(uuid.uuid4()), run_mode="plan")
    await _call(
        http,
        "update_item",
        {
            "item_id": item_id,
            "version": await _version(item_id),
            "build_engine": "claude-code",
        },
        _headers(token),
    )

    records = _events(logs, "mcp_http.tool_call")
    assert [(r.tool, r.outcome) for r in records] == [
        ("add_comment", "ok"),
        ("update_item", "tool_error"),
    ]
    assert records[0].error is None
    assert "Plan-mode run may not change build_engine" in records[1].error
    assert all(isinstance(r.duration_ms, int) for r in records)


async def test_tool_call_unexpected_exception_logged(
    started, http, api_key, monkeypatch, logs
):
    async def _explode(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(BoardBackend, "list_projects", _explode)

    result = await _call(http, "list_projects", {}, _headers(api_key))

    assert result["isError"] is True
    records = _events(logs, "mcp_http.tool_call")
    assert [(r.tool, r.outcome) for r in records] == [("list_projects", "exception")]
    assert records[0].levelno == logging.ERROR


async def test_tool_call_non_tool_error_logged(started, http, api_key, logs):
    """An exception FastMCP does not wrap (argument validation) is logged too."""
    res = await _rpc(
        http,
        "tools/call",
        {"name": "get_item", "arguments": {}},
        _headers(api_key),
    )
    assert res.status_code == 200
    records = _events(logs, "mcp_http.tool_call")
    assert [(r.tool, r.outcome) for r in records] == [("get_item", "exception")]
    assert records[0].levelno == logging.ERROR
