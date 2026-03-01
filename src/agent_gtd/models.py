"""Pydantic v2 domain models for Agent GTD."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

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
    NEXT_ACTION = "next_action"
    WAITING_FOR = "waiting_for"
    SCHEDULED = "scheduled"
    SOMEDAY_MAYBE = "someday_maybe"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(StrEnum):
    """Item priority level."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# --- Domain Models ---


class User(BaseModel):
    """App user account."""

    id: str
    email: str
    hashed_password: str
    created_at: datetime


class Project(BaseModel):
    """A GTD project."""

    id: str
    user_id: str
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    area: str = ""
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


# --- API Request/Response Schemas ---


class RegisterRequest(BaseModel):
    """Account registration request."""

    email: str
    password: str


class LoginRequest(BaseModel):
    """Login request."""

    email: str
    password: str


class AuthResponse(BaseModel):
    """Auth response with JWT token."""

    token: str
    user: "UserResponse"


class UserResponse(BaseModel):
    """Public user info (no password hash)."""

    id: str
    email: str
    created_at: datetime


# --- Project Schemas ---


class CreateProjectRequest(BaseModel):
    """Create a new project."""

    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    area: str = ""


class UpdateProjectRequest(BaseModel):
    """Update a project. All fields optional."""

    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    area: str | None = None


class ProjectResponse(BaseModel):
    """Project data returned from API."""

    id: str
    name: str
    description: str
    status: ProjectStatus
    area: str
    created_at: datetime
    updated_at: datetime


# --- Item Schemas ---


class CreateItemRequest(BaseModel):
    """Create a new item."""

    title: str
    description: str = ""
    project_id: str | None = None
    status: ItemStatus = ItemStatus.INBOX
    priority: Priority = Priority.NORMAL
    due_date: str | None = None
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
    created_at: datetime
    updated_at: datetime


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
