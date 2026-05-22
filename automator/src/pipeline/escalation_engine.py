"""Escalation Engine — human-in-the-loop escalation management.

Manages the pause/resume lifecycle when the Vision Agent encounters
obstacles requiring human intervention (CAPTCHAs) or high-value jobs
that deserve personalized answers (open-ended questions on high-scoring
jobs).

This module encapsulates:
- Freshness tier calculation from ``discovered_at`` timestamps
- Timeout deadline computation per freshness tier
- Escalation record creation, resolution, and timeout handling
- CAPTCHA polling loop (5s interval, 30 min max) with domain deduplication

Validates: Requirements 1.1, 1.4, 1.6, 2.1, 4.1, 4.2, 4.3, 4.5, 7.1, 7.5
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import EscalationRecord, JobRecord
from src.db.job_repo import update_job_status
from src.integrations.ntfy_client import NtfyResult, publish
from src.integrations.sms_gateway import compose_sms, send_sms
from src.pipeline.notification_service import NotificationSettings

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CAPTCHA Domain Tracking — session-level deduplication
# ---------------------------------------------------------------------------

_solved_captcha_domains: set[str] = set()
"""Tracks ATS domains where CAPTCHAs have been solved during this session.

Used for deduplication: once a CAPTCHA is solved on a domain, subsequent
applications to the same domain during the same browser session should not
re-trigger CAPTCHA escalation unless a new CAPTCHA is actually encountered.

Validates: Requirement 1.6
"""


# ---------------------------------------------------------------------------
# Freshness Tier — determines timeout behavior based on job posting age
# ---------------------------------------------------------------------------


class FreshnessTier(str, Enum):
    """Classification of job posting age into three categories.

    Used to determine the auto-submit timeout duration for human_review
    escalations. Fresh postings get short timeouts to maximize speed-to-apply,
    while older postings give the user more time to personalize.
    """

    FRESH = "fresh"  # < 24 hours old
    RECENT = "recent"  # 24 hours to 7 days old
    STALE = "stale"  # > 7 days old


TIMEOUT_BY_FRESHNESS: dict[FreshnessTier, timedelta] = {
    FreshnessTier.FRESH: timedelta(minutes=45),
    FreshnessTier.RECENT: timedelta(hours=6),
    FreshnessTier.STALE: timedelta(hours=24),
}
"""Mapping from freshness tier to auto-submit timeout duration.

