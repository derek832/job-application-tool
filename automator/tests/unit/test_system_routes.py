"""
Unit tests for the system control API routes.

Tests cover authentication, status retrieval, run/pause/resume controls,
and health check endpoint behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.schemas import HealthResponse
from src.api.system_routes import _compute_next_run_at

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a minimal FastAPI app with system routes for testing."""
    from fastapi import FastAPI

    from src.api.system_routes import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database session for testing."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def seeded_session(db_session):
    """Session with api_token and system_state pre-configured."""
    import json

    from src.db.models import Config

    # Set api_token
    db_session.add(
        Config(
            key="api_token",
            value=json.dumps("test-secret-token"),
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    # Set system_state
    db_session.add(
        Config(
            key="system_state",
            value=json.dumps(
                {"status": "idle", "last_run_at": "2024-01-15T09:00:00Z", "last_error": None}
            ),
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    # Set settings
    db_session.add(
        Config(
            key="settings",
            value=json.dumps(
                {
                    "scheduled_time": "09:00",
                    "claude_api_key": "sk-test",
                    "gmail_user": "test@gmail.com",
                    "gmail_app_password": "pass",
                    "gdocs_script_url": "https://script.google.com/test",
                }
            ),
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    await db_session.commit()
    return db_session


@pytest.fixture
async def client(app, seeded_session):
    """Async HTTP test client with DB session override."""
    from src.db.database import get_session

    async def override_get_session():
        yield seeded_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    """Tests for the verify_token dependency."""

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_returns_401(self, client):
        """Request without 'Bearer ' prefix should be rejected."""
        response = await client.get("/status", headers={"Authorization": "Token abc123"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client):
        """Request with wrong token should be rejected."""
        response = await client.get("/status", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_422(self, client):
        """Request without Authorization header should return 422 (validation error)."""
        response = await client.get("/status")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_token_passes(self, client):
        """Request with correct token should succeed."""
        with patch(
            "src.api.system_routes._perform_health_checks", new_callable=AsyncMock
        ) as mock_health:
            mock_health.return_value = HealthResponse(
                claude_api=False, gmail=False, google_docs=False
            )
            response = await client.get(
                "/status", headers={"Authorization": "Bearer test-secret-token"}
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /status tests
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for the GET /status endpoint."""

    @pytest.mark.asyncio
    async def test_returns_status_response(self, client):
        """Should return a valid StatusResponse with system state."""
        with patch(
            "src.api.system_routes._perform_health_checks", new_callable=AsyncMock
        ) as mock_health:
            mock_health.return_value = HealthResponse(claude_api=True, gmail=True, google_docs=True)
            response = await client.get(
                "/status", headers={"Authorization": "Bearer test-secret-token"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"
        assert data["last_run_at"] == "2024-01-15T09:00:00Z"
        assert data["queue_count"] == 0
        assert "stats" in data
        assert "health" in data

    @pytest.mark.asyncio
    async def test_status_includes_stats(self, client):
        """Should include pipeline statistics in the response."""
        with patch(
            "src.api.system_routes._perform_health_checks", new_callable=AsyncMock
        ) as mock_health:
            mock_health.return_value = HealthResponse()
            response = await client.get(
                "/status", headers={"Authorization": "Bearer test-secret-token"}
            )

        data = response.json()
        stats = data["stats"]
        assert "total_discovered" in stats
        assert "total_applied" in stats
        assert "total_skipped" in stats
        assert "total_pending_review" in stats
        assert "application_success_rate" in stats


# ---------------------------------------------------------------------------
# POST /run tests
# ---------------------------------------------------------------------------


class TestPostRun:
    """Tests for the POST /run endpoint."""

    @pytest.mark.asyncio
    async def test_run_sets_status_to_running(self, client):
        """Triggering a run should set system state to 'running'."""
        with patch("src.api.system_routes.scheduler_trigger_now"):
            response = await client.post("/run", headers={"Authorization": "Bearer test-secret-token"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_run_requires_auth(self, client):
        """POST /run without valid auth should be rejected."""
        response = await client.post("/run", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /pause tests
# ---------------------------------------------------------------------------


class TestPostPause:
    """Tests for the POST /pause endpoint."""

    @pytest.mark.asyncio
    async def test_pause_sets_status_to_paused(self, client):
        """Pausing should set system state to 'paused'."""
        response = await client.post(
            "/pause", headers={"Authorization": "Bearer test-secret-token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "paused"
        assert data["next_run_at"] is None

    @pytest.mark.asyncio
    async def test_pause_requires_auth(self, client):
        """POST /pause without valid auth should be rejected."""
        response = await client.post("/pause", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /resume tests
# ---------------------------------------------------------------------------


class TestPostResume:
    """Tests for the POST /resume endpoint."""

    @pytest.mark.asyncio
    async def test_resume_sets_status_to_idle(self, client):
        """Resuming should set system state to 'idle'."""
        # First pause
        await client.post("/pause", headers={"Authorization": "Bearer test-secret-token"})
        # Then resume
        response = await client.post(
            "/resume", headers={"Authorization": "Bearer test-secret-token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"

    @pytest.mark.asyncio
    async def test_resume_includes_next_run_at(self, client):
        """After resume, next_run_at should be computed from scheduled_time."""
        response = await client.post(
            "/resume", headers={"Authorization": "Bearer test-secret-token"}
        )

        data = response.json()
        # scheduled_time is "09:00" so next_run_at should be set
        assert data["next_run_at"] is not None

    @pytest.mark.asyncio
    async def test_resume_requires_auth(self, client):
        """POST /resume without valid auth should be rejected."""
        response = await client.post("/resume", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /health tests
# ---------------------------------------------------------------------------


class TestGetHealth:
    """Tests for the GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_health_response(self, client):
        """Should return a HealthResponse with boolean fields."""
        with (
            patch("src.api.system_routes._check_claude_api", new_callable=AsyncMock) as mock_claude,
            patch("src.api.system_routes._check_gmail_oauth", new_callable=AsyncMock) as mock_gmail,
            patch("src.api.system_routes._check_gdocs", new_callable=AsyncMock) as mock_gdocs,
        ):
            mock_claude.return_value = True
            mock_gmail.return_value = True
            mock_gdocs.return_value = False

            response = await client.get(
                "/health", headers={"Authorization": "Bearer test-secret-token"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["claude_api"] is True
        assert data["gmail"] is True
        assert data["google_docs"] is False

    @pytest.mark.asyncio
    async def test_health_requires_auth(self, client):
        """GET /health without valid auth should be rejected."""
        response = await client.get("/health", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestComputeNextRunAt:
    """Tests for the _compute_next_run_at helper."""

    def test_valid_time_returns_iso_string(self):
        """A valid HH:MM time should produce an ISO 8601 timestamp."""
        result = _compute_next_run_at("09:00")
        assert result is not None
        assert "T09:00:00" in result

    def test_invalid_time_returns_none(self):
        """An invalid time string should return None."""
        assert _compute_next_run_at("invalid") is None
        assert _compute_next_run_at("") is None
        assert _compute_next_run_at("25:00") is None

    def test_none_input_returns_none(self):
        """None input should return None."""
        assert _compute_next_run_at(None) is None
