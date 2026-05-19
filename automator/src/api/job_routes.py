"""
Job record API routes for the LinkedIn Job Automator.

Provides endpoints for listing, retrieving, and summarizing job records.
All endpoints require Bearer token authentication.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import JobRecordOut, StatsOut
from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.job_repo import get_external_apply_stats, get_job_record, get_stats, list_jobs

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------


@router.get("", response_model=list[JobRecordOut])
async def list_job_records(
    status: str | None = Query(default=None, description="Filter by job status"),
    search: str | None = Query(default=None, description="Search job title or company"),
    run_id: str | None = Query(default=None, description="Filter by run ID"),
    min_score: int | None = Query(default=None, ge=0, le=100, description="Minimum fit score"),
    max_score: int | None = Query(default=None, ge=0, le=100, description="Maximum fit score"),
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
        run_id: If provided, filter to records from this pipeline run.
        min_score: If provided, filter to records with fit_score >= this value.
        max_score: If provided, filter to records with fit_score <= this value.
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
        run_id=run_id,
        min_score=min_score,
        max_score=max_score,
        page=page,
        limit=limit,
    )

    records = await list_jobs(
        session,
        status=status,
        search=search,
        run_id=run_id,
        min_score=min_score,
        max_score=max_score,
        page=page,
        limit=limit,
    )
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
# GET /jobs/stats/external-apply
# ---------------------------------------------------------------------------


@router.get("/stats/external-apply")
async def get_external_apply_statistics(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> dict:
    """Return statistics on external apply attempts and extraction methods.

    Tracks how often DOM extraction succeeds vs. when vision would be needed.
    Useful for evaluating whether a local vision model is worth the complexity.

    Returns:
        Dict with total_attempts, dom_success, dom_failed, vision_used,
        dom_success_rate, avg_dom_fields, avg_fields_filled, and outcomes breakdown.
    """
    logger.info("get_external_apply_stats_requested")
    return await get_external_apply_stats(session)


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


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/pdf
# ---------------------------------------------------------------------------


@router.get("/{job_id}/pdf")
async def get_job_pdf(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> FileResponse:
    """Serve the tailored resume PDF for a job record.

    Args:
        job_id: The LinkedIn job ID (primary key).
        session: Active async database session.

    Returns:
        The PDF file as a downloadable response.

    Raises:
        HTTPException: 404 if no job record or PDF exists.
    """
    logger.info("get_job_pdf_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    if not record.tailored_resume_pdf:
        raise HTTPException(status_code=404, detail="No tailored PDF available for this job")

    pdf_path = Path(record.tailored_resume_pdf)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"resume_{record.company}_{job_id}.pdf",
    )


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/test-apply
# ---------------------------------------------------------------------------


@router.post("/{job_id}/test-apply")
async def test_apply_job(
    job_id: str,
    dry_run: bool = True,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> dict:
    """Trigger the Vision Agent on a single job for testing.

    By default runs in dry_run mode — fills the form but does NOT click submit.
    Set dry_run=false to actually submit.

    Args:
        job_id: The LinkedIn job ID.
        dry_run: If True (default), fills form but skips submission.

    Args:
        job_id: The LinkedIn job ID.
        session: Active async database session.

    Returns:
        Result dict with ok, error, and reason fields.

    Raises:
        HTTPException: 404 if job not found, 400 if preconditions not met.
    """
    logger.info("test_apply_requested", job_id=job_id)

    record = await get_job_record(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job record not found: {job_id}")

    if not record.external_url:
        raise HTTPException(
            status_code=400,
            detail="Job has no external_url. Set one first or use an external_apply job.",
        )

    # Load user profile and settings
    from src.db.config_repo import get_config

    user_profile_raw = await get_config(session, "user_profile")
    goals_raw = await get_config(session, "goals_profile")
    settings_raw = await get_config(session, "settings")

    from src.api.schemas import GoalsProfile, Settings, UserProfile

    user_profile = UserProfile.model_validate(user_profile_raw or {})
    goals = GoalsProfile.model_validate(goals_raw or {})
    settings = Settings.model_validate(settings_raw or {})

    if not settings.claude_api_key or settings.claude_api_key == "***":
        raise HTTPException(status_code=400, detail="Claude API key not configured")

    from src.agents.claude_client import ClaudeClient

    claude_client = ClaudeClient(api_key=settings.claude_api_key)

    # Launch a browser page for the test
    import os

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        cdp_url = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")
        ws_url_path = os.path.join("data", "chrome-ws-url.txt")
        if os.path.exists(ws_url_path):
            with open(ws_url_path) as f:
                ws_url = f.read().strip()
            browser = await pw.chromium.connect_over_cdp(ws_url)
        else:
            browser = await pw.chromium.connect_over_cdp(cdp_url)

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        from src.agents.vision_agent import process_external_apply

        result = await process_external_apply(
            job_record=record,
            profile=user_profile,
            page=page,
            claude_client=claude_client,
            min_salary=goals.min_salary,
            dry_run=dry_run,
        )

        await page.close()
    finally:
        await pw.stop()

    return {"ok": result.ok, "error": result.error, "reason": result.reason, "dry_run": dry_run}
