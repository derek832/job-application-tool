"""
Notification rate limiter for the LinkedIn Job Automator.

Enforces a maximum of 10 notifications per rolling 1-hour window by
querying the ``notification_log`` table for recent successful sends
across ALL channels (ntfy, sms, sms_fallback).

The rate limit is channel-agnostic — it counts every successful delivery
regardless of which channel was used (Requirements 9.1, 9.2, 9.4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import NotificationLog

logger = structlog.get_logger(__name__)

# Maximum number of successful sends allowed within the rate window.
# This limit applies across ALL channels (ntfy, sms, sms_fallback).
_MAX_SENDS_PER_WINDOW: int = 10

# Rolling window duration in seconds.
_WINDOW_SECONDS: int = 3600


async def check_rate_limit(session: AsyncSession) -> bool:
    """Check whether sending a notification is allowed under the rate limit.

    Queries the ``notification_log`` table for rows where ``sent_at`` is within
    the last 3600 seconds (1 hour) and ``success = 1``. The query is
    channel-agnostic — it counts successful sends across all channels (ntfy,
    sms, sms_fallback) in a single shared counter.

    Args:
        session: An active SQLAlchemy async session for database access.

    Returns:
        ``True`` if sending is allowed (fewer than 10 successful sends in the
        last hour). ``False`` if the rate limit has been reached (10 or more
        successful sends in the last hour).
    """
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=_WINDOW_SECONDS)
    cutoff_iso = cutoff.isoformat()

    # Count ALL successful sends regardless of channel value.
    # This ensures ntfy, sms, and sms_fallback all share the same budget.
    stmt = (
        select(func.count())
        .select_from(NotificationLog)
        .where(
            NotificationLog.sent_at >= cutoff_iso,
            NotificationLog.success == 1,
        )
    )

    result = await session.execute(stmt)
    count: int = result.scalar_one()

    if count >= _MAX_SENDS_PER_WINDOW:
        logger.warning(
            "notification_rate_limit_hit",
            recent_sends=count,
            window_seconds=_WINDOW_SECONDS,
            max_allowed=_MAX_SENDS_PER_WINDOW,
        )
        return False

    return True
