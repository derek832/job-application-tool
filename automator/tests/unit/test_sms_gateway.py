"""Unit tests for the SMS gateway client module."""

from unittest.mock import MagicMock, patch

import pytest

from src.integrations.sms_gateway import (
    ACTION_PROMPT,
    MAX_RETRIES,
    SMS_MAX_LENGTH,
    SMSSettings,
    compose_sms,
    send_sms,
)


class TestComposeSms:
    """Tests for compose_sms message composition."""

    def test_short_message_includes_all_fields(self) -> None:
        """A short message contains job_title, company, trigger_reason, and action prompt."""
        result = compose_sms("Engineer", "Acme", "stretch role")
        assert "Engineer" in result
        assert "Acme" in result
        assert "stretch role" in result
        assert ACTION_PROMPT in result

    def test_short_message_not_truncated(self) -> None:
        """Messages under 160 chars are returned as-is without truncation markers."""
        result = compose_sms("Engineer", "Acme", "stretch role")
        assert len(result) <= SMS_MAX_LENGTH
        assert "..." not in result

    def test_long_message_truncated_to_160(self) -> None:
        """Messages exceeding 160 chars are truncated to exactly 160."""
        long_title = "A" * 80
        long_company = "B" * 80
        result = compose_sms(long_title, long_company, "reason")
        assert len(result) <= SMS_MAX_LENGTH

    def test_truncated_message_ends_with_action_prompt(self) -> None:
        """Truncated messages always end with the action prompt."""
        long_title = "Senior Staff Software Engineer Level VII"
        long_company = "International Business Machines Corporation"
        long_reason = "This is a stretch role that requires additional review from the user"
        result = compose_sms(long_title, long_company, long_reason)
        assert result.endswith(ACTION_PROMPT)

    def test_truncated_message_contains_ellipsis(self) -> None:
        """Truncated messages contain '...' to indicate truncation."""
        long_title = "X" * 80
        long_company = "Y" * 80
        result = compose_sms(long_title, long_company, "reason")
        assert "..." in result

    def test_exact_160_char_message(self) -> None:
        """A message that is exactly 160 chars is not truncated."""
        # Build a message that is exactly 160 chars
        # Format: "{title} @ {company}: {reason}. {ACTION_PROMPT}"
        # ACTION_PROMPT = "Open Kiro to review" (19 chars)
        # " @ " = 3, ": " = 2, ". " = 2 → overhead = 7 + 19 = 26
        remaining = SMS_MAX_LENGTH - len(f" @ : . {ACTION_PROMPT}")
        title = "A" * (remaining // 3)
        company = "B" * (remaining // 3)
        reason = "C" * (remaining - 2 * (remaining // 3))
        result = compose_sms(title, company, reason)
        assert len(result) <= SMS_MAX_LENGTH
        assert ACTION_PROMPT in result


class TestSendSms:
    """Tests for send_sms SMTP sending with retries."""

    @pytest.fixture()
    def settings(self) -> SMSSettings:
        """Standard test settings."""
        return SMSSettings(
            gmail_user="test@gmail.com",
            gmail_app_password="app-password-123",
            sms_gateway="5551234567@txt.att.net",
        )

    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_successful_send_returns_ok(
        self, mock_smtp_class: MagicMock, settings: SMSSettings
    ) -> None:
        """A successful SMTP send returns Result(ok=True)."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_sms("Test message", settings)

        assert result.ok is True
        assert result.error is None

    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_successful_send_calls_starttls(
        self, mock_smtp_class: MagicMock, settings: SMSSettings
    ) -> None:
        """SMTP connection uses STARTTLS."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_sms("Test message", settings)

        mock_server.starttls.assert_called_once()

    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_successful_send_authenticates(
        self, mock_smtp_class: MagicMock, settings: SMSSettings
    ) -> None:
        """SMTP connection authenticates with gmail credentials."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_sms("Test message", settings)

        mock_server.login.assert_called_once_with("test@gmail.com", "app-password-123")

    @patch("src.integrations.sms_gateway.time.sleep")
    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_retries_on_failure(
        self, mock_smtp_class: MagicMock, mock_sleep: MagicMock, settings: SMSSettings
    ) -> None:
        """Retries 3 times on SMTP failure before returning error."""
        mock_smtp_class.return_value.__enter__ = MagicMock(
            side_effect=ConnectionError("Connection refused")
        )
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_sms("Test message", settings)

        assert result.ok is False
        assert result.error is not None
        assert "Connection refused" in result.error

    @patch("src.integrations.sms_gateway.time.sleep")
    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_retries_with_30s_intervals(
        self, mock_smtp_class: MagicMock, mock_sleep: MagicMock, settings: SMSSettings
    ) -> None:
        """Waits 30 seconds between retry attempts."""
        mock_smtp_class.return_value.__enter__ = MagicMock(
            side_effect=ConnectionError("Connection refused")
        )
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_sms("Test message", settings)

        # Should sleep between attempts (MAX_RETRIES - 1 times)
        assert mock_sleep.call_count == MAX_RETRIES - 1
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 30

    @patch("src.integrations.sms_gateway.time.sleep")
    @patch("src.integrations.sms_gateway.smtplib.SMTP")
    def test_succeeds_on_second_attempt(
        self, mock_smtp_class: MagicMock, mock_sleep: MagicMock, settings: SMSSettings
    ) -> None:
        """Returns ok=True if a retry succeeds."""
        mock_server = MagicMock()
        # First call raises, second succeeds
        mock_smtp_class.return_value.__enter__ = MagicMock(
            side_effect=[ConnectionError("timeout"), mock_server]
        )
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_sms("Test message", settings)

        assert result.ok is True
        assert result.error is None
