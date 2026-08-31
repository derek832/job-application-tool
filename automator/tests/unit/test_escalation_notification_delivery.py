"""Unit tests for escalation notification delivery wiring.

Tests the notification delivery logic in create_escalation:
- ntfy publish is called after escalation record is persisted
- On ntfy failure, SMS fallback is attempted
- Delivery failures are logged but don't prevent escalation creation
- When ntfy is disabled, notification is skipped gracefully
- Review URL uses lan_base_url when available, else localhost

Validates: Requirements 5.5
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.integrations.sms_gateway import SMSSettings
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
        id="job-notif-001",
        job_title="Backend Developer",
        company="TechCorp",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/job-notif-001",
        external_url="https://boards.greenhouse.io/techcorp/jobs/456",
        apply_type="external_apply",
        status="applying",
        fit_score=92,
        discovered_at=discovered.isoformat(),
        updated_at=now.isoformat(),
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.fixture
def ntfy_settings() -> NtfySettings:
    """Return ntfy settings for testing."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6g7h8",
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="test-token-abc123",
    )


@pytest.fixture
def sms_settings() -> SMSSettings:
    """Return SMS settings for testing."""
    return SMSSettings(
        gmail_user="test@gmail.com",
        sms_gateway="5551234567@vtext.com",
    )


@pytest.fixture
def notification_settings_ntfy_only(ntfy_settings: NtfySettings) -> NotificationSettings:
    """Notification settings with ntfy enabled, SMS disabled."""
    return NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=False,
        sms=None,
    )


@pytest.fixture
def notification_settings_both(
    ntfy_settings: NtfySettings, sms_settings: SMSSettings
) -> NotificationSettings:
    """Notification settings with both ntfy and SMS enabled."""
    return NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=True,
        sms=sms_settings,
    )


@pytest.fixture
def notification_settings_disabled() -> NotificationSettings:
    """Notification settings with all channels disabled."""
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
        "external_url": "https://boards.greenhouse.io/techcorp/jobs/456",
        "fields": [{"field_id": "f1", "label": "Name", "value": "Alex", "type": "text"}],
        "page_title": "Apply - Backend Developer at TechCorp",
    }


@pytest.fixture
def sample_draft_answers() -> list[dict]:
    """Return sample draft answers."""
    return [
        {
            "field_id": "field_5",
            "question_text": "Why are you interested?",
            "draft_answer": "I'm drawn to TechCorp's mission...",
            "edited_answer": None,
        }
    ]


# ---------------------------------------------------------------------------
# Tests: ntfy publish is called on escalation creation
# ---------------------------------------------------------------------------


