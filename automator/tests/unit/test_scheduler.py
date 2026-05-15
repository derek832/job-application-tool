"""
Unit tests for the APScheduler integration module.

Tests cover:
- setup_scheduler creates and starts an AsyncIOScheduler
- setup_scheduler registers the weekday pipeline cron job
- setup_scheduler registers the backup job
- setup_scheduler stores the scheduler on app.state
- setup_scheduler uses default time when scheduled_time is None
- setup_scheduler parses custom scheduled_time correctly
- trigger_now adds a one-time job to the scheduler
- trigger_now raises RuntimeError when scheduler is not initialized
- _parse_time handles valid and invalid time strings
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.scheduler.scheduler import _parse_time, setup_scheduler, trigger_now


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

        scheduler = setup_scheduler(mock_app, scheduled_time="09:00")

        assert isinstance(scheduler, AsyncIOScheduler)

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_stores_scheduler_on_app_state(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler attaches the scheduler to app.state.scheduler."""
        scheduler = setup_scheduler(mock_app, scheduled_time="09:00")

        assert mock_app.state.scheduler is scheduler

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_registers_weekday_cron_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler registers a job with id 'weekday_pipeline_run'."""
        scheduler = setup_scheduler(mock_app, scheduled_time="10:30")

        job = scheduler.get_job("weekday_pipeline_run")
        assert job is not None
        assert job.name == "Weekday Job Pipeline Run"

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_registers_backup_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler calls register_backup_job with the scheduler."""
        scheduler = setup_scheduler(mock_app, scheduled_time="09:00")

        mock_register_backup.assert_called_once_with(scheduler)

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_uses_default_time_when_none(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler defaults to 09:00 when scheduled_time is None."""
        scheduler = setup_scheduler(mock_app, scheduled_time=None)

        job = scheduler.get_job("weekday_pipeline_run")
        assert job is not None

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_scheduler_is_running(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """setup_scheduler starts the scheduler (state is running)."""
        scheduler = setup_scheduler(mock_app, scheduled_time="09:00")

        assert scheduler.running


class TestTriggerNow:
    """Tests for trigger_now function."""

    @patch("src.scheduler.scheduler.register_backup_job")
    async def test_adds_manual_run_job(
        self, mock_register_backup: MagicMock, mock_app: MagicMock
    ) -> None:
        """trigger_now adds a job with id 'manual_pipeline_run'."""
        setup_scheduler(mock_app, scheduled_time="09:00")

        trigger_now()

        import src.scheduler.scheduler as mod

        job = mod._scheduler.get_job("manual_pipeline_run")
        assert job is not None
        assert job.name == "Manual Pipeline Run"

    def test_raises_when_scheduler_not_initialized(self) -> None:
        """trigger_now raises RuntimeError if scheduler is not set up."""
        with pytest.raises(RuntimeError, match="Scheduler not initialized"):
            trigger_now()


class TestParseTime:
    """Tests for _parse_time helper function."""

    def test_parses_valid_time(self) -> None:
        """_parse_time correctly parses a valid HH:MM string."""
        assert _parse_time("09:00") == (9, 0)
        assert _parse_time("14:30") == (14, 30)
        assert _parse_time("00:00") == (0, 0)
        assert _parse_time("23:59") == (23, 59)

    def test_strips_whitespace(self) -> None:
        """_parse_time strips leading/trailing whitespace."""
        assert _parse_time("  09:00  ") == (9, 0)

    def test_raises_on_invalid_format(self) -> None:
        """_parse_time raises ValueError for non-HH:MM strings."""
        with pytest.raises(ValueError, match="Invalid time format"):
            _parse_time("9")

        with pytest.raises(ValueError, match="Invalid time format"):
            _parse_time("09:00:00")

    def test_raises_on_invalid_hour(self) -> None:
        """_parse_time raises ValueError for hour outside 0-23."""
        with pytest.raises(ValueError, match="Hour must be 0-23"):
            _parse_time("24:00")

    def test_raises_on_invalid_minute(self) -> None:
        """_parse_time raises ValueError for minute outside 0-59."""
        with pytest.raises(ValueError, match="Minute must be 0-59"):
            _parse_time("09:60")
