"""Integration tests for end-to-end notification flow.

Tests the full notification pipeline with a real in-memory SQLite database
and mocked external services (httpx for ntfy, send_sms for SMS gateway).

Validates: Requirements 1.1, 1.3, 8.1, 8.5, 9.1
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, NotificationLog, RunSummary
from src.integrations.ntfy_client import NtfySettings
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.notification_service import (
    NotificationSettings,
    notify,
    send_run_summary,
)
from src.pipeline.run_summary import RunStats, generate_summary_text, store_run_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    """Create an in-memory SQLite async engine with all tables."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncSession:
    """Provide an async session bound to the in-memory database."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess


@pytest.fixture
def ntfy_settings() -> NtfySettings:
    """Ntfy configuration for tests."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6g7h8",
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="test-bearer-token",
    )


@pytest.fixture
def sms_settings() -> SMSSettings:
    """SMS gateway configuration for tests."""
    return SMSSettings(
        gmail_user="derek@gmail.com",
        sms_gateway="5551234567@vtext.com",
    )


@pytest.fixture
def settings_both(ntfy_settings: NtfySettings, sms_settings: SMSSettings) -> NotificationSettings:
    """Notification settings with both ntfy and SMS enabled."""
    return NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=True,
        sms=sms_settings,
    )


@pytest.fixture
def settings_ntfy_only(ntfy_settings: NtfySettings) -> NotificationSettings:
    """Notification settings with ntfy only."""
    return NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=False,
        sms=None,
    )


@pytest.fixture
async def job_record(session: AsyncSession) -> JobRecord:
    """Insert and return a realistic job record in the database."""
    job = JobRecord(
        id="3987654321",
        job_title="Senior Backend Engineer",
        company="TechCorp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/view/3987654321",
        apply_type="easy_apply",
        status="scored",
        fit_score=82,
        queue_reason="stretch_role",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )
    session.add(job)
    await session.commit()
    return job


# ---------------------------------------------------------------------------
# Test 1: ntfy publish success — notification sent via ntfy, logged, SMS NOT called
# ---------------------------------------------------------------------------


