"""Unit tests for health check integration into the pipeline entry point.

Tests that run_pipeline():
- Skips the pipeline run and sends ntfy notification on health check failure
- Updates system_state.last_health_check_at on health check success

Validates: Requirements 2.1, 2.4, 2.8, 2.9
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.config_repo import get_config, set_config
from src.db.models import Base
from src.pipeline.health_checker import HealthCheckResult
from src.pipeline.job_pipeline import run_pipeline


@pytest_asyncio.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


async def _setup_pipeline_config(session: AsyncSession) -> None:
    """Set up the minimum config needed for the pipeline to reach the health check."""
    await set_config(session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        session,
        "goals_profile",
        {"target_titles": ["Engineer"], "deal_breakers": [], "open_to_stretch": True},
    )
    await set_config(session, "search_config", {"keywords": "python"})
    await set_config(session, "user_profile", {"full_name": "Test User"})
    await set_config(
        session,
        "settings",
        {"claude_api_key": "sk-test", "good_fit_threshold": 75, "stretch_threshold": 50},
    )
    # Enable ntfy so we can verify notification is sent on failure
    await set_config(session, "ntfy_enabled", True)
    await set_config(session, "ntfy_server_url", "https://ntfy.sh")
    await set_config(session, "ntfy_urgent_topic", "test-urgent-topic")
    await set_config(session, "ntfy_info_topic", "test-info-topic")
    await set_config(session, "api_token", "test-token")
    await session.commit()


@pytest.mark.asyncio
async def test_pipeline_skips_on_chrome_unreachable(async_session: AsyncSession):
    """Pipeline skips and sends ntfy notification when Chrome CDP is unreachable.

    Validates: Requirements 2.1, 2.4
    """
    await _setup_pipeline_config(async_session)

    failed_result = HealthCheckResult(
        chrome_reachable=False,
        linkedin_authenticated=False,
        error_message="Chrome CDP is not reachable",
        checked_at="2024-03-15T09:00:00+00:00",
    )

    mock_publish = AsyncMock()

    with (
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=failed_result,
        ),
        patch("src.pipeline.job_pipeline.publish", mock_publish),
        patch("src.pipeline.job_pipeline.async_playwright") as mock_pw,
    ):
        await run_pipeline(async_session)

        # Playwright should never be started (pipeline skipped)
        mock_pw.assert_not_called()

        # ntfy notification should be sent with specific failure reason
        mock_publish.assert_called_once()
        payload = mock_publish.call_args[0][0]
        assert "Chrome CDP is not reachable" in payload.message
        assert payload.priority == 4
        assert payload.tags == ["warning"]


@pytest.mark.asyncio
async def test_pipeline_skips_on_linkedin_session_expired(async_session: AsyncSession):
    """Pipeline skips and sends ntfy notification when LinkedIn session is expired.

    Validates: Requirements 2.4, 2.9
    """
    await _setup_pipeline_config(async_session)

    failed_result = HealthCheckResult(
        chrome_reachable=True,
        linkedin_authenticated=False,
        error_message="LinkedIn session expired — please log in to Chrome",
        checked_at="2024-03-15T09:00:00+00:00",
    )

    mock_publish = AsyncMock()

    with (
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=failed_result,
        ),
        patch("src.pipeline.job_pipeline.publish", mock_publish),
        patch("src.pipeline.job_pipeline.async_playwright") as mock_pw,
    ):
        await run_pipeline(async_session)

        # Playwright should never be started
        mock_pw.assert_not_called()

        # ntfy notification should contain the LinkedIn-specific message
        mock_publish.assert_called_once()
        payload = mock_publish.call_args[0][0]
        assert "LinkedIn session expired" in payload.message


@pytest.mark.asyncio
async def test_pipeline_updates_last_health_check_at_on_success(async_session: AsyncSession):
    """Pipeline updates system_state.last_health_check_at when health check passes.

    Validates: Requirements 2.8
    """
    await _setup_pipeline_config(async_session)

    healthy_result = HealthCheckResult(
        chrome_reachable=True,
        linkedin_authenticated=True,
        error_message=None,
        checked_at="2024-03-15T09:00:00+00:00",
    )

    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]

    mock_pw = AsyncMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    with (
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=healthy_result,
        ),
        patch("src.pipeline.job_pipeline.async_playwright") as mock_async_pw,
        patch(
            "src.pipeline.job_pipeline.discover_and_extract_jobs",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)
        await run_pipeline(async_session)

    # Verify system_state.last_health_check_at was updated
    state = await get_config(async_session, "system_state")
    assert state["last_health_check_at"] == "2024-03-15T09:00:00+00:00"


@pytest.mark.asyncio
async def test_pipeline_skips_without_notification_when_ntfy_disabled(
    async_session: AsyncSession,
):
    """Pipeline skips on health failure but doesn't crash when ntfy is disabled.

    Validates: Requirements 2.1, 2.4
    """
    # Set up config WITHOUT ntfy enabled
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        async_session,
        "goals_profile",
        {"target_titles": ["Engineer"], "deal_breakers": [], "open_to_stretch": True},
    )
    await set_config(async_session, "search_config", {"keywords": "python"})
    await set_config(async_session, "user_profile", {"full_name": "Test User"})
    await set_config(
        async_session,
        "settings",
        {"claude_api_key": "sk-test", "good_fit_threshold": 75, "stretch_threshold": 50},
    )
    await async_session.commit()

    failed_result = HealthCheckResult(
        chrome_reachable=False,
        linkedin_authenticated=False,
        error_message="Chrome CDP is not reachable",
        checked_at="2024-03-15T09:00:00+00:00",
    )

    mock_publish = AsyncMock()

    with (
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=failed_result,
        ),
        patch("src.pipeline.job_pipeline.publish", mock_publish),
        patch("src.pipeline.job_pipeline.async_playwright") as mock_pw,
    ):
        # Should not raise even without ntfy configured
        await run_pipeline(async_session)

        # Playwright should never be started
        mock_pw.assert_not_called()

        # ntfy publish should NOT be called (ntfy disabled)
        mock_publish.assert_not_called()
