"""Unit tests for CAPTCHA polling loop in Escalation Engine.

Tests the poll_captcha_resolution function including:
- Successful CAPTCHA resolution detection
- 30-minute timeout behavior
- Domain recording for deduplication
- Graceful handling of page navigation errors
- Escalation record status update on resolution

Validates: Requirements 1.4, 1.6
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import (
    CAPTCHA_POLL_INTERVAL_SECONDS,
    CAPTCHA_POLL_MAX_DURATION_SECONDS,
    _page_has_captcha,
    _solved_captcha_domains,
    poll_captcha_resolution,
)


@pytest_asyncio.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def job_record(async_session: AsyncSession) -> JobRecord:
    """Insert and return a sample job record."""
    now = datetime.now(tz=UTC)
    record = JobRecord(
        id="job-captcha-001",
        job_title="Backend Engineer",
        company="TestCo",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/job-captcha-001",
        apply_type="external_apply",
        status="applying",
        fit_score=88,
        discovered_at=(now - timedelta(hours=1)).isoformat(),
        updated_at=now.isoformat(),
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest_asyncio.fixture
async def pending_captcha_escalation(
    async_session: AsyncSession, job_record: JobRecord
) -> EscalationRecord:
    """Create and return a pending CAPTCHA escalation record."""
    now = datetime.now(tz=UTC)
    record = EscalationRecord(
        id="esc-captcha-001",
        job_id=job_record.id,
        tier="captcha",
        form_state_snapshot='{"external_url": "https://boards.greenhouse.io/testco/jobs/1"}',
        draft_answers=None,
        timeout_deadline=None,
        freshness_tier=None,
        status="pending",
        resolution_method=None,
        created_at=now.isoformat(),
        resolved_at=None,
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.fixture(autouse=True)
def clear_solved_domains():
    """Clear the solved domains set before each test."""
    _solved_captcha_domains.clear()
    yield
    _solved_captcha_domains.clear()


# ---------------------------------------------------------------------------
# _page_has_captcha helper tests
# ---------------------------------------------------------------------------


class TestPageHasCaptcha:
    """Tests for the _page_has_captcha helper function."""

    @pytest.mark.asyncio
    async def test_detects_recaptcha(self) -> None:
        """Should detect reCAPTCHA text on page."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Please complete the reCAPTCHA below"
        )
        assert await _page_has_captcha(page) is True

    @pytest.mark.asyncio
    async def test_detects_hcaptcha(self) -> None:
        """Should detect hCaptcha text on page."""
        page = AsyncMock()
        page.inner_text = AsyncMock(return_value="Powered by hCaptcha")
        assert await _page_has_captcha(page) is True

    @pytest.mark.asyncio
    async def test_detects_generic_captcha(self) -> None:
        """Should detect generic CAPTCHA text."""
        page = AsyncMock()
        page.inner_text = AsyncMock(return_value="Solve the CAPTCHA to continue")
        assert await _page_has_captcha(page) is True

    @pytest.mark.asyncio
    async def test_detects_not_a_robot(self) -> None:
        """Should detect 'I'm not a robot' text."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Check the box: I'm not a robot"
        )
        assert await _page_has_captcha(page) is True

    @pytest.mark.asyncio
    async def test_detects_verify_human(self) -> None:
        """Should detect 'verify you are human' text."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Please verify you are human to continue"
        )
        assert await _page_has_captcha(page) is True

    @pytest.mark.asyncio
    async def test_no_captcha_on_normal_page(self) -> None:
        """Should return False for a normal page without CAPTCHA."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Apply for Senior Engineer at Acme Corp. Fill in your details below."
        )
        assert await _page_has_captcha(page) is False

    @pytest.mark.asyncio
    async def test_returns_true_on_page_error(self) -> None:
        """Should assume CAPTCHA present if page text can't be read."""
        page = AsyncMock()
        page.inner_text = AsyncMock(side_effect=Exception("Page disconnected"))
        assert await _page_has_captcha(page) is True


# ---------------------------------------------------------------------------
# poll_captcha_resolution tests
# ---------------------------------------------------------------------------


