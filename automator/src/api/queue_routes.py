"""
Human Queue API routes for the LinkedIn Job Automator.

Provides endpoints for listing pending queue items and resolving them via
approve, reject, or manual-apply actions. All endpoints require Bearer token
authentication.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import QueueItemOut
from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.job_repo import get_job_record, get_queue_items, update_job_status

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/queue", tags=["queue"])


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# GET /queue
# ---------------------------------------------------------------------------


@router.get("", response_model=list[QueueItemOut])
async def list_queue_items(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> list[QueueItemOut]:
    """Return all pending Human Queue items awaiting user review.

    Items are jobs with a non-null queue_reason and a non-terminal status.
    Results are ordered by most recently updated first.

    Returns:
        List of queue items with job title, company, reason, and fit details.
    """
    logger.info("list_queue_items_requested")

    records = await get_queue_items(session)
    return [
        QueueItemOut(
            job_id=record.id,
            job_title=record.job_title,
            company=record.company,
            linkedin_url=record.linkedin_url,
            queue_reason=record.queue_reason,
            fit_score=record.fit_score,
            fit_rationale=record.fit_rationale,
            added_at=record.updated_at,
        )
        for record in records
    ]


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/approve
# ---------------------------------------------------------------------------


@router.post("/{job_id}/approve", response_model=QueueItemOut)
async def approve_queue_item(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Approve a job in the Human Queue for application.

    Sets the job status to "approved_for_apply", clears the queue_reason,
    and records the approval timestamp. The scheduler will pick up the
    approved job for processing within 5 minutes.

    Args:
        job_id: The LinkedIn job ID to approve.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("approve_queue_item_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    now = _utcnow_iso()

    await update_job_status(session, job_id, "approved_for_apply", reason="user_approved")
    record.queue_reason = None
    record.approved_at = now
    record.updated_at = now
    await session.flush()

    logger.info("queue_item_approved", job_id=job_id)

    return QueueItemOut(
        job_id=record.id,
        job_title=record.job_title,
        company=record.company,
        linkedin_url=record.linkedin_url,
        queue_reason=record.queue_reason,
        fit_score=record.fit_score,
        fit_rationale=record.fit_rationale,
        added_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/reject
# ---------------------------------------------------------------------------


@router.post("/{job_id}/reject", response_model=QueueItemOut)
async def reject_queue_item(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Reject a job in the Human Queue.

    Sets the job status to "rejected_by_user" and clears the queue_reason.
    The job will no longer appear in the queue or be processed further.

    Args:
        job_id: The LinkedIn job ID to reject.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("reject_queue_item_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    now = _utcnow_iso()

    await update_job_status(session, job_id, "rejected_by_user", reason="user_rejected")
    record.queue_reason = None
    record.updated_at = now
    await session.flush()

    logger.info("queue_item_rejected", job_id=job_id)

    return QueueItemOut(
        job_id=record.id,
        job_title=record.job_title,
        company=record.company,
        linkedin_url=record.linkedin_url,
        queue_reason=record.queue_reason,
        fit_score=record.fit_score,
        fit_rationale=record.fit_rationale,
        added_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/manual
# ---------------------------------------------------------------------------


@router.post("/{job_id}/manual", response_model=QueueItemOut)
async def mark_manually_applied(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Mark a job in the Human Queue as manually applied.

    Sets the job status to "manually_applied", clears the queue_reason,
    and records the applied_at timestamp.

    Args:
        job_id: The LinkedIn job ID to mark as manually applied.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("mark_manually_applied_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    now = _utcnow_iso()

    await update_job_status(session, job_id, "manually_applied", reason="user_manual_apply")
    record.queue_reason = None
    record.applied_at = now
    record.updated_at = now
    await session.flush()

    logger.info("queue_item_manually_applied", job_id=job_id)

    return QueueItemOut(
        job_id=record.id,
        job_title=record.job_title,
        company=record.company,
        linkedin_url=record.linkedin_url,
        queue_reason=record.queue_reason,
        fit_score=record.fit_score,
        fit_rationale=record.fit_rationale,
        added_at=record.updated_at,
    )
