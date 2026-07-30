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
from src.integrations.ntfy_client import NtfyPayload, NtfySettings, publish
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.easy_apply_stage import run_easy_apply
from src.pipeline.health_checker import check_session_health
from src.pipeline.notification_service import NotificationSettings, send_run_summary
from src.pipeline.run_summary import RunStats, generate_summary_text, store_run_summary
from src.pipeline.scoring_stage import run_scoring
from src.pipeline.shadow_scoring import run_shadow_scoring, store_comparison
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

    # Generate a unique run_id for this pipeline execution
    run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M")

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
        await session.commit()

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

    # Build unified notification settings (ntfy only — SMS deprecated)
    notification_settings = await _build_notification_settings(session, settings)

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
    core_keywords: list[str] = []
    supporting_keywords: list[str] = []
    if claude_client and not skip_discovery:
        from src.pipeline.prefilter import (
            compute_context_hash,
            generate_tiered_filter_keywords,
        )

        current_hash = compute_context_hash(
            goals_profile.supplementary_context,
            goals_profile.career_objective,
            goals_profile.target_titles,
        )
        keyword_config = await get_config(session, "filter_keywords") or {}
        stored_hash = keyword_config.get("hash")
        stored_core = keyword_config.get("core", [])
        stored_supporting = keyword_config.get("supporting", [])
        # Backward compat: old format stored flat "keywords" list
        stored_keywords = keyword_config.get("keywords", [])

        if stored_hash == current_hash and (stored_core or stored_keywords):
            if stored_core:
                core_keywords = stored_core
                supporting_keywords = stored_supporting
                filter_keywords = stored_core + stored_supporting
            else:
                # Legacy flat format — use as-is until regenerated
                filter_keywords = stored_keywords
            logger.info(
                "prefilter_keywords_loaded_from_cache",
                core_count=len(core_keywords),
                supporting_count=len(supporting_keywords),
                total=len(filter_keywords),
            )
        else:
            logger.info("prefilter_keywords_regenerating", reason="profile_changed")
            tiered = await generate_tiered_filter_keywords(
                claude_client=claude_client,
                supplementary_context=goals_profile.supplementary_context,
                career_objective=goals_profile.career_objective,
                target_titles=goals_profile.target_titles,
            )
            core_keywords = tiered["core"]
            supporting_keywords = tiered["supporting"]
            filter_keywords = core_keywords + supporting_keywords
            await set_config(
                session,
                "filter_keywords",
                {
                    "hash": current_hash,
                    "core": core_keywords,
                    "supporting": supporting_keywords,
                    # Keep flat "keywords" for backward compat with web app
                    "keywords": filter_keywords,
                },
            )
            await session.commit()
    elif not skip_discovery:
        # No Claude client — try to load cached keywords
        keyword_config = await get_config(session, "filter_keywords") or {}
        core_keywords = keyword_config.get("core", [])
        supporting_keywords = keyword_config.get("supporting", [])
        filter_keywords = keyword_config.get("keywords", [])
        if not filter_keywords and (core_keywords or supporting_keywords):
            filter_keywords = core_keywords + supporting_keywords

    # Step 3.6: Session health check before launching browser
    cdp_url = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")
    health_result = await check_session_health(cdp_url)

    if health_result.error_message:
        # Health check failed — skip the pipeline run and notify
        logger.warning(
            "pipeline_health_check_failed",
            chrome_reachable=health_result.chrome_reachable,
            linkedin_authenticated=health_result.linkedin_authenticated,
            error=health_result.error_message,
        )
        # Send ntfy notification with specific failure reason
        if notification_settings.ntfy_enabled and notification_settings.ntfy:
            payload = NtfyPayload(
                topic=notification_settings.ntfy.urgent_topic,
                title="Job Automator",
                message=f"Pipeline skipped — {health_result.error_message}",
                priority=4,
                tags=["warning"],
                actions=None,
            )
            await publish(payload, notification_settings.ntfy)
        logger.info("pipeline_run_skipped_health_check_failed")
        return
    else:
        # Health check passed — update system_state.last_health_check_at
        current_state = await get_config(session, "system_state") or {}
        current_state["last_health_check_at"] = health_result.checked_at
        await set_config(session, "system_state", current_state)
        await session.commit()
        logger.info(
            "pipeline_health_check_passed",
            checked_at=health_result.checked_at,
        )

    # Step 4: Launch Playwright persistent context
    logger.info("pipeline_launching_browser", user_data_dir=_USER_DATA_DIR)
    browser_context: BrowserContext | None = None

    try:
        pw = await async_playwright().start()

        # Connect to the user's Chrome instance via CDP (remote debugging)
        # This uses the real browser session — no login needed
        logger.info("pipeline_connecting_to_chrome", cdp_url=cdp_url)

        try:
            browser = await _connect_to_chrome(pw, cdp_url)
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

            # Cross-run dedup: load job IDs discovered in the last 7 days
            from sqlalchemy import text as sa_text

            known_ids_result = await session.execute(
                sa_text(
                    "SELECT id FROM job_records WHERE discovered_at > datetime('now', '-7 days')"
                )
            )
            known_job_ids: set[str] = {row[0] for row in known_ids_result.all()}
            logger.info("pipeline_known_job_ids_loaded", count=len(known_job_ids))

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

                try:
                    query_results = await discover_and_extract_jobs(
                        page=page,
                        config=query_config,
                        session=session,
                        max_pages=5,
                        known_job_ids=known_job_ids,
                    )
                    discovered.extend(query_results)
                    logger.info(
                        "pipeline_query_completed",
                        keywords=query_keywords,
                        jobs_found=len(query_results),
                    )
                except Exception as query_exc:
                    logger.error(
                        "pipeline_query_failed",
                        keywords=query_keywords,
                        error=str(query_exc)[:200],
                    )
                    # Continue with remaining queries rather than killing the run
                    continue

            # Limit to 5 jobs in dry run mode to control costs
            if settings.dry_run and len(discovered) > 5:
                discovered = discovered[:5]
                logger.info("pipeline_dry_run_limited", total_found=len(discovered), limit=5)

            logger.info("pipeline_discovery_completed", new_jobs=len(discovered))

            # Create JobRecords with title, company, and description already populated
            # First, check which jobs already exist to avoid IntegrityError
            existing_ids: set[str] = set()
            for job in discovered:
                result = await session.execute(
                    select(JobRecord.id).where(JobRecord.id == job.job_id)
                )
                if result.scalar_one_or_none() is not None:
                    existing_ids.add(job.job_id)

            new_count = 0
            for job in discovered:
                if job.job_id in existing_ids:
                    # Job already exists — update external_url if we now have one
                    if job.external_url:
                        result = await session.execute(
                            select(JobRecord).where(JobRecord.id == job.job_id)
                        )
                        record = result.scalar_one_or_none()
                        if record and not record.external_url:
                            record.external_url = job.external_url
                            logger.debug(
                                "pipeline_existing_job_url_updated",
                                job_id=job.job_id,
                                external_url=job.external_url[:80],
                            )
                    continue

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
                        record.run_id = run_id
                        if job.external_url:
                            record.external_url = job.external_url

                    new_count += 1
                    logger.info(
                        "job_record_created",
                        job_id=job.job_id,
                        title=job.title,
                        company=job.company,
                        apply_type=job.apply_type,
                    )
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    logger.error(
                        "pipeline_job_record_creation_failed",
                        job_id=job.job_id,
                        error=str(exc)[:200],
                    )

            logger.info(
                "pipeline_jobs_persisted",
                new=new_count,
                skipped_existing=len(existing_ids),
                total_discovered=len(discovered),
            )

            # Step 7.5: Blacklist filtering — check extracted jobs before scoring
            from src.db.blacklist_repo import build_blacklist_config, get_all_entries
            from src.db.blacklist_repo import increment_hit_count as _increment_hit_count
            from src.pipeline.blacklist_filter import check_blacklist

            blacklist_config = await build_blacklist_config(session)
            # Build a lookup map: (entry_type, value_lower) -> entry_id
            all_bl_entries = await get_all_entries(session)
            _bl_entry_lookup: dict[tuple[str, str], int] = {
                (e.entry_type, e.value.lower()): e.id for e in all_bl_entries
            }

            extracted_for_bl = await _get_jobs_by_status(session, "extracted")
            blacklisted_count = 0

            for job_record in extracted_for_bl:
                is_blacklisted, matched_entry = check_blacklist(
                    company=job_record.company or "",
                    title=job_record.job_title or "",
                    blacklist=blacklist_config,
                )
                if is_blacklisted:
                    from src.db.job_repo import update_job_status

                    await update_job_status(
                        session,
                        job_record.id,
                        "skipped",
                        reason=f"blacklisted: {matched_entry}",
                    )
                    logger.info(
                        "pipeline_blacklist_skipped",
                        job_id=job_record.id,
                        title=job_record.job_title,
                        company=job_record.company,
                        matched_entry=matched_entry,
                    )
                    # Increment hit_count on the matched blacklist entry
                    if matched_entry:
                        # Parse "company:Revature" or "title:intern"
                        entry_type_key, entry_value = matched_entry.split(":", 1)
                        bl_type = "company" if entry_type_key == "company" else "title_pattern"
                        entry_id = _bl_entry_lookup.get((bl_type, entry_value.lower()))
                        if entry_id is not None:
                            await _increment_hit_count(session, entry_id)
                    blacklisted_count += 1
                    await session.commit()

            if blacklisted_count > 0:
                logger.info(
                    "pipeline_blacklist_filtering_completed",
                    blacklisted=blacklisted_count,
                )

            # Step 8: Run scoring for jobs in "extracted" status
            if claude_client:
                extracted_jobs = await _get_jobs_by_status(session, "extracted")
                resume_content = await _load_resume_content(gdocs_client)

                # Shadow scoring config: read trial settings
                shadow_mode_enabled = bool(
                    await get_config(session, "shadow_mode_enabled")
                )
                local_score_cutoff_raw = await get_config(session, "local_score_cutoff")
                local_score_cutoff: int = (
                    int(local_score_cutoff_raw) if local_score_cutoff_raw is not None else 40
                )

                # Get local_scorer instance (set up on app.state by startup in task 10.1)
                local_scorer = None
                if shadow_mode_enabled:
                    try:
                        from src.scoring.local_scorer import _active_scorer

                        local_scorer = _active_scorer
                    except Exception:
                        local_scorer = None

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
                        check_description_length,
                        check_keyword_presence,
                        check_tiered_keyword_presence,
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
                        await session.commit()
                        continue

                    # Pre-filter: check description length (skip recruiter spam)
                    if not check_description_length(job_record):
                        from src.db.job_repo import update_job_status

                        await update_job_status(
                            session,
                            job_record.id,
                            "skipped",
                            reason="Pre-filter: description too short",
                        )
                        logger.info(
                            "prefilter_description_too_short",
                            job_id=job_record.id,
                            title=job_record.job_title,
                            length=len(job_record.description_text or ""),
                        )
                        await session.commit()
                        continue

                    # Pre-filter: check keyword presence in description (tiered)
                    if core_keywords or supporting_keywords:
                        # Use tiered matching when tiered keywords are available
                        if not check_tiered_keyword_presence(
                            job_record, core_keywords, supporting_keywords
                        ):
                            from src.db.job_repo import update_job_status

                            await update_job_status(
                                session,
                                job_record.id,
                                "skipped",
                                reason="Pre-filter: insufficient keyword matches (tiered)",
                            )
                            logger.info(
                                "prefilter_keyword_excluded",
                                job_id=job_record.id,
                                title=job_record.job_title,
                                company=job_record.company,
                            )
                            await session.commit()
                            continue
                    elif filter_keywords:
                        # Fallback to flat keyword matching (legacy)
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
                            await session.commit()
                            continue

                    # Pre-filter: check salary range against minimum
                    from src.pipeline.prefilter import check_salary_filter

                    if not check_salary_filter(job_record, goals_profile.min_salary):
                        from src.db.job_repo import update_job_status

                        await update_job_status(
                            session,
                            job_record.id,
                            "skipped",
                            reason="Pre-filter: salary below minimum",
                        )
                        await session.commit()
                        continue

                    try:
                        # Shadow scoring: run local scorer before Claude (does NOT affect pipeline)
                        local_score: int | None = None
                        if (
                            shadow_mode_enabled
                            and local_scorer is not None
                            and local_scorer.is_ready
                        ):
                            local_score = await run_shadow_scoring(
                                job_record=job_record,
                                session=session,
                                local_scorer=local_scorer,
                                cutoff=local_score_cutoff,
                            )

                        # Claude scoring (unchanged — drives all pipeline decisions)
                        await run_scoring(
                            job_record=job_record,
                            session=session,
                            claude_client=claude_client,
                            resume_content=resume_content,
                            goals_profile=goals_json,
                            deal_breakers=goals_profile.deal_breakers,
                            good_fit_threshold=settings.good_fit_threshold,
                            stretch_threshold=settings.stretch_threshold,
                            notification_settings=notification_settings,
                        )

                        # Store comparison record after Claude scoring completes
                        if shadow_mode_enabled:
                            model_version = (
                                local_scorer.model_version
                                if local_scorer is not None
                                else None
                            )
                            await store_comparison(
                                session=session,
                                job_id=job_record.id,
                                local_score=local_score,
                                claude_score=job_record.fit_score,
                                model_version=model_version,
                                cutoff=local_score_cutoff,
                            )
                            logger.info(
                                "shadow_scoring_comparison_stored",
                                job_id=job_record.id,
                                local_score=local_score,
                                claude_score=job_record.fit_score,
                                score_difference=(
                                    (job_record.fit_score - local_score)
                                    if local_score is not None
                                    else None
                                ),
                                model_version=model_version,
                            )

                        logger.info(
                            "pipeline_scoring_completed",
                            job_id=job_record.id,
                            new_status=job_record.status,
                        )
                        await session.commit()
                    except Exception as exc:
                        logger.error(
                            "pipeline_scoring_error",
                            job_id=job_record.id,
                            error=str(exc),
                        )
            else:
                logger.warning("pipeline_scoring_skipped_no_claude_client")

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
                        notification_settings=notification_settings,
                        supplementary_context=goals_profile.supplementary_context,
                        user_full_name=user_profile.full_name,
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
                            notification_settings=notification_settings,
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

                            cost_before_ext = claude_client.total_cost_usd
                            result = await process_external_apply(
                                job_record=job_record,
                                profile=user_profile,
                                page=page,
                                claude_client=claude_client,
                                min_salary=goals_profile.min_salary,
                                session=session,
                                notification_settings=notification_settings,
                                goals_profile_json=goals_json,
                                supplementary_context=goals_profile.supplementary_context,
                            )
                            ext_cost = claude_client.total_cost_usd - cost_before_ext
                            if ext_cost > 0:
                                existing_cost = float(job_record.claude_cost_usd or "0")
                                job_record.claude_cost_usd = str(
                                    round(existing_cost + ext_cost, 6)
                                )
                            if result.ok:
                                from src.db.job_repo import update_job_status

                                job_record.applied_at = datetime.now(UTC).isoformat()
                                if result.application_notes:
                                    job_record.application_notes = result.application_notes
                                await update_job_status(
                                    session,
                                    job_record.id,
                                    "applied",
                                    reason="External apply submitted via Vision Agent",
                                )
                                # Mark as applied on LinkedIn
                                from src.integrations.linkedin_scraper import (
                                    mark_as_applied_on_linkedin,
                                )

                                await mark_as_applied_on_linkedin(page, job_record.linkedin_url)
                            elif result.reason == "escalation_created":
                                # Escalation was created — pipeline is paused for this job
                                # Job status is managed by the escalation engine
                                from src.db.job_repo import update_job_status

                                job_record.queue_reason = "escalation_pending"
                                await update_job_status(
                                    session,
                                    job_record.id,
                                    "human_queue",
                                    reason=f"Escalation created: {result.error}",
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

                            if notification_settings:
                                await notify(
                                    session=session,
                                    job_record=job_record,
                                    trigger_reason="resume_ready_go_apply",
                                    settings=notification_settings,
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
                    await session.commit()
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

    # Step 12: Generate and publish run summary
    last_run_at: str | None = (
        system_state.get("last_run_at") if system_state else None
    )
    await _generate_and_publish_run_summary(
        session, notification_settings, run_id, last_run_at,
        claude_cost_usd=claude_client.total_cost_usd if claude_client else 0.0,
    )

    # Step 13: Update system_state.last_run_at
    now_iso = datetime.now(UTC).isoformat()
    current_state = await get_config(session, "system_state") or {}
    current_state["last_run_at"] = now_iso
    if current_state.get("status") not in ("paused", "error"):
        current_state["status"] = "idle"
    await set_config(session, "system_state", current_state)
    await session.commit()

    logger.info("pipeline_run_completed", last_run_at=now_iso)


async def _connect_to_chrome(pw, cdp_url: str):
    """Connect to Chrome via CDP with automatic websocket URL discovery.

    Tries multiple strategies in order:
    1. Stored websocket URL from file (fastest, works if Chrome hasn't restarted)
    2. Fresh discovery from Chrome's /json/version endpoint (handles restarts)
    3. Direct CDP URL connection (fallback)

    Updates the stored websocket URL file on successful discovery.

    Args:
        pw: The Playwright instance.
        cdp_url: The base CDP URL (e.g., http://host.docker.internal:9222).

    Returns:
        A connected Browser instance.

    Raises:
        Exception: If all connection strategies fail.
    """
    import httpx

    ws_url_path = os.path.join("data", "chrome-ws-url.txt")

    # Strategy 1: Try stored websocket URL
    if os.path.exists(ws_url_path):
        with open(ws_url_path) as f:
            ws_url = f.read().strip()
        if ws_url:
            try:
                logger.info("chrome_trying_stored_ws_url", ws_url=ws_url[:60])
                browser = await pw.chromium.connect_over_cdp(ws_url)
                return browser
            except Exception as exc:
                logger.warning("chrome_stored_ws_url_stale", error=str(exc)[:80])

    # Strategy 2: Discover fresh websocket URL from /json/version
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                f"{cdp_url}/json/version",
                timeout=5.0,
                headers={"Host": "localhost"},
            )
            if resp.status_code == 200:
                version_data = resp.json()
                ws_url = version_data.get("webSocketDebuggerUrl", "")
                if ws_url:
                    logger.info("chrome_discovered_ws_url", ws_url=ws_url[:60])
                    browser = await pw.chromium.connect_over_cdp(ws_url)
                    # Update the stored file for next time
                    with open(ws_url_path, "w") as f:
                        f.write(ws_url)
                    return browser
    except Exception as exc:
        logger.warning("chrome_discovery_failed", error=str(exc)[:80])

    # Strategy 3: Direct CDP URL
    logger.info("chrome_trying_direct_cdp", url=cdp_url)
    browser = await pw.chromium.connect_over_cdp(cdp_url)
    return browser


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

    SMS has been deprecated in favor of ntfy push notifications.
    This function now always returns None to disable SMS entirely.

    Args:
        settings: The application settings (unused, retained for API compat).

    Returns:
        Always None — SMS is disabled.
    """
    return None


async def _build_notification_settings(
    session: AsyncSession,
    settings: Settings,
) -> NotificationSettings:
    """Build unified NotificationSettings from config DB and application settings.

    Loads ntfy configuration (enabled flag, server URL, topics, LAN URL, API token)
    from the config table and combines with SMS settings from the Settings model.

    Args:
        session: Active async database session.
        settings: The application settings containing Gmail and SMS config.

    Returns:
        A NotificationSettings instance with both ntfy and SMS configuration.
    """
    # Load ntfy config from DB
    ntfy_enabled_raw = await get_config(session, "ntfy_enabled")
    ntfy_enabled = ntfy_enabled_raw is True or ntfy_enabled_raw == "true"

    ntfy_settings: NtfySettings | None = None
    if ntfy_enabled:
        ntfy_server_url = await get_config(session, "ntfy_server_url")
        ntfy_urgent_topic = await get_config(session, "ntfy_urgent_topic")
        ntfy_info_topic = await get_config(session, "ntfy_info_topic")
        lan_base_url = await get_config(session, "lan_base_url")
        api_token = await get_config(session, "api_token")

        if ntfy_server_url and ntfy_urgent_topic and ntfy_info_topic and api_token:
            ntfy_settings = NtfySettings(
                server_url=ntfy_server_url,
                urgent_topic=ntfy_urgent_topic,
                info_topic=ntfy_info_topic,
                lan_base_url=lan_base_url,
                api_token=api_token,
            )
        else:
            logger.warning(
                "ntfy_enabled_but_incomplete_config",
                has_server_url=bool(ntfy_server_url),
                has_urgent_topic=bool(ntfy_urgent_topic),
                has_info_topic=bool(ntfy_info_topic),
                has_api_token=bool(api_token),
            )

    # Build SMS settings
    sms_settings = _build_sms_settings(settings)
    sms_enabled = sms_settings is not None

    return NotificationSettings(
        ntfy_enabled=ntfy_enabled,
        ntfy=ntfy_settings,
        sms_enabled=sms_enabled,
        sms=sms_settings,
    )


async def _generate_and_publish_run_summary(
    session: AsyncSession,
    notification_settings: NotificationSettings,
    run_id: str,
    last_run_at: str | None,
    claude_cost_usd: float = 0.0,
) -> None:
    """Generate delta-based run statistics, store the summary, and publish to ntfy.

    Computes stats based only on NEW activity this run:
    - Jobs discovered/scored/applied/skipped/escalated THIS run (by run_id)
    - Jobs that transitioned to 'applied' since the previous run ended but
      were approved from the Human Queue (inter-run activity)

    Args:
        session: Active async database session.
        notification_settings: Unified notification settings for publishing.
        run_id: The unique identifier for this pipeline run.
        last_run_at: ISO 8601 timestamp of when the previous run completed,
            or None if this is the first run.
    """
    try:
        from sqlalchemy import func

        from src.db.models import StatusTransition

        # --- Delta stats for THIS run (jobs tagged with this run_id) ---
        result = await session.execute(
            select(JobRecord.status, func.count(JobRecord.id))
            .where(JobRecord.run_id == run_id)
            .group_by(JobRecord.status)
        )
        status_counts: dict[str, int] = dict(result.all())

        jobs_discovered = sum(status_counts.values())

        # Count jobs that actually went through Claude scoring (have a fit_score)
        scored_result = await session.execute(
            select(func.count(JobRecord.id))
            .where(JobRecord.run_id == run_id, JobRecord.fit_score.isnot(None))
        )
        jobs_scored = scored_result.scalar() or 0

        # Pre-filtered = skipped without a score (keyword filter caught them)
        prefiltered_result = await session.execute(
            select(func.count(JobRecord.id))
            .where(
                JobRecord.run_id == run_id,
                JobRecord.status == "skipped",
                JobRecord.fit_score.is_(None),
            )
        )
        jobs_prefiltered = prefiltered_result.scalar() or 0

        jobs_approved = (
            status_counts.get("approved_for_apply", 0)
            + status_counts.get("applying", 0)
            + status_counts.get("applied", 0)
        )
        jobs_applied = status_counts.get("applied", 0)
        # Skipped after scoring (have a score but it was too low)
        jobs_skipped = status_counts.get("skipped", 0) - jobs_prefiltered
        jobs_escalated = status_counts.get("scored", 0) + status_counts.get(
            "apply_failed", 0
        ) + status_counts.get("resume_failed", 0)

        # --- Inter-run activity: jobs approved from queue then applied ---
        # These are jobs that were NOT discovered this run but transitioned
        # to 'applied' since the last run completed (user approved from queue)
        jobs_applied_from_queue = 0
        if last_run_at:
            queue_applied_result = await session.execute(
                select(func.count(StatusTransition.id))
                .where(
                    StatusTransition.to_status == "applied",
                    StatusTransition.timestamp > last_run_at,
                    StatusTransition.job_id.notin_(
                        select(JobRecord.id).where(JobRecord.run_id == run_id)
                    ),
                )
            )
            jobs_applied_from_queue = queue_applied_result.scalar() or 0

        stats = RunStats(
            jobs_discovered=jobs_discovered,
            jobs_scored=jobs_scored,
            jobs_prefiltered=jobs_prefiltered,
            jobs_approved=jobs_approved,
            jobs_applied=jobs_applied,
            jobs_skipped=jobs_skipped,
            jobs_escalated=jobs_escalated,
            jobs_applied_from_queue=jobs_applied_from_queue,
            claude_cost_usd=claude_cost_usd,
            errors=[],
        )

        summary_text = generate_summary_text(stats)
        await store_run_summary(session, stats, summary_text)
        await send_run_summary(session, summary_text, notification_settings)
        await session.commit()

        logger.info(
            "pipeline_run_summary_published",
            summary=summary_text[:100],
            run_id=run_id,
        )
    except Exception as exc:
        logger.error("pipeline_run_summary_failed", error=str(exc))


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
