"""
Property-based tests for URL replacement bounded retry logic.

Uses Hypothesis to verify correctness properties of the URLReplacementTracker
class in src/pipeline/url_validator.py.

Properties tested:
- Property 2: URL Replacement Bounded Retry
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.url_validator import URLReplacementTracker


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for platform names (simple ASCII identifiers)
platform_strategy = st.sampled_from(
    ["greenhouse", "lever", "workday", "icims", "bamboohr"]
)

# Strategy for sequences of stale/active URL results
# True = stale (needs replacement attempt), False = active (no replacement needed)
stale_sequence_strategy = st.lists(st.booleans(), min_size=1, max_size=20)


# ---------------------------------------------------------------------------
# Property 2: URL Replacement Bounded Retry
# ---------------------------------------------------------------------------


@given(
    platform=platform_strategy,
    stale_results=stale_sequence_strategy,
)
@settings(max_examples=200)
def test_at_most_3_replacement_attempts_allowed(
    platform: str,
    stale_results: list[bool],
) -> None:
    """
    For any platform and any sequence of stale/active URL results,
    attempt_replacement returns True at most 2 times (attempts 1 and 2),
    then returns False on the 3rd attempt. No more than 3 total calls
    to attempt_replacement can occur before the platform is blocked.

    **Validates: Requirements 1.4, 2.5**
    """
    tracker = URLReplacementTracker()
    allowed_count = 0
    total_attempts = 0

    for is_stale in stale_results:
        if is_stale:
            result = tracker.attempt_replacement(platform)
            total_attempts += 1
            if result:
                allowed_count += 1

    # At most 2 replacements are allowed (attempts 1 and 2 return True,
    # attempt 3 returns False and marks unavailable)
    assert allowed_count <= 2, (
        f"Expected at most 2 allowed replacements, but got {allowed_count} "
        f"for platform='{platform}' with {total_attempts} total attempts"
    )


@given(
    platform=platform_strategy,
    stale_results=stale_sequence_strategy,
)
@settings(max_examples=200)
def test_platform_marked_unavailable_after_3_attempts(
    platform: str,
    stale_results: list[bool],
) -> None:
    """
    For any platform, after 3 replacement attempts (regardless of sequence),
    is_unavailable(platform) returns True.

    **Validates: Requirements 1.4, 2.5**
    """
    tracker = URLReplacementTracker()
    total_attempts = 0

    for is_stale in stale_results:
        if is_stale:
            tracker.attempt_replacement(platform)
            total_attempts += 1

    if total_attempts >= 3:
        assert tracker.is_unavailable(platform), (
            f"Expected platform '{platform}' to be unavailable after "
            f"{total_attempts} attempts, but is_unavailable returned False"
        )


@given(
    platform=platform_strategy,
    extra_attempts=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=200)
def test_no_replacements_allowed_after_unavailable(
    platform: str,
    extra_attempts: int,
) -> None:
    """
    For any platform that has been marked unavailable (after 3 attempts),
    all subsequent calls to attempt_replacement return False.

    **Validates: Requirements 1.4, 2.5**
    """
    tracker = URLReplacementTracker()

    # Exhaust the 3 attempts to mark platform unavailable
    for _ in range(3):
        tracker.attempt_replacement(platform)

    assert tracker.is_unavailable(platform), (
        f"Platform '{platform}' should be unavailable after 3 attempts"
    )

    # All further attempts must return False
    for i in range(extra_attempts):
        result = tracker.attempt_replacement(platform)
        assert result is False, (
            f"Expected False for attempt {i + 4} after platform '{platform}' "
            f"is unavailable, but got {result}"
        )