class TestNtfyPublishSuccess:
    """Test that ntfy publish works end-to-end with real DB logging."""

    @respx.mock
    async def test_ntfy_publish_success_logs_correctly(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """When ntfy succeeds, notification is logged with channel='ntfy' and SMS is not called.

        Validates: Requirements 1.1, 8.1
        """
        # Mock ntfy server to return 200
        ntfy_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200, json={"id": "msg123"})
        )

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            await notify(session, job_record, "stretch_role", settings_both)
            await session.commit()

            # SMS should NOT be called when ntfy succeeds
            mock_sms.assert_not_awaited()

        # Verify ntfy was called
        assert ntfy_route.called
        assert ntfy_route.call_count == 1

        # Verify the notification log in the database
        result = await session.execute(select(NotificationLog))
        logs = result.scalars().all()
        assert len(logs) == 1

        log = logs[0]
        assert log.channel == "ntfy"
        assert log.success == 1
        assert log.error_message is None
        assert log.job_id == "3987654321"
        assert log.trigger_reason == "stretch_role"
        assert "Senior Backend Engineer" in log.sms_body
        assert "TechCorp" in log.sms_body

    @respx.mock
    async def test_ntfy_publish_payload_contains_required_fields(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """The ntfy POST body includes title, priority, tags, and action buttons.

        Validates: Requirements 1.1, 1.5
        """
        captured_request = None

        def capture_request(request):
            nonlocal captured_request
            captured_request = request
            return Response(200, json={"id": "msg456"})

        respx.post("https://ntfy.sh").mock(side_effect=capture_request)

        await notify(session, job_record, "stretch_role", settings_both)
        await session.commit()

        assert captured_request is not None
        import json

        body = json.loads(captured_request.content)
        assert body["title"] == "Job Automator"
        assert body["priority"] == 4
        assert "briefcase" in body["tags"]
        assert body["topic"] == "a1b2c3d4e5f6g7h8"
        # Action buttons should be present (job has queue_reason and lan_base_url)
        assert "actions" in body
        assert len(body["actions"]) == 2
        assert body["actions"][0]["label"] == "Approve"
        assert body["actions"][1]["label"] == "Reject"


# ---------------------------------------------------------------------------
# Test 2: SMS fallback when ntfy fails
# ---------------------------------------------------------------------------


class TestSmsFallback:
    """Test that SMS is used as fallback when ntfy fails after retries."""

    @respx.mock
    async def test_sms_fallback_on_ntfy_failure(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """When ntfy fails after all retries, SMS fallback is called and logged.

        Validates: Requirements 1.3, 8.5
        """
        # Mock ntfy to return 500 on all attempts (triggers retry exhaustion)
        respx.post("https://ntfy.sh").mock(
            return_value=Response(500, text="Internal Server Error")
        )

        from src.integrations.sms_gateway import Result

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            mock_sms.return_value = Result(ok=True)

            # Patch asyncio.sleep to avoid waiting for backoff delays
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await notify(session, job_record, "stretch_role", settings_both)
                await session.commit()

            # SMS fallback should have been called
            mock_sms.assert_awaited_once()

        # Verify the notification log records the SMS fallback
        result = await session.execute(select(NotificationLog))
        logs = result.scalars().all()
        assert len(logs) == 1

        log = logs[0]
        assert log.channel == "sms_fallback"
        assert log.success == 1
        assert log.job_id == "3987654321"

    @respx.mock
    async def test_sms_fallback_also_fails(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """When both ntfy and SMS fail, the failure is logged.

        Validates: Requirements 1.3, 8.5
        """
        respx.post("https://ntfy.sh").mock(
            return_value=Response(500, text="Server Error")
        )

        from src.integrations.sms_gateway import Result

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            mock_sms.return_value = Result(ok=False, error="SMTP connection refused")

            with patch("asyncio.sleep", new_callable=AsyncMock):
                await notify(session, job_record, "stretch_role", settings_both)
                await session.commit()

        # Verify the failure is logged
        result = await session.execute(select(NotificationLog))
        logs = result.scalars().all()
        assert len(logs) == 1

        log = logs[0]
        assert log.channel == "sms_fallback"
        assert log.success == 0
        assert log.error_message == "SMTP connection refused"

    @respx.mock
    async def test_no_sms_fallback_on_4xx_error(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """4xx errors do not retry and still trigger SMS fallback.

        Validates: Requirements 1.3, 8.5
        """
        # 4xx errors are not retried but should still trigger fallback
        respx.post("https://ntfy.sh").mock(
            return_value=Response(403, text="Forbidden")
        )

        from src.integrations.sms_gateway import Result

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            mock_sms.return_value = Result(ok=True)

            await notify(session, job_record, "stretch_role", settings_both)
            await session.commit()

            # SMS fallback should be called since ntfy failed
            mock_sms.assert_awaited_once()

        result = await session.execute(select(NotificationLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].channel == "sms_fallback"
        assert logs[0].success == 1


# ---------------------------------------------------------------------------
# Test 3: Rate limiting across both channels
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test that rate limiting blocks notifications after 10 sends in an hour."""

    async def _insert_successful_sends(
        self, session: AsyncSession, count: int, job_id: str
    ) -> None:
        """Insert N successful notification log entries within the last hour."""
        now = datetime.now(tz=UTC)
        for i in range(count):
            log = NotificationLog(
                job_id=job_id,
                trigger_reason="test_trigger",
                sms_body=f"Test notification {i}",
                sent_at=(now - timedelta(minutes=i + 1)).isoformat(),
                success=1,
                error_message=None,
                channel="ntfy" if i % 2 == 0 else "sms",
            )
            session.add(log)
        await session.flush()

    @respx.mock
    async def test_11th_notification_is_blocked(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """After 10 successful sends in the last hour, the 11th is rate-limited.

        Validates: Requirements 9.1
        """
        # Insert 10 successful sends (mix of ntfy and sms channels)
        await self._insert_successful_sends(session, 10, job_record.id)
        await session.commit()

        # Mock ntfy (should NOT be called due to rate limit)
        ntfy_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200, json={"id": "msg789"})
        )

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            await notify(session, job_record, "new_trigger", settings_both)
            await session.commit()

            # Neither channel should be called
            mock_sms.assert_not_awaited()

        assert not ntfy_route.called

        # Verify the rate-limited log entry
        result = await session.execute(
            select(NotificationLog).where(NotificationLog.trigger_reason == "new_trigger")
        )
        logs = result.scalars().all()
        assert len(logs) == 1

        log = logs[0]
        assert log.success == 0
        assert log.error_message == "rate_limited"

    @respx.mock
    async def test_10th_notification_is_allowed(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """The 10th notification (with 9 prior sends) is still allowed.

        Validates: Requirements 9.1
        """
        # Insert 9 successful sends
        await self._insert_successful_sends(session, 9, job_record.id)
        await session.commit()

        ntfy_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200, json={"id": "msg_ok"})
        )

        await notify(session, job_record, "allowed_trigger", settings_both)
        await session.commit()

        # Should be allowed through
        assert ntfy_route.called

        result = await session.execute(
            select(NotificationLog).where(NotificationLog.trigger_reason == "allowed_trigger")
        )
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].success == 1
        assert logs[0].channel == "ntfy"

    @respx.mock
    async def test_rate_limit_counts_both_channels(
        self,
        session: AsyncSession,
        job_record: JobRecord,
        settings_both: NotificationSettings,
    ) -> None:
        """Rate limit counts ntfy and SMS sends together in a shared counter.

        Validates: Requirements 9.1
        """
        # Insert 5 ntfy + 5 sms = 10 total successful sends
        now = datetime.now(tz=UTC)
        for i in range(5):
            session.add(
                NotificationLog(
                    job_id=job_record.id,
                    trigger_reason="ntfy_send",
                    sms_body=f"ntfy msg {i}",
                    sent_at=(now - timedelta(minutes=i + 1)).isoformat(),
                    success=1,
                    channel="ntfy",
                )
            )
        for i in range(5):
            session.add(
                NotificationLog(
                    job_id=job_record.id,
                    trigger_reason="sms_send",
                    sms_body=f"sms msg {i}",
                    sent_at=(now - timedelta(minutes=i + 6)).isoformat(),
                    success=1,
                    channel="sms",
                )
            )
        await session.commit()

        ntfy_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200)
        )

        await notify(session, job_record, "should_be_blocked", settings_both)
        await session.commit()

        # Should be blocked
        assert not ntfy_route.called

        result = await session.execute(
            select(NotificationLog).where(
                NotificationLog.trigger_reason == "should_be_blocked"
            )
        )
        log = result.scalars().first()
        assert log is not None
        assert log.success == 0
        assert log.error_message == "rate_limited"


# ---------------------------------------------------------------------------
# Test 4: Run summary generation and delivery after pipeline run
# ---------------------------------------------------------------------------


class TestRunSummaryFlow:
    """Test the full run summary generation, storage, and delivery flow."""

    @respx.mock
    async def test_run_summary_stored_and_published(
        self,
        session: AsyncSession,
        settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Run summary is stored in DB and published to the info topic.

        Validates: Requirements 5.1, 5.3
        """
        # Mock the info topic endpoint
        info_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200, json={"id": "summary_msg"})
        )

        # Generate stats and summary
        stats = RunStats(
            jobs_discovered=12,
            jobs_scored=10,
            jobs_approved=5,
            jobs_applied=3,
            jobs_skipped=4,
            jobs_escalated=2,
            errors=[],
        )
        summary_text = generate_summary_text(stats)

        # Store the summary
        record = await store_run_summary(session, stats, summary_text)
        await session.commit()

        # Publish to ntfy info topic
        await send_run_summary(session, summary_text, settings_ntfy_only)
        await session.commit()

        # Verify the summary was stored in the database
        result = await session.execute(select(RunSummary))
        summaries = result.scalars().all()
        assert len(summaries) == 1

        stored = summaries[0]
        assert stored.id == record.id
        assert stored.jobs_discovered == 12
        assert stored.jobs_scored == 10
        assert stored.jobs_applied == 3
        assert stored.jobs_skipped == 4
        assert stored.jobs_escalated == 2
        assert "found 12 jobs" in stored.summary
        assert len(stored.summary) <= 500

        # Verify ntfy was called with the info topic
        assert info_route.called
        import json

        request_body = json.loads(info_route.calls[0].request.content)
        assert request_body["topic"] == "i9j0k1l2m3n4o5p6"
        assert request_body["priority"] == 3
        assert "chart_with_upwards_trend" in request_body["tags"]
        assert request_body["title"] == "Job Automator"
        assert "found 12 jobs" in request_body["message"]

        # Verify the notification log for the summary publish
        result = await session.execute(
            select(NotificationLog).where(NotificationLog.trigger_reason == "run_summary")
        )
        log = result.scalars().first()
        assert log is not None
        assert log.channel == "ntfy"
        assert log.success == 1

    @respx.mock
    async def test_run_summary_with_errors(
        self,
        session: AsyncSession,
        settings_ntfy_only: NotificationSettings,
    ) -> None:
        """Run summary includes error information when errors occurred."""
        info_route = respx.post("https://ntfy.sh").mock(
            return_value=Response(200, json={"id": "err_msg"})
        )

        stats = RunStats(
            jobs_discovered=8,
            jobs_scored=6,
            jobs_approved=2,
            jobs_applied=1,
            jobs_skipped=3,
            jobs_escalated=1,
            errors=["Timeout on job 123", "Claude API rate limit"],
        )
        summary_text = generate_summary_text(stats)

        record = await store_run_summary(session, stats, summary_text)
        await session.commit()

        await send_run_summary(session, summary_text, settings_ntfy_only)
        await session.commit()

        # Verify errors are mentioned in the summary
        assert "Errors:" in summary_text or "error" in summary_text.lower()
        assert info_route.called

    @respx.mock
    async def test_run_summary_ntfy_failure_does_not_fallback_to_sms(
        self,
        session: AsyncSession,
        settings_both: NotificationSettings,
    ) -> None:
        """When ntfy fails for run summary, SMS fallback is NOT attempted.

        Run summaries are non-critical — no SMS fallback.
        """
        respx.post("https://ntfy.sh").mock(
            return_value=Response(500, text="Server Error")
        )

        with patch("src.pipeline.notification_service.send_sms") as mock_sms:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await send_run_summary(
                    session, "Run complete: found 5 jobs. No errors.", settings_both
                )
                await session.commit()

            # SMS should NOT be called for run summaries
            mock_sms.assert_not_awaited()

        # Verify failure is logged
        result = await session.execute(
            select(NotificationLog).where(NotificationLog.trigger_reason == "run_summary")
        )
        log = result.scalars().first()
        assert log is not None
        assert log.channel == "ntfy"
        assert log.success == 0

    async def test_run_summary_retention_enforced(
        self,
        session: AsyncSession,
    ) -> None:
        """After storing 21 summaries, only 20 are retained (oldest deleted)."""
        from src.pipeline.run_summary import store_run_summary as store

        # Insert 21 summaries
        for i in range(21):
            stats = RunStats(
                jobs_discovered=i + 1,
                jobs_scored=i,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=[],
            )
            text = generate_summary_text(stats)
            await store(session, stats, text)

        await session.commit()

        # Verify only 20 remain
        result = await session.execute(select(RunSummary))
        summaries = result.scalars().all()
        assert len(summaries) == 20
