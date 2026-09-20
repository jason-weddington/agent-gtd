"""Pydantic v2 domain models for Agent GTD."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, assert_never

from agent_gtd_dispatch_protocol import DispatchMode as DispatchMode
from agent_gtd_dispatch_protocol import RunStatus as RemoteRunStatus
from pydantic import BaseModel, Field, field_validator

from agent_gtd.dispatch_constants import MANAGER_DEFAULT_TIMEOUT_MINUTES

# --- Enums ---


class ProjectStatus(StrEnum):
    """Project lifecycle status."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"


class RepoMode(StrEnum):
    """Project repository mode.

    MONOREPO: single git repo (default, today's behaviour).
    WORKSPACE: ordered list of git clone URLs that the dispatch host checks
               out together under a shared workspace root.
    """

    MONOREPO = "monorepo"
    WORKSPACE = "workspace"


class ItemStatus(StrEnum):
    """GTD item status."""

    INBOX = "inbox"
    NEW = "new"
    READY = "ready"
    NEXT_ACTION = "next_action"
    WAITING_FOR = "waiting_for"
    SCHEDULED = "scheduled"
    SOMEDAY_MAYBE = "someday_maybe"
    ACTIVE = "active"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(StrEnum):
    """Item priority level."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class LocalRunStatus(StrEnum):
    """Claude dispatch run status (local/internal representation).

    Use ``from_remote()`` to convert a shared protocol ``RunStatus`` value
    to the corresponding local status.
    """

    PENDING = "pending"
    CLONING = "cloning"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @classmethod
    def from_remote(cls, remote: RemoteRunStatus) -> "LocalRunStatus":
        """Map a remote dispatch-service status to the local run status.

        This mapping is total — every value in the shared
        ``agent_gtd_dispatch_protocol.RunStatus`` enum has an explicit
        branch.  Adding a new remote status without updating this method
        will cause a ``mypy --strict`` failure at the ``case _:`` guard.

        Args:
            remote: A status value from ``agent_gtd_dispatch_protocol.RunStatus``.

        Returns:
            The corresponding ``LocalRunStatus``.
        """
        match remote:
            case RemoteRunStatus.succeeded:
                return cls.SUCCESS
            case RemoteRunStatus.already_satisfied:
                # The agent found the acceptance criteria already met and the
                # quality gate passed on the untouched tree.  That is a terminal
                # without error, so it mirrors as SUCCESS: mapping it to FAILED
                # would halt a rollout wave over healthy work.
                #
                # It does NOT mean the item is done, and nothing here implies
                # that — SUCCESS drives only the stored local status and the SSE
                # event type.  The dispatch service owns the item transition
                # (PATCH to `review`) and records the rollout child as `skipped`
                # so the wave advances.  The local enum deliberately grows no
                # `already_satisfied` member: that would change persisted values
                # and the UI for a distinction only the dispatch side acts on.
                return cls.SUCCESS
            case RemoteRunStatus.failed:
                return cls.FAILED
            case RemoteRunStatus.timed_out:
                return cls.TIMEOUT
            case RemoteRunStatus.cancelled:
                return cls.CANCELLED
            case RemoteRunStatus.pending:
                return cls.PENDING
            case RemoteRunStatus.running:
                return cls.RUNNING
            case _:
                assert_never(remote)


class RolloutStatus(StrEnum):
    """Autonomous rollout lifecycle status."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RolloutItemStatus(StrEnum):
    """Status of a single item within a rollout plan."""

    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    HALTED = "halted"
    SKIPPED = "skipped"


class RolloutEventActor(StrEnum):
    """Actor that generated a rollout event."""

    MANAGER = "manager"
    CHILD_AGENT = "child-agent"
    HUMAN = "human"


class MergeActor(StrEnum):
    """Who merged (or will merge) the PR for a wave plan item."""

    HUMAN = "human"
    MANAGER_ALLOWLIST = "manager-allowlist"
    MANAGER_AUTONOMOUS = "manager-autonomous"
    MANAGER_HUMAN_FIXUP = "manager+human-fixup"
    # The short-lived reviewer the worker-driven wave loop launches per item. A
    # distinct actor from the manager, so it gets a distinct value rather than
    # being folded into `manager-autonomous`: the whole point of the redesign is
    # that no long-lived manager exists, and the merge record should say who
    # actually decided. Added after the dispatch side began sending it and every
    # completion 422'd — the merge had already landed and only the bookkeeping
    # failed, which halted the whole rollout and stopped two unrelated items.
    REVIEWER_AUTONOMOUS = "reviewer-autonomous"


