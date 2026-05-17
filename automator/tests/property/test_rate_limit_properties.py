"""
Property-based tests for notification rate limit enforcement and logging completeness.

Uses Hypothesis to verify correctness properties of the rate limiter
(src/integrations/sms_rate_limiter.py) and the notification logging behavior
of the notification service (src/pipeline/notification_service.py).

Properties tested:
- Property 9: Shared Rate Limit Enforcement
- Property 10: Notification Attempt Logging Completeness
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, NotificationLog
from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.integrations.sms_gateway import SMSSettings
from src.integrations.sms_rate_limiter import check_rate_limit
from src.pipeline.notification_service import NotificationSettings, notify


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for channels that count toward the rate limit (successful sends)
channel_strategy = st.sampled_from(["ntfy", "sms", "sms_fallback"])

# Strategy for the number of recent successful sends (0 to 15, covering
# below, at, and above the 10-per-hour limit)
recent_sends_count_strategy = st.integers(min_value=0, max_value=15)

# Strategy for timestamps within the last hour (seconds ago from now)
seconds_ago_strategy = st.integers(min_value=0, max_value=3599)

# Strategy for timestamps outside the 1-hour window (more than 1 hour ago)
old_seconds_ago_strategy = st.integers(min_value=3601, max_value=86400)

# Strategy for non-empty text fields
non_empty_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

# Strategy for job IDs
job_id_strategy = st.from_regex(r"[0-9]{5,15}", fullmatch=True)

# Strategy for trigger reasons
trigger_reason_strategy = st.sampled_from([
    "stretch_role",
    "captcha_detected",
    "score_at_threshold_boundary",
    "resume_ready_external_apply",
])

# Strategy for notification outcome scenarios
outcome_strategy = st.sampled_from(["ntfy_success", "ntfy_fail_no_fallback", "sms_success", "both_disabled", "rate_limited"])


# ---------------------------------------------------------------------------
# Async DB helpers
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


async def _insert_notification_log(
    session: AsyncSession,
    *,
    sent_at: str,
    success: int,
    channel: str,
    job_id: str | None = None,
) -> None:
    """Insert a notification_log row for test setup."""
    log_entry = NotificationLog(
        job_id=job_id,
        trigger_reason="test_trigger",
        sms_body="test body",
        sent_at=sent_at,
        success=success,
        error_message=None if success == 1 else "test_error",
        channel=channel,
    )
    session.add(log_entry)
    await session.flush()


async def _create_job_record(session: AsyncSession, job_id: str) -> JobRecord:
    """Create a minimal JobRecord for testing."""
    now = datetime.now(tz=UTC).isoformat()
    job = JobRecord(
        id=job_id,
        job_title="Software Engineer",
        company="Acme Corp",
        linkedin_url=f"https://linkedin.com/jobs/{job_id}",
        apply_type="easy_apply",
        status="discovered",
        discovered_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()
    return job


# ---------------------------------------------------------------------------
# Property 9: Shared Rate Limit Enforcement
# ---------------------------------------------------------------------------


@given(
    recent_successful_sends=recent_sends_count_strategy,
    channels=st.lists(channel_strategy, min_size=0, max_size=15),
    old_sends=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=200)
def test_shared_rate_limit_enforcement(
    recent_successful_sends: int,
    channels: list[str],
    old_sends: int,
) -> None:
    """
    For any sequence of notification attempts with timestamps, the rate limiter
    SHALL allow at most 10 successful deliveries within any rolling 1-hour
    window, counting both ntfy and SMS sends together in a single shared
    counter. The 11th attempt within any 1-hour window SHALL be blocked
    regardless of channel.

    **Validates: Requirements 9.1, 9.2, 9.4**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(tz=UTC)

            # Insert `recent_successful_sends` successful sends within the last hour
            # using a mix of channels from the generated list
            for i in range(recent_successful_sends):
                # Spread sends across the last hour
                seconds_back = int((i + 1) * (3500 / max(recent_successful_sends, 1)))
                sent_at = (now - timedelta(seconds=seconds_back)).isoformat()
                ch = channels[i % len(channels)] if channels else "ntfy"
                await _insert_notification_log(
                    session,
                    sent_at=sent_at,
                    success=1,
                    channel=ch,
                )

            # Insert some old sends (outside the window) — these should NOT count
            for i in range(old_sends):
                old_time = (now - timedelta(hours=2, minutes=i)).isoformat()
                await _insert_notification_log(
                    session,
                    sent_at=old_time,
                    success=1,
                    channel="sms",
                )

            await session.commit()

            # Check rate limit
            allowed = await check_rate_limit(session)

            if recent_successful_sends < 10:
                assert allowed is True, (
                    f"Rate limiter blocked with only {recent_successful_sends} "
                    f"recent sends (limit is 10). Old sends ({old_sends}) should "
                    f"not count."
                )
            else:
                # 10 or more recent successful sends — should be blocked
                assert allowed is False, (
                    f"Rate limiter allowed send with {recent_successful_sends} "
                    f"recent successful sends (limit is 10). Channels used: "
                    f"{channels[:recent_successful_sends]}"
                )
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    ntfy_sends=st.integers(min_value=0, max_value=10),
    sms_sends=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100)
