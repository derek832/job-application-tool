"""
Property-based tests for specific times schedule correctness.

Uses Hypothesis to verify that compute_next_run_times_specific() always
produces run times that:
- Correspond to one of the N configured times (matching hour and minute)
- Are in strictly ascending chronological order
- Are all in the future relative to the reference datetime

Properties tested:
- Property 6: Specific Times Schedule Correctness
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from src.scheduler.schedule_manager import compute_next_run_times_specific


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate valid HH:MM time strings
valid_time_strategy = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    h=st.integers(min_value=0, max_value=23),
    m=st.integers(min_value=0, max_value=59),
)

# Generate lists of 1-10 unique valid HH:MM times
times_list_strategy = st.lists(
    valid_time_strategy,
    min_size=1,
    max_size=10,
    unique=True,
)

# Generate timezone-aware reference datetimes within a reasonable range
# Use a fixed timezone for the reference datetime to avoid edge cases with
# naive datetimes
reference_datetime_strategy = st.builds(
    lambda dt, tz: dt.replace(tzinfo=tz),
    dt=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
    ),
    tz=st.just(ZoneInfo("America/New_York")),
)

# Weekend runs toggle
weekend_runs_strategy = st.booleans()

# Count of results to request (1-10)
count_strategy = st.integers(min_value=1, max_value=10)


# ---------------------------------------------------------------------------
# Property 6: Specific Times Schedule Correctness
# ---------------------------------------------------------------------------


@given(
    times=times_list_strategy,
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
    count=count_strategy,
)
@settings(max_examples=200)
def test_specific_times_results_match_configured_times(
    times: list[str],
    now: datetime,
    weekend_runs: bool,
    count: int,
) -> None:
    """
    For any valid schedule configuration in "specific_times" mode with N
    configured times, each computed next run time SHALL correspond to one of
    the N configured times (matching hour and minute).

    **Validates: Requirements 3.1**
    """
    results = compute_next_run_times_specific(
        times=times,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=count,
    )

    # Parse configured times into (hour, minute) tuples
    configured_hm = set()
    for t in times:
        h, m = map(int, t.split(":"))
        configured_hm.add((h, m))

    # Each result must match one of the configured times
    for result in results:
        result_hm = (result.hour, result.minute)
        assert result_hm in configured_hm, (
            f"Result time {result.hour:02d}:{result.minute:02d} does not match "
            f"any configured time. Configured: {sorted(configured_hm)}, "
            f"Got result: {result}"
        )


@given(
    times=times_list_strategy,
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
    count=count_strategy,
)
@settings(max_examples=200)
def test_specific_times_results_strictly_ascending(
    times: list[str],
    now: datetime,
    weekend_runs: bool,
    count: int,
) -> None:
    """
    For any valid schedule configuration in "specific_times" mode, the computed
    next run times SHALL be in strictly ascending chronological order.

    **Validates: Requirements 3.1**
    """
    results = compute_next_run_times_specific(
        times=times,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=count,
    )

    # Results must be in strictly ascending order
    for i in range(1, len(results)):
        assert results[i] > results[i - 1], (
            f"Results not in strictly ascending order at index {i}: "
            f"{results[i - 1]} >= {results[i]}. "
            f"Full results: {results}"
        )


@given(
    times=times_list_strategy,
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
    count=count_strategy,
)
@settings(max_examples=200)
def test_specific_times_results_all_in_future(
    times: list[str],
    now: datetime,
    weekend_runs: bool,
    count: int,
) -> None:
    """
    For any valid schedule configuration in "specific_times" mode and a given
    reference datetime, all computed next run times SHALL be in the future
    relative to the reference datetime.

    **Validates: Requirements 3.1**
    """
    results = compute_next_run_times_specific(
        times=times,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=count,
    )

    # Normalize now to the same timezone for comparison
    tz = ZoneInfo("America/New_York")
    now_local = now.astimezone(tz)

    # All results must be strictly in the future
    for result in results:
        assert result > now_local, (
            f"Result {result} is not in the future relative to "
            f"reference datetime {now_local}. "
            f"Configured times: {times}"
        )
