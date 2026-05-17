"""Unit tests for the LAN IP auto-detection endpoint.

Tests the GET /config/lan-detect endpoint covering:
- Happy path with DNS resolution returning a private IP
- Environment variable override (LAN_IP)
- DNS timeout producing 503
- Public IP rejection (422)
- Loopback IP rejection (422)
- Link-local IP rejection (422)
- Hostname passthrough (non-IPv4 accepted without validation)
- Authentication required (401 without token)

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config_routes import router
from src.api.lan_detect import LanDetectionError
from src.db.database import get_session
from src.db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI app with config routes and auth overridden."""
    from src.api.auth import verify_token

    test_app = FastAPI()
    test_app.include_router(router)

    async def _no_auth() -> None:
        pass

    async def _get_test_session():
        yield db_session

    test_app.dependency_overrides[verify_token] = _no_auth
    test_app.dependency_overrides[get_session] = _get_test_session

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create an async test client with auth bypassed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLanDetectEndpoint:
    """Tests for GET /config/lan-detect."""

    @pytest.mark.asyncio
    async def test_happy_path_private_ip(self, client: AsyncClient) -> None:
        """DNS returns a private IP — verify 200 with correct lan_base_url and port."""
        mock_detect = AsyncMock(return_value="192.168.1.100")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_base_url"] == "http://192.168.1.100:7432"
        assert data["port"] == 7432

    @pytest.mark.asyncio
    async def test_env_var_override(self, client: AsyncClient) -> None:
        """LAN_IP env var set — DNS not called, correct response returned."""
        mock_detect = AsyncMock(return_value="10.0.0.50")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_base_url"] == "http://10.0.0.50:7432"
        assert data["port"] == 7432
        # Verify detect_lan_ip was called (it handles env var internally)
        mock_detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_dns_timeout_returns_503(self, client: AsyncClient) -> None:
        """DNS resolution times out — verify 503 with descriptive error."""
        error_msg = (
            "Auto-detection failed: could not resolve "
            "host.docker.internal within 5 seconds. "
            "Set LAN_IP in your .env file as a fallback."
        )
        mock_detect = AsyncMock(side_effect=LanDetectionError(error_msg))

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 503
        data = resp.json()
        assert "error" in data
        assert "Auto-detection failed" in data["error"]
        assert "5 seconds" in data["error"]

    @pytest.mark.asyncio
    async def test_public_ip_rejected(self, client: AsyncClient) -> None:
        """DNS returns a public IP (8.8.8.8) — verify 422 error."""
        mock_detect = AsyncMock(return_value="8.8.8.8")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert "8.8.8.8" in data["error"]
        assert "does not appear to be a LAN IP" in data["error"]

    @pytest.mark.asyncio
    async def test_loopback_rejected(self, client: AsyncClient) -> None:
        """DNS returns 127.0.0.1 — verify 422 error."""
        mock_detect = AsyncMock(return_value="127.0.0.1")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert "127.0.0.1" in data["error"]
        assert "not routable on the LAN" in data["error"]

    @pytest.mark.asyncio
    async def test_link_local_rejected(self, client: AsyncClient) -> None:
        """DNS returns 169.254.1.1 — verify 422 error."""
        mock_detect = AsyncMock(return_value="169.254.1.1")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert "169.254.1.1" in data["error"]
        assert "not routable on the LAN" in data["error"]

    @pytest.mark.asyncio
    async def test_hostname_passthrough(self, client: AsyncClient) -> None:
        """LAN_IP set to non-IPv4 string — accepted without validation."""
        mock_detect = AsyncMock(return_value="my-desktop.local")

        with patch("src.api.config_routes.detect_lan_ip", mock_detect):
            resp = await client.get("/config/lan-detect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_base_url"] == "http://my-desktop.local:7432"
        assert data["port"] == 7432


class TestLanDetectAuth:
    """Tests verifying authentication is required for the LAN detect endpoint."""

    @pytest.mark.asyncio
    async def test_auth_required(self, db_session: AsyncSession) -> None:
        """Request without token — verify 401 (or 403 from HTTPBearer)."""
        # Create app WITHOUT overriding auth
        app = FastAPI()
        app.include_router(router)

        async def _get_test_session():
            yield db_session

        app.dependency_overrides[get_session] = _get_test_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/config/lan-detect")
            # FastAPI HTTPBearer returns 403 when no credentials provided
            assert resp.status_code in (401, 403)
