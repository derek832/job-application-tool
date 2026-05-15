"""Unit tests for the scoring pipeline stage.

Tests cover the full routing logic: good fit, stretch role, skip, deal-breaker
override, and threshold boundary detection with SMS notifications.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.agents.claude_client import FitScoreResult
from src.db.models import Base, JobRecord, NotificationLog
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.scoring_stage import run_scoring


@pytest_asyncio.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


def _make_job_record(job_id: str = "12345") -> JobRecord:
    """Create a minimal JobRecord for testing."""
    return JobRecord(
        id=job_id,
        job_title="Senior Python Developer",
        company="Acme Corp",
        location="Remote",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        apply_type="easy_apply",
        status="extracted",
        description_text="We are looking for a senior Python developer with 5+ years experience.",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )


def _make_sms_settings() -> SMSSettings:
    """Create test SMS settings."""
    return SMSSettings(
        gmail_user="test@gmail.com",
        gmail_app_password="app-password",
        sms_gateway="5551234567@txt.att.net",
    )


@pytest.mark.asyncio
async def test_good_fit_routes_to_approved(async_session: AsyncSession) -> None:
    """A score above good_fit_threshold routes to approved_for_apply."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=85,
        rationale="Strong Python match with relevant experience.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer with 7 years experience",
        goals_profile='{"target_titles": ["Senior Python Developer"]}',
        deal_breakers=[],
        good_fit_threshold=75,
        stretch_threshold=50,
    )

    assert job.fit_score == 85
    assert job.fit_rationale == "Strong Python match with relevant experience."
    assert job.status == "approved_for_apply"
    assert job.scored_at is not None
    assert job.queue_reason is None


@pytest.mark.asyncio
async def test_stretch_role_routes_to_human_queue(async_session: AsyncSession) -> None:
    """A score between stretch and good_fit thresholds routes to human queue."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=62,
        rationale="Some relevant skills but lacks Kubernetes experience.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    with patch("src.pipeline.scoring_stage.send_sms") as mock_send:
        mock_send.return_value = MagicMock(ok=True, error=None)
        await run_scoring(
            job_record=job,
            session=async_session,
            claude_client=mock_client,
            resume_content="Python developer",
            goals_profile='{"target_titles": ["Python Developer"]}',
            deal_breakers=[],
            good_fit_threshold=75,
            stretch_threshold=50,
            sms_settings=_make_sms_settings(),
        )

    assert job.fit_score == 62
    assert job.status == "scored"
    assert job.queue_reason == "stretch_role"
    assert job.scored_at is not None

    # Verify notification was logged
    result = await async_session.execute(select(NotificationLog))
    logs = list(result.scalars().all())
    assert len(logs) == 1
    assert logs[0].trigger_reason == "stretch_role"
    assert logs[0].success == 1


@pytest.mark.asyncio
async def test_low_score_routes_to_skipped(async_session: AsyncSession) -> None:
    """A score below stretch_threshold routes to skipped."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=30,
        rationale="No relevant experience for this role.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer",
        goals_profile='{"target_titles": ["Python Developer"]}',
        deal_breakers=[],
        good_fit_threshold=75,
        stretch_threshold=50,
    )

    assert job.fit_score == 30
    assert job.status == "skipped"
    assert job.scored_at is not None


@pytest.mark.asyncio
async def test_deal_breaker_overrides_high_score(async_session: AsyncSession) -> None:
    """A deal-breaker in the description forces skip regardless of score."""
    job = _make_job_record()
    job.description_text = "We need a senior developer with security clearance required."
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=90,
        rationale="Excellent match on all technical skills.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer",
        goals_profile='{"target_titles": ["Python Developer"]}',
        deal_breakers=["security clearance"],
        good_fit_threshold=75,
        stretch_threshold=50,
    )

    assert job.fit_score == 90
    assert job.status == "skipped"
    assert job.scored_at is not None


