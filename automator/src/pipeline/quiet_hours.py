"""Quiet hours manager — notification queueing and batch delivery.

During configured quiet hours, notifications are queued in the
``notification_queue`` table rather than delivered immediately. When quiet
hours end, an APScheduler job triggers ``flush_notification_queue()`` which
composes a single batch summary and delivers it via ntfy.

Validates: Requirements 3.7, 3.8, 3.9
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import NotificationQueue
from src.integrations.ntfy_client import NtfyPayload, NtfySettings, publish

logger = structlog.get_logger(__name__)


def is_quiet_hours(
    now: datetime,
    quiet_start: str | None,
    quiet_end: str | None,
    timezone: str,
) -> bool:
    """Check if the current time falls within quiet hours.

    Handles overnight ranges (e.g., 22:00 to 07:00) by checking if the range
    crosses midnight. Returns False if quiet hours are not configured (either
    start or end is None).

    Args:
        now: The current datetime (timezone-aware).
        quiet_start: Start of quiet hours in "HH:MM" format, or None.
        quiet_end: End of quiet hours in "HH:MM" format, or None.
        timezone: IANA timezone string (e.g. "America/New_York").

    Returns:
        True if the current time is within quiet hours, False otherwise.
    """
    if not quiet_start or not quiet_end:
        return False

    tz = ZoneInfo(timezone)
    local_now = now.astimezone(tz)
    current_minutes = local_now.hour * 60 + local_now.minute

    start_h, start_m = map(int, quiet_start.split(":"))
    end_h, end_m = map(int, quiet_end.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        # Same-day range (e.g., 08:00 to 17:00)
        return start_minutes <= current_minutes < end_minutes
    else:
        # Overnight range (e.g., 22:00 to 07:00)
        return current_minutes >= start_minutes or current_minutes < end_minutes


async def queue_notification(
    session: AsyncSession,
    job_id: str | None,
    trigger_reason: str,
    message_body: str,
) -> None:
    """Store a notification in the queue for later batch delivery.

    Inserts a new row into the ``notification_queue`` table with
    ``delivered=0``. The notification will be delivered when quiet hours
    end and ``flush_notification_queue()`` is called.

    Args:
        session: Active async database session.
        job_id: The job record ID, or None for non-job notifications.
        trigger_reason: The condition that caused this notification.
        message_body: The notification text content.
    """
    entry = NotificationQueue(
        job_id=job_id,
        trigger_reason=trigger_reason,
        message_body=message_body,
        queued_at=datetime.now(tz=UTC).isoformat(),
        delivered=0,
    )
    session.add(entry)
    await session.flush()

    logger.info(
        "notification_queued",
        job_id=job_id,
        trigger_reason=trigger_reason,
    )


async def flush_notification_queue(
    session: AsyncSession,
    ntfy_settings: NtfySettings,
) -> None:
    """Deliver all queued notifications as a single batch summary via ntfy.

    Composes a single summary message listing all pending (undelivered) items,
    sends it via ntfy, and marks all items as delivered. If there are no
    pending notifications, returns immediately without sending.

    Called by an APScheduler job registered at the ``quiet_hours_end`` time.

    Args:
        session: Active async database session.
        ntfy_settings: Ntfy server/topic configuration for delivery.
    """
    # Fetch all undelivered notifications
    stmt = select(NotificationQueue).where(NotificationQueue.delivered == 0)
    result = await session.execute(stmt)
    queued = result.scalars().all()

    if not queued:
        logger.debug("flush_notification_queue_empty")
        return

    # Compose batch summary
    summary_lines = [f"📋 {len(queued)} notifications during quiet hours:\n"]
    for item in queued:
        summary_lines.append(f"• {item.trigger_reason}: {item.message_body}")

    batch_message = "\n".join(summary_lines)

    # Send via ntfy
    payload = NtfyPayload(
        topic=ntfy_settings.info_topic,
        title="Job Automator — Quiet Hours Summary",
        message=batch_message,
        priority=3,
        tags=["moon", "clipboard"],
        actions=None,
    )

    publish_result = await publish(payload, ntfy_settings)

    if publish_result.ok:
        # Mark all as delivered
        ids = [item.id for item in queued]
        stmt_update = (
            update(NotificationQueue)
            .where(NotificationQueue.id.in_(ids))
            .values(delivered=1)
        )
        await session.execute(stmt_update)
        await session.flush()

        logger.info(
            "notification_queue_flushed",
            count=len(queued),
        )
    else:
        # Leave items in queue for retry on next flush cycle
        logger.error(
            "notification_queue_flush_failed",
            count=len(queued),
            error=publish_result.error,
        )


def register_quiet_hours_flush_job(
    scheduler: "AsyncIOScheduler",  # noqa: F821
    quiet_hours_end: str,
    timezone: str,
) -> None:
    """Register an APScheduler job to flush the notification queue at quiet_hours_end.

    Creates a CronTrigger that fires daily at the configured quiet hours end
    time. The job calls ``flush_notification_queue()`` to deliver all queued
    notifications as a batch summary.

    Args:
        scheduler: The APScheduler AsyncIOScheduler instance.
        quiet_hours_end: End of quiet hours in "HH:MM" format.
        timezone: IANA timezone string for the trigger.
    """
    from apscheduler.triggers.cron import CronTrigger

    end_h, end_m = map(int, quiet_hours_end.split(":"))
    tz = ZoneInfo(timezone)

    scheduler.add_job(
        _flush_queue_wrapper,
        trigger=CronTrigger(
            hour=end_h,
            minute=end_m,
            timezone=tz,
        ),
        id="quiet_hours_flush",
        name="Quiet Hours Notification Flush",
        replace_existing=True,
    )

    logger.info(
        "quiet_hours_flush_job_registered",
        quiet_hours_end=quiet_hours_end,
        timezone=timezone,
    )


async def _flush_queue_wrapper() -> None:
    """Wrapper for the APScheduler flush job.

    Obtains a database session and ntfy settings from the config table,
    then calls ``flush_notification_queue()``. Defers imports to avoid
    circular dependencies.
    """
    from src.db.config_repo import get_config
    from src.db.database import get_session

    async for session in get_session():
        # Load ntfy settings from config table
        ntfy_enabled = await get_config(session, "ntfy_enabled")
        if not ntfy_enabled:
            logger.info("flush_queue_skipped", reason="ntfy not enabled")
            return

        server_url = await get_config(session, "ntfy_server_url") or "https://ntfy.sh"
        urgent_topic = await get_config(session, "ntfy_urgent_topic") or ""
        info_topic = await get_config(session, "ntfy_info_topic") or ""
        lan_base_url = await get_config(session, "lan_base_url")
        api_token = await get_config(session, "api_token") or ""

        if not info_topic:
            logger.warning("flush_queue_skipped", reason="no info_topic configured")
            return

        ntfy_settings = NtfySettings(
            server_url=server_url,
            urgent_topic=urgent_topic,
            info_topic=info_topic,
            lan_base_url=lan_base_url,
            api_token=api_token,
        )

        await flush_notification_queue(session, ntfy_settings)
        break
