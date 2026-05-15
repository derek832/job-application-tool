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
    "work authorization": "work_auth",
    "work auth": "work_auth",
    "authorized to work": "work_auth",
    "linkedin": "linkedin_url",
    "linkedin url": "linkedin_url",
    "linkedin profile": "linkedin_url",
    "salary": "min_salary",
    "salary expectation": "min_salary",
    "expected salary": "min_salary",
    "desired salary": "min_salary",
    "minimum salary": "min_salary",
}


def map_fields_to_profile(
    fields: list[FormField],
    profile: UserProfile,
    min_salary: int | None,
) -> tuple[dict[str, str], list[FormField], bool]:
    """Map identified form fields to user profile values.

    Args:
        fields: List of form fields identified by Claude Vision.
        profile: The user's profile configuration.
        min_salary: The user's minimum salary from GoalsProfile, or None.

    Returns:
        A tuple of:
        - mapped: dict mapping field_id to the value to fill
        - unmapped: list of fields that could not be mapped
        - salary_missing: True if a salary field was found but no min_salary configured
    """
    profile_values: dict[str, str | None] = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "work_auth": profile.work_auth,
        "linkedin_url": profile.linkedin_url,
        "min_salary": str(min_salary) if min_salary is not None else None,
    }

    mapped: dict[str, str] = {}
    unmapped: list[FormField] = []
    salary_missing = False

    for field in fields:
        # First try the suggested_value from Claude
        if field.suggested_value:
            mapped[field.field_id] = field.suggested_value
            continue

        # Try to match the label to a known profile key
        label_lower = field.label.lower().strip()
        profile_key = _LABEL_TO_PROFILE_KEY.get(label_lower)

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
            unmapped.append(field)

    return mapped, unmapped, salary_missing


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
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary)

        # Escalate for salary missing
        if salary_missing:
            log.warning("salary_missing")
            return Result(
                ok=False,
                error="Salary field detected but no min_salary configured",
                reason="salary_missing",
            )

        # Escalate for unrecognized fields
        if unmapped:
            unmapped_labels = [f.label for f in unmapped]
            log.warning("unrecognized_fields", fields=unmapped_labels)
            return Result(
                ok=False,
                error=f"Unrecognized fields: {', '.join(unmapped_labels)}",
                reason="unrecognized_field",
            )

        # Fill all mapped fields
        for field_id, value in mapped.items():
            sanitized = sanitize_value(value)
            if sanitized is None:
                log.warning("unsafe_value_skipped", field_id=field_id)
                return Result(
                    ok=False,
                    error=f"Unsafe value detected for field {field_id}",
                    reason="unsafe_value",
                )

            try:
                selector = f"[id='{field_id}'], [name='{field_id}']"
                await page.fill(selector, sanitized)
                log.debug("field_filled", field_id=field_id)
            except Exception as exc:
                log.error("fill_failed", field_id=field_id, error=str(exc))
                return Result(
                    ok=False,
                    error=f"Failed to fill field {field_id}: {exc}",
                    reason="fill_failed",
                )

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
