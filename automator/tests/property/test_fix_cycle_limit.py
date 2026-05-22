"""
Property-based tests for fix cycle limit enforcement.

Uses Hypothesis to verify correctness properties of the FixCycleManager
class in src/pipeline/fix_cycle_manager.py.

Properties tested:
- Property 8: Fix Cycle Limit Enforcement
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.fix_cycle_manager import FixCycleManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for platform names (simple ASCII identifiers)
platform_strategy = st.sampled_from(
    ["greenhouse", "lever", "workday", "icims", "bamboohr"]
)

# Strategy for sequences of fix cycle attempts (up to 10 attempts)
cycle_attempts_strategy = st.lists(st.booleans(), max_size=10)


# ---------------------------------------------------------------------------
# Property 8: Fix Cycle Limit Enforcement
# ---------------------------------------------------------------------------


@given(
    platform=platform_strategy,
    attempts=cycle_attempts_strategy,
)
@settings(max_examples=200)
def test_consume_cycle_returns_true_at_most_5_times(
    platform: str,
    attempts: list[bool],
) -> None:
    """
    For any platform and any sequence of fix cycle attempts,
    consume_cycle returns True at most 5 times. The total number
    of successful consumptions never exceeds MAX_CYCLES (5).

    **Validates: Requirements 5.5, 5.6**
    """
    manager = FixCycleManager()
    success_count = 0

    for _ in attempts:
        result = manager.consume_cycle(platform)
        if result:
            success_count += 1

    assert success_count <= 5, (
        f"Expected at most 5 successful cycle consumptions, but got "
        f"{success_count} for platform='{platform}' with {len(attempts)} attempts"
    )


@given(
    platform=platform_strategy,
    attempts=cycle_attempts_strategy,
)
@settings(max_examples=200)
def test_is_exhausted_after_5_cycles(
    platform: str,
    attempts: list[bool],
) -> None:
    """
    For any platform, after 5 successful cycle consumptions,
    is_exhausted(platform) returns True, indicating the platform
    should be marked as "fail".

    **Validates: Requirements 5.5, 5.6**
    """
    manager = FixCycleManager()
    success_count = 0

    for _ in attempts:
        result = manager.consume_cycle(platform)
        if result:
            success_count += 1

    if success_count >= 5:
        assert manager.is_exhausted(platform), (
            f"Expected platform '{platform}' to be exhausted after "
            f"{success_count} successful cycles, but is_exhausted returned False"
        )


@given(
    platform=platform_strategy,
    attempts=cycle_attempts_strategy,
)
@settings(max_examples=200)
def test_cycles_used_never_exceeds_5(
    platform: str,
    attempts: list[bool],
) -> None:
    """
    For any platform and any sequence of fix cycle attempts,
    cycles_used() never exceeds 5 regardless of how many times
    consume_cycle is called.

    **Validates: Requirements 5.5, 5.6**
    """
    manager = FixCycleManager()

    for _ in attempts:
        manager.consume_cycle(platform)

    assert manager.cycles_used(platform) <= 5, (
        f"Expected cycles_used <= 5, but got {manager.cycles_used(platform)} "
        f"for platform='{platform}' with {len(attempts)} attempts"
    )
