"""Unit tests for resolve_escalation function.

Tests the escalation resolution logic including:
- "resolved" resolution: sets status, resolution_method, stores edited answers, sets resolved_at
- "skipped" resolution: sets status, resolution_method, transitions job to "skipped"
- Not found: raises ValueError with "not_found" context
- Already resolved: raises ValueError with "already_resolved" context

Validates: Requirements 6.3, 6.4, 7.2, 8.2
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord, StatusTransition
from src.pipeline.escalation_engine import resolve_escalation


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


@pytest_asyncio.fixture
async def job_record(async_session: AsyncSession) -> JobRecord:
    """Insert and return a sample job record."""
    now = datetime.now(tz=UTC)
    record = JobRecord(
        id="job-resolve-001",
        job_title="Senior Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/job-resolve-001",
        apply_type="external_apply",
        status="applying",
        fit_score=90,
        discovered_at=(now - timedelta(hours=2)).isoformat(),
        updated_at=now.isoformat(),
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest_asyncio.fixture
async def pending_escalation(
    async_session: AsyncSession, job_record: JobRecord
) -> EscalationRecord:
    """Insert and return a pending human_review escalation record."""
    now = datetime.now(tz=UTC)
    record = EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_record.id,
        tier="human_review",
        form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
        draft_answers=json.dumps([
            {
                "field_id": "field_5",
                "question_text": "Why are you interested?",
                "draft_answer": "Original draft answer",
                "edited_answer": None,
            }
        ]),
        timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
        freshness_tier="fresh",
        status="pending",
        resolution_method=None,
        created_at=now.isoformat(),
        resolved_at=None,
    )
    async_session.add(record)
    await async_session.flush()
    return record


# ---------------------------------------------------------------------------
# "resolved" resolution tests
# ---------------------------------------------------------------------------


class TestResolveEscalationResolved:
    """Tests for resolve_escalation with resolution='resolved'."""

    @pytest.mark.asyncio
    async def test_sets_status_to_resolved(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=[{"field_id": "field_5", "edited_answer": "My edited answer"}],
        )
        assert result.status == "resolved"

    @pytest.mark.asyncio
    async def test_sets_resolution_method_user_submit(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=[{"field_id": "field_5", "edited_answer": "My edited answer"}],
        )
        assert result.resolution_method == "user_submit"

    @pytest.mark.asyncio
    async def test_sets_resolved_at_timestamp(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        before = datetime.now(tz=UTC)
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=[{"field_id": "field_5", "edited_answer": "My edited answer"}],
        )
        assert result.resolved_at is not None
        resolved_dt = datetime.fromisoformat(result.resolved_at)
        assert resolved_dt >= before

    @pytest.mark.asyncio
    async def test_stores_edited_answers(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        edited = [{"field_id": "field_5", "edited_answer": "Personalized answer"}]
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=edited,
        )
        stored = json.loads(result.draft_answers)
        assert stored == edited

    @pytest.mark.asyncio
    async def test_resolved_without_edited_answers_keeps_original(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        original_drafts = pending_escalation.draft_answers
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=None,
        )
        # draft_answers should remain unchanged when no edits provided
        assert result.draft_answers == original_drafts

    @pytest.mark.asyncio
    async def test_does_not_transition_job_status(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord, job_record: JobRecord
    ):
        await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=[{"field_id": "field_5", "edited_answer": "answer"}],
        )
        await async_session.refresh(job_record)
        # Job should still be "applying" — not transitioned on submit
        assert job_record.status == "applying"


# ---------------------------------------------------------------------------
# "skipped" resolution tests
# ---------------------------------------------------------------------------


class TestResolveEscalationSkipped:
    """Tests for resolve_escalation with resolution='skipped'."""

    @pytest.mark.asyncio
    async def test_sets_status_to_skipped(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )
        assert result.status == "skipped"

    @pytest.mark.asyncio
    async def test_sets_resolution_method_user_skip(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )
        assert result.resolution_method == "user_skip"

    @pytest.mark.asyncio
    async def test_sets_resolved_at_timestamp(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        before = datetime.now(tz=UTC)
        result = await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )
        assert result.resolved_at is not None
        resolved_dt = datetime.fromisoformat(result.resolved_at)
        assert resolved_dt >= before

    @pytest.mark.asyncio
    async def test_transitions_job_to_skipped(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord, job_record: JobRecord
    ):
        await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )
        await async_session.refresh(job_record)
        assert job_record.status == "skipped"

    @pytest.mark.asyncio
    async def test_sets_job_queue_reason(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord, job_record: JobRecord
    ):
        await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )
        # Check the status transition was recorded with the correct reason
        from sqlalchemy import select

        stmt = select(StatusTransition).where(
            StatusTransition.job_id == job_record.id,
            StatusTransition.to_status == "skipped",
        )
        result = await async_session.execute(stmt)
        transition = result.scalars().first()
        assert transition is not None
        assert transition.reason == "user_skipped_escalation"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestResolveEscalationErrors:
    """Tests for error conditions in resolve_escalation."""

    @pytest.mark.asyncio
    async def test_raises_not_found_for_invalid_id(self, async_session: AsyncSession):
        with pytest.raises(ValueError, match="Escalation not found"):
            await resolve_escalation(
                async_session,
                "nonexistent-id",
                "resolved",
            )

    @pytest.mark.asyncio
    async def test_raises_already_resolved_for_non_pending(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        # First resolve it
        await resolve_escalation(
            async_session,
            pending_escalation.id,
            "resolved",
            edited_answers=[{"field_id": "field_5", "edited_answer": "answer"}],
        )

        # Try to resolve again
        with pytest.raises(ValueError, match="Escalation already resolved"):
            await resolve_escalation(
                async_session,
                pending_escalation.id,
                "skipped",
            )

    @pytest.mark.asyncio
    async def test_raises_already_resolved_for_skipped_status(
        self, async_session: AsyncSession, pending_escalation: EscalationRecord
    ):
        # Skip it first
        await resolve_escalation(
            async_session,
            pending_escalation.id,
            "skipped",
        )

        # Try to resolve again
        with pytest.raises(ValueError, match="Escalation already resolved"):
            await resolve_escalation(
                async_session,
                pending_escalation.id,
                "resolved",
                edited_answers=[{"field_id": "field_5", "edited_answer": "answer"}],
            )
