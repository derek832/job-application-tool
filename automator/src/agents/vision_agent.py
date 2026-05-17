"""Vision Agent for external job application form filling.

Implements the full sequence: navigate → screenshot → identify fields →
map fields → fill fields → submit, with escalation for CAPTCHA,
unrecognized fields, salary missing, and multi-page forms (>3 pages).

All values are sanitized before being typed into form fields to prevent
injection via malicious job postings.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.claude_client import ClaudeClient, FormField
from src.api.schemas import UserProfile
from src.db.models import ExternalApplyLog, JobRecord

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
        application_notes: JSON string summarizing what was filled/submitted.
    """

    ok: bool
    error: str | None = None
    reason: str | None = None
    application_notes: str | None = None


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


async def _log_external_apply(
    session: AsyncSession | None,
    job_id: str,
    domain: str,
    method: str,
    dom_fields_found: int,
    vision_fields_found: int,
    fields_filled: int,
    outcome: str,
    failure_reason: str | None = None,
) -> None:
    """Write an ExternalApplyLog row to track extraction method usage.

    Silently skips if no session is available (e.g. during tests without DB).
    """
    if session is None:
        return
    try:
        entry = ExternalApplyLog(
            job_id=job_id,
            domain=domain,
            method=method,
            dom_fields_found=dom_fields_found,
            vision_fields_found=vision_fields_found,
            fields_filled=fields_filled,
            outcome=outcome,
            failure_reason=failure_reason,
            timestamp=datetime.now(UTC).isoformat(),
        )
        session.add(entry)
        await session.flush()
    except Exception:
        # Tracking should never break the apply flow
        logger.debug("external_apply_log_write_failed", job_id=job_id)


