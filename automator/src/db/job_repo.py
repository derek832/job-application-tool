"""
Job record repository — CRUD and query operations for the job_records table.

All functions are async and operate on an ``AsyncSession`` passed by the caller.
Status transitions are validated against ``VALID_STATUSES`` before writing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import VALID_STATUSES, ExternalApplyLog, JobRecord, StatusTransition

logger = structlog.get_logger(__name__)

# Terminal statuses — jobs in these states are no longer actionable in the queue.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"applied", "skipped", "rejected_by_user", "manually_applied"}
)


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


async def create_job_record(session: AsyncSession, **fields: object) -> JobRecord:
    """Create a new JobRecord with status 'discovered' and current timestamps.

    Args:
        session: Active async database session.
        **fields: Column values for the new record. Must include at minimum
            ``id``, ``job_title``, ``company``, ``linkedin_url``, and
            ``apply_type``.

    Returns:
        The newly created ``JobRecord`` instance (already added to the session).
    """
    now = _utcnow_iso()
    record = JobRecord(
        status="discovered",
        discovered_at=now,
        updated_at=now,
        **fields,
    )
    session.add(record)
    await session.flush()

    logger.info(
        "job_record_created",
        job_id=record.id,
        job_title=record.job_title,
        company=record.company,
    )
    return record


async def get_job_record(session: AsyncSession, job_id: str) -> JobRecord | None:
    """Retrieve a single JobRecord by its primary key.

    Args:
        session: Active async database session.
        job_id: The LinkedIn job ID (primary key).

    Returns:
        The ``JobRecord`` if found, otherwise ``None``.
    """
    result = await session.execute(select(JobRecord).where(JobRecord.id == job_id))
    return result.scalar_one_or_none()


async def update_job_status(
    session: AsyncSession,
    job_id: str,
    new_status: str,
    reason: str | None = None,
) -> JobRecord:
    """Update a job's status and write a StatusTransition audit row.

    Validates that ``new_status`` is a member of ``VALID_STATUSES`` before
    making any changes. Raises ``ValueError`` if the status is invalid.

    Args:
        session: Active async database session.
        job_id: The LinkedIn job ID to update.
        new_status: Target status value (must be in ``VALID_STATUSES``).
        reason: Optional human-readable reason for the transition.

    Returns:
        The updated ``JobRecord``.

    Raises:
        ValueError: If ``new_status`` is not in ``VALID_STATUSES``.
        ValueError: If no JobRecord exists with the given ``job_id``.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {new_status!r}. Must be one of: {sorted(VALID_STATUSES)}")

    record = await get_job_record(session, job_id)
    if record is None:
        raise ValueError(f"No JobRecord found with id={job_id!r}")

    from_status = record.status
    now = _utcnow_iso()

    record.status = new_status
    record.updated_at = now

    transition = StatusTransition(
        job_id=job_id,
        from_status=from_status,
        to_status=new_status,
        reason=reason,
        timestamp=now,
    )
    session.add(transition)
    await session.flush()

    logger.info(
        "job_status_updated",
        job_id=job_id,
        from_status=from_status,
        to_status=new_status,
        reason=reason,
    )
    return record


async def list_jobs(
    session: AsyncSession,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> list[JobRecord]:
    """Return a paginated list of JobRecords with optional filters.

    Args:
        session: Active async database session.
        status: If provided, filter to records matching this status.
        search: If provided, filter to records where ``job_title`` or
            ``company`` contains this substring (case-insensitive).
        page: Page number (1-indexed). Defaults to 1.
        limit: Maximum records per page. Defaults to 20.

    Returns:
        List of matching ``JobRecord`` instances for the requested page.
    """
    query = select(JobRecord)

    if status is not None:
        query = query.where(JobRecord.status == status)

    if search is not None:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                JobRecord.job_title.ilike(pattern),
                JobRecord.company.ilike(pattern),
            )
        )

    offset = (page - 1) * limit
    query = query.order_by(JobRecord.discovered_at.desc()).offset(offset).limit(limit)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_stats(session: AsyncSession) -> dict[str, int | float]:
    """Return summary statistics across all job records.

    Returns:
        A dict with keys:
        - ``total_discovered``: count of all records
        - ``total_applied``: count with status 'applied'
        - ``total_skipped``: count with status 'skipped'
        - ``total_pending_review``: count of records with a non-null
          ``queue_reason`` and status not in terminal states
        - ``application_success_rate``: applied / approved_for_apply, or 0
    """
    # Total discovered (all records)
    total_result = await session.execute(select(func.count(JobRecord.id)))
    total_discovered = total_result.scalar_one()

    # Total applied
    applied_result = await session.execute(
        select(func.count(JobRecord.id)).where(JobRecord.status == "applied")
    )
    total_applied = applied_result.scalar_one()

    # Total skipped
    skipped_result = await session.execute(
        select(func.count(JobRecord.id)).where(JobRecord.status == "skipped")
    )
    total_skipped = skipped_result.scalar_one()

    # Total pending review (in queue, not terminal)
    pending_result = await session.execute(
        select(func.count(JobRecord.id)).where(
            JobRecord.queue_reason.isnot(None),
            JobRecord.status.notin_(TERMINAL_STATUSES),
        )
    )
    total_pending_review = pending_result.scalar_one()

    # Application success rate: applied / approved_for_apply (or 0)
    approved_result = await session.execute(
        select(func.count(JobRecord.id)).where(JobRecord.status == "approved_for_apply")
    )
    total_approved = approved_result.scalar_one()

    # For success rate, count all that were ever approved (now applied + still approved)
    # The rate is applied / (applied + approved_for_apply) — but per the design spec,
    # it's applied / approved_for_apply. Since approved jobs transition to applied,
    # we need to count all jobs that ever reached approved_for_apply.
    # The simplest correct approach: count applied + count still at approved_for_apply.
    denominator = total_applied + total_approved
    application_success_rate = (total_applied / denominator) if denominator > 0 else 0.0

    return {
        "total_discovered": total_discovered,
        "total_applied": total_applied,
        "total_skipped": total_skipped,
        "total_pending_review": total_pending_review,
        "application_success_rate": application_success_rate,
    }


