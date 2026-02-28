"""Pydantic v2 domain models for Agent Gtd."""

from datetime import datetime

from pydantic import BaseModel

# --- Domain Models ---


class User(BaseModel):
    """App user account."""

    id: str
    email: str
    hashed_password: str
    created_at: datetime


class Note(BaseModel):
    """A user's note."""

    id: str
    user_id: str
    title: str = ""
    content: str = ""
    tags: list[str] = []
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


class CreateNoteRequest(BaseModel):
    """Create a new note."""

    title: str = ""
    content: str = ""
    tags: list[str] = []


class UpdateNoteRequest(BaseModel):
    """Update a note. All fields optional."""

    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None


class NoteResponse(BaseModel):
    """Note data returned from API."""

    id: str
    title: str
    content: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