async def process_external_apply(
    job_record: JobRecord,
    profile: UserProfile,
    page: Page,
    claude_client: ClaudeClient,
    min_salary: int | None = None,
    dry_run: bool = False,
    session: AsyncSession | None = None,
) -> Result:
    """Process an external job application using DOM-based form detection.

    Uses a hybrid approach:
    1. Extract form fields directly from the DOM (labels, types, selectors)
    2. Map known fields to profile values locally
    3. For unknown fields, ask Claude (text-based, not vision) for answers
    4. Fill fields using real DOM selectors (not visual coordinates)
    5. Upload resume PDF to file inputs
    6. Submit the form (unless dry_run is True)

    Falls back to Claude Vision only if DOM extraction finds no fields.

    Args:
        job_record: The job record with external_url to apply to.
        profile: The user's profile configuration for form filling.
        page: A Playwright Page instance for browser interaction.
        claude_client: The Claude API client for field identification.
        min_salary: The user's minimum salary from GoalsProfile, or None.
        dry_run: If True, fills the form but does not click submit.

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

    # Click through to the actual form (ATS landing pages)
    await _click_through_to_form(page, log)

    # Detect if we're on a login/registration page instead of the application form
    from src.agents.ats_registration import (
        _extract_domain,
        detect_page_type,
        get_stored_account,
        handle_google_oauth,
        handle_login,
        handle_registration,
        store_account,
        wait_for_verification_email,
    )

    page_text = await page.inner_text("body")
    page_type = detect_page_type(page_text)
    domain = _extract_domain(job_record.external_url or "")

    if page_type == "google_oauth":
        log.info("detected_google_oauth", domain=domain)
        success = await handle_google_oauth(page)
        if not success:
            return Result(ok=False, error="Google OAuth flow failed", reason="oauth_failed")
        if session:
            await store_account(session, domain, profile.email or "", None, "google_oauth")

    elif page_type == "login" and session and profile.email:
        log.info("detected_login_page", domain=domain)
        stored = await get_stored_account(session, domain, profile.email)
        if stored and stored.password:
            log.info("using_stored_credentials", domain=domain)
            await handle_login(page, stored.email, stored.password)
        elif stored and stored.auth_method == "google_oauth":
            await handle_google_oauth(page)
        else:
            log.warning("no_stored_credentials", domain=domain)
            return Result(
                ok=False,
                error=f"Login required but no stored credentials for {domain}",
                reason="login_required",
            )

    elif page_type == "registration" and profile.email:
        log.info("detected_registration_page", domain=domain)
        success, password = await handle_registration(page, profile.email, profile.full_name)
        if success and password and session:
            await store_account(
                session, domain, profile.email, password, "password", "auto-registered"
            )
            # Check if email verification is needed
            new_page_text = await page.inner_text("body")
            if "verify" in new_page_text.lower() or "check your email" in new_page_text.lower():
                log.info("waiting_for_verification_email", domain=domain)
                verify_url = await wait_for_verification_email(profile.email, domain)
                if verify_url:
                    await page.goto(verify_url, timeout=30000)
                    await page.wait_for_timeout(3000)
                else:
                    return Result(
                        ok=False,
                        error="Email verification required but no link found",
                        reason="verification_timeout",
                    )
        elif not success:
            return Result(
                ok=False,
                error="Account registration failed",
                reason="registration_failed",
            )

    page_count = 0
    total_dom_fields_found = 0
    total_filled_count = 0
    filled_details: list[dict[str, str]] = []

    while True:
        page_count += 1

        if page_count > MAX_FORM_PAGES:
            log.warning("too_many_pages", page_count=page_count)
            await _log_external_apply(
                session,
                job_record.id,
                domain,
                "dom",
                total_dom_fields_found,
                0,
                total_filled_count,
                "failed",
                "too_many_pages",
            )
            return Result(
                ok=False,
                error=f"External form has {page_count} pages (max {MAX_FORM_PAGES})",
                reason="too_many_pages",
            )

        # Extract form fields from the DOM
        dom_fields = await _extract_dom_fields(page)
        log.info("dom_fields_extracted", count=len(dom_fields), page_number=page_count)
        total_dom_fields_found += len(dom_fields)

        if not dom_fields:
            # No fields found — might be a confirmation page or error
            log.info("no_fields_found_on_page", page_number=page_count)
            break

        # Check for CAPTCHA in the page
        page_text = await page.inner_text("body")
        if _page_has_captcha(page_text):
            log.warning("captcha_detected")
            await _log_external_apply(
                session,
                job_record.id,
                domain,
                "dom",
                total_dom_fields_found,
                0,
                total_filled_count,
                "escalated",
                "captcha_detected",
            )
            return Result(
                ok=False,
                error="CAPTCHA detected on application form",
                reason="captcha_detected",
            )

        # Map fields to profile values
        fill_plan = _build_fill_plan(dom_fields, profile, min_salary)

        # Handle file uploads (resume)
        for field in dom_fields:
            if field["type"] == "file":
                label_lower = field["label"].lower()
                if (
                    "resume" in label_lower or "cv" in label_lower
                ) and job_record.tailored_resume_pdf:
                    try:
                        file_input = await page.query_selector(field["selector"])
                        if file_input:
                            await file_input.set_input_files(job_record.tailored_resume_pdf)
                            log.info("resume_uploaded", path=job_record.tailored_resume_pdf)
                    except Exception as exc:
                        log.warning("resume_upload_failed", error=str(exc))

        # Fill text/select fields
        filled_count = 0
        for field_info in fill_plan:
            value = field_info.get("value")
            if not value:
                continue

            sanitized = sanitize_value(value)
            if sanitized is None:
                continue

            try:
                selector = field_info["selector"]
                field_type = field_info.get("type", "text")

                if field_type == "select":
                    await page.select_option(selector, label=sanitized)
                else:
                    await page.fill(selector, sanitized, timeout=5000)
                filled_count += 1
                filled_details.append({"field": field_info["label"], "value": sanitized})
                log.debug("field_filled", label=field_info["label"], selector=selector)
            except Exception as exc:
                # Try clicking and typing as fallback
                try:
                    el = await page.query_selector(field_info["selector"])
                    if el:
                        await el.click()
                        await page.keyboard.type(sanitized)
                        filled_count += 1
                        filled_details.append({"field": field_info["label"], "value": sanitized})
                        log.debug("field_filled_via_type", label=field_info["label"])
                    else:
                        log.debug("field_skip_not_found", label=field_info["label"])
                except Exception:
                    log.debug("field_fill_failed", label=field_info["label"], error=str(exc))

        log.info("fields_filled", filled=filled_count, total=len(fill_plan), page=page_count)
        total_filled_count += filled_count

        # Check for Next/Continue button (multi-page form)
        next_button = await page.query_selector(
            "button:has-text('Next'), button:has-text('Continue'), "
            "input[type='submit'][value*='Next'], input[type='submit'][value*='Continue']"
        )

        if next_button:
            is_visible = await next_button.is_visible()
            if is_visible:
                log.info("advancing_to_next_page", current_page=page_count)
                await next_button.click()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                import asyncio

                await asyncio.sleep(2)
                continue

        # No next button — look for submit
        break

    # Submit the form (or skip if dry_run)
    import json as _json

    notes = _json.dumps(filled_details, indent=2) if filled_details else None

    # If no DOM fields were found at all, this is where vision would be needed
    if total_dom_fields_found == 0:
        log.warning("dom_extraction_failed_completely", domain=domain)
        await _log_external_apply(
            session,
            job_record.id,
            domain,
            "none",
            0,
            0,
            0,
            "failed",
            "no_dom_fields",
        )
        return Result(
            ok=False,
            error="No form fields found via DOM extraction",
            reason="no_dom_fields",
        )

    if dry_run:
        log.info("dry_run_skipping_submit", fields_filled=True)
        method = "dom" if total_dom_fields_found > 0 else "none"
        await _log_external_apply(
            session,
            job_record.id,
            domain,
            method,
            total_dom_fields_found,
            0,
            total_filled_count,
            "dry_run",
        )
        return Result(ok=True, application_notes=notes)

    try:
        submit_button = await page.query_selector(
            "button[type='submit'], button:has-text('Submit'), "
            "button:has-text('Apply'), button:has-text('Send Application'), "
            "input[type='submit']"
        )
        if submit_button:
            is_visible = await submit_button.is_visible()
            if is_visible:
                log.info("submitting_form")
                await submit_button.click()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            else:
                log.warning("submit_button_not_visible")
                await _log_external_apply(
                    session,
                    job_record.id,
                    domain,
                    "dom",
                    total_dom_fields_found,
                    0,
                    total_filled_count,
                    "failed",
                    "no_submit_button",
                )
                return Result(
                    ok=False, error="Submit button not visible", reason="no_submit_button"
                )
        else:
            log.warning("no_submit_button")
            await _log_external_apply(
                session,
                job_record.id,
                domain,
                "dom",
                total_dom_fields_found,
                0,
                total_filled_count,
                "failed",
                "no_submit_button",
            )
            return Result(ok=False, error="Could not find submit button", reason="no_submit_button")
    except Exception as exc:
        log.error("submission_failed", error=str(exc))
        await _log_external_apply(
            session,
            job_record.id,
            domain,
            "dom",
            total_dom_fields_found,
            0,
            total_filled_count,
            "failed",
            "submission_failed",
        )
        return Result(ok=False, error=f"Form submission failed: {exc}", reason="submission_failed")

    log.info("external_apply_success")
    await _log_external_apply(
        session,
        job_record.id,
        domain,
        "dom",
        total_dom_fields_found,
        0,
        total_filled_count,
        "submitted",
    )
    return Result(ok=True, application_notes=notes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _extract_dom_fields(page: Page) -> list[dict]:
    """Extract all form input fields from the page DOM.

    Finds all visible input, select, and textarea elements and extracts
    their label, type, id, name, and a working CSS selector.

    Args:
        page: The Playwright page.

    Returns:
        List of dicts with keys: label, type, selector, id, name, tag.
    """
    fields = await page.evaluate("""() => {
        const results = [];
        const inputs = document.querySelectorAll(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
            'select, textarea'
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
            if (!label) {
                const parentLabel = el.closest('label');
                if (parentLabel) label = parentLabel.textContent.trim();
            }
            if (!label) {
                const prev = el.previousElementSibling;
                if (prev && (prev.tagName === 'LABEL' || prev.tagName === 'SPAN')) {
                    label = prev.textContent.trim();
                }
            }

            let selector = '';
            if (el.id) {
                selector = '#' + CSS.escape(el.id);
            } else if (el.name) {
                selector = '[name="' + el.name + '"]';
            }

            results.push({
                label: label.replace(/[\\n\\r]+/g, ' ').replace(/\\s+/g, ' ').trim(),
                type: el.type || el.tagName.toLowerCase(),
                selector: selector,
                id: el.id || '',
                name: el.name || '',
                tag: el.tagName.toLowerCase(),
                value: el.value || '',
            });
        }
        return results;
    }""")

    return fields


def _build_fill_plan(
    dom_fields: list[dict],
    profile: UserProfile,
    min_salary: int | None,
) -> list[dict]:
    """Build a plan for which fields to fill with which values.

    Maps DOM-extracted fields to user profile values using label matching.
    """
    zip_code = profile.common_answers.get("zip_code", profile.common_answers.get("zip", ""))

    available_values: dict[str, str] = {}
    if profile.full_name:
        available_values["full_name"] = profile.full_name
        parts = profile.full_name.split(None, 1)
        if len(parts) == 2:
            available_values["first_name"] = parts[0]
            available_values["last_name"] = parts[1]
        else:
            available_values["first_name"] = profile.full_name
            available_values["last_name"] = ""
    if profile.email:
        available_values["email"] = profile.email
    if profile.phone:
        available_values["phone"] = profile.phone
    if profile.location:
        available_values["location"] = profile.location
        if "," in profile.location:
            city_state = profile.location.split(",")
            available_values["city"] = city_state[0].strip()
            available_values["state"] = city_state[1].strip() if len(city_state) > 1 else ""
    if zip_code:
        available_values["zip"] = zip_code
    if profile.work_auth:
        available_values["work_auth"] = profile.work_auth
    if profile.linkedin_url:
        available_values["linkedin"] = profile.linkedin_url
        available_values["website"] = profile.linkedin_url
    if min_salary is not None:
        available_values["salary"] = str(min_salary)

    available_values["date_available"] = profile.common_answers.get("date_available", "2 weeks")
    available_values["country"] = profile.common_answers.get("country", "United States")

    for key, val in profile.common_answers.items():
        available_values[key.lower()] = val

    label_rules: list[tuple[str, str]] = [
        ("first name", "first_name"),
        ("last name", "last_name"),
        ("full name", "full_name"),
        ("email", "email"),
        ("phone", "phone"),
        ("mobile", "phone"),
        ("telephone", "phone"),
        ("city", "city"),
        ("state", "state"),
        ("zip", "zip"),
        ("postal", "zip"),
        ("country", "country"),
        ("address", "location"),
        ("location", "location"),
        ("linkedin", "linkedin"),
        ("website", "website"),
        ("portfolio", "website"),
        ("blog", "website"),
        ("work auth", "work_auth"),
        ("authorized", "work_auth"),
        ("legally auth", "work_auth"),
        ("salary", "salary"),
        ("desired pay", "salary"),
        ("compensation", "salary"),
        ("date available", "date_available"),
        ("start date", "date_available"),
        ("when can you start", "date_available"),
        ("earliest start", "date_available"),
    ]

    fill_plan: list[dict] = []

    for field in dom_fields:
        if field["type"] == "file":
            continue
        if field.get("value"):
            continue
        if not field.get("selector"):
            continue

        label_lower = field["label"].lower().replace("*", "").strip()
        if not label_lower:
            continue
        if _is_optional_field(label_lower):
            continue

        matched_value = None
        for label_pattern, value_key in label_rules:
            if label_pattern in label_lower:
                matched_value = available_values.get(value_key)
                break

        if matched_value is None:
            for answer_key, answer_val in profile.common_answers.items():
                if answer_key.lower() in label_lower or label_lower in answer_key.lower():
                    matched_value = answer_val
                    break

        if matched_value:
            fill_plan.append(
                {
                    "selector": field["selector"],
                    "label": field["label"],
                    "value": matched_value,
                    "type": field["type"],
                }
            )

    return fill_plan


def _page_has_captcha(page_text: str) -> bool:
    """Check if the page contains CAPTCHA indicators."""
    lower = page_text.lower()
    indicators = ["recaptcha", "hcaptcha", "captcha", "i'm not a robot", "verify you are human"]
    return any(ind in lower for ind in indicators)


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
