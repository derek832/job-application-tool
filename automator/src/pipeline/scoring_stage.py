"""Pipeline stage: fit scoring and classification.

Accepts a job record with an extracted description, scores it against the
candidate's resume and goals via the Claude API, classifies the result, and
routes the job to the appropriate next state (approved_for_apply, skipped,
or human queue).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient, FitScoreResult
from src.db.job_repo import update_job_status
from src.db.models import JobRecord, NotificationLog
from src.integrations.sms_gateway import SMSSettings, compose_sms, send_sms
from src.integrations.sms_rate_limiter import check_rate_limit
from src.pipeline.fit_classifier import classify_fit, is_threshold_boundary

logger = structlog.get_logger(__name__)


async def run_scoring(
    job_record: JobRecord,
    session: AsyncSession,
    claude_client: ClaudeClient,
    resume_content: str,
    goals_profile: str,
    deal_breakers: list[str],
    good_fit_threshold: int,
    stretch_threshold: int,
    sms_settings: SMSSettings | None = None,
) -> None:
    """Score a job record and route it based on fit classification.

    Calls the Claude API to score the job description against the candidate's
    resume and goals. Stores the score and rationale, checks for deal-breakers,
    classifies the fit, detects threshold boundaries, and routes the job to
    the appropriate next state.

    Args:
        job_record: The job record to score (must have description_text populated).
        session: Active async database session.
        claude_client: Configured Claude API client instance.
        resume_content: The Resume_Base content as plain text.
        goals_profile: The Goals_Profile as a JSON string.
        deal_breakers: List of deal-breaker keywords/phrases from the goals profile.
        good_fit_threshold: Score at or above which a job is a good fit.
        stretch_threshold: Score at or above which a job is a stretch role.
        sms_settings: SMS gateway settings for notifications. If None, SMS is skipped.

    Raises:
        ScoringError: If the Claude API call fails after all retries.
    """
    logger.info(
        "scoring_stage_start",
        job_id=job_record.id,
        job_title=job_record.job_title,
        company=job_record.company,
    )

    # 1. Call Claude API for fit scoring
    result: FitScoreResult = await claude_client.score_fit(
        description=job_record.description_text or "",
        resume=resume_content,
        goals=goals_profile,
    )

    # 2. Store fit_score and fit_rationale in job_record
    job_record.fit_score = result.fit_score
    job_record.fit_rationale = result.rationale

    logger.info(
        "scoring_result_stored",
        job_id=job_record.id,
        fit_score=result.fit_score,
        deal_breaker_found=result.deal_breaker_found,
    )

    # 3. Check deal-breakers (rely on Claude's contextual analysis only)
    # We don't do substring matching because terms like "Associate" can appear
    # in non-deal-breaker contexts (e.g. "associate with teams", "Associate's degree")
    deal_breaker_found = result.deal_breaker_found
    matched_term = result.deal_breaker_term

    # 4. If deal-breaker found → classify as "skip", set status to "skipped"
    if deal_breaker_found:
        logger.info(
            "deal_breaker_detected",
            job_id=job_record.id,
            matched_term=matched_term,
        )
        job_record.scored_at = datetime.now(UTC).isoformat()
        await update_job_status(
            session,
            job_record.id,
            "skipped",
            reason=f"Deal-breaker detected: {matched_term}",
        )
        await session.flush()
        return

    # 5. Classify fit
    classification = classify_fit(result.fit_score, good_fit_threshold, stretch_threshold)

    # 6. Check boundary
    boundary = is_threshold_boundary(result.fit_score, good_fit_threshold, stretch_threshold)

    # 7. Route based on classification and boundary
    job_record.scored_at = datetime.now(UTC).isoformat()

    if boundary:
        # Boundary score → add to human queue, send SMS
        job_record.queue_reason = "score_at_threshold_boundary"
        await update_job_status(
            session,
            job_record.id,
            "scored",
            reason="Score at threshold boundary, requires human review",
        )
        logger.info(
            "boundary_score_queued",
            job_id=job_record.id,
            fit_score=result.fit_score,
            good_fit_threshold=good_fit_threshold,
            stretch_threshold=stretch_threshold,
        )
        await _send_notification(
            session=session,
            job_record=job_record,
            trigger_reason="score_at_threshold_boundary",
            sms_settings=sms_settings,
        )

    elif classification == "good_fit":
        # Good fit and not boundary → approved_for_apply
        await update_job_status(
            session,
            job_record.id,
            "approved_for_apply",
            reason=f"Good fit (score={result.fit_score})",
        )
        logger.info(
            "job_approved_for_apply",
            job_id=job_record.id,
            fit_score=result.fit_score,
        )

    elif classification == "stretch_role":
        # Stretch role → add to human queue, send SMS
        job_record.queue_reason = "stretch_role"
        await update_job_status(
            session,
            job_record.id,
            "scored",
            reason="Stretch role, requires human review",
        )
        logger.info(
            "stretch_role_queued",
            job_id=job_record.id,
            fit_score=result.fit_score,
        )
        await _send_notification(
            session=session,
            job_record=job_record,
            trigger_reason="stretch_role",
            sms_settings=sms_settings,
        )

    else:
        # Skip → status "skipped"
        await update_job_status(
            session,
            job_record.id,
            "skipped",
            reason=f"Low fit score ({result.fit_score})",
        )
        logger.info(
            "job_skipped_low_score",
            job_id=job_record.id,
            fit_score=result.fit_score,
        )

    await session.flush()


async def _send_notification(
    session: AsyncSession,
    job_record: JobRecord,
    trigger_reason: str,
    sms_settings: SMSSettings | None,
) -> None:
    """Send an SMS notification and log it to the notification_log table.

    Checks the rate limit before sending. Logs the notification attempt
    regardless of success or failure.

    Args:
        session: Active async database session.
        job_record: The job record triggering the notification.
        trigger_reason: The reason for the notification.
        sms_settings: SMS gateway settings. If None, notification is logged but not sent.
    """
    sms_body = compose_sms(
        job_record.job_title, job_record.company, trigger_reason, job_record.fit_score
    )
    now_iso = datetime.now(UTC).isoformat()

    if sms_settings is None:
        logger.warning(
            "sms_settings_not_configured",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        # Log the notification attempt as unsuccessful (no settings)
        log_entry = NotificationLog(
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            sms_body=sms_body,
            sent_at=now_iso,
            success=0,
            error_message="SMS settings not configured",
        )
        session.add(log_entry)
        await session.flush()
        return

    # Check rate limit
    allowed = await check_rate_limit(session)
    if not allowed:
        logger.warning(
            "sms_rate_limited",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        log_entry = NotificationLog(
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            sms_body=sms_body,
            sent_at=now_iso,
            success=0,
            error_message="Rate limit exceeded",
        )
        session.add(log_entry)
        await session.flush()
        return

    # Send SMS
    result = await send_sms(sms_body, sms_settings)

    log_entry = NotificationLog(
        job_id=job_record.id,
        trigger_reason=trigger_reason,
        sms_body=sms_body,
        sent_at=now_iso,
        success=1 if result.ok else 0,
        error_message=result.error,
    )
    session.add(log_entry)
    await session.flush()

    if result.ok:
        logger.info(
            "sms_notification_sent",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
    else:
        logger.error(
            "sms_notification_failed",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
            error=result.error,
        )
