"""Auth API routes: register, login, logout, me."""

from typing import Annotated

from fastapi import APIRouter, Depends

from agent_gtd.auth import (
    authenticate_user,
    create_token,
    get_current_user,
    register_user,
)
from agent_gtd.models import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    User,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest) -> AuthResponse:
    """Create a new user account."""
    user = await register_user(body.email, body.password)
    token = create_token(user.id)
    return AuthResponse(token=token, user=_user_response(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest) -> AuthResponse:
    """Authenticate and receive a JWT token."""
    user = await authenticate_user(body.email, body.password)
    token = create_token(user.id)
    return AuthResponse(token=token, user=_user_response(user))


@router.post("/logout", status_code=204)
async def logout(
    _user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Logout (client discards token; placeholder for token blocklist)."""


@router.get("/me", response_model=UserResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Get current user profile."""
    return _user_response(user)
