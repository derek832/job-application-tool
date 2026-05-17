"""
Schedule Manager — Translates user schedule config into APScheduler triggers.

Supports two scheduling modes:
- specific_times: Multiple CronTrigger jobs, one per configured HH:MM time
- interval: IntervalTrigger with window constraints

Provides hot-reload via apply_schedule() which removes existing pipeline jobs
and registers new triggers from the current config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger(__name__)

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Job ID prefix used to identify schedule-managed pipeline jobs
_JOB_ID_PREFIX = "scheduled_pipeline_"


@dataclass
class ScheduleConfig:
    """User-configurable schedule for pipeline runs."""

    mode: Literal["specific_times", "interval"]
    times: list[str] = field(default_factory=list)  # HH:MM strings (specific_times mode)
    interval_hours: int = 2  # (interval mode)
    window_start: str = "08:00"  # HH:MM (interval mode)
    window_end: str = "20:00"  # HH:MM (interval mode)
    weekend_runs: bool = False
    timezone: str = "America/New_York"  # IANA timezone string
    quiet_hours_start: str | None = None  # HH:MM or None
    quiet_hours_end: str | None = None  # HH:MM or None


def validate_schedule_config(config: ScheduleConfig) -> None:
    """Validate a schedule configuration.

    Raises:
        ValueError: If the config is invalid (zero times in specific_times mode,
            invalid time formats, invalid interval, or invalid timezone).
    """
    # Validate timezone
    try:
        ZoneInfo(config.timezone)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid timezone: {config.timezone}") from exc

    if config.mode == "specific_times":
        # Reject zero times
        if not config.times:
            raise ValueError(
                "At least one time must be configured in specific_times mode"
            )
        # Validate each time format
        for time_str in config.times:
            if not _TIME_PATTERN.match(time_str):
                raise ValueError(
                    f"Invalid time format: '{time_str}'. Expected HH:MM (00:00-23:59)"
                )

    elif config.mode == "interval":
        # Validate interval_hours
        if config.interval_hours < 1:
            raise ValueError(
                f"interval_hours must be at least 1, got {config.interval_hours}"
            )
        # Validate window times
        if not _TIME_PATTERN.match(config.window_start):
            raise ValueError(
                f"Invalid window_start format: '{config.window_start}'. Expected HH:MM"
            )
        if not _TIME_PATTERN.match(config.window_end):
            raise ValueError(
                f"Invalid window_end format: '{config.window_end}'. Expected HH:MM"
            )
    else:
        raise ValueError(f"Invalid mode: '{config.mode}'. Must be 'specific_times' or 'interval'")

    # Validate quiet hours if provided
    if config.quiet_hours_start is not None:
        if not _TIME_PATTERN.match(config.quiet_hours_start):
            raise ValueError(
                f"Invalid quiet_hours_start format: '{config.quiet_hours_start}'. Expected HH:MM"
            )
    if config.quiet_hours_end is not None:
        if not _TIME_PATTERN.match(config.quiet_hours_end):
            raise ValueError(
                f"Invalid quiet_hours_end format: '{config.quiet_hours_end}'. Expected HH:MM"
            )


def compute_next_run_times(
    config: ScheduleConfig,
    now: datetime,
    count: int = 3,
) -> list[datetime]:
    """Compute the next N scheduled run times from the given config.

    Args:
        config: The schedule configuration.
        now: The reference datetime (timezone-aware).
        count: Number of future run times to compute.

    Returns:
        A list of up to `count` future datetimes in ascending order.
    """
    if config.mode == "specific_times":
        return compute_next_run_times_specific(
            times=config.times,
            weekend_runs=config.weekend_runs,
            timezone=config.timezone,
            now=now,
            count=count,
        )
    else:
        return compute_next_run_times_interval(
            interval_hours=config.interval_hours,
            window_start=config.window_start,
            window_end=config.window_end,
            weekend_runs=config.weekend_runs,
            timezone=config.timezone,
            now=now,
            count=count,
        )


def compute_next_run_times_specific(
    times: list[str],
    weekend_runs: bool,
    timezone: str,
    now: datetime,
    count: int = 3,
) -> list[datetime]:
    """Generate next N run times from a list of daily times.

    For each day starting from today, check each configured time.
    Skip weekends if weekend_runs is False.
    Collect until we have `count` future times.

    Args:
        times: List of HH:MM strings.
        weekend_runs: Whether to include Saturday/Sunday.
        timezone: IANA timezone string.
        now: Reference datetime (timezone-aware).
        count: Number of results to return.

    Returns:
        List of future datetimes in ascending order.
    """
    tz = ZoneInfo(timezone)
    results: list[datetime] = []
    current_date = now.astimezone(tz).date()

    # Safety limit to prevent infinite loops (scan up to 365 days ahead)
    max_days = 365

    for _ in range(max_days):
        if len(results) >= count:
            break

        weekday = current_date.weekday()  # 0=Mon, 6=Sun
        if weekend_runs or weekday < 5:
            for time_str in sorted(times):
                hour, minute = map(int, time_str.split(":"))
                candidate = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    hour,
                    minute,
                    tzinfo=tz,
                )
                if candidate > now.astimezone(tz):
                    results.append(candidate)
                    if len(results) >= count:
                        break

        current_date += timedelta(days=1)

    return results


def compute_next_run_times_interval(
    interval_hours: int,
    window_start: str,
    window_end: str,
    weekend_runs: bool,
    timezone: str,
    now: datetime,
    count: int = 3,
) -> list[datetime]:
    """Generate next N run times from an interval within a daily window.

    Starting from window_start, generate times every interval_hours
    until window_end. Skip weekends if disabled.

    Args:
        interval_hours: Hours between runs.
        window_start: HH:MM start of daily window.
        window_end: HH:MM end of daily window.
        weekend_runs: Whether to include Saturday/Sunday.
        timezone: IANA timezone string.
        now: Reference datetime (timezone-aware).
        count: Number of results to return.

    Returns:
        List of future datetimes in ascending order.
    """
    tz = ZoneInfo(timezone)
    start_h, start_m = map(int, window_start.split(":"))
    end_h, end_m = map(int, window_end.split(":"))
    results: list[datetime] = []
    current_date = now.astimezone(tz).date()

    # Safety limit to prevent infinite loops
    max_days = 365

    for _ in range(max_days):
        if len(results) >= count:
            break

        weekday = current_date.weekday()
        if weekend_runs or weekday < 5:
            t = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                start_h,
                start_m,
                tzinfo=tz,
            )
            end_time = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                end_h,
                end_m,
                tzinfo=tz,
            )
            while t <= end_time:
                if t > now.astimezone(tz):
                    results.append(t)
                    if len(results) >= count:
                        break
                t += timedelta(hours=interval_hours)

        current_date += timedelta(days=1)

    return results


def apply_schedule(
    scheduler: AsyncIOScheduler,
    config: ScheduleConfig,
) -> None:
    """Remove existing pipeline jobs and register new ones from config.

    For specific_times mode: one CronTrigger per configured time.
    For interval mode: one IntervalTrigger with window constraints.

    The weekend toggle is applied via the day_of_week parameter:
    - weekend_runs=False → "mon-fri"
    - weekend_runs=True → "mon-sun"

    Args:
        scheduler: The APScheduler AsyncIOScheduler instance.
        config: The validated schedule configuration.

    Raises:
        ValueError: If the config is invalid.
    """
    # Validate before applying
    validate_schedule_config(config)

    # Remove existing scheduled pipeline jobs
    _remove_existing_pipeline_jobs(scheduler)

    tz = ZoneInfo(config.timezone)
    day_of_week = "mon-sun" if config.weekend_runs else "mon-fri"

    if config.mode == "specific_times":
        _apply_specific_times(scheduler, config.times, day_of_week, tz)
    else:
        _apply_interval(
            scheduler,
            config.interval_hours,
            config.window_start,
            config.window_end,
            day_of_week,
            tz,
        )

    logger.info(
        "schedule_applied",
        mode=config.mode,
        day_of_week=day_of_week,
        timezone=config.timezone,
    )


def _remove_existing_pipeline_jobs(scheduler: AsyncIOScheduler) -> None:
    """Remove all jobs with the scheduled pipeline prefix."""
    jobs_to_remove = [
        job for job in scheduler.get_jobs()
        if job.id.startswith(_JOB_ID_PREFIX)
    ]
    for job in jobs_to_remove:
        scheduler.remove_job(job.id)
        logger.debug("removed_pipeline_job", job_id=job.id)

    if jobs_to_remove:
        logger.info("removed_existing_pipeline_jobs", count=len(jobs_to_remove))


async def _run_pipeline_wrapper() -> None:
    """Wrapper that imports and calls run_pipeline.

    Defers the import to avoid circular dependencies.
    """
    from src.pipeline.job_pipeline import run_pipeline

    logger.info("scheduled_pipeline_run_started")
    try:
        await run_pipeline()
    except Exception:
        logger.exception("scheduled_pipeline_run_failed")


def _apply_specific_times(
    scheduler: AsyncIOScheduler,
    times: list[str],
    day_of_week: str,
    tz: ZoneInfo,
) -> None:
    """Register one CronTrigger job per configured time.

    Args:
        scheduler: The APScheduler instance.
        times: List of HH:MM strings.
        day_of_week: APScheduler day_of_week expression.
        tz: Timezone for the triggers.
    """
    for i, time_str in enumerate(sorted(times)):
        hour, minute = map(int, time_str.split(":"))
        job_id = f"{_JOB_ID_PREFIX}specific_{i}_{time_str.replace(':', '')}"

        scheduler.add_job(
            _run_pipeline_wrapper,
            trigger=CronTrigger(
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
                timezone=tz,
            ),
            id=job_id,
            name=f"Pipeline Run at {time_str}",
            replace_existing=True,
        )

        logger.debug(
            "registered_specific_time_job",
            job_id=job_id,
            time=time_str,
            day_of_week=day_of_week,
        )

    logger.info(
        "specific_times_schedule_applied",
        times=sorted(times),
        day_of_week=day_of_week,
    )


def _apply_interval(
    scheduler: AsyncIOScheduler,
    interval_hours: int,
    window_start: str,
    window_end: str,
    day_of_week: str,
    tz: ZoneInfo,
) -> None:
    """Register an IntervalTrigger with window constraints.

    For interval mode, we use a CronTrigger that fires every interval_hours
    within the configured window. This is more reliable than IntervalTrigger
    for daily windowed schedules because it respects day boundaries.

    Args:
        scheduler: The APScheduler instance.
        interval_hours: Hours between runs.
        window_start: HH:MM start of daily window.
        window_end: HH:MM end of daily window.
        day_of_week: APScheduler day_of_week expression.
        tz: Timezone for the triggers.
    """
    start_h, start_m = map(int, window_start.split(":"))
    end_h, end_m = map(int, window_end.split(":"))

    # Generate all run hours within the window
    run_hours: list[int] = []

    # Calculate total minutes for start and end
    start_total_min = start_h * 60 + start_m
    end_total_min = end_h * 60 + end_m

    current_total_min = start_total_min
    while current_total_min <= end_total_min:
        run_hours.append(current_total_min // 60)
        current_total_min += interval_hours * 60

    if not run_hours:
        run_hours = [start_h]

    # Use a CronTrigger with explicit hours for windowed interval behavior
    # This ensures runs only happen within the window on the correct days
    hours_str = ",".join(str(h) for h in sorted(set(run_hours)))
    job_id = f"{_JOB_ID_PREFIX}interval_{interval_hours}h"

    scheduler.add_job(
        _run_pipeline_wrapper,
        trigger=CronTrigger(
            day_of_week=day_of_week,
            hour=hours_str,
            minute=start_m,
            timezone=tz,
        ),
        id=job_id,
        name=f"Pipeline Run every {interval_hours}h ({window_start}-{window_end})",
        replace_existing=True,
    )

    logger.info(
        "interval_schedule_applied",
        interval_hours=interval_hours,
        window=f"{window_start}-{window_end}",
        run_hours=hours_str,
        day_of_week=day_of_week,
    )
