"""
Property-based tests for pass criteria evaluation.

Uses Hypothesis to verify that meets_pass_criteria() correctly evaluates
FillResult instances against the defined pass criteria.

Properties tested:
- Property 4: Pass Criteria Evaluation

Feature: visual-apply-validation, Property 4: Pass Criteria Evaluation
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.agents.visual_form_filler import FillResult
from src.pipeline.validation_models import meets_pass_criteria


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Possible reason values including the two that should cause failure
REASONS = [
    None,
    "captcha_detected",
    "vision_api_error",
    "navigation_failure",
    "field_identification_failure",
    "timeout",
    "success",
]

reason_strategy = st.sampled_from(REASONS)


# ---------------------------------------------------------------------------
# Property 4: Pass Criteria Evaluation
# ---------------------------------------------------------------------------


@given(
    ok=st.booleans(),
    fields_filled=st.integers(min_value=0, max_value=100),
    reason=reason_strategy,
)
@settings(max_examples=200)
def test_pass_criteria_evaluation(
    ok: bool,
    fields_filled: int,
    reason: str | None,
) -> None:
    """
    For any FillResult with arbitrary ok, fields_filled, and reason values,
    meets_pass_criteria returns True if and only if all three conditions hold:
    - ok is True
    - fields_filled >= 3
    - reason is not "captcha_detected" and not "vision_api_error"

    No other combination should pass.

    **Validates: Requirements 3.1, 3.5**
    """
    result = FillResult(
        ok=ok,
        fields_filled=fields_filled,
        reason=reason,
    )

    actual = meets_pass_criteria(result)

    # Compute expected result from the specification
    expected = (
        ok is True
        and fields_filled >= 3
        and reason not in ("captcha_detected", "vision_api_error")
    )

    assert actual == expected, (
        f"meets_pass_criteria returned {actual}, expected {expected} "
        f"for ok={ok}, fields_filled={fields_filled}, reason={reason!r}"
    )