- FRESH (< 24h): 45 minutes — fast turnaround for new postings
- RECENT (24h–7d): 6 hours — moderate window for personalization
- STALE (> 7d): 24 hours — maximum time for older postings
"""


def calculate_freshness_tier(discovered_at: str) -> FreshnessTier:
    """Determine freshness tier by comparing current UTC time to discovered_at.

    Parses the ISO 8601 timestamp and computes the age of the posting.
    Naive timestamps (without timezone info) are assumed to be UTC.

    Args:
        discovered_at: ISO 8601 timestamp string representing when the job
            was discovered/posted.

    Returns:
        The appropriate FreshnessTier based on posting age:
        - FRESH if age < 24 hours
        - RECENT if 24 hours <= age <= 7 days
        - STALE if age > 7 days
    """
    discovered = datetime.fromisoformat(discovered_at)

    # Treat naive datetimes as UTC
    if discovered.tzinfo is None:
        discovered = discovered.replace(tzinfo=UTC)

    now = datetime.now(tz=UTC)
    age = now - discovered

    if age < timedelta(hours=24):
        tier = FreshnessTier.FRESH
    elif age <= timedelta(days=7):
        tier = FreshnessTier.RECENT
    else:
        tier = FreshnessTier.STALE

    logger.debug(
        "freshness_tier_calculated",
        discovered_at=discovered_at,
        age_hours=age.total_seconds() / 3600,
        tier=tier.value,
    )

    return tier


def calculate_timeout_deadline(freshness: FreshnessTier) -> datetime:
    """Return the absolute UTC deadline for auto-submit.

    Adds the timeout duration for the given freshness tier to the current
    UTC time to produce an absolute deadline timestamp.

    Args:
        freshness: The freshness tier determining timeout duration.

    Returns:
        A timezone-aware UTC datetime representing when auto-submit
        should fire if the user hasn't acted.
    """
    timeout_duration = TIMEOUT_BY_FRESHNESS[freshness]
    deadline = datetime.now(tz=UTC) + timeout_duration

    logger.debug(
        "timeout_deadline_calculated",
        freshness_tier=freshness.value,
        timeout_duration_minutes=timeout_duration.total_seconds() / 60,
        deadline=deadline.isoformat(),
    )

    return deadline


# ---------------------------------------------------------------------------
# Escalation Creation
# ---------------------------------------------------------------------------


async def create_escalation(
    session: AsyncSession,
    job_record: JobRecord,
    tier: Literal["captcha", "human_review"],
    form_state_snapshot: dict,
    draft_answers: list[dict] | None,
    page: Page | None,
    notification_settings: NotificationSettings,
) -> EscalationRecord:
    """Create an escalation record, persist it, and return it.

    Enforces one-pending-per-job uniqueness: if a pending escalation already
    exists for the given job, the existing record is returned without creating
    a duplicate.

    For ``human_review`` tier, computes the freshness tier from the job's
    ``discovered_at`` timestamp and sets the timeout deadline accordingly.
    For ``captcha`` tier, timeout_deadline and freshness_tier are set to NULL.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        job_record: The job record being escalated.
        tier: Escalation type — "captcha" or "human_review".
        form_state_snapshot: Dict capturing the current form state (serialized to JSON).
        draft_answers: List of Claude's draft answer dicts; None for CAPTCHA tier.
        page: Playwright Page instance (reserved for future use).
        notification_settings: Notification channel configuration.

    Returns:
        The newly created (or existing pending) EscalationRecord.

    Validates: Requirements 1.1, 2.1, 2.3, 4.1, 4.2, 4.3, 7.1, 7.5
    """
    # --- Uniqueness check: one pending escalation per job ---
    existing_stmt = select(EscalationRecord).where(
        EscalationRecord.job_id == job_record.id,
        EscalationRecord.status == "pending",
    )
    result = await session.execute(existing_stmt)
    existing = result.scalars().first()

    if existing is not None:
        logger.info(
            "escalation_already_pending",
            job_id=job_record.id,
            existing_escalation_id=existing.id,
            tier=existing.tier,
        )
        return existing

    # --- Compute freshness tier and timeout deadline ---
    freshness: FreshnessTier | None = None
    timeout_deadline: datetime | None = None

    if tier == "human_review":
        freshness = calculate_freshness_tier(job_record.discovered_at)
        timeout_deadline = calculate_timeout_deadline(freshness)
    # CAPTCHA tier: freshness_tier = NULL, timeout_deadline = NULL

    # --- Serialize snapshot and draft answers to JSON strings ---
    form_state_json = json.dumps(form_state_snapshot)
    draft_answers_json = json.dumps(draft_answers) if draft_answers is not None else None

    # --- Build the escalation record ---
    now = datetime.now(tz=UTC)
    record = EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_record.id,
        tier=tier,
        form_state_snapshot=form_state_json,
        draft_answers=draft_answers_json,
        timeout_deadline=timeout_deadline.isoformat() if timeout_deadline else None,
        freshness_tier=freshness.value if freshness else None,
        status="pending",
        resolution_method=None,
        created_at=now.isoformat(),
        resolved_at=None,
    )

    # --- Persist to database ---
    session.add(record)
    await session.flush()

    logger.info(
        "escalation_created",
        escalation_id=record.id,
        job_id=job_record.id,
        tier=tier,
        freshness_tier=freshness.value if freshness else None,
        timeout_deadline=record.timeout_deadline,
    )

    # --- Send escalation notification with fallback ---
    await _send_escalation_notification(
        session=session,
        record=record,
        job_record=job_record,
        tier=tier,
        freshness=freshness,
        timeout_deadline=timeout_deadline,
        open_ended_count=len(draft_answers) if draft_answers else 0,
        notification_settings=notification_settings,
    )

    # Schedule timeout job with APScheduler for human_review tier
    if tier == "human_review" and timeout_deadline is not None:
        from src.pipeline.escalation_scheduler import schedule_escalation_timeout

        schedule_escalation_timeout(record.id, timeout_deadline)

    return record


async def _send_escalation_notification(
    session: AsyncSession,
    *,
    record: EscalationRecord,
    job_record: JobRecord,
    tier: Literal["captcha", "human_review"],
    freshness: FreshnessTier | None,
    timeout_deadline: datetime | None,
    open_ended_count: int,
    notification_settings: NotificationSettings,
) -> None:
    """Send the escalation notification via ntfy with SMS fallback.

    Composes the escalation notification payload and publishes it via ntfy.
    If ntfy fails after its built-in 3 retries, falls back to SMS using the
    existing SMS gateway. Logs all delivery failures.

    Notification failure does NOT prevent escalation creation — this function
    catches all exceptions and logs them rather than propagating.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        record: The persisted escalation record.
        job_record: The job record being escalated.
        tier: Escalation type — "captcha" or "human_review".
        freshness: The freshness tier; None for CAPTCHA tier.
        timeout_deadline: The auto-submit deadline; None for CAPTCHA tier.
        open_ended_count: Number of open-ended questions detected.
        notification_settings: Notification channel configuration.

    Validates: Requirements 5.5
    """
    from src.pipeline.notification_composer import compose_escalation_notification

    # Construct the review URL using lan_base_url if available, else localhost
    base_url = "http://localhost:3000"
    if (
        notification_settings.ntfy_enabled
        and notification_settings.ntfy is not None
        and notification_settings.ntfy.lan_base_url
    ):
        base_url = notification_settings.ntfy.lan_base_url

    review_url = f"{base_url}/escalations/{record.id}"

    # Check if ntfy is enabled and configured
    if not notification_settings.ntfy_enabled or notification_settings.ntfy is None:
        logger.warning(
            "escalation_notification_skipped",
            escalation_id=record.id,
            reason="ntfy_not_configured",
        )
        return

    try:
        # Compose the notification payload
        payload = compose_escalation_notification(
            job_record=job_record,
            tier=tier,
            freshness=freshness,
            timeout_deadline=timeout_deadline,
            open_ended_count=open_ended_count,
            review_url=review_url,
        )

        # Set the topic from settings (composer leaves it empty)
        payload.topic = notification_settings.ntfy.urgent_topic

        # Publish via ntfy (has built-in 3 retries with backoff)
        result: NtfyResult = await publish(payload, notification_settings.ntfy)

        if result.ok:
            logger.info(
                "escalation_notification_sent",
                escalation_id=record.id,
                job_id=job_record.id,
                tier=tier,
                channel="ntfy",
            )
            return

        # ntfy failed after 3 retries — log the failure and attempt SMS fallback
        logger.error(
            "escalation_notification_ntfy_failed",
            escalation_id=record.id,
            job_id=job_record.id,
            tier=tier,
            error=result.error,
            status_code=result.status_code,
        )

        # Fall back to SMS if configured
        if notification_settings.sms_enabled and notification_settings.sms is not None:
            logger.info(
                "escalation_notification_falling_back_to_sms",
                escalation_id=record.id,
                job_id=job_record.id,
                tier=tier,
            )

            sms_body = compose_sms(
                job_title=job_record.job_title,
                company=job_record.company,
                trigger_reason=f"escalation_{tier}",
                fit_score=job_record.fit_score,
            )

            sms_result = await send_sms(sms_body, notification_settings.sms)

            if sms_result.ok:
                logger.info(
                    "escalation_notification_sent",
                    escalation_id=record.id,
                    job_id=job_record.id,
                    tier=tier,
                    channel="sms_fallback",
                )
            else:
                logger.error(
                    "escalation_notification_sms_fallback_failed",
                    escalation_id=record.id,
                    job_id=job_record.id,
                    tier=tier,
                    error=sms_result.error,
                )
        else:
            logger.warning(
                "escalation_notification_no_sms_fallback",
                escalation_id=record.id,
                job_id=job_record.id,
                tier=tier,
                reason="sms_not_configured",
            )

    except Exception as exc:
        # Notification failure must not prevent escalation creation
        logger.error(
            "escalation_notification_unexpected_error",
            escalation_id=record.id,
            job_id=job_record.id,
            tier=tier,
            error=str(exc),
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Timeout Handling
# ---------------------------------------------------------------------------


async def handle_timeout(
    session: AsyncSession,
    escalation_id: str,
) -> None:
    """Auto-submit when timeout expires.

    Looks up the escalation by ID. If not found or already resolved,
    performs a no-op with appropriate logging. Otherwise, transitions the
    escalation to ``auto_submitted`` status and logs the auto-submission
    with timeout duration and freshness tier.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        escalation_id: UUID string identifying the escalation record.

    Returns:
        None

    Validates: Requirements 4.4, 4.6
    """
    # --- Look up escalation by ID ---
    stmt = select(EscalationRecord).where(EscalationRecord.id == escalation_id)
    result = await session.execute(stmt)
    record = result.scalars().first()

    if record is None:
        logger.warning(
            "handle_timeout_escalation_not_found",
            escalation_id=escalation_id,
        )
        return

    # --- No-op if already resolved (not pending) ---
    if record.status != "pending":
        logger.info(
            "handle_timeout_already_resolved",
            escalation_id=escalation_id,
            current_status=record.status,
        )
        return

    # --- Transition to auto_submitted ---
    now = datetime.now(tz=UTC)
    record.status = "auto_submitted"
    record.resolution_method = "auto_submit"
    record.resolved_at = now.isoformat()

    # --- Compute timeout duration for logging ---
    created = datetime.fromisoformat(record.created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    timeout_duration = now - created

    logger.info(
        "escalation_auto_submitted",
        escalation_id=escalation_id,
        freshness_tier=record.freshness_tier,
        timeout_duration_seconds=timeout_duration.total_seconds(),
        timeout_duration_minutes=timeout_duration.total_seconds() / 60,
        draft_answers_present=record.draft_answers is not None,
    )

    # --- Flush changes to DB ---
    await session.flush()

    # Resume mechanism is triggered by the Vision Agent when it detects
    # the auto_submitted status and has a browser page available.
    # See: src.pipeline.escalation_resume.resume_from_escalation


# ---------------------------------------------------------------------------
# CAPTCHA Expiry Handling
# ---------------------------------------------------------------------------

CAPTCHA_EXPIRY_HOURS = 24
"""CAPTCHA escalations older than this are considered expired."""


async def expire_stale_captcha_escalations(session: AsyncSession) -> list[EscalationRecord]:
    """Expire CAPTCHA escalations that have been pending for more than 24 hours.

    Queries all escalation records where tier="captcha", status="pending", and
    the age (current_time - created_at) exceeds 24 hours. For each expired
    record:
    - Sets status="expired"
    - Sets resolution_method="timeout_expired"
    - Sets resolved_at to the current UTC time
    - Transitions the associated job to status="apply_failed" with
      queue_reason="captcha_timeout"
    - Logs the expiration

    Args:
        session: Active SQLAlchemy async session for DB operations.

    Returns:
        List of EscalationRecord instances that were expired.

    Validates: Requirements 1.5
    """
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=CAPTCHA_EXPIRY_HOURS)

    # Query all pending CAPTCHA escalations
    stmt = select(EscalationRecord).where(
        EscalationRecord.tier == "captcha",
        EscalationRecord.status == "pending",
    )
    result = await session.execute(stmt)
    pending_captchas = list(result.scalars().all())

    expired_records: list[EscalationRecord] = []

    for record in pending_captchas:
        # Parse created_at and check if older than 24 hours
        created = datetime.fromisoformat(record.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)

        if created > cutoff:
            # Not yet expired
            continue

        # Mark as expired
        record.status = "expired"
        record.resolution_method = "timeout_expired"
        record.resolved_at = now.isoformat()

        # Transition the associated job to apply_failed
        await update_job_status(
            session,
            record.job_id,
            "apply_failed",
            reason="captcha_timeout",
        )

        age_hours = (now - created).total_seconds() / 3600
        logger.info(
            "captcha_escalation_expired",
            escalation_id=record.id,
            job_id=record.job_id,
            created_at=record.created_at,
            age_hours=round(age_hours, 1),
        )

        expired_records.append(record)

    if expired_records:
        await session.flush()
        logger.info(
            "captcha_expiry_sweep_complete",
            expired_count=len(expired_records),
        )
    else:
        logger.debug("captcha_expiry_sweep_complete", expired_count=0)

    return expired_records


async def check_captcha_expiry_on_startup(session: AsyncSession) -> list[EscalationRecord]:
    """Check for and expire stale CAPTCHA escalations on application startup.

    This function should be called during app startup to handle any CAPTCHA
    escalations that expired while the container was down. It delegates to
    ``expire_stale_captcha_escalations`` which handles the actual expiry logic.

    Args:
        session: Active SQLAlchemy async session for DB operations.

    Returns:
        List of EscalationRecord instances that were expired during startup.

    Validates: Requirements 1.5
    """
    logger.info("checking_captcha_expiry_on_startup")
    expired = await expire_stale_captcha_escalations(session)

    if expired:
        logger.info(
            "startup_captcha_expiry_handled",
            expired_count=len(expired),
            escalation_ids=[r.id for r in expired],
        )
    else:
        logger.info("startup_captcha_expiry_none_found")

    return expired


# ---------------------------------------------------------------------------
# CAPTCHA Polling
# ---------------------------------------------------------------------------

CAPTCHA_POLL_INTERVAL_SECONDS: int = 5
"""Interval between CAPTCHA resolution checks (seconds)."""

CAPTCHA_POLL_MAX_DURATION_SECONDS: int = 30 * 60  # 30 minutes
"""Maximum duration to actively poll for CAPTCHA resolution."""

_CAPTCHA_INDICATORS: list[str] = [
    "recaptcha",
    "hcaptcha",
    "captcha",
    "i'm not a robot",
    "verify you are human",
]
"""Text indicators that suggest a CAPTCHA is present on the page."""


async def _page_has_captcha(page: Page) -> bool:
    """Check if the page currently contains CAPTCHA indicators.

    Extracts the page body text and checks for known CAPTCHA provider
    keywords (reCAPTCHA, hCaptcha, Cloudflare Turnstile, generic CAPTCHA
    challenge text).

    Args:
        page: Playwright Page instance to inspect.

    Returns:
        True if CAPTCHA indicators are found on the page, False otherwise.
    """
    try:
        page_text = await page.inner_text("body")
    except Exception:
        # If we can't read the page, assume CAPTCHA is still present
        # (the page may be navigating or in an error state)
        return True

    lower = page_text.lower()
    return any(indicator in lower for indicator in _CAPTCHA_INDICATORS)


async def poll_captcha_resolution(
    page: Page,
    escalation_id: str,
    session: AsyncSession,
) -> bool:
    """Poll the page for CAPTCHA resolution, updating the escalation on success.

    Checks the page every 5 seconds for up to 30 minutes to determine if the
    user has solved the CAPTCHA in the connected Chrome session. On resolution:
    - Updates the escalation status to "resolved" with resolution_method="captcha_solved"
    - Records the solved domain in the session-level ``_solved_captcha_domains`` set
    - Returns True indicating automation can resume

    If 30 minutes pass without resolution, stops polling and returns False.
    The 24-hour expiry timer continues separately (handled by Task 6.2).

    Page navigation errors are handled gracefully — a warning is logged and
    polling continues, since the page may recover.

    Args:
        page: Playwright Page instance connected to the Chrome session
            where the CAPTCHA is displayed.
        escalation_id: UUID of the pending CAPTCHA escalation record.
        session: Active SQLAlchemy async session for DB operations.

    Returns:
        True if the CAPTCHA was resolved within the polling window.
        False if the 30-minute polling window expired without resolution.

    Validates: Requirements 1.4, 1.6
    """
    elapsed_seconds = 0

    logger.info(
        "captcha_poll_started",
        escalation_id=escalation_id,
        max_duration_seconds=CAPTCHA_POLL_MAX_DURATION_SECONDS,
        poll_interval_seconds=CAPTCHA_POLL_INTERVAL_SECONDS,
    )

    while elapsed_seconds < CAPTCHA_POLL_MAX_DURATION_SECONDS:
        await asyncio.sleep(CAPTCHA_POLL_INTERVAL_SECONDS)
        elapsed_seconds += CAPTCHA_POLL_INTERVAL_SECONDS

        try:
            captcha_present = await _page_has_captcha(page)
        except Exception as exc:
            # Handle page navigation errors gracefully — log and continue
            logger.warning(
                "captcha_poll_page_error",
                escalation_id=escalation_id,
                elapsed_seconds=elapsed_seconds,
                error=str(exc),
            )
            continue

        if not captcha_present:
            # CAPTCHA resolved — update escalation record
            logger.info(
                "captcha_resolved_detected",
                escalation_id=escalation_id,
                elapsed_seconds=elapsed_seconds,
            )

            # Update escalation status in DB
            stmt = select(EscalationRecord).where(
                EscalationRecord.id == escalation_id
            )
            result = await session.execute(stmt)
            record = result.scalars().first()

            if record is not None and record.status == "pending":
                now = datetime.now(tz=UTC)
                record.status = "resolved"
                record.resolution_method = "captcha_solved"
                record.resolved_at = now.isoformat()
                await session.flush()

                logger.info(
                    "captcha_escalation_resolved",
                    escalation_id=escalation_id,
                    resolution_method="captcha_solved",
                    elapsed_seconds=elapsed_seconds,
                )

            # Record solved domain for deduplication
            try:
                current_url = page.url
                domain = urlparse(current_url).netloc
                if domain:
                    _solved_captcha_domains.add(domain)
                    logger.info(
                        "captcha_domain_recorded",
                        domain=domain,
                        escalation_id=escalation_id,
                    )
            except Exception as exc:
                logger.warning(
                    "captcha_domain_record_failed",
                    escalation_id=escalation_id,
                    error=str(exc),
                )

            return True

    # 30-minute polling window expired without resolution
    logger.info(
        "captcha_poll_timeout",
        escalation_id=escalation_id,
        elapsed_seconds=elapsed_seconds,
    )
    return False


# ---------------------------------------------------------------------------
# Escalation Resolution
# ---------------------------------------------------------------------------


async def resolve_escalation(
    session: AsyncSession,
    escalation_id: str,
    resolution: Literal["resolved", "skipped"],
    edited_answers: list[dict] | None = None,
) -> EscalationRecord:
    """Resolve a pending escalation with user action.

    Looks up the escalation by ID, validates it is still pending, then applies
    the requested resolution. For "resolved", stores the user's edited answers
    and marks the record as submitted. For "skipped", marks the escalation as
    skipped and transitions the associated job to "skipped" status.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        escalation_id: UUID of the escalation record to resolve.
        resolution: The user's action — "resolved" (submit with edits) or
            "skipped" (cancel the application).
        edited_answers: List of edited answer dicts for "resolved" resolution;
            ignored for "skipped".

    Returns:
        The updated EscalationRecord with terminal status.

    Raises:
        ValueError: If no escalation exists with the given ID (context: "not_found").
        ValueError: If the escalation is not in "pending" status (context: "already_resolved").

    Validates: Requirements 6.3, 6.4, 7.2, 8.2
    """
    # --- Look up escalation by ID ---
    stmt = select(EscalationRecord).where(EscalationRecord.id == escalation_id)
    result = await session.execute(stmt)
    record = result.scalars().first()

    if record is None:
        raise ValueError(f"Escalation not found: {escalation_id}")

    if record.status != "pending":
        raise ValueError(
            f"Escalation already resolved: {escalation_id} "
            f"(current status: {record.status})"
        )

    now = datetime.now(tz=UTC).isoformat()

    # Cancel any pending timeout job before resolving
    from src.pipeline.escalation_scheduler import cancel_escalation_timeout

    cancel_escalation_timeout(escalation_id)

    if resolution == "resolved":
        record.status = "resolved"
        record.resolution_method = "user_submit"
        record.resolved_at = now

        # Store edited answers as JSON in the draft_answers field
        if edited_answers is not None:
            record.draft_answers = json.dumps(edited_answers)

        logger.info(
            "escalation_resolved_submit",
            escalation_id=escalation_id,
            job_id=record.job_id,
            edited_answers_count=len(edited_answers) if edited_answers else 0,
        )

    elif resolution == "skipped":
        record.status = "skipped"
        record.resolution_method = "user_skip"
        record.resolved_at = now

        # Transition the associated job to "skipped" status
        await update_job_status(
            session,
            record.job_id,
            "skipped",
            reason="user_skipped_escalation",
        )

        logger.info(
            "escalation_resolved_skip",
            escalation_id=escalation_id,
            job_id=record.job_id,
        )

    await session.flush()

    return record
