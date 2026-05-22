"""
Property-based tests for failure classification completeness.

Uses Hypothesis to verify that for any FillResult that does NOT meet pass criteria
combined with any Docker log content, the failure classifier always returns exactly
one category from the defined set. The classifier never returns None and never
returns multiple categories.

Properties tested:
- Property 5: Failure Classification Completeness
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.agents.visual_form_filler import FillResult
from src.pipeline.failure_classifier import FAILURE_CATEGORIES, classify_failure
from src.pipeline.validation_models import meets_pass_criteria


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Possible reason values including failure-related ones and None
reason_values = st.sampled_from([
    None,
    "captcha_detected",
    "vision_api_error",
    "vision_timeout",
    "navigation_failure",
    "field_identification_failure",
    "timeout",
    "unknown",
    "",
    "platform_specific_error",
    "Vision API returned empty",
])

# Strategy for generating arbitrary FillResult instances
fill_result_strategy = st.builds(
    FillResult,
    ok=st.booleans(),
    fields_filled=st.integers(min_value=0, max_value=50),
    fields_found=st.integers(min_value=0, max_value=50),
    pages_completed=st.integers(min_value=0, max_value=10),
    error=st.one_of(st.none(), st.text(min_size=0, max_size=100)),
    reason=reason_values,
)

# Strategy for Docker log content
docker_logs_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z", "S")),
    min_size=0,
    max_size=500,
)


# ---------------------------------------------------------------------------
# Property 5: Failure Classification Completeness
# ---------------------------------------------------------------------------


@given(
    fill_result=fill_result_strategy,
    docker_logs=docker_logs_strategy,
)
@settings(max_examples=200)
def test_failure_classifier_returns_exactly_one_category(
    fill_result: FillResult,
    docker_logs: str,
) -> None:
    """
    For any FillResult that does NOT meet Pass_Criteria combined with any Docker
    log content, the failure classifier shall assign exactly one category from the
    defined set: no_fields_detected, vision_api_error, captcha_detected,
    no_submit_button, low_fill_count, or platform_specific_error.

    The classifier shall never return None and never return multiple categories.

    **Validates: Requirements 3.3**
    """
    # Only test inputs that do NOT meet pass criteria (failure cases)
    assume(not meets_pass_criteria(fill_result))

    result = classify_failure(fill_result, docker_logs)

    # Result must be a string (never None)
    assert result is not None, (
        f"classify_failure returned None for fill_result={fill_result}, "
        f"docker_logs={docker_logs!r}"
    )
    assert isinstance(result, str), (
        f"classify_failure must return a string, got {type(result).__name__}: {result}"
    )

    # Result must be exactly one category from the defined set
    assert result in FAILURE_CATEGORIES, (
        f"classify_failure returned '{result}' which is not in FAILURE_CATEGORIES: "
        f"{FAILURE_CATEGORIES}. Input: fill_result={fill_result}, "
        f"docker_logs={docker_logs!r}"
    )
