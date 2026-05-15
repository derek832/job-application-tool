"""Main pipeline orchestrator for the LinkedIn Job Automator.

Coordinates the full job search and application pipeline: discovery, extraction,
scoring, tailoring, and application submission. Called by the scheduler on each
run cycle.

Implements idempotency by querying jobs by status and skipping terminal states.
All state transitions are logged at INFO level with structlog.
"""

from __future__ import annotations

import asyncio
import os
import random
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
from src.integrations.linkedin_scraper import discover_and_extract_jobs
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.easy_apply_stage import run_easy_apply
from src.pipeline.scoring_stage import run_scoring
from src.pipeline.tailoring_stage import restore_resume_base, run_tailoring

logger = structlog.get_logger(__name__)

# Default Playwright user-data directory for persistent session cookies.
_USER_DATA_DIR = os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "data/browser-profile")


async def run_pipeline(session: AsyncSession | None = None) -> None:
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
        session: Active async database session. If None, creates one internally.
    """
    from src.db.database import get_session as _get_session

    # If no session provided, create one
    if session is None:
        async for s in _get_session():
            session = s
            break

    if session is None:
        logger.error("pipeline_no_session_available")
        return

    logger.info("pipeline_run_started")

    # Step 1: Check system_state
    system_state = await get_config(session, "system_state")
    if system_state and system_state.get("status") == "paused":
        logger.info("pipeline_aborted_system_paused")
        return

    # Check for skip_discovery flag (debug mode — skips discovery and scoring)
    skip_discovery = bool(system_state and system_state.get("skip_discovery"))
    if skip_discovery:
        logger.info("pipeline_skip_discovery_mode_enabled")
        # Clear the flag so subsequent scheduled runs don't skip
        system_state["skip_discovery"] = False
        await set_config(session, "system_state", system_state)
        await session.flush()

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

    # Step 3.5: Generate/refresh pre-filter keywords if profile changed
    filter_keywords: list[str] = []
    if claude_client and not skip_discovery:
        from src.pipeline.prefilter import compute_context_hash, generate_filter_keywords

        current_hash = compute_context_hash(
            goals_profile.supplementary_context,
            goals_profile.career_objective,
            goals_profile.target_titles,
        )
        keyword_config = await get_config(session, "filter_keywords") or {}
        stored_hash = keyword_config.get("hash")
        stored_keywords = keyword_config.get("keywords", [])

        if stored_hash == current_hash and stored_keywords:
            filter_keywords = stored_keywords
            logger.info("prefilter_keywords_loaded_from_cache", count=len(filter_keywords))
        else:
            logger.info("prefilter_keywords_regenerating", reason="profile_changed")
            filter_keywords = await generate_filter_keywords(
                claude_client=claude_client,
                supplementary_context=goals_profile.supplementary_context,
                career_objective=goals_profile.career_objective,
                target_titles=goals_profile.target_titles,
            )
            await set_config(
                session,
                "filter_keywords",
                {
                    "hash": current_hash,
                    "keywords": filter_keywords,
                },
            )
            await session.flush()
    elif not skip_discovery:
        # No Claude client — try to load cached keywords
        keyword_config = await get_config(session, "filter_keywords") or {}
        filter_keywords = keyword_config.get("keywords", [])

    # Step 4: Launch Playwright persistent context
    logger.info("pipeline_launching_browser", user_data_dir=_USER_DATA_DIR)
    browser_context: BrowserContext | None = None

    try:
        pw = await async_playwright().start()

        # Connect to the user's Chrome instance via CDP (remote debugging)
        # This uses the real browser session — no login needed
        cdp_url = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")
        logger.info("pipeline_connecting_to_chrome", cdp_url=cdp_url)

        try:
            # Read the websocket URL written by start-chrome-debug.bat
            ws_url_path = os.path.join("data", "chrome-ws-url.txt")
            if os.path.exists(ws_url_path):
                with open(ws_url_path) as f:
                    ws_url = f.read().strip()
                logger.info("pipeline_chrome_ws_url_from_file", ws_url=ws_url)
                browser = await pw.chromium.connect_over_cdp(ws_url)
            else:
                logger.info("pipeline_chrome_connecting_direct", url=cdp_url)
                browser = await pw.chromium.connect_over_cdp(cdp_url)

            browser_context = (
                browser.contexts[0] if browser.contexts else await browser.new_context()
            )
            logger.info("pipeline_chrome_connected", contexts=len(browser.contexts))
        except Exception as exc:
            logger.error(
                "pipeline_chrome_connection_failed",
                error=str(exc),
                hint="Start Chrome with: start-chrome-debug.bat",
            )
            return

        page = await browser_context.new_page()

        if not skip_discovery:
            # Step 5+6+7: Discover jobs and extract descriptions in one pass
            # Runs each configured search query separately and aggregates results
            keyword_list = search_config.get_keyword_list()
            if not keyword_list:
                logger.warning("pipeline_no_search_queries_configured")
                keyword_list = [""]  # Run once with no keywords as fallback

            discovered: list = []
            for i, query_keywords in enumerate(keyword_list):
                # Randomized delay between queries to avoid detection
                if i > 0:
                    delay = random.uniform(10.0, 20.0)
                    logger.info("pipeline_inter_query_delay", delay_seconds=round(delay, 1))
                    await asyncio.sleep(delay)

                # Build a per-query config with the current keywords
                query_config = SearchConfig(
                    keywords=query_keywords or None,
                    location=search_config.location,
                    job_type=search_config.job_type,
                    experience_level=search_config.experience_level,
                    remote_pref=search_config.remote_pref,
                )
                logger.info("pipeline_running_search_query", keywords=query_keywords)

                query_results = await discover_and_extract_jobs(
                    page=page,
                    config=query_config,
                    session=session,
                    max_pages=5,
                )
                discovered.extend(query_results)
                logger.info(
                    "pipeline_query_completed",
                    keywords=query_keywords,
                    jobs_found=len(query_results),
                )

            # Limit to 5 jobs in dry run mode to control costs
            if settings.dry_run and len(discovered) > 5:
                discovered = discovered[:5]
                logger.info("pipeline_dry_run_limited", total_found=len(discovered), limit=5)

            logger.info("pipeline_discovery_completed", new_jobs=len(discovered))

            # Create JobRecords with title, company, and description already populated
            for job in discovered:
                try:
                    await create_job_record(
                        session,
                        id=job.job_id,
                        job_title=job.title,
                        company=job.company,
                        linkedin_url=job.linkedin_url,
                        apply_type=job.apply_type,
                    )
                    # Update the record with the extracted description
                    from src.db.job_repo import update_job_status

                    result = await session.execute(
                        select(JobRecord).where(JobRecord.id == job.job_id)
                    )
                    record = result.scalar_one_or_none()
                    if record:
                        record.description_text = job.description
                        record.status = "extracted"
                        record.extracted_at = datetime.now(UTC).isoformat()
                        if job.external_url:
                            record.external_url = job.external_url

                    logger.info(
                        "pipeline_job_discovered_and_extracted",
                        job_id=job.job_id,
                        title=job.title,
                        company=job.company,
                        apply_type=job.apply_type,
                    )
                except Exception as exc:
                    logger.error(
                        "pipeline_job_record_creation_failed",
                        job_id=job.job_id,
                        error=str(exc),
                    )

            await session.flush()

            # Step 8: Run scoring for jobs in "extracted" status
            if claude_client:
                extracted_jobs = await _get_jobs_by_status(session, "extracted")
                resume_content = await _load_resume_content(gdocs_client)

                # Append supplementary context (work notes, detailed experience) so
                # Claude has richer context for scoring and tailoring without polluting
                # the actual resume used for PDF export.
                if goals_profile.supplementary_context:
                    resume_content = (
                        f"{resume_content}\n\n"
                        f"## Additional Context (not part of resume)\n"
                        f"{goals_profile.supplementary_context}"
                    )

                goals_json = goals_profile.model_dump_json()

                for job_record in extracted_jobs:
                    # Pre-filter: check title exclusions
                    from src.pipeline.prefilter import (
                        check_keyword_presence,
                        check_title_exclusions,
                    )

                    excluded_term = check_title_exclusions(job_record, goals_profile.deal_breakers)
                    if excluded_term:
                        from src.db.job_repo import update_job_status

                        await update_job_status(
                            session,
                            job_record.id,
                            "skipped",
                            reason=f"Title pre-filter: '{excluded_term}'",
                        )
                        logger.info(
                            "prefilter_title_excluded",
                            job_id=job_record.id,
                            title=job_record.job_title,
                            term=excluded_term,
                        )
                        continue

                    # Pre-filter: check keyword presence in description
                    if not check_keyword_presence(job_record, filter_keywords):
                        from src.db.job_repo import update_job_status

                        await update_job_status(
                            session,
                            job_record.id,
                            "skipped",
                            reason="Pre-filter: insufficient keyword matches",
                        )
                        logger.info(
                            "prefilter_keyword_excluded",
                            job_id=job_record.id,
                            title=job_record.job_title,
                            company=job_record.company,
                        )
                        continue

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
        else:
            logger.info("pipeline_discovery_and_scoring_skipped")

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
                        supplementary_context=goals_profile.supplementary_context,
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
                        # External apply routing based on configurable threshold:
                        # - Score >= external_apply_threshold: auto-submit via Vision Agent
                        # - Score below threshold: resume tailored, notify user to apply manually
                        ext_threshold = settings.external_apply_threshold

                        if (job_record.fit_score or 0) >= ext_threshold:
                            # High-match: attempt auto-submission via Vision Agent
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
                        else:
                            # Below auto-apply threshold: resume is tailored (PDF ready),
                            # notify user and add to human queue for manual submission.
                            from src.db.job_repo import update_job_status
                            from src.pipeline.notification_service import notify

                            job_record.queue_reason = "resume_ready_external_apply"
                            await update_job_status(
                                session,
                                job_record.id,
                                "applying",
                                reason="External apply — resume tailored, "
                                "awaiting manual submission",
                            )

                            if sms_settings:
                                await notify(
                                    session=session,
                                    job_record=job_record,
                                    trigger_reason="resume_ready_go_apply",
                                    sms_settings=sms_settings,
                                )

                            logger.info(
                                "pipeline_external_apply_resume_ready",
                                job_id=job_record.id,
                                fit_score=job_record.fit_score,
                                pdf_path=job_record.tailored_resume_pdf,
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
        # Step 11: Close the page we created (but NOT the browser — it's the user's Chrome)
        if browser_context:
            try:
                # Only close pages we created, not the whole context
                for p in browser_context.pages:
                    if p != page:
                        continue
                    await p.close()
            except Exception as exc:
                logger.error("pipeline_page_close_error", error=str(exc))
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


def _load_cookies_from_state(state_path: str) -> list[dict[str, object]]:
    """Load cookies from a Playwright storage state JSON file.

    Args:
        state_path: Path to the storage-state.json file.

    Returns:
        List of cookie dicts suitable for browser_context.add_cookies().
    """
    import json

    with open(state_path) as f:
        state = json.load(f)

    return state.get("cookies", [])