class TestNtfyPublishCalled:
    """Verify ntfy publish is called after escalation record is persisted."""

    @pytest.mark.asyncio
    async def test_ntfy_publish_called_for_captcha_tier(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """ntfy publish should be called when creating a CAPTCHA escalation."""
        mock_publish = AsyncMock(return_value=NtfyResult(ok=True, status_code=200))

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        assert record.status == "pending"
        mock_publish.assert_called_once()
        payload = mock_publish.call_args[0][0]
        assert payload.topic == "a1b2c3d4e5f6g7h8"
        assert payload.priority == 4

    @pytest.mark.asyncio
    async def test_ntfy_publish_called_for_human_review_tier(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
        sample_draft_answers: list[dict],
    ) -> None:
        """ntfy publish should be called when creating a human_review escalation."""
        mock_publish = AsyncMock(return_value=NtfyResult(ok=True, status_code=200))

        with (
            patch("src.pipeline.escalation_engine.publish", mock_publish),
            patch("src.pipeline.escalation_scheduler.schedule_escalation_timeout"),
        ):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="human_review",
                form_state_snapshot=sample_form_state,
                draft_answers=sample_draft_answers,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        assert record.status == "pending"
        mock_publish.assert_called_once()
        payload = mock_publish.call_args[0][0]
        assert payload.topic == "a1b2c3d4e5f6g7h8"
        assert payload.priority == 3


# ---------------------------------------------------------------------------
# Tests: SMS fallback on ntfy failure
# ---------------------------------------------------------------------------


class TestSmsFallback:
    """Verify SMS fallback is triggered when ntfy fails."""

    @pytest.mark.asyncio
    async def test_sms_fallback_on_ntfy_failure(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_both: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """When ntfy fails after retries, SMS fallback should be attempted."""
        mock_publish = AsyncMock(
            return_value=NtfyResult(ok=False, error="HTTP 500: Server Error", status_code=500)
        )
        mock_send_sms = AsyncMock(return_value=AsyncMock(ok=True))

        with (
            patch("src.pipeline.escalation_engine.publish", mock_publish),
            patch("src.pipeline.escalation_engine.send_sms", mock_send_sms),
        ):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_both,
            )

        # Escalation still created successfully
        assert record.status == "pending"
        assert record.id is not None

        # SMS was called as fallback
        mock_send_sms.assert_called_once()
        sms_body = mock_send_sms.call_args[0][0]
        assert "TechCorp" in sms_body

    @pytest.mark.asyncio
    async def test_no_sms_fallback_when_sms_disabled(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """When ntfy fails and SMS is disabled, no fallback is attempted."""
        mock_publish = AsyncMock(
            return_value=NtfyResult(ok=False, error="HTTP 500: Server Error", status_code=500)
        )
        mock_send_sms = AsyncMock()

        with (
            patch("src.pipeline.escalation_engine.publish", mock_publish),
            patch("src.pipeline.escalation_engine.send_sms", mock_send_sms),
        ):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        # Escalation still created
        assert record.status == "pending"
        # SMS was NOT called
        mock_send_sms.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Notification failure doesn't prevent escalation creation
# ---------------------------------------------------------------------------


class TestNotificationFailureIsolation:
    """Verify notification failures don't prevent escalation creation."""

    @pytest.mark.asyncio
    async def test_escalation_created_despite_ntfy_failure(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Escalation record is persisted even when ntfy publish fails."""
        mock_publish = AsyncMock(
            return_value=NtfyResult(ok=False, error="Network error", status_code=None)
        )

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        assert record is not None
        assert record.status == "pending"
        assert record.id is not None

    @pytest.mark.asyncio
    async def test_escalation_created_despite_unexpected_exception(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Escalation record is persisted even when notification raises an exception."""
        mock_publish = AsyncMock(side_effect=RuntimeError("Unexpected crash"))

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        assert record is not None
        assert record.status == "pending"


# ---------------------------------------------------------------------------
# Tests: Notification skipped when ntfy disabled
# ---------------------------------------------------------------------------


class TestNotificationSkipped:
    """Verify notification is skipped gracefully when ntfy is disabled."""

    @pytest.mark.asyncio
    async def test_no_publish_when_ntfy_disabled(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_disabled: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """No ntfy publish attempt when ntfy is disabled."""
        mock_publish = AsyncMock()

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_disabled,
            )

        assert record.status == "pending"
        mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Review URL construction
# ---------------------------------------------------------------------------


class TestReviewUrlConstruction:
    """Verify review URL uses lan_base_url when available."""

    @pytest.mark.asyncio
    async def test_review_url_uses_lan_base_url(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
        sample_form_state: dict,
    ) -> None:
        """Review URL in notification should use lan_base_url from settings."""
        mock_publish = AsyncMock(return_value=NtfyResult(ok=True, status_code=200))

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=notification_settings_ntfy_only,
            )

        payload = mock_publish.call_args[0][0]
        assert payload.actions is not None
        assert len(payload.actions) == 1
        review_action = payload.actions[0]
        assert review_action.label == "Review"
        assert f"http://192.168.1.100:7432/escalations/{record.id}" == review_action.url

    @pytest.mark.asyncio
    async def test_review_url_falls_back_to_localhost(
        self,
        async_session: AsyncSession,
        job_record: JobRecord,
        sample_form_state: dict,
    ) -> None:
        """Review URL should use localhost:3000 when lan_base_url is None."""
        ntfy_settings_no_lan = NtfySettings(
            server_url="https://ntfy.sh",
            urgent_topic="a1b2c3d4e5f6g7h8",
            info_topic="i9j0k1l2m3n4o5p6",
            lan_base_url=None,
            api_token="test-token",
        )
        settings = NotificationSettings(
            ntfy_enabled=True,
            ntfy=ntfy_settings_no_lan,
            sms_enabled=False,
            sms=None,
        )

        mock_publish = AsyncMock(return_value=NtfyResult(ok=True, status_code=200))

        with patch("src.pipeline.escalation_engine.publish", mock_publish):
            record = await create_escalation(
                session=async_session,
                job_record=job_record,
                tier="captcha",
                form_state_snapshot=sample_form_state,
                draft_answers=None,
                page=None,
                notification_settings=settings,
            )

        payload = mock_publish.call_args[0][0]
        assert payload.actions is not None
        review_action = payload.actions[0]
        assert f"http://localhost:3000/escalations/{record.id}" == review_action.url