@pytest.mark.asyncio
async def test_claude_deal_breaker_detection(async_session: AsyncSession) -> None:
    """Claude's own deal-breaker detection also triggers skip."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=80,
        rationale="Good match but requires relocation.",
        deal_breaker_found=True,
        deal_breaker_term="relocation required",
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer",
        goals_profile='{"target_titles": ["Python Developer"]}',
        deal_breakers=[],
        good_fit_threshold=75,
        stretch_threshold=50,
    )

    assert job.status == "skipped"


@pytest.mark.asyncio
async def test_boundary_score_routes_to_human_queue(async_session: AsyncSession) -> None:
    """A score within ±2 of a threshold routes to human queue."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    # Score of 76 is within ±2 of good_fit_threshold=75
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=76,
        rationale="Borderline good fit.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    with patch("src.pipeline.scoring_stage.send_sms") as mock_send:
        mock_send.return_value = MagicMock(ok=True, error=None)
        await run_scoring(
            job_record=job,
            session=async_session,
            claude_client=mock_client,
            resume_content="Python developer",
            goals_profile='{"target_titles": ["Python Developer"]}',
            deal_breakers=[],
            good_fit_threshold=75,
            stretch_threshold=50,
            sms_settings=_make_sms_settings(),
        )

    assert job.status == "scored"
    assert job.queue_reason == "score_at_threshold_boundary"
    assert job.scored_at is not None

    # Verify notification was logged
    result = await async_session.execute(select(NotificationLog))
    logs = list(result.scalars().all())
    assert len(logs) == 1
    assert logs[0].trigger_reason == "score_at_threshold_boundary"


@pytest.mark.asyncio
async def test_no_sms_when_settings_none(async_session: AsyncSession) -> None:
    """When sms_settings is None, notification is logged but not sent."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=60,
        rationale="Stretch role.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer",
        goals_profile='{"target_titles": ["Python Developer"]}',
        deal_breakers=[],
        good_fit_threshold=75,
        stretch_threshold=50,
        sms_settings=None,
    )

    assert job.queue_reason == "stretch_role"

    # Notification logged as unsuccessful
    result = await async_session.execute(select(NotificationLog))
    logs = list(result.scalars().all())
    assert len(logs) == 1
    assert logs[0].success == 0
    assert logs[0].error_message == "SMS settings not configured"


@pytest.mark.asyncio
async def test_score_and_rationale_stored_exactly(async_session: AsyncSession) -> None:
    """The exact score and rationale from Claude are stored in the job record."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    rationale = "This is a detailed rationale with special chars: <>&\"'"
    mock_client = AsyncMock()
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=42,
        rationale=rationale,
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    await run_scoring(
        job_record=job,
        session=async_session,
        claude_client=mock_client,
        resume_content="Python developer",
        goals_profile='{"target_titles": ["Python Developer"]}',
        deal_breakers=[],
        good_fit_threshold=75,
        stretch_threshold=50,
    )

    assert job.fit_score == 42
    assert job.fit_rationale == rationale


@pytest.mark.asyncio
async def test_boundary_at_stretch_threshold(async_session: AsyncSession) -> None:
    """A score within ±2 of stretch_threshold also routes to human queue."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    mock_client = AsyncMock()
    # Score of 51 is within ±2 of stretch_threshold=50
    mock_client.score_fit.return_value = FitScoreResult(
        fit_score=51,
        rationale="Near stretch threshold.",
        deal_breaker_found=False,
        deal_breaker_term=None,
    )

    with patch("src.pipeline.scoring_stage.send_sms") as mock_send:
        mock_send.return_value = MagicMock(ok=True, error=None)
        await run_scoring(
            job_record=job,
            session=async_session,
            claude_client=mock_client,
            resume_content="Python developer",
            goals_profile='{"target_titles": ["Python Developer"]}',
            deal_breakers=[],
            good_fit_threshold=75,
            stretch_threshold=50,
            sms_settings=_make_sms_settings(),
        )

    assert job.status == "scored"
    assert job.queue_reason == "score_at_threshold_boundary"
