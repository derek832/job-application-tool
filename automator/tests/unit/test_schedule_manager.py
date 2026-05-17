"""
Unit tests for the schedule manager module.

Tests cover:
- ScheduleConfig dataclass creation
- validate_schedule_config: rejects zero times, invalid formats, invalid timezone
- compute_next_run_times_specific: generates correct future times
- compute_next_run_times_interval: generates correct interval times within window
- apply_schedule: removes old jobs and registers new triggers
- Weekend toggle behavior (day_of_week filtering)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.scheduler.schedule_manager import (
    _JOB_ID_PREFIX,
    ScheduleConfig,
    apply_schedule,
    compute_next_run_times,
    compute_next_run_times_interval,
    compute_next_run_times_specific,
    validate_schedule_config,
)

# --- Fixtures ---


@pytest.fixture
def eastern_tz() -> ZoneInfo:
    return ZoneInfo("America/New_York")


@pytest.fixture
def specific_times_config() -> ScheduleConfig:
    return ScheduleConfig(
        mode="specific_times",
        times=["09:00", "13:00", "17:00"],
        weekend_runs=False,
        timezone="America/New_York",
    )


@pytest.fixture
def interval_config() -> ScheduleConfig:
    return ScheduleConfig(
        mode="interval",
        interval_hours=2,
        window_start="08:00",
        window_end="20:00",
        weekend_runs=False,
        timezone="America/New_York",
    )


@pytest.fixture
async def scheduler() -> AsyncIOScheduler:
    """Create a real APScheduler instance for testing (requires event loop)."""
    sched = AsyncIOScheduler(timezone=ZoneInfo("America/New_York"))
    sched.start()
    yield sched
    if sched.running:
        sched.shutdown(wait=False)


# --- validate_schedule_config tests ---


class TestValidateScheduleConfig:
    """Tests for validate_schedule_config."""

    def test_valid_specific_times_config(self, specific_times_config: ScheduleConfig) -> None:
        """Valid specific_times config passes validation."""
        validate_schedule_config(specific_times_config)  # Should not raise

    def test_valid_interval_config(self, interval_config: ScheduleConfig) -> None:
        """Valid interval config passes validation."""
        validate_schedule_config(interval_config)  # Should not raise

    def test_rejects_zero_times_in_specific_mode(self) -> None:
        """Rejects config with empty times list in specific_times mode."""
        config = ScheduleConfig(mode="specific_times", times=[])
        with pytest.raises(ValueError, match="At least one time"):
            validate_schedule_config(config)

    def test_rejects_invalid_time_format_letters(self) -> None:
        """Rejects time strings that aren't HH:MM."""
        config = ScheduleConfig(mode="specific_times", times=["9:00"])
        with pytest.raises(ValueError, match="Invalid time format"):
            validate_schedule_config(config)

    def test_rejects_invalid_time_format_out_of_range(self) -> None:
        """Rejects time strings with hours > 23 or minutes > 59."""
        config = ScheduleConfig(mode="specific_times", times=["25:00"])
        with pytest.raises(ValueError, match="Invalid time format"):
            validate_schedule_config(config)

    def test_rejects_invalid_time_format_minutes(self) -> None:
        """Rejects time strings with minutes > 59."""
        config = ScheduleConfig(mode="specific_times", times=["09:60"])
        with pytest.raises(ValueError, match="Invalid time format"):
            validate_schedule_config(config)

    def test_rejects_invalid_timezone(self) -> None:
        """Rejects config with invalid timezone string."""
        config = ScheduleConfig(
            mode="specific_times",
            times=["09:00"],
            timezone="Invalid/Timezone",
        )
        with pytest.raises(ValueError, match="Invalid timezone"):
            validate_schedule_config(config)

    def test_rejects_zero_interval_hours(self) -> None:
        """Rejects interval config with interval_hours < 1."""
        config = ScheduleConfig(
            mode="interval",
            interval_hours=0,
            window_start="08:00",
            window_end="20:00",
        )
        with pytest.raises(ValueError, match="interval_hours must be at least 1"):
            validate_schedule_config(config)

    def test_rejects_invalid_window_start(self) -> None:
        """Rejects interval config with invalid window_start."""
        config = ScheduleConfig(
            mode="interval",
            interval_hours=2,
            window_start="8:00",
            window_end="20:00",
        )
        with pytest.raises(ValueError, match="Invalid window_start format"):
            validate_schedule_config(config)

    def test_rejects_invalid_window_end(self) -> None:
        """Rejects interval config with invalid window_end."""
        config = ScheduleConfig(
            mode="interval",
            interval_hours=2,
            window_start="08:00",
            window_end="8pm",
        )
        with pytest.raises(ValueError, match="Invalid window_end format"):
            validate_schedule_config(config)

    def test_rejects_invalid_quiet_hours_start(self) -> None:
        """Rejects config with invalid quiet_hours_start."""
        config = ScheduleConfig(
            mode="specific_times",
            times=["09:00"],
            quiet_hours_start="10pm",
        )
        with pytest.raises(ValueError, match="Invalid quiet_hours_start format"):
            validate_schedule_config(config)

    def test_rejects_invalid_quiet_hours_end(self) -> None:
        """Rejects config with invalid quiet_hours_end."""
        config = ScheduleConfig(
            mode="specific_times",
            times=["09:00"],
            quiet_hours_end="7am",
        )
        with pytest.raises(ValueError, match="Invalid quiet_hours_end format"):
            validate_schedule_config(config)


