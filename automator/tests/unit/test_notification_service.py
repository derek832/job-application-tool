"""Unit tests for the refactored notification service (channel router)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord, NotificationLog
from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.integrations.sms_gateway import Result, SMSSettings
from src.pipeline.notification_service import (
    NotificationSettings,
    determine_channel,
    notify,
    send_run_summary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ntfy_settings() -> NtfySettings:
    """Fixture providing test ntfy settings."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6g7h8",
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="test-token-abc123",
    )


@pytest.fixture
def sms_settings() -> SMSSettings:
    """Fixture providing test SMS settings."""
    return SMSSettings(
        gmail_user="test@gmail.com",
        sms_gateway="5551234567@txt.att.net",
    )


@pytest.fixture
def notification_settings_ntfy_only(ntfy_settings: NtfySettings) -> NotificationSettings:
    """Settings with ntfy enabled, SMS disabled."""
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
    """Settings with both ntfy and SMS enabled."""
    return NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=True,
        sms=sms_settings,
    )


@pytest.fixture
def notification_settings_sms_only(sms_settings: SMSSettings) -> NotificationSettings:
    """Settings with ntfy disabled, SMS enabled."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=True,
        sms=sms_settings,
    )


@pytest.fixture
def notification_settings_none() -> NotificationSettings:
    """Settings with both channels disabled."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=False,
        sms=None,
    )


@pytest.fixture
def job_record() -> JobRecord:
    """Fixture providing a test job record."""
    return JobRecord(
        id="12345",
        job_title="Senior Software Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/view/12345",
        apply_type="easy_apply",
        status="scored",
        fit_score=85,
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture providing a mock async session."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# determine_channel tests
# ---------------------------------------------------------------------------


class TestDetermineChannel:
    """Tests for the determine_channel routing logic."""

    def test_ntfy_primary_when_enabled(
        self, notification_settings_both: NotificationSettings
    ) -> None:
        """Ntfy is primary when both are enabled."""
        assert determine_channel(notification_settings_both) == "ntfy"

    def test_sms_when_ntfy_disabled(
        self, notification_settings_sms_only: NotificationSettings
    ) -> None:
        """SMS is used when ntfy is disabled."""
        assert determine_channel(notification_settings_sms_only) == "sms"

    def test_none_when_both_disabled(
        self, notification_settings_none: NotificationSettings
    ) -> None:
        """Returns 'none' when both channels are disabled."""
        assert determine_channel(notification_settings_none) == "none"

    def test_ntfy_enabled_but_no_settings(self) -> None:
        """Returns 'none' when ntfy is enabled but settings are None."""
        settings = NotificationSettings(
            ntfy_enabled=True, ntfy=None, sms_enabled=False, sms=None
        )
        # ntfy_enabled is True but ntfy settings are None — falls through
        assert determine_channel(settings) == "none"

    def test_sms_enabled_but_no_settings(self) -> None:
        """Returns 'none' when sms is enabled but settings are None."""
        settings = NotificationSettings(
            ntfy_enabled=False, ntfy=None, sms_enabled=True, sms=None
        )
        assert determine_channel(settings) == "none"


# ---------------------------------------------------------------------------
# notify() tests — ntfy channel
# ---------------------------------------------------------------------------


class TestNotifyNtfy:
    """Tests for notify() routing to ntfy."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_ntfy_success(
        self,
        mock_rate_limit: AsyncMock,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Successful ntfy delivery logs with channel='ntfy' and success=1."""
        mock_rate_limit.return_value = True
        mock_publish.return_value = NtfyResult(ok=True, status_code=200)

        await notify(mock_session, job_record, "stretch_role", notification_settings_ntfy_only)

        mock_publish.assert_awaited_once()
        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "ntfy"
        assert log_entry.success == 1
        assert log_entry.error_message is None

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.send_sms")
    @patch("src.pipeline.notification_service.publish")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_ntfy_failure_falls_back_to_sms(
        self,
        mock_rate_limit: AsyncMock,
        mock_publish: AsyncMock,
        mock_send_sms: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_both: NotificationSettings,
    ) -> None:
        """When ntfy fails and SMS is configured, falls back to SMS."""
        mock_rate_limit.return_value = True
        mock_publish.return_value = NtfyResult(ok=False, error="server error", status_code=500)
        mock_send_sms.return_value = Result(ok=True)

        await notify(mock_session, job_record, "stretch_role", notification_settings_both)

        mock_publish.assert_awaited_once()
        mock_send_sms.assert_awaited_once()

        # Should log the SMS fallback attempt
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "sms_fallback"
        assert log_entry.success == 1

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_ntfy_failure_no_sms_fallback(
        self,
        mock_rate_limit: AsyncMock,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
    ) -> None:
        """When ntfy fails and SMS is not configured, logs failure."""
        mock_rate_limit.return_value = True
        mock_publish.return_value = NtfyResult(ok=False, error="timeout", status_code=None)

        await notify(mock_session, job_record, "stretch_role", notification_settings_ntfy_only)

        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "ntfy"
        assert log_entry.success == 0
        assert log_entry.error_message == "timeout"


# ---------------------------------------------------------------------------
# notify() tests — SMS channel
# ---------------------------------------------------------------------------


class TestNotifySms:
    """Tests for notify() routing to SMS."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.send_sms")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_sms_success(
        self,
        mock_rate_limit: AsyncMock,
        mock_send_sms: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_sms_only: NotificationSettings,
    ) -> None:
        """Successful SMS delivery logs with channel='sms' and success=1."""
        mock_rate_limit.return_value = True
        mock_send_sms.return_value = Result(ok=True)

        await notify(mock_session, job_record, "stretch_role", notification_settings_sms_only)

        mock_send_sms.assert_awaited_once()
        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "sms"
        assert log_entry.success == 1

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.send_sms")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_sms_failure(
        self,
        mock_rate_limit: AsyncMock,
        mock_send_sms: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_sms_only: NotificationSettings,
    ) -> None:
        """Failed SMS delivery logs with channel='sms' and success=0."""
        mock_rate_limit.return_value = True
        mock_send_sms.return_value = Result(ok=False, error="SMTP refused")

        await notify(mock_session, job_record, "stretch_role", notification_settings_sms_only)

        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "sms"
        assert log_entry.success == 0
        assert log_entry.error_message == "SMTP refused"


# ---------------------------------------------------------------------------
# notify() tests — both channels disabled
# ---------------------------------------------------------------------------


class TestNotifyNone:
    """Tests for notify() when both channels are disabled."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_both_disabled_logs_warning(
        self,
        mock_rate_limit: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_none: NotificationSettings,
    ) -> None:
        """When both channels disabled, logs with channel='none'."""
        mock_rate_limit.return_value = True

        await notify(mock_session, job_record, "stretch_role", notification_settings_none)

        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "none"
        assert log_entry.success == 0
        assert log_entry.error_message == "both_channels_disabled"


