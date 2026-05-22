"""
Property-based tests for Resolution Metadata Completeness.

Uses Hypothesis to verify that for ALL resolution paths (resolve, skip,
handle_timeout), the resolved_at timestamp is non-null and valid ISO 8601,
and the resolution_method matches the expected value for the transition type.

Properties tested:
- Property 8: Resolution Metadata Completeness

Feature: human-in-the-loop-escalation, Property 8: Resolution Metadata Completeness
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
from src.pipeline.escalation_engine import handle_timeout, resolve_escalation


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate varied draft answers for human_review escalations
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

# Generate edited answers for "resolved" resolution
edited_answer_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "field_id": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            ),
            "edited_answer": st.text(min_size=1, max_size=200),
        }
    ),
    min_size=1,
    max_size=3,
)

freshness_tier_strategy = st.sampled_from(["fresh", "recent", "stale"])


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
# Helpers
# ---------------------------------------------------------------------------


def _make_pending_escalation(
    job_id: str,
    *,
    freshness_tier: str = "fresh",
    draft_answers: list[dict] | None = None,
) -> EscalationRecord:
    """Create a pending human_review escalation record for testing."""
    now = datetime.now(tz=UTC)
    timeout_deadline = now + timedelta(minutes=45)

    if draft_answers is None:
        draft_answers = [
            {
                "field_id": "field_1",
                "question_text": "Why are you interested?",
                "draft_answer": "I'm drawn to the mission...",
            }
        ]

    return EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tier="human_review",
        form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
        draft_answers=json.dumps(draft_answers),
        timeout_deadline=timeout_deadline.isoformat(),
        freshness_tier=freshness_tier,
        status="pending",
        resolution_method=None,
        created_at=now.isoformat(),
        resolved_at=None,
    )


# ---------------------------------------------------------------------------
# Property 8: Resolution Metadata Completeness — "resolved" path
# ---------------------------------------------------------------------------


@given(
    edited_answers=edited_answer_strategy,
    freshness_tier=freshness_tier_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_resolve_resolved_sets_metadata(
    edited_answers: list[dict],
    freshness_tier: str,
    async_engine,
) -> None:
    """
    For any pending escalation resolved via "resolved", resolved_at should be
    non-null and a valid ISO 8601 timestamp, and resolution_method should be
    "user_submit". The status should transition from "pending" to "resolved".

    **Validates: Requirements 7.2**

    Feature: human-in-the-loop-escalation, Property 8: Resolution Metadata Completeness
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-res-{uuid.uuid4().hex[:8]}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-res",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending escalation
        escalation = _make_pending_escalation(
            job.id, freshness_tier=freshness_tier
        )
        session.add(escalation)
        await session.flush()

        before = datetime.now(tz=UTC)

        # Resolve with "resolved"
        result = await resolve_escalation(
            session,
            escalation.id,
            "resolved",
            edited_answers=edited_answers,
        )

        # Assert: resolved_at is non-null
        assert result.resolved_at is not None, "resolved_at must be non-null after resolution"

        # Assert: resolved_at is valid ISO 8601
        resolved_dt = datetime.fromisoformat(result.resolved_at)
        assert resolved_dt >= before, "resolved_at should be >= time before resolution"

        # Assert: resolution_method is "user_submit"
        assert result.resolution_method == "user_submit", (
            f"Expected resolution_method='user_submit', got '{result.resolution_method}'"
        )

        # Assert: status transitioned to "resolved"
        assert result.status == "resolved", (
            f"Expected status='resolved', got '{result.status}'"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


# ---------------------------------------------------------------------------
# Property 8: Resolution Metadata Completeness — "skipped" path
# ---------------------------------------------------------------------------


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_resolve_skipped_sets_metadata(
    freshness_tier: str,
    draft_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending escalation resolved via "skipped", resolved_at should be
    non-null and a valid ISO 8601 timestamp, and resolution_method should be
    "user_skip". The status should transition from "pending" to "skipped".

    **Validates: Requirements 7.2**

    Feature: human-in-the-loop-escalation, Property 8: Resolution Metadata Completeness
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-skip-{uuid.uuid4().hex[:8]}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-skip",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending escalation
        escalation = _make_pending_escalation(
            job.id, freshness_tier=freshness_tier, draft_answers=draft_answers
        )
        session.add(escalation)
        await session.flush()

        before = datetime.now(tz=UTC)

        # Resolve with "skipped"
        result = await resolve_escalation(
            session,
            escalation.id,
            "skipped",
        )

        # Assert: resolved_at is non-null
        assert result.resolved_at is not None, "resolved_at must be non-null after skip"

        # Assert: resolved_at is valid ISO 8601
        resolved_dt = datetime.fromisoformat(result.resolved_at)
        assert resolved_dt >= before, "resolved_at should be >= time before resolution"

        # Assert: resolution_method is "user_skip"
        assert result.resolution_method == "user_skip", (
            f"Expected resolution_method='user_skip', got '{result.resolution_method}'"
        )

        # Assert: status transitioned to "skipped"
        assert result.status == "skipped", (
            f"Expected status='skipped', got '{result.status}'"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


# ---------------------------------------------------------------------------
# Property 8: Resolution Metadata Completeness — "auto_submitted" path
# ---------------------------------------------------------------------------


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_handle_timeout_sets_metadata(
    freshness_tier: str,
    draft_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending escalation that times out via handle_timeout, resolved_at
    should be non-null and a valid ISO 8601 timestamp, and resolution_method
    should be "auto_submit". The status should transition from "pending" to
    "auto_submitted".

    **Validates: Requirements 7.2**

    Feature: human-in-the-loop-escalation, Property 8: Resolution Metadata Completeness
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-timeout-{uuid.uuid4().hex[:8]}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-timeout",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending escalation
        escalation = _make_pending_escalation(
            job.id, freshness_tier=freshness_tier, draft_answers=draft_answers
        )
        session.add(escalation)
        await session.flush()

        before = datetime.now(tz=UTC)

        # Trigger timeout
        await handle_timeout(session, escalation.id)

        # Refresh to get updated values
        await session.refresh(escalation)

        # Assert: resolved_at is non-null
        assert escalation.resolved_at is not None, (
            "resolved_at must be non-null after timeout"
        )

        # Assert: resolved_at is valid ISO 8601
        resolved_dt = datetime.fromisoformat(escalation.resolved_at)
        assert resolved_dt >= before, "resolved_at should be >= time before timeout"

        # Assert: resolution_method is "auto_submit"
        assert escalation.resolution_method == "auto_submit", (
            f"Expected resolution_method='auto_submit', got '{escalation.resolution_method}'"
        )

        # Assert: status transitioned to "auto_submitted"
        assert escalation.status == "auto_submitted", (
            f"Expected status='auto_submitted', got '{escalation.status}'"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()
