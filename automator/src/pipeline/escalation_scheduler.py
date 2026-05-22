"""Escalation Scheduler — APScheduler integration for timeout jobs.

Manages one-shot APScheduler jobs that fire ``handle_timeout`` when a
human_review escalation's deadline expires. Jobs are registered at
escalation creation and cancelled when the user resolves before timeout.

On application startup, ``recover_pending_timeouts_on_startup`` re-registers
jobs for any pending escalations whose timeouts were lost during a container
restart.

Validates: Requirements 4.4, 4.6
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Prefix for escalation timeout job IDs to avoid collisions with other jobs
_JOB_ID_PREFIX = "escalation_timeout_"


def _get_scheduler() -> AsyncIOScheduler | None:
    """Retrieve the global APScheduler instance.

    Defers import to avoid circular dependencies at module load time.
    Returns None if the scheduler has not been initialized yet.
    """
    from src.scheduler.scheduler import _scheduler

    return _scheduler


def _make_job_id(escalation_id: str) -> str:
    """Build a deterministic job ID from the escalation ID."""
    return f"{_JOB_ID_PREFIX}{escalation_id}"


async def _timeout_job_wrapper(escalation_id: str) -> None:
    """APScheduler job target — calls handle_timeout with a fresh DB session.

    Defers imports to avoid circular dependencies and obtains its own
    database session since APScheduler invokes this outside of any
    request context.
    """
    from src.db.database import get_session
    from src.pipeline.escalation_engine import handle_timeout

    logger.info("escalation_timeout_fired", escalation_id=escalation_id)

    async for session in get_session():
        try:
            await handle_timeout(session, escalation_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "escalation_timeout_handler_failed",
                escalation_id=escalation_id,
            )
        break


def schedule_escalation_timeout(escalation_id: str, deadline: datetime) -> bool:
    """Schedule a one-shot APScheduler job to fire handle_timeout at deadline.

    Uses the escalation_id as part of the job ID for easy cancellation.
    If the scheduler is not available (e.g., during tests), logs a warning
    and returns False.

    Args:
        escalation_id: UUID string identifying the escalation record.
        deadline: Timezone-aware UTC datetime when auto-submit should fire.

    Returns:
        True if the job was successfully scheduled, False otherwise.
    """
    scheduler = _get_scheduler()

    if scheduler is None:
        logger.warning(
            "escalation_timeout_schedule_skipped",
            escalation_id=escalation_id,
            reason="scheduler_not_initialized",
        )
        return False

    job_id = _make_job_id(escalation_id)

    scheduler.add_job(
        _timeout_job_wrapper,
        trigger=DateTrigger(run_date=deadline),
        id=job_id,
        name=f"Escalation Timeout: {escalation_id}",
        args=[escalation_id],
        replace_existing=True,
    )

    logger.info(
        "escalation_timeout_scheduled",
        escalation_id=escalation_id,
        job_id=job_id,
        deadline=deadline.isoformat(),
    )

    return True


def cancel_escalation_timeout(escalation_id: str) -> bool:
    """Cancel a scheduled escalation timeout job.

    No-op if the job doesn't exist (already fired or never scheduled).

    Args:
        escalation_id: UUID string identifying the escalation record.

    Returns:
        True if the job was found and removed, False if it didn't exist
        or the scheduler is unavailable.
    """
    scheduler = _get_scheduler()

    if scheduler is None:
        logger.warning(
            "escalation_timeout_cancel_skipped",
            escalation_id=escalation_id,
            reason="scheduler_not_initialized",
        )
        return False

    job_id = _make_job_id(escalation_id)

    try:
        scheduler.remove_job(job_id)
        logger.info(
            "escalation_timeout_cancelled",
            escalation_id=escalation_id,
            job_id=job_id,
        )
        return True
    except JobLookupError:
        logger.debug(
            "escalation_timeout_cancel_noop",
            escalation_id=escalation_id,
            job_id=job_id,
            reason="job_not_found",
        )
        return False


# ---------------------------------------------------------------------------
# Startup Recovery — re-register pending timeout jobs after container restart
# ---------------------------------------------------------------------------


async def recover_pending_timeouts_on_startup(session: AsyncSession) -> None:
    """Recover pending escalation timeouts on application startup.

    Queries all escalation records where status="pending" AND timeout_deadline
    IS NOT NULL. For each record:
    - If the deadline is in the past: triggers immediate auto-submit via
      ``handle_timeout``.
    - If the deadline is in the future: re-registers the APScheduler job via
      ``schedule_escalation_timeout``.

    Logs a summary of how many escalations were auto-submitted vs re-scheduled.

    This function should be called during app startup (in the FastAPI lifespan)
    to handle any escalations whose timeouts expired while the container was
    down.

    Args:
        session: Active SQLAlchemy async session for DB operations.

    Validates: Requirements 4.4
    """
    from src.db.models import EscalationRecord
    from src.pipeline.escalation_engine import handle_timeout

    logger.info("recover_pending_timeouts_started")

    # Query all pending escalations with a non-null timeout_deadline
    stmt = select(EscalationRecord).where(
        EscalationRecord.status == "pending",
        EscalationRecord.timeout_deadline.isnot(None),
    )
    result = await session.execute(stmt)
    pending_records = list(result.scalars().all())

    if not pending_records:
        logger.info("recover_pending_timeouts_none_found")
        return

    now = datetime.now(tz=UTC)
    auto_submitted_count = 0
    rescheduled_count = 0

    for record in pending_records:
        # Parse the timeout_deadline (stored as ISO 8601 string)
        deadline = datetime.fromisoformat(record.timeout_deadline)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)

        if deadline <= now:
            # Deadline has passed — trigger immediate auto-submit
            logger.info(
                "recover_timeout_auto_submit",
                escalation_id=record.id,
                deadline=record.timeout_deadline,
                overdue_seconds=(now - deadline).total_seconds(),
            )
            await handle_timeout(session, record.id)
            auto_submitted_count += 1
        else:
            # Deadline is in the future — re-register APScheduler job
            scheduled = schedule_escalation_timeout(record.id, deadline)
            if scheduled:
                rescheduled_count += 1
                logger.info(
                    "recover_timeout_rescheduled",
                    escalation_id=record.id,
                    deadline=record.timeout_deadline,
                    remaining_seconds=(deadline - now).total_seconds(),
                )
            else:
                logger.warning(
                    "recover_timeout_reschedule_failed",
                    escalation_id=record.id,
                    deadline=record.timeout_deadline,
                    reason="scheduler_unavailable",
                )

    logger.info(
        "recover_pending_timeouts_complete",
        total_pending=len(pending_records),
        auto_submitted=auto_submitted_count,
        rescheduled=rescheduled_count,
    )