class BuildEngine(StrEnum):
    """Dispatch build engine identifier.

    Union of all currently registered engines across item.build_engine and
    settings.engine use-cases.
    """

    CLAUDE_CODE = "claude-code"
    CLAUDE_CODE_OLLAMA = "claude-code-ollama"
    CLAUDE_CODE_GLM = "claude-code-glm"
    CLAUDE_CODE_SONNET = "claude-code-sonnet"
    CLAUDE_CODE_HAIKU = "claude-code-haiku"
    KIRO = "kiro"
    # Talos engine family (dispatched via the agent-gtd-dispatch talos.py
    # subprocess path; see kb-* + item 2f79463d). BUILD-mode only: talos has no
    # GTD/MCP access, so a plan dispatch on an item with a talos build_engine
    # falls back to the global dispatch engine at the dispatch worker instead of
    # attempting to run talos in plan mode. Manage-mode stays pinned to
    # MANAGE_ENGINE regardless of item build_engine.
    TALOS_HAIKU = "talos-haiku"
    TALOS_SONNET = "talos-sonnet"
    TALOS_OPUS = "talos-opus"
    TALOS_QWEN = "talos-qwen"
    TALOS_GLM = "talos-glm"
    TALOS_GLM_FLASH = "talos-glm-flash"


TALOS_ENGINES: frozenset[str] = frozenset(
    member.value for member in BuildEngine if member.value.startswith("talos-")
)
"""Build engines that are build-mode only (see `BuildEngine` docstring above).

Derived from the enum so a future `talos-*` member is automatically included.
"""


CLAUDE_CODE_ENGINES: frozenset[str] = frozenset(
    member.value for member in BuildEngine if member.value.startswith("claude-code")
)
"""Engines that drive the Claude Code harness.

Derived from the enum so a future `claude-code-*` member is automatically
included.  This is the HARNESS family, not a model tier — the mirror of
``agent_gtd_dispatch.engines.Engine.is_claude_code_family`` on the dispatch
side, which grants a manage-mode run the dispatch URL + key it needs to
dispatch its own children.
"""


MANAGE_CAPABLE_ENGINES: frozenset[str] = CLAUDE_CODE_ENGINES
"""Engines that may drive a manage-mode (rollout manager) run.

Manage mode runs a multi-wave loop: it dispatches child build runs, waits on
them, reconciles acceptance criteria and merges.  Only the Claude Code harness
family can do that today — it is also the only family the dispatch service
grants ``_MANAGE_EXECUTOR_ENV_KEYS`` to, so an engine outside it would come up
without the dispatch URL/key and fail in a way that reads as a model problem.
"""


def manage_engine_rejection(engine: str) -> str | None:
    """Return an error message when *engine* cannot drive manage mode.

    Returns ``None`` when the engine is manage-capable.  The message is written
    to be read by a human at the API boundary, so it says WHY rather than just
    that the value was refused.
    """
    if engine in TALOS_ENGINES:
        return (
            f"manage_engine {engine!r} is not supported: talos engines"
            " self-verify a single gate and return a disposition — they are not"
            " a harness that can drive a multi-wave manager loop, dispatch child"
            " runs and merge their work. Choose one of:"
            f" {', '.join(sorted(MANAGE_CAPABLE_ENGINES))}."
        )
    if engine not in MANAGE_CAPABLE_ENGINES:
        return (
            f"manage_engine {engine!r} is not manage-capable: manage mode needs"
            " the Claude Code harness, which is the only family granted the"
            " dispatch URL and key a manager uses to dispatch its children."
            f" Choose one of: {', '.join(sorted(MANAGE_CAPABLE_ENGINES))}."
        )
    return None


