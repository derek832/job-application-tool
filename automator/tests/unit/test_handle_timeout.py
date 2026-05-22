"""Unit tests for the handle_timeout function in the Escalation Engine.

Tests cover:
- Happy path: pending escalation gets auto-submitted
- No-op when already resolved
- No-op when escalation not found
- Correct metadata (status, resolution_method, resolved_at)

Validates: Requirements 4.4, 4.6
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import handle_timeout


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
async def sample_job_record(async_session: AsyncSession) -> JobRecord:
    """Insert and return a sample job record for escalation tests."""
    record = JobRecord(
        id="job-timeout-001",
        job_title="Senior Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/12345",
        apply_type="external",
        status="applying",
        description_text="We need a senior engineer.",
        discovered_at=(datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    async_session.add(record)
    await async_session.flush()
    return record


def _make_pending_escalation(
    job_id: str,
    *,
    escalation_id: str | None = None,
    tier: str = "human_review",
    freshness_tier: str = "fresh",
    draft_answers: list[dict] | None = None,
    created_minutes_ago: int = 45,
) -> EscalationRecord:
    """Helper to create a pending escalation record for testing."""
    created_at = datetime.now(tz=UTC) - timedelta(minutes=created_minutes_ago)
    timeout_deadline = created_at + timedelta(minutes=45)

    if draft_answers is None:
        draft_answers = [
            {
                "field_id": "field_5",
                "question_text": "Why are you interested?",
                "draft_answer": "I'm drawn to Acme's mission...",
            }
        ]

    return EscalationRecord(
        id=escalation_id or str(uuid.uuid4()),
        job_id=job_id,
        tier=tier,
        form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
        draft_answers=json.dumps(draft_answers),
        timeout_deadline=timeout_deadline.isoformat(),
        freshness_tier=freshness_tier,
        status="pending",
        resolution_method=None,
        created_at=created_at.isoformat(),
        resolved_at=None,
    )


# ---------------------------------------------------------------------------
# Happy path: pending escalation gets auto-submitted
# ---------------------------------------------------------------------------


class TestHandleTimeoutHappyPath:
    """Test that a pending escalation is correctly auto-submitted on timeout."""

    @pytest.mark.asyncio
    async def test_pending_escalation_transitions_to_auto_submitted(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """A pending escalation should transition to auto_submitted status."""
        escalation = _make_pending_escalation(sample_job_record.id)
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "auto_submitted"

    @pytest.mark.asyncio
    async def test_resolution_method_set_to_auto_submit(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Resolution method should be set to 'auto_submit'."""
        escalation = _make_pending_escalation(sample_job_record.id)
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.resolution_method == "auto_submit"

    @pytest.mark.asyncio
    async def test_resolved_at_is_set(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """resolved_at should be set to a valid ISO 8601 timestamp."""
        escalation = _make_pending_escalation(sample_job_record.id)
        async_session.add(escalation)
        await async_session.flush()

        before = datetime.now(tz=UTC)
        await handle_timeout(async_session, escalation.id)
        after = datetime.now(tz=UTC)

        await async_session.refresh(escalation)
        assert escalation.resolved_at is not None

        resolved = datetime.fromisoformat(escalation.resolved_at)
        assert before <= resolved <= after

    @pytest.mark.asyncio
    async def test_draft_answers_preserved(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Draft answers should remain unchanged after auto-submit."""
        original_drafts = [
            {"field_id": "q1", "question_text": "Tell us about yourself", "draft_answer": "I am..."}
        ]
        escalation = _make_pending_escalation(
            sample_job_record.id, draft_answers=original_drafts
        )
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert json.loads(escalation.draft_answers) == original_drafts


# ---------------------------------------------------------------------------
# No-op when already resolved
# ---------------------------------------------------------------------------


class TestHandleTimeoutAlreadyResolved:
    """Test that handle_timeout is a no-op when escalation is already resolved."""

    @pytest.mark.asyncio
    async def test_noop_when_status_is_resolved(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Should not modify an escalation that is already 'resolved'."""
        escalation = _make_pending_escalation(sample_job_record.id)
        escalation.status = "resolved"
        escalation.resolution_method = "user_submit"
        escalation.resolved_at = datetime.now(tz=UTC).isoformat()
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "resolved"
        assert escalation.resolution_method == "user_submit"

    @pytest.mark.asyncio
    async def test_noop_when_status_is_skipped(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Should not modify an escalation that is already 'skipped'."""
        escalation = _make_pending_escalation(sample_job_record.id)
        escalation.status = "skipped"
        escalation.resolution_method = "user_skip"
        escalation.resolved_at = datetime.now(tz=UTC).isoformat()
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "skipped"
        assert escalation.resolution_method == "user_skip"

    @pytest.mark.asyncio
    async def test_noop_when_status_is_auto_submitted(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Should not modify an escalation that is already 'auto_submitted'."""
        escalation = _make_pending_escalation(sample_job_record.id)
        escalation.status = "auto_submitted"
        escalation.resolution_method = "auto_submit"
        original_resolved_at = datetime.now(tz=UTC).isoformat()
        escalation.resolved_at = original_resolved_at
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "auto_submitted"
        assert escalation.resolved_at == original_resolved_at

    @pytest.mark.asyncio
    async def test_noop_when_status_is_expired(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Should not modify an escalation that is already 'expired'."""
        escalation = _make_pending_escalation(sample_job_record.id)
        escalation.status = "expired"
        escalation.resolution_method = "timeout_expired"
        escalation.resolved_at = datetime.now(tz=UTC).isoformat()
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "expired"
        assert escalation.resolution_method == "timeout_expired"


# ---------------------------------------------------------------------------
# No-op when escalation not found
# ---------------------------------------------------------------------------


class TestHandleTimeoutNotFound:
    """Test that handle_timeout is a no-op when escalation ID doesn't exist."""

    @pytest.mark.asyncio
    async def test_noop_when_id_not_found(self, async_session: AsyncSession) -> None:
        """Should return without error when escalation ID doesn't exist."""
        nonexistent_id = str(uuid.uuid4())

        # Should not raise
        await handle_timeout(async_session, nonexistent_id)

    @pytest.mark.asyncio
    async def test_noop_with_empty_string_id(self, async_session: AsyncSession) -> None:
        """Should return without error when given an empty string ID."""
        await handle_timeout(async_session, "")


# ---------------------------------------------------------------------------
# Correct metadata verification
# ---------------------------------------------------------------------------


class TestHandleTimeoutMetadata:
    """Test that all metadata fields are correctly set after auto-submit."""

    @pytest.mark.asyncio
    async def test_all_metadata_fields_correct(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Verify status, resolution_method, and resolved_at are all set correctly."""
        escalation = _make_pending_escalation(
            sample_job_record.id, freshness_tier="recent", created_minutes_ago=360
        )
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "auto_submitted"
        assert escalation.resolution_method == "auto_submit"
        assert escalation.resolved_at is not None
        # Freshness tier should remain unchanged
        assert escalation.freshness_tier == "recent"
        # Other fields should remain unchanged
        assert escalation.tier == "human_review"
        assert escalation.job_id == sample_job_record.id

    @pytest.mark.asyncio
    async def test_resolved_at_is_utc_iso8601(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """resolved_at should be a valid UTC ISO 8601 timestamp."""
        escalation = _make_pending_escalation(sample_job_record.id)
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        resolved = datetime.fromisoformat(escalation.resolved_at)
        assert resolved.tzinfo is not None

    @pytest.mark.asyncio
    async def test_stale_freshness_tier_auto_submits(
        self, async_session: AsyncSession, sample_job_record: JobRecord
    ) -> None:
        """Escalations with stale freshness tier should also auto-submit correctly."""
        escalation = _make_pending_escalation(
            sample_job_record.id, freshness_tier="stale", created_minutes_ago=1440
        )
        async_session.add(escalation)
        await async_session.flush()

        await handle_timeout(async_session, escalation.id)

        await async_session.refresh(escalation)
        assert escalation.status == "auto_submitted"
        assert escalation.freshness_tier == "stale"
