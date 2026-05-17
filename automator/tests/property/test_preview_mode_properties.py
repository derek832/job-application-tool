"""
Property-based tests for preview mode never advancing beyond scoring.

Uses Hypothesis to verify that compute_projected_action() never returns
any status that implies application was attempted. In preview mode, the
maximum status reached is "scored" — no job shall transition to "applying",
"applied", or "apply_failed".

Properties tested:
- Property 1: Preview Mode Never Advances Beyond Scoring
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.preview_pipeline import compute_projected_action


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Statuses that imply application was attempted — these must NEVER appear
# in preview mode output.
APPLICATION_STATUSES = frozenset({"applying", "applied", "apply_failed"})

# The only valid projected_action values that compute_projected_action() may return.
VALID_PREVIEW_ACTIONS = frozenset({"blacklisted", "skip", "auto_apply", "stretch_queue"})


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Fit scores: 0–100 integer or None (None means job wasn't scored)
fit_score_strategy = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=100),
)

# Thresholds: realistic range for good_fit and stretch thresholds (1–100)
threshold_strategy = st.integers(min_value=1, max_value=100)

# Blacklist flag
blacklist_flag_strategy = st.booleans()


# ---------------------------------------------------------------------------
# Property 1: Preview Mode Never Advances Beyond Scoring
# ---------------------------------------------------------------------------


@given(
    fit_score=fit_score_strategy,
    good_fit_threshold=threshold_strategy,
    stretch_threshold=threshold_strategy,
    is_blacklisted=blacklist_flag_strategy,
)
@settings(max_examples=200)
def test_preview_mode_never_returns_application_status(
    fit_score: int | None,
    good_fit_threshold: int,
    stretch_threshold: int,
    is_blacklisted: bool,
) -> None:
    """
    For any pipeline execution in preview mode and any set of discovered jobs,
    no job shall transition to status "applying", "applied", or "apply_failed".
    The maximum status reached in preview mode is "scored".

    compute_projected_action() must never return any status that implies
    application was attempted.

    **Validates: Requirements 1.1**
    """
    result = compute_projected_action(
        fit_score=fit_score,
        good_fit_threshold=good_fit_threshold,
        stretch_threshold=stretch_threshold,
        is_blacklisted=is_blacklisted,
    )

    assert result not in APPLICATION_STATUSES, (
        f"Preview mode returned application status '{result}' which implies "
        f"application was attempted. Preview mode must never advance beyond "
        f"scoring. Inputs: fit_score={fit_score}, "
        f"good_fit_threshold={good_fit_threshold}, "
        f"stretch_threshold={stretch_threshold}, is_blacklisted={is_blacklisted}"
    )


@given(
    fit_score=fit_score_strategy,
    good_fit_threshold=threshold_strategy,
    stretch_threshold=threshold_strategy,
    is_blacklisted=blacklist_flag_strategy,
)
@settings(max_examples=200)
def test_preview_projected_action_is_always_valid(
    fit_score: int | None,
    good_fit_threshold: int,
    stretch_threshold: int,
    is_blacklisted: bool,
) -> None:
    """
    For any combination of fit score, thresholds, and blacklist flag,
    compute_projected_action() shall only return one of the valid preview
    actions: "blacklisted", "skip", "auto_apply", or "stretch_queue".

    None of these are application statuses — they represent classification
    decisions, not execution outcomes.

    **Validates: Requirements 1.1**
    """
    result = compute_projected_action(
        fit_score=fit_score,
        good_fit_threshold=good_fit_threshold,
        stretch_threshold=stretch_threshold,
        is_blacklisted=is_blacklisted,
    )

    assert result in VALID_PREVIEW_ACTIONS, (
        f"compute_projected_action() returned '{result}' which is not in the "
        f"set of valid preview actions {VALID_PREVIEW_ACTIONS}. "
        f"Inputs: fit_score={fit_score}, good_fit_threshold={good_fit_threshold}, "
        f"stretch_threshold={stretch_threshold}, is_blacklisted={is_blacklisted}"
    )
