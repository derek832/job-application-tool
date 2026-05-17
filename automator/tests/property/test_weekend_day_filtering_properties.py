"""
Property-based tests for weekend day filtering in the schedule manager.

Uses Hypothesis to verify that:
- When weekend_runs=False, no computed run time falls on Saturday (weekday=5)
  or Sunday (weekday=6).
- When weekend_runs=True, run times can include any day of the week.

Properties tested:
- Property 8: Weekend Day Filtering
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from src.scheduler.schedule_manager import (
    compute_next_run_times_specific,
    compute_next_run_times_interval,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for valid HH:MM time strings
time_str_strategy = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    h=st.integers(min_value=0, max_value=23),
    m=st.integers(min_value=0, max_value=59),
)

# Strategy for a list of valid times (1-5 entries, no duplicates)
times_list_strategy = st.lists(
    time_str_strategy,
    min_size=1,
    max_size=5,
    unique=True,
)

# Strategy for valid IANA timezones (use a representative subset)
timezone_strategy = st.sampled_from([
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Australia/Sydney",
    "UTC",
])

# Strategy for interval hours (1-12)
interval_hours_strategy = st.integers(min_value=1, max_value=12)

# Strategy for window start/end that form a valid window (start < end)
@st.composite
def window_strategy(draw):
    """Generate a valid window_start and window_end where start < end."""
    start_h = draw(st.integers(min_value=0, max_value=20))
    start_m = draw(st.integers(min_value=0, max_value=59))
    # Ensure end is at least 1 hour after start
    end_h = draw(st.integers(min_value=start_h + 1, max_value=23))
    end_m = draw(st.integers(min_value=0, max_value=59))
    return f"{start_h:02d}:{start_m:02d}", f"{end_h:02d}:{end_m:02d}"


# Strategy for reference datetimes (timezone-aware, within a reasonable range)
reference_datetime_strategy = st.builds(
    lambda year, month, day, hour, minute, tz_name: datetime(
        year, month, day, hour, minute, tzinfo=ZoneInfo(tz_name)
    ),
    year=st.just(2024),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),  # Use 28 to avoid month overflow
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    tz_name=timezone_strategy,
)


# ---------------------------------------------------------------------------
# Property 8: Weekend Day Filtering
# ---------------------------------------------------------------------------


@given(
    times=times_list_strategy,
    timezone=timezone_strategy,
    now=reference_datetime_strategy,
    count=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=150)
def test_specific_times_no_weekend_runs_excludes_weekends(
    times: list[str],
    timezone: str,
    now: datetime,
    count: int,
) -> None:
    """
    When weekend_runs=False, compute_next_run_times_specific() SHALL NOT
    return any datetime that falls on Saturday (weekday=5) or Sunday (weekday=6).

    **Validates: Requirements 3.4, 3.5, 3.6**
    """
    results = compute_next_run_times_specific(
        times=times,
        weekend_runs=False,
        timezone=timezone,
        now=now,
        count=count,
    )

    for run_time in results:
        # Convert to the target timezone to check the weekday
        tz = ZoneInfo(timezone)
        local_time = run_time.astimezone(tz)
        weekday = local_time.weekday()
        assert weekday < 5, (
            f"Expected no weekend runs when weekend_runs=False, but got "
            f"run_time={run_time} (local={local_time}, weekday={weekday}, "
            f"{'Saturday' if weekday == 5 else 'Sunday'}). "
            f"Config: times={times}, timezone={timezone}, now={now}"
        )


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    timezone=timezone_strategy,
    now=reference_datetime_strategy,
    count=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=150)
def test_interval_no_weekend_runs_excludes_weekends(
    interval_hours: int,
    window: tuple[str, str],
    timezone: str,
    now: datetime,
    count: int,
) -> None:
    """
    When weekend_runs=False, compute_next_run_times_interval() SHALL NOT
    return any datetime that falls on Saturday (weekday=5) or Sunday (weekday=6).

    **Validates: Requirements 3.4, 3.5, 3.6**
    """
    window_start, window_end = window

    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=False,
        timezone=timezone,
        now=now,
        count=count,
    )

    for run_time in results:
        tz = ZoneInfo(timezone)
        local_time = run_time.astimezone(tz)
        weekday = local_time.weekday()
        assert weekday < 5, (
            f"Expected no weekend runs when weekend_runs=False, but got "
            f"run_time={run_time} (local={local_time}, weekday={weekday}, "
            f"{'Saturday' if weekday == 5 else 'Sunday'}). "
            f"Config: interval_hours={interval_hours}, window={window_start}-{window_end}, "
            f"timezone={timezone}, now={now}"
        )


@given(
    times=st.lists(time_str_strategy, min_size=1, max_size=1, unique=True),
    timezone=timezone_strategy,
)
@settings(max_examples=150)
def test_specific_times_weekend_runs_enabled_can_include_any_day(
    times: list[str],
    timezone: str,
) -> None:
    """
    When weekend_runs=True, compute_next_run_times_specific() SHALL allow
    run times on any day of the week (0-6), including Saturday and Sunday.
    We verify this by starting from a Friday evening and confirming that
    weekend days appear in the results.

    **Validates: Requirements 3.4, 3.5, 3.6**
    """
    tz = ZoneInfo(timezone)
    # Start from a Friday at 23:59 so the next results must include Saturday/Sunday
    # 2024-01-05 is a Friday
    now = datetime(2024, 1, 5, 23, 59, tzinfo=tz)

    # Request enough results to span into the weekend
    results = compute_next_run_times_specific(
        times=times,
        weekend_runs=True,
        timezone=timezone,
        now=now,
        count=10,
    )

    assert len(results) > 0, "Expected at least one result"

    # All results should be in the future
    for run_time in results:
        local_time = run_time.astimezone(tz)
        assert local_time > now, (
            f"Expected all run times to be in the future, but got "
            f"run_time={local_time} which is not after now={now}"
        )

    # With weekend_runs=True and starting from Friday 23:59, the next day
    # is Saturday. With 1 time per day and 10 results, we span 10 days
    # which must include both Saturday and Sunday.
    weekdays_present = {r.astimezone(tz).weekday() for r in results}
    assert 5 in weekdays_present or 6 in weekdays_present, (
        f"Expected weekend days (5=Sat, 6=Sun) to be present when "
        f"weekend_runs=True, but only got weekdays {sorted(weekdays_present)}. "
        f"Config: times={times}, timezone={timezone}"
    )


@given(
    interval_hours=interval_hours_strategy,
    window=window_strategy(),
    timezone=timezone_strategy,
)
@settings(max_examples=150)
def test_interval_weekend_runs_enabled_can_include_any_day(
    interval_hours: int,
    window: tuple[str, str],
    timezone: str,
) -> None:
    """
    When weekend_runs=True, compute_next_run_times_interval() SHALL allow
    run times on any day of the week (0-6), including Saturday and Sunday.
    We verify this by starting from a Friday evening and confirming that
    weekend days appear in the results.

    **Validates: Requirements 3.4, 3.5, 3.6**
    """
    window_start, window_end = window
    tz = ZoneInfo(timezone)
    # Start from a Friday at 23:59 so the next results must include Saturday/Sunday
    # 2024-01-05 is a Friday
    now = datetime(2024, 1, 5, 23, 59, tzinfo=tz)

    # Request enough results to span into the weekend
    results = compute_next_run_times_interval(
        interval_hours=interval_hours,
        window_start=window_start,
        window_end=window_end,
        weekend_runs=True,
        timezone=timezone,
        now=now,
        count=10,
    )

    assert len(results) > 0, "Expected at least one result"

    # All results should be in the future
    for run_time in results:
        local_time = run_time.astimezone(tz)
        assert local_time > now, (
            f"Expected all run times to be in the future, but got "
            f"run_time={local_time} which is not after now={now}"
        )

    # With weekend_runs=True and starting from Friday 23:59, the next day
    # is Saturday. With 10 results spanning multiple days, weekend days
    # must appear.
    weekdays_present = {r.astimezone(tz).weekday() for r in results}
    assert 5 in weekdays_present or 6 in weekdays_present, (
        f"Expected weekend days (5=Sat, 6=Sun) to be present when "
        f"weekend_runs=True, but only got weekdays {sorted(weekdays_present)}. "
        f"Config: interval_hours={interval_hours}, window={window_start}-{window_end}, "
        f"timezone={timezone}"
    )
