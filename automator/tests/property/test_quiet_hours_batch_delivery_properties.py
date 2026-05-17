"""
Property-based tests for quiet hours batch delivery.

Uses Hypothesis to verify that when quiet hours end and
flush_notification_queue() is called, all queued notifications are delivered
in a single batch summary. The batch message contains all queued items and
all items are marked as delivered.

Properties tested:
- Property 10: Quiet Hours Batch Delivery
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, NotificationQueue
from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.pipeline.quiet_hours import flush_notification_queue


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Trigger reasons: realistic notification trigger strings
trigger_reason_strategy = st.sampled_from([
    "new_application",
    "job_scored",
    "job_applied",
    "health_check_failed",
    "pipeline_completed",
    "stretch_queue_added",
    "blacklist_hit",
    "session_expired",
])

# Message bodies: non-empty text representing notification content
message_body_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
)

# A single queued notification item (trigger_reason, message_body)
notification_item_strategy = st.tuples(trigger_reason_strategy, message_body_strategy)

# List of 1-20 queued notifications
queued_notifications_strategy = st.lists(
    notification_item_strategy,
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Async DB helper
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh in-memory SQLite session with schema initialized."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    return session, engine


async def _cleanup(session: AsyncSession, engine) -> None:
    """Close session and dispose engine."""
    await session.close()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_NTFY_SETTINGS = NtfySettings(
    server_url="https://ntfy.sh",
    urgent_topic="test_urgent_topic",
    info_topic="test_info_topic",
    lan_base_url=None,
    api_token="test_token",
)


# ---------------------------------------------------------------------------
# Property 10: Quiet Hours Batch Delivery
# ---------------------------------------------------------------------------


@given(notifications=queued_notifications_strategy)
@settings(max_examples=150)
def test_quiet_hours_batch_delivery_all_items_in_message(
    notifications: list[tuple[str, str]],
) -> None:
    """
    When quiet hours end and flush_notification_queue() is called, all queued
    notifications are delivered in a single batch summary. The batch message
    contains all queued items (each trigger_reason and message_body appears
    in the composed message).

    **Validates: Requirements 3.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert queued notifications into the database
            for trigger_reason, message_body in notifications:
                entry = NotificationQueue(
                    job_id=None,
                    trigger_reason=trigger_reason,
                    message_body=message_body,
                    queued_at=datetime.now(tz=UTC).isoformat(),
                    delivered=0,
                )
                session.add(entry)
            await session.flush()

            # Mock ntfy publish to capture the batch message
            captured_payloads: list = []

            async def mock_publish(payload, settings):
                captured_payloads.append(payload)
                return NtfyResult(ok=True, status_code=200)

            with patch(
                "src.pipeline.quiet_hours.publish",
                side_effect=mock_publish,
            ):
                await flush_notification_queue(session, _NTFY_SETTINGS)

            # Exactly one batch message should have been sent
            assert len(captured_payloads) == 1, (
                f"Expected exactly 1 batch message, got {len(captured_payloads)}"
            )

            batch_message = captured_payloads[0].message

            # The batch message must contain all queued items
            for trigger_reason, message_body in notifications:
                assert trigger_reason in batch_message, (
                    f"Batch message missing trigger_reason '{trigger_reason}'. "
                    f"Message: '{batch_message[:200]}...'"
                )
                assert message_body in batch_message, (
                    f"Batch message missing message_body '{message_body}'. "
                    f"Message: '{batch_message[:200]}...'"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(notifications=queued_notifications_strategy)
@settings(max_examples=150)
def test_quiet_hours_batch_delivery_all_marked_delivered(
    notifications: list[tuple[str, str]],
) -> None:
    """
    When quiet hours end and flush_notification_queue() is called, all queued
    notifications are marked as delivered (delivered=1) after the batch
    summary is sent successfully.

    **Validates: Requirements 3.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert queued notifications into the database
            for trigger_reason, message_body in notifications:
                entry = NotificationQueue(
                    job_id=None,
                    trigger_reason=trigger_reason,
                    message_body=message_body,
                    queued_at=datetime.now(tz=UTC).isoformat(),
                    delivered=0,
                )
                session.add(entry)
            await session.flush()

            # Mock ntfy publish to succeed
            async def mock_publish(payload, settings):
                return NtfyResult(ok=True, status_code=200)

            with patch(
                "src.pipeline.quiet_hours.publish",
                side_effect=mock_publish,
            ):
                await flush_notification_queue(session, _NTFY_SETTINGS)

            # All notifications should now be marked as delivered
            stmt = select(NotificationQueue)
            result = await session.execute(stmt)
            all_items = result.scalars().all()

            assert len(all_items) == len(notifications), (
                f"Expected {len(notifications)} items in DB, got {len(all_items)}"
            )

            for item in all_items:
                assert item.delivered == 1, (
                    f"Notification id={item.id} reason='{item.trigger_reason}' "
                    f"was not marked as delivered after flush. delivered={item.delivered}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
