"""
Unit tests for app/auth.py: bcrypt password hashing and JWT lifecycle.

No database or HTTP involved — these exercise the crypto/token functions
directly, including their edge cases (overlong passwords, expired/invalid
tokens).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from app import auth


class TestPasswordHashing:
    def test_hash_then_verify_round_trips(self):
        hashed = auth.hash_password("correct horse battery staple")
        assert auth.verify_password("correct horse battery staple", hashed)

    def test_verify_rejects_wrong_password(self):
        hashed = auth.hash_password("correct horse battery staple")
        assert not auth.verify_password("wrong password", hashed)

    def test_hash_rejects_passwords_over_72_bytes(self):
        too_long = "a" * 73
        with pytest.raises(ValueError):
            auth.hash_password(too_long)

    def test_hash_accepts_password_at_the_72_byte_boundary(self):
        exactly_72 = "a" * 72
        hashed = auth.hash_password(exactly_72)
        assert auth.verify_password(exactly_72, hashed)

    def test_verify_returns_false_for_overlong_password_rather_than_raising(self):
        hashed = auth.hash_password("a" * 72)
        assert auth.verify_password("a" * 73, hashed) is False

    def test_two_hashes_of_the_same_password_differ(self):
        # bcrypt salts each hash independently.
        h1 = auth.hash_password("same-password")
        h2 = auth.hash_password("same-password")
        assert h1 != h2


class TestAccessTokens:
    def test_create_access_token_embeds_user_id_as_sub(self):
        user_id = uuid.uuid4()
        token = auth.create_access_token(user_id)
        payload = jwt.decode(token, auth.JWT_SECRET_KEY, algorithms=[auth.JWT_ALGORITHM])
        assert payload["sub"] == str(user_id)

    async def test_get_current_user_id_accepts_a_valid_token(self):
        user_id = uuid.uuid4()
        token = auth.create_access_token(user_id)
        creds = type("Creds", (), {"credentials": token})()
        resolved = await auth.get_current_user_id(credentials=creds)
        assert resolved == user_id

    async def test_get_current_user_id_rejects_missing_credentials(self):
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_current_user_id(credentials=None)
        assert exc_info.value.status_code == 401

    async def test_get_current_user_id_rejects_garbage_token(self):
        creds = type("Creds", (), {"credentials": "not-a-real-jwt"})()
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_current_user_id(credentials=creds)
        assert exc_info.value.status_code == 401

    async def test_get_current_user_id_rejects_expired_token(self):
        now = datetime.now(timezone.utc)
        expired_payload = {
            "sub": str(uuid.uuid4()),
            "iat": now - timedelta(days=8),
            "exp": now - timedelta(days=1),
        }
        expired_token = jwt.encode(
            expired_payload, auth.JWT_SECRET_KEY, algorithm=auth.JWT_ALGORITHM
        )
        creds = type("Creds", (), {"credentials": expired_token})()
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_current_user_id(credentials=creds)
        assert exc_info.value.status_code == 401

    async def test_get_current_user_id_rejects_token_missing_sub(self):
        now = datetime.now(timezone.utc)
        payload = {"iat": now, "exp": now + timedelta(minutes=5)}
        token = jwt.encode(payload, auth.JWT_SECRET_KEY, algorithm=auth.JWT_ALGORITHM)
        creds = type("Creds", (), {"credentials": token})()
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_current_user_id(credentials=creds)
        assert exc_info.value.status_code == 401
