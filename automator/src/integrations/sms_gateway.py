"""SMS gateway client for sending notifications via Gmail API email-to-SMS.

Uses the Gmail API with OAuth2 to send messages through the carrier's
email-to-SMS gateway address (e.g., 5307558669@vtext.com).

OAuth2 credentials are managed by gmail_oauth.py — the access token is
refreshed automatically using the stored refresh token.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from email.message import EmailMessage

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.integrations.gmail_oauth import load_credentials

logger = structlog.get_logger(__name__)

SMS_MAX_LENGTH = 160
ACTION_PROMPT = "Open extension to review"
MAX_RETRIES = 3
RETRY_DELAYS_SECONDS = [5, 15, 30]


@dataclass
class Result:
    """Outcome of an SMS send operation.

    Attributes:
        ok: True if the message was sent successfully.
        error: Description of the failure, or None on success.
        reason: Optional categorized reason for the failure.
    """

    ok: bool
    error: str | None = None
    reason: str | None = None


@dataclass
class SMSSettings:
    """Settings required to send an SMS via Gmail API.

    Attributes:
        gmail_user: The Gmail/Workspace address used as the sender.
        sms_gateway: The carrier email-to-SMS gateway address
            (e.g., 5307558669@vtext.com).
    """

    gmail_user: str
    sms_gateway: str


def compose_sms(job_title: str, company: str, trigger_reason: str) -> str:
    """Compose an SMS message containing job info and an action prompt.

    Builds a message with the job title, company name, trigger reason, and a
    fixed action prompt. Truncates the result to 160 characters to ensure
    single-message delivery.

    Args:
        job_title: The title of the job posting.
        company: The company name.
        trigger_reason: Brief description of why the notification was triggered.

    Returns:
        A string of at most 160 characters containing all three fields and an action prompt.
    """
    full_message = f"{job_title} @ {company}: {trigger_reason}. {ACTION_PROMPT}"
    if len(full_message) <= SMS_MAX_LENGTH:
        return full_message

    # Truncate while preserving the action prompt suffix
    suffix = f"... {ACTION_PROMPT}"
    available = SMS_MAX_LENGTH - len(suffix)
    prefix = f"{job_title} @ {company}: {trigger_reason}"
    truncated = prefix[:available] + suffix
    return truncated


async def send_sms(body: str, settings: SMSSettings) -> Result:
    """Send an SMS message via Gmail API to the configured carrier gateway.

    Uses OAuth2 credentials (loaded from disk) to authenticate with the Gmail
    API. Retries up to 3 times with [5s, 15s, 30s] backoff on failure.
    Logs each attempt with structlog. Never logs secret values.

    Args:
        body: The SMS message body to send.
        settings: Gmail user and gateway address.

    Returns:
        A Result indicating success or failure with an error description.
    """
    creds = load_credentials()
    if creds is None:
        logger.error("sms_send_failed_no_oauth_credentials")
        return Result(
            ok=False,
            error="Gmail OAuth credentials not configured. Run authorization flow.",
            reason="oauth_not_configured",
        )

    msg = EmailMessage()
    msg["From"] = settings.gmail_user
    msg["To"] = settings.sms_gateway
    msg["Subject"] = ""
    msg.set_content(body)

    # Encode the message for the Gmail API
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.debug(
            "sms_send_attempt",
            attempt=attempt,
            max_retries=MAX_RETRIES,
            gateway=settings.sms_gateway,
            gmail_user=settings.gmail_user,
        )
        try:
            # Run the synchronous Gmail API call in an executor to avoid
            # blocking the async event loop.
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                _gmail_api_send,
                creds,
                raw_message,
            )
            if result is None:
                logger.debug("sms_sent_successfully", attempt=attempt)
                return Result(ok=True)
            else:
                last_error = result

        except Exception as exc:
            last_error = str(exc)

        logger.warning(
            "sms_send_failed",
            attempt=attempt,
            max_retries=MAX_RETRIES,
            error=last_error,
        )
        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt - 1])

    logger.error(
        "sms_send_exhausted",
        max_retries=MAX_RETRIES,
        error=last_error,
        gateway=settings.sms_gateway,
    )
    return Result(ok=False, error=last_error)


def _gmail_api_send(creds, raw_message: str) -> str | None:
    """Send an email via the Gmail API (synchronous, run in executor).

    Args:
        creds: Valid OAuth2 credentials.
        raw_message: Base64url-encoded email message.

    Returns:
        None on success, or an error string on failure.
    """
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        service.users().messages().send(
            userId="me",
            body={"raw": raw_message},
        ).execute()
        return None
    except HttpError as exc:
        return f"Gmail API error: {exc.status_code} {exc.reason}"
    except Exception as exc:
        return f"Gmail send error: {exc}"
