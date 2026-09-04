"""
Shared pytest fixtures.

Critically, this sets DATABASE_URL / JWT_SECRET_KEY *before* anything under
`app` gets imported by a test module. app/db.py raises RuntimeError at
import time if DATABASE_URL is missing, and app/auth.py reads
JWT_SECRET_KEY at import time too — so these must land before the first
`import app...` anywhere in the test session, not inside a fixture that
runs after collection.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-prod")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
