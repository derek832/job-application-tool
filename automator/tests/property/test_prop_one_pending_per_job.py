"""
Property-based tests for One Pending Escalation Per Job.

Uses Hypothesis to verify that create_escalation enforces uniqueness:
calling it twice for the same job always returns the same record (same ID),
and only one pending record exists in the DB.

Properties tested:
- Property 10: One Pending Escalation Per Job

Feature: human-in-the-loop-escalation, Property 10: One Pending Escalation Per Job
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import create_escalation
from src.pipeline.notification_service import NotificationSettings


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

tier_strategy = st.sampled_from(["captcha", "human_review"])

form_state_strategy = st.fixed_dictionaries(
    {
        "external_url": st.from_regex(
            r"https://[a-z]+\.(greenhouse|lever|workday)\.(io|com)/jobs/[0-9]+",
            fullmatch=True,
        ),
        "fields": st.lists(
            st.fixed_dictionaries(
                {
                    "field_id": st.text(
                        alphabet=st.characters(whitelist_categories=("L", "N")),
                        min_size=1,
                        max_size=20,
                    ),
                    "label": st.text(min_size=1, max_size=50),
                    "value": st.text(max_size=100),
                    "type": st.sampled_from(["text", "textarea", "select"]),
                }
            ),
            min_size=1,
            max_size=5,
        ),
        "page_title": st.text(min_size=1, max_size=100),
    }
)

draft_answer_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "field_id": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            ),
            "question_text": st.text(min_size=1, max_size=100),
            "draft_answer": st.text(min_size=1, max_size=200),
            "edited_answer": st.none(),
        }
    ),
    min_size=1,
    max_size=3,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def notification_settings() -> NotificationSettings:
    """Return notification settings with all channels disabled (for testing)."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=False,
        sms=None,
    )


# ---------------------------------------------------------------------------
# Property 10: One Pending Escalation Per Job
# ---------------------------------------------------------------------------


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_duplicate_escalation_returns_same_record(
    tier: str,
    form_state: dict,
    draft_answers: list[dict],
    async_engine,
    notification_settings: NotificationSettings,
) -> None:
    """
    For any job_id that already has a pending escalation record, attempting
    to create another pending escalation for the same job_id should return
    the existing record (same ID).

    **Validates: Requirements 7.5**

    Feature: human-in-the-loop-escalation, Property 10: One Pending Escalation Per Job
    """
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-dup-{hash((tier, str(form_state)))!s}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-dup",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=discovered.isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Use draft_answers only for human_review tier
        answers = draft_answers if tier == "human_review" else None

        # First call — creates the escalation
        first = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        # Second call — should return the existing record
        second = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        assert first.id == second.id, (
            f"Expected same escalation ID for duplicate creation. "
            f"Got first={first.id}, second={second.id}"
        )

        # Cleanup
        await session.delete(first)
        await session.delete(job)
        await session.commit()


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_only_one_pending_record_exists_after_duplicate(
    tier: str,
    form_state: dict,
    draft_answers: list[dict],
    async_engine,
    notification_settings: NotificationSettings,
) -> None:
    """
    For any job_id that already has a pending escalation record, after
    attempting to create a duplicate, only one pending record should exist
    in the database for that job.

    **Validates: Requirements 7.5**

    Feature: human-in-the-loop-escalation, Property 10: One Pending Escalation Per Job
    """
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-cnt-{hash((tier, str(form_state)))!s}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-cnt",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=discovered.isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        answers = draft_answers if tier == "human_review" else None

        # Create escalation twice
        first = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        # Query all pending escalation records for this job
        stmt = select(EscalationRecord).where(
            EscalationRecord.job_id == job.id,
            EscalationRecord.status == "pending",
        )
        result = await session.execute(stmt)
        pending_records = result.scalars().all()

        assert len(pending_records) == 1, (
            f"Expected exactly 1 pending escalation for job {job.id}, "
            f"found {len(pending_records)}"
        )

        # Cleanup
        await session.delete(first)
        await session.delete(job)
        await session.commit()
