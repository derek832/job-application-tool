"""Unit tests for Human Queue API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.queue_routes import router
from src.db.database import get_session
from src.db.models import Base, JobRecord

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
    """Create a FastAPI app with queue routes and overridden dependencies."""
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


def _make_job_record(
    job_id: str = "12345",
    status: str = "scored",
    queue_reason: str | None = "stretch_role",
    fit_score: int | None = 65,
) -> JobRecord:
    """Create a JobRecord instance for testing."""
    now = datetime.now(UTC).isoformat()
    return JobRecord(
        id=job_id,
        job_title="Senior Software Engineer",
        company="Acme Corp",
        location="San Francisco, CA",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        external_url=None,
        apply_type="easy_apply",
        status=status,
        fit_score=fit_score,
        fit_rationale="Strong Python match but lacks Kubernetes experience.",
        queue_reason=queue_reason,
        discovered_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# GET /queue tests
# ---------------------------------------------------------------------------


class TestListQueueItems:
    """Tests for GET /queue."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items(self, client: AsyncClient) -> None:
        """GET /queue returns empty list when no jobs are in the queue."""
        resp = await client.get("/queue")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_queued_items(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /queue returns jobs with non-null queue_reason and non-terminal status."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        resp = await client.get("/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["job_id"] == "12345"
        assert data[0]["job_title"] == "Senior Software Engineer"
        assert data[0]["company"] == "Acme Corp"
        assert data[0]["queue_reason"] == "stretch_role"
        assert data[0]["fit_score"] == 65

    @pytest.mark.asyncio
    async def test_excludes_terminal_status_items(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /queue excludes jobs in terminal statuses even with queue_reason."""
        record = _make_job_record(status="rejected_by_user", queue_reason="stretch_role")
        db_session.add(record)
        await db_session.commit()

        resp = await client.get("/queue")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_excludes_items_without_queue_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /queue excludes jobs without a queue_reason."""
        record = _make_job_record(queue_reason=None)
        db_session.add(record)
        await db_session.commit()

        resp = await client.get("/queue")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /queue/{id}/approve tests
# ---------------------------------------------------------------------------


class TestApproveQueueItem:
    """Tests for POST /queue/{id}/approve."""

    @pytest.mark.asyncio
    async def test_approve_sets_status_and_clears_queue(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /queue/{id}/approve sets status to approved_for_apply."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        resp = await client.post("/queue/12345/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "12345"
        assert data["queue_reason"] is None

        # Verify DB state
        await db_session.refresh(record)
        assert record.status == "approved_for_apply"
        assert record.queue_reason is None
        assert record.approved_at is not None

    @pytest.mark.asyncio
    async def test_approve_returns_404_for_missing_job(self, client: AsyncClient) -> None:
        """POST /queue/{id}/approve returns 404 for non-existent job."""
        resp = await client.post("/queue/nonexistent/approve")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_records_approved_at_timestamp(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /queue/{id}/approve sets approved_at timestamp."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        await client.post("/queue/12345/approve")

        await db_session.refresh(record)
        assert record.approved_at is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(record.approved_at)


# ---------------------------------------------------------------------------
# POST /queue/{id}/reject tests
# ---------------------------------------------------------------------------


class TestRejectQueueItem:
    """Tests for POST /queue/{id}/reject."""

    @pytest.mark.asyncio
    async def test_reject_sets_status_and_clears_queue(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /queue/{id}/reject sets status to rejected_by_user."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        resp = await client.post("/queue/12345/reject")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "12345"
        assert data["queue_reason"] is None

        # Verify DB state
        await db_session.refresh(record)
        assert record.status == "rejected_by_user"
        assert record.queue_reason is None

    @pytest.mark.asyncio
    async def test_reject_returns_404_for_missing_job(self, client: AsyncClient) -> None:
        """POST /queue/{id}/reject returns 404 for non-existent job."""
        resp = await client.post("/queue/nonexistent/reject")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /queue/{id}/manual tests
# ---------------------------------------------------------------------------


class TestMarkManuallyApplied:
    """Tests for POST /queue/{id}/manual."""

    @pytest.mark.asyncio
    async def test_manual_sets_status_and_clears_queue(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /queue/{id}/manual sets status to manually_applied."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        resp = await client.post("/queue/12345/manual")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "12345"
        assert data["queue_reason"] is None

        # Verify DB state
        await db_session.refresh(record)
        assert record.status == "manually_applied"
        assert record.queue_reason is None
        assert record.applied_at is not None

    @pytest.mark.asyncio
    async def test_manual_returns_404_for_missing_job(self, client: AsyncClient) -> None:
        """POST /queue/{id}/manual returns 404 for non-existent job."""
        resp = await client.post("/queue/nonexistent/manual")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manual_records_applied_at_timestamp(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /queue/{id}/manual sets applied_at timestamp."""
        record = _make_job_record()
        db_session.add(record)
        await db_session.commit()

        await client.post("/queue/12345/manual")

        await db_session.refresh(record)
        assert record.applied_at is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(record.applied_at)
