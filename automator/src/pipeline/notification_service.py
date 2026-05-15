"""Notification trigger logger for the LinkedIn Job Automator.

Orchestrates the full notification flow: rate-limit check, SMS composition,
SMS delivery, and audit logging to the ``notification_log`` table.

Every notification attempt — whether successful, failed, or rate-limited —
is recorded in the database for auditability and rate-limit enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord, NotificationLog
from src.integrations.sms_gateway import SMSSettings, compose_sms, send_sms
from src.integrations.sms_rate_limiter import check_rate_limit

logger = structlog.get_logger(__name__)


async def notify(
    session: AsyncSession,
    job_record: JobRecord,
    trigger_reason: str,
    sms_settings: SMSSettings,
) -> None:
    """Send an SMS notification and log the attempt to the database.

    Checks the rolling-window rate limit before attempting delivery. Regardless
    of whether the send succeeds, fails, or is rate-limited, a row is always
    written to ``notification_log`` for audit and rate-limit tracking.

    Args:
        session: An active SQLAlchemy async session for database access.
        job_record: The job record that triggered the notification.
        trigger_reason: The notification trigger condition (e.g. "stretch_role",
            "captcha_detected", "score_at_threshold_boundary").
        sms_settings: SMTP credentials and carrier gateway address for SMS delivery.
    """
    sent_at = datetime.now(tz=UTC).isoformat()

    # Step 1: Check rate limit
    allowed = await check_rate_limit(session)

    if not allowed:
        logger.warning(
            "notification_rate_limited",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        sms_body = compose_sms(
            job_record.job_title, job_record.company, trigger_reason, job_record.fit_score
        )
        log_entry = NotificationLog(
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            sms_body=sms_body,
            sent_at=sent_at,
            success=0,
            error_message="rate_limited",
        )
        session.add(log_entry)
        await session.flush()
        return

    # Step 2: Compose the SMS message
    sms_body = compose_sms(
        job_record.job_title, job_record.company, trigger_reason, job_record.fit_score
    )

    # Step 3: Attempt delivery
    result = await send_sms(sms_body, sms_settings)

    # Step 4: Log the result
    success = 1 if result.ok else 0
    error_message = result.error if not result.ok else None

    if result.ok:
        logger.info(
            "notification_sent",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
    else:
        logger.error(
            "notification_send_failed",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            error=error_message,
        )

    log_entry = NotificationLog(
        job_id=job_record.id,
        trigger_reason=trigger_reason,
        sms_body=sms_body,
        sent_at=sent_at,
        success=success,
        error_message=error_message,
    )
    session.add(log_entry)
    await session.flush()