REVIEW_CAPABLE_ENGINES: frozenset[str] = CLAUDE_CODE_ENGINES
"""Engines that may drive a REVIEW-mode (per-build merge reviewer) run.

Same family as ``MANAGE_CAPABLE_ENGINES`` but for a different reason, and the
distinction matters: a manager needs the Claude Code harness because it
dispatches child runs with the dispatch URL + key.  A reviewer is explicitly
NOT granted those keys (it returns a verdict; the worker dispatches).  It needs
the harness because it drives git, runs the project gate command and writes a
structured verdict artifact — work a single-gate self-verifying engine cannot
do.
"""


def reviewer_engine_rejection(engine: str) -> str | None:
    """Return an error message when *engine* cannot drive review mode.

    Returns ``None`` when the engine is review-capable.  Kept separate from
    :func:`manage_engine_rejection` because the two refuse for different
    reasons and a reviewer must never be told it was refused for lacking
    dispatch keys it is deliberately denied.
    """
    if engine in TALOS_ENGINES:
        return (
            f"reviewer_engine {engine!r} is not supported: talos engines"
            " self-verify a single gate and return a disposition — they cannot"
            " drive the git merge dance or emit a bounded review verdict."
            f" Choose one of: {', '.join(sorted(REVIEW_CAPABLE_ENGINES))}."
        )
    if engine not in REVIEW_CAPABLE_ENGINES:
        return (
            f"reviewer_engine {engine!r} is not review-capable: review mode"
            " needs the Claude Code harness to read a diff, run the project"
            " gate command and perform the merge."
            f" Choose one of: {', '.join(sorted(REVIEW_CAPABLE_ENGINES))}."
        )
    return None


class RolloutEventKind(StrEnum):
    """Kind of event emitted during a rollout."""

    WAVE_PLANNED = "wave_planned"
    ITEM_OUTCOME = "item_outcome"
    WAVE_COMPLETED = "wave_completed"
    COMMENT_POSTED = "comment_posted"
    WAVE_HALTED = "wave_halted"
    MANAGE_RELAUNCHED = "manage_relaunched"
    WAVE_CANCELLED = "wave_cancelled"
    WAVE_STARTED = "wave_started"
    # Historical only: emitted by the removed LLM replanner.  Retained so
    # existing rollout_events rows still deserialise.
    WAVE_REPLANNED = "wave_replanned"
    MANAGER_STATE_UPDATE = "manager_state_update"
    WAVE_RESUMED = "wave_resumed"
    # A dispatched item was returned to 'ready' so the worker can re-dispatch
    # it after a reviewer returned a `re-dispatch` verdict.
    ITEM_RESET = "item_reset"


class RolloutItemOutcome(StrEnum):
    """Outcome of a single item within a rollout."""

    COMPLETED = "completed"
    HALTED = "halted"
    SKIPPED = "skipped"


class ManagerPhase(StrEnum):
    """Current execution phase of the rollout manager."""

    WARM_UP = "warm_up"
    DISPATCHING = "dispatching"
    POLLING = "polling"
    REVIEWING = "reviewing"
    MERGING = "merging"
    RECONCILING_AC = "reconciling_ac"
    HALTED = "halted"


# --- Domain Models ---


class User(BaseModel):
    """App user account."""

    id: str
    email: str
    hashed_password: str
    is_admin: bool = False
    created_at: datetime


class Project(BaseModel):
    """A GTD project."""

    id: str
    user_id: str
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    area: str = ""
    git_origin: str = ""
    kb_project_ref: str = ""
    repo_mode: RepoMode = RepoMode.MONOREPO
    workspace_repos: list[str] = []
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None
    # Engine used for manage-mode (rollout manager) runs. None = use the
    # deployment default (claude-code / Opus). See dispatch_worker.resolve_engine.
    manage_engine: BuildEngine | None = None
    # Engine used for REVIEW-mode (per-build merge reviewer) runs. None = use
    # the deployment default (claude-code-sonnet). A per-rollout value
    # overrides this. See dispatch_worker.resolve_reviewer_engine.
    reviewer_engine: BuildEngine | None = None
    # Per-repo/per-workspace-repo gate commands are DEFERRED to ~0.5.0
    # (workspace_repos stays a plain URL list until then); gate_command is a
    # single project-level nullable shell string.
    gate_command: str | None = None
    created_at: datetime
    updated_at: datetime


