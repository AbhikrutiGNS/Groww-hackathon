"""
Integration tests that exercise the real FastAPI app object: middleware,
routing, and the auth dependency wired end-to-end through actual HTTP
requests via TestClient. No real Postgres is available in CI, so the
background ingestion loops (which need a live DB) are patched out before
the app's lifespan starts — everything else (CORS, routing, auth
short-circuiting before any DB access) runs for real.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app import auth


def _client(monkeypatch) -> TestClient:
    # Prevent the lifespan's background loops from repeatedly trying (and
    # failing/retrying) to hit a database that doesn't exist in this
    # environment. Each loop is patched to a no-op coroutine.
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.main.fetch_and_store_snapshots", _noop)
    monkeypatch.setattr("app.main.fetch_and_store_fundamentals", _noop)

    from app.main import app

    return TestClient(app)


def test_health_endpoint_returns_ok(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_cors_allows_configured_frontend_origin(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_protected_watchlist_route_requires_auth(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/watchlist")
        assert response.status_code == 401


def test_protected_route_rejects_malformed_bearer_token(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get(
            "/watchlist", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401


def test_demo_endpoints_hidden_and_disabled_when_demo_mode_is_off(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    with _client(monkeypatch) as client:
        # A valid token still gets a 404 (not 401) — the route is gated by
        # DEMO_MODE, not by auth, once auth passes.
        token = auth.create_access_token(uuid.uuid4())
        response = client.post(
            "/watchlist/demo/simulate-move",
            headers={"Authorization": f"Bearer {token}"},
            json={"symbol": "AAPL"},
        )
        assert response.status_code == 404
