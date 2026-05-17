"""
Property-based tests for schedule validation rejecting zero times.

Uses Hypothesis to verify that validate_schedule_config() rejects
configurations in "specific_times" mode with an empty times list,
and also rejects invalid time formats.

Properties tested:
- Property 11: Schedule Validation Rejects Zero Times
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.scheduler.schedule_manager import ScheduleConfig, validate_schedule_config


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid IANA timezones commonly used
_valid_timezones = st.sampled_from([
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
    "UTC",
])

# Strategy for valid HH:MM time strings
_valid_time_strategy = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    h=st.integers(min_value=0, max_value=23),
    m=st.integers(min_value=0, max_value=59),
)

# Strategy for invalid time format strings — things that don't match HH:MM (00:00-23:59)
_invalid_time_format_strategy = st.one_of(
    # Missing colon
    st.from_regex(r"^[0-9]{4}$", fullmatch=True),
    # Single digit hour
    st.builds(lambda m: f"9:{m:02d}", m=st.integers(min_value=0, max_value=59)),
    # Hour out of range (24-99)
    st.builds(lambda h, m: f"{h}:{m:02d}", h=st.integers(min_value=24, max_value=99), m=st.integers(min_value=0, max_value=59)),
    # Minute out of range (60-99)
    st.builds(lambda h, m: f"{h:02d}:{m}", h=st.integers(min_value=0, max_value=23), m=st.integers(min_value=60, max_value=99)),
    # Random non-time strings
    st.sampled_from(["", "noon", "12pm", "25:00", "12:60", "abc", "1:30", "12:5", "24:00"]),
    # Letters mixed in
    st.from_regex(r"^[a-z]{2}:[0-9]{2}$", fullmatch=True),
)

# Strategy for weekend_runs boolean
_weekend_runs_strategy = st.booleans()

# Strategy for interval_hours (valid range)
_interval_hours_strategy = st.integers(min_value=1, max_value=12)


# ---------------------------------------------------------------------------
# Property 11: Schedule Validation Rejects Zero Times
# ---------------------------------------------------------------------------


@given(
    timezone=_valid_timezones,
    weekend_runs=_weekend_runs_strategy,
    quiet_hours_start=st.one_of(st.none(), _valid_time_strategy),
    quiet_hours_end=st.one_of(st.none(), _valid_time_strategy),
)
@settings(max_examples=150)
def test_specific_times_mode_with_empty_times_raises_value_error(
    timezone: str,
    weekend_runs: bool,
    quiet_hours_start: str | None,
    quiet_hours_end: str | None,
) -> None:
    """
    For any schedule configuration in "specific_times" mode with an empty
    times list, validate_schedule_config() SHALL raise a ValueError.
    The scheduler shall not be modified.

    **Validates: Requirements 3.12**
    """
    config = ScheduleConfig(
        mode="specific_times",
        times=[],  # Empty times list — must be rejected
        weekend_runs=weekend_runs,
        timezone=timezone,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )

    with pytest.raises(ValueError, match="[Aa]t least one time"):
        validate_schedule_config(config)


@given(
    invalid_time=_invalid_time_format_strategy,
    other_valid_times=st.lists(_valid_time_strategy, min_size=0, max_size=3),
    timezone=_valid_timezones,
    weekend_runs=_weekend_runs_strategy,
)
@settings(max_examples=150)
def test_specific_times_mode_with_invalid_time_format_raises_value_error(
    invalid_time: str,
    other_valid_times: list[str],
    timezone: str,
    weekend_runs: bool,
) -> None:
    """
    For any schedule configuration in "specific_times" mode containing an
    invalid time format string, validate_schedule_config() SHALL raise a
    ValueError indicating the invalid format.

    **Validates: Requirements 3.12**
    """
    # Include the invalid time among potentially valid ones
    times = other_valid_times + [invalid_time]

    config = ScheduleConfig(
        mode="specific_times",
        times=times,
        weekend_runs=weekend_runs,
        timezone=timezone,
    )

    with pytest.raises(ValueError, match="[Ii]nvalid time format"):
        validate_schedule_config(config)


@given(
    times=st.lists(_valid_time_strategy, min_size=1, max_size=5),
    timezone=_valid_timezones,
    weekend_runs=_weekend_runs_strategy,
    quiet_hours_start=st.one_of(st.none(), _valid_time_strategy),
    quiet_hours_end=st.one_of(st.none(), _valid_time_strategy),
)
@settings(max_examples=150)
def test_specific_times_mode_with_valid_times_does_not_raise(
    times: list[str],
    timezone: str,
    weekend_runs: bool,
    quiet_hours_start: str | None,
    quiet_hours_end: str | None,
) -> None:
    """
    For any schedule configuration in "specific_times" mode with at least one
    valid time, validate_schedule_config() SHALL NOT raise a ValueError.
    This is the complement property — valid configs pass validation.

    **Validates: Requirements 3.12**
    """
    config = ScheduleConfig(
        mode="specific_times",
        times=times,
        weekend_runs=weekend_runs,
        timezone=timezone,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )

    # Should not raise — valid configuration
    validate_schedule_config(config)