class TestPollCaptchaResolution:
    """Tests for the poll_captcha_resolution function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_captcha_resolved(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should return True when CAPTCHA is no longer detected on page."""
        page = AsyncMock()
        # First poll: CAPTCHA present, second poll: resolved
        page.inner_text = AsyncMock(
            side_effect=[
                "Please solve the captcha",
                "Welcome! Fill in your application details.",
            ]
        )
        page.url = "https://boards.greenhouse.io/testco/jobs/1"

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_updates_escalation_status_on_resolution(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should update escalation to resolved with captcha_solved method."""
        page = AsyncMock()
        # Immediately resolved on first poll
        page.inner_text = AsyncMock(
            return_value="Welcome! Fill in your application details."
        )
        page.url = "https://boards.greenhouse.io/testco/jobs/1"

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        # Refresh from DB
        await async_session.refresh(pending_captcha_escalation)
        assert pending_captcha_escalation.status == "resolved"
        assert pending_captcha_escalation.resolution_method == "captcha_solved"
        assert pending_captcha_escalation.resolved_at is not None

    @pytest.mark.asyncio
    async def test_records_solved_domain(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should record the solved domain in _solved_captcha_domains set."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Welcome! Fill in your application details."
        )
        page.url = "https://boards.greenhouse.io/testco/jobs/1"

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        assert "boards.greenhouse.io" in _solved_captcha_domains

    @pytest.mark.asyncio
    async def test_returns_false_after_30_minutes(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should return False if CAPTCHA not resolved within 30 minutes."""
        page = AsyncMock()
        # CAPTCHA always present
        page.inner_text = AsyncMock(return_value="Please solve the captcha")

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_stays_pending_on_timeout(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Escalation should remain pending if polling times out."""
        page = AsyncMock()
        page.inner_text = AsyncMock(return_value="Please solve the captcha")

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        await async_session.refresh(pending_captcha_escalation)
        assert pending_captcha_escalation.status == "pending"
        assert pending_captcha_escalation.resolved_at is None

    @pytest.mark.asyncio
    async def test_handles_page_error_gracefully(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should continue polling after page navigation errors."""
        page = AsyncMock()
        # First call: error, second call: error, third call: resolved
        page.inner_text = AsyncMock(
            side_effect=[
                Exception("Navigation failed"),
                Exception("Page crashed"),
                "Welcome! Application form loaded.",
            ]
        )
        page.url = "https://boards.greenhouse.io/testco/jobs/1"

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_update_already_resolved_escalation(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should not overwrite status if escalation was resolved externally."""
        # Simulate external resolution (e.g., 24h expiry handler ran)
        pending_captcha_escalation.status = "expired"
        pending_captcha_escalation.resolution_method = "timeout_expired"
        pending_captcha_escalation.resolved_at = datetime.now(tz=UTC).isoformat()
        await async_session.flush()

        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Welcome! Application form loaded."
        )
        page.url = "https://boards.greenhouse.io/testco/jobs/1"

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        # Still returns True (CAPTCHA is gone from page)
        assert result is True
        # But status should NOT be overwritten
        await async_session.refresh(pending_captcha_escalation)
        assert pending_captcha_escalation.status == "expired"
        assert pending_captcha_escalation.resolution_method == "timeout_expired"

    @pytest.mark.asyncio
    async def test_handles_domain_extraction_failure(
        self,
        async_session: AsyncSession,
        pending_captcha_escalation: EscalationRecord,
    ) -> None:
        """Should still resolve even if domain extraction fails."""
        page = AsyncMock()
        page.inner_text = AsyncMock(
            return_value="Welcome! Application form loaded."
        )
        # page.url raises an error
        type(page).url = property(lambda self: (_ for _ in ()).throw(Exception("No URL")))

        with patch("src.pipeline.escalation_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await poll_captcha_resolution(
                page=page,
                escalation_id=pending_captcha_escalation.id,
                session=async_session,
            )

        # Should still return True (CAPTCHA resolved)
        assert result is True
        # Escalation should still be updated
        await async_session.refresh(pending_captcha_escalation)
        assert pending_captcha_escalation.status == "resolved"


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestCaptchaPollingConstants:
    """Verify polling constants match requirements."""

    def test_poll_interval_is_5_seconds(self) -> None:
        """Requirement 1.4: Poll every 5 seconds."""
        assert CAPTCHA_POLL_INTERVAL_SECONDS == 5

    def test_max_duration_is_30_minutes(self) -> None:
        """Requirement 1.4: Poll for up to 30 minutes."""
        assert CAPTCHA_POLL_MAX_DURATION_SECONDS == 30 * 60
