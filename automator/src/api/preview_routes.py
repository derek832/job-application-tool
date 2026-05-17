"""
Preview pipeline API routes for the LinkedIn Job Automator.

Provides endpoints for triggering preview/dry-run pipeline executions,
retrieving preview results, and promoting selected jobs to the real pipeline.

Validates: Requirements 1.3, 1.4, 1.7, 1.8
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.models import PreviewJob, PreviewRun
from src.pipeline.preview_pipeline import promote_preview_jobs, run_preview

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/preview", tags=["preview"])


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class PreviewTriggerResponse(BaseModel):
    """Response returned when a preview run is triggered.

    Attributes:
        run_id: The unique identifier for the preview run.
        status: Initial status of the run (always 'running').
    """

    run_id: str
    status: str = "running"


class PreviewJobOut(BaseModel):
    """A single job from a preview run result.

    Attributes:
        job_id: LinkedIn job ID.
        job_title: Title of the job posting.
        company: Name of the hiring company.
        linkedin_url: Canonical LinkedIn URL for the job listing.
        fit_score: Claude-assigned fit score (0–100), or None if not scored.
        fit_rationale: Claude's explanation of the score.
        projected_action: What would happen in a full run.
        promoted: Whether this job has been promoted to the real pipeline.
    """

    job_id: str
    job_title: str
    company: str
    linkedin_url: str
    fit_score: int | None = None
    fit_rationale: str | None = None
    projected_action: str
    promoted: bool


class PreviewRunResponse(BaseModel):
    """Full preview run status and results.

    Attributes:
        id: The preview run UUID.
        status: Current run status — 'running', 'completed', or 'failed'.
        started_at: ISO 8601 timestamp when the run began.
        completed_at: ISO 8601 timestamp when the run finished (nullable).
        error_message: Error details if the run failed (nullable).
        total_discovered: Number of jobs discovered.
        total_scored: Number of jobs scored.
        total_blacklisted: Number of jobs filtered by blacklist.
        jobs: List of preview job results.
    """

    id: str
    status: str
    started_at: str
    completed_at: str | None = None
    error_message: str | None = None
    total_discovered: int = 0
    total_scored: int = 0
    total_blacklisted: int = 0
    jobs: list[PreviewJobOut] = Field(default_factory=list)


class PromoteRequest(BaseModel):
    """Request body for promoting preview jobs to the real pipeline.

    Attributes:
        job_ids: List of LinkedIn job IDs to promote.
    """

    job_ids: list[str]


class PromoteResponse(BaseModel):
    """Response after promoting preview jobs.

    Attributes:
        promoted_ids: List of job IDs that were successfully promoted.
        count: Number of jobs promoted.
    """

    promoted_ids: list[str]
    count: int


# ---------------------------------------------------------------------------
# POST /preview — Trigger a preview run
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=PreviewTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_preview(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> PreviewTriggerResponse:
    """Trigger a new preview pipeline run.

    Creates a PreviewRun record immediately and starts the preview pipeline
    as a background task. Returns 202 with the run_id so the client can poll
    GET /preview/{run_id} to check progress.

    Returns:
        202 response with the run_id and initial status.
    """
    logger.info("preview_trigger_requested")

    run_id = str(uuid4())
    started_at = datetime.now(UTC).isoformat()

    # Create the PreviewRun record so GET /preview/{run_id} works immediately
    preview_run = PreviewRun(
        id=run_id,
        status="running",
        started_at=started_at,
        total_discovered=0,
        total_scored=0,
        total_blacklisted=0,
    )
    session.add(preview_run)
    await session.flush()

    # The session will be committed by the get_session dependency on return.
    # Schedule the background task to execute the actual preview pipeline.
    asyncio.create_task(_execute_preview_background(run_id))

    logger.info("preview_run_triggered", run_id=run_id)

    return PreviewTriggerResponse(run_id=run_id, status="running")


async def _execute_preview_background(run_id: str) -> None:
    """Execute the preview pipeline in a background coroutine.

    Calls run_preview which creates its own PreviewRun record (with a
    different ID). After completion, copies the results to the original
    run_id record that the client is polling.

    Args:
        run_id: The run_id returned to the client (placeholder record).
    """
    from src.db.database import get_session as _get_session

    async for session in _get_session():
        try:
            # run_preview creates its own PreviewRun record internally
            actual_run_id = await run_preview(session)
            await session.commit()

            # Transfer results from the actual run to our placeholder run_id
            await _transfer_preview_results(session, actual_run_id, run_id)

        except Exception as exc:
            logger.error("preview_background_error", run_id=run_id, error=str(exc))
            try:
                await session.rollback()
                # Mark the placeholder as failed
                result = await session.execute(
                    select(PreviewRun).where(PreviewRun.id == run_id)
                )
                placeholder = result.scalar_one_or_none()
                if placeholder:
                    placeholder.status = "failed"
                    placeholder.error_message = str(exc)[:500]
                    placeholder.completed_at = datetime.now(UTC).isoformat()
                await session.commit()
            except Exception as inner_exc:
                logger.error(
                    "preview_error_handling_failed",
                    run_id=run_id,
                    error=str(inner_exc),
                )
        break


async def _transfer_preview_results(
    session: AsyncSession,
    source_run_id: str,
    target_run_id: str,
) -> None:
    """Transfer preview results from the source run to the target run_id.

    Copies status, counts, and error info from the source PreviewRun to the
    target, reassigns all PreviewJob records, then deletes the source run.

    Args:
        session: Active async database session.
        source_run_id: The run_id created by run_preview.
        target_run_id: The run_id the client is polling.
    """
    if source_run_id == target_run_id:
        return

    # Load the source run
    result = await session.execute(
        select(PreviewRun).where(PreviewRun.id == source_run_id)
    )
    source_run = result.scalar_one_or_none()
    if source_run is None:
        return

    # Update the target placeholder with source results
    result = await session.execute(
        select(PreviewRun).where(PreviewRun.id == target_run_id)
    )
    target_run = result.scalar_one_or_none()
    if target_run is None:
        return

    target_run.status = source_run.status
    target_run.started_at = source_run.started_at
    target_run.completed_at = source_run.completed_at
    target_run.error_message = source_run.error_message
    target_run.total_discovered = source_run.total_discovered
    target_run.total_scored = source_run.total_scored
    target_run.total_blacklisted = source_run.total_blacklisted

    # Reassign all preview jobs from source to target
    await session.execute(
        update(PreviewJob)
        .where(PreviewJob.run_id == source_run_id)
        .values(run_id=target_run_id)
    )

    # Delete the source run (jobs already moved)
    await session.delete(source_run)
    await session.commit()

    logger.info(
        "preview_results_transferred",
        source_run_id=source_run_id,
        target_run_id=target_run_id,
    )


# ---------------------------------------------------------------------------
# GET /preview/{run_id} — Get preview run status and results
# ---------------------------------------------------------------------------


@router.get("/{run_id}", response_model=PreviewRunResponse)
async def get_preview_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> PreviewRunResponse:
    """Get the status and results of a preview run.

    Args:
        run_id: The preview run UUID.

    Returns:
        The preview run status, aggregate counts, and list of preview jobs.

    Raises:
        HTTPException: 404 if the run_id does not exist.
    """
    logger.info("get_preview_run_requested", run_id=run_id)

    result = await session.execute(
        select(PreviewRun).where(PreviewRun.id == run_id)
    )
    preview_run = result.scalar_one_or_none()

    if preview_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview run '{run_id}' not found",
        )

    # Load associated preview jobs
    jobs_result = await session.execute(
        select(PreviewJob).where(PreviewJob.run_id == run_id)
    )
    preview_jobs = jobs_result.scalars().all()

    jobs_out = [
        PreviewJobOut(
            job_id=pj.job_id,
            job_title=pj.job_title,
            company=pj.company,
            linkedin_url=pj.linkedin_url,
            fit_score=pj.fit_score,
            fit_rationale=pj.fit_rationale,
            projected_action=pj.projected_action,
            promoted=bool(pj.promoted),
        )
        for pj in preview_jobs
    ]

    return PreviewRunResponse(
        id=preview_run.id,
        status=preview_run.status,
        started_at=preview_run.started_at,
        completed_at=preview_run.completed_at,
        error_message=preview_run.error_message,
        total_discovered=preview_run.total_discovered,
        total_scored=preview_run.total_scored,
        total_blacklisted=preview_run.total_blacklisted,
        jobs=jobs_out,
    )


# ---------------------------------------------------------------------------
# POST /preview/{run_id}/promote — Promote selected jobs
# ---------------------------------------------------------------------------


@router.post("/{run_id}/promote", response_model=PromoteResponse)
async def promote_jobs(
    run_id: str,
    body: PromoteRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> PromoteResponse:
    """Promote selected preview jobs to the real pipeline.

    Copies the selected jobs from preview_jobs to job_records with status
    'approved_for_apply', and marks them as promoted in the preview.

    Args:
        run_id: The preview run UUID.
        body: Request body containing the list of job IDs to promote.

    Returns:
        The list of successfully promoted job IDs and count.

    Raises:
        HTTPException: 404 if the run_id does not exist.
        HTTPException: 400 if no job_ids are provided.
    """
    logger.info("promote_preview_jobs_requested", run_id=run_id, job_ids=body.job_ids)

    # Validate the run exists
    result = await session.execute(
        select(PreviewRun).where(PreviewRun.id == run_id)
    )
    preview_run = result.scalar_one_or_none()

    if preview_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview run '{run_id}' not found",
        )

    if not body.job_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No job IDs provided for promotion",
        )

    promoted_ids = await promote_preview_jobs(session, run_id, body.job_ids)

    logger.info(
        "preview_jobs_promoted_via_api",
        run_id=run_id,
        requested=len(body.job_ids),
        promoted=len(promoted_ids),
    )

    return PromoteResponse(promoted_ids=promoted_ids, count=len(promoted_ids))
