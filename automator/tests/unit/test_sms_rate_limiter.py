"""
Unit tests for the SMS rate limiter.

Tests verify that check_rate_limit correctly allows or blocks SMS sends
based on the count of successful notifications in the last hour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, NotificationLog
from src.integrations.sms_rate_limiter import check_rate_limit


@pytest.fixture
async def session() -> AsyncSession:
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess

    await engine.dispose()


async def _insert_notifications(
    session: AsyncSession,
    count: int,
    *,
    minutes_ago: int = 30,
    success: int = 1,
) -> None:
    """Insert notification_log rows with sent_at set to `minutes_ago` minutes before now."""
    sent_at = (datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)).isoformat()
    for i in range(count):
        await session.execute(
            insert(NotificationLog).values(
                trigger_reason="test_trigger",
                sms_body=f"Test message {i}",
                sent_at=sent_at,
                success=success,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_allows_send_when_no_notifications(session: AsyncSession) -> None:
    """Rate limiter allows sending when there are no prior notifications."""
    result = await check_rate_limit(session)
    assert result is True


@pytest.mark.asyncio
async def test_allows_send_below_limit(session: AsyncSession) -> None:
    """Rate limiter allows sending when count is below 10."""
    await _insert_notifications(session, 9, minutes_ago=30)
    result = await check_rate_limit(session)
    assert result is True


@pytest.mark.asyncio
async def test_blocks_send_at_limit(session: AsyncSession) -> None:
    """Rate limiter blocks sending when exactly 10 successful sends exist."""
    await _insert_notifications(session, 10, minutes_ago=30)
    result = await check_rate_limit(session)
    assert result is False


@pytest.mark.asyncio
async def test_blocks_send_above_limit(session: AsyncSession) -> None:
    """Rate limiter blocks sending when more than 10 successful sends exist."""
    await _insert_notifications(session, 15, minutes_ago=30)
    result = await check_rate_limit(session)
    assert result is False


@pytest.mark.asyncio
async def test_ignores_old_notifications(session: AsyncSession) -> None:
    """Notifications older than 1 hour do not count toward the limit."""
    await _insert_notifications(session, 15, minutes_ago=61)
    result = await check_rate_limit(session)
    assert result is True


@pytest.mark.asyncio
async def test_ignores_failed_notifications(session: AsyncSession) -> None:
    """Failed notifications (success=0) do not count toward the limit."""
    await _insert_notifications(session, 15, minutes_ago=30, success=0)
    result = await check_rate_limit(session)
    assert result is True


@pytest.mark.asyncio
async def test_mixed_success_and_failure(session: AsyncSession) -> None:
    """Only successful sends count; failed sends are excluded."""
    await _insert_notifications(session, 9, minutes_ago=30, success=1)
    await _insert_notifications(session, 5, minutes_ago=30, success=0)
    result = await check_rate_limit(session)
    assert result is True


@pytest.mark.asyncio
async def test_mixed_old_and_recent(session: AsyncSession) -> None:
    """Only recent sends count; old sends are excluded."""
    await _insert_notifications(session, 8, minutes_ago=61)  # old, ignored
    await _insert_notifications(session, 9, minutes_ago=30)  # recent, counted
    result = await check_rate_limit(session)
    assert result is True