async def get_queue_items(session: AsyncSession) -> list[JobRecord]:
    """Return all JobRecords currently in the human queue.

    A job is considered "in the queue" when it has a non-null ``queue_reason``
    and its status is not in a terminal state (applied, skipped,
    rejected_by_user, manually_applied).

    Returns:
        List of ``JobRecord`` instances awaiting human review.
    """
    query = (
        select(JobRecord)
        .where(
            JobRecord.queue_reason.isnot(None),
            JobRecord.status.notin_(TERMINAL_STATUSES),
        )
        .order_by(JobRecord.updated_at.desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_external_apply_stats(session: AsyncSession) -> dict[str, int | float]:
    """Return statistics on external apply attempts and extraction methods.

    Tracks how often DOM extraction succeeds vs. when vision would be needed,
    informing cost/architecture decisions about local model hosting.

    Returns:
        A dict with keys:
        - ``total_attempts``: total external apply attempts logged
        - ``dom_success``: attempts where DOM extraction found fields
        - ``dom_failed``: attempts where DOM extraction found no fields
        - ``vision_used``: attempts that fell back to Claude Vision
        - ``dom_success_rate``: dom_success / total_attempts (or 0)
        - ``avg_dom_fields``: average DOM fields found per attempt
        - ``avg_fields_filled``: average fields filled per attempt
        - ``outcomes``: dict of outcome → count
    """
    # Total attempts
    total_result = await session.execute(select(func.count(ExternalApplyLog.id)))
    total_attempts = total_result.scalar_one()

    if total_attempts == 0:
        return {
            "total_attempts": 0,
            "dom_success": 0,
            "dom_failed": 0,
            "vision_used": 0,
            "dom_success_rate": 0.0,
            "avg_dom_fields": 0.0,
            "avg_fields_filled": 0.0,
            "outcomes": {},
        }

    # Count by method
    dom_result = await session.execute(
        select(func.count(ExternalApplyLog.id)).where(ExternalApplyLog.method == "dom")
    )
    dom_success = dom_result.scalar_one()

    vision_result = await session.execute(
        select(func.count(ExternalApplyLog.id)).where(ExternalApplyLog.method == "vision")
    )
    vision_used = vision_result.scalar_one()

    none_result = await session.execute(
        select(func.count(ExternalApplyLog.id)).where(ExternalApplyLog.method == "none")
    )
    dom_failed = none_result.scalar_one()

    # Averages
    avg_dom_result = await session.execute(select(func.avg(ExternalApplyLog.dom_fields_found)))
    avg_dom_fields = avg_dom_result.scalar_one() or 0.0

    avg_filled_result = await session.execute(select(func.avg(ExternalApplyLog.fields_filled)))
    avg_fields_filled = avg_filled_result.scalar_one() or 0.0

    # Outcomes breakdown
    outcome_rows = await session.execute(
        select(ExternalApplyLog.outcome, func.count(ExternalApplyLog.id)).group_by(
            ExternalApplyLog.outcome
        )
    )
    outcomes = {row[0]: row[1] for row in outcome_rows.all()}

    dom_success_rate = dom_success / total_attempts if total_attempts > 0 else 0.0

    return {
        "total_attempts": total_attempts,
        "dom_success": dom_success,
        "dom_failed": dom_failed,
        "vision_used": vision_used,
        "dom_success_rate": round(dom_success_rate, 3),
        "avg_dom_fields": round(float(avg_dom_fields), 1),
        "avg_fields_filled": round(float(avg_fields_filled), 1),
        "outcomes": outcomes,
    }
