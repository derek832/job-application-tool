"""
Human Queue API routes for the LinkedIn Job Automator.

Provides endpoints for listing pending queue items and resolving them via
approve, skip, applied, or decline actions. Approve triggers immediate
tailoring as a background task.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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


def _to_queue_item(record) -> QueueItemOut:
    """Convert a JobRecord to a QueueItemOut response."""
    return QueueItemOut(
        job_id=record.id,
        job_title=record.job_title,
        company=record.company,
        linkedin_url=record.linkedin_url,
        queue_reason=record.queue_reason,
        fit_score=record.fit_score,
        fit_rationale=record.fit_rationale,
        status=record.status,
        tailored_resume_pdf=record.tailored_resume_pdf,
        tailored_resume_text=record.tailored_resume_text,
        added_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /queue
# ---------------------------------------------------------------------------


@router.get("", response_model=list[QueueItemOut])
async def list_queue_items(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> list[QueueItemOut]:
    """Return all pending queue items.

    Includes two categories:
    - "Needs Review": status=scored with a queue_reason (threshold/stretch)
    - "Ready to Apply": status=tailored (PDF ready, awaiting user action)

    Results are ordered by most recently updated first.
    """
    logger.info("list_queue_items_requested")

    records = await get_queue_items(session)
    return [_to_queue_item(record) for record in records]


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/approve — trigger immediate tailoring
# ---------------------------------------------------------------------------


@router.post("/{job_id}/approve", response_model=QueueItemOut)
async def approve_queue_item(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Approve a threshold/stretch job for tailoring.

    Clears the queue_reason and kicks off immediate resume tailoring as a
    background task. The job will reappear in the queue with status "tailored"
    once tailoring completes (typically 10-20 seconds).

    Args:
        job_id: The LinkedIn job ID to approve.

    Returns:
        The updated queue item (status still "scored" — tailoring is async).

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("approve_queue_item_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    now = _utcnow_iso()

    # Clear queue reason so it doesn't show in "Needs Review" anymore
    record.queue_reason = None
    record.approved_at = now
    record.updated_at = now
    await session.flush()

    logger.info("queue_item_approved_for_tailoring", job_id=job_id)

    # Schedule immediate tailoring in background
    background_tasks.add_task(_run_tailoring_for_job, job_id)

    return _to_queue_item(record)


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/skip — remove from queue without tailoring
# ---------------------------------------------------------------------------


@router.post("/{job_id}/skip", response_model=QueueItemOut)
async def skip_queue_item(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Skip a job in the review queue.

    Sets the job status to "skipped" and removes it from the queue.
    Used for threshold/stretch jobs the user doesn't want to pursue.

    Args:
        job_id: The LinkedIn job ID to skip.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("skip_queue_item_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    await update_job_status(session, job_id, "skipped", reason="user_skipped")
    record.queue_reason = None
    record.updated_at = _utcnow_iso()
    await session.flush()

    logger.info("queue_item_skipped", job_id=job_id)
    return _to_queue_item(record)


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/applied — user manually applied
# ---------------------------------------------------------------------------


@router.post("/{job_id}/applied", response_model=QueueItemOut)
async def mark_applied(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Mark a tailored job as applied.

    Sets the job status to "applied" and records the timestamp.
    Used after the user has manually submitted their application.

    Args:
        job_id: The LinkedIn job ID to mark as applied.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("mark_applied_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    now = _utcnow_iso()

    await update_job_status(session, job_id, "applied", reason="user_applied_manually")
    record.queue_reason = None
    record.applied_at = now
    record.updated_at = now
    await session.flush()

    logger.info("queue_item_applied", job_id=job_id)
    return _to_queue_item(record)


# ---------------------------------------------------------------------------
# POST /queue/{job_id}/decline — user chose not to apply
# ---------------------------------------------------------------------------


@router.post("/{job_id}/decline", response_model=QueueItemOut)
async def decline_queue_item(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> QueueItemOut:
    """Decline a tailored job — user decided not to apply.

    Sets the job status to "declined" and removes it from the queue.

    Args:
        job_id: The LinkedIn job ID to decline.

    Returns:
        The resolved queue item.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("decline_queue_item_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    await update_job_status(session, job_id, "declined", reason="user_declined")
    record.queue_reason = None
    record.updated_at = _utcnow_iso()
    await session.flush()

    logger.info("queue_item_declined", job_id=job_id)
    return _to_queue_item(record)


# ---------------------------------------------------------------------------
# Background task: immediate tailoring
# ---------------------------------------------------------------------------


async def _run_tailoring_for_job(job_id: str) -> None:
    """Run tailoring for a single job as a background task.

    Creates its own DB session and loads required clients. On failure,
    logs the error but does not raise (background tasks should not crash).
    """
    from src.db.database import async_session_factory

    async with async_session_factory() as session:
        record = await get_job_record(session, job_id)
        if record is None:
            logger.error("bg_tailoring_job_not_found", job_id=job_id)
            return

        # Load required config
        from src.db.config_repo import get_config

        settings_raw = await get_config(session, "settings")
        goals_raw = await get_config(session, "goals_profile")
        profile_raw = await get_config(session, "user_profile")

        if not settings_raw or not settings_raw.get("claude_api_key"):
            logger.error("bg_tailoring_no_api_key", job_id=job_id)
            return

        from src.agents.claude_client import ClaudeClient
        from src.api.schemas import GoalsProfile, UserProfile
        from src.integrations.gdocs_client import GDocsClient
        from src.pipeline.tailoring_stage import restore_resume_base, run_tailoring

        claude_client = ClaudeClient(api_key=settings_raw["claude_api_key"])
        goals_profile = GoalsProfile.model_validate(goals_raw or {})
        user_profile = UserProfile.model_validate(profile_raw or {})

        gdocs_url = settings_raw.get("gdocs_script_url")
        if not gdocs_url:
            logger.error("bg_tailoring_no_gdocs_url", job_id=job_id)
            return

        gdocs_client = GDocsClient(script_url=gdocs_url)

        try:
            await run_tailoring(
                job_record=record,
                session=session,
                gdocs_client=gdocs_client,
                claude_client=claude_client,
                supplementary_context=goals_profile.supplementary_context,
                user_full_name=user_profile.full_name,
            )

            # Restore resume base after tailoring
            await restore_resume_base(
                job_record=record,
                gdocs_client=gdocs_client,
                session=session,
            )

            await session.commit()
            logger.info("bg_tailoring_complete", job_id=job_id)

        except Exception as exc:
            logger.error("bg_tailoring_failed", job_id=job_id, error=str(exc))
            await session.rollback()
