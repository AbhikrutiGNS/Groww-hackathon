# app/auth.py
"""
Real authentication: bcrypt password hashing + JWT issuance/verification.

Replaces the earlier MOCK auth stub (which returned one hardcoded user id
for every request, no verification at all). Every protected route depends
on get_current_user_id, which now validates a real Bearer JWT.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

# --- Config -----------------------------------------------------------------
# In production this MUST come from a real secret (env var / secrets
# manager). The fallback below only exists so local dev doesn't hard-crash
# if .env is missing; it is NOT safe to deploy with the fallback in use.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # default: 7 days

_bearer_scheme = HTTPBearer(auto_error=False)


# --- Passwords ----------------------------------------------------------
# bcrypt truncates at 72 bytes silently, which can degrade to comparing
# only a prefix of long passwords. We reject overlong passwords instead
# (the signup schema already caps password length at 128 chars, but this
# guards hash_password/verify_password themselves regardless of caller).
_MAX_PASSWORD_BYTES = 72


def hash_password(plain_password: str) -> str:
    pw_bytes = plain_password.encode("utf-8")
    if len(pw_bytes) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} bytes.")
    hashed = bcrypt.hashpw(pw_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pw_bytes = plain_password.encode("utf-8")
    if len(pw_bytes) > _MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))


# --- JWTs -----------------------------------------------------------------
def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> uuid.UUID:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise JWTError("Missing sub claim")
        return uuid.UUID(sub)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )