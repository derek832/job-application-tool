"""Unit tests for the notification service module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord, NotificationLog
from src.integrations.sms_gateway import Result, SMSSettings
from src.pipeline.notification_service import notify


@pytest.fixture
def sms_settings() -> SMSSettings:
    """Fixture providing test SMS settings."""
    return SMSSettings(
        gmail_user="test@gmail.com",
        gmail_app_password="app-password",
        sms_gateway="5551234567@txt.att.net",
    )


@pytest.fixture
def job_record() -> JobRecord:
    """Fixture providing a test job record."""
    record = JobRecord(
        id="12345",
        job_title="Senior Software Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/view/12345",
        apply_type="easy_apply",
        status="scored",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )
    return record


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture providing a mock async session."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_success(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test successful notification delivery writes a log row with success=1."""
    mock_check_rate_limit.return_value = True
    mock_send_sms.return_value = Result(ok=True)

    await notify(mock_session, job_record, "stretch_role", sms_settings)

    mock_check_rate_limit.assert_awaited_once_with(mock_session)
    mock_send_sms.assert_called_once()

    # Verify a NotificationLog was added to the session
    mock_session.add.assert_called_once()
    log_entry: NotificationLog = mock_session.add.call_args[0][0]
    assert isinstance(log_entry, NotificationLog)
    assert log_entry.job_id == "12345"
    assert log_entry.trigger_reason == "stretch_role"
    assert log_entry.success == 1
    assert log_entry.error_message is None
    assert log_entry.sent_at is not None
    assert "Senior Software Engineer" in log_entry.sms_body
    assert "Acme Corp" in log_entry.sms_body

    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_send_failure(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test failed SMS delivery writes a log row with success=0 and error message."""
    mock_check_rate_limit.return_value = True
    mock_send_sms.return_value = Result(ok=False, error="SMTP connection refused")

    await notify(mock_session, job_record, "captcha_detected", sms_settings)

    mock_check_rate_limit.assert_awaited_once_with(mock_session)
    mock_send_sms.assert_called_once()

    mock_session.add.assert_called_once()
    log_entry: NotificationLog = mock_session.add.call_args[0][0]
    assert isinstance(log_entry, NotificationLog)
    assert log_entry.job_id == "12345"
    assert log_entry.trigger_reason == "captcha_detected"
    assert log_entry.success == 0
    assert log_entry.error_message == "SMTP connection refused"

    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_rate_limited(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test rate-limited notification skips send and logs with error_message='rate_limited'."""
    mock_check_rate_limit.return_value = False

    await notify(mock_session, job_record, "score_at_threshold_boundary", sms_settings)

    mock_check_rate_limit.assert_awaited_once_with(mock_session)
    mock_send_sms.assert_not_called()

    mock_session.add.assert_called_once()
    log_entry: NotificationLog = mock_session.add.call_args[0][0]
    assert isinstance(log_entry, NotificationLog)
    assert log_entry.job_id == "12345"
    assert log_entry.trigger_reason == "score_at_threshold_boundary"
    assert log_entry.success == 0
    assert log_entry.error_message == "rate_limited"
    assert log_entry.sms_body != ""

    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_always_writes_log(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test that a log row is always written regardless of outcome."""
    # Test with success
    mock_check_rate_limit.return_value = True
    mock_send_sms.return_value = Result(ok=True)
    await notify(mock_session, job_record, "stretch_role", sms_settings)
    assert mock_session.add.call_count == 1
    assert mock_session.flush.await_count == 1

    mock_session.reset_mock()

    # Test with failure
    mock_send_sms.return_value = Result(ok=False, error="timeout")
    await notify(mock_session, job_record, "stretch_role", sms_settings)
    assert mock_session.add.call_count == 1
    assert mock_session.flush.await_count == 1

    mock_session.reset_mock()

    # Test with rate limit
    mock_check_rate_limit.return_value = False
    await notify(mock_session, job_record, "stretch_role", sms_settings)
    assert mock_session.add.call_count == 1
    assert mock_session.flush.await_count == 1


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_sms_body_contains_job_info(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test that the composed SMS body contains job title, company, and trigger reason."""
    mock_check_rate_limit.return_value = True
    mock_send_sms.return_value = Result(ok=True)

    await notify(mock_session, job_record, "stretch_role", sms_settings)

    log_entry: NotificationLog = mock_session.add.call_args[0][0]
    assert "Senior Software Engineer" in log_entry.sms_body
    assert "Acme Corp" in log_entry.sms_body
    assert "stretch_role" in log_entry.sms_body


@pytest.mark.asyncio
@patch("src.pipeline.notification_service.check_rate_limit")
@patch("src.pipeline.notification_service.send_sms")
async def test_notify_sent_at_is_iso8601(
    mock_send_sms: MagicMock,
    mock_check_rate_limit: AsyncMock,
    mock_session: AsyncMock,
    job_record: JobRecord,
    sms_settings: SMSSettings,
) -> None:
    """Test that sent_at is a valid ISO 8601 timestamp."""
    mock_check_rate_limit.return_value = True
    mock_send_sms.return_value = Result(ok=True)

    await notify(mock_session, job_record, "stretch_role", sms_settings)

    log_entry: NotificationLog = mock_session.add.call_args[0][0]
    # ISO 8601 format should contain 'T' separator and timezone info
    assert "T" in log_entry.sent_at
    assert "+" in log_entry.sent_at or "Z" in log_entry.sent_at
