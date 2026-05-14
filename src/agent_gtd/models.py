"""Pydantic v2 domain models for Agent GTD."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator

# --- Enums ---


class ProjectStatus(StrEnum):
    """Project lifecycle status."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"


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


class RunStatus(StrEnum):
    """Claude dispatch run status."""

    PENDING = "pending"
    CLONING = "cloning"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class WaveRunStatus(StrEnum):
    """Autonomous wave run lifecycle status."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"


class WavePlanItemStatus(StrEnum):
    """Status of a single item within a wave plan."""

    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    HALTED = "halted"
    SKIPPED = "skipped"


class WaveEventActor(StrEnum):
    """Actor that generated a wave event."""

    MANAGER = "manager"
    CHILD_AGENT = "child-agent"
    HUMAN = "human"


class MergeActor(StrEnum):
    """Who merged (or will merge) the PR for a wave plan item."""

    HUMAN = "human"
    MANAGER_ALLOWLIST = "manager-allowlist"
    MANAGER_HUMAN_FIXUP = "manager+human-fixup"


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
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None
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
    locked_by_wave_id: str | None = None
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


class WaveRun(BaseModel):
    """An autonomous wave run coordinating multiple agent dispatches."""

    id: str
    project_id: str
    lead_user_id: str
    status: WaveRunStatus
    halt_reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WavePlan(BaseModel):
    """A DAG plan produced by the wave planner for a wave run."""

    id: str
    wave_run_id: str
    version: int
    nodes: list[str]
    edges: list[dict[str, str]]
    planner_model: str
    created_at: datetime


class WavePlanItem(BaseModel):
    """Tracking record for a single item within a wave plan."""

    wave_run_id: str
    item_id: str
    status: WavePlanItemStatus
    claude_run_id: str | None = None
    completed_at: datetime | None = None
    merge_actor: MergeActor | None = None


class WaveEvent(BaseModel):
    """A structured event emitted during a wave run."""

    id: str
    wave_run_id: str
    seq: int
    ts: datetime
    kind: str
    actor: WaveEventActor
    decision_rule: str
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


class UpdateProjectRequest(BaseModel):
    """Update a project. All fields optional.

    For dispatch_max_turns, dispatch_timeout_minutes, plan_dispatch_agent,
    and build_dispatch_agent:
    - Field absent → unchanged
    - Field explicitly null → clear the override (revert to inheriting global)
    - Field set → persist the value
    """

    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    area: str | None = None
    git_origin: str | None = None
    kb_project_ref: str | None = None
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None


class ProjectResponse(BaseModel):
    """Project data returned from API."""

    id: str
    name: str
    description: str
    status: ProjectStatus
    area: str
    git_origin: str
    kb_project_ref: str
    dispatch_max_turns: int | None = None
    dispatch_timeout_minutes: int | None = None
    plan_dispatch_agent: str | None = None
    build_dispatch_agent: str | None = None
    created_at: datetime
    updated_at: datetime
    is_owner: bool | None = None
    owner_email: str | None = None
    member_count: int | None = None
    total_items: int = 0
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
    created_by: str = "human"
    assigned_to: str = ""
    waiting_on: str = ""
    sort_order: float = 0
    labels: list[str] = []


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
    version: int | None = None


class InboxCaptureRequest(BaseModel):
    """Quick capture to inbox — title only."""

    title: str
    created_by: str = "human"


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
    locked_by_wave_id: str | None = None
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
    created_by: str = "human"


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
    mode: str = "build"
    wave_run_id: str | None = None


class MaxConcurrentRequest(BaseModel):
    """Request body for updating the dispatch concurrency cap."""

    value: int


class DispatchSettingsResponse(BaseModel):
    """Full dispatch settings returned from GET /api/settings/dispatch."""

    engine: str
    plan_agent_name: str = ""
    build_agent_name: str = ""
    max_concurrent: int
    default_max_turns: int = 100
    default_timeout_minutes: int = 30
    service_url: str
    service_api_key_preview: str = ""


class UpdateDispatchSettingsRequest(BaseModel):
    """Body for PATCH /api/settings/dispatch — per-user dispatch config.

    Only provided fields are updated; omit a field to leave it unchanged.
    """

    engine: str | None = None
    plan_agent_name: str | None = None
    build_agent_name: str | None = None
    service_url: str | None = None
    service_api_key: str | None = None
    default_max_turns: int | None = None
    default_timeout_minutes: int | None = None


class RunResponse(BaseModel):
    """Claude dispatch run data returned from API."""

    id: str
    item_id: str
    project_id: str
    status: RunStatus
    feature_branch: str
    workspace_dir: str
    max_turns: int
    mode: str
    started_at: datetime | None
    finished_at: datetime | None
    error_msg: str
    wave_run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    dispatched_by_email: str | None = None


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

    engine: str | None = None
    version: str | None = None
    agents: list[DispatchAgentInfo] = []


# --- Wave Manager Schemas ---


class PlanWaveItemSummary(BaseModel):
    """Per-item summary within a wave plan result."""

    item_id: str
    title: str
    predecessors: list[str] = []


class PlanWavePlan(BaseModel):
    """The DAG plan nested inside a PlanWaveResult."""

    nodes: list[str]
    edges: list[dict[str, str]]


class PlanWaveResult(BaseModel):
    """Response returned by the plan_wave MCP tool on success."""

    wave_run_id: str
    status: WaveRunStatus
    plan: PlanWavePlan
    planner_model: str
    item_count: int
    per_item: list[PlanWaveItemSummary]


class WaveRunResponse(BaseModel):
    """Wave run data returned from the API, augmented with progress counts."""

    id: str
    project_id: str
    lead_user_id: str
    status: WaveRunStatus
    halt_reason: str | None
    started_at: str | None
    ended_at: str | None
    created_at: str
    updated_at: str
    total_count: int
    done_count: int


class WaveEventResponse(BaseModel):
    """A single wave event row returned from the API."""

    id: str
    wave_run_id: str
    seq: int
    ts: str
    kind: str
    actor: WaveEventActor
    decision_rule: str
    payload: dict[str, Any]


class ResumeWaveRequest(BaseModel):
    """Request body for POST /api/wave-runs/{id}/resume."""

    answer: str


class ActivityEvent(BaseModel):
    """A single enriched wave activity event returned from GET /activity."""

    id: str
    wave_run_id: str
    seq: int
    ts: str
    actor: str
    event_type: str
    item_id: str | None
    item_title: str | None
    run_id: str | None
    decision_rule: str | None
    payload: dict[str, Any]
