"""Unit tests for Agent Gtd auth utilities."""

import time

import jwt as pyjwt
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_gtd.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

# --- Password hashing ---


def test_hash_verify_roundtrip():
    h = hash_password("secret123")
    assert verify_password("secret123", h)


def test_verify_wrong_password():
    h = hash_password("correct")
    assert not verify_password("wrong", h)


def test_hash_bcrypt_format():
    h = hash_password("test")
    assert h.startswith("$2b$")


# --- JWT ---


def test_create_decode_token_roundtrip():
    token = create_token("user-42")
    assert decode_token(token) == "user-42"


def test_decode_expired_token():
    payload = {"sub": "user-1", "exp": time.time() - 10, "iat": time.time() - 100}
    token = pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(Exception) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401  # type: ignore[union-attr]


def test_decode_invalid_token():
    with pytest.raises(Exception) as exc_info:
        decode_token("garbage.token.here")
    assert exc_info.value.status_code == 401  # type: ignore[union-attr]


# --- Property-based ---


@given(
    password=st.text(min_size=1, max_size=72).filter(lambda s: len(s.encode()) <= 72)
)
@settings(max_examples=10, deadline=None)
def test_hash_verify_any_password(password):
    h = hash_password(password)
    assert verify_password(password, h)


@given(user_id=st.text(min_size=1, max_size=100))
@settings(max_examples=10)
def test_token_roundtrip_any_user_id(user_id):
    token = create_token(user_id)
    assert decode_token(token) == user_id
