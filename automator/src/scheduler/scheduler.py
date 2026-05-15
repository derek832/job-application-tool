"""
APScheduler integration for the LinkedIn Job Automator.

Provides scheduler setup, weekday cron job registration, and manual trigger
functionality. The scheduler runs embedded within the FastAPI process using
APScheduler's AsyncIOScheduler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scheduler.backup_job import register_backup_job

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_pipeline_wrapper() -> None:
    """Wrapper that imports and calls run_pipeline.

    Defers the import to avoid circular dependencies and to allow the pipeline
    module to be loaded after the scheduler is configured.
    """
    from src.pipeline.job_pipeline import run_pipeline

    logger.info("scheduled_pipeline_run_started")
    try:
        await run_pipeline()
    except Exception:
        logger.exception("scheduled_pipeline_run_failed")


def setup_scheduler(app: FastAPI, scheduled_time: str | None = None) -> AsyncIOScheduler:
    """Create, configure, and start the APScheduler instance.

    Registers a weekday cron job (Monday–Friday) at the configured time that
    triggers the job pipeline. Also registers the daily database backup job.
    The scheduler instance is stored on ``app.state.scheduler`` for access
    from route handlers.

    Args:
        app: The FastAPI application instance. The scheduler is attached to
            ``app.state.scheduler``.
        scheduled_time: Time in "HH:MM" format for the weekday cron job.
            Defaults to "09:00" if not provided or None.

    Returns:
        The configured and started AsyncIOScheduler instance.
    """
    global _scheduler  # noqa: PLW0603

    if scheduled_time is None:
        scheduled_time = "09:00"

    hour, minute = _parse_time(scheduled_time)

    scheduler = AsyncIOScheduler()

    # Register the weekday pipeline cron job (Mon-Fri)
    scheduler.add_job(
        _run_pipeline_wrapper,
        trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
        id="weekday_pipeline_run",
        name="Weekday Job Pipeline Run",
        replace_existing=True,
    )

    logger.info(
        "pipeline_cron_registered",
        job_id="weekday_pipeline_run",
        schedule=f"mon-fri at {hour:02d}:{minute:02d}",
    )

    # Register the daily backup job
    register_backup_job(scheduler)

    # Start the scheduler
    scheduler.start()

    # Store on app state for access from routes
    app.state.scheduler = scheduler
    _scheduler = scheduler

    logger.info("scheduler_started")

    return scheduler


def trigger_now() -> None:
    """Trigger an immediate pipeline run by adding a one-time job.

    Adds a run-once job to the scheduler that executes the pipeline immediately.
    This is used by the ``POST /run`` endpoint for manual triggers.

    Raises:
        RuntimeError: If the scheduler has not been initialized via
            ``setup_scheduler``.
    """
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call setup_scheduler() first.")

    _scheduler.add_job(
        _run_pipeline_wrapper,
        id="manual_pipeline_run",
        name="Manual Pipeline Run",
        replace_existing=True,
    )

    logger.info("manual_pipeline_run_triggered")


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse a time string in HH:MM format into hour and minute integers.

    Args:
        time_str: Time string in "HH:MM" format (e.g., "09:00", "14:30").

    Returns:
        A tuple of (hour, minute) as integers.

    Raises:
        ValueError: If the time string is not in valid HH:MM format.
    """
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format '{time_str}', expected HH:MM")

    hour = int(parts[0])
    minute = int(parts[1])

    if not (0 <= hour <= 23):
        raise ValueError(f"Hour must be 0-23, got {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"Minute must be 0-59, got {minute}")

    return hour, minute
