"""Contract tests: dispatch payload shapes and manage-tool allowlist.

Two test groups verify cross-repo contracts between agent_gtd and the
shared ``agent_gtd_dispatch_protocol`` package:

1. ``TestDispatchPayloadContract`` — the four ``DispatchRequest`` body shapes
   that ``_dispatch_to_remote()`` in ``dispatch_worker.py:245-257`` can produce
   are all valid per the shared protocol schema.  No network calls required —
   pure Pydantic validation.

2. ``TestManageToolAllowlist`` — every tool name in ``MANAGE_ALLOWED_TOOLS``
   (from the shared protocol package) is registered in the MCP server.
   Skipped until the companion dispatch-repo change exports
   ``MANAGE_ALLOWED_TOOLS`` from ``agent_gtd_dispatch_protocol``.

Cancel endpoint note (AC-6):
    ``POST /runs/{id}/cancel`` sends no request body (see ``_cancel_remote_run``
    in ``dispatch_worker.py:282-297``).  The protocol package does not export a
    ``CancelRequest`` model, so there is no Pydantic contract to validate on the
    gtd side.

Companion dispatch-repo change required for AC-2:
    Export ``MANAGE_ALLOWED_TOOLS`` from ``agent_gtd_dispatch_protocol/__init__.py``.
    The dispatch service currently defines ``_MANAGE_ALLOWED_TOOLS`` inline in
    ``dispatch.py:225-245``; it should import from the shared package so both
    repos stay in sync.  Once that change lands, ``TestManageToolAllowlist``
    will begin running in CI automatically (the ``skipif`` guard lifts).
"""

import pytest
from agent_gtd_dispatch_protocol import DispatchRequest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# MANAGE_ALLOWED_TOOLS — guarded import until companion change lands
# ---------------------------------------------------------------------------
# When the dispatch repo exports MANAGE_ALLOWED_TOOLS from the protocol
# package, the import below succeeds and TestManageToolAllowlist runs.
# Until then, _HAS_MANAGE_ALLOWED_TOOLS is False and the class is skipped.
try:
    from agent_gtd_dispatch_protocol import (
        MANAGE_ALLOWED_TOOLS,  # type: ignore[attr-defined]
    )

    _HAS_MANAGE_ALLOWED_TOOLS = True
except ImportError:
    MANAGE_ALLOWED_TOOLS: list[str] = []  # placeholder; class is skipped below
    _HAS_MANAGE_ALLOWED_TOOLS = False

from agent_gtd.mcp_server import mcp

# MCP tool names are qualified as "mcp__agent-gtd__<bare>" on the client side;
# the server registry stores bare names.  Strip this prefix before looking up.
_QUALIFIED_PREFIX = "mcp__agent-gtd__"

# ---------------------------------------------------------------------------
# Payload shapes produced by _dispatch_to_remote() (dispatch_worker.py:245-257)
#
# The function calls DispatchRequest(...).model_dump(exclude_none=True) to
# build the POST /dispatch body.  Shapes (a)-(d) below represent the four
# distinct combinations the caller can produce.
# ---------------------------------------------------------------------------

# (a) Minimal valid build dispatch: no optional item_id / agent_name /
#     attribution / rollout_id — these are excluded by exclude_none=True.
_MINIMAL_BUILD: dict[str, object] = {
    "max_turns": 100,
    "mode": "build",
    "engine": "claude-code",
    "timeout_minutes": 30,
}

# (b) All optional fields set on a build dispatch.
_ALL_FIELDS_BUILD: dict[str, object] = {
    "max_turns": 100,
    "mode": "build",
    "engine": "claude-code",
    "timeout_minutes": 30,
    "item_id": "item-abc123",
    "agent_name": "test-agent",
    "attribution": "claude-build-xyz",
}

# (c) Manage-mode: rollout_id set; item_id deliberately absent because
#     manage runs are not scoped to a single item.
_MANAGE: dict[str, object] = {
    "max_turns": 200,
    "mode": "manage",
    "rollout_id": "rollout-abc123",
    "engine": "claude-code",
    "timeout_minutes": 60,
}

