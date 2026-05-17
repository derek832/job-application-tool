"""Unit tests for preview pipeline API endpoints.

Tests the GET /preview/{run_id} and POST /preview/{run_id}/promote endpoints.
The POST /preview endpoint is tested with a mocked background task since it
triggers an async pipeline execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.preview_routes import router
from src.db.database import get_session
from src.db.models import Base, PreviewJob, PreviewRun


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
    """Create a FastAPI app with preview routes and overridden dependencies."""
    from src.api.system_routes import verify_token

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
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def sample_preview_run(db_session: AsyncSession) -> PreviewRun:
    """Create a completed preview run with sample jobs."""
    now = datetime.now(UTC).isoformat()
    run = PreviewRun(
        id="test-run-001",
        status="completed",
        started_at=now,
        completed_at=now,
        total_discovered=3,
        total_scored=2,
        total_blacklisted=1,
    )
    db_session.add(run)

    jobs = [
        PreviewJob(
            run_id="test-run-001",
            job_id="job-100",
            job_title="Senior Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/job-100",
            fit_score=85,
            fit_rationale="Strong match on cloud experience.",
            projected_action="auto_apply",
        ),
        PreviewJob(
            run_id="test-run-001",
            job_id="job-101",
            job_title="Staff Engineer",
            company="Beta Inc",
            linkedin_url="https://linkedin.com/jobs/view/job-101",
            fit_score=60,
            fit_rationale="Partial match on backend skills.",
            projected_action="stretch_queue",
        ),
        PreviewJob(
            run_id="test-run-001",
            job_id="job-102",
            job_title="Junior Developer",
            company="Revature",
            linkedin_url="https://linkedin.com/jobs/view/job-102",
            fit_score=None,
            fit_rationale="Blacklisted: company:Revature",
            projected_action="blacklisted",
        ),
    ]
    for job in jobs:
        db_session.add(job)

    await db_session.flush()
    await db_session.commit()
    return run


# ---------------------------------------------------------------------------
# POST /preview tests
# ---------------------------------------------------------------------------


class TestTriggerPreview:
    """Tests for POST /preview."""

    @pytest.mark.asyncio
    async def test_trigger_returns_202_with_run_id(self, client: AsyncClient) -> None:
        """POST /preview returns 202 with a run_id and status 'running'."""
        with patch("src.api.preview_routes.asyncio.create_task"):
            resp = await client.post("/preview")

        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data
        assert data["status"] == "running"
        assert len(data["run_id"]) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_trigger_creates_preview_run_record(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /preview creates a PreviewRun record in the database."""
        from sqlalchemy import select

        with patch("src.api.preview_routes.asyncio.create_task"):
            resp = await client.post("/preview")

        run_id = resp.json()["run_id"]

        result = await db_session.execute(
            select(PreviewRun).where(PreviewRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        assert run is not None
        assert run.status == "running"
        assert run.total_discovered == 0


# ---------------------------------------------------------------------------
# GET /preview/{run_id} tests
# ---------------------------------------------------------------------------


class TestGetPreviewRun:
    """Tests for GET /preview/{run_id}."""

    @pytest.mark.asyncio
    async def test_get_returns_completed_run(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """GET /preview/{run_id} returns the full run with jobs."""
        resp = await client.get("/preview/test-run-001")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-run-001"
        assert data["status"] == "completed"
        assert data["total_discovered"] == 3
        assert data["total_scored"] == 2
        assert data["total_blacklisted"] == 1
        assert len(data["jobs"]) == 3

    @pytest.mark.asyncio
    async def test_get_returns_job_details(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """GET /preview/{run_id} includes correct job details."""
        resp = await client.get("/preview/test-run-001")
        data = resp.json()

        # Find the auto_apply job
        auto_apply_jobs = [j for j in data["jobs"] if j["projected_action"] == "auto_apply"]
        assert len(auto_apply_jobs) == 1
        job = auto_apply_jobs[0]
        assert job["job_id"] == "job-100"
        assert job["job_title"] == "Senior Engineer"
        assert job["company"] == "Acme Corp"
        assert job["fit_score"] == 85
        assert job["promoted"] is False

    @pytest.mark.asyncio
    async def test_get_returns_404_for_unknown_run(self, client: AsyncClient) -> None:
        """GET /preview/{run_id} returns 404 for non-existent run."""
        resp = await client.get("/preview/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_running_run_returns_empty_jobs(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /preview/{run_id} returns empty jobs list for a running preview."""
        now = datetime.now(UTC).isoformat()
        run = PreviewRun(
            id="running-run",
            status="running",
            started_at=now,
            total_discovered=0,
            total_scored=0,
            total_blacklisted=0,
        )
        db_session.add(run)
        await db_session.flush()
        await db_session.commit()

        resp = await client.get("/preview/running-run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["jobs"] == []


# ---------------------------------------------------------------------------
# POST /preview/{run_id}/promote tests
# ---------------------------------------------------------------------------


class TestPromoteJobs:
    """Tests for POST /preview/{run_id}/promote."""

    @pytest.mark.asyncio
    async def test_promote_returns_promoted_ids(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """POST /preview/{run_id}/promote returns the promoted job IDs."""
        resp = await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": ["job-100"]},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["promoted_ids"] == ["job-100"]
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_promote_multiple_jobs(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """POST /preview/{run_id}/promote handles multiple job IDs."""
        resp = await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": ["job-100", "job-101"]},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["promoted_ids"]) == {"job-100", "job-101"}
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_promote_returns_404_for_unknown_run(
        self, client: AsyncClient
    ) -> None:
        """POST /preview/{run_id}/promote returns 404 for non-existent run."""
        resp = await client.post(
            "/preview/nonexistent/promote",
            json={"job_ids": ["job-100"]},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_promote_returns_400_for_empty_job_ids(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """POST /preview/{run_id}/promote returns 400 for empty job_ids."""
        resp = await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": []},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_promote_marks_jobs_as_promoted(
        self, client: AsyncClient, db_session: AsyncSession, sample_preview_run: PreviewRun
    ) -> None:
        """Promoted jobs have promoted=1 in the database."""
        from sqlalchemy import select

        await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": ["job-100"]},
        )

        result = await db_session.execute(
            select(PreviewJob).where(
                PreviewJob.run_id == "test-run-001",
                PreviewJob.job_id == "job-100",
            )
        )
        job = result.scalar_one()
        assert job.promoted == 1
        assert job.promoted_at is not None

    @pytest.mark.asyncio
    async def test_promote_creates_job_record(
        self, client: AsyncClient, db_session: AsyncSession, sample_preview_run: PreviewRun
    ) -> None:
        """Promoted jobs are inserted into job_records with approved_for_apply status."""
        from sqlalchemy import select
        from src.db.models import JobRecord

        await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": ["job-100"]},
        )

        result = await db_session.execute(
            select(JobRecord).where(JobRecord.id == "job-100")
        )
        job_record = result.scalar_one_or_none()
        assert job_record is not None
        assert job_record.status == "approved_for_apply"
        assert job_record.job_title == "Senior Engineer"
        assert job_record.company == "Acme Corp"

    @pytest.mark.asyncio
    async def test_promote_ignores_nonexistent_job_ids(
        self, client: AsyncClient, sample_preview_run: PreviewRun
    ) -> None:
        """Promoting non-existent job IDs returns empty promoted list."""
        resp = await client.post(
            "/preview/test-run-001/promote",
            json={"job_ids": ["nonexistent-job"]},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["promoted_ids"] == []
        assert data["count"] == 0
