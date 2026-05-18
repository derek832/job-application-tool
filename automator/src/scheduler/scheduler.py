"""
APScheduler integration for the LinkedIn Job Automator.

Provides scheduler setup, weekday cron job registration, and manual trigger
functionality. The scheduler runs embedded within the FastAPI process using
APScheduler's AsyncIOScheduler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.scheduler.backup_job import register_backup_job

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

EASTERN_TZ = ZoneInfo("America/New_York")


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

    Does NOT register any pipeline cron jobs — those are managed entirely by
    the schedule_config in the database via apply_schedule(). This function
    only creates the scheduler, registers the daily backup job, and starts it.

    Args:
        app: The FastAPI application instance. The scheduler is attached to
            ``app.state.scheduler``.
        scheduled_time: Unused, retained for API compatibility.

    Returns:
        The configured and started AsyncIOScheduler instance.
    """
    global _scheduler  # noqa: PLW0603

    scheduler = AsyncIOScheduler(timezone=EASTERN_TZ)

    # Register the daily backup job
    register_backup_job(scheduler)

    # Start the scheduler
    scheduler.start()

    # Store on app state for access from routes
    app.state.scheduler = scheduler
    _scheduler = scheduler

    logger.info("scheduler_started", note="no hardcoded pipeline cron — schedule managed via UI")

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
