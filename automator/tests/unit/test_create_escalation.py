"""Unit tests for create_escalation function.

Tests the escalation record creation logic including:
- CAPTCHA tier: no timeout, no freshness tier
- human_review tier: freshness tier computed, timeout deadline set
- One-pending-per-job uniqueness enforcement
- JSON serialization of form_state_snapshot and draft_answers
- UUID generation and timestamp setting

Validates: Requirements 1.1, 2.1, 2.3, 4.1, 4.2, 4.3, 7.1, 7.5
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import create_escalation
from src.pipeline.notification_service import NotificationSettings


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
    """Insert and return a sample job record discovered 2 hours ago (FRESH)."""
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)
    record = JobRecord(
        id="job-001",
        job_title="Senior Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/job-001",
        apply_type="external_apply",
        status="applying",
        fit_score=90,
        discovered_at=discovered.isoformat(),
        updated_at=now.isoformat(),
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.fixture
def notification_settings() -> NotificationSettings:
    """Return notification settings with all channels disabled (for unit tests)."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=False,
        sms=None,
    )


@pytest.fixture
def sample_form_state() -> dict:
    """Return a sample form state snapshot dict."""
    return {
        "external_url": "https://boards.greenhouse.io/acme/jobs/123",
        "fields": [
            {
                "field_id": "field_1",
                "label": "Full Name",
                "value": "Derek Smith",
                "type": "text",
                "selector": "#first_name",
            }
        ],
        "screenshot_path": "/data/screenshots/test.png",
        "page_title": "Apply - Senior Engineer at Acme Corp",
    }


@pytest.fixture
def sample_draft_answers() -> list[dict]:
    """Return sample draft answers."""
    return [
        {
            "field_id": "field_5",
            "question_text": "Why are you interested in this role?",
            "draft_answer": "I'm drawn to Acme's mission...",
            "edited_answer": None,
        }
    ]


# ---------------------------------------------------------------------------
# CAPTCHA tier tests
# ---------------------------------------------------------------------------


class TestCreateEscalationCaptchaTier:
    """Tests for create_escalation with tier='captcha'."""

    @pytest.mark.asyncio
    async def test_captcha_tier_has_no_timeout(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """CAPTCHA escalations should have timeout_deadline = NULL."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.timeout_deadline is None

    @pytest.mark.asyncio
    async def test_captcha_tier_has_no_freshness_tier(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """CAPTCHA escalations should have freshness_tier = NULL."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.freshness_tier is None

    @pytest.mark.asyncio
    async def test_captcha_tier_sets_status_pending(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """New escalation should have status='pending'."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.status == "pending"

    @pytest.mark.asyncio
    async def test_captcha_tier_draft_answers_null(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """CAPTCHA escalations should have draft_answers = NULL."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.draft_answers is None


# ---------------------------------------------------------------------------
# human_review tier tests
# ---------------------------------------------------------------------------


class TestCreateEscalationHumanReviewTier:
    """Tests for create_escalation with tier='human_review'."""

    @pytest.mark.asyncio
    async def test_human_review_sets_freshness_tier(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
        sample_draft_answers: list[dict],
    ) -> None:
        """human_review escalation should compute freshness tier from discovered_at."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="human_review",
            form_state_snapshot=sample_form_state,
            draft_answers=sample_draft_answers,
            page=None,
            notification_settings=notification_settings,
        )

        # Job was discovered 2 hours ago → FRESH
        assert record.freshness_tier == "fresh"

    @pytest.mark.asyncio
    async def test_human_review_sets_timeout_deadline(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
        sample_draft_answers: list[dict],
    ) -> None:
        """human_review escalation should set a non-null timeout_deadline."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="human_review",
            form_state_snapshot=sample_form_state,
            draft_answers=sample_draft_answers,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.timeout_deadline is not None
        # Parse and verify it's roughly 45 minutes from now (FRESH tier)
        deadline = datetime.fromisoformat(record.timeout_deadline)
        now = datetime.now(tz=UTC)
        diff = deadline - now
        # Should be close to 45 minutes (allow 5 seconds tolerance)
        assert timedelta(minutes=44, seconds=55) < diff < timedelta(minutes=45, seconds=5)

    @pytest.mark.asyncio
    async def test_human_review_serializes_draft_answers(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
        sample_draft_answers: list[dict],
    ) -> None:
        """Draft answers should be serialized as a JSON string."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="human_review",
            form_state_snapshot=sample_form_state,
            draft_answers=sample_draft_answers,
            page=None,
            notification_settings=notification_settings,
        )

        parsed = json.loads(record.draft_answers)
        assert parsed == sample_draft_answers


# ---------------------------------------------------------------------------
# Common behavior tests
# ---------------------------------------------------------------------------


class TestCreateEscalationCommon:
    """Tests for common create_escalation behavior across tiers."""

    @pytest.mark.asyncio
    async def test_generates_uuid4_id(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Escalation ID should be a valid UUID4 string."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        parsed_uuid = uuid.UUID(record.id)
        assert parsed_uuid.version == 4

    @pytest.mark.asyncio
    async def test_sets_created_at_iso8601(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """created_at should be a valid ISO 8601 UTC timestamp."""
        before = datetime.now(tz=UTC)
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )
        after = datetime.now(tz=UTC)

        created = datetime.fromisoformat(record.created_at)
        assert before <= created <= after

    @pytest.mark.asyncio
    async def test_serializes_form_state_snapshot(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """form_state_snapshot should be stored as a JSON string."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        parsed = json.loads(record.form_state_snapshot)
        assert parsed == sample_form_state

    @pytest.mark.asyncio
    async def test_persists_to_database(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Record should be queryable from the database after creation."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        stmt = select(EscalationRecord).where(EscalationRecord.id == record.id)
        result = await async_session.execute(stmt)
        db_record = result.scalars().first()

        assert db_record is not None
        assert db_record.id == record.id
        assert db_record.job_id == job_record.id
        assert db_record.tier == "captcha"
        assert db_record.status == "pending"

    @pytest.mark.asyncio
    async def test_resolved_at_is_null(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """New escalation should have resolved_at = NULL."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.resolved_at is None

    @pytest.mark.asyncio
    async def test_resolution_method_is_null(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """New escalation should have resolution_method = NULL."""
        record = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert record.resolution_method is None


# ---------------------------------------------------------------------------
# Uniqueness enforcement tests
# ---------------------------------------------------------------------------


class TestCreateEscalationUniqueness:
    """Tests for one-pending-per-job uniqueness enforcement."""

    @pytest.mark.asyncio
    async def test_returns_existing_pending_escalation(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """If a pending escalation exists for the job, return it instead of creating new."""
        first = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        second = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert first.id == second.id

    @pytest.mark.asyncio
    async def test_only_one_record_in_db_after_duplicate_attempt(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Only one escalation record should exist after duplicate creation attempt."""
        await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        stmt = select(EscalationRecord).where(EscalationRecord.job_id == job_record.id)
        result = await async_session.execute(stmt)
        records = result.scalars().all()

        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_allows_new_escalation_after_resolved(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """A new escalation can be created if the existing one is no longer pending."""
        first = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        # Simulate resolution
        first.status = "resolved"
        first.resolved_at = datetime.now(tz=UTC).isoformat()
        await async_session.flush()

        second = await create_escalation(
            session=async_session,
            job_record=job_record,
            tier="captcha",
            form_state_snapshot=sample_form_state,
            draft_answers=None,
            page=None,
            notification_settings=notification_settings,
        )

        assert first.id != second.id
        assert second.status == "pending"
