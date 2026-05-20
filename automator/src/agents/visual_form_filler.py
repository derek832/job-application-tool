"""Visual form filler using screenshot-based coordinate interaction.

Implements an iterative screenshot → identify → click → type → verify loop
that works regardless of DOM structure (shadow DOM, custom React components,
Workday SPAs, etc.). Uses Claude Vision to identify interactive elements
with pixel coordinates, then Playwright's mouse/keyboard APIs to interact.

This replaces the fragile DOM-based approach for external ATS forms while
keeping DOM extraction as a fast-path optimization for simple forms.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from playwright.async_api import Page

from src.agents.claude_client import ClaudeClient, VisualFormField
from src.agents.vision_agent import sanitize_value
from src.api.schemas import UserProfile

logger = structlog.get_logger()

# Safety limits
MAX_ITERATIONS = 20  # Max screenshot→fill cycles per form page
MAX_PAGES = 10  # Max multi-page form pages
FILL_CONFIDENCE_THRESHOLD = 0.6  # Minimum confidence to interact with a field
VERIFY_AFTER_N_FIELDS = 3  # Verify screenshot every N fields filled
HUMAN_TYPING_DELAY_MS = 30  # Milliseconds between keystrokes


@dataclass
class FillResult:
    """Result of a visual form filling attempt.

    Attributes:
        ok: Whether the form was successfully submitted.
        fields_filled: Total number of fields filled across all pages.
        fields_found: Total number of interactive fields detected.
        pages_completed: Number of form pages navigated.
        error: Human-readable error if ok is False.
        reason: Machine-readable failure reason.
        application_notes: JSON-serializable summary of what was filled.
        verification_failures: Fields that failed post-fill verification.
    """

    ok: bool
    fields_filled: int = 0
    fields_found: int = 0
    pages_completed: int = 0
    error: str | None = None
    reason: str | None = None
    application_notes: list[dict[str, str]] = field(default_factory=list)
    verification_failures: list[str] = field(default_factory=list)


async def _take_viewport_screenshot(page: Page) -> tuple[bytes, int, int]:
    """Take a screenshot of the current viewport and return dimensions.

    Args:
        page: The Playwright page.

    Returns:
        Tuple of (screenshot_bytes, width, height).
    """
    viewport = page.viewport_size or {"width": 1280, "height": 900}
    screenshot = await page.screenshot(full_page=False, type="png")
    return screenshot, viewport["width"], viewport["height"]


async def _click_at(page: Page, x: int, y: int) -> None:
    """Click at specific pixel coordinates with a small random offset.

    Args:
        page: The Playwright page.
        x: X coordinate in pixels.
        y: Y coordinate in pixels.
    """
    await page.mouse.click(x, y)
    await asyncio.sleep(0.3)


async def _fill_text_field(page: Page, field: VisualFormField, value: str) -> bool:
    """Fill a text/textarea field by clicking and typing.

    Clicks the field center to focus, selects any existing text, then types
    the new value with human-like delays.

    Args:
        page: The Playwright page.
        field: The visual field with coordinates.
        value: The sanitized value to type.

    Returns:
        True if the interaction completed without error.
    """
    x, y = field.center[0], field.center[1]
    try:
        await _click_at(page, x, y)
        # Triple-click to select all existing text in the field
        await page.mouse.click(x, y, click_count=3)
        await asyncio.sleep(0.2)
        # Type the value with human-like delay
        await page.keyboard.type(value, delay=HUMAN_TYPING_DELAY_MS)
        # Tab out to trigger any validation
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.3)
        return True
    except Exception as exc:
        logger.debug("fill_text_field_error", label=field.label, error=str(exc))
        return False


async def _fill_select_field(page: Page, field: VisualFormField, value: str) -> bool:
    """Fill a dropdown/select field by clicking and selecting an option.

    Strategy:
    1. Click the dropdown trigger to open it
    2. Wait for options to appear
    3. Type the value to filter options (works on most custom dropdowns)
    4. Press Enter to select

    Args:
        page: The Playwright page.
        field: The visual field with coordinates.
        value: The option text to select.

    Returns:
        True if the interaction completed without error.
    """
    x, y = field.center[0], field.center[1]
    try:
        # Click to open dropdown
        await _click_at(page, x, y)
        await asyncio.sleep(0.8)  # Wait for dropdown animation

        # Try typing to filter (works on searchable dropdowns)
        await page.keyboard.type(value[:30], delay=50)
        await asyncio.sleep(0.5)

        # Press Enter to select the first matching option
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        return True
    except Exception as exc:
        logger.debug("fill_select_field_error", label=field.label, error=str(exc))
        return False


async def _fill_checkbox_field(page: Page, field: VisualFormField) -> bool:
    """Toggle a checkbox by clicking its center.

    Args:
        page: The Playwright page.
        field: The visual field with coordinates.

    Returns:
        True if the click completed without error.
    """
    x, y = field.center[0], field.center[1]
    try:
        await _click_at(page, x, y)
        return True
    except Exception as exc:
        logger.debug("fill_checkbox_error", label=field.label, error=str(exc))
        return False


async def _fill_radio_field(page: Page, field: VisualFormField) -> bool:
    """Select a radio button by clicking its center.

    Args:
        page: The Playwright page.
        field: The visual field with coordinates.

    Returns:
        True if the click completed without error.
    """
    x, y = field.center[0], field.center[1]
    try:
        await _click_at(page, x, y)
        return True
    except Exception as exc:
        logger.debug("fill_radio_error", label=field.label, error=str(exc))
        return False


async def _upload_file(page: Page, field: VisualFormField, file_path: str) -> bool:
    """Handle file upload by finding the file input near the visual coordinates.

    Since file inputs can't be filled by clicking coordinates alone, we use
    a hybrid approach: find the nearest file input in the DOM and use
    set_input_files on it.

    Args:
        page: The Playwright page.
        field: The visual field with coordinates.
        file_path: Path to the file to upload.

    Returns:
        True if the file was uploaded successfully.
    """
    try:
        # Try to find a file input near the visual coordinates
        file_inputs = await page.query_selector_all("input[type='file']")
        if file_inputs:
            # Use the first visible file input (most forms have only one)
            for file_input in file_inputs:
                try:
                    await file_input.set_input_files(file_path)
                    logger.info("file_uploaded_via_input", path=file_path)
                    return True
                except Exception:
                    continue

        # Fallback: click the upload area and hope a file dialog opens
        # (won't work in headless, but worth trying in headed mode)
        logger.warning("no_file_input_found", label=field.label)
        return False
    except Exception as exc:
        logger.debug("file_upload_error", label=field.label, error=str(exc))
        return False


async def _fill_single_field(
    page: Page,
    field: VisualFormField,
    resume_pdf_path: str | None,
) -> bool:
    """Dispatch to the appropriate fill method based on field type.

    Args:
        page: The Playwright page.
        field: The visual field to fill.
        resume_pdf_path: Path to resume PDF for file uploads.

    Returns:
        True if the field was filled successfully.
    """
    value = field.suggested_value
    if value is None and field.field_type not in ("checkbox", "radio", "file", "button"):
        return False

    if field.field_type in ("text", "textarea"):
        if value is None:
            return False
        sanitized = sanitize_value(value)
        if sanitized is None:
            logger.warning("visual_fill_sanitize_rejected", label=field.label)
            return False
        return await _fill_text_field(page, field, sanitized)

    elif field.field_type == "select":
        if value is None:
            return False
        sanitized = sanitize_value(value)
        if sanitized is None:
            return False
        return await _fill_select_field(page, field, sanitized)

    elif field.field_type == "checkbox":
        return await _fill_checkbox_field(page, field)

    elif field.field_type == "radio":
        return await _fill_radio_field(page, field)

    elif field.field_type == "file":
        if resume_pdf_path:
            return await _upload_file(page, field, resume_pdf_path)
        return False

    return False


async def fill_form_visually(
    page: Page,
    claude_client: ClaudeClient,
    profile: UserProfile,
    resume_pdf_path: str | None = None,
    min_salary: int | None = None,
    job_description: str | None = None,
    dry_run: bool = False,
) -> FillResult:
    """Fill a form using iterative screenshot-based visual interaction.

    This is the main entry point for visual form filling. It implements
    an iterative loop:
    1. Screenshot the current viewport
    2. Ask Claude to identify all interactive fields with coordinates
    3. Fill unfilled fields one at a time using mouse/keyboard
    4. Periodically verify fills with a fresh screenshot
    5. Click Next/Continue for multi-page forms
    6. Click Submit when all fields are filled

    Args:
        page: A Playwright Page positioned on the form.
        claude_client: Claude API client for vision calls.
        profile: User profile with values to fill.
        resume_pdf_path: Path to tailored resume PDF, or None.
        min_salary: Minimum salary for salary fields, or None.
        job_description: Job description for context on questions.
        dry_run: If True, fills fields but does not click Submit.

    Returns:
        FillResult with success/failure details.
    """
    log = logger.bind(url=page.url[:80])

    # Build profile JSON for Claude (include salary context)
    profile_data = profile.model_dump(exclude_none=True)
    if min_salary is not None:
        profile_data["min_salary"] = str(min_salary)
    profile_json = str(profile_data)

    filled_labels: list[str] = []
    total_fields_found = 0
    total_fields_filled = 0
    pages_completed = 0
    notes: list[dict[str, str]] = []

    for page_num in range(1, MAX_PAGES + 1):
        log.info("visual_fill_page_start", page=page_num)
        page_filled_this_round = 0
        stale_iterations = 0  # Track iterations with no progress

        for iteration in range(MAX_ITERATIONS):
            # Take a fresh screenshot
            screenshot, vw, vh = await _take_viewport_screenshot(page)

            # Ask Claude to identify fields
            try:
                fields = await claude_client.identify_fields_visual(
                    screenshot_bytes=screenshot,
                    profile=profile_json,
                    viewport_width=vw,
                    viewport_height=vh,
                    job_description=job_description,
                    filled_labels=filled_labels,
                )
            except Exception as exc:
                log.error("visual_identification_failed", error=str(exc))
                return FillResult(
                    ok=False,
                    fields_filled=total_fields_filled,
                    fields_found=total_fields_found,
                    pages_completed=pages_completed,
                    error=f"Claude Vision identification failed: {exc}",
                    reason="vision_api_error",
                    application_notes=notes,
                )

            total_fields_found += len(fields)
            log.debug(
                "visual_fields_identified",
                count=len(fields),
                iteration=iteration,
                page=page_num,
            )

            # Separate fields by type
            fillable = [
                f
                for f in fields
                if f.field_type not in ("button",)
                and (f.suggested_value is not None or f.field_type in ("checkbox", "radio", "file"))
                and f.label not in filled_labels
                and f.confidence >= FILL_CONFIDENCE_THRESHOLD
                and f.current_value is None  # Skip pre-filled fields
            ]
            buttons = [
                f
                for f in fields
                if f.field_type == "button" and f.confidence >= FILL_CONFIDENCE_THRESHOLD
            ]

            # Check for CAPTCHA indicators in field labels
            captcha_fields = [
                f
                for f in fields
                if any(
                    ind in f.label.lower()
                    for ind in ["captcha", "recaptcha", "hcaptcha", "not a robot"]
                )
            ]
            if captcha_fields:
                log.warning("captcha_detected_visually")
                return FillResult(
                    ok=False,
                    fields_filled=total_fields_filled,
                    fields_found=total_fields_found,
                    pages_completed=pages_completed,
                    error="CAPTCHA detected on form",
                    reason="captcha_detected",
                    application_notes=notes,
                )

            if not fillable:
                # No more fields to fill — look for navigation buttons
                submit_btn = next(
                    (
                        b
                        for b in buttons
                        if any(
                            kw in b.label.lower() for kw in ["submit", "send application", "apply"]
                        )
                    ),
                    None,
                )
                next_btn = next(
                    (
                        b
                        for b in buttons
                        if any(
                            kw in b.label.lower()
                            for kw in ["next", "continue", "save and continue"]
                        )
                    ),
                    None,
                )

                if next_btn:
                    # Multi-page form — advance to next page
                    log.info("visual_clicking_next", label=next_btn.label)
                    await _click_at(page, next_btn.center[0], next_btn.center[1])
                    await asyncio.sleep(3)  # Wait for page transition
                    pages_completed += 1
                    break  # Break inner loop, continue outer page loop

                elif submit_btn and not dry_run:
                    # Submit the form
                    log.info("visual_clicking_submit", label=submit_btn.label)
                    await _click_at(page, submit_btn.center[0], submit_btn.center[1])
                    await asyncio.sleep(3)
                    pages_completed += 1
                    return FillResult(
                        ok=True,
                        fields_filled=total_fields_filled,
                        fields_found=total_fields_found,
                        pages_completed=pages_completed,
                        application_notes=notes,
                    )

                elif submit_btn and dry_run:
                    log.info("visual_dry_run_skip_submit", label=submit_btn.label)
                    pages_completed += 1
                    return FillResult(
                        ok=True,
                        fields_filled=total_fields_filled,
                        fields_found=total_fields_found,
                        pages_completed=pages_completed,
                        application_notes=notes,
                    )

                else:
                    # No fillable fields and no buttons — might be stuck
                    stale_iterations += 1
                    if stale_iterations >= 3:
                        log.warning("visual_fill_stuck", iterations=iteration)
                        break
                    await asyncio.sleep(1)
                    continue

            # Fill fields one at a time for reliability
            field_to_fill = fillable[0]
            success = await _fill_single_field(page, field_to_fill, resume_pdf_path)

            if success:
                filled_labels.append(field_to_fill.label)
                total_fields_filled += 1
                page_filled_this_round += 1
                notes.append(
                    {
                        "field": field_to_fill.label,
                        "value": field_to_fill.suggested_value or "(interaction)",
                        "type": field_to_fill.field_type,
                    }
                )
                log.debug(
                    "visual_field_filled",
                    label=field_to_fill.label,
                    type=field_to_fill.field_type,
                )
                stale_iterations = 0
            else:
                # Failed to fill — skip this field to avoid infinite loop
                filled_labels.append(field_to_fill.label)
                stale_iterations += 1
                log.debug("visual_field_fill_failed", label=field_to_fill.label)

            # Periodic verification
            if total_fields_filled > 0 and total_fields_filled % VERIFY_AFTER_N_FIELDS == 0:
                await _verify_recent_fills(page, claude_client, notes[-VERIFY_AFTER_N_FIELDS:])

            await asyncio.sleep(0.5)

        else:
            # Inner loop exhausted without finding next/submit
            log.warning("visual_max_iterations_reached", page=page_num)
            break

    # If we get here without submitting, check if we filled anything useful
    if total_fields_filled == 0 and total_fields_found == 0:
        return FillResult(
            ok=False,
            fields_filled=0,
            fields_found=0,
            pages_completed=pages_completed,
            error="No interactive form fields detected visually",
            reason="no_fields_detected",
            application_notes=notes,
        )

    # We filled fields but couldn't find submit — partial success
    return FillResult(
        ok=False,
        fields_filled=total_fields_filled,
        fields_found=total_fields_found,
        pages_completed=pages_completed,
        error="Form filled but submit button not found or not clicked",
        reason="no_submit_button",
        application_notes=notes,
    )


async def _verify_recent_fills(
    page: Page,
    claude_client: ClaudeClient,
    recent_notes: list[dict[str, str]],
) -> list[str]:
    """Verify recently filled fields by taking a fresh screenshot.

    Args:
        page: The Playwright page.
        claude_client: Claude client for verification.
        recent_notes: Recent fill notes with 'field' and 'value' keys.

    Returns:
        List of field labels that failed verification.
    """
    try:
        screenshot, vw, vh = await _take_viewport_screenshot(page)
        expected = [
            {"label": n["field"], "value": n["value"]}
            for n in recent_notes
            if n.get("value") and n["value"] != "(interaction)"
        ]
        if not expected:
            return []

        results = await claude_client.verify_form_state(
            screenshot_bytes=screenshot,
            viewport_width=vw,
            viewport_height=vh,
            expected_fills=expected,
        )

        failures = [label for label, ok in results.items() if not ok]
        if failures:
            logger.warning("visual_verification_failures", fields=failures)
        return failures
    except Exception as exc:
        logger.debug("visual_verification_error", error=str(exc))
        return []
