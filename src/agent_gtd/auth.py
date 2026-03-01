"""Authentication utilities: password hashing, JWT, and FastAPI dependency."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt as _bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_gtd.database import get_db, row_to_dict
from agent_gtd.models import User

SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 72

_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return _bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    """Create a JWT token for the given user ID."""
    payload = {
        "sub": user_id,
        "exp": datetime.now(UTC) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    """Decode a JWT and return the user ID.

    Raises:
        HTTPException: If the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from None


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> User:
    """FastAPI dependency that extracts and validates the current user."""
    return await get_current_user_from_token(credentials.credentials)


async def get_current_user_from_token(token: str) -> User:
    """Validate a JWT token string and return the user.

    Reusable helper for contexts where Bearer auth is unavailable
    (e.g. EventSource query params).

    Raises:
        HTTPException: If the token is invalid or user not found.
    """
    user_id = decode_token(token)
    db = await get_db()
    row = await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return User(**row_to_dict(row))


async def register_user(email: str, password: str) -> User:
    """Create a new user account.

    Raises:
        HTTPException: If the email is already registered.
    """
    db = await get_db()

    row = await db.fetchrow("SELECT id FROM users WHERE email = $1", email)
    if row:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password(password),
        created_at=datetime.now(UTC),
    )

    sql = (
        "INSERT INTO users (id, email, hashed_password, created_at)"
        " VALUES ($1, $2, $3, $4)"
    )
    await db.execute(
        sql,
        user.id,
        user.email,
        user.hashed_password,
        user.created_at.isoformat(),
    )

    return user


async def authenticate_user(email: str, password: str) -> User:
    """Validate credentials and return the user.

    Raises:
        HTTPException: If credentials are invalid.
    """
    db = await get_db()
    row = await db.fetchrow("SELECT * FROM users WHERE email = $1", email)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    user = User(**row_to_dict(row))
    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return user
