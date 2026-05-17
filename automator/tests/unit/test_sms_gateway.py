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
    """Tests for send_sms Gmail API sending with retries."""

    @pytest.fixture()
    def settings(self) -> SMSSettings:
        """Standard test settings."""
        return SMSSettings(
            gmail_user="test@gmail.com",
            sms_gateway="5551234567@txt.att.net",
        )

    @pytest.mark.asyncio
    @patch("src.integrations.sms_gateway.load_credentials")
    @patch("src.integrations.sms_gateway._gmail_api_send")
    async def test_successful_send_returns_ok(
        self, mock_send: MagicMock, mock_creds: MagicMock, settings: SMSSettings
    ) -> None:
        """A successful Gmail API send returns Result(ok=True)."""
        mock_creds.return_value = MagicMock()
        mock_send.return_value = None  # None means success

        result = await send_sms("Test message", settings)

        assert result.ok is True
        assert result.error is None

    @pytest.mark.asyncio
    @patch("src.integrations.sms_gateway.load_credentials")
    async def test_no_credentials_returns_error(
        self, mock_creds: MagicMock, settings: SMSSettings
    ) -> None:
        """Returns error when OAuth credentials are not configured."""
        mock_creds.return_value = None

        result = await send_sms("Test message", settings)

        assert result.ok is False
        assert "OAuth" in result.error
        assert result.reason == "oauth_not_configured"

    @pytest.mark.asyncio
    @patch("src.integrations.sms_gateway.asyncio.sleep", new_callable=MagicMock)
    @patch("src.integrations.sms_gateway.load_credentials")
    @patch("src.integrations.sms_gateway._gmail_api_send")
    async def test_retries_on_failure(
        self, mock_send: MagicMock, mock_creds: MagicMock, mock_sleep: MagicMock, settings: SMSSettings
    ) -> None:
        """Retries 3 times on Gmail API failure before returning error."""
        from unittest.mock import AsyncMock as AM
        mock_creds.return_value = MagicMock()
        mock_send.return_value = "Gmail API error: 500 Internal Server Error"

        with patch("src.integrations.sms_gateway.asyncio.sleep", new_callable=AM):
            result = await send_sms("Test message", settings)

        assert result.ok is False
        assert result.error is not None

    @pytest.mark.asyncio
    @patch("src.integrations.sms_gateway.load_credentials")
    @patch("src.integrations.sms_gateway._gmail_api_send")
    async def test_succeeds_on_second_attempt(
        self, mock_send: MagicMock, mock_creds: MagicMock, settings: SMSSettings
    ) -> None:
        """Returns ok=True if a retry succeeds."""
        from unittest.mock import AsyncMock as AM
        mock_creds.return_value = MagicMock()
        # First call fails, second succeeds
        mock_send.side_effect = ["Gmail API error: 500", None]

        with patch("src.integrations.sms_gateway.asyncio.sleep", new_callable=AM):
            result = await send_sms("Test message", settings)

        assert result.ok is True
        assert result.error is None