def test_rate_limit_counts_all_channels_together(
    ntfy_sends: int,
    sms_sends: int,
) -> None:
    """
    The rate limit SHALL count ntfy and SMS sends together in a single shared
    counter. The combined total determines whether the limit is reached,
    regardless of which channel each send used.

    **Validates: Requirements 9.1, 9.4**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(tz=UTC)
            total_sends = ntfy_sends + sms_sends

            # Insert ntfy sends
            for i in range(ntfy_sends):
                sent_at = (now - timedelta(minutes=i + 1)).isoformat()
                await _insert_notification_log(
                    session,
                    sent_at=sent_at,
                    success=1,
                    channel="ntfy",
                )

            # Insert sms sends
            for i in range(sms_sends):
                sent_at = (now - timedelta(minutes=ntfy_sends + i + 1)).isoformat()
                await _insert_notification_log(
                    session,
                    sent_at=sent_at,
                    success=1,
                    channel="sms",
                )

            await session.commit()

            allowed = await check_rate_limit(session)

            if total_sends < 10:
                assert allowed is True, (
                    f"Rate limiter blocked with {ntfy_sends} ntfy + {sms_sends} sms = "
                    f"{total_sends} total (limit is 10)"
                )
            else:
                assert allowed is False, (
                    f"Rate limiter allowed with {ntfy_sends} ntfy + {sms_sends} sms = "
                    f"{total_sends} total (limit is 10)"
                )
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    failed_sends=st.integers(min_value=10, max_value=20),
)
@settings(max_examples=50)
def test_rate_limit_ignores_failed_sends(
    failed_sends: int,
) -> None:
    """
    Failed notification attempts (success=0) SHALL NOT count toward the rate
    limit. Only successful deliveries consume the budget.

    **Validates: Requirements 9.1, 9.2**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(tz=UTC)

            # Insert many failed sends within the window
            for i in range(failed_sends):
                sent_at = (now - timedelta(minutes=i + 1)).isoformat()
                await _insert_notification_log(
                    session,
                    sent_at=sent_at,
                    success=0,
                    channel="ntfy",
                )

            await session.commit()

            # Should still be allowed since none were successful
            allowed = await check_rate_limit(session)
            assert allowed is True, (
                f"Rate limiter blocked with {failed_sends} FAILED sends — "
                f"only successful sends should count toward the limit"
            )
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 10: Notification Attempt Logging Completeness
# ---------------------------------------------------------------------------


