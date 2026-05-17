"""Unit tests for schedule configuration API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config_routes import router, schedule_router
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

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI app with config and schedule routes."""
    from src.api.auth import verify_token

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.include_router(schedule_router)

    # Mock scheduler on app state
    mock_scheduler = MagicMock()
    mock_scheduler.get_jobs.return_value = []
    test_app.state.scheduler = mock_scheduler

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
# GET /config/schedule tests
# ---------------------------------------------------------------------------


class TestGetScheduleConfig:
    """Tests for GET /config/schedule."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/schedule returns default config when not set."""
        resp = await client.get("/config/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "specific_times"
        assert data["times"] == []
        assert data["interval_hours"] == 2
        assert data["window_start"] == "08:00"
        assert data["window_end"] == "20:00"
        assert data["weekend_runs"] is False
        assert data["timezone"] == "America/New_York"
        assert data["quiet_hours_start"] is None
        assert data["quiet_hours_end"] is None

    @pytest.mark.asyncio
    async def test_returns_stored_config(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /config/schedule returns previously stored config."""
        from src.db.config_repo import set_config

        config_data = {
            "mode": "specific_times",
            "times": ["09:00", "13:00", "17:00"],
            "interval_hours": 2,
            "window_start": "08:00",
            "window_end": "20:00",
            "weekend_runs": True,
            "timezone": "America/Chicago",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        }
        await set_config(db_session, "schedule_config", config_data)
        await db_session.commit()

        resp = await client.get("/config/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "specific_times"
        assert data["times"] == ["09:00", "13:00", "17:00"]
        assert data["weekend_runs"] is True
        assert data["timezone"] == "America/Chicago"
        assert data["quiet_hours_start"] == "22:00"
        assert data["quiet_hours_end"] == "07:00"


# ---------------------------------------------------------------------------
# PUT /config/schedule tests
# ---------------------------------------------------------------------------


class TestPutScheduleConfig:
    """Tests for PUT /config/schedule."""

    @pytest.mark.asyncio
    async def test_saves_valid_specific_times_config(
        self, client: AsyncClient
    ) -> None:
        """PUT /config/schedule saves a valid specific_times config."""
        payload = {
            "mode": "specific_times",
            "times": ["09:00", "13:00", "17:00"],
            "weekend_runs": False,
            "timezone": "America/New_York",
        }
        resp = await client.put("/config/schedule", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "specific_times"
        assert data["times"] == ["09:00", "13:00", "17:00"]

    @pytest.mark.asyncio
    async def test_saves_valid_interval_config(self, client: AsyncClient) -> None:
        """PUT /config/schedule saves a valid interval config."""
        payload = {
            "mode": "interval",
            "interval_hours": 3,
            "window_start": "08:00",
            "window_end": "18:00",
            "weekend_runs": True,
            "timezone": "America/Los_Angeles",
        }
        resp = await client.put("/config/schedule", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "interval"
        assert data["interval_hours"] == 3
        assert data["window_start"] == "08:00"
        assert data["window_end"] == "18:00"

    @pytest.mark.asyncio
    async def test_rejects_zero_times_in_specific_mode(
        self, client: AsyncClient
    ) -> None:
        """PUT /config/schedule returns 422 for zero times in specific_times mode."""
        payload = {
            "mode": "specific_times",
            "times": [],
            "weekend_runs": False,
            "timezone": "America/New_York",
        }
        resp = await client.put("/config/schedule", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert "at least one time" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_time_format(self, client: AsyncClient) -> None:
        """PUT /config/schedule returns 422 for invalid time format."""
        payload = {
            "mode": "specific_times",
            "times": ["9:00", "25:00"],
            "weekend_runs": False,
            "timezone": "America/New_York",
        }
        resp = await client.put("/config/schedule", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert "invalid time format" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_timezone(self, client: AsyncClient) -> None:
        """PUT /config/schedule returns 422 for invalid timezone."""
        payload = {
            "mode": "specific_times",
            "times": ["09:00"],
            "weekend_runs": False,
            "timezone": "Invalid/Timezone",
        }
        resp = await client.put("/config/schedule", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert "timezone" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_calls_apply_schedule_for_hot_reload(
        self, client: AsyncClient, app: FastAPI
    ) -> None:
        """PUT /config/schedule calls apply_schedule on the scheduler."""
        payload = {
            "mode": "specific_times",
            "times": ["09:00", "17:00"],
            "weekend_runs": False,
            "timezone": "America/New_York",
        }

        with patch(
            "src.api.config_routes.apply_schedule"
        ) as mock_apply:
            resp = await client.put("/config/schedule", json=payload)
            assert resp.status_code == 200
            mock_apply.assert_called_once()
            # Verify the scheduler was passed
            call_args = mock_apply.call_args
            assert call_args[0][0] is app.state.scheduler

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/schedule persists data retrievable via GET."""
        payload = {
            "mode": "interval",
            "interval_hours": 4,
            "window_start": "07:00",
            "window_end": "19:00",
            "weekend_runs": True,
            "timezone": "Europe/London",
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "06:00",
        }
        put_resp = await client.put("/config/schedule", json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/config/schedule")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["mode"] == "interval"
        assert data["interval_hours"] == 4
        assert data["window_start"] == "07:00"
        assert data["window_end"] == "19:00"
        assert data["weekend_runs"] is True
        assert data["timezone"] == "Europe/London"
        assert data["quiet_hours_start"] == "23:00"
        assert data["quiet_hours_end"] == "06:00"


# ---------------------------------------------------------------------------
# GET /schedule/next tests
# ---------------------------------------------------------------------------


class TestGetScheduleNext:
    """Tests for GET /schedule/next."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_config(self, client: AsyncClient) -> None:
        """GET /schedule/next returns empty list when no schedule is configured."""
        resp = await client.get("/schedule/next")
        assert resp.status_code == 200
        data = resp.json()
        assert data["next_runs"] == []

    @pytest.mark.asyncio
    async def test_returns_next_runs_for_specific_times(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /schedule/next returns computed next run times."""
        from src.db.config_repo import set_config

        config_data = {
            "mode": "specific_times",
            "times": ["09:00", "13:00", "17:00"],
            "interval_hours": 2,
            "window_start": "08:00",
            "window_end": "20:00",
            "weekend_runs": True,
            "timezone": "America/New_York",
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        }
        await set_config(db_session, "schedule_config", config_data)
        await db_session.commit()

        resp = await client.get("/schedule/next")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["next_runs"]) == 3
        # All should be ISO 8601 strings
        for run_time in data["next_runs"]:
            assert isinstance(run_time, str)
            assert ":" in run_time  # Basic ISO format check

    @pytest.mark.asyncio
    async def test_returns_422_for_invalid_stored_config(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /schedule/next returns 422 if stored config is invalid."""
        from src.db.config_repo import set_config

        # Store config with zero times (invalid for specific_times mode)
        config_data = {
            "mode": "specific_times",
            "times": [],
            "interval_hours": 2,
            "window_start": "08:00",
            "window_end": "20:00",
            "weekend_runs": False,
            "timezone": "America/New_York",
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        }
        await set_config(db_session, "schedule_config", config_data)
        await db_session.commit()

        resp = await client.get("/schedule/next")
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_returns_next_runs_for_interval_mode(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /schedule/next returns computed next run times for interval mode."""
        from src.db.config_repo import set_config

        config_data = {
            "mode": "interval",
            "times": [],
            "interval_hours": 2,
            "window_start": "08:00",
            "window_end": "20:00",
            "weekend_runs": True,
            "timezone": "America/New_York",
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        }
        await set_config(db_session, "schedule_config", config_data)
        await db_session.commit()

        resp = await client.get("/schedule/next")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["next_runs"]) == 3
