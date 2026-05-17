"""Unit tests for LAN server creation.

Validates: Requirements 4.2, 4.3
- Only queue + health routes are mounted on the LAN app
- All LAN endpoints require bearer token authentication
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.lan_server import create_lan_app
from src.db.database import get_session
from src.db.models import Base, Config


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database with a valid api_token."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        # Seed a valid API token for auth tests
        token_config = Config(
            key="api_token",
            value=json.dumps("test-secret-token"),
            updated_at="2024-01-01T00:00:00+00:00",
        )
        session.add(token_config)
        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
def lan_app(db_session: AsyncSession) -> FastAPI:
    """Create the LAN app with a real verify_token dependency and test DB session."""
    main_app = FastAPI(title="Main App (unused)")
    app = create_lan_app(main_app)

    async def _get_test_session():
        yield db_session

    app.dependency_overrides[get_session] = _get_test_session
    return app


@pytest.fixture
async def client(lan_app: FastAPI) -> AsyncClient:
    """Create an async test client for the LAN app."""
    transport = ASGITransport(app=lan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Route mounting tests — Verify only queue + health routes are mounted
# ---------------------------------------------------------------------------


class TestLanAppRoutes:
    """Verify only queue + health routes are mounted on the LAN app."""

    def test_lan_app_has_queue_routes(self, lan_app: FastAPI) -> None:
        """The LAN app should include all queue router endpoints."""
        routes = {route.path for route in lan_app.routes if hasattr(route, "path")}

        assert "/queue" in routes
        assert "/queue/{job_id}/approve" in routes
        assert "/queue/{job_id}/reject" in routes
        assert "/queue/{job_id}/manual" in routes

    def test_lan_app_has_health_route(self, lan_app: FastAPI) -> None:
        """The LAN app should include the /health endpoint."""
        routes = {route.path for route in lan_app.routes if hasattr(route, "path")}
        assert "/health" in routes

    def test_lan_app_does_not_have_system_routes(self, lan_app: FastAPI) -> None:
        """The LAN app should NOT expose system control endpoints."""
        routes = {route.path for route in lan_app.routes if hasattr(route, "path")}

        assert "/status" not in routes
        assert "/run" not in routes
        assert "/pause" not in routes
        assert "/resume" not in routes

    def test_lan_app_does_not_have_config_routes(self, lan_app: FastAPI) -> None:
        """The LAN app should NOT expose configuration endpoints."""
        routes = {route.path for route in lan_app.routes if hasattr(route, "path")}

        assert "/config" not in routes
        assert "/config/ntfy" not in routes
        assert "/config/settings" not in routes

    def test_lan_app_does_not_have_job_routes(self, lan_app: FastAPI) -> None:
        """The LAN app should NOT expose job listing/detail endpoints."""
        routes = {route.path for route in lan_app.routes if hasattr(route, "path")}

        assert "/jobs" not in routes
        assert "/jobs/{job_id}" not in routes

    def test_lan_app_only_has_expected_routes(self, lan_app: FastAPI) -> None:
        """The LAN app should have exactly the expected set of routes (queue + health)."""
        expected_paths = {
            "/queue",
            "/queue/{job_id}/approve",
            "/queue/{job_id}/reject",
            "/queue/{job_id}/manual",
            "/health",
        }

        # Filter out FastAPI's built-in documentation routes
        fastapi_builtin = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}

        actual_paths = {
            route.path
            for route in lan_app.routes
            if hasattr(route, "path") and route.path not in fastapi_builtin
        }

        assert actual_paths == expected_paths


# ---------------------------------------------------------------------------
# Auth tests — Verify auth is required on all LAN endpoints
# ---------------------------------------------------------------------------


class TestLanAppAuth:
    """Verify bearer token auth is required on all LAN endpoints."""

    @pytest.mark.asyncio
    async def test_health_rejects_missing_auth(self, client: AsyncClient) -> None:
        """GET /health returns 401 when no Authorization header is provided."""
        resp = await client.get("/health")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_health_rejects_invalid_token(self, client: AsyncClient) -> None:
        """GET /health returns 401 with an invalid bearer token."""
        resp = await client.get(
            "/health", headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_health_accepts_valid_token(self, client: AsyncClient) -> None:
        """GET /health returns 200 with a valid bearer token."""
        resp = await client.get(
            "/health", headers={"Authorization": "Bearer test-secret-token"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_queue_list_rejects_missing_auth(self, client: AsyncClient) -> None:
        """GET /queue returns 401/422 when no Authorization header is provided."""
        resp = await client.get("/queue")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_queue_list_rejects_invalid_token(self, client: AsyncClient) -> None:
        """GET /queue returns 401 with an invalid bearer token."""
        resp = await client.get(
            "/queue", headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_queue_approve_rejects_missing_auth(self, client: AsyncClient) -> None:
        """POST /queue/{id}/approve returns 401/422 without auth."""
        resp = await client.post("/queue/12345/approve")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_queue_approve_rejects_invalid_token(self, client: AsyncClient) -> None:
        """POST /queue/{id}/approve returns 401 with invalid token."""
        resp = await client.post(
            "/queue/12345/approve",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_queue_reject_rejects_missing_auth(self, client: AsyncClient) -> None:
        """POST /queue/{id}/reject returns 401/422 without auth."""
        resp = await client.post("/queue/12345/reject")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_queue_reject_rejects_invalid_token(self, client: AsyncClient) -> None:
        """POST /queue/{id}/reject returns 401 with invalid token."""
        resp = await client.post(
            "/queue/12345/reject",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_queue_manual_rejects_missing_auth(self, client: AsyncClient) -> None:
        """POST /queue/{id}/manual returns 401/422 without auth."""
        resp = await client.post("/queue/12345/manual")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_queue_manual_rejects_invalid_token(self, client: AsyncClient) -> None:
        """POST /queue/{id}/manual returns 401 with invalid token."""
        resp = await client.post(
            "/queue/12345/manual",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_health_rejects_malformed_auth_header(
        self, client: AsyncClient
    ) -> None:
        """GET /health returns 401 when Authorization header is not 'Bearer <token>'."""
        resp = await client.get(
            "/health", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        assert resp.status_code == 401
