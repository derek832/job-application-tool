"""Main pipeline orchestrator for the LinkedIn Job Automator.

Coordinates the full job search and application pipeline: discovery, extraction,
scoring, tailoring, and application submission. Called by the scheduler on each
run cycle.

Implements idempotency by querying jobs by status and skipping terminal states.
All state transitions are logged at INFO level with structlog.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import structlog
from playwright.async_api import BrowserContext, async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient
from src.api.schemas import GoalsProfile, SearchConfig, Settings, UserProfile
from src.db.config_repo import get_config, set_config
from src.db.job_repo import TERMINAL_STATUSES, create_job_record
from src.db.models import JobRecord
from src.integrations.gdocs_client import GDocsClient
from src.integrations.linkedin_scraper import discover_jobs
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.easy_apply_stage import run_easy_apply
from src.pipeline.extraction_stage import run_extraction
from src.pipeline.scoring_stage import run_scoring
from src.pipeline.tailoring_stage import restore_resume_base, run_tailoring

logger = structlog.get_logger(__name__)

# Default Playwright user-data directory for persistent session cookies.
_USER_DATA_DIR = os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "data/browser-profile")


async def run_pipeline(session: AsyncSession) -> None:
    """Execute the full job search and application pipeline.

    This is the top-level function called by the scheduler. It orchestrates
    all pipeline stages sequentially:

    1. Check system_state — abort if paused.
    2. Check goals_profile is configured — pause system if missing.
    3. Load all configuration (search_config, goals_profile, user_profile, settings).
    4. Launch Playwright persistent context.
    5. Run job discovery.
    6. Create JobRecords for newly discovered jobs.
    7. Run extraction for jobs in "discovered" status.
    8. Run scoring for jobs in "extracted" status.
    9. Run tailoring and application for jobs in "approved_for_apply" status.
    10. Restore resume base after each application.
    11. Close Playwright context.
    12. Update system_state.last_run_at.

    Idempotency: queries jobs by status, skips jobs in terminal states.
    Exceptions are caught at the job level — logged and continued with next job.

    Args:
        session: Active async database session for all DB operations.
    """
    logger.info("pipeline_run_started")

    # Step 1: Check system_state
    system_state = await get_config(session, "system_state")
    if system_state and system_state.get("status") == "paused":
        logger.info("pipeline_aborted_system_paused")
        return

    # Step 2: Check goals_profile is configured
    goals_profile_raw = await get_config(session, "goals_profile")
    if not goals_profile_raw:
        logger.info("pipeline_aborted_goals_not_configured")
        await set_config(
            session,
            "system_state",
            {
                "status": "paused",
                "last_error": "Goals profile not configured",
                "last_run_at": datetime.now(UTC).isoformat(),
            },
        )
        await session.commit()
        return

    # Step 3: Load all configuration
    search_config_raw = await get_config(session, "search_config")
    user_profile_raw = await get_config(session, "user_profile")
    settings_raw = await get_config(session, "settings")

    goals_profile = GoalsProfile.model_validate(goals_profile_raw)
    search_config = SearchConfig.model_validate(search_config_raw or {})
    user_profile = UserProfile.model_validate(user_profile_raw or {})
    settings = Settings.model_validate(settings_raw or {})

    # Build SMS settings if configured
    sms_settings = _build_sms_settings(settings)

    # Build Claude client
    claude_client: ClaudeClient | None = None
    if settings.claude_api_key and settings.claude_api_key != "***":
        claude_client = ClaudeClient(api_key=settings.claude_api_key)

    # Build GDocs client
    gdocs_client: GDocsClient | None = None
    if settings.gdocs_script_url:
        gdocs_client = GDocsClient(endpoint_url=settings.gdocs_script_url)

    # Step 4: Launch Playwright persistent context
    logger.info("pipeline_launching_browser", user_data_dir=_USER_DATA_DIR)
    browser_context: BrowserContext | None = None

    try:
        pw = await async_playwright().start()
        browser_context = await pw.chromium.launch_persistent_context(
            user_data_dir=_USER_DATA_DIR,
            headless=True,
        )
        page = await browser_context.new_page()

        # Step 5: Run job discovery
        new_job_ids = await discover_jobs(
            page=page,
            config=search_config,
            session=session,
            max_pages=5,
        )
        logger.info("pipeline_discovery_completed", new_jobs=len(new_job_ids))

        # Step 6: Create JobRecords for newly discovered jobs
        for job_id in new_job_ids:
            try:
                await create_job_record(
                    session,
                    id=job_id,
                    job_title="Unknown",
                    company="Unknown",
                    linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                    apply_type="easy_apply",
                )
                logger.info("pipeline_job_record_created", job_id=job_id)
            except Exception as exc:
                logger.error("pipeline_job_record_creation_failed", job_id=job_id, error=str(exc))

        await session.flush()

        # Step 7: Run extraction for jobs in "discovered" status
        discovered_jobs = await _get_jobs_by_status(session, "discovered")
        for job_record in discovered_jobs:
            try:
                await run_extraction(job_record=job_record, page=page, session=session)
                logger.info(
                    "pipeline_extraction_completed",
                    job_id=job_record.id,
                    new_status=job_record.status,
                )
            except Exception as exc:
                logger.error(
                    "pipeline_extraction_error",
                    job_id=job_record.id,
                    error=str(exc),
                )

        await session.flush()

        # Step 8: Run scoring for jobs in "extracted" status
        if claude_client:
            extracted_jobs = await _get_jobs_by_status(session, "extracted")
            resume_content = await _load_resume_content(gdocs_client)
            goals_json = goals_profile.model_dump_json()

            for job_record in extracted_jobs:
                try:
                    await run_scoring(
                        job_record=job_record,
                        session=session,
                        claude_client=claude_client,
                        resume_content=resume_content,
                        goals_profile=goals_json,
                        deal_breakers=goals_profile.deal_breakers,
                        good_fit_threshold=settings.good_fit_threshold,
                        stretch_threshold=settings.stretch_threshold,
                        sms_settings=sms_settings,
                    )
                    logger.info(
                        "pipeline_scoring_completed",
                        job_id=job_record.id,
                        new_status=job_record.status,
                    )
                except Exception as exc:
                    logger.error(
                        "pipeline_scoring_error",
                        job_id=job_record.id,
                        error=str(exc),
                    )
        else:
            logger.warning("pipeline_scoring_skipped_no_claude_client")

        await session.flush()

        # Step 9: Run tailoring and application for "approved_for_apply" jobs
        if claude_client and gdocs_client:
            approved_jobs = await _get_jobs_by_status(session, "approved_for_apply")

            for job_record in approved_jobs:
                try:
                    # Run tailoring
                    await run_tailoring(
                        job_record=job_record,
                        session=session,
                        gdocs_client=gdocs_client,
                        claude_client=claude_client,
                        sms_settings=sms_settings,
                    )

                    # Only proceed to apply if tailoring succeeded (status is "applying")
                    await session.refresh(job_record)
                    if job_record.status != "applying":
                        logger.info(
                            "pipeline_apply_skipped_tailoring_failed",
                            job_id=job_record.id,
                            status=job_record.status,
                        )
                        continue

                    # DRY RUN: skip actual submission, log what would happen
                    if settings.dry_run:
                        from src.db.job_repo import update_job_status

                        logger.info(
                            "pipeline_dry_run_skip_submit",
                            job_id=job_record.id,
                            job_title=job_record.job_title,
                            company=job_record.company,
                            apply_type=job_record.apply_type,
                            message="Dry run — skipping actual submission",
                        )
                        await update_job_status(
                            session,
                            job_record.id,
                            "applied",
                            reason="Dry run — submission skipped",
                        )
                        job_record.applied_at = datetime.now(UTC).isoformat()
                    elif job_record.apply_type == "easy_apply":
                        await run_easy_apply(
                            job_record=job_record,
                            profile=user_profile,
                            session=session,
                            page=page,
                            claude_client=claude_client,
                            sms_settings=sms_settings,
                            goals_profile=goals_json,
                        )
                    else:
                        # External apply via Vision Agent
                        from src.agents.vision_agent import process_external_apply

                        result = await process_external_apply(
                            job_record=job_record,
                            profile=user_profile,
                            page=page,
                            claude_client=claude_client,
                            min_salary=goals_profile.min_salary,
                        )
                        if result.ok:
                            from src.db.job_repo import update_job_status

                            job_record.applied_at = datetime.now(UTC).isoformat()
                            await update_job_status(
                                session,
                                job_record.id,
                                "applied",
                                reason="External apply submitted via Vision Agent",
                            )
                        else:
                            from src.db.job_repo import update_job_status

                            job_record.error_message = result.error
                            job_record.queue_reason = result.reason or "apply_failed"
                            await update_job_status(
                                session,
                                job_record.id,
                                "apply_failed",
                                reason=f"External apply failed: {result.error}",
                            )

                    # Step 10: Restore resume base after each application
                    await restore_resume_base(
                        job_record=job_record,
                        gdocs_client=gdocs_client,
                        session=session,
                    )

                    logger.info(
                        "pipeline_application_completed",
                        job_id=job_record.id,
                        final_status=job_record.status,
                    )
                except Exception as exc:
                    logger.error(
                        "pipeline_application_error",
                        job_id=job_record.id,
                        error=str(exc),
                    )
                    # Still attempt to restore resume on error
                    try:
                        await restore_resume_base(
                            job_record=job_record,
                            gdocs_client=gdocs_client,
                            session=session,
                        )
                    except Exception as restore_exc:
                        logger.error(
                            "pipeline_resume_restore_error",
                            job_id=job_record.id,
                            error=str(restore_exc),
                        )
        else:
            if not claude_client:
                logger.warning("pipeline_apply_skipped_no_claude_client")
            if not gdocs_client:
                logger.warning("pipeline_apply_skipped_no_gdocs_client")

        await session.flush()

    except Exception as exc:
        logger.error("pipeline_fatal_error", error=str(exc))
    finally:
        # Step 11: Close Playwright context
        if browser_context:
            try:
                await browser_context.close()
            except Exception as exc:
                logger.error("pipeline_browser_close_error", error=str(exc))
        try:
            await pw.stop()
        except Exception:
            pass

    # Step 12: Update system_state.last_run_at
    now_iso = datetime.now(UTC).isoformat()
    current_state = await get_config(session, "system_state") or {}
    current_state["last_run_at"] = now_iso
    if current_state.get("status") not in ("paused", "error"):
        current_state["status"] = "idle"
    await set_config(session, "system_state", current_state)
    await session.commit()

    logger.info("pipeline_run_completed", last_run_at=now_iso)


async def _get_jobs_by_status(session: AsyncSession, status: str) -> list[JobRecord]:
    """Query all job records with the given status, excluding terminal states.

    Args:
        session: Active async database session.
        status: The status to filter by.

    Returns:
        List of JobRecord instances matching the status.
    """
    result = await session.execute(
        select(JobRecord)
        .where(JobRecord.status == status)
        .where(JobRecord.status.notin_(TERMINAL_STATUSES))
        .order_by(JobRecord.discovered_at.asc())
    )
    return list(result.scalars().all())


async def _load_resume_content(gdocs_client: GDocsClient | None) -> str:
    """Load the current resume content from Google Docs.

    Falls back to an empty string if the client is not configured or the
    read fails.

    Args:
        gdocs_client: The Google Docs client, or None if not configured.

    Returns:
        The resume content as a string, or empty string on failure.
    """
    if gdocs_client is None:
        logger.warning("pipeline_resume_load_skipped_no_gdocs_client")
        return ""

    try:
        return await gdocs_client.read_resume()
    except Exception as exc:
        logger.error("pipeline_resume_load_failed", error=str(exc))
        return ""


def _build_sms_settings(settings: Settings) -> SMSSettings | None:
    """Build SMSSettings from the application settings if all fields are present.

    Args:
        settings: The application settings containing Gmail and SMS config.

    Returns:
        An SMSSettings instance if all required fields are configured, else None.
    """
    if settings.gmail_user and settings.gmail_user != "***" and settings.sms_gateway:
        return SMSSettings(
            gmail_user=settings.gmail_user,
            sms_gateway=settings.sms_gateway,
        )
    return None
