"""
Property-based tests for CAPTCHA Expiry After 24 Hours.

Uses Hypothesis to verify that expire_stale_captcha_escalations correctly
expires CAPTCHA escalations older than 24 hours, setting the appropriate
status, resolution_method, resolved_at, and transitioning the associated
job to "apply_failed".

Properties tested:
- Property 14: CAPTCHA Expiry After 24 Hours

Feature: human-in-the-loop-escalation, Property 14: CAPTCHA Expiry After 24 Hours
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import expire_stale_captcha_escalations


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate created_at timestamps older than 24 hours (25 hours to 365 days ago)
hours_past_expiry_strategy = st.integers(min_value=25, max_value=8760).map(
    lambda hours_ago: datetime.now(tz=UTC) - timedelta(hours=hours_ago)
)

# Generate various job titles
job_title_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=3,
    max_size=50,
).filter(lambda s: s.strip())

# Generate various company names
company_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=2,
    max_size=30,
).filter(lambda s: s.strip())


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


# ---------------------------------------------------------------------------
# Property 14: CAPTCHA Expiry After 24 Hours
# ---------------------------------------------------------------------------


@given(
    created_at=hours_past_expiry_strategy,
    job_title=job_title_strategy,
    company=company_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_captcha_expiry_sets_status_to_expired(
    created_at: datetime,
    job_title: str,
    company: str,
    async_engine,
) -> None:
    """
    For any CAPTCHA escalation record where (current_time - created_at) exceeds
    24 hours and status is still "pending", the expiry handler should set
    escalation status to "expired".

    **Validates: Requirements 1.5**

    Feature: human-in-the-loop-escalation, Property 14: CAPTCHA Expiry After 24 Hours
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job_id = f"job-captcha-exp-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title=job_title,
            company=company,
            linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
            apply_type="external_apply",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending CAPTCHA escalation older than 24 hours
        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="captcha",
            form_state_snapshot=json.dumps({"external_url": "https://example.com/apply"}),
            draft_answers=None,
            timeout_deadline=None,
            freshness_tier=None,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        # Run the expiry handler
        expired = await expire_stale_captcha_escalations(session)

        # Verify escalation status is "expired"
        assert len(expired) == 1, (
            f"Expected 1 expired record, got {len(expired)} "
            f"for created_at={created_at.isoformat()}"
        )
        assert expired[0].status == "expired", (
            f"Expected status='expired', got '{expired[0].status}' "
            f"for created_at={created_at.isoformat()}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    created_at=hours_past_expiry_strategy,
    job_title=job_title_strategy,
    company=company_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_captcha_expiry_sets_resolution_method_to_timeout_expired(
    created_at: datetime,
    job_title: str,
    company: str,
    async_engine,
) -> None:
    """
    For any CAPTCHA escalation record where (current_time - created_at) exceeds
    24 hours and status is still "pending", the expiry handler should set
    resolution_method to "timeout_expired".

    **Validates: Requirements 1.5**

    Feature: human-in-the-loop-escalation, Property 14: CAPTCHA Expiry After 24 Hours
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-captcha-exp-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title=job_title,
            company=company,
            linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
            apply_type="external_apply",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="captcha",
            form_state_snapshot=json.dumps({"external_url": "https://example.com/apply"}),
            draft_answers=None,
            timeout_deadline=None,
            freshness_tier=None,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        expired = await expire_stale_captcha_escalations(session)

        assert len(expired) == 1
        assert expired[0].resolution_method == "timeout_expired", (
            f"Expected resolution_method='timeout_expired', "
            f"got '{expired[0].resolution_method}' "
            f"for created_at={created_at.isoformat()}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    created_at=hours_past_expiry_strategy,
    job_title=job_title_strategy,
    company=company_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_captcha_expiry_sets_resolved_at_non_null(
    created_at: datetime,
    job_title: str,
    company: str,
    async_engine,
) -> None:
    """
    For any CAPTCHA escalation record where (current_time - created_at) exceeds
    24 hours and status is still "pending", the expiry handler should set
    resolved_at to a non-null value (current UTC time).

    **Validates: Requirements 1.5**

    Feature: human-in-the-loop-escalation, Property 14: CAPTCHA Expiry After 24 Hours
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-captcha-exp-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title=job_title,
            company=company,
            linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
            apply_type="external_apply",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="captcha",
            form_state_snapshot=json.dumps({"external_url": "https://example.com/apply"}),
            draft_answers=None,
            timeout_deadline=None,
            freshness_tier=None,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        expired = await expire_stale_captcha_escalations(session)

        assert len(expired) == 1
        assert expired[0].resolved_at is not None, (
            f"Expected resolved_at to be non-null after expiry, "
            f"got None for created_at={created_at.isoformat()}"
        )

        # Verify it's a valid ISO 8601 timestamp
        resolved = datetime.fromisoformat(expired[0].resolved_at)
        assert resolved.tzinfo is not None, "resolved_at should be timezone-aware"

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    created_at=hours_past_expiry_strategy,
    job_title=job_title_strategy,
    company=company_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_captcha_expiry_transitions_job_to_apply_failed(
    created_at: datetime,
    job_title: str,
    company: str,
    async_engine,
) -> None:
    """
    For any CAPTCHA escalation record where (current_time - created_at) exceeds
    24 hours and status is still "pending", the expiry handler should transition
    the associated job to status="apply_failed".

    **Validates: Requirements 1.5**

    Feature: human-in-the-loop-escalation, Property 14: CAPTCHA Expiry After 24 Hours
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-captcha-exp-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title=job_title,
            company=company,
            linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
            apply_type="external_apply",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=48)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="captcha",
            form_state_snapshot=json.dumps({"external_url": "https://example.com/apply"}),
            draft_answers=None,
            timeout_deadline=None,
            freshness_tier=None,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        await expire_stale_captcha_escalations(session)

        # Refresh the job record to see the updated status
        await session.refresh(job)
        assert job.status == "apply_failed", (
            f"Expected job status='apply_failed', got '{job.status}' "
            f"for created_at={created_at.isoformat()}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()
