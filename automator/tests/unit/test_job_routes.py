"""
Unit tests for the job record API routes (src/api/job_routes.py).

Uses a real in-memory SQLite database and the FastAPI test client to validate
endpoint behavior including authentication, filtering, pagination, and 404s.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.job_routes import router as job_router
from src.db.config_repo import set_config
from src.db.database import get_session
from src.db.job_repo import create_job_record, update_job_status
from src.db.models import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TOKEN = "test-secret-token"


@pytest.fixture
async def engine():
    """Create an in-memory async SQLite engine for testing."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    """Return a session factory bound to the test engine."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory) -> AsyncSession:
    """Yield a fresh AsyncSession for seeding data."""
    async with session_factory() as sess:
        yield sess


@pytest.fixture
async def app(session_factory):
    """Create a FastAPI app with the job router and overridden dependencies."""

    application = FastAPI()
    application.include_router(job_router)

    async def override_get_session():
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    application.dependency_overrides[get_session] = override_get_session

    return application


@pytest.fixture
async def authed_client(app, session) -> AsyncClient:
    """Return an AsyncClient with a valid auth token pre-configured."""
    # Store the API token in the config table
    await set_config(session, "api_token", TEST_TOKEN)
    await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["Authorization"] = f"Bearer {TEST_TOKEN}"
        yield client


@pytest.fixture
async def unauthed_client(app) -> AsyncClient:
    """Return an AsyncClient without auth headers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _seed_jobs(session: AsyncSession) -> None:
    """Seed 5 jobs with varying statuses and names."""
    jobs = [
        ("j1", "Python Developer", "Acme", "discovered"),
        ("j2", "Java Engineer", "BigCo", "extracted"),
        ("j3", "Python Lead", "StartupX", "applied"),
        ("j4", "Data Scientist", "Acme", "skipped"),
        ("j5", "ML Engineer", "DataCorp", "discovered"),
    ]
    for job_id, title, company, status in jobs:
        await create_job_record(
            session,
            id=job_id,
            job_title=title,
            company=company,
            linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
            apply_type="easy_apply",
        )
        if status != "discovered":
            await update_job_status(session, job_id, status)
    await session.commit()


# ---------------------------------------------------------------------------
# GET /jobs — authentication
# ---------------------------------------------------------------------------


class TestJobsAuth:
    async def test_returns_422_without_token(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get("/jobs")
        # FastAPI returns 422 when a required Header is missing entirely
        assert response.status_code == 422

    async def test_returns_401_with_invalid_token(self, unauthed_client: AsyncClient, session):
        await set_config(session, "api_token", TEST_TOKEN)
        await session.commit()

        response = await unauthed_client.get(
            "/jobs", headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /jobs — listing
# ---------------------------------------------------------------------------


class TestListJobs:
    async def test_returns_empty_list_when_no_jobs(self, authed_client: AsyncClient):
        response = await authed_client.get("/jobs")
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_all_jobs(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    async def test_filters_by_status(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs", params={"status": "discovered"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(j["status"] == "discovered" for j in data)

    async def test_filters_by_search(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs", params={"search": "Python"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_search_matches_company(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs", params={"search": "Acme"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_pagination(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs", params={"page": 1, "limit": 2})
        assert response.status_code == 200
        assert len(response.json()) == 2

        response = await authed_client.get("/jobs", params={"page": 3, "limit": 2})
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_invalid_page_returns_422(self, authed_client: AsyncClient):
        response = await authed_client.get("/jobs", params={"page": 0})
        assert response.status_code == 422

    async def test_invalid_limit_returns_422(self, authed_client: AsyncClient):
        response = await authed_client.get("/jobs", params={"limit": 0})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /jobs/{id}
# ---------------------------------------------------------------------------


class TestGetJob:
    async def test_returns_job_by_id(self, authed_client: AsyncClient, session: AsyncSession):
        await create_job_record(
            session,
            id="single_1",
            job_title="Backend Dev",
            company="TestCo",
            linkedin_url="https://linkedin.com/jobs/view/single_1",
            apply_type="easy_apply",
        )
        await session.commit()

        response = await authed_client.get("/jobs/single_1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "single_1"
        assert data["job_title"] == "Backend Dev"
        assert data["company"] == "TestCo"
        assert data["status"] == "discovered"

    async def test_returns_404_for_missing_job(self, authed_client: AsyncClient):
        response = await authed_client.get("/jobs/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /jobs/stats
# ---------------------------------------------------------------------------


class TestGetStats:
    async def test_returns_zeros_for_empty_db(self, authed_client: AsyncClient):
        response = await authed_client.get("/jobs/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_discovered"] == 0
        assert data["total_applied"] == 0
        assert data["total_skipped"] == 0
        assert data["total_pending_review"] == 0
        assert data["application_success_rate"] == 0.0

    async def test_returns_correct_counts(self, authed_client: AsyncClient, session: AsyncSession):
        await _seed_jobs(session)
        response = await authed_client.get("/jobs/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_discovered"] == 5
        assert data["total_applied"] == 1
        assert data["total_skipped"] == 1