class Item(BaseModel):
    """A GTD action item."""

    id: str
    project_id: str | None = None
    user_id: str
    title: str
    description: str = ""
    status: ItemStatus = ItemStatus.INBOX
    priority: Priority = Priority.NORMAL
    due_date: datetime | None = None
    completed_at: datetime | None = None
    created_by: str = "human"
    assigned_to: str = ""
    waiting_on: str = ""
    sort_order: float = 0
    labels: list[str] = []
    version: int = 1
    locked_by_rollout_id: str | None = None
    build_engine: BuildEngine | None = None
    acceptance_criteria: list[str] = []
    files_to_modify: list[dict[str, Any]] = []
    scope_out: list[str] = []
    created_at: datetime
    updated_at: datetime


class Note(BaseModel):
    """A project note."""

    id: str
    project_id: str
    user_id: str
    title: str = ""
    content_markdown: str = ""
    labels: list[str] = []
    created_at: datetime
    updated_at: datetime


class Comment(BaseModel):
    """A comment on a project or item."""

    id: str
    project_id: str | None = None
    item_id: str | None = None
    user_id: str
    content_markdown: str = ""
    created_by: str = "human"
    created_at: datetime
    updated_at: datetime


class Event(BaseModel):
    """A server-sent event record."""

    id: str
    user_id: str
    event_type: str
    entity_type: str
    entity_id: str
    project_id: str | None = None
    payload: str
    created_at: datetime


class Attachment(BaseModel):
    """A file attachment on a GTD item."""

    id: str
    item_id: str
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    created_at: datetime


class Rollout(BaseModel):
    """An autonomous rollout coordinating multiple agent dispatches."""

    id: str
    project_id: str
    lead_user_id: str
    status: RolloutStatus
    halt_reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    dispatch_host_id: str | None = None
    created_at: datetime
    updated_at: datetime


class RolloutPlan(BaseModel):
    """A DAG plan produced by the planner for a rollout."""

    id: str
    rollout_id: str
    version: int
    nodes: list[str]
    edges: list[dict[str, str]]
    planner_model: str
    created_at: datetime


class RolloutItem(BaseModel):
    """Tracking record for a single item within a rollout plan."""

    rollout_id: str
    item_id: str
    status: RolloutItemStatus
    claude_run_id: str | None = None
    completed_at: datetime | None = None
    merge_actor: MergeActor | None = None


class RolloutEvent(BaseModel):
    """A structured event emitted during a rollout."""

    id: str
    rollout_id: str
    seq: int
    ts: datetime
    kind: RolloutEventKind
    actor: RolloutEventActor
    decision_rule: Literal["", "agent-judgment"]
    payload: dict[str, Any]


# --- API Request/Response Schemas ---


class RegisterRequest(BaseModel):
    """Account registration request."""

    email: str
    password: str
    invite_token: str


class LoginRequest(BaseModel):
    """Login request."""

    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    """Change own password (authenticated)."""

    current_password: str
    new_password: str


class AuthResponse(BaseModel):
    """Auth response with JWT token."""

    token: str
    user: "UserResponse"


class UserResponse(BaseModel):
    """Public user info (no password hash)."""

    id: str
    email: str
    is_admin: bool
    created_at: datetime


# --- Invite Schemas ---


class CreateInviteRequest(BaseModel):
    """Create a new invite token (admin only)."""

    note: str = ""


class InviteResponse(BaseModel):
    """Invite creation response with one-time-use token."""

    token: str
    url: str
    note: str
    created_at: datetime


class InviteListItem(BaseModel):
    """Single invite entry in the admin invite list."""

    token: str
    issued_by: str
    note: str
    created_at: datetime
    used_at: datetime | None
    used_by: str | None


# --- Password Reset Schemas ---


class PasswordResetIssueResponse(BaseModel):
    """Admin response when issuing a one-time password-reset link."""

    token: str
    url: str
    expires_at: datetime


class PasswordResetConsumeRequest(BaseModel):
    """Public request body for consuming a password-reset token."""

    token: str
    new_password: str


# --- API Key Schemas ---


class CreateApiKeyRequest(BaseModel):
    """Create a new API key."""

    name: str = ""


class ApiKeyResponse(BaseModel):
    """API key creation response — plaintext key shown only once."""

    api_key: str
    name: str


class ApiKeyInfo(BaseModel):
    """API key metadata (no secret material)."""

    id: str
    name: str
    hash_prefix: str
    created_at: datetime


