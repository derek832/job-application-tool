"""
Unit tests for the quiet hours manager (automator/src/pipeline/quiet_hours.py).

Tests cover:
- is_quiet_hours: same-day ranges, overnight ranges, edge cases, None config
- queue_notification: inserts into notification_queue table
- flush_notification_queue: composes batch summary, sends via ntfy, marks delivered

Requirements: 3.7, 3.8, 3.9
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, NotificationQueue
from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.pipeline.quiet_hours import (
    flush_notification_queue,
    is_quiet_hours,
    queue_notification,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()

    await engine.dispose()


@pytest.fixture
def ntfy_settings() -> NtfySettings:
    """Create test ntfy settings."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="test_urgent_topic",
        info_topic="test_info_topic",
        lan_base_url=None,
        api_token="test_token",
    )


# ---------------------------------------------------------------------------
# is_quiet_hours — None/disabled config
# ---------------------------------------------------------------------------


class TestIsQuietHoursDisabled:
    """Tests for is_quiet_hours when quiet hours are not configured."""

    def test_both_none(self) -> None:
        """Returns False when both start and end are None."""
        now = datetime(2024, 3, 15, 23, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, None, None, "America/New_York") is False

    def test_start_none(self) -> None:
        """Returns False when start is None."""
        now = datetime(2024, 3, 15, 23, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, None, "07:00", "America/New_York") is False

    def test_end_none(self) -> None:
        """Returns False when end is None."""
        now = datetime(2024, 3, 15, 23, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, "22:00", None, "America/New_York") is False

    def test_start_empty_string(self) -> None:
        """Returns False when start is an empty string."""
        now = datetime(2024, 3, 15, 23, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, "", "07:00", "America/New_York") is False

    def test_end_empty_string(self) -> None:
        """Returns False when end is an empty string."""
        now = datetime(2024, 3, 15, 23, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, "22:00", "", "America/New_York") is False


# ---------------------------------------------------------------------------
# is_quiet_hours — same-day range
# ---------------------------------------------------------------------------


class TestIsQuietHoursSameDay:
    """Tests for is_quiet_hours with same-day ranges (start < end)."""

    def test_within_range(self) -> None:
        """Returns True when current time is within the same-day range."""
        # 12:00 Eastern is within 08:00-17:00
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 12, 0, tzinfo=tz)
        assert is_quiet_hours(now, "08:00", "17:00", "America/New_York") is True

    def test_before_range(self) -> None:
        """Returns False when current time is before the range."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 7, 30, tzinfo=tz)
        assert is_quiet_hours(now, "08:00", "17:00", "America/New_York") is False

    def test_after_range(self) -> None:
        """Returns False when current time is after the range."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 18, 0, tzinfo=tz)
        assert is_quiet_hours(now, "08:00", "17:00", "America/New_York") is False

    def test_at_start_boundary(self) -> None:
        """Returns True when current time is exactly at start (inclusive)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 8, 0, tzinfo=tz)
        assert is_quiet_hours(now, "08:00", "17:00", "America/New_York") is True

    def test_at_end_boundary(self) -> None:
        """Returns False when current time is exactly at end (exclusive)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 17, 0, tzinfo=tz)
        assert is_quiet_hours(now, "08:00", "17:00", "America/New_York") is False


# ---------------------------------------------------------------------------
# is_quiet_hours — overnight range
# ---------------------------------------------------------------------------


