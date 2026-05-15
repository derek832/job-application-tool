"""Vision Agent for external job application form filling.

Implements the full sequence: navigate → screenshot → identify fields →
map fields → fill fields → submit, with escalation for CAPTCHA,
unrecognized fields, salary missing, and multi-page forms (>3 pages).

All values are sanitized before being typed into form fields to prevent
injection via malicious job postings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from playwright.async_api import Page

from src.agents.claude_client import ClaudeClient, FormField
from src.api.schemas import UserProfile
from src.db.models import JobRecord

logger = structlog.get_logger()

MAX_FORM_PAGES = 3
MAX_FIELD_LENGTH = 500

# SQL injection patterns to reject (case-insensitive)
_SQL_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE),
    re.compile(r"\bSELECT\s+.+\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bUNION\s+SELECT\b", re.IGNORECASE),
    re.compile(r";\s*--", re.IGNORECASE),
    re.compile(r"\bOR\s+1\s*=\s*1\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class Result:
    """Outcome of a Vision Agent operation.

    Attributes:
        ok: Whether the operation succeeded.
        error: Human-readable error description when ok is False.
        reason: Machine-readable escalation reason when ok is False.
    """

    ok: bool
    error: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------


def sanitize_value(value: str) -> str | None:
    """Sanitize a value before filling it into a form field.

    Strips whitespace, limits to 500 characters, and rejects values containing
    script injection or SQL injection patterns.

    Args:
        value: The raw value to sanitize.

    Returns:
        The sanitized value, or None if the value is rejected as unsafe.
    """
    stripped = value.strip()
    truncated = stripped[:MAX_FIELD_LENGTH]

    lower = truncated.lower()
    if "<script" in lower or "javascript:" in lower:
        logger.warning("sanitize_rejected", reason="script_injection", value_preview=lower[:50])
        return None

    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(truncated):
            logger.warning(
                "sanitize_rejected",
                reason="sql_injection",
                pattern=pattern.pattern,
                value_preview=truncated[:50],
            )
            return None

    return truncated


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

# Maps common form field labels (lowercased) to UserProfile attribute names
_LABEL_TO_PROFILE_KEY: dict[str, str] = {
    "full name": "full_name",
    "name": "full_name",
    "first name": "full_name",
    "last name": "full_name",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "telephone": "phone",
    "mobile": "phone",
    "location": "location",
    "city": "location",
    "address": "location",
    "zip": "zip_code",
    "zip code": "zip_code",
    "postal code": "zip_code",
    "work authorization": "work_auth",
    "work auth": "work_auth",
    "authorized to work": "work_auth",
    "are you authorized": "work_auth",
    "legally authorized": "work_auth",
    "linkedin": "linkedin_url",
    "linkedin url": "linkedin_url",
    "linkedin profile": "linkedin_url",
    "website": "linkedin_url",
    "portfolio": "linkedin_url",
    "blog or portfolio": "linkedin_url",
    "personal website": "linkedin_url",
    "salary": "min_salary",
    "salary expectation": "min_salary",
    "expected salary": "min_salary",
    "desired salary": "min_salary",
    "desired pay": "min_salary",
    "minimum salary": "min_salary",
    "compensation": "min_salary",
    "date available": "date_available",
    "start date": "date_available",
    "available start date": "date_available",
    "earliest start date": "date_available",
    "when can you start": "date_available",
}

# Fields that are optional — if unmapped, skip them rather than escalating
_OPTIONAL_FIELD_LABELS: set[str] = {
    "cover letter",
    "blog or portfolio",
    "portfolio",
    "personal website",
    "website",
    "how did you hear about us",
    "how did you hear about this position",
    "referral",
    "referred by",
    "additional information",
    "anything else",
    "comments",
    "notes",
}


def map_fields_to_profile(
    fields: list[FormField],
    profile: UserProfile,
    min_salary: int | None,
) -> tuple[dict[str, str], list[FormField], list[FormField], bool]:
    """Map identified form fields to user profile values.

    Args:
        fields: List of form fields identified by Claude Vision.
        profile: The user's profile configuration.
        min_salary: The user's minimum salary from GoalsProfile, or None.

    Returns:
        A tuple of:
        - mapped: dict mapping field_id to the value to fill
        - unmapped: list of required fields that could not be mapped
        - file_fields: list of file upload fields (resume, cover letter)
        - salary_missing: True if a salary field was found but no min_salary configured
    """
    # Extract ZIP from location (e.g., "Norfolk, VA" → try common_answers first)
    zip_code = profile.common_answers.get("zip_code", profile.common_answers.get("zip"))

    profile_values: dict[str, str | None] = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "zip_code": zip_code,
        "work_auth": profile.work_auth,
        "linkedin_url": profile.linkedin_url,
        "min_salary": str(min_salary) if min_salary is not None else None,
        "date_available": profile.common_answers.get("date_available", "2 weeks"),
    }

    mapped: dict[str, str] = {}
    unmapped: list[FormField] = []
    file_fields: list[FormField] = []
    salary_missing = False

    for field in fields:
        # File upload fields get handled separately
        if field.field_type == "file":
            file_fields.append(field)
            continue

        # First try the suggested_value from Claude
        if field.suggested_value:
            mapped[field.field_id] = field.suggested_value
            continue

        # Try to match the label to a known profile key
        label_lower = field.label.lower().strip()

        # Check if this is an optional field we can skip
        if _is_optional_field(label_lower):
            logger.debug("optional_field_skipped", field_id=field.field_id, label=field.label)
            continue

        profile_key = _match_label_to_key(label_lower)

        # Also check common_answers for custom questions
        if profile_key is None:
            # Check if the label matches any common_answers key
            for answer_key, answer_value in profile.common_answers.items():
                if answer_key.lower() in label_lower or label_lower in answer_key.lower():
                    mapped[field.field_id] = answer_value
                    break
            else:
                unmapped.append(field)
            continue

        # Handle salary field specially
        if profile_key == "min_salary":
            if min_salary is None:
                salary_missing = True
                continue
            mapped[field.field_id] = str(min_salary)
            continue

        # Get the profile value
        value = profile_values.get(profile_key)
        if value is not None:
            mapped[field.field_id] = value
        else:
            # If we have a key but no value, check if it's optional
            if _is_optional_field(label_lower):
                continue
            unmapped.append(field)

    return mapped, unmapped, file_fields, salary_missing


def _match_label_to_key(label_lower: str) -> str | None:
    """Match a field label to a profile key using the mapping table.

    Tries exact match first, then substring matching for longer labels.

    Args:
        label_lower: Lowercased field label.

    Returns:
        The profile key if matched, or None.
    """
    # Exact match
    if label_lower in _LABEL_TO_PROFILE_KEY:
        return _LABEL_TO_PROFILE_KEY[label_lower]

    # Substring match — check if any known label is contained in the field label
    for known_label, key in _LABEL_TO_PROFILE_KEY.items():
        if known_label in label_lower:
            return key

    return None


def _is_optional_field(label_lower: str) -> bool:
    """Check if a field label indicates an optional field that can be skipped."""
    for optional in _OPTIONAL_FIELD_LABELS:
        if optional in label_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Vision Agent core
# ---------------------------------------------------------------------------


async def process_external_apply(
    job_record: JobRecord,
    profile: UserProfile,
    page: Page,
    claude_client: ClaudeClient,
    min_salary: int | None = None,
) -> Result:
    """Process an external job application using visual form parsing.

    Implements the full sequence: navigate → screenshot → identify fields →
    map fields → fill fields → submit, with escalation for CAPTCHA,
    unrecognized fields, salary missing, and >3 pages.

    Args:
        job_record: The job record with external_url to apply to.
        profile: The user's profile configuration for form filling.
        page: A Playwright Page instance for browser interaction.
        claude_client: The Claude API client for vision-based field identification.
        min_salary: The user's minimum salary from GoalsProfile, or None.

    Returns:
        Result indicating success or failure with escalation reason.
    """
    log = logger.bind(job_id=job_record.id, company=job_record.company)

    if not job_record.external_url:
        log.error("no_external_url")
        return Result(ok=False, error="No external URL for job", reason="no_external_url")

    # Navigate to the external application URL
    try:
        log.info("navigating_to_external_url", url=job_record.external_url)
        await page.goto(job_record.external_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        log.error("navigation_failed", error=str(exc))
        return Result(ok=False, error=f"Navigation failed: {exc}", reason="navigation_failed")

    # Many ATS sites show a job description page first with an "Apply" button.
    # Try to click through to the actual application form.
    await _click_through_to_form(page, log)

    profile_json = profile.model_dump_json()
    page_count = 0

    while True:
        page_count += 1

        # Escalate if more than 3 pages
        if page_count > MAX_FORM_PAGES:
            log.warning("too_many_pages", page_count=page_count)
            return Result(
                ok=False,
                error=f"External form has {page_count} pages (max {MAX_FORM_PAGES})",
                reason="too_many_pages",
            )

        # Take screenshot
        log.debug("taking_screenshot", page_number=page_count)
        try:
            screenshot_bytes = await page.screenshot(full_page=True)
        except Exception as exc:
            log.error("screenshot_failed", error=str(exc))
            return Result(ok=False, error=f"Screenshot failed: {exc}", reason="screenshot_failed")

        # Identify form fields via Claude Vision
        log.debug("identifying_fields", page_number=page_count)
        try:
            fields = await claude_client.identify_form_fields(screenshot_bytes, profile_json)
        except Exception as exc:
            log.error("field_identification_failed", error=str(exc))
            return Result(
                ok=False,
                error=f"Field identification failed: {exc}",
                reason="field_identification_failed",
            )

        # Check for CAPTCHA
        for field in fields:
            if _is_captcha_field(field):
                log.warning("captcha_detected", page_number=page_count)
                return Result(
                    ok=False,
                    error="CAPTCHA detected on application form",
                    reason="captcha_detected",
                )

        # Map fields to profile values
        mapped, unmapped, file_fields, salary_missing = map_fields_to_profile(
            fields, profile, min_salary
        )

        # Escalate for salary missing
        if salary_missing:
            log.warning("salary_missing")
            return Result(
                ok=False,
                error="Salary field detected but no min_salary configured",
                reason="salary_missing",
            )

        # Escalate for unrecognized required fields (more than 2 unmapped = likely a problem)
        if len(unmapped) > 2:
            unmapped_labels = [f.label for f in unmapped]
            log.warning("too_many_unrecognized_fields", fields=unmapped_labels)
            return Result(
                ok=False,
                error=f"Too many unrecognized fields: {', '.join(unmapped_labels)}",
                reason="unrecognized_field",
            )
        elif unmapped:
            # 1-2 unmapped fields — log but continue (they might be optional)
            unmapped_labels = [f.label for f in unmapped]
            log.info("skipping_unmapped_fields", fields=unmapped_labels)

        # Handle file upload fields (resume PDF)
        for file_field in file_fields:
            label_lower = file_field.label.lower()
            if "resume" in label_lower or "cv" in label_lower:
                if job_record.tailored_resume_pdf:
                    try:
                        selector = f"input[type='file'][id='{file_field.field_id}'], "
                        selector += f"input[type='file'][name='{file_field.field_id}']"
                        file_input = await page.query_selector(selector)
                        if file_input is None:
                            # Try broader file input selector
                            file_input = await page.query_selector("input[type='file']")
                        if file_input:
                            await file_input.set_input_files(job_record.tailored_resume_pdf)
                            log.info("resume_uploaded", path=job_record.tailored_resume_pdf)
                    except Exception as exc:
                        log.warning("resume_upload_failed", error=str(exc))
                else:
                    log.warning("no_tailored_pdf_for_upload")
            # Cover letter and other file fields are optional — skip

        # Fill all mapped text fields
        for field_id, value in mapped.items():
            sanitized = sanitize_value(value)
            if sanitized is None:
                log.warning("unsafe_value_skipped", field_id=field_id)
                return Result(
                    ok=False,
                    error=f"Unsafe value detected for field {field_id}",
                    reason="unsafe_value",
                )

            # Find the corresponding field object to get the label
            field_label = field_id
            for f in fields:
                if f.field_id == field_id:
                    field_label = f.label
                    break

            try:
                # Try multiple strategies to locate the field:
                # 1. By label text (most reliable for ATS forms)
                filled = await _fill_by_label(page, field_label, sanitized)
                if not filled:
                    # 2. By id/name attribute
                    filled = await _fill_by_selector(page, field_id, sanitized)
                if not filled:
                    log.warning("field_not_found", field_id=field_id, label=field_label)
                    # Don't fail — skip unfillable fields
                    continue
                log.debug("field_filled", field_id=field_id, label=field_label)
            except Exception as exc:
                log.warning("fill_failed", field_id=field_id, label=field_label, error=str(exc))
                # Don't fail on individual field errors — continue with others
                continue

        # Check if there's a "Next" button (multi-page form)
        next_button = await page.query_selector(
            "button:has-text('Next'), button:has-text('Continue'), "
            "input[type='submit'][value*='Next'], input[type='submit'][value*='Continue']"
        )

        if next_button:
            log.info("advancing_to_next_page", current_page=page_count)
            await next_button.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            continue

        # No next button — submit the form
        break

    # Submit the form
    try:
        submit_button = await page.query_selector(
            "button[type='submit'], button:has-text('Submit'), button:has-text('Apply'), "
            "input[type='submit']"
        )
        if submit_button:
            log.info("submitting_form")
            await submit_button.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        else:
            log.error("no_submit_button")
            return Result(
                ok=False,
                error="Could not find submit button",
                reason="no_submit_button",
            )
    except Exception as exc:
        log.error("submission_failed", error=str(exc))
        return Result(ok=False, error=f"Form submission failed: {exc}", reason="submission_failed")

    log.info("external_apply_success")
    return Result(ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fill_by_label(page: Page, label: str, value: str) -> bool:
    """Try to fill a form field by finding it via its label text.

    Uses Playwright's label-based locator which handles both <label for="...">
    and labels wrapping inputs.

    Args:
        page: The Playwright page.
        label: The visible label text for the field.
        value: The value to fill.

    Returns:
        True if the field was found and filled.
    """
    try:
        locator = page.get_by_label(label, exact=False)
        if await locator.count() > 0:
            await locator.first.fill(value, timeout=5000)
            return True
    except Exception:
        pass

    # Fallback: try placeholder text
    try:
        locator = page.get_by_placeholder(label, exact=False)
        if await locator.count() > 0:
            await locator.first.fill(value, timeout=5000)
            return True
    except Exception:
        pass

    return False


async def _fill_by_selector(page: Page, field_id: str, value: str) -> bool:
    """Try to fill a form field by id or name attribute.

    Args:
        page: The Playwright page.
        field_id: The id or name to search for.
        value: The value to fill.

    Returns:
        True if the field was found and filled.
    """
    selectors = [
        f"[id='{field_id}']",
        f"[name='{field_id}']",
        f"[id*='{field_id}']",
        f"[name*='{field_id}']",
    ]
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                await el.fill(value)
                return True
        except Exception:
            continue
    return False


def _is_captcha_field(field: FormField) -> bool:
    """Detect if a form field represents a CAPTCHA challenge.

    Args:
        field: A form field identified by Claude Vision.

    Returns:
        True if the field appears to be a CAPTCHA.
    """
    captcha_indicators = ["captcha", "recaptcha", "hcaptcha", "i'm not a robot", "verify human"]
    label_lower = field.label.lower()
    field_id_lower = field.field_id.lower()

    return any(
        indicator in label_lower or indicator in field_id_lower for indicator in captcha_indicators
    )


async def _click_through_to_form(page: Page, log) -> None:
    """Attempt to click an 'Apply' button on a job landing page.

    Many ATS sites (BambooHR, Greenhouse, Lever, Workday) show the job
    description first with an "Apply" or "Apply for this Job" button that
    leads to the actual form. This function detects and clicks that button.

    If no apply button is found, assumes we're already on the form.

    Args:
        page: The Playwright page after navigating to the external URL.
        log: Bound structlog logger.
    """
    import asyncio

    await asyncio.sleep(2)  # Let the page render

    apply_selectors = [
        "a:has-text('Apply for this Job')",
        "a:has-text('Apply Now')",
        "a:has-text('Apply for this Position')",
        "button:has-text('Apply for this Job')",
        "button:has-text('Apply Now')",
        "button:has-text('Apply for this Position')",
        "a:has-text('Apply')",
        "button:has-text('Apply')",
        "a[class*='apply'], a[id*='apply']",
        "button[class*='apply'], button[id*='apply']",
    ]

    for selector in apply_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn:
                is_visible = await btn.is_visible()
                if is_visible:
                    log.info("clicking_apply_button", selector=selector)
                    await btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)  # Let the form render
                    return
        except Exception:
            continue

    log.debug("no_apply_landing_page_detected")
