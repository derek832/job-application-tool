"""
Property-based tests for patch retry discard logic.

Uses Hypothesis to verify correctness properties of the PatchRetryTracker
class in src/pipeline/fix_cycle_manager.py.

Properties tested:
- Property 7: Patch Retry Discard After Two Failures
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.fix_cycle_manager import PatchRetryTracker


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for platform names
platform_strategy = st.sampled_from(
    ["greenhouse", "lever", "workday", "icims", "bamboohr"]
)

# Strategy for root cause strings
root_cause_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
)

# Strategy for patch outcome sequences (False=failure, True=success)
patch_outcomes_strategy = st.lists(st.booleans(), min_size=1, max_size=10)


# ---------------------------------------------------------------------------
# Property 7: Patch Retry Discard After Two Failures
# ---------------------------------------------------------------------------


@given(
    platform=platform_strategy,
    root_cause=root_cause_strategy,
    outcomes=patch_outcomes_strategy,
)
@settings(max_examples=200)
def test_discard_after_two_failures_at_same_root_cause(
    platform: str,
    root_cause: str,
    outcomes: list[bool],
) -> None:
    """
    For any sequence of patch outcomes targeting the same root cause,
    after 2 failures the system returns "discard_and_rediagnose".

    **Validates: Requirements 5.3**
    """
    tracker = PatchRetryTracker()
    failure_count = 0

    for success in outcomes:
        result = tracker.record_patch_attempt(platform, root_cause, success)

        if success:
            assert result == "resolved", (
                f"Expected 'resolved' for successful patch, got '{result}'"
            )
        else:
            failure_count += 1
            if failure_count >= 2:
                assert result == "discard_and_rediagnose", (
                    f"Expected 'discard_and_rediagnose' after {failure_count} "
                    f"failures, got '{result}'"
                )
            else:
                assert result == "continue", (
                    f"Expected 'continue' after {failure_count} failure(s), "
                    f"got '{result}'"
                )


@given(
    platform=platform_strategy,
    root_cause=root_cause_strategy,
)
@settings(max_examples=200)
def test_first_failure_returns_continue(
    platform: str,
    root_cause: str,
) -> None:
    """
    The first failure at any root cause always returns "continue",
    indicating more attempts are allowed.

    **Validates: Requirements 5.3**
    """
    tracker = PatchRetryTracker()
    result = tracker.record_patch_attempt(platform, root_cause, False)
    assert result == "continue", (
        f"Expected 'continue' for first failure, got '{result}'"
    )


@given(
    platform=platform_strategy,
    root_cause=root_cause_strategy,
)
@settings(max_examples=200)
def test_success_always_returns_resolved(
    platform: str,
    root_cause: str,
) -> None:
    """
    A successful patch always returns "resolved" regardless of prior failures.

    **Validates: Requirements 5.3**
    """
    tracker = PatchRetryTracker()

    # Even after one failure, a success returns "resolved"
    tracker.record_patch_attempt(platform, root_cause, False)
    result = tracker.record_patch_attempt(platform, root_cause, True)
    assert result == "resolved", (
        f"Expected 'resolved' for successful patch after 1 failure, got '{result}'"
    )


@given(
    platform=platform_strategy,
    root_cause=root_cause_strategy,
    extra_failures=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=200)
def test_never_returns_continue_after_two_failures(
    platform: str,
    root_cause: str,
    extra_failures: int,
) -> None:
    """
    After 2 failures at the same root cause, no subsequent failure
    at that root cause ever returns "continue". The system never
    attempts a third patch at the same root cause without re-diagnosing.

    **Validates: Requirements 5.3**
    """
    tracker = PatchRetryTracker()

    # Record 2 failures to trigger discard
    tracker.record_patch_attempt(platform, root_cause, False)
    result = tracker.record_patch_attempt(platform, root_cause, False)
    assert result == "discard_and_rediagnose"

    # Any further failures at the same root cause must never return "continue"
    for i in range(extra_failures):
        result = tracker.record_patch_attempt(platform, root_cause, False)
        assert result != "continue", (
            f"Expected 'discard_and_rediagnose' for failure {i + 3} at same "
            f"root cause, but got '{result}' — system should never allow a "
            f"third patch without re-diagnosing"
        )
