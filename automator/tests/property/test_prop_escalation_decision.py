"""
Property-based tests for Escalation Decision Boundary.

Uses Hypothesis to verify that the escalation decision function creates a
human_review escalation if and only if fit_score >= human_review_threshold
AND open-ended fields are present. When fit_score < threshold or no open-ended
fields exist, no escalation should be created.

Properties tested:
- Property 1: Escalation Decision Boundary

Feature: human-in-the-loop-escalation, Property 1: Escalation Decision Boundary
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Helper function encapsulating the escalation decision logic
# ---------------------------------------------------------------------------


def should_escalate(fit_score: int, threshold: int, has_open_ended: bool) -> bool:
    """Determine whether a job should be escalated for human review.

    The escalation decision is:
    - When open-ended fields are detected AND fit_score >= threshold → escalate
    - When fit_score < threshold → no escalation (auto-fill with Claude drafts)
    - When no open-ended fields → no escalation regardless of score

    Args:
        fit_score: The job's fit score (0-100).
        threshold: The human_review_threshold from settings (50-100).
        has_open_ended: Whether the job application has open-ended form fields.

    Returns:
        True if the job should be escalated for human review, False otherwise.
    """
    return has_open_ended and fit_score >= threshold


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Fit scores in the valid range [0, 100]
fit_score_strategy = st.integers(min_value=0, max_value=100)

# Threshold in the valid configurable range [50, 100]
threshold_strategy = st.integers(min_value=50, max_value=100)

# Boolean for whether open-ended fields are present
has_open_ended_strategy = st.booleans()


# ---------------------------------------------------------------------------
# Property 1: Escalation Decision Boundary
# ---------------------------------------------------------------------------


@given(
    fit_score=fit_score_strategy,
    threshold=threshold_strategy,
)
@settings(max_examples=200)
def test_escalation_when_open_ended_and_score_at_or_above_threshold(
    fit_score: int,
    threshold: int,
) -> None:
    """
    When has_open_ended=True AND fit_score >= threshold, should_escalate
    returns True (escalation is created).

    **Validates: Requirements 2.1, 2.5**
    """
    if fit_score >= threshold:
        result = should_escalate(fit_score=fit_score, threshold=threshold, has_open_ended=True)
        assert result is True, (
            f"Expected escalation for fit_score={fit_score} >= threshold={threshold} "
            f"with open-ended fields, but got {result}"
        )


@given(
    fit_score=fit_score_strategy,
    threshold=threshold_strategy,
)
@settings(max_examples=200)
def test_no_escalation_when_open_ended_and_score_below_threshold(
    fit_score: int,
    threshold: int,
) -> None:
    """
    When has_open_ended=True AND fit_score < threshold, should_escalate
    returns False (no escalation, auto-fill with Claude drafts).

    **Validates: Requirements 2.1, 2.5**
    """
    if fit_score < threshold:
        result = should_escalate(fit_score=fit_score, threshold=threshold, has_open_ended=True)
        assert result is False, (
            f"Expected no escalation for fit_score={fit_score} < threshold={threshold} "
            f"with open-ended fields, but got {result}"
        )


@given(
    fit_score=fit_score_strategy,
    threshold=threshold_strategy,
)
@settings(max_examples=200)
def test_no_escalation_when_no_open_ended_fields(
    fit_score: int,
    threshold: int,
) -> None:
    """
    When has_open_ended=False, should_escalate returns False regardless
    of the fit_score (no open-ended fields means no escalation needed).

    **Validates: Requirements 2.1, 2.5**
    """
    result = should_escalate(fit_score=fit_score, threshold=threshold, has_open_ended=False)
    assert result is False, (
        f"Expected no escalation when no open-ended fields present "
        f"(fit_score={fit_score}, threshold={threshold}), but got {result}"
    )


@given(
    fit_score=fit_score_strategy,
    threshold=threshold_strategy,
    has_open_ended=has_open_ended_strategy,
)
@settings(max_examples=200)
def test_escalation_decision_boundary_complete(
    fit_score: int,
    threshold: int,
    has_open_ended: bool,
) -> None:
    """
    For any job with any fit_score in [0, 100] and any threshold in [50, 100],
    the escalation decision function should create a human_review escalation
    if and only if fit_score >= threshold AND has_open_ended is True.

    This is the complete decision boundary property — it verifies the
    biconditional: escalate ↔ (has_open_ended ∧ fit_score ≥ threshold).

    **Validates: Requirements 2.1, 2.5**
    """
    result = should_escalate(fit_score=fit_score, threshold=threshold, has_open_ended=has_open_ended)
    expected = has_open_ended and fit_score >= threshold

    assert result == expected, (
        f"Decision boundary violated: should_escalate("
        f"fit_score={fit_score}, threshold={threshold}, "
        f"has_open_ended={has_open_ended}) returned {result}, expected {expected}"
    )