# ---------------------------------------------------------------------------
# notify() tests — rate limiting
# ---------------------------------------------------------------------------


class TestNotifyRateLimit:
    """Tests for notify() rate limiting behavior."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_notify_rate_limited(
        self,
        mock_rate_limit: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_both: NotificationSettings,
    ) -> None:
        """Rate-limited notification logs with error_message='rate_limited'."""
        mock_rate_limit.return_value = False

        await notify(mock_session, job_record, "stretch_role", notification_settings_both)

        mock_session.add.assert_called_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.success == 0
        assert log_entry.error_message == "rate_limited"


# ---------------------------------------------------------------------------
# notify() tests — logging completeness
# ---------------------------------------------------------------------------


class TestNotifyLogging:
    """Tests for notification logging completeness."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_log_contains_job_info(
        self,
        mock_rate_limit: AsyncMock,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Log entry contains job title, company, and trigger reason in body."""
        mock_rate_limit.return_value = True
        mock_publish.return_value = NtfyResult(ok=True, status_code=200)

        await notify(mock_session, job_record, "stretch_role", notification_settings_ntfy_only)

        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert "Senior Software Engineer" in log_entry.sms_body
        assert "Acme Corp" in log_entry.sms_body
        assert "stretch_role" in log_entry.sms_body

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    @patch("src.pipeline.notification_service.check_rate_limit")
    async def test_log_sent_at_is_iso8601(
        self,
        mock_rate_limit: AsyncMock,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        job_record: JobRecord,
        notification_settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Log entry sent_at is a valid ISO 8601 timestamp."""
        mock_rate_limit.return_value = True
        mock_publish.return_value = NtfyResult(ok=True, status_code=200)

        await notify(mock_session, job_record, "stretch_role", notification_settings_ntfy_only)

        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert "T" in log_entry.sent_at
        assert "+" in log_entry.sent_at or "Z" in log_entry.sent_at


# ---------------------------------------------------------------------------
# send_run_summary() tests
# ---------------------------------------------------------------------------


class TestSendRunSummary:
    """Tests for the send_run_summary function."""

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    async def test_send_run_summary_success(
        self,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        notification_settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Successful run summary publishes to info topic with priority 3."""
        mock_publish.return_value = NtfyResult(ok=True, status_code=200)

        await send_run_summary(
            mock_session, "Run complete: found 10 jobs.", notification_settings_ntfy_only
        )

        mock_publish.assert_awaited_once()
        payload = mock_publish.call_args[0][0]
        assert payload.topic == "i9j0k1l2m3n4o5p6"
        assert payload.priority == 3
        assert payload.actions is None
        assert "chart_with_upwards_trend" in payload.tags

        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "ntfy"
        assert log_entry.success == 1
        assert log_entry.trigger_reason == "run_summary"

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    async def test_send_run_summary_ntfy_disabled(
        self,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        notification_settings_sms_only: NotificationSettings,
    ) -> None:
        """When ntfy is disabled, run summary is logged but not sent (no SMS fallback)."""
        await send_run_summary(
            mock_session, "Run complete: found 5 jobs.", notification_settings_sms_only
        )

        mock_publish.assert_not_awaited()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "none"
        assert log_entry.success == 0
        assert log_entry.error_message == "ntfy_disabled"

    @pytest.mark.asyncio
    @patch("src.pipeline.notification_service.publish")
    async def test_send_run_summary_publish_failure_no_sms_fallback(
        self,
        mock_publish: AsyncMock,
        mock_session: AsyncMock,
        notification_settings_both: NotificationSettings,
    ) -> None:
        """When ntfy publish fails for run summary, no SMS fallback is attempted."""
        mock_publish.return_value = NtfyResult(ok=False, error="server down", status_code=500)

        await send_run_summary(
            mock_session, "Run complete: found 3 jobs.", notification_settings_both
        )

        mock_publish.assert_awaited_once()
        log_entry: NotificationLog = mock_session.add.call_args[0][0]
        assert log_entry.channel == "ntfy"
        assert log_entry.success == 0
        assert log_entry.error_message == "server down"