class ApiKeyListResponse(BaseModel):
    """List of API keys for the current user."""

    keys: list[ApiKeyInfo]


# --- Project Schemas ---


class CreateProjectRequest(BaseModel):
    """Create a new project."""

    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    area: str = ""
    git_origin: str = ""
    kb_project_ref: str = ""
    repo_mode: RepoMode = RepoMode.MONOREPO
    workspace_repos: list[str] = []
    gate_command: str | None = None


class UpdateProjectRequest(BaseModel):
    """Update a project. All fields optional.

    For dispatch_max_turns, dispatch_timeout_minutes, plan_dispatch_agent,
    build_dispatch_agent, and manage_engine:
    - Field absent → unchanged
    - Field explicitly null → clear the override (revert to inheriting global)
    - Field set → persist the value

    For repo_mode and workspace_repos:
    - Field absent → unchanged
    - Field set → persist the value (None = unchanged, not a clear)
    """

    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    area: str | None = None
    git_origin: str | None = None
    kb_project_ref: str | None = None
    repo_mode: RepoMode | None = None
    workspace_repos: list[str] | None = None
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None
    manage_engine: BuildEngine | None = None
    reviewer_engine: BuildEngine | None = None
    gate_command: str | None = None

    @field_validator("manage_engine")
    @classmethod
    def _validate_manage_engine(cls, v: BuildEngine | None) -> BuildEngine | None:
        """Reject non-manage-capable engines at the API boundary.

        An unknown engine is already rejected by the ``BuildEngine`` enum; this
        catches the registered-but-not-manage-capable ones (talos, kiro) so the
        problem surfaces on save rather than at manager launch time.
        """
        if v is None:
            return v
        rejection = manage_engine_rejection(v.value)
        if rejection is not None:
            raise ValueError(rejection)
        return v

    @field_validator("reviewer_engine")
    @classmethod
    def _validate_reviewer_engine(cls, v: BuildEngine | None) -> BuildEngine | None:
        """Reject non-review-capable engines at the API boundary.

        Mirrors ``_validate_manage_engine``: the enum already rejects unknown
        engines, so this catches the registered-but-not-review-capable ones
        (talos, kiro) on save rather than at reviewer launch time.
        """
        if v is None:
            return v
        rejection = reviewer_engine_rejection(v.value)
        if rejection is not None:
            raise ValueError(rejection)
        return v


class ProjectResponse(BaseModel):
    """Project data returned from API."""

    id: str
    name: str
    description: str
    status: ProjectStatus
    area: str
    git_origin: str
    kb_project_ref: str
    repo_mode: RepoMode = RepoMode.MONOREPO
    workspace_repos: list[str] = []
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None
    manage_engine: BuildEngine | None = None
    reviewer_engine: BuildEngine | None = None
    gate_command: str | None = None
    created_at: datetime
    updated_at: datetime
    is_owner: bool | None = None
    owner_email: str | None = None
    member_count: int | None = None
    total_items: int = 0  # open (non-done) items only
    description_preview: str | None = None


# --- Member Schemas ---


class MemberSummary(BaseModel):
    """Project member data returned from API."""

    user_id: str
    email: str
    added_at: datetime