# (d) Plan-mode: item_id set, mode="plan".
_PLAN: dict[str, object] = {
    "max_turns": 50,
    "mode": "plan",
    "item_id": "item-def456",
    "engine": "claude-code",
    "timeout_minutes": 30,
}


class TestDispatchPayloadContract:
    """Payload shapes from _dispatch_to_remote() must validate against DispatchRequest.

    AC-3 / additive-evolution guarantee:
        If a future protocol version adds a new *optional* field to
        DispatchRequest (with a default or default_factory), omitting it from
        the body dicts below still passes model_validate — Pydantic fills in
        the default.  Only a new *required* field (no default) would cause a
        ValidationError; in that case the missing field name appears in the
        error message (see test_missing_required_field_raises for a
        demonstration of this failure mode).
    """

    # AC-3 no-op parametrize case: _MINIMAL_BUILD intentionally omits the
    # optional fields (item_id, agent_name, attribution, rollout_id).  Its
    # presence in the matrix proves that absent optional fields do not break
    # validation — Pydantic supplies their defaults transparently.
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(_MINIMAL_BUILD, id="minimal-build"),
            pytest.param(_ALL_FIELDS_BUILD, id="all-fields-build"),
            pytest.param(_MANAGE, id="manage-mode"),
            pytest.param(_PLAN, id="plan-mode"),
        ],
    )
    def test_payload_validates(self, body: dict[str, object]) -> None:
        """Each body dict validates against DispatchRequest without raising.

        No ValidationError = pass.  The call itself is the assertion.
        """
        DispatchRequest.model_validate(body)

    def test_missing_required_field_raises(self) -> None:
        """Absent required field raises ValidationError naming the missing field.

        Documents the additive-evolution failure mode: if a future protocol
        version adds a required field and gtd's body dict omits it, the error
        surfaces here with the field name in the message.
        """
        body = dict(_MINIMAL_BUILD)
        del body["max_turns"]
        with pytest.raises(ValidationError) as exc_info:
            DispatchRequest.model_validate(body)
        assert "max_turns" in str(exc_info.value)

    def test_manage_mode_omits_item_id(self) -> None:
        """Manage-mode body has no item_id; DispatchRequest defaults it to None."""
        req = DispatchRequest.model_validate(_MANAGE)
        assert req.item_id is None

    def test_plan_mode_carries_item_id(self) -> None:
        """Plan-mode body includes item_id; DispatchRequest preserves it."""
        req = DispatchRequest.model_validate(_PLAN)
        assert req.item_id == "item-def456"


@pytest.mark.skipif(
    not _HAS_MANAGE_ALLOWED_TOOLS,
    reason=(
        "MANAGE_ALLOWED_TOOLS not yet exported from agent_gtd_dispatch_protocol. "
        "Companion dispatch-repo change required: export MANAGE_ALLOWED_TOOLS from "
        "agent_gtd_dispatch_protocol/__init__.py so the dispatch service imports the "
        "allowlist from the shared package instead of defining it inline."
    ),
)
class TestManageToolAllowlist:
    """Every tool in MANAGE_ALLOWED_TOOLS must be registered in the MCP server.

    Uses FastMCP's public async API (await mcp.list_tools()) — no private
    attributes.  No network calls: the MCP server is introspected in-process.

    AC-4: failure message is exactly
        f'manage allowlist references undefined tool: {qualified_name}'
    """

    async def test_all_allowlist_tools_registered(self) -> None:
        """Every mcp__agent-gtd__* name in MANAGE_ALLOWED_TOOLS must be registered."""
        tools = await mcp.list_tools()
        bare_names = {t.name for t in tools}

        for qualified_name in MANAGE_ALLOWED_TOOLS:
            bare_name = qualified_name.removeprefix(_QUALIFIED_PREFIX)
            assert bare_name in bare_names, (
                f"manage allowlist references undefined tool: {qualified_name}"
            )
