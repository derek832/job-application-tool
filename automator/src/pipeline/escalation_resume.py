"""Escalation Resume — resume automation after escalation resolution.

Handles the three resolution paths:
1. CAPTCHA solved (captcha_solved): continue form filling from current page state
2. Human review submitted (user_submit): navigate to stored URL, re-fill with
   edited answers, proceed to submission
3. Auto-submit timeout (auto_submit): same as human review but use original
   draft_answers

Detects form expiry (page load failure, structure mismatch) and marks the
escalation as "expired" with the job transitioning to "apply_failed".

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.job_repo import update_job_status
from src.db.models import EscalationRecord

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger(__name__)


class ResumeResult:
    """Outcome of a resume_from_escalation operation.

    Attributes:
        ok: Whether the resume and submission succeeded.
        error: Human-readable error description when ok is False.
        reason: Machine-readable failure reason when ok is False.
    """

    def __init__(
        self,
        ok: bool,
        error: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.ok = ok
        self.error = error
        self.reason = reason


async def resume_from_escalation(
    session: AsyncSession,
    escalation_record: EscalationRecord,
    page: Page,
) -> ResumeResult:
    """Resume automation after an escalation has been resolved.

    Dispatches to the appropriate resume handler based on the escalation's
    resolution_method:
    - "captcha_solved": continue form filling from the current page state
    - "user_submit": navigate to stored URL, re-fill with edited answers, submit
    - "auto_submit": navigate to stored URL, re-fill with original drafts, submit

    On any error (navigation failure, form structure mismatch, submission error),
    marks the escalation as "expired" and the job as "apply_failed".

    Args:
        session: Active SQLAlchemy async session for DB operations.
        escalation_record: The resolved escalation record with resolution details.
        page: Playwright Page instance for browser interaction.

    Returns:
        ResumeResult indicating success or failure with error details.

    Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
    """
    log = logger.bind(
        escalation_id=escalation_record.id,
        job_id=escalation_record.job_id,
        resolution_method=escalation_record.resolution_method,
    )

    resolution_method = escalation_record.resolution_method

    try:
        if resolution_method == "captcha_solved":
            log.info("resuming_after_captcha")
            return await _resume_from_captcha(page, log)

        elif resolution_method == "user_submit":
            log.info("resuming_after_human_review")
            return await _resume_with_answers(
                session=session,
                escalation_record=escalation_record,
                page=page,
                use_edited_answers=True,
                log=log,
            )

        elif resolution_method == "auto_submit":
            log.info("resuming_after_auto_submit")
            return await _resume_with_answers(
                session=session,
                escalation_record=escalation_record,
                page=page,
                use_edited_answers=False,
                log=log,
            )

        else:
            error_msg = f"Unknown resolution method: {resolution_method}"
            log.error("unknown_resolution_method", resolution_method=resolution_method)
            await _mark_expired(session, escalation_record, error_msg, log)
            return ResumeResult(ok=False, error=error_msg, reason="unknown_resolution")

    except Exception as exc:
        error_msg = f"Unexpected error during resume: {exc}"
        log.error("resume_unexpected_error", error=str(exc), exc_info=True)
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="resume_error")


async def _resume_from_captcha(
    page: Page,
    log: structlog.stdlib.BoundLogger,
) -> ResumeResult:
    """Continue form filling from the current page state after CAPTCHA resolution.

    After the user solves the CAPTCHA in the connected Chrome session, the page
    should be in a state where form filling can continue. This function
    re-identifies fields on the current page and resumes the fill sequence.

    Args:
        page: Playwright Page instance at the current form state.
        log: Bound logger for structured logging.

    Returns:
        ResumeResult indicating the page is ready for continued form filling.

    Validates: Requirement 8.1
    """
    try:
        # Verify the page is still accessible and has form content
        await page.wait_for_load_state("domcontentloaded", timeout=10000)

        # Check that the page has navigable content (not an error page)
        page_text = await page.inner_text("body")
        if not page_text or len(page_text.strip()) < 10:
            return ResumeResult(
                ok=False,
                error="Page appears empty after CAPTCHA resolution",
                reason="page_empty",
            )

        log.info(
            "captcha_resume_ready",
            page_url=page.url[:100],
            page_text_length=len(page_text),
        )

        return ResumeResult(ok=True)

    except Exception as exc:
        error_msg = f"Page not accessible after CAPTCHA resolution: {exc}"
        log.error("captcha_resume_page_error", error=str(exc))
        return ResumeResult(ok=False, error=error_msg, reason="page_not_accessible")


async def _resume_with_answers(
    session: AsyncSession,
    escalation_record: EscalationRecord,
    page: Page,
    use_edited_answers: bool,
    log: structlog.stdlib.BoundLogger,
) -> ResumeResult:
    """Navigate to the stored URL, re-fill fields, and submit the form.

    Used for both human_review (user_submit) and auto-submit resolutions.
    Parses the form_state_snapshot to get the external URL and field values,
    then navigates, fills, and submits.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        escalation_record: The resolved escalation record.
        page: Playwright Page instance for browser interaction.
        use_edited_answers: If True, use edited answers from draft_answers field.
            If False, use original draft_answers from the snapshot.
        log: Bound logger for structured logging.

    Returns:
        ResumeResult indicating success or failure.

    Validates: Requirements 8.2, 8.3, 8.4, 8.5
    """
    # --- Parse form state snapshot ---
    try:
        snapshot = json.loads(escalation_record.form_state_snapshot)
    except (json.JSONDecodeError, TypeError) as exc:
        error_msg = f"Failed to parse form_state_snapshot: {exc}"
        log.error("snapshot_parse_failed", error=str(exc))
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="snapshot_invalid")

    external_url = snapshot.get("external_url")
    if not external_url:
        error_msg = "No external_url in form_state_snapshot"
        log.error("no_external_url_in_snapshot")
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="no_external_url")

    snapshot_fields = snapshot.get("fields", [])

    # --- Parse draft answers ---
    draft_answers: list[dict] = []
    if escalation_record.draft_answers:
        try:
            draft_answers = json.loads(escalation_record.draft_answers)
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("draft_answers_parse_failed", error=str(exc))
            # Continue without draft answers — standard fields can still be filled

    # --- Build the answer map ---
    # For user_submit: use edited_answer from draft_answers (falling back to draft_answer)
    # For auto_submit: use draft_answer from draft_answers
    answer_map: dict[str, str] = {}
    for answer in draft_answers:
        field_id = answer.get("field_id", "")
        if use_edited_answers:
            # User submit: prefer edited_answer, fall back to draft_answer
            value = answer.get("edited_answer") or answer.get("draft_answer", "")
        else:
            # Auto submit: use original draft_answer
            value = answer.get("draft_answer", "")
        if field_id and value:
            answer_map[field_id] = value

    # --- Navigate to the external URL ---
    try:
        log.info("navigating_to_form", url=external_url[:100])
        response = await page.goto(external_url, wait_until="domcontentloaded", timeout=30000)

        if response is None or response.status >= 400:
            status_code = response.status if response else "no_response"
            error_msg = f"Form expired during escalation — page load failed (status: {status_code})"
            log.error(
                "navigation_failed_status",
                url=external_url[:100],
                status=status_code,
            )
            await _mark_expired(session, escalation_record, error_msg, log)
            return ResumeResult(ok=False, error=error_msg, reason="page_load_failed")

    except Exception as exc:
        error_msg = f"Form expired during escalation — navigation failed: {exc}"
        log.error("navigation_exception", url=external_url[:100], error=str(exc))
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="navigation_failed")

    # --- Verify form structure matches snapshot ---
    try:
        structure_ok = await _verify_form_structure(page, snapshot_fields, log)
        if not structure_ok:
            error_msg = "Form expired during escalation — form structure mismatch"
            log.error("form_structure_mismatch", url=external_url[:100])
            await _mark_expired(session, escalation_record, error_msg, log)
            return ResumeResult(ok=False, error=error_msg, reason="structure_mismatch")
    except Exception as exc:
        error_msg = f"Form expired during escalation — structure check failed: {exc}"
        log.error("structure_check_exception", error=str(exc))
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="structure_check_failed")

    # --- Re-fill all fields from snapshot + answers ---
    try:
        filled_count = await _fill_fields_from_snapshot(page, snapshot_fields, answer_map, log)
        log.info("fields_refilled", filled_count=filled_count, total_fields=len(snapshot_fields))
    except Exception as exc:
        error_msg = f"Form expired during escalation — field fill failed: {exc}"
        log.error("field_fill_exception", error=str(exc))
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="fill_failed")

    # --- Submit the form ---
    try:
        submitted = await _submit_form(page, log)
        if not submitted:
            error_msg = "Form submission failed — no submit button found"
            log.error("submit_button_not_found")
            await _mark_expired(session, escalation_record, error_msg, log)
            return ResumeResult(ok=False, error=error_msg, reason="no_submit_button")
    except Exception as exc:
        error_msg = f"Form submission failed: {exc}"
        log.error("submission_exception", error=str(exc))
        await _mark_expired(session, escalation_record, error_msg, log)
        return ResumeResult(ok=False, error=error_msg, reason="submission_failed")

    log.info("resume_submission_success")
    return ResumeResult(ok=True)


async def _verify_form_structure(
    page: Page,
    snapshot_fields: list[dict],
    log: structlog.stdlib.BoundLogger,
) -> bool:
    """Verify the current page form structure matches the snapshot.

    Checks that at least 50% of the expected fields from the snapshot are
    present on the current page. This accounts for minor DOM changes while
    detecting major structural changes (form expired, different page loaded).

    Args:
        page: Playwright Page instance.
        snapshot_fields: List of field dicts from the form_state_snapshot.
        log: Bound logger.

    Returns:
        True if the form structure is sufficiently similar to the snapshot.
    """
    if not snapshot_fields:
        # No fields in snapshot — can't verify, assume OK
        return True

    # Extract current page fields
    try:
        current_fields = await page.evaluate("""() => {
            const results = [];
            const inputs = document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), '
                + 'select, textarea'
            );
            for (const el of inputs) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;

                let label = '';
                if (el.id) {
                    const labelEl = document.querySelector('label[for="' + el.id + '"]');
                    if (labelEl) label = labelEl.textContent.trim();
                }
                if (!label) label = el.getAttribute('aria-label') || '';
                if (!label) label = el.getAttribute('placeholder') || '';

                let selector = '';
                if (el.id) {
                    selector = '#' + CSS.escape(el.id);
                } else if (el.name) {
                    selector = '[name="' + el.name + '"]';
                }
                results.push({
                    selector: selector,
                    label: label.replace(/[\\n\\r]+/g, ' ').replace(/\\s+/g, ' ').trim(),
                    type: el.type || el.tagName.toLowerCase(),
                });
            }
            return results;
        }""")
    except Exception as exc:
        log.warning("field_extraction_failed_during_verify", error=str(exc))
        return False

    if not current_fields:
        log.warning("no_fields_found_on_page")
        return False

    # Build sets of selectors for comparison
    snapshot_selectors = {f.get("selector", "") for f in snapshot_fields if f.get("selector")}
    current_selectors = {f.get("selector", "") for f in current_fields if f.get("selector")}

    if not snapshot_selectors:
        # No selectors in snapshot — fall back to label matching
        snapshot_labels = {
            f.get("label", "").lower().strip() for f in snapshot_fields if f.get("label")
        }
        current_labels = {
            f.get("label", "").lower().strip() for f in current_fields if f.get("label")
        }
        if not snapshot_labels:
            return True
        match_count = len(snapshot_labels & current_labels)
        match_ratio = match_count / len(snapshot_labels)
        log.debug(
            "structure_check_by_labels",
            match_ratio=f"{match_ratio:.0%}",
            matched=match_count,
            expected=len(snapshot_labels),
        )
        return match_ratio >= 0.5

    # Compare by selectors
    match_count = len(snapshot_selectors & current_selectors)
    match_ratio = match_count / len(snapshot_selectors)

    log.debug(
        "structure_check_by_selectors",
        match_ratio=f"{match_ratio:.0%}",
        matched=match_count,
        expected=len(snapshot_selectors),
    )

    return match_ratio >= 0.5


async def _fill_fields_from_snapshot(
    page: Page,
    snapshot_fields: list[dict],
    answer_map: dict[str, str],
    log: structlog.stdlib.BoundLogger,
) -> int:
    """Re-fill form fields using snapshot values and answer overrides.

    For each field in the snapshot:
    - If the field_id has an entry in answer_map, use that value (edited/draft answer)
    - Otherwise, use the value from the snapshot (standard auto-filled fields)
    - Skip fields with no value and no answer override

    Args:
        page: Playwright Page instance.
        snapshot_fields: List of field dicts from the form_state_snapshot.
        answer_map: Mapping of field_id → answer value for open-ended fields.
        log: Bound logger.

    Returns:
        Number of fields successfully filled.
    """
    filled_count = 0

    for field in snapshot_fields:
        field_id = field.get("field_id", "")
        selector = field.get("selector", "")
        field_type = field.get("type", "text")

        if not selector:
            continue

        # Determine the value to fill
        if field_id in answer_map:
            value = answer_map[field_id]
        else:
            value = field.get("value", "")

        if not value:
            continue

        try:
            if field_type == "select":
                await page.select_option(selector, label=value, timeout=5000)
            elif field_type == "file":
                # Skip file inputs — resume upload handled separately
                continue
            else:
                # Clear existing value and fill with new value
                await page.fill(selector, "", timeout=5000)
                await page.fill(selector, value, timeout=5000)

            filled_count += 1
            log.debug("field_refilled", field_id=field_id, selector=selector)

        except Exception as exc:
            # Try click-and-type fallback
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await el.evaluate("el => el.value = ''")
                    await page.keyboard.type(value)
                    filled_count += 1
                    log.debug("field_refilled_via_type", field_id=field_id)
                else:
                    log.debug(
                        "field_refill_skipped_not_found",
                        field_id=field_id,
                        selector=selector,
                    )
            except Exception:
                log.debug(
                    "field_refill_failed",
                    field_id=field_id,
                    selector=selector,
                    error=str(exc),
                )

    return filled_count


async def _submit_form(
    page: Page,
    log: structlog.stdlib.BoundLogger,
) -> bool:
    """Find and click the submit button on the form.

    Tries multiple common submit button selectors in order of specificity.
    Scrolls the button into view before clicking.

    Args:
        page: Playwright Page instance.
        log: Bound logger.

    Returns:
        True if a submit button was found and clicked, False otherwise.
    """
    import asyncio

    submit_selectors = [
        "button:has-text('Submit')",
        "button:has-text('Submit application')",
        "button:has-text('Apply')",
        "button:has-text('Send Application')",
        "button[type='submit']",
        "input[type='submit']",
    ]

    for sel in submit_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                is_visible = await btn.is_visible()
                if is_visible:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    log.info("clicking_submit_button", selector=sel)
                    await btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    return True
        except Exception as exc:
            log.debug("submit_selector_failed", selector=sel, error=str(exc))
            continue

    return False


async def _mark_expired(
    session: AsyncSession,
    escalation_record: EscalationRecord,
    error_message: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Mark an escalation as expired and transition the job to apply_failed.

    Sets the escalation status to "expired" with resolution_method="form_expired",
    and transitions the associated job to "apply_failed" with the error message
    as the reason.

    Args:
        session: Active SQLAlchemy async session for DB operations.
        escalation_record: The escalation record to mark as expired.
        error_message: Human-readable description of what went wrong.
        log: Bound logger.

    Validates: Requirements 8.3, 8.5
    """
    now = datetime.now(tz=UTC).isoformat()

    escalation_record.status = "expired"
    escalation_record.resolution_method = "form_expired"
    escalation_record.resolved_at = now

    log.info(
        "escalation_marked_expired",
        escalation_id=escalation_record.id,
        job_id=escalation_record.job_id,
        error_message=error_message,
    )

    try:
        await update_job_status(
            session,
            escalation_record.job_id,
            "apply_failed",
            reason=error_message,
        )
    except Exception as exc:
        log.error(
            "job_status_update_failed_during_expiry",
            job_id=escalation_record.job_id,
            error=str(exc),
        )

    await session.flush()
