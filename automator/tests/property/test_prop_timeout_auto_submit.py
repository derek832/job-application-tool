"""
Property-based tests for Timeout Handler Auto-Submits.

Uses Hypothesis to verify that handle_timeout correctly transitions pending
human_review escalations to auto_submitted status with proper metadata,
regardless of freshness tier, draft answers content, or creation timestamp.

Properties tested:
- Property 13: Timeout Handler Auto-Submits

Feature: human-in-the-loop-escalation, Property 13: Timeout Handler Auto-Submits
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
from src.pipeline.escalation_engine import handle_timeout


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

freshness_tier_strategy = st.sampled_from(["fresh", "recent", "stale"])

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
        }
    ),
    min_size=1,
    max_size=5,
)

# Generate created_at timestamps in the past (simulating expired timeouts)
# Range: 1 minute ago to 30 days ago
created_at_strategy = st.integers(min_value=1, max_value=43200).map(
    lambda minutes_ago: datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)
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


# ---------------------------------------------------------------------------
# Property 13: Timeout Handler Auto-Submits
# ---------------------------------------------------------------------------


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
    created_at=created_at_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_timeout_sets_status_to_auto_submitted(
    freshness_tier: str,
    draft_answers: list[dict],
    created_at: datetime,
    async_engine,
) -> None:
    """
    For any pending human_review escalation whose timeout_deadline has passed,
    the timeout handler should set status to "auto_submitted".

    **Validates: Requirements 4.4**

    Feature: human-in-the-loop-escalation, Property 13: Timeout Handler Auto-Submits
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job_id = f"job-timeout-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-timeout",
            apply_type="external",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending escalation with expired timeout
        timeout_deadline = created_at + timedelta(minutes=45)
        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps(draft_answers),
            timeout_deadline=timeout_deadline.isoformat(),
            freshness_tier=freshness_tier,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        # Call handle_timeout
        await handle_timeout(session, escalation_id)

        # Verify status
        await session.refresh(escalation)
        assert escalation.status == "auto_submitted", (
            f"Expected status='auto_submitted', got '{escalation.status}' "
            f"for freshness_tier={freshness_tier}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
    created_at=created_at_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_timeout_sets_resolution_method_to_auto_submit(
    freshness_tier: str,
    draft_answers: list[dict],
    created_at: datetime,
    async_engine,
) -> None:
    """
    For any pending human_review escalation whose timeout_deadline has passed,
    the timeout handler should set resolution_method to "auto_submit".

    **Validates: Requirements 4.4**

    Feature: human-in-the-loop-escalation, Property 13: Timeout Handler Auto-Submits
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-timeout-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-timeout",
            apply_type="external",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        timeout_deadline = created_at + timedelta(minutes=45)
        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps(draft_answers),
            timeout_deadline=timeout_deadline.isoformat(),
            freshness_tier=freshness_tier,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        await handle_timeout(session, escalation_id)

        await session.refresh(escalation)
        assert escalation.resolution_method == "auto_submit", (
            f"Expected resolution_method='auto_submit', got '{escalation.resolution_method}' "
            f"for freshness_tier={freshness_tier}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
    created_at=created_at_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_timeout_sets_resolved_at_non_null(
    freshness_tier: str,
    draft_answers: list[dict],
    created_at: datetime,
    async_engine,
) -> None:
    """
    For any pending human_review escalation whose timeout_deadline has passed,
    the timeout handler should set resolved_at to a non-null value.

    **Validates: Requirements 4.4**

    Feature: human-in-the-loop-escalation, Property 13: Timeout Handler Auto-Submits
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-timeout-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-timeout",
            apply_type="external",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        timeout_deadline = created_at + timedelta(minutes=45)
        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps(draft_answers),
            timeout_deadline=timeout_deadline.isoformat(),
            freshness_tier=freshness_tier,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        await handle_timeout(session, escalation_id)

        await session.refresh(escalation)
        assert escalation.resolved_at is not None, (
            f"Expected resolved_at to be non-null after timeout, "
            f"got None for freshness_tier={freshness_tier}"
        )

        # Verify it's a valid ISO 8601 timestamp
        resolved = datetime.fromisoformat(escalation.resolved_at)
        assert resolved.tzinfo is not None, "resolved_at should be timezone-aware"

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()


@given(
    freshness_tier=freshness_tier_strategy,
    draft_answers=draft_answer_strategy,
    created_at=created_at_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_timeout_preserves_draft_answers(
    freshness_tier: str,
    draft_answers: list[dict],
    created_at: datetime,
    async_engine,
) -> None:
    """
    For any pending human_review escalation whose timeout_deadline has passed,
    the timeout handler should preserve draft_answers unchanged (for the
    resume mechanism to use the original drafts).

    **Validates: Requirements 4.4**

    Feature: human-in-the-loop-escalation, Property 13: Timeout Handler Auto-Submits
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job_id = f"job-timeout-{uuid.uuid4().hex[:8]}"
        job = JobRecord(
            id=job_id,
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-timeout",
            apply_type="external",
            status="applying",
            discovered_at=(datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
        session.add(job)
        await session.flush()

        timeout_deadline = created_at + timedelta(minutes=45)
        escalation_id = str(uuid.uuid4())
        original_draft_json = json.dumps(draft_answers)
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=original_draft_json,
            timeout_deadline=timeout_deadline.isoformat(),
            freshness_tier=freshness_tier,
            status="pending",
            resolution_method=None,
            created_at=created_at.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        await handle_timeout(session, escalation_id)

        await session.refresh(escalation)
        assert json.loads(escalation.draft_answers) == draft_answers, (
            f"Expected draft_answers to be preserved after timeout. "
            f"Original: {draft_answers}, "
            f"Got: {json.loads(escalation.draft_answers)}"
        )

        # Cleanup
        await session.delete(escalation)
        await session.delete(job)
        await session.commit()
