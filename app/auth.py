# app/auth.py
"""
MOCK authentication — local development only.

This returns a single hardcoded UUID and performs NO verification of any
kind: anyone who can reach this API is treated as this one user. This is
acceptable ONLY while wiring the backend loop together. Before this touches
real user data or a public URL, replace get_current_user_id with real
verification (e.g. validating a Supabase JWT from the Authorization header).
"""
from __future__ import annotations

import os
import uuid

_MOCK_USER_ID = uuid.UUID(os.getenv("MOCK_USER_ID", "00000000-0000-0000-0000-000000000001"))


async def get_current_user_id() -> uuid.UUID:
    return _MOCK_USER_ID