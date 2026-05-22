"""Failure classification for visual apply validation dry-runs.

Classifies dry-run failures into exactly one category based on the FillResult
and Docker log content. Used by the agent to determine the appropriate
diagnostic workflow for each failure.
"""

from __future__ import annotations

from .validation_models import FillResult

# Valid failure categories
FAILURE_CATEGORIES: set[str] = {
    "no_fields_detected",
    "vision_api_error",
    "captcha_detected",
    "no_submit_button",
    "low_fill_count",
    "platform_specific_error",
}


def classify_failure(fill_result: FillResult, docker_logs: str) -> str:
    """Classify a dry-run failure into exactly one category.

    The classification logic follows a priority order:
    1. no_fields_detected — fields_found == 0
    2. vision_api_error — reason contains "vision"
    3. captcha_detected — reason == "captcha_detected"
    4. no_submit_button — fields_filled > 0 but ok is False
    5. low_fill_count — ok is True but fields_filled < 3
    6. platform_specific_error — fallback for all other failures

    Args:
        fill_result: The FillResult from the dry-run execution.
        docker_logs: Raw Docker log output from the automator container.

    Returns:
        Exactly one category string from FAILURE_CATEGORIES.
    """
    # 1. No fields detected at all
    if fill_result.fields_found == 0:
        return "no_fields_detected"

    # 2. Vision API error (reason contains "vision", case-insensitive)
    if fill_result.reason and "vision" in fill_result.reason.lower():
        return "vision_api_error"

    # 3. CAPTCHA detected
    if fill_result.reason == "captcha_detected":
        return "captcha_detected"

    # 4. Fields were filled but form not completed (not ok)
    if fill_result.fields_filled > 0 and not fill_result.ok:
        return "no_submit_button"

    # 5. Ok but too few fields filled
    if fill_result.ok and fill_result.fields_filled < 3:
        return "low_fill_count"

    # 6. Fallback — platform-specific or unclassifiable error
    return "platform_specific_error"
