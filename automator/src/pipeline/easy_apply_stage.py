"""Pipeline stage: LinkedIn Easy Apply submission.

Navigates to the job's LinkedIn URL, initiates the Easy Apply flow, fills
standard fields from the user profile, attaches the tailored resume PDF,
generates a cover letter if required, handles unanswered questions by
escalating to the human queue, and submits the application.

Retries once on submission failure before marking the job as apply_failed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient
from src.api.schemas import UserProfile
from src.db.job_repo import update_job_status
from src.db.models import JobRecord
from src.exceptions import ApplyError
from src.pipeline.notification_service import NotificationSettings, notify

logger = structlog.get_logger(__name__)

# Playwright timeouts (milliseconds)
NAVIGATION_TIMEOUT_MS = 30_000
ELEMENT_TIMEOUT_MS = 10_000

# Standard Easy Apply field selectors (LinkedIn's form structure)
EASY_APPLY_BUTTON_SELECTOR = 'button.jobs-apply-button, button[aria-label*="Easy Apply"]'
SUBMIT_BUTTON_SELECTOR = 'button[aria-label="Submit application"]'
NEXT_BUTTON_SELECTOR = 'button[aria-label="Continue to next step"]'
REVIEW_BUTTON_SELECTOR = 'button[aria-label="Review your application"]'
DISMISS_BUTTON_SELECTOR = 'button[aria-label="Dismiss"]'

# Field label patterns for standard fields
FIELD_PATTERNS: dict[str, str] = {
    "first name": "full_name",
    "last name": "full_name",
    "full name": "full_name",
    "email": "email",
    "phone": "phone",
    "mobile phone": "phone",
    "city": "location",
    "location": "location",
    "work authorization": "work_auth",
    "authorized to work": "work_auth",
}


async def run_easy_apply(
    job_record: JobRecord,
    profile: UserProfile,
    session: AsyncSession,
    page: Page,
    claude_client: ClaudeClient,
    notification_settings: NotificationSettings | None = None,
    goals_profile: str | None = None,
) -> None:
    """Execute the Easy Apply flow for a single job record.

    Navigates to the job's LinkedIn URL, clicks Easy Apply, fills form fields
    from the user profile, attaches the tailored resume PDF, generates a cover
    letter if required, and submits the application.

    On unanswered questions: sets queue_reason, sends notification, and returns
    without submitting. On submission failure: retries once, then marks as
    apply_failed with notification.

    Args:
        job_record: The job record to apply to. Must have status "approved_for_apply"
            or "applying", apply_type "easy_apply", and a non-null tailored_resume_pdf.
        profile: User profile data for filling standard form fields.
        session: Active async database session for persisting state changes.
        page: A Playwright Page instance (already authenticated with LinkedIn).
        claude_client: Claude API client for cover letter generation.
        notification_settings: Unified notification settings. If None, notifications
            are skipped.
        goals_profile: Goals profile as JSON string for cover letter generation context.
    """
    job_id = job_record.id
    logger.info(
        "easy_apply_stage_started",
        job_id=job_id,
        job_title=job_record.job_title,
        company=job_record.company,
    )

    # Transition to "applying" status
    await update_job_status(session, job_id, "applying", reason="Starting Easy Apply")

    try:
        await _execute_easy_apply(
            job_record=job_record,
            profile=profile,
            session=session,
            page=page,
            claude_client=claude_client,
            notification_settings=notification_settings,
            goals_profile=goals_profile,
        )
    except ApplyError as exc:
        # First failure — retry once
        logger.warning(
            "easy_apply_first_attempt_failed",
            job_id=job_id,
            error=exc.message,
        )
        try:
            await _execute_easy_apply(
                job_record=job_record,
                profile=profile,
                session=session,
                page=page,
                claude_client=claude_client,
                notification_settings=notification_settings,
                goals_profile=goals_profile,
            )
        except ApplyError as retry_exc:
            # Retry exhausted — mark as apply_failed
            logger.error(
                "easy_apply_retry_exhausted",
                job_id=job_id,
                error=retry_exc.message,
            )
            job_record.error_message = retry_exc.message
            job_record.queue_reason = "apply_failed"
            await update_job_status(
                session,
                job_id,
                "apply_failed",
                reason=f"Easy Apply failed after retry: {retry_exc.message}",
            )
            await _send_notification(
                session=session,
                job_record=job_record,
                trigger_reason=f"apply_failed: {retry_exc.message}",
                notification_settings=notification_settings,
            )
            return


async def _execute_easy_apply(
    job_record: JobRecord,
    profile: UserProfile,
    session: AsyncSession,
    page: Page,
    claude_client: ClaudeClient,
    notification_settings: NotificationSettings | None,
    goals_profile: str | None,
) -> None:
    """Internal implementation of the Easy Apply flow.

    Raises ApplyError on any failure that should trigger a retry or escalation.
    Returns normally if the job is queued for human review (unanswered question).

    Args:
        job_record: The job record being applied to.
        profile: User profile for form filling.
        session: Active async database session.
        page: Playwright Page instance.
        claude_client: Claude API client.
        notification_settings: Unified notification settings for alerts.
        goals_profile: Goals profile JSON string.

    Raises:
        ApplyError: If navigation, form interaction, or submission fails.
    """
    job_id = job_record.id

    # Step 1: Navigate to the job's LinkedIn URL
    try:
        await page.goto(job_record.linkedin_url, timeout=NAVIGATION_TIMEOUT_MS)
        await page.wait_for_load_state("domcontentloaded")
    except (PlaywrightTimeout, Exception) as exc:
        raise ApplyError(
            message=f"Failed to navigate to job page: {exc}",
            job_id=job_id,
        ) from exc

    # Step 2: Click the Easy Apply button
    try:
        easy_apply_btn = await page.wait_for_selector(
            EASY_APPLY_BUTTON_SELECTOR, timeout=ELEMENT_TIMEOUT_MS
        )
        if easy_apply_btn is None:
            raise ApplyError(
                message="Easy Apply button not found on page",
                job_id=job_id,
            )
        await easy_apply_btn.click()
        # Wait for the modal to appear
        await page.wait_for_selector(
            'div[role="dialog"], div.jobs-easy-apply-modal', timeout=ELEMENT_TIMEOUT_MS
        )
    except PlaywrightTimeout as exc:
        raise ApplyError(
            message=f"Easy Apply button not found or modal did not open: {exc}",
            job_id=job_id,
        ) from exc

    # Step 3: Process form pages (fill fields, handle file uploads, navigate)
    max_pages = 10  # Safety limit to prevent infinite loops
    for page_num in range(max_pages):
        logger.debug("easy_apply_processing_page", job_id=job_id, page_num=page_num + 1)

        # Fill standard text fields on the current page
        unanswered = await _fill_form_fields(page, profile, job_id)
        if unanswered:
            # Unanswered question found — escalate to human queue
            question_text = unanswered
            logger.info(
                "easy_apply_unanswered_question",
                job_id=job_id,
                question=question_text,
            )
            job_record.queue_reason = f"unanswered_question: {question_text}"
            await update_job_status(
                session,
                job_id,
                "apply_failed",
                reason=f"Unanswered question: {question_text}",
            )
            await _send_notification(
                session=session,
                job_record=job_record,
                trigger_reason=f"unanswered_question: {question_text[:80]}",
                notification_settings=notification_settings,
            )
            # Dismiss the modal
            await _dismiss_modal(page)
            return

        # Handle resume upload if a file input is present
        await _attach_resume(page, job_record)

        # Handle cover letter if required
        await _handle_cover_letter(
            page=page,
            job_record=job_record,
            session=session,
            claude_client=claude_client,
            goals_profile=goals_profile,
        )

        # Check for Submit button
        submit_btn = await page.query_selector(SUBMIT_BUTTON_SELECTOR)
        if submit_btn:
            # Submit the application
            await submit_btn.click()
            await _wait_for_submission_confirmation(page)

            # Success — update status
            job_record.applied_at = datetime.now(UTC).isoformat()
            await update_job_status(
                session, job_id, "applied", reason="Easy Apply submitted successfully"
            )
            logger.info(
                "easy_apply_submitted",
                job_id=job_id,
                job_title=job_record.job_title,
                company=job_record.company,
            )
            return

        # Check for Review button (final step before submit)
        review_btn = await page.query_selector(REVIEW_BUTTON_SELECTOR)
        if review_btn:
            await review_btn.click()
            await page.wait_for_timeout(1000)
            continue

        # Check for Next button (multi-step form)
        next_btn = await page.query_selector(NEXT_BUTTON_SELECTOR)
        if next_btn:
            await next_btn.click()
            await page.wait_for_timeout(1000)
            continue

        # No navigation button found — unexpected state
        raise ApplyError(
            message="No Submit, Review, or Next button found on form page",
            job_id=job_id,
        )

    # Exceeded max pages without finding submit
    raise ApplyError(
        message=f"Easy Apply form exceeded {max_pages} pages without submission",
        job_id=job_id,
    )


async def _fill_form_fields(
    page: Page,
    profile: UserProfile,
    job_id: str,
) -> str | None:
    """Fill standard form fields on the current Easy Apply page.

    Identifies input fields by their labels and fills them with values from
    the user profile. Returns the label of the first unanswered question
    (a field that cannot be mapped to a profile value), or None if all fields
    were filled.

    Args:
        page: Playwright Page with the Easy Apply modal open.
        profile: User profile data.
        job_id: Job ID for logging context.

    Returns:
        The label text of the first unanswered question, or None if all filled.
    """
    # Find all visible label+input pairs in the modal
    labels = await page.query_selector_all(
        'div[role="dialog"] label, div.jobs-easy-apply-modal label'
    )

    profile_values = _build_profile_map(profile)

    for label_el in labels:
        label_text = (await label_el.inner_text()).strip().lower()
        if not label_text:
            continue

        # Find the associated input
        label_for = await label_el.get_attribute("for")
        if label_for:
            input_el = await page.query_selector(f"#{label_for}")
        else:
            # Try sibling or child input
            input_el = await label_el.query_selector(
                "~ input, ~ select, ~ textarea, input, select, textarea"
            )

        if input_el is None:
            continue

        # Check if the field already has a value
        tag_name = await input_el.evaluate("el => el.tagName.toLowerCase()")
        current_value = ""
        if tag_name in ("input", "textarea"):
            current_value = await input_el.input_value() or ""
        elif tag_name == "select":
            current_value = await input_el.evaluate(
                "el => el.options[el.selectedIndex]?.text || ''"
            )

        if current_value.strip():
            # Field already filled (LinkedIn may pre-populate)
            continue

        # Try to map the label to a profile value
        value = _match_field_to_profile(label_text, profile_values)

        if value is None:
            # Check common_answers
            value = _match_common_answer(label_text, profile.common_answers)

        if value is None:
            # Unanswered question — cannot fill this field
            original_label = await label_el.inner_text()
            logger.debug(
                "easy_apply_unmapped_field",
                job_id=job_id,
                label=original_label.strip(),
            )
            return original_label.strip()

        # Fill the field with sanitized value
        sanitized = _sanitize_input(value)
        if tag_name in ("input", "textarea"):
            await input_el.fill(sanitized)
        elif tag_name == "select":
            # Try to select by visible text
            await input_el.select_option(label=sanitized)

        logger.debug(
            "easy_apply_field_filled",
            job_id=job_id,
            label=label_text,
        )

    return None


def _build_profile_map(profile: UserProfile) -> dict[str, str]:
    """Build a mapping of field keys to profile values.

    Args:
        profile: The user profile.

    Returns:
        Dict mapping field keys to non-null string values.
    """
    mapping: dict[str, str] = {}
    if profile.full_name:
        mapping["full_name"] = profile.full_name
    if profile.email:
        mapping["email"] = profile.email
    if profile.phone:
        mapping["phone"] = profile.phone
    if profile.location:
        mapping["location"] = profile.location
    if profile.work_auth:
        mapping["work_auth"] = profile.work_auth
    return mapping


def _match_field_to_profile(label_text: str, profile_values: dict[str, str]) -> str | None:
    """Match a form field label to a profile value using known patterns.

    Args:
        label_text: Lowercase label text from the form.
        profile_values: Mapping of profile keys to values.

    Returns:
        The matching profile value, or None if no match found.
    """
    for pattern, profile_key in FIELD_PATTERNS.items():
        if pattern in label_text:
            return profile_values.get(profile_key)
    return None


def _match_common_answer(label_text: str, common_answers: dict[str, str]) -> str | None:
    """Match a form field label against the user's pre-configured common answers.

    Performs case-insensitive substring matching against common_answers keys.

    Args:
        label_text: Lowercase label text from the form.
        common_answers: Dict of question patterns to answers.

    Returns:
        The matching answer, or None if no match found.
    """
    for question_key, answer in common_answers.items():
        if question_key.lower() in label_text or label_text in question_key.lower():
            return answer
    return None


def _sanitize_input(value: str) -> str:
    """Sanitize a value before typing it into a form field.

    Strips whitespace, limits length to 500 characters, and rejects values
    containing potential injection patterns.

    Args:
        value: The raw value to sanitize.

    Returns:
        The sanitized value, safe for form input.
    """
    sanitized = value.strip()[:500]
    # Reject dangerous patterns by replacing them with empty string
    dangerous_patterns = ["<script", "javascript:", "'; drop", '"; drop']
    for pattern in dangerous_patterns:
        if pattern.lower() in sanitized.lower():
            sanitized = ""
            break
    return sanitized


async def _attach_resume(page: Page, job_record: JobRecord) -> None:
    """Attach the tailored resume PDF if a file upload input is present.

    Looks for file input elements in the Easy Apply modal and uploads the
    tailored PDF from the job record's stored path.

    Args:
        page: Playwright Page with the Easy Apply modal open.
        job_record: Job record containing the tailored_resume_pdf path.
    """
    if not job_record.tailored_resume_pdf:
        logger.warning("easy_apply_no_resume_pdf", job_id=job_record.id)
        return

    file_inputs = await page.query_selector_all(
        'div[role="dialog"] input[type="file"], div.jobs-easy-apply-modal input[type="file"]'
    )

    for file_input in file_inputs:
        # Check if this is a resume upload (by nearby label text)
        parent = await file_input.evaluate("el => el.closest('.jobs-document-upload')")
        if parent is not None:
            # Check label for "resume" keyword
            label_el = await page.query_selector('div[role="dialog"] .jobs-document-upload label')
            if label_el:
                label_text = (await label_el.inner_text()).lower()
                if "resume" in label_text or "cv" in label_text:
                    await file_input.set_input_files(job_record.tailored_resume_pdf)
                    logger.debug(
                        "easy_apply_resume_attached",
                        job_id=job_record.id,
                        pdf_path=job_record.tailored_resume_pdf,
                    )
                    return

    # Fallback: if there's exactly one file input, use it for the resume
    if len(file_inputs) == 1:
        await file_inputs[0].set_input_files(job_record.tailored_resume_pdf)
        logger.debug(
            "easy_apply_resume_attached_fallback",
            job_id=job_record.id,
            pdf_path=job_record.tailored_resume_pdf,
        )


async def _handle_cover_letter(
    page: Page,
    job_record: JobRecord,
    session: AsyncSession,
    claude_client: ClaudeClient,
    goals_profile: str | None,
) -> None:
    """Generate and attach a cover letter if the form requires one.

    Detects cover letter fields by label text. If found, generates a cover
    letter via the Claude API and fills the textarea or uploads as a file.

    Args:
        page: Playwright Page with the Easy Apply modal open.
        job_record: Job record with description and tailored resume info.
        session: Active async database session.
        claude_client: Claude API client for generation.
        goals_profile: Goals profile JSON string for context.
    """
    # Look for cover letter textarea or upload
    cover_letter_labels = await page.query_selector_all(
        'div[role="dialog"] label, div.jobs-easy-apply-modal label'
    )

    cover_letter_field = None
    for label_el in cover_letter_labels:
        label_text = (await label_el.inner_text()).strip().lower()
        if "cover letter" in label_text:
            label_for = await label_el.get_attribute("for")
            if label_for:
                cover_letter_field = await page.query_selector(f"#{label_for}")
            else:
                cover_letter_field = await label_el.query_selector(
                    "~ textarea, ~ input[type='file'], textarea, input[type='file']"
                )
            break

    if cover_letter_field is None:
        return

    # Generate cover letter
    logger.info("easy_apply_generating_cover_letter", job_id=job_record.id)

    description = job_record.description_text or ""
    tailored_resume = job_record.resume_snapshot or ""
    goals = goals_profile or ""

    cover_letter_text = await claude_client.generate_cover_letter(
        description=description,
        tailored_resume=tailored_resume,
        goals=goals,
    )

    # Store the cover letter in the job record
    job_record.cover_letter_text = cover_letter_text

    # Determine field type and fill accordingly
    tag_name = await cover_letter_field.evaluate("el => el.tagName.toLowerCase()")
    input_type = await cover_letter_field.get_attribute("type") or ""

    if tag_name == "textarea" or (tag_name == "input" and input_type == "text"):
        sanitized = _sanitize_input(cover_letter_text)
        await cover_letter_field.fill(sanitized)
        logger.debug("easy_apply_cover_letter_filled_text", job_id=job_record.id)
    elif tag_name == "input" and input_type == "file":
        # Write cover letter to a temp file and upload
        import tempfile
        from pathlib import Path

        temp_path = Path(tempfile.gettempdir()) / f"cover_letter_{job_record.id}.txt"
        temp_path.write_text(cover_letter_text, encoding="utf-8")
        await cover_letter_field.set_input_files(str(temp_path))
        logger.debug("easy_apply_cover_letter_uploaded", job_id=job_record.id)


async def _wait_for_submission_confirmation(page: Page) -> None:
    """Wait for LinkedIn to confirm the application was submitted.

    Looks for success indicators in the page after clicking Submit.

    Args:
        page: Playwright Page after submission.

    Raises:
        ApplyError: If no confirmation is detected within the timeout.
    """
    try:
        # LinkedIn typically shows a success message or closes the modal
        await page.wait_for_selector(
            'div[role="dialog"] h2:has-text("submitted"), '
            'div[aria-label*="submitted"], '
            "div.artdeco-inline-feedback--success",
            timeout=ELEMENT_TIMEOUT_MS,
        )
    except PlaywrightTimeout:
        # Check if the modal closed (also indicates success)
        modal = await page.query_selector('div[role="dialog"].jobs-easy-apply-modal')
        if modal is None:
            # Modal closed — likely successful
            return
        raise ApplyError(
            message="No submission confirmation detected after clicking Submit",
            job_id=None,
        )


async def _dismiss_modal(page: Page) -> None:
    """Dismiss the Easy Apply modal without submitting.

    Args:
        page: Playwright Page with the modal open.
    """
    try:
        dismiss_btn = await page.query_selector(DISMISS_BUTTON_SELECTOR)
        if dismiss_btn:
            await dismiss_btn.click()
            # Confirm discard if prompted
            discard_btn = await page.wait_for_selector(
                'button[data-control-name="discard_application_confirm_btn"], '
                'button:has-text("Discard")',
                timeout=3000,
            )
            if discard_btn:
                await discard_btn.click()
    except (PlaywrightTimeout, Exception):
        # Best effort — if dismiss fails, continue anyway
        logger.debug("easy_apply_dismiss_modal_failed")


async def _send_notification(
    session: AsyncSession,
    job_record: JobRecord,
    trigger_reason: str,
    notification_settings: NotificationSettings | None,
) -> None:
    """Send a notification via the centralized notification service.

    Delegates to the refactored notify() function which handles channel routing
    (ntfy primary, SMS fallback), rate limiting, and logging.

    Args:
        session: Active async database session.
        job_record: The job record triggering the notification.
        trigger_reason: The reason for the notification.
        notification_settings: Unified notification settings. If None, notification
            is skipped.
    """
    if notification_settings is None:
        logger.warning(
            "notification_settings_not_configured",
            job_id=job_record.id,
            trigger_reason=trigger_reason,
        )
        return

    await notify(
        session=session,
        job_record=job_record,
        trigger_reason=trigger_reason,
        settings=notification_settings,
    )