class AddMemberRequest(BaseModel):
    """Add a member to a project by email."""

    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate basic email shape."""
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.strip()):
            raise ValueError("Invalid email format")
        return v.strip().lower()


# --- Item Schemas ---


class BlockerSummary(BaseModel):
    """Lightweight item summary used in blocker picker and search results."""

    id: str
    title: str
    status: ItemStatus
    project_id: str | None
    project_name: str | None


class AddBlockerRequest(BaseModel):
    """Request to add a blocker to an item."""

    blocker_item_id: str


class CreateItemRequest(BaseModel):
    """Create a new item."""

    title: str
    description: str = ""
    project_id: str | None = None
    status: ItemStatus = ItemStatus.INBOX
    priority: Priority = Priority.NORMAL
    due_date: str | None = None
    created_by: str | None = None
    assigned_to: str = ""
    waiting_on: str = ""
    sort_order: float = 0
    labels: list[str] = []
    build_engine: BuildEngine | None = None
    acceptance_criteria: list[str] = []
    files_to_modify: list[dict[str, Any]] = []
    scope_out: list[str] = []


class UpdateItemRequest(BaseModel):
    """Update an item. All fields optional."""

    title: str | None = None
    description: str | None = None
    project_id: str | None = None
    status: ItemStatus | None = None
    priority: Priority | None = None
    due_date: str | None = None
    assigned_to: str | None = None
    waiting_on: str | None = None
    sort_order: float | None = None
    labels: list[str] | None = None
    build_engine: BuildEngine | None = None
    acceptance_criteria: list[str] | None = None
    files_to_modify: list[dict[str, Any]] | None = None
    scope_out: list[str] | None = None
    version: int | None = None


class InboxCaptureRequest(BaseModel):
    """Quick capture to inbox — title only."""

    title: str
    created_by: str | None = None


class ClaimItemRequest(BaseModel):
    """Claim an item for an agent."""

    agent_name: str


class ItemResponse(BaseModel):
    """Item data returned from API."""

    id: str
    project_id: str | None
    title: str
    description: str
    status: ItemStatus
    priority: Priority
    due_date: str | None
    completed_at: str | None
    created_by: str
    assigned_to: str
    waiting_on: str
    sort_order: float
    labels: list[str]
    version: int
    locked_by_rollout_id: str | None = None
    build_engine: BuildEngine | None = None
    acceptance_criteria: list[str] = []
    files_to_modify: list[dict[str, Any]] = []
    scope_out: list[str] = []
    created_at: datetime
    updated_at: datetime
    blockers: list[BlockerSummary] = []


# --- Note Schemas ---


class CreateNoteRequest(BaseModel):
    """Create a new project note."""

    title: str = ""
    content_markdown: str = ""
    labels: list[str] = []


class UpdateNoteRequest(BaseModel):
    """Update a note. All fields optional."""

    title: str | None = None
    content_markdown: str | None = None
    labels: list[str] | None = None


class NoteResponse(BaseModel):
    """Note data returned from API."""

    id: str
    project_id: str
    title: str
    content_markdown: str
    labels: list[str]
    created_at: datetime
    updated_at: datetime


# --- Comment Schemas ---


class CreateCommentRequest(BaseModel):
    """Create a new comment."""

    content_markdown: str
    created_by: str | None = None


class UpdateCommentRequest(BaseModel):
    """Update a comment. All fields optional."""

    content_markdown: str | None = None


class CommentResponse(BaseModel):
    """Comment data returned from API."""

    id: str
    project_id: str | None
    item_id: str | None
    content_markdown: str
    created_by: str
    created_at: datetime
    updated_at: datetime


# --- Dispatch Run Schemas ---


class CreateRunRequest(BaseModel):
    """Dispatch a Claude Code agent for an item."""

    max_turns: int | None = None
    mode: DispatchMode = DispatchMode.BUILD
    rollout_id: str | None = None
    dispatch_host_id: str | None = None


class DispatchSettingsResponse(BaseModel):
    """Full dispatch settings returned from GET /api/settings/dispatch."""

    engine: BuildEngine
    plan_agent_name: str = ""
    build_agent_name: str = ""
    default_max_turns: int = 100
    default_timeout_minutes: int = 30
    manager_default_timeout_minutes: int = MANAGER_DEFAULT_TIMEOUT_MINUTES
    service_url: str
    service_api_key_preview: str = ""


class UpdateDispatchSettingsRequest(BaseModel):
    """Body for PATCH /api/settings/dispatch — per-user dispatch config.

    Only provided fields are updated; omit a field to leave it unchanged.
    """

    engine: BuildEngine | None = None
    plan_agent_name: str | None = None
    build_agent_name: str | None = None
    service_url: str | None = None
    service_api_key: str | None = None
    default_max_turns: int | None = None
    default_timeout_minutes: int | None = None
    manager_default_timeout_minutes: int | None = None


class RunResponse(BaseModel):
    """Claude dispatch run data returned from API."""

    id: str
    item_id: str | None = None
    project_id: str
    status: LocalRunStatus
    feature_branch: str
    workspace_dir: str
    max_turns: int
    mode: DispatchMode
    started_at: datetime | None
    finished_at: datetime | None
    error_msg: str
    rollout_id: str | None = None
    engine: str | None = None
    engine_actual: str | None = None
    dispatch_host_url: str | None = None
    created_at: datetime
    updated_at: datetime
    dispatched_by_email: str | None = None
    remote_run_id: str = ""


class FailedRunResponse(RunResponse):
    """Enriched run data for the failures feed (failed / timeout runs)."""

    item_title: str | None = None
    project_name: str = ""


class StaleRunResponse(FailedRunResponse):
    """Enriched run data for the stale-completed feed.

    A stale run is a successful build-mode run whose linked item has not been
    advanced to review/done/cancelled — the agent skipped the status flip.
    """

    item_status: str = ""


class RolloutFailureFeed(BaseModel):
    """Per-rollout failure feed aggregating halt events and failed runs."""

    wave_halts: list[dict[str, object]] = []
    failed_runs: list[FailedRunResponse] = []


# --- Attachment Schemas ---


class AttachmentResponse(BaseModel):
    """Attachment metadata returned from the API (no storage internals)."""

    id: str
    item_id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime


# --- Dispatch Capabilities Schemas ---


class DispatchAgentInfo(BaseModel):
    """Info about a single agent available on the dispatch service."""

    name: str
    description: str = ""


class DispatchCapabilitiesResponse(BaseModel):
    """Response shape for the /api/dispatch/capabilities proxy endpoint."""

    engines: list[str] = []
    versions: list[str] = []
    agents: list[DispatchAgentInfo] = []
    total_capacity: int | None = None


class DispatchHostResponse(BaseModel):
    """A configured dispatch host (API key masked)."""

    id: str
    label: str
    url: str
    api_key_preview: str  # "****" + last-4, never full key
    created_at: datetime


class AddDispatchHostRequest(BaseModel):
    """Request to add a new dispatch host."""

    label: str = ""
    url: str  # Must be non-empty, stripped
    api_key: str  # Must be non-empty


# --- Rollout Manager Schemas ---


class PlanRolloutItemSummary(BaseModel):
    """Per-item summary within a rollout plan result."""

    item_id: str
    title: str
    predecessors: list[str] = []


class PlanRolloutPlan(BaseModel):
    """The DAG plan nested inside a PlanRolloutResult."""

    nodes: list[str]
    edges: list[dict[str, str]]


class PlanRolloutResult(BaseModel):
    """Response returned by the plan_rollout MCP tool on success."""

    rollout_id: str
    status: RolloutStatus
    plan: PlanRolloutPlan
    planner_model: str
    item_count: int
    per_item: list[PlanRolloutItemSummary]


class InFlightBuildRun(BaseModel):
    """A non-terminal child build run tracked under a rollout (derived on read).

    Derived at read time from a JOIN of rollout_items -> claude_runs.
    Never persisted; no new column on autonomous_rollouts.
    """

    run_id: str = Field(alias="runId", serialization_alias="runId")
    item_id: str = Field(alias="itemId", serialization_alias="itemId")
    status: str


class RolloutResponse(BaseModel):
    """Rollout data returned from the API, augmented with progress counts."""

    id: str
    project_id: str
    lead_user_id: str
    status: RolloutStatus
    halt_reason: str | None
    started_at: str | None
    ended_at: str | None
    created_at: str
    updated_at: str
    total_count: int
    done_count: int
    in_flight_build_runs: list[InFlightBuildRun] = Field(
        default_factory=list,
        alias="inFlightBuildRuns",
        serialization_alias="inFlightBuildRuns",
        description="Non-terminal child build runs (derived on read; never stored).",
    )


class RolloutEventResponse(BaseModel):
    """A single rollout event row returned from the API."""

    id: str
    rollout_id: str
    seq: int
    ts: str
    kind: RolloutEventKind
    actor: RolloutEventActor
    decision_rule: Literal["", "agent-judgment"]
    payload: dict[str, Any]


class ResumeRolloutRequest(BaseModel):
    """Request body for POST /api/rollouts/{id}/resume."""

    answer: str


class ActivityEvent(BaseModel):
    """A single enriched rollout activity event returned from GET /activity."""

    id: str
    rollout_id: str
    seq: int
    ts: str
    actor: str
    event_type: str
    item_id: str | None
    item_title: str | None
    run_id: str | None
    decision_rule: Literal["", "agent-judgment"] | None
    payload: dict[str, Any]
