"""
Property-based tests for interval schedule correctness.

Uses Hypothesis to verify that compute_next_run_times_interval() always produces
run times that fall within the configured time window and are exactly N hours
apart on the same day.

Properties tested:
- Property 7: Interval Schedule Correctness
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from src.scheduler.schedule_manager import compute_next_run_times_interval


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid interval hours (1-12)
interval_hours_strategy = st.integers(min_value=1, max_value=12)

# Valid hour values for window boundaries (0-23)
hour_strategy = st.integers(min_value=0, max_value=23)


@st.composite
def window_strategy(draw: st.DrawFn) -> tuple[str, str]:
    """Generate valid window_start and window_end where start < end.

    We ensure at least 1 hour gap so there's room for at least one run time.
    """
    start_hour = draw(st.integers(min_value=0, max_value=21))
    # End hour must be at least 1 hour after start
    end_hour = draw(st.integers(min_value=start_hour + 1, max_value=23))
    start_minute = draw(st.sampled_from([0, 15, 30, 45]))
    end_minute = draw(st.sampled_from([0, 15, 30, 45]))

    # Ensure end is actually after start in total minutes
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        end_minute = 0  # Reset to ensure end > start

    window_start = f"{start_hour:02d}:{start_minute:02d}"
    window_end = f"{end_hour:02d}:{end_minute:02d}"
    return window_start, window_end


# Reference datetimes — use a fixed timezone to avoid DST edge cases in tests
reference_datetime_strategy = st.builds(
    lambda year, month, day, hour, minute: datetime(
        year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York")
    ),
    year=st.just(2024),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),  # Avoid month-end issues
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)

weekend_runs_strategy = st.booleans()


# ---------------------------------------------------------------------------
# Property 7: Interval Schedule Correctness
# ---------------------------------------------------------------------------


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
)
@settings(max_examples=200)
def test_interval_run_times_fall_within_window(
    interval_hours: int,
    window: tuple[str, str],
    now: datetime,
    weekend_runs: bool,
) -> None:
    """
    For any valid schedule configuration in "interval" mode with interval N hours
    and window [start, end], all computed run times SHALL fall within the configured
    time window (hour >= window_start_hour and the time is <= window_end time).

    **Validates: Requirements 3.2**
    """
    window_start, window_end = window
    start_h, start_m = map(int, window_start.split(":"))
    end_h, end_m = map(int, window_end.split(":"))

    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=5,
    )

    start_total_minutes = start_h * 60 + start_m
    end_total_minutes = end_h * 60 + end_m

    for run_time in results:
        run_total_minutes = run_time.hour * 60 + run_time.minute
        assert run_total_minutes >= start_total_minutes, (
            f"Run time {run_time} (minute {run_total_minutes}) is before "
            f"window_start {window_start} (minute {start_total_minutes})"
        )
        assert run_total_minutes <= end_total_minutes, (
            f"Run time {run_time} (minute {run_total_minutes}) is after "
            f"window_end {window_end} (minute {end_total_minutes})"
        )


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
)
@settings(max_examples=200)
def test_interval_consecutive_same_day_runs_are_n_hours_apart(
    interval_hours: int,
    window: tuple[str, str],
    now: datetime,
    weekend_runs: bool,
) -> None:
    """
    For any valid schedule configuration in "interval" mode with interval N hours,
    consecutive run times on the same day SHALL be exactly N hours apart.

    **Validates: Requirements 3.2**
    """
    window_start, window_end = window

    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=10,
    )

    # Group results by date
    by_date: dict[str, list[datetime]] = {}
    for run_time in results:
        date_key = run_time.strftime("%Y-%m-%d")
        by_date.setdefault(date_key, []).append(run_time)

    # For each day with multiple runs, check consecutive spacing
    for date_key, day_runs in by_date.items():
        if len(day_runs) < 2:
            continue
        sorted_runs = sorted(day_runs)
        for i in range(1, len(sorted_runs)):
            diff = sorted_runs[i] - sorted_runs[i - 1]
            expected_diff = timedelta(hours=interval_hours)
            assert diff == expected_diff, (
                f"On {date_key}, consecutive runs {sorted_runs[i-1]} and "
                f"{sorted_runs[i]} are {diff} apart, expected {expected_diff}"
            )


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
)
@settings(max_examples=200)
def test_interval_run_times_are_in_the_future(
    interval_hours: int,
    window: tuple[str, str],
    now: datetime,
    weekend_runs: bool,
) -> None:
    """
    For any valid schedule configuration in "interval" mode, all computed run
    times SHALL be strictly in the future relative to the reference datetime.

    **Validates: Requirements 3.2**
    """
    window_start, window_end = window

    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=5,
    )

    tz = ZoneInfo("America/New_York")
    now_local = now.astimezone(tz)

    for run_time in results:
        assert run_time > now_local, (
            f"Run time {run_time} is not in the future relative to now={now_local}"
        )


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    now=reference_datetime_strategy,
    weekend_runs=weekend_runs_strategy,
)
@settings(max_examples=200)
def test_interval_run_times_are_in_ascending_order(
    interval_hours: int,
    window: tuple[str, str],
    now: datetime,
    weekend_runs: bool,
) -> None:
    """
    For any valid schedule configuration in "interval" mode, the computed run
    times SHALL be in strictly ascending chronological order.

    **Validates: Requirements 3.2**
    """
    window_start, window_end = window

    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=weekend_runs,
        timezone="America/New_York",
        now=now,
        count=5,
    )

    for i in range(1, len(results)):
        assert results[i] > results[i - 1], (
            f"Run times not in ascending order: {results[i-1]} >= {results[i]}"
        )