@given(
    outcome=outcome_strategy,
    job_id=job_id_strategy,
    trigger_reason=trigger_reason_strategy,
)
@settings(max_examples=100)
def test_notification_attempt_logging_completeness(
    outcome: str,
    job_id: str,
    trigger_reason: str,
) -> None:
    """
    For any notification attempt — whether it succeeds, fails, or is
    rate-limited — a corresponding row SHALL be written to the notification_log
    table with a valid timestamp, the channel used, and the outcome status.

    **Validates: Requirements 9.3**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Create a job record for the notification
            job = await _create_job_record(session, job_id)
            await session.commit()

            # Configure settings based on the outcome scenario
            ntfy_settings = NtfySettings(
                server_url="https://ntfy.sh",
                urgent_topic="a1b2c3d4e5f6g7h8",
                info_topic="i9j0k1l2m3n4o5p6",
                lan_base_url=None,
                api_token="test_token",
            )
            sms_settings = SMSSettings(
                gmail_user="test@gmail.com",
                sms_gateway="5551234567@vtext.com",
            )

            if outcome == "ntfy_success":
                settings = NotificationSettings(
                    ntfy_enabled=True,
                    ntfy=ntfy_settings,
                    sms_enabled=False,
                    sms=None,
                )
                mock_publish_result = NtfyResult(ok=True, status_code=200)
                mock_sms_result = None
            elif outcome == "ntfy_fail_no_fallback":
                settings = NotificationSettings(
                    ntfy_enabled=True,
                    ntfy=ntfy_settings,
                    sms_enabled=False,
                    sms=None,
                )
                mock_publish_result = NtfyResult(ok=False, error="server_error", status_code=500)
                mock_sms_result = None
            elif outcome == "sms_success":
                settings = NotificationSettings(
                    ntfy_enabled=False,
                    ntfy=None,
                    sms_enabled=True,
                    sms=sms_settings,
                )
                mock_publish_result = None
                mock_sms_result = AsyncMock(return_value=type("Result", (), {"ok": True, "error": None})())
            elif outcome == "both_disabled":
                settings = NotificationSettings(
                    ntfy_enabled=False,
                    ntfy=None,
                    sms_enabled=False,
                    sms=None,
                )
                mock_publish_result = None
                mock_sms_result = None
            else:  # rate_limited
                # Pre-fill 10 successful sends to trigger rate limit
                now = datetime.now(tz=UTC)
                for i in range(10):
                    sent_at = (now - timedelta(minutes=i + 1)).isoformat()
                    await _insert_notification_log(
                        session,
                        sent_at=sent_at,
                        success=1,
                        channel="ntfy",
                    )
                await session.commit()
                settings = NotificationSettings(
                    ntfy_enabled=True,
                    ntfy=ntfy_settings,
                    sms_enabled=False,
                    sms=None,
                )
                mock_publish_result = None
                mock_sms_result = None

            # Count log entries before the notification
            pre_count_result = await session.execute(
                select(NotificationLog)
            )
            pre_count = len(pre_count_result.scalars().all())

            # Patch external calls and invoke notify
            with patch(
                "src.pipeline.notification_service.publish",
                new_callable=AsyncMock,
            ) as mock_publish, patch(
                "src.pipeline.notification_service.send_sms",
                new_callable=AsyncMock,
            ) as mock_sms:
                if mock_publish_result is not None:
                    mock_publish.return_value = mock_publish_result
                if mock_sms_result is not None:
                    mock_sms.side_effect = mock_sms_result
                elif outcome == "sms_success":
                    from src.integrations.sms_gateway import Result as SMSResult
                    mock_sms.return_value = SMSResult(ok=True)

                await notify(session, job, trigger_reason, settings)

            # Verify: at least one new log entry was created
            post_count_result = await session.execute(
                select(NotificationLog)
            )
            post_entries = post_count_result.scalars().all()
            post_count = len(post_entries)

            assert post_count > pre_count, (
                f"No notification_log entry was created for outcome='{outcome}'. "
                f"Pre-count={pre_count}, post-count={post_count}. "
                f"Every notification attempt must be logged."
            )

            # Verify the new log entry has required fields
            new_entries = [e for e in post_entries if e.job_id == job_id]
            assert len(new_entries) >= 1, (
                f"Expected at least 1 log entry for job_id='{job_id}', "
                f"found {len(new_entries)}"
            )

            latest_entry = new_entries[-1]

            # Valid timestamp (ISO 8601 parseable)
            assert latest_entry.sent_at is not None, "sent_at must not be None"
            assert len(latest_entry.sent_at) > 0, "sent_at must not be empty"
            # Verify it's a valid ISO timestamp by parsing
            datetime.fromisoformat(latest_entry.sent_at)

            # Channel must be set
            assert latest_entry.channel is not None, "channel must not be None"
            assert latest_entry.channel in NotificationLog.VALID_CHANNELS, (
                f"channel '{latest_entry.channel}' is not a valid channel. "
                f"Valid: {NotificationLog.VALID_CHANNELS}"
            )

            # Success field must be set (0 or 1)
            assert latest_entry.success in (0, 1), (
                f"success must be 0 or 1, got {latest_entry.success}"
            )

            # Verify outcome matches expectation
            if outcome == "ntfy_success" or outcome == "sms_success":
                assert latest_entry.success == 1, (
                    f"Expected success=1 for outcome='{outcome}', "
                    f"got success={latest_entry.success}"
                )
            elif outcome in ("ntfy_fail_no_fallback", "both_disabled", "rate_limited"):
                assert latest_entry.success == 0, (
                    f"Expected success=0 for outcome='{outcome}', "
                    f"got success={latest_entry.success}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
