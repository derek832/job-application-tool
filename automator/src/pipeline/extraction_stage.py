"""Pipeline stage: job description extraction.

Navigates to a job's LinkedIn URL, extracts the full description text,
and updates the job record accordingly. On failure after retries, the job
is routed to the human queue with an SMS notification.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.job_repo import update_job_status
from src.db.models import JobRecord
from src.exceptions import ExtractionError
from src.integrations.linkedin_scraper import extract_description

logger = structlog.get_logger(__name__)


async def run_extraction(job_record: JobRecord, page: Page, session: AsyncSession) -> None:
    """Run the extraction stage for a single job record.

    Attempts to extract the full job description from the job's LinkedIn page.
    On success, stores the description text and advances the status to "extracted".
    On failure (ExtractionError after retries), sets status to "extraction_failed",
    adds the job to the human queue, and records the error.

    Args:
        job_record: The job record to extract a description for. Must have status
            "discovered".
        page: A Playwright Page instance (already authenticated with LinkedIn).
        session: Active async database session for persisting state changes.
    """
    job_id = job_record.id
    logger.info("extraction_stage_started", job_id=job_id, company=job_record.company)

    try:
        description_text = await extract_description(page, job_record)
    except ExtractionError as exc:
        logger.error(
            "extraction_stage_failed",
            job_id=job_id,
            error=exc.message,
        )
        job_record.error_message = exc.message
        job_record.queue_reason = "extraction_failed"
        await update_job_status(
            session,
            job_id,
            "extraction_failed",
            reason=f"Extraction failed after retries: {exc.message}",
        )
        return

    # Success path: store description and advance status.
    job_record.description_text = description_text
    job_record.extracted_at = datetime.now(UTC).isoformat()
    await update_job_status(session, job_id, "extracted", reason="Description extracted")

    logger.info(
        "extraction_stage_completed",
        job_id=job_id,
        description_length=len(description_text),
    )
