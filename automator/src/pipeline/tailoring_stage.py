"""Pipeline stage: resume tailoring and restore.

Handles the resume tailoring lifecycle — reading the base resume, storing a
pre-tailoring snapshot, invoking Claude for tailoring, writing back to Google
Docs, exporting PDF, and restoring the original resume content after each
application.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient
from src.db.config_repo import set_config
from src.db.job_repo import update_job_status
from src.db.models import JobRecord
from src.exceptions import GDocsError, TailoringError
from src.integrations.gdocs_client import GDocsClient
from src.pipeline.notification_service import NotificationSettings, notify

logger = structlog.get_logger(__name__)

PDF_OUTPUT_DIR = "data/pdfs"


def _build_pdf_filename(full_name: str | None, company: str, job_title: str) -> str:
    """Build a professional, filesystem-safe PDF filename.

    Produces filenames like: Derek_Smith_Acme_Corp_Software_Engineer_Resume.pdf

    Each component (name, company, title) is sanitized by replacing spaces with
    underscores and stripping characters that are unsafe for filesystems. If the
    user's full name is not configured, it is omitted from the filename.

    Args:
        full_name: User's full name from their profile (may be None).
        company: Company name from the job record.
        job_title: Job title from the job record.

    Returns:
        A sanitized filename string ending in .pdf.
    """

    def sanitize(text: str) -> str:
        """Replace spaces with underscores and strip non-alphanumeric/underscore chars."""
        text = text.strip().replace(" ", "_")
        text = re.sub(r"[^\w\-]", "", text)
        # Collapse multiple underscores
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    parts: list[str] = []
    if full_name:
        parts.append(sanitize(full_name))
    parts.append(sanitize(company))
    parts.append(sanitize(job_title))
    parts.append("Resume")

    filename = "_".join(part for part in parts if part)

    # Truncate to keep total path length reasonable (max 150 chars for the name)
    if len(filename) > 150:
        filename = filename[:150].rstrip("_")

    return f"{filename}.pdf"


async def run_tailoring(
    job_record: JobRecord,
    session: AsyncSession,
    gdocs_client: GDocsClient,
    claude_client: ClaudeClient,
    notification_settings: NotificationSettings | None = None,
    supplementary_context: str | None = None,
    user_full_name: str | None = None,
) -> None:
    """Run the resume tailoring stage for a single job record.

    Reads the current Resume_Base from Google Docs, stores a pre-tailoring
    snapshot, invokes Claude for ATS-optimized tailoring, writes the tailored
    content back to Google Docs, and exports a PDF.

    On GDocsError with authorization_expired=True: pauses the system and
    notifies the user. On other failures after retries: sets status to
    "resume_failed", adds to human queue, and sends notification.

    Args:
        job_record: The job record to tailor a resume for. Must have status
            "approved_for_apply".
        session: Active async database session for persisting state changes.
        gdocs_client: An initialized Google Apps Script client.
        claude_client: The Claude API client instance for resume tailoring.
        notification_settings: Unified notification settings. If None,
            notifications are skipped on failure.
        supplementary_context: Additional experience notes or work details
            passed to Claude for richer keyword matching. Not included in
            the final tailored resume output.
        user_full_name: User's full name from their profile, used to build
            a professional PDF filename. If None, the name is omitted.
    """
    job_id = job_record.id
    logger.info("tailoring_stage_started", job_id=job_id, company=job_record.company)

    # Step 1: Read the current resume from Google Docs
    try:
        resume_base = await gdocs_client.read_resume()
    except GDocsError as exc:
        await _handle_gdocs_error(exc, job_record, session, notification_settings)
        return

    # Step 2: Store pre-tailoring snapshot
    job_record.resume_snapshot = json.dumps(resume_base)
    await session.flush()

    # Step 3: Invoke Claude for tailoring (returns JSON replacements)
    try:
        cost_before = claude_client.total_cost_usd
        tailoring_response = await claude_client.tailor_resume(
            description=job_record.description_text,
            resume_base=resume_base,
            supplementary_context=supplementary_context,
        )
        tailoring_cost = claude_client.total_cost_usd - cost_before

        # Accumulate cost on the job record
        existing_cost = float(job_record.claude_cost_usd or "0")
        job_record.claude_cost_usd = str(round(existing_cost + tailoring_cost, 6))
    except TailoringError as exc:
        await _handle_tailoring_failure(exc.message, job_record, session, notification_settings)
        return

    # Parse the replacements JSON from Claude
    try:
        cleaned = claude_client._extract_json(tailoring_response)
        replacements = json.loads(cleaned)
        if not isinstance(replacements, list):
            raise ValueError("Expected a JSON array of replacements")
    except (json.JSONDecodeError, ValueError) as exc:
        await _handle_tailoring_failure(
            f"Failed to parse tailoring replacements: {exc}",
            job_record, session, notification_settings,
        )
        return

    # Store the replacements for review
    job_record.tailored_resume_text = json.dumps(replacements, indent=2)
    await session.flush()

    # Step 4+5: Copy original doc, apply replacements, export PDF (preserves formatting)
    pdf_filename = _build_pdf_filename(user_full_name, job_record.company, job_record.job_title)
    pdf_path = f"{PDF_OUTPUT_DIR}/{pdf_filename}"
    try:
        applied = await gdocs_client.tailor_and_export(replacements, Path(pdf_path))
        logger.info(
            "tailoring_replacements_applied",
            job_id=job_id,
            total_replacements=len(replacements),
            applied=applied,
        )
    except GDocsError as exc:
        await _handle_gdocs_error(exc, job_record, session, notification_settings)
        return

    # Step 6: Update job record with PDF path and advance status
    job_record.tailored_resume_pdf = pdf_path
    await update_job_status(session, job_id, "applying", reason="Resume tailored and PDF exported")

    logger.info("tailoring_stage_completed", job_id=job_id, pdf_path=pdf_path)


async def restore_resume_base(
    job_record: JobRecord,
    gdocs_client: GDocsClient,
    session: AsyncSession,
) -> None:
    """Restore the pre-tailoring resume snapshot back to Google Docs.

    After each application, the original Resume_Base content (stored as a
    JSON-encoded string in ``job_record.resume_snapshot``) is written back
    to the Google Docs document. This ensures the canonical resume is always
    restored to its untailored state for the next application.

    Errors are logged but do not fail the pipeline — the resume can be
    manually restored by the user if this step fails.

    Args:
        job_record: The job record containing the pre-tailoring snapshot in
            ``resume_snapshot``.
        gdocs_client: An initialized Google Apps Script client for writing
            to the resume document.
        session: Active async database session (available for future use if
            state tracking is needed).
    """
    job_id = job_record.id
    logger.info("resume_restore_started", job_id=job_id, company=job_record.company)

    if not job_record.resume_snapshot:
        logger.warning(
            "resume_restore_skipped_no_snapshot",
            job_id=job_id,
            reason="No resume_snapshot stored on job record",
        )
        return

    try:
        original_content: str = json.loads(job_record.resume_snapshot)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "resume_restore_decode_failed",
            job_id=job_id,
            error=str(exc),
        )
        return

    try:
        await gdocs_client.write_resume(original_content)
    except Exception as exc:
        logger.error(
            "resume_restore_write_failed",
            job_id=job_id,
            error=str(exc),
        )
        return

    logger.info("resume_restore_completed", job_id=job_id)


async def _handle_gdocs_error(
    exc: GDocsError,
    job_record: JobRecord,
    session: AsyncSession,
    notification_settings: NotificationSettings | None,
) -> None:
    """Handle a GDocsError during the tailoring stage.

    If the error indicates authorization has expired, pauses the system and
    notifies the user. Otherwise, sets the job to "resume_failed" and adds
    it to the human queue.
    """
    job_id = job_record.id

    if exc.authorization_expired:
        logger.error(
            "tailoring_gdocs_authorization_expired",
            job_id=job_id,
        )
        await set_config(
            session,
            "system_state",
            {
                "status": "error",
                "last_error": "Google Docs authorization expired",
                "last_run_at": datetime.now(UTC).isoformat(),
            },
        )
        if notification_settings:
            await notify(
                session=session,
                job_record=job_record,
                trigger_reason="gdocs_authorization_expired",
                settings=notification_settings,
            )
        return

    await _handle_tailoring_failure(exc.message, job_record, session, notification_settings)


async def _handle_tailoring_failure(
    error_message: str,
    job_record: JobRecord,
    session: AsyncSession,
    notification_settings: NotificationSettings | None,
) -> None:
    """Handle a non-authorization tailoring failure.

    Sets the job status to "resume_failed", records the error, adds to the
    human queue, and sends a notification if settings are available.
    """
    job_id = job_record.id
    logger.error("tailoring_stage_failed", job_id=job_id, error=error_message)

    job_record.error_message = error_message
    job_record.queue_reason = "resume_tailoring_failed"
    await update_job_status(
        session,
        job_id,
        "resume_failed",
        reason=f"Resume tailoring failed: {error_message}",
    )

    if notification_settings:
        await notify(
            session=session,
            job_record=job_record,
            trigger_reason="resume_tailoring_failed",
            settings=notification_settings,
        )
