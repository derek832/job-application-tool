"""
Property-based tests for quiet hours notification queueing.

Uses Hypothesis to verify that ``is_quiet_hours()`` correctly identifies
whether a given time falls within configured quiet hours — for both
same-day ranges (e.g., 08:00–17:00) and overnight ranges (e.g., 22:00–07:00).

Properties tested:
- Property 9: Quiet Hours Notification Queueing
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from zoneinfo import ZoneInfo

from src.pipeline.quiet_hours import is_quiet_hours


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for valid IANA timezones (representative subset)
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

# Strategy for hours (0-23) and minutes (0-59)
hour_strategy = st.integers(min_value=0, max_value=23)
minute_strategy = st.integers(min_value=0, max_value=59)


def time_str(hour: int, minute: int) -> str:
    """Format hour and minute as HH:MM string."""
    return f"{hour:02d}:{minute:02d}"


def minutes_of_day(hour: int, minute: int) -> int:
    """Convert hour and minute to total minutes since midnight."""
    return hour * 60 + minute


# ---------------------------------------------------------------------------
# Property 9: Quiet Hours Notification Queueing — Same-Day Range
# ---------------------------------------------------------------------------


@given(
    start_hour=hour_strategy,
    start_minute=minute_strategy,
    end_hour=hour_strategy,
    end_minute=minute_strategy,
    test_hour=hour_strategy,
    test_minute=minute_strategy,
    timezone=timezone_strategy,
)
@settings(max_examples=200)
def test_same_day_range_quiet_hours(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    test_hour: int,
    test_minute: int,
    timezone: str,
) -> None:
    """
    For any same-day quiet hours range (start <= end), ``is_quiet_hours()``
    returns True if and only if the test time is >= start and < end.

    **Validates: Requirements 3.8**
    """
    start_minutes = minutes_of_day(start_hour, start_minute)
    end_minutes = minutes_of_day(end_hour, end_minute)

    # Only test same-day ranges (start <= end) and non-degenerate (start < end)
    assume(start_minutes < end_minutes)

    quiet_start = time_str(start_hour, start_minute)
    quiet_end = time_str(end_hour, end_minute)

    # Create a timezone-aware datetime at the test time
    tz = ZoneInfo(timezone)
    # Use a fixed date to avoid DST transition edge cases
    test_dt = datetime(2024, 6, 15, test_hour, test_minute, 0, tzinfo=tz)

    result = is_quiet_hours(test_dt, quiet_start, quiet_end, timezone)

    test_minutes = minutes_of_day(test_hour, test_minute)
    expected = start_minutes <= test_minutes < end_minutes

    assert result == expected, (
        f"Same-day range [{quiet_start}, {quiet_end}): "
        f"time {time_str(test_hour, test_minute)} "
        f"expected is_quiet_hours={expected}, got {result}"
    )


# ---------------------------------------------------------------------------
# Property 9: Quiet Hours Notification Queueing — Overnight Range
# ---------------------------------------------------------------------------


@given(
    start_hour=hour_strategy,
    start_minute=minute_strategy,
    end_hour=hour_strategy,
    end_minute=minute_strategy,
    test_hour=hour_strategy,
    test_minute=minute_strategy,
    timezone=timezone_strategy,
)
@settings(max_examples=200)
def test_overnight_range_quiet_hours(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    test_hour: int,
    test_minute: int,
    timezone: str,
) -> None:
    """
    For any overnight quiet hours range (start > end, e.g., 22:00–07:00),
    ``is_quiet_hours()`` returns True if and only if the test time is
    >= start OR < end.

    **Validates: Requirements 3.8**
    """
    start_minutes = minutes_of_day(start_hour, start_minute)
    end_minutes = minutes_of_day(end_hour, end_minute)

    # Only test overnight ranges (start > end)
    assume(start_minutes > end_minutes)

    quiet_start = time_str(start_hour, start_minute)
    quiet_end = time_str(end_hour, end_minute)

    # Create a timezone-aware datetime at the test time
    tz = ZoneInfo(timezone)
    # Use a fixed date to avoid DST transition edge cases
    test_dt = datetime(2024, 6, 15, test_hour, test_minute, 0, tzinfo=tz)

    result = is_quiet_hours(test_dt, quiet_start, quiet_end, timezone)

    test_minutes = minutes_of_day(test_hour, test_minute)
    expected = test_minutes >= start_minutes or test_minutes < end_minutes

    assert result == expected, (
        f"Overnight range [{quiet_start}, {quiet_end}): "
        f"time {time_str(test_hour, test_minute)} "
        f"expected is_quiet_hours={expected}, got {result}"
    )


# ---------------------------------------------------------------------------
# Property 9: Quiet Hours — None Configuration Returns False
# ---------------------------------------------------------------------------


@given(
    test_hour=hour_strategy,
    test_minute=minute_strategy,
    timezone=timezone_strategy,
    null_start=st.booleans(),
)
@settings(max_examples=100)
def test_none_quiet_hours_returns_false(
    test_hour: int,
    test_minute: int,
    timezone: str,
    null_start: bool,
) -> None:
    """
    When quiet hours are not configured (either start or end is None),
    ``is_quiet_hours()`` always returns False regardless of the current time.

    **Validates: Requirements 3.8**
    """
    tz = ZoneInfo(timezone)
    test_dt = datetime(2024, 6, 15, test_hour, test_minute, 0, tzinfo=tz)

    if null_start:
        result = is_quiet_hours(test_dt, None, "07:00", timezone)
    else:
        result = is_quiet_hours(test_dt, "22:00", None, timezone)

    assert result is False, (
        f"When quiet hours are not fully configured, is_quiet_hours() "
        f"must return False. Got True at {time_str(test_hour, test_minute)}"
    )
