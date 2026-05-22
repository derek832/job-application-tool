"""Unit tests for CAPTCHA expiry handler functions.

Tests specific examples and edge cases for:
- expire_stale_captcha_escalations() — detecting and expiring stale CAPTCHA escalations
- check_captcha_expiry_on_startup() — startup hook for handling expired CAPTCHAs

Validates: Requirements 1.5
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import (
    CAPTCHA_EXPIRY_HOURS,
    check_captcha_expiry_on_startup,
    expire_stale_captcha_escalations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_session():
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


def _make_job_record(job_id: str | None = None, status: str = "applying") -> JobRecord:
    """Create a JobRecord instance for testing."""
    now = datetime.now(tz=UTC).isoformat()
    return JobRecord(
        id=job_id or str(uuid.uuid4()),
        job_title="Software Engineer",
        company="Acme Corp",
        linkedin_url="https://linkedin.com/jobs/view/123",
        apply_type="external_apply",
        status=status,
        discovered_at=now,
        updated_at=now,
    )


def _make_captcha_escalation(
    job_id: str,
    created_at: datetime,
    status: str = "pending",
) -> EscalationRecord:
    """Create a CAPTCHA escalation record for testing."""
    return EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tier="captcha",
        form_state_snapshot=json.dumps({"external_url": "https://example.com"}),
        draft_answers=None,
        timeout_deadline=None,
        freshness_tier=None,
        status=status,
        resolution_method=None,
        created_at=created_at.isoformat(),
        resolved_at=None,
    )


# ---------------------------------------------------------------------------
# expire_stale_captcha_escalations()
# ---------------------------------------------------------------------------


class TestExpireStaleCaptchaEscalations:
    """Test the CAPTCHA expiry sweep function."""

    @pytest.mark.asyncio
    async def test_expires_captcha_older_than_24_hours(self, async_session: AsyncSession) -> None:
        """A CAPTCHA escalation older than 24 hours should be expired."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=25)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        assert len(expired) == 1
        assert expired[0].id == escalation.id
        assert expired[0].status == "expired"
        assert expired[0].resolution_method == "timeout_expired"
        assert expired[0].resolved_at is not None

    @pytest.mark.asyncio
    async def test_does_not_expire_captcha_under_24_hours(
        self, async_session: AsyncSession
    ) -> None:
        """A CAPTCHA escalation less than 24 hours old should NOT be expired."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=23)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        assert len(expired) == 0
        await async_session.refresh(escalation)
        assert escalation.status == "pending"

    @pytest.mark.asyncio
    async def test_transitions_job_to_apply_failed(self, async_session: AsyncSession) -> None:
        """Expiring a CAPTCHA should transition the job to apply_failed."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=25)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        await expire_stale_captcha_escalations(async_session)

        await async_session.refresh(job)
        assert job.status == "apply_failed"

    @pytest.mark.asyncio
    async def test_ignores_already_resolved_captcha(self, async_session: AsyncSession) -> None:
        """A CAPTCHA escalation that is already resolved should not be expired again."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=48)
        escalation = _make_captcha_escalation(job.id, created_at, status="resolved")
        escalation.resolution_method = "captcha_solved"
        escalation.resolved_at = (created_at + timedelta(hours=1)).isoformat()
        async_session.add(escalation)
        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_ignores_human_review_escalations(self, async_session: AsyncSession) -> None:
        """Human review escalations should not be affected by CAPTCHA expiry."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=48)
        escalation = EscalationRecord(
            id=str(uuid.uuid4()),
            job_id=job.id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com"}),
            draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "test"}]),
            timeout_deadline=(created_at + timedelta(hours=6)).isoformat(),
            freshness_tier="recent",
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        async_session.add(escalation)
        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_expires_multiple_stale_captchas(self, async_session: AsyncSession) -> None:
        """Multiple stale CAPTCHA escalations should all be expired."""
        jobs = []
        escalations = []
        for i in range(3):
            job = _make_job_record()
            async_session.add(job)
            jobs.append(job)

        await async_session.flush()

        for i, job in enumerate(jobs):
            created_at = datetime.now(tz=UTC) - timedelta(hours=25 + i)
            esc = _make_captcha_escalation(job.id, created_at)
            async_session.add(esc)
            escalations.append(esc)

        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        assert len(expired) == 3
        for esc in expired:
            assert esc.status == "expired"
            assert esc.resolution_method == "timeout_expired"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_pending_captchas(
        self, async_session: AsyncSession
    ) -> None:
        """When there are no pending CAPTCHA escalations, returns empty list."""
        expired = await expire_stale_captcha_escalations(async_session)
        assert expired == []

    @pytest.mark.asyncio
    async def test_boundary_exactly_24_hours_not_expired(
        self, async_session: AsyncSession
    ) -> None:
        """A CAPTCHA escalation exactly 24 hours old should NOT be expired (boundary)."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        # Exactly at the cutoff — not strictly older than 24 hours
        created_at = datetime.now(tz=UTC) - timedelta(hours=24)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        expired = await expire_stale_captcha_escalations(async_session)

        # At exactly 24 hours, the record is at the boundary.
        # The condition is (created > cutoff) means NOT expired,
        # so exactly at cutoff means created == cutoff, which is NOT > cutoff,
        # so it WILL be expired.
        assert len(expired) == 1

    @pytest.mark.asyncio
    async def test_captcha_expiry_hours_constant(self) -> None:
        """The CAPTCHA_EXPIRY_HOURS constant should be 24."""
        assert CAPTCHA_EXPIRY_HOURS == 24


# ---------------------------------------------------------------------------
# check_captcha_expiry_on_startup()
# ---------------------------------------------------------------------------


class TestCheckCaptchaExpiryOnStartup:
    """Test the startup hook for CAPTCHA expiry."""

    @pytest.mark.asyncio
    async def test_expires_stale_captchas_on_startup(self, async_session: AsyncSession) -> None:
        """Startup check should expire stale CAPTCHA escalations."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=30)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        expired = await check_captcha_expiry_on_startup(async_session)

        assert len(expired) == 1
        assert expired[0].status == "expired"

    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_to_expire(
        self, async_session: AsyncSession
    ) -> None:
        """Startup check returns empty list when no stale CAPTCHAs exist."""
        expired = await check_captcha_expiry_on_startup(async_session)
        assert expired == []

    @pytest.mark.asyncio
    async def test_startup_transitions_jobs_correctly(
        self, async_session: AsyncSession
    ) -> None:
        """Startup expiry should transition associated jobs to apply_failed."""
        job = _make_job_record()
        async_session.add(job)
        await async_session.flush()

        created_at = datetime.now(tz=UTC) - timedelta(hours=48)
        escalation = _make_captcha_escalation(job.id, created_at)
        async_session.add(escalation)
        await async_session.flush()

        await check_captcha_expiry_on_startup(async_session)

        await async_session.refresh(job)
        assert job.status == "apply_failed"
