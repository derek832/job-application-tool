"""
Job record API routes for the LinkedIn Job Automator.

Provides endpoints for listing, retrieving, and summarizing job records.
All endpoints require Bearer token authentication.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import JobRecordOut, StatsOut
from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.job_repo import get_job_record, get_stats, list_jobs

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------


@router.get("", response_model=list[JobRecordOut])
async def list_job_records(
    status: str | None = Query(default=None, description="Filter by job status"),
    search: str | None = Query(default=None, description="Search job title or company"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Records per page"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> list[JobRecordOut]:
    """Return a paginated list of job records with optional filters.

    Args:
        status: If provided, filter to records matching this status.
        search: If provided, filter to records where job_title or company
            contains this substring (case-insensitive).
        page: Page number (1-indexed). Defaults to 1.
        limit: Maximum records per page. Defaults to 20, max 100.
        session: Active async database session.

    Returns:
        List of job records for the requested page.
    """
    logger.info(
        "list_jobs_requested",
        status=status,
        search=search,
        page=page,
        limit=limit,
    )

    records = await list_jobs(session, status=status, search=search, page=page, limit=limit)
    return [JobRecordOut.model_validate(record) for record in records]


# ---------------------------------------------------------------------------
# GET /jobs/stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=StatsOut)
async def get_job_stats(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> StatsOut:
    """Return summary statistics for the job pipeline.

    Returns:
        Statistics including total discovered, applied, skipped,
        pending review, and application success rate.
    """
    logger.info("get_job_stats_requested")

    stats_data = await get_stats(session)
    return StatsOut(**stats_data)


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=JobRecordOut)
async def get_single_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> JobRecordOut:
    """Retrieve a single job record by its LinkedIn job ID.

    Args:
        job_id: The LinkedIn job ID (primary key).
        session: Active async database session.

    Returns:
        The job record if found.

    Raises:
        HTTPException: 404 if no job record exists with the given ID.
    """
    logger.info("get_job_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    return JobRecordOut.model_validate(record)
