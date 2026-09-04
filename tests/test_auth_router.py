"""
Integration tests for the /auth router, driven through the real FastAPI
app + HTTP layer, with `get_db` swapped for an in-memory fake session.

This covers the actual request/response contract (status codes, body
shape, password never echoed back) and the interaction between the router,
pydantic validation, app.auth's hashing/JWT functions, and the fake DB —
without requiring a live Postgres instance.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import get_db
from app.models import User


@dataclass
class _ScalarResult:
    _value: object

    def scalar_one_or_none(self):
        return self._value


@dataclass
class FakeSession:
    """Minimal stand-in for AsyncSession covering exactly what the
    /auth router does: one SELECT by email, an INSERT-via-add, and
    commit/rollback/refresh bookkeeping."""

    users_by_email: dict[str, User] = field(default_factory=dict)
    _pending: User | None = None
    commits: int = 0

    async def execute(self, stmt, *_args, **_kwargs):
        # Both signup's existence check and login's user lookup are
        # `select(...).where(User.email == email)` — inspect the bound
        # parameter to find the email being queried for.
        compiled = stmt.compile()
        email = list(compiled.params.values())[0]
        return _ScalarResult(self.users_by_email.get(email))

    def add(self, user: User):
        self._pending = user

    async def commit(self):
        if self._pending is not None:
            if self._pending.email in self.users_by_email:
                raise RuntimeError("unique constraint violation")
            if self._pending.id is None:
                self._pending.id = uuid.uuid4()
            self.users_by_email[self._pending.email] = self._pending
            self._pending = None
        self.commits += 1

    async def rollback(self):
        self._pending = None

    async def refresh(self, _user):
        return None


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def client(fake_session, monkeypatch):
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr("app.main.fetch_and_store_snapshots", _noop)
    monkeypatch.setattr("app.main.fetch_and_store_fundamentals", _noop)

    from app.main import app

    async def _override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


class TestSignup:
    def test_signup_creates_user_and_returns_bearer_token(self, client):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "hunter2pass"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert "access_token" in body
        assert "password" not in body

    def test_signup_rejects_duplicate_email(self, client, fake_session):
        existing = User(
            id=uuid.uuid4(), email="taken@example.com", hashed_password=auth.hash_password("x")
        )
        fake_session.users_by_email["taken@example.com"] = existing

        response = client.post(
            "/auth/signup", json={"email": "taken@example.com", "password": "hunter2pass"}
        )
        assert response.status_code == 409

    def test_signup_rejects_short_password(self, client):
        response = client.post(
            "/auth/signup", json={"email": "short@example.com", "password": "short"}
        )
        assert response.status_code == 422

    def test_signup_normalizes_email_case_and_whitespace(self, client, fake_session):
        response = client.post(
            "/auth/signup",
            json={"email": "  Mixed.Case@Example.com  ", "password": "hunter2pass"},
        )
        assert response.status_code == 201
        assert "mixed.case@example.com" in fake_session.users_by_email


class TestLogin:
    def test_login_succeeds_with_correct_credentials(self, client, fake_session):
        fake_session.users_by_email["user@example.com"] = User(
            id=uuid.uuid4(),
            email="user@example.com",
            hashed_password=auth.hash_password("correcthorse"),
        )
        response = client.post(
            "/auth/login", json={"email": "user@example.com", "password": "correcthorse"}
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_rejects_wrong_password(self, client, fake_session):
        fake_session.users_by_email["user@example.com"] = User(
            id=uuid.uuid4(),
            email="user@example.com",
            hashed_password=auth.hash_password("correcthorse"),
        )
        response = client.post(
            "/auth/login", json={"email": "user@example.com", "password": "wrongpassword"}
        )
        assert response.status_code == 401

    def test_login_rejects_unknown_email_with_same_error_as_wrong_password(self, client):
        response = client.post(
            "/auth/login", json={"email": "ghost@example.com", "password": "whatever"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password."
