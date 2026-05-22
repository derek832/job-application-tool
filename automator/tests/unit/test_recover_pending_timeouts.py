"""Unit tests for recover_pending_timeouts_on_startup.

Tests cover:
- No-op when no pending escalations exist
- Past deadlines trigger immediate auto-submit via handle_timeout
- Future deadlines re-register APScheduler jobs
- Mixed past/future deadlines are handled correctly
- CAPTCHA escalations (no timeout_deadline) are ignored

Validates: Requirements 4.4
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_scheduler import recover_pending_timeouts_on_startup


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


def _make_job_record(job_id: str | None = None) -> JobRecord:
    """Create a minimal JobRecord for testing."""
    now = datetime.now(tz=UTC).isoformat()
    return JobRecord(
        id=job_id or str(uuid.uuid4()),
        job_title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/123",
        apply_type="external_apply",
        status="applying",
        discovered_at=now,
        updated_at=now,
    )


def _make_escalation(
    job_id: str,
    *,
    status: str = "pending",
    tier: str = "human_review",
    timeout_deadline: str | None = None,
) -> EscalationRecord:
    """Create an EscalationRecord for testing."""
    return EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tier=tier,
        form_state_snapshot=json.dumps({"fields": []}),
        draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "test"}]),
        timeout_deadline=timeout_deadline,
        freshness_tier="fresh" if tier == "human_review" else None,
        status=status,
        resolution_method=None,
        created_at=(datetime.now(tz=UTC) - timedelta(hours=1)).isoformat(),
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_no_pending_escalations(async_session: AsyncSession) -> None:
    """When no pending escalations exist, function completes without action."""
    await recover_pending_timeouts_on_startup(async_session)
    # No error raised, no side effects


@pytest.mark.asyncio
async def test_past_deadline_triggers_auto_submit(async_session: AsyncSession) -> None:
    """Escalations with past deadlines trigger immediate handle_timeout."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    past_deadline = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
    esc = _make_escalation(job.id, timeout_deadline=past_deadline)
    async_session.add(esc)
    await async_session.flush()

    with patch(
        "src.pipeline.escalation_engine.handle_timeout", new_callable=AsyncMock
    ) as mock_timeout:
        await recover_pending_timeouts_on_startup(async_session)

    mock_timeout.assert_called_once_with(async_session, esc.id)


@pytest.mark.asyncio
async def test_future_deadline_reschedules_job(async_session: AsyncSession) -> None:
    """Escalations with future deadlines re-register APScheduler jobs."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    future_deadline = (datetime.now(tz=UTC) + timedelta(hours=2)).isoformat()
    esc = _make_escalation(job.id, timeout_deadline=future_deadline)
    async_session.add(esc)
    await async_session.flush()

    with patch(
        "src.pipeline.escalation_scheduler.schedule_escalation_timeout",
        return_value=True,
    ) as mock_schedule:
        await recover_pending_timeouts_on_startup(async_session)

    mock_schedule.assert_called_once()
    call_args = mock_schedule.call_args
    assert call_args[0][0] == esc.id
    # The deadline passed should be a datetime object
    assert isinstance(call_args[0][1], datetime)


@pytest.mark.asyncio
async def test_mixed_past_and_future_deadlines(async_session: AsyncSession) -> None:
    """Handles a mix of past and future deadlines correctly."""
    job1 = _make_job_record()
    job2 = _make_job_record()
    async_session.add_all([job1, job2])
    await async_session.flush()

    past_deadline = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    future_deadline = (datetime.now(tz=UTC) + timedelta(hours=3)).isoformat()

    esc_past = _make_escalation(job1.id, timeout_deadline=past_deadline)
    esc_future = _make_escalation(job2.id, timeout_deadline=future_deadline)
    async_session.add_all([esc_past, esc_future])
    await async_session.flush()

    with (
        patch(
            "src.pipeline.escalation_engine.handle_timeout", new_callable=AsyncMock
        ) as mock_timeout,
        patch(
            "src.pipeline.escalation_scheduler.schedule_escalation_timeout",
            return_value=True,
        ) as mock_schedule,
    ):
        await recover_pending_timeouts_on_startup(async_session)

    # Past deadline should trigger auto-submit
    mock_timeout.assert_called_once_with(async_session, esc_past.id)
    # Future deadline should re-schedule
    mock_schedule.assert_called_once()
    assert mock_schedule.call_args[0][0] == esc_future.id


@pytest.mark.asyncio
async def test_captcha_escalations_ignored(async_session: AsyncSession) -> None:
    """CAPTCHA escalations (no timeout_deadline) are not processed."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    # CAPTCHA escalation has no timeout_deadline
    esc = _make_escalation(job.id, tier="captcha", timeout_deadline=None)
    async_session.add(esc)
    await async_session.flush()

    with (
        patch(
            "src.pipeline.escalation_engine.handle_timeout", new_callable=AsyncMock
        ) as mock_timeout,
        patch(
            "src.pipeline.escalation_scheduler.schedule_escalation_timeout",
            return_value=True,
        ) as mock_schedule,
    ):
        await recover_pending_timeouts_on_startup(async_session)

    mock_timeout.assert_not_called()
    mock_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_resolved_escalations_ignored(async_session: AsyncSession) -> None:
    """Already-resolved escalations are not processed even if they have a deadline."""
    job = _make_job_record()
    async_session.add(job)
    await async_session.flush()

    past_deadline = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    esc = _make_escalation(job.id, status="resolved", timeout_deadline=past_deadline)
    async_session.add(esc)
    await async_session.flush()

    with (
        patch(
            "src.pipeline.escalation_engine.handle_timeout", new_callable=AsyncMock
        ) as mock_timeout,
        patch(
            "src.pipeline.escalation_scheduler.schedule_escalation_timeout",
            return_value=True,
        ) as mock_schedule,
    ):
        await recover_pending_timeouts_on_startup(async_session)

    mock_timeout.assert_not_called()
    mock_schedule.assert_not_called()