# --- compute_next_run_times_specific tests ---


class TestComputeNextRunTimesSpecific:
    """Tests for compute_next_run_times_specific."""

    def test_returns_future_times_only(self, eastern_tz: ZoneInfo) -> None:
        """All returned times are in the future relative to now."""
        # Wednesday at 10:00 AM
        now = datetime(2024, 3, 13, 10, 0, tzinfo=eastern_tz)
        times = ["09:00", "13:00", "17:00"]

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        assert len(results) == 3
        for t in results:
            assert t > now

    def test_skips_past_times_today(self, eastern_tz: ZoneInfo) -> None:
        """Times earlier today are skipped."""
        # Wednesday at 14:00 — 09:00 and 13:00 are in the past
        now = datetime(2024, 3, 13, 14, 0, tzinfo=eastern_tz)
        times = ["09:00", "13:00", "17:00"]

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        # First result should be 17:00 today
        assert results[0].hour == 17
        assert results[0].day == 13

    def test_ascending_order(self, eastern_tz: ZoneInfo) -> None:
        """Results are in strictly ascending chronological order."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)
        times = ["09:00", "13:00", "17:00"]

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=5,
        )

        for i in range(len(results) - 1):
            assert results[i] < results[i + 1]

    def test_skips_weekends_when_disabled(self, eastern_tz: ZoneInfo) -> None:
        """No results fall on Saturday or Sunday when weekend_runs=False."""
        # Friday at 18:00 — next times should be Monday
        now = datetime(2024, 3, 15, 18, 0, tzinfo=eastern_tz)
        times = ["09:00", "13:00", "17:00"]

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        for t in results:
            assert t.weekday() < 5  # 0=Mon, 4=Fri

    def test_includes_weekends_when_enabled(self, eastern_tz: ZoneInfo) -> None:
        """Results can include Saturday/Sunday when weekend_runs=True."""
        # Friday at 18:00
        now = datetime(2024, 3, 15, 18, 0, tzinfo=eastern_tz)
        times = ["09:00"]

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=True,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        # Saturday should be included
        assert results[0].weekday() == 5  # Saturday

    def test_times_match_configured_hours(self, eastern_tz: ZoneInfo) -> None:
        """Each result's hour:minute matches one of the configured times."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)
        times = ["09:00", "13:00", "17:00"]
        configured_set = {(9, 0), (13, 0), (17, 0)}

        results = compute_next_run_times_specific(
            times=times,
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=6,
        )

        for t in results:
            assert (t.hour, t.minute) in configured_set


# --- compute_next_run_times_interval tests ---


