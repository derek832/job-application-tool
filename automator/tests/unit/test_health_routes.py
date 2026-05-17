"""Unit tests for session health API endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.health_routes import router
from src.db.database import get_session
from src.db.models import Base
from src.pipeline.health_checker import HealthCheckResult

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI app with health routes and overridden dependencies."""
    from src.api.system_routes import verify_token

    test_app = FastAPI()
    test_app.include_router(router)

    # Override auth to be a no-op for testing
    async def _no_auth() -> None:
        pass

    # Override get_session to return our test session
    async def _get_test_session():
        yield db_session

    test_app.dependency_overrides[verify_token] = _no_auth
    test_app.dependency_overrides[get_session] = _get_test_session

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /health/session tests
# ---------------------------------------------------------------------------


class TestSessionHealth:
    """Tests for GET /health/session."""

    @pytest.mark.asyncio
    @patch("src.api.health_routes.check_session_health")
    async def test_returns_healthy_result(
        self, mock_check: AsyncMock, client: AsyncClient
    ) -> None:
        """GET /health/session returns structured healthy result."""
        mock_check.return_value = HealthCheckResult(
            chrome_reachable=True,
            linkedin_authenticated=True,
            error_message=None,
            checked_at="2024-03-15T09:00:00+00:00",
        )

        resp = await client.get("/health/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_reachable"] is True
        assert data["linkedin_authenticated"] is True
        assert data["error_message"] is None
        assert data["checked_at"] == "2024-03-15T09:00:00+00:00"

    @pytest.mark.asyncio
    @patch("src.api.health_routes.check_session_health")
    async def test_returns_chrome_unreachable(
        self, mock_check: AsyncMock, client: AsyncClient
    ) -> None:
        """GET /health/session returns chrome_reachable=False when CDP is down."""
        mock_check.return_value = HealthCheckResult(
            chrome_reachable=False,
            linkedin_authenticated=False,
            error_message="Chrome CDP is not reachable",
            checked_at="2024-03-15T09:00:00+00:00",
        )

        resp = await client.get("/health/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_reachable"] is False
        assert data["linkedin_authenticated"] is False
        assert data["error_message"] == "Chrome CDP is not reachable"

    @pytest.mark.asyncio
    @patch("src.api.health_routes.check_session_health")
    async def test_returns_linkedin_session_expired(
        self, mock_check: AsyncMock, client: AsyncClient
    ) -> None:
        """GET /health/session returns linkedin_authenticated=False when session expired."""
        mock_check.return_value = HealthCheckResult(
            chrome_reachable=True,
            linkedin_authenticated=False,
            error_message="LinkedIn session expired — please log in to Chrome",
            checked_at="2024-03-15T09:00:00+00:00",
        )

        resp = await client.get("/health/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_reachable"] is True
        assert data["linkedin_authenticated"] is False
        assert "LinkedIn session expired" in data["error_message"]

    @pytest.mark.asyncio
    @patch("src.api.health_routes.check_session_health")
    async def test_returns_timeout_error(
        self, mock_check: AsyncMock, client: AsyncClient
    ) -> None:
        """GET /health/session returns timeout error when check exceeds 15s."""
        mock_check.return_value = HealthCheckResult(
            chrome_reachable=False,
            linkedin_authenticated=False,
            error_message="Health check timed out after 15 seconds",
            checked_at="2024-03-15T09:00:00+00:00",
        )

        resp = await client.get("/health/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_reachable"] is False
        assert data["linkedin_authenticated"] is False
        assert "timed out" in data["error_message"]

    @pytest.mark.asyncio
    @patch("src.api.health_routes.check_session_health")
    async def test_uses_cdp_url_from_env(
        self, mock_check: AsyncMock, client: AsyncClient
    ) -> None:
        """GET /health/session passes the configured CDP URL to check_session_health."""
        mock_check.return_value = HealthCheckResult(
            chrome_reachable=True,
            linkedin_authenticated=True,
            error_message=None,
            checked_at="2024-03-15T09:00:00+00:00",
        )

        await client.get("/health/session")
        mock_check.assert_called_once()
        # The CDP URL should be a string (either from env or default)
        cdp_url_arg = mock_check.call_args[0][0]
        assert isinstance(cdp_url_arg, str)
        assert "9222" in cdp_url_arg


class TestSessionHealthAuth:
    """Tests verifying auth is enforced on health/session endpoint."""

    @pytest.mark.asyncio
    async def test_missing_auth_returns_error(self, db_session: AsyncSession) -> None:
        """Requests without auth header are rejected."""
        # Create app WITHOUT overriding auth
        test_app = FastAPI()
        test_app.include_router(router)

        async def _get_test_session():
            yield db_session

        test_app.dependency_overrides[get_session] = _get_test_session

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health/session")
            # verify_token uses Header(...) which returns 422 when missing
            assert resp.status_code in (401, 403, 422)