class TestIsQuietHoursOvernight:
    """Tests for is_quiet_hours with overnight ranges (start > end)."""

    def test_late_night_within_range(self) -> None:
        """Returns True when current time is after start (late night)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 23, 30, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is True

    def test_early_morning_within_range(self) -> None:
        """Returns True when current time is before end (early morning)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 16, 5, 0, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is True

    def test_daytime_outside_range(self) -> None:
        """Returns False when current time is during the day (outside range)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 12, 0, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is False

    def test_at_start_boundary_overnight(self) -> None:
        """Returns True when current time is exactly at start (inclusive)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 22, 0, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is True

    def test_at_end_boundary_overnight(self) -> None:
        """Returns False when current time is exactly at end (exclusive)."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 16, 7, 0, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is False

    def test_just_before_start(self) -> None:
        """Returns False when current time is just before start."""
        tz = ZoneInfo("America/New_York")
        now = datetime(2024, 3, 15, 21, 59, tzinfo=tz)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is False


# ---------------------------------------------------------------------------
# is_quiet_hours — timezone handling
# ---------------------------------------------------------------------------


class TestIsQuietHoursTimezone:
    """Tests for is_quiet_hours timezone conversion."""

    def test_utc_time_converted_to_local(self) -> None:
        """UTC time is correctly converted to the specified timezone."""
        # 03:00 UTC = 22:00 Eastern (previous day, during DST)
        # In March 2024, Eastern is UTC-4 (EDT)
        # So 02:00 UTC = 22:00 EDT (previous day)
        now = datetime(2024, 3, 16, 2, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, "22:00", "07:00", "America/New_York") is True

    def test_different_timezone(self) -> None:
        """Works correctly with a different timezone."""
        # 14:00 UTC = 23:00 Tokyo (UTC+9)
        now = datetime(2024, 3, 15, 14, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(now, "22:00", "07:00", "Asia/Tokyo") is True


# ---------------------------------------------------------------------------
# queue_notification
# ---------------------------------------------------------------------------


class TestQueueNotification:
    """Tests for queue_notification function."""

    @pytest.mark.asyncio
    async def test_inserts_notification(self, session: AsyncSession) -> None:
        """queue_notification inserts a row into notification_queue."""
        await queue_notification(
            session,
            job_id="job123",
            trigger_reason="stretch_role",
            message_body="Senior Engineer @ Acme Corp (72%)",
        )
        await session.commit()

        result = await session.execute(select(NotificationQueue))
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].job_id == "job123"
        assert entries[0].trigger_reason == "stretch_role"
        assert entries[0].message_body == "Senior Engineer @ Acme Corp (72%)"
        assert entries[0].delivered == 0
        assert entries[0].queued_at is not None

    @pytest.mark.asyncio
    async def test_inserts_with_none_job_id(self, session: AsyncSession) -> None:
        """queue_notification works with None job_id for system notifications."""
        await queue_notification(
            session,
            job_id=None,
            trigger_reason="health_check_failed",
            message_body="Chrome CDP unreachable",
        )
        await session.commit()

        result = await session.execute(select(NotificationQueue))
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].job_id is None
        assert entries[0].trigger_reason == "health_check_failed"

    @pytest.mark.asyncio
    async def test_multiple_notifications_queued(self, session: AsyncSession) -> None:
        """Multiple notifications can be queued independently."""
        await queue_notification(session, "job1", "stretch_role", "Message 1")
        await queue_notification(session, "job2", "good_fit", "Message 2")
        await queue_notification(session, None, "run_summary", "Message 3")
        await session.commit()

        result = await session.execute(select(NotificationQueue))
        entries = result.scalars().all()
        assert len(entries) == 3
        assert all(e.delivered == 0 for e in entries)


# ---------------------------------------------------------------------------
# flush_notification_queue
# ---------------------------------------------------------------------------


class TestFlushNotificationQueue:
    """Tests for flush_notification_queue function."""

    @pytest.mark.asyncio
    async def test_empty_queue_does_nothing(
        self, session: AsyncSession, ntfy_settings: NtfySettings
    ) -> None:
        """flush_notification_queue returns without sending when queue is empty."""
        with patch("src.pipeline.quiet_hours.publish") as mock_publish:
            await flush_notification_queue(session, ntfy_settings)
            mock_publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_batch_summary(
        self, session: AsyncSession, ntfy_settings: NtfySettings
    ) -> None:
        """flush_notification_queue composes and sends a batch summary."""
        await queue_notification(session, "job1", "stretch_role", "Engineer @ Acme")
        await queue_notification(session, "job2", "good_fit", "Dev @ Corp")
        await session.commit()

        with patch(
            "src.pipeline.quiet_hours.publish",
            new_callable=AsyncMock,
            return_value=NtfyResult(ok=True, status_code=200),
        ) as mock_publish:
            await flush_notification_queue(session, ntfy_settings)
            await session.commit()

            mock_publish.assert_called_once()
            payload = mock_publish.call_args[0][0]
            assert "2 notifications during quiet hours" in payload.message
            assert "stretch_role: Engineer @ Acme" in payload.message
            assert "good_fit: Dev @ Corp" in payload.message
            assert payload.topic == "test_info_topic"
            assert payload.title == "Job Automator — Quiet Hours Summary"

    @pytest.mark.asyncio
    async def test_marks_all_as_delivered(
        self, session: AsyncSession, ntfy_settings: NtfySettings
    ) -> None:
        """flush_notification_queue marks all items as delivered on success."""
        await queue_notification(session, "job1", "stretch_role", "Message 1")
        await queue_notification(session, "job2", "good_fit", "Message 2")
        await session.commit()

        with patch(
            "src.pipeline.quiet_hours.publish",
            new_callable=AsyncMock,
            return_value=NtfyResult(ok=True, status_code=200),
        ):
            await flush_notification_queue(session, ntfy_settings)
            await session.commit()

        result = await session.execute(select(NotificationQueue))
        entries = result.scalars().all()
        assert all(e.delivered == 1 for e in entries)

    @pytest.mark.asyncio
    async def test_leaves_queue_on_failure(
        self, session: AsyncSession, ntfy_settings: NtfySettings
    ) -> None:
        """flush_notification_queue leaves items undelivered on ntfy failure."""
        await queue_notification(session, "job1", "stretch_role", "Message 1")
        await session.commit()

        with patch(
            "src.pipeline.quiet_hours.publish",
            new_callable=AsyncMock,
            return_value=NtfyResult(ok=False, error="timeout", status_code=None),
        ):
            await flush_notification_queue(session, ntfy_settings)

        result = await session.execute(select(NotificationQueue))
        entries = result.scalars().all()
        assert all(e.delivered == 0 for e in entries)

    @pytest.mark.asyncio
    async def test_skips_already_delivered(
        self, session: AsyncSession, ntfy_settings: NtfySettings
    ) -> None:
        """flush_notification_queue only sends undelivered notifications."""
        # Add one delivered and one pending
        await queue_notification(session, "job1", "old", "Already sent")
        await session.commit()

        # Manually mark first as delivered
        result = await session.execute(select(NotificationQueue))
        entry = result.scalars().first()
        entry.delivered = 1
        await session.flush()

        # Add a new pending one
        await queue_notification(session, "job2", "new", "Pending")
        await session.commit()

        with patch(
            "src.pipeline.quiet_hours.publish",
            new_callable=AsyncMock,
            return_value=NtfyResult(ok=True, status_code=200),
        ) as mock_publish:
            await flush_notification_queue(session, ntfy_settings)
            await session.commit()

            mock_publish.assert_called_once()
            payload = mock_publish.call_args[0][0]
            assert "1 notifications during quiet hours" in payload.message
            assert "new: Pending" in payload.message
            assert "old" not in payload.message