class TestComputeNextRunTimesInterval:
    """Tests for compute_next_run_times_interval."""

    def test_returns_future_times_only(self, eastern_tz: ZoneInfo) -> None:
        """All returned times are in the future."""
        now = datetime(2024, 3, 13, 10, 0, tzinfo=eastern_tz)

        results = compute_next_run_times_interval(
            interval_hours=2,
            window_start="08:00",
            window_end="20:00",
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        assert len(results) == 3
        for t in results:
            assert t > now

    def test_times_within_window(self, eastern_tz: ZoneInfo) -> None:
        """All returned times fall within the configured window."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)

        results = compute_next_run_times_interval(
            interval_hours=2,
            window_start="08:00",
            window_end="20:00",
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=6,
        )

        for t in results:
            total_min = t.hour * 60 + t.minute
            assert total_min >= 8 * 60  # >= 08:00
            assert total_min <= 20 * 60  # <= 20:00

    def test_consecutive_same_day_interval(self, eastern_tz: ZoneInfo) -> None:
        """Consecutive times on the same day are exactly interval_hours apart."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)

        results = compute_next_run_times_interval(
            interval_hours=3,
            window_start="08:00",
            window_end="20:00",
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=4,
        )

        # Filter to same day
        same_day = [t for t in results if t.date() == results[0].date()]
        for i in range(len(same_day) - 1):
            diff = same_day[i + 1] - same_day[i]
            assert diff.total_seconds() == 3 * 3600

    def test_skips_weekends_when_disabled(self, eastern_tz: ZoneInfo) -> None:
        """No results on weekends when weekend_runs=False."""
        # Friday at 21:00 — past window end
        now = datetime(2024, 3, 15, 21, 0, tzinfo=eastern_tz)

        results = compute_next_run_times_interval(
            interval_hours=2,
            window_start="08:00",
            window_end="20:00",
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=3,
        )

        for t in results:
            assert t.weekday() < 5

    def test_ascending_order(self, eastern_tz: ZoneInfo) -> None:
        """Results are in strictly ascending order."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)

        results = compute_next_run_times_interval(
            interval_hours=2,
            window_start="08:00",
            window_end="20:00",
            weekend_runs=False,
            timezone="America/New_York",
            now=now,
            count=5,
        )

        for i in range(len(results) - 1):
            assert results[i] < results[i + 1]


# --- compute_next_run_times dispatch tests ---


class TestComputeNextRunTimes:
    """Tests for the dispatch function compute_next_run_times."""

    def test_dispatches_to_specific_times(
        self, specific_times_config: ScheduleConfig, eastern_tz: ZoneInfo
    ) -> None:
        """Dispatches to specific_times implementation."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)
        results = compute_next_run_times(specific_times_config, now, count=3)
        assert len(results) == 3

    def test_dispatches_to_interval(
        self, interval_config: ScheduleConfig, eastern_tz: ZoneInfo
    ) -> None:
        """Dispatches to interval implementation."""
        now = datetime(2024, 3, 13, 7, 0, tzinfo=eastern_tz)
        results = compute_next_run_times(interval_config, now, count=3)
        assert len(results) == 3


# --- apply_schedule tests ---


class TestApplySchedule:
    """Tests for apply_schedule."""

    async def test_registers_cron_jobs_for_specific_times(
        self, scheduler: AsyncIOScheduler, specific_times_config: ScheduleConfig
    ) -> None:
        """Registers one CronTrigger job per configured time."""
        apply_schedule(scheduler, specific_times_config)

        jobs = [j for j in scheduler.get_jobs() if j.id.startswith(_JOB_ID_PREFIX)]
        assert len(jobs) == 3  # 3 configured times

    async def test_registers_interval_job(
        self, scheduler: AsyncIOScheduler, interval_config: ScheduleConfig
    ) -> None:
        """Registers a single job for interval mode."""
        apply_schedule(scheduler, interval_config)

        jobs = [j for j in scheduler.get_jobs() if j.id.startswith(_JOB_ID_PREFIX)]
        assert len(jobs) == 1

    async def test_removes_existing_pipeline_jobs_on_reapply(
        self, scheduler: AsyncIOScheduler, specific_times_config: ScheduleConfig
    ) -> None:
        """Reapplying schedule removes old jobs before adding new ones."""
        apply_schedule(scheduler, specific_times_config)

        # Change to interval mode
        interval_config = ScheduleConfig(
            mode="interval",
            interval_hours=2,
            window_start="08:00",
            window_end="20:00",
        )
        apply_schedule(scheduler, interval_config)

        jobs = [j for j in scheduler.get_jobs() if j.id.startswith(_JOB_ID_PREFIX)]
        # Should only have the interval job, not the old specific_times jobs
        assert len(jobs) == 1

    async def test_weekday_only_trigger(
        self, scheduler: AsyncIOScheduler
    ) -> None:
        """weekend_runs=False sets day_of_week to mon-fri."""
        config = ScheduleConfig(
            mode="specific_times",
            times=["09:00"],
            weekend_runs=False,
        )
        apply_schedule(scheduler, config)

        jobs = [j for j in scheduler.get_jobs() if j.id.startswith(_JOB_ID_PREFIX)]
        assert len(jobs) == 1
        # Check the trigger's day_of_week field
        trigger = jobs[0].trigger
        day_field = str(trigger.fields[trigger.FIELD_NAMES.index("day_of_week")])
        assert "sat" not in day_field.lower() or "mon-fri" in day_field.lower()

    async def test_all_days_trigger(
        self, scheduler: AsyncIOScheduler
    ) -> None:
        """weekend_runs=True sets day_of_week to mon-sun."""
        config = ScheduleConfig(
            mode="specific_times",
            times=["09:00"],
            weekend_runs=True,
        )
        apply_schedule(scheduler, config)

        jobs = [j for j in scheduler.get_jobs() if j.id.startswith(_JOB_ID_PREFIX)]
        assert len(jobs) == 1

    async def test_rejects_invalid_config(self, scheduler: AsyncIOScheduler) -> None:
        """apply_schedule raises ValueError for invalid config."""
        config = ScheduleConfig(mode="specific_times", times=[])
        with pytest.raises(ValueError):
            apply_schedule(scheduler, config)

    async def test_does_not_remove_non_pipeline_jobs(
        self, scheduler: AsyncIOScheduler, specific_times_config: ScheduleConfig
    ) -> None:
        """Non-pipeline jobs are preserved when schedule is reapplied."""
        # Add a non-pipeline job
        scheduler.add_job(
            lambda: None,
            "interval",
            hours=24,
            id="backup_job",
            name="Daily Backup",
        )

        apply_schedule(scheduler, specific_times_config)

        backup_job = scheduler.get_job("backup_job")
        assert backup_job is not None
