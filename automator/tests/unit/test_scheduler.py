"""
Unit tests for the APScheduler integration module.

Tests cover:
- setup_scheduler creates and starts an AsyncIOScheduler
- setup_scheduler registers the weekday hourly pipeline cron job (8AM-8PM ET)
- setup_scheduler registers the backup job
- setup_scheduler stores the scheduler on app.state
- trigger_now adds a one-time job to the scheduler
- trigger_now raises RuntimeError when scheduler is not initialized
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.scheduler.scheduler import setup_scheduler, trigger_now


@pytest.fixture(autouse=True)
def reset_scheduler_global() -> None:
    """Reset the module-level _scheduler global before each test."""
    import src.scheduler.scheduler as mod

    mod._scheduler = None
    yield
    # Ensure cleanup after test — suppress errors from closed event loops
    if mod._scheduler is not None:
        try:
            if mod._scheduler.running:
                mod._scheduler.shutdown(wait=False)
        except RuntimeError:
            pass
    mod._scheduler = None


@pytest.fixture
def mock_app() -> MagicMock:
    """Create a mock FastAPI app with a state attribute."""
    app = MagicMock()
    app.state = MagicMock()
    return app


class TestSetupScheduler:
    """Tests for setup_scheduler function."""

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_returns_scheduler_instance(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler returns an AsyncIOScheduler instance."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = setup_scheduler(mock_app)

        assert isinstance(scheduler, AsyncIOScheduler)

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_stores_scheduler_on_app_state(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler attaches the scheduler to app.state.scheduler."""
        scheduler = setup_scheduler(mock_app)

        assert mock_app.state.scheduler is scheduler

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_registers_weekday_hourly_cron_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler registers an hourly job with id 'weekday_pipeline_run'."""
        scheduler = setup_scheduler(mock_app)

        job = scheduler.get_job("weekday_pipeline_run")
        assert job is not None
        assert job.name == "Weekday Hourly Job Pipeline Run (8AM-8PM ET)"

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_cron_trigger_uses_eastern_timezone(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler configures the cron trigger with America/New_York timezone."""
        from zoneinfo import ZoneInfo

        scheduler = setup_scheduler(mock_app)

        job = scheduler.get_job("weekday_pipeline_run")
        trigger = job.trigger
        assert trigger.timezone == ZoneInfo("America/New_York")

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_registers_backup_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler calls register_backup_job with the scheduler."""
        scheduler = setup_scheduler(mock_app)

        mock_register_backup.assert_called_once_with(scheduler)

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_scheduler_is_running(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler starts the scheduler (state is running)."""
        scheduler = setup_scheduler(mock_app)

        assert scheduler.running


class TestTriggerNow:
    """Tests for trigger_now function."""

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_adds_manual_run_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """trigger_now adds a job with id 'manual_pipeline_run'."""
        setup_scheduler(mock_app)

        trigger_now()

        import src.scheduler.scheduler as mod

        job = mod._scheduler.get_job("manual_pipeline_run")
        assert job is not None
        assert job.name == "Manual Pipeline Run"

    def test_raises_when_scheduler_not_initialized(self) -> None:
        """trigger_now raises RuntimeError if scheduler is not set up."""
        with pytest.raises(RuntimeError, match="Scheduler not initialized"):
            trigger_now()
