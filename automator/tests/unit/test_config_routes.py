"""Unit tests for configuration API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config_routes import router
from src.db.database import get_session
from src.db.models import Base

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
    """Create a FastAPI app with config routes and overridden dependencies."""
    from src.api.auth import verify_token

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
# Search Config tests
# ---------------------------------------------------------------------------


class TestSearchConfig:
    """Tests for GET/PUT /config/search."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/search returns default empty config when not set."""
        resp = await client.get("/config/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keywords"] is None
        assert data["location"] is None
        assert data["job_type"] is None
        assert data["experience_level"] is None
        assert data["remote_pref"] is None

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/search persists data retrievable via GET."""
        payload = {
            "keywords": "python,fastapi",
            "location": "San Francisco",
            "job_type": "full-time",
            "experience_level": "mid-senior",
            "remote_pref": "remote",
        }
        put_resp = await client.put("/config/search", json=payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["keywords"] == "python,fastapi"

        get_resp = await client.get("/config/search")
        assert get_resp.status_code == 200
        assert get_resp.json() == payload

    @pytest.mark.asyncio
    async def test_put_partial_update(self, client: AsyncClient) -> None:
        """PUT /config/search with partial fields sets others to None."""
        payload = {"keywords": "react", "location": "NYC"}
        resp = await client.put("/config/search", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["keywords"] == "react"
        assert data["location"] == "NYC"
        assert data["job_type"] is None

    @pytest.mark.asyncio
    async def test_put_validates_body(self, client: AsyncClient) -> None:
        """PUT /config/search rejects invalid body types."""
        resp = await client.put("/config/search", json={"keywords": ["not", "a", "string"]})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Goals Profile tests
# ---------------------------------------------------------------------------


class TestGoalsProfile:
    """Tests for GET/PUT /config/goals."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/goals returns default empty profile when not set."""
        resp = await client.get("/config/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_titles"] == []
        assert data["deal_breakers"] == []
        assert data["open_to_stretch"] is True
        assert data["min_salary"] is None

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/goals persists data retrievable via GET."""
        payload = {
            "target_titles": ["Senior Engineer", "Staff Engineer"],
            "industries": ["Tech"],
            "company_sizes": ["startup"],
            "geo_prefs": ["Bay Area"],
            "min_salary": 150000,
            "deal_breakers": ["clearance required"],
            "open_to_stretch": False,
            "career_objective": "Lead a platform team.",
        }
        put_resp = await client.put("/config/goals", json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/config/goals")
        assert get_resp.status_code == 200
        assert get_resp.json() == payload

    @pytest.mark.asyncio
    async def test_put_with_empty_lists(self, client: AsyncClient) -> None:
        """PUT /config/goals accepts empty lists."""
        payload = {
            "target_titles": [],
            "industries": [],
            "company_sizes": [],
            "geo_prefs": [],
            "deal_breakers": [],
            "open_to_stretch": True,
        }
        resp = await client.put("/config/goals", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_titles"] == []


# ---------------------------------------------------------------------------
# User Profile tests
# ---------------------------------------------------------------------------


class TestUserProfile:
    """Tests for GET/PUT /config/profile."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/profile returns default empty profile when not set."""
        resp = await client.get("/config/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] is None
        assert data["email"] is None
        assert data["common_answers"] == {}

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/profile persists data retrievable via GET."""
        payload = {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-0100",
            "location": "San Francisco, CA",
            "work_auth": "US Citizen",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "common_answers": {"willing_to_relocate": "yes", "start_date": "immediately"},
        }
        put_resp = await client.put("/config/profile", json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/config/profile")
        assert get_resp.status_code == 200
        assert get_resp.json() == payload

    @pytest.mark.asyncio
    async def test_put_with_common_answers(self, client: AsyncClient) -> None:
        """PUT /config/profile stores common_answers dict correctly."""
        payload = {
            "full_name": "John",
            "common_answers": {"q1": "a1", "q2": "a2"},
        }
        resp = await client.put("/config/profile", json=payload)
        assert resp.status_code == 200
        assert resp.json()["common_answers"] == {"q1": "a1", "q2": "a2"}


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class TestSettings:
    """Tests for GET/PUT /config/settings."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_with_redacted_secrets(self, client: AsyncClient) -> None:
        """GET /config/settings returns defaults with secrets redacted."""
        resp = await client.get("/config/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claude_api_key"] == "***"
        assert data["gmail_user"] == "***"
        assert data["gmail_app_password"] == "***"
        assert data["good_fit_threshold"] == 75
        assert data["stretch_threshold"] == 50

    @pytest.mark.asyncio
    async def test_put_stores_secrets_but_get_redacts(self, client: AsyncClient) -> None:
        """PUT /config/settings stores real values; GET redacts secrets."""
        payload = {
            "claude_api_key": "sk-ant-real-key-12345",
            "gmail_user": "user@gmail.com",
            "gmail_app_password": "super-secret",
            "sms_gateway": "5551234567@txt.att.net",
            "good_fit_threshold": 80,
            "stretch_threshold": 55,
        }
        put_resp = await client.put("/config/settings", json=payload)
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        # PUT response also redacts secrets
        assert put_data["claude_api_key"] == "***"
        assert put_data["gmail_user"] == "***"
        assert put_data["gmail_app_password"] == "***"
        # Non-secret fields are returned as-is
        assert put_data["sms_gateway"] == "5551234567@txt.att.net"
        assert put_data["good_fit_threshold"] == 80

        get_resp = await client.get("/config/settings")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["claude_api_key"] == "***"
        assert get_data["sms_gateway"] == "5551234567@txt.att.net"
        assert get_data["good_fit_threshold"] == 80

    @pytest.mark.asyncio
    async def test_put_merges_with_existing(self, client: AsyncClient) -> None:
        """PUT /config/settings merges partial updates with existing values."""
        # First PUT sets some values
        await client.put(
            "/config/settings",
            json={"claude_api_key": "key1", "good_fit_threshold": 80},
        )

        # Second PUT updates only threshold
        resp = await client.put(
            "/config/settings",
            json={"good_fit_threshold": 90},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Threshold updated
        assert data["good_fit_threshold"] == 90
        # Secret still redacted (but was preserved in storage)
        assert data["claude_api_key"] == "***"

    @pytest.mark.asyncio
    async def test_put_with_all_none_is_noop(self, client: AsyncClient) -> None:
        """PUT /config/settings with all None fields preserves existing."""
        await client.put(
            "/config/settings",
            json={"sms_gateway": "5551234567@txt.att.net", "good_fit_threshold": 85},
        )

        # PUT with empty body (all None)
        resp = await client.put("/config/settings", json={})
        assert resp.status_code == 200
        data = resp.json()
        # Existing values preserved
        assert data["sms_gateway"] == "5551234567@txt.att.net"
        assert data["good_fit_threshold"] == 85


# ---------------------------------------------------------------------------
# Auth dependency tests
# ---------------------------------------------------------------------------


class TestAuthDependency:
    """Tests verifying auth is enforced on config routes."""

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401_or_403(self, db_session: AsyncSession) -> None:
        """Requests without auth header are rejected."""
        # Create app WITHOUT overriding auth
        app = FastAPI()
        app.include_router(router)

        async def _get_test_session():
            yield db_session

        app.dependency_overrides[get_session] = _get_test_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/config/search")
            # FastAPI HTTPBearer returns 403 when no credentials are provided
            assert resp.status_code in (401, 403)
