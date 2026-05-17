"""Notification service — channel router for the LinkedIn Job Automator.

Routes notifications through the configured channel(s): ntfy (primary) or
SMS (fallback). Enforces the shared rate limit, logs every attempt to the
``notification_log`` table, and handles fallback on ntfy failure.

Every notification attempt — whether successful, failed, or rate-limited —
is recorded in the database for auditability and rate-limit enforcement.

Validates: Requirements 8.1, 8.2, 8.3, 8.5, 9.3
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord, NotificationLog
from src.integrations.ntfy_client import NtfyPayload, NtfyResult, NtfySettings, publish
from src.integrations.sms_gateway import SMSSettings, compose_sms, send_sms
from src.integrations.sms_rate_limiter import check_rate_limit

logger = structlog.get_logger(__name__)


@dataclass
class NotificationSettings:
    """Unified notification configuration combining ntfy and SMS settings.

    Attributes:
        ntfy_enabled: Whether ntfy push notifications are active.
        ntfy: Ntfy server/topic configuration, or None if not configured.
        sms_enabled: Whether SMS notifications are active.
        sms: SMS gateway configuration, or None if not configured.
    """

    ntfy_enabled: bool
    ntfy: NtfySettings | None
    sms_enabled: bool
    sms: SMSSettings | None


def determine_channel(settings: NotificationSettings) -> str:
    """Determine which notification channel to use.

    Priority:
    1. ntfy (if enabled and settings present)
    2. SMS (if enabled and settings present)
    3. none (both disabled or unconfigured)

    Args:
        settings: The unified notification settings.

    Returns:
        One of "ntfy", "sms", or "none".
    """
    if settings.ntfy_enabled and settings.ntfy is not None:
        return "ntfy"
    elif settings.sms_enabled and settings.sms is not None:
        return "sms"
    else:
        return "none"


async def _log_attempt(
    session: AsyncSession,
    *,
    job_id: str | None,
    trigger_reason: str,
    body: str,
    channel: str,
    success: int,
    error_message: str | None,
) -> None:
    """Write a notification attempt to the notification_log table.

    Args:
        session: Active async database session.
        job_id: The job record ID, or None for non-job notifications.
        trigger_reason: Why the notification was triggered.
        body: The notification message body.
        channel: The delivery channel used (ntfy, sms, sms_fallback, none).
        success: 1 if delivered successfully, 0 otherwise.
        error_message: Error detail when success is 0.
    """
    log_entry = NotificationLog(
        job_id=job_id,
        trigger_reason=trigger_reason,
        sms_body=body,
        sent_at=datetime.now(tz=UTC).isoformat(),
        success=success,
        error_message=error_message,
        channel=channel,
    )
    session.add(log_entry)
    await session.flush()


async def notify(
    session: AsyncSession,
    job_record: JobRecord,
    trigger_reason: str,
    settings: NotificationSettings,
) -> None:
    """Route a notification through the configured channel(s).

    Flow:
    1. Check the shared rate limit — if exceeded, log and return.
    2. Determine the primary channel via ``determine_channel()``.
    3. If ntfy: publish to urgent topic. On failure after retries, fall back
       to SMS if configured.
    4. If SMS: send via the SMS gateway.
    5. If none: log a warning and skip delivery.

    Every attempt is logged to ``notification_log`` with the channel field.

    Args:
        session: Active async database session.
        job_record: The job record that triggered the notification.
        trigger_reason: The notification trigger condition.
        settings: Unified notification settings (ntfy + SMS).
    """
    # Compose a message body for logging purposes (used regardless of channel)
    body = compose_sms(
        job_record.job_title,
        job_record.company,
        trigger_reason,
        job_record.fit_score,
    )

    # Step 1: Check rate limit
    allowed = await check_rate_limit(session)

    if not allowed:
        logger.warning(
            "notification_rate_limited",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        await _log_attempt(
            session,
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            body=body,
            channel=determine_channel(settings),
            success=0,
            error_message="rate_limited",
        )
        return

    # Step 2: Determine channel
    channel = determine_channel(settings)

    # Step 3: Route to appropriate channel
    if channel == "ntfy":
        await _send_via_ntfy(
            session=session,
            job_record=job_record,
            trigger_reason=trigger_reason,
            body=body,
            settings=settings,
        )
    elif channel == "sms":
        await _send_via_sms(
            session=session,
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            body=body,
            sms_settings=settings.sms,
            channel="sms",
        )
    else:
        # Both channels disabled
        logger.warning(
            "notification_both_channels_disabled",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        await _log_attempt(
            session,
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            body=body,
            channel="none",
            success=0,
            error_message="both_channels_disabled",
        )


async def _send_via_ntfy(
    session: AsyncSession,
    *,
    job_record: JobRecord,
    trigger_reason: str,
    body: str,
    settings: NotificationSettings,
) -> None:
    """Attempt ntfy delivery with SMS fallback on failure.

    Args:
        session: Active async database session.
        job_record: The job record that triggered the notification.
        trigger_reason: The notification trigger condition.
        body: The composed message body.
        settings: Unified notification settings.
    """
    assert settings.ntfy is not None  # Guaranteed by determine_channel

    # Build the ntfy payload for urgent notifications
    score_str = f" ({job_record.fit_score}%)" if job_record.fit_score is not None else ""
    message = f"{job_record.job_title} @ {job_record.company}{score_str}: {trigger_reason}"

    from src.integrations.ntfy_client import NtfyAction

    actions: list[NtfyAction] | None = None
    if job_record.queue_reason is not None and settings.ntfy.lan_base_url:
        actions = [
            NtfyAction(
                action="http",
                label="Approve",
                url=f"{settings.ntfy.lan_base_url}/queue/{job_record.id}/approve",
                method="POST",
                headers={"Authorization": f"Bearer {settings.ntfy.api_token}"},
            ),
            NtfyAction(
                action="http",
                label="Reject",
                url=f"{settings.ntfy.lan_base_url}/queue/{job_record.id}/reject",
                method="POST",
                headers={"Authorization": f"Bearer {settings.ntfy.api_token}"},
            ),
        ]

    payload = NtfyPayload(
        topic=settings.ntfy.urgent_topic,
        title="Job Automator",
        message=message,
        priority=4,
        tags=["briefcase"],
        actions=actions,
    )

    result: NtfyResult = await publish(payload, settings.ntfy)

    if result.ok:
        logger.info(
            "notification_sent",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            channel="ntfy",
        )
        await _log_attempt(
            session,
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            body=body,
            channel="ntfy",
            success=1,
            error_message=None,
        )
    else:
        # Ntfy failed after retries — attempt SMS fallback if configured
        logger.error(
            "notification_ntfy_failed",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            error=result.error,
        )

        if settings.sms_enabled and settings.sms is not None:
            logger.info(
                "notification_falling_back_to_sms",
                job_id=job_record.id,
                trigger_reason=trigger_reason,
            )
            await _send_via_sms(
                session=session,
                job_id=job_record.id,
                trigger_reason=trigger_reason,
                body=body,
                sms_settings=settings.sms,
                channel="sms_fallback",
            )
        else:
            # No fallback available — log the ntfy failure
            await _log_attempt(
                session,
                job_id=job_record.id,
                trigger_reason=trigger_reason,
                body=body,
                channel="ntfy",
                success=0,
                error_message=result.error,
            )


async def _send_via_sms(
    session: AsyncSession,
    *,
    job_id: str | None,
    trigger_reason: str,
    body: str,
    sms_settings: SMSSettings | None,
    channel: str,
) -> None:
    """Send a notification via SMS and log the result.

    Args:
        session: Active async database session.
        job_id: The job record ID, or None for non-job notifications.
        trigger_reason: The notification trigger condition.
        body: The SMS message body.
        sms_settings: SMS gateway configuration.
        channel: The channel label for logging (e.g. "sms" or "sms_fallback").
    """
    assert sms_settings is not None

    result = await send_sms(body, sms_settings)

    if result.ok:
        logger.info(
            "notification_sent",
            job_id=job_id,
            trigger_reason=trigger_reason,
            channel=channel,
        )
        await _log_attempt(
            session,
            job_id=job_id,
            trigger_reason=trigger_reason,
            body=body,
            channel=channel,
            success=1,
            error_message=None,
        )
    else:
        logger.error(
            "notification_send_failed",
            job_id=job_id,
            trigger_reason=trigger_reason,
            channel=channel,
            error=result.error,
        )
        await _log_attempt(
            session,
            job_id=job_id,
            trigger_reason=trigger_reason,
            body=body,
            channel=channel,
            success=0,
            error_message=result.error,
        )


async def send_run_summary(
    session: AsyncSession,
    summary_text: str,
    settings: NotificationSettings,
) -> None:
    """Publish a run summary to the info topic (no action buttons, no SMS fallback).

    Publishes to the ntfy info topic with priority 3 and no action buttons.
    If ntfy is disabled or the publish fails, the failure is logged but no
    SMS fallback is attempted (info notifications are non-critical).

    Args:
        session: Active async database session.
        summary_text: The plain-English run summary text.
        settings: Unified notification settings.
    """
    trigger_reason = "run_summary"

    if not settings.ntfy_enabled or settings.ntfy is None:
        logger.info(
            "run_summary_ntfy_disabled",
            reason="ntfy not enabled or not configured",
        )
        await _log_attempt(
            session,
            job_id=None,
            trigger_reason=trigger_reason,
            body=summary_text,
            channel="none",
            success=0,
            error_message="ntfy_disabled",
        )
        return

    payload = NtfyPayload(
        topic=settings.ntfy.info_topic,
        title="Job Automator",
        message=summary_text,
        priority=3,
        tags=["chart_with_upwards_trend"],
        actions=None,
    )

    result: NtfyResult = await publish(payload, settings.ntfy)

    if result.ok:
        logger.info(
            "run_summary_published",
            topic=settings.ntfy.info_topic,
        )
        await _log_attempt(
            session,
            job_id=None,
            trigger_reason=trigger_reason,
            body=summary_text,
            channel="ntfy",
            success=1,
            error_message=None,
        )
    else:
        logger.warning(
            "run_summary_publish_failed",
            topic=settings.ntfy.info_topic,
            error=result.error,
        )
        await _log_attempt(
            session,
            job_id=None,
            trigger_reason=trigger_reason,
            body=summary_text,
            channel="ntfy",
            success=0,
            error_message=result.error,
        )
