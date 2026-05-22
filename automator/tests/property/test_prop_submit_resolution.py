"""
Property-based tests for Submit Resolution Stores Edited Answers.

Uses Hypothesis to verify that resolving a pending human_review escalation
via submit correctly sets status, resolution_method, stores edited answers
as JSON in draft_answers, and sets resolved_at to a non-null timestamp.

Properties tested:
- Property 11: Submit Resolution Stores Edited Answers

Feature: human-in-the-loop-escalation, Property 11: Submit Resolution Stores Edited Answers
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
from src.pipeline.escalation_engine import resolve_escalation


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

edited_answer_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "field_id": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            ),
            "edited_answer": st.text(min_size=1, max_size=300),
        }
    ),
    min_size=1,
    max_size=5,
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
# Property 11: Submit Resolution Stores Edited Answers
# ---------------------------------------------------------------------------


@given(edited_answers=edited_answer_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_submit_resolution_sets_status_resolved(
    edited_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending human_review escalation and any set of edited answers,
    resolving via submit should set status="resolved".

    **Validates: Requirements 6.3**

    Feature: human-in-the-loop-escalation, Property 11: Submit Resolution Stores Edited Answers
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-submit-{uuid.uuid4().hex[:8]}",
            job_title="Senior Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-submit",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending human_review escalation
        escalation = EscalationRecord(
            id=str(uuid.uuid4()),
            job_id=job.id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "original"}]),
            timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
            freshness_tier="fresh",
            status="pending",
            resolution_method=None,
            created_at=now.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        # Resolve via submit
        result = await resolve_escalation(
            session,
            escalation.id,
            "resolved",
            edited_answers=edited_answers,
        )

        assert result.status == "resolved"

        # Cleanup
        await session.delete(result)
        await session.delete(job)
        await session.commit()


@given(edited_answers=edited_answer_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_submit_resolution_sets_resolution_method_user_submit(
    edited_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending human_review escalation and any set of edited answers,
    resolving via submit should set resolution_method="user_submit".

    **Validates: Requirements 6.3**

    Feature: human-in-the-loop-escalation, Property 11: Submit Resolution Stores Edited Answers
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-method-{uuid.uuid4().hex[:8]}",
            job_title="Senior Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-method",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation = EscalationRecord(
            id=str(uuid.uuid4()),
            job_id=job.id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "original"}]),
            timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
            freshness_tier="fresh",
            status="pending",
            resolution_method=None,
            created_at=now.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        result = await resolve_escalation(
            session,
            escalation.id,
            "resolved",
            edited_answers=edited_answers,
        )

        assert result.resolution_method == "user_submit"

        # Cleanup
        await session.delete(result)
        await session.delete(job)
        await session.commit()


@given(edited_answers=edited_answer_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_submit_resolution_stores_edited_answers_as_json(
    edited_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending human_review escalation and any set of edited answers,
    resolving via submit should store the edited answers serialized as JSON
    in the draft_answers field.

    **Validates: Requirements 6.3**

    Feature: human-in-the-loop-escalation, Property 11: Submit Resolution Stores Edited Answers
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-store-{uuid.uuid4().hex[:8]}",
            job_title="Senior Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-store",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation = EscalationRecord(
            id=str(uuid.uuid4()),
            job_id=job.id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "original"}]),
            timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
            freshness_tier="fresh",
            status="pending",
            resolution_method=None,
            created_at=now.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        result = await resolve_escalation(
            session,
            escalation.id,
            "resolved",
            edited_answers=edited_answers,
        )

        # The edited answers should be stored as JSON in draft_answers
        stored = json.loads(result.draft_answers)
        assert stored == edited_answers

        # Cleanup
        await session.delete(result)
        await session.delete(job)
        await session.commit()


@given(edited_answers=edited_answer_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_submit_resolution_sets_resolved_at_timestamp(
    edited_answers: list[dict],
    async_engine,
) -> None:
    """
    For any pending human_review escalation and any set of edited answers,
    resolving via submit should set resolved_at to a non-null ISO 8601
    timestamp.

    **Validates: Requirements 6.3**

    Feature: human-in-the-loop-escalation, Property 11: Submit Resolution Stores Edited Answers
    """
    now = datetime.now(tz=UTC)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-ts-{uuid.uuid4().hex[:8]}",
            job_title="Senior Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-ts",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        escalation = EscalationRecord(
            id=str(uuid.uuid4()),
            job_id=job.id,
            tier="human_review",
            form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
            draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "original"}]),
            timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
            freshness_tier="fresh",
            status="pending",
            resolution_method=None,
            created_at=now.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        before = datetime.now(tz=UTC)

        result = await resolve_escalation(
            session,
            escalation.id,
            "resolved",
            edited_answers=edited_answers,
        )

        # resolved_at should be non-null and a valid timestamp
        assert result.resolved_at is not None
        resolved_dt = datetime.fromisoformat(result.resolved_at)
        assert resolved_dt >= before

        # Cleanup
        await session.delete(result)
        await session.delete(job)
        await session.commit()
