"""Preview pipeline mode — discovery + scoring without application.

Executes the pipeline in preview/dry-run mode: discovers jobs, applies the
blacklist filter, scores remaining jobs via Claude, and persists results as
PreviewRun/PreviewJob records. Never proceeds to tailoring or application.

Jobs already present in the ``job_records`` table are deduplicated and skipped.
Each new job receives a ``projected_action`` computed from its fit score and
the configured thresholds.
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from playwright.async_api import BrowserContext, async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient
from src.api.schemas import GoalsProfile, SearchConfig, Settings
from src.db.blacklist_repo import build_blacklist_config
from src.db.config_repo import get_config, set_config
from src.db.models import JobRecord, PreviewJob, PreviewRun
from src.integrations.gdocs_client import GDocsClient
from src.integrations.linkedin_scraper import DiscoveredJob, discover_and_extract_jobs
from src.pipeline.blacklist_filter import check_blacklist
from src.pipeline.health_checker import check_session_health

logger = structlog.get_logger(__name__)

# Default CDP URL for Chrome remote debugging.
_CDP_URL = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")


def compute_projected_action(
    fit_score: int | None,
    good_fit_threshold: int,
    stretch_threshold: int,
    is_blacklisted: bool,
) -> str:
    """Compute the projected pipeline action for a preview job.

    Determines what action the full pipeline would take based on the job's
    fit score and the configured thresholds.

    Args:
        fit_score: Claude-assigned fit score (0–100), or None if not scored.
        good_fit_threshold: Minimum score for automatic application.
        stretch_threshold: Minimum score for stretch/human-review queue.
        is_blacklisted: Whether the job matched a blacklist entry.

    Returns:
        One of: "blacklisted", "skip", "auto_apply", "stretch_queue".
    """
    if is_blacklisted:
        return "blacklisted"
    if fit_score is None:
        return "skip"
    if fit_score >= good_fit_threshold:
        return "auto_apply"
    if fit_score >= stretch_threshold:
        return "stretch_queue"
    return "skip"


async def promote_preview_jobs(
    session: AsyncSession,
    run_id: str,
    job_ids: list[str],
) -> list[str]:
    """Promote selected preview jobs to the real pipeline.

    Copies matching preview jobs from ``preview_jobs`` to ``job_records`` with
    status ``"approved_for_apply"``, then marks the preview jobs as promoted.

    Args:
        session: Active async database session.
        run_id: The preview run ID that owns the jobs.
        job_ids: List of LinkedIn job IDs to promote.

    Returns:
        List of job IDs that were successfully promoted.
    """
    if not job_ids:
        return []

    # Query preview_jobs for the given run_id and job_ids
    result = await session.execute(
        select(PreviewJob).where(
            PreviewJob.run_id == run_id,
            PreviewJob.job_id.in_(job_ids),
            PreviewJob.promoted == 0,
        )
    )
    preview_jobs = result.scalars().all()

    if not preview_jobs:
        return []

    now = datetime.now(UTC).isoformat()
    promoted_ids: list[str] = []

    for pj in preview_jobs:
        # Create a new JobRecord with status "approved_for_apply"
        job_record = JobRecord(
            id=pj.job_id,
            job_title=pj.job_title,
            company=pj.company,
            linkedin_url=pj.linkedin_url,
            apply_type="easy_apply",
            status="approved_for_apply",
            discovered_at=now,
            updated_at=now,
        )
        session.add(job_record)

        # Mark the preview job as promoted
        pj.promoted = 1
        pj.promoted_at = now

        promoted_ids.append(pj.job_id)

    await session.flush()

    logger.info(
        "preview_jobs_promoted",
        run_id=run_id,
        promoted_count=len(promoted_ids),
        promoted_ids=promoted_ids,
    )

    return promoted_ids


async def run_preview(session: AsyncSession) -> str:
    """Execute a preview pipeline run (discovery + scoring only).

    Performs the following stages:
    1. Session health check — aborts if Chrome/LinkedIn are unhealthy.
    2. Job discovery via LinkedIn scraping.
    3. Deduplication — skips jobs already in ``job_records``.
    4. Blacklist filtering — marks matching jobs as blacklisted.
    5. Scoring via Claude API — scores remaining jobs.
    6. Persists PreviewRun and PreviewJob records.

    Never proceeds to tailoring or application stages.

    Args:
        session: Active async database session.

    Returns:
        The preview run ID (UUID string).

    Raises:
        Exception: If a fatal error occurs. The PreviewRun record will be
            marked as "failed" with the error message.
    """
    run_id = str(uuid4())
    started_at = datetime.now(UTC).isoformat()

    # Create the PreviewRun record
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

    logger.info("preview_run_started", run_id=run_id)

    try:
        # Step 1: Session health check
        health_result = await check_session_health(_CDP_URL)

        if health_result.error_message:
            logger.warning(
                "preview_health_check_failed",
                run_id=run_id,
                error=health_result.error_message,
            )
            await _fail_preview_run(session, preview_run, health_result.error_message)
            # Send notification about the failure
            await _notify_preview_failure(session, health_result.error_message)
            return run_id

        # Update last_health_check_at on success
        current_state = await get_config(session, "system_state") or {}
        current_state["last_health_check_at"] = health_result.checked_at
        await set_config(session, "system_state", current_state)
        await session.flush()

        # Step 2: Load configuration
        goals_profile_raw = await get_config(session, "goals_profile")
        if not goals_profile_raw:
            await _fail_preview_run(session, preview_run, "Goals profile not configured")
            return run_id

        search_config_raw = await get_config(session, "search_config")
        settings_raw = await get_config(session, "settings")

        goals_profile = GoalsProfile.model_validate(goals_profile_raw)
        search_config = SearchConfig.model_validate(search_config_raw or {})
        settings = Settings.model_validate(settings_raw or {})

        good_fit_threshold = settings.good_fit_threshold
        stretch_threshold = settings.stretch_threshold

        # Build Claude client
        claude_client: ClaudeClient | None = None
        if settings.claude_api_key and settings.claude_api_key != "***":
            claude_client = ClaudeClient(api_key=settings.claude_api_key)

        # Build GDocs client for resume loading
        gdocs_client: GDocsClient | None = None
        if settings.gdocs_script_url:
            gdocs_client = GDocsClient(endpoint_url=settings.gdocs_script_url)

        # Build blacklist config
        blacklist_config = await build_blacklist_config(session)

        # Step 3: Connect to Chrome and discover jobs
        discovered_jobs = await _run_discovery(
            session=session,
            search_config=search_config,
            settings=settings,
        )

        preview_run.total_discovered = len(discovered_jobs)
        await session.flush()

        logger.info(
            "preview_discovery_completed",
            run_id=run_id,
            total_discovered=len(discovered_jobs),
        )

        # Step 4: Deduplication — filter out jobs already in job_records
        new_jobs = await _deduplicate_jobs(session, discovered_jobs)

        logger.info(
            "preview_deduplication_completed",
            run_id=run_id,
            before=len(discovered_jobs),
            after=len(new_jobs),
            duplicates_skipped=len(discovered_jobs) - len(new_jobs),
        )

        # Step 5: Blacklist filtering
        non_blacklisted: list[DiscoveredJob] = []
        blacklisted_jobs: list[tuple[DiscoveredJob, str]] = []

        for job in new_jobs:
            is_blacklisted, matched_entry = check_blacklist(
                company=job.company,
                title=job.title,
                blacklist=blacklist_config,
            )
            if is_blacklisted:
                blacklisted_jobs.append((job, matched_entry or "unknown"))
                logger.info(
                    "preview_job_blacklisted",
                    run_id=run_id,
                    job_id=job.job_id,
                    company=job.company,
                    title=job.title,
                    matched_entry=matched_entry,
                )
            else:
                non_blacklisted.append(job)

        preview_run.total_blacklisted = len(blacklisted_jobs)
        await session.flush()

        # Persist blacklisted jobs as PreviewJob records
        for job, matched_entry in blacklisted_jobs:
            preview_job = PreviewJob(
                run_id=run_id,
                job_id=job.job_id,
                job_title=job.title,
                company=job.company,
                linkedin_url=job.linkedin_url,
                fit_score=None,
                fit_rationale=f"Blacklisted: {matched_entry}",
                projected_action="blacklisted",
            )
            session.add(preview_job)

        await session.flush()

        # Step 6: Score remaining jobs
        scored_count = 0

        if claude_client and non_blacklisted:
            resume_content = await _load_resume_content(gdocs_client)

            # Append supplementary context for richer scoring
            if goals_profile.supplementary_context:
                resume_content = (
                    f"{resume_content}\n\n"
                    f"## Additional Context (not part of resume)\n"
                    f"{goals_profile.supplementary_context}"
                )

            goals_json = goals_profile.model_dump_json()

            for job in non_blacklisted:
                try:
                    # Score the job
                    result = await claude_client.score_fit(
                        description=job.description,
                        resume=resume_content,
                        goals=goals_json,
                    )

                    fit_score = result.fit_score
                    fit_rationale = result.rationale

                    # Compute projected action
                    projected_action = compute_projected_action(
                        fit_score=fit_score,
                        good_fit_threshold=good_fit_threshold,
                        stretch_threshold=stretch_threshold,
                        is_blacklisted=False,
                    )

                    # Persist PreviewJob record
                    preview_job = PreviewJob(
                        run_id=run_id,
                        job_id=job.job_id,
                        job_title=job.title,
                        company=job.company,
                        linkedin_url=job.linkedin_url,
                        fit_score=fit_score,
                        fit_rationale=fit_rationale,
                        projected_action=projected_action,
                    )
                    session.add(preview_job)
                    scored_count += 1

                    logger.info(
                        "preview_job_scored",
                        run_id=run_id,
                        job_id=job.job_id,
                        fit_score=fit_score,
                        projected_action=projected_action,
                    )

                except Exception as exc:
                    # Claude API error — skip this job but continue with others
                    logger.error(
                        "preview_scoring_error",
                        run_id=run_id,
                        job_id=job.job_id,
                        error=str(exc),
                    )
                    # Still create a PreviewJob record with no score
                    preview_job = PreviewJob(
                        run_id=run_id,
                        job_id=job.job_id,
                        job_title=job.title,
                        company=job.company,
                        linkedin_url=job.linkedin_url,
                        fit_score=None,
                        fit_rationale=f"Scoring failed: {str(exc)[:200]}",
                        projected_action="skip",
                    )
                    session.add(preview_job)

        elif not claude_client:
            # No Claude client — create PreviewJob records without scores
            logger.warning("preview_scoring_skipped_no_claude_client", run_id=run_id)
            for job in non_blacklisted:
                preview_job = PreviewJob(
                    run_id=run_id,
                    job_id=job.job_id,
                    job_title=job.title,
                    company=job.company,
                    linkedin_url=job.linkedin_url,
                    fit_score=None,
                    fit_rationale=None,
                    projected_action="skip",
                )
                session.add(preview_job)

        # Finalize the preview run
        preview_run.total_scored = scored_count
        preview_run.status = "completed"
        preview_run.completed_at = datetime.now(UTC).isoformat()
        await session.flush()

        logger.info(
            "preview_run_completed",
            run_id=run_id,
            total_discovered=preview_run.total_discovered,
            total_scored=scored_count,
            total_blacklisted=preview_run.total_blacklisted,
        )

    except Exception as exc:
        logger.error("preview_run_fatal_error", run_id=run_id, error=str(exc))
        await _fail_preview_run(session, preview_run, str(exc))

    return run_id


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fail_preview_run(
    session: AsyncSession,
    preview_run: PreviewRun,
    error_message: str,
) -> None:
    """Mark a preview run as failed with an error message.

    Args:
        session: Active async database session.
        preview_run: The PreviewRun record to update.
        error_message: Human-readable error description.
    """
    preview_run.status = "failed"
    preview_run.error_message = error_message
    preview_run.completed_at = datetime.now(UTC).isoformat()
    await session.flush()


async def _notify_preview_failure(
    session: AsyncSession,
    error_message: str,
) -> None:
    """Send an ntfy notification about a preview run failure.

    Loads ntfy configuration from the database and sends a notification
    if ntfy is enabled and properly configured.

    Args:
        session: Active async database session.
        error_message: The error message to include in the notification.
    """
    from src.integrations.ntfy_client import NtfyPayload, NtfySettings, publish

    # Check if ntfy is configured
    ntfy_enabled_raw = await get_config(session, "ntfy_enabled")
    ntfy_enabled = ntfy_enabled_raw is True or ntfy_enabled_raw == "true"

    if not ntfy_enabled:
        return

    ntfy_server_url = await get_config(session, "ntfy_server_url")
    ntfy_urgent_topic = await get_config(session, "ntfy_urgent_topic")
    ntfy_info_topic = await get_config(session, "ntfy_info_topic")
    api_token = await get_config(session, "api_token")

    if not ntfy_server_url or not ntfy_urgent_topic or not ntfy_info_topic or not api_token:
        return

    lan_base_url = await get_config(session, "lan_base_url")

    ntfy_settings = NtfySettings(
        server_url=ntfy_server_url,
        urgent_topic=ntfy_urgent_topic,
        info_topic=ntfy_info_topic,
        lan_base_url=lan_base_url,
        api_token=api_token,
    )

    payload = NtfyPayload(
        topic=ntfy_urgent_topic,
        title="Preview Run Failed",
        message=f"Preview pipeline skipped — {error_message}",
        priority=4,
        tags=["warning"],
        actions=None,
    )
    await publish(payload, ntfy_settings)


async def _deduplicate_jobs(
    session: AsyncSession,
    discovered_jobs: list[DiscoveredJob],
) -> list[DiscoveredJob]:
    """Filter out jobs that already exist in the job_records table.

    Args:
        session: Active async database session.
        discovered_jobs: List of discovered jobs to check.

    Returns:
        List of jobs that are NOT already in job_records.
    """
    if not discovered_jobs:
        return []

    # Get all job IDs from the discovered list
    job_ids = [job.job_id for job in discovered_jobs]

    # Query existing job_records for these IDs
    result = await session.execute(select(JobRecord.id).where(JobRecord.id.in_(job_ids)))
    existing_ids = set(result.scalars().all())

    # Filter out duplicates
    new_jobs = [job for job in discovered_jobs if job.job_id not in existing_ids]
    return new_jobs


async def _run_discovery(
    session: AsyncSession,
    search_config: SearchConfig,
    settings: Settings,
) -> list[DiscoveredJob]:
    """Run the job discovery stage using Playwright and LinkedIn scraping.

    Connects to Chrome via CDP, runs each configured search query, and
    aggregates all discovered jobs.

    Args:
        session: Active async database session.
        search_config: The search configuration with keywords and filters.
        settings: Application settings.

    Returns:
        List of all discovered jobs across all search queries.
    """
    pw = await async_playwright().start()
    browser_context: BrowserContext | None = None

    try:
        # Connect to Chrome via CDP
        browser = await _connect_to_chrome(pw, _CDP_URL)
        browser_context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await browser_context.new_page()

        # Run each search query
        keyword_list = search_config.get_keyword_list()
        if not keyword_list:
            keyword_list = [""]  # Run once with no keywords as fallback

        discovered: list[DiscoveredJob] = []

        for i, query_keywords in enumerate(keyword_list):
            # Randomized delay between queries
            if i > 0:
                delay = random.uniform(10.0, 20.0)
                logger.info("preview_inter_query_delay", delay_seconds=round(delay, 1))
                await asyncio.sleep(delay)

            # Build a per-query config
            query_config = SearchConfig(
                keywords=query_keywords or None,
                location=search_config.location,
                job_type=search_config.job_type,
                experience_level=search_config.experience_level,
                remote_pref=search_config.remote_pref,
            )
            logger.info("preview_running_search_query", keywords=query_keywords)

            query_results = await discover_and_extract_jobs(
                page=page,
                config=query_config,
                session=session,
                max_pages=5,
                skip_viewed=settings.skip_viewed_jobs,
            )
            discovered.extend(query_results)
            logger.info(
                "preview_query_completed",
                keywords=query_keywords,
                jobs_found=len(query_results),
            )

        return discovered

    finally:
        # Close the page we created but not the browser (it's the user's Chrome)
        if browser_context:
            try:
                pages = browser_context.pages
                for p in pages:
                    await p.close()
            except Exception as exc:
                logger.error("preview_page_close_error", error=str(exc))
        try:
            await pw.stop()
        except Exception:
            pass


async def _connect_to_chrome(pw, cdp_url: str):
    """Connect to Chrome via CDP with websocket URL discovery.

    Mirrors the connection strategy from job_pipeline.py.

    Args:
        pw: The Playwright instance.
        cdp_url: The base CDP URL.

    Returns:
        A connected Browser instance.

    Raises:
        Exception: If connection fails.
    """
    import httpx

    ws_url_path = os.path.join("data", "chrome-ws-url.txt")

    # Strategy 1: Try stored websocket URL
    if os.path.exists(ws_url_path):
        with open(ws_url_path) as f:
            ws_url = f.read().strip()
        if ws_url:
            try:
                logger.info("preview_chrome_trying_stored_ws_url", ws_url=ws_url[:60])
                browser = await pw.chromium.connect_over_cdp(ws_url)
                return browser
            except Exception:
                logger.debug("preview_chrome_stored_ws_url_failed")

    # Strategy 2: Fresh discovery from /json/version
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cdp_url}/json/version", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                ws_url = data.get("webSocketDebuggerUrl", "")
                if ws_url:
                    # Save for next time
                    os.makedirs(os.path.dirname(ws_url_path), exist_ok=True)
                    with open(ws_url_path, "w") as f:
                        f.write(ws_url)
                    browser = await pw.chromium.connect_over_cdp(ws_url)
                    logger.info("preview_chrome_connected_via_discovery", ws_url=ws_url[:60])
                    return browser
    except Exception:
        logger.debug("preview_chrome_discovery_failed")

    # Strategy 3: Direct CDP URL
    browser = await pw.chromium.connect_over_cdp(cdp_url)
    logger.info("preview_chrome_connected_direct", cdp_url=cdp_url)
    return browser


async def _load_resume_content(gdocs_client: GDocsClient | None) -> str:
    """Load the resume content from Google Docs or return a placeholder.

    Falls back to an empty string if the client is not configured or the
    read fails.

    Args:
        gdocs_client: Configured GDocs client, or None.

    Returns:
        The resume content as plain text.
    """
    if gdocs_client is None:
        logger.warning("preview_resume_load_skipped_no_gdocs_client")
        return ""

    try:
        return await gdocs_client.read_resume()
    except Exception as exc:
        logger.error("preview_resume_load_error", error=str(exc))
        return ""
