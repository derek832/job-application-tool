"""
Property-based tests for Freshness Tier and Timeout Calculation.

Uses Hypothesis to verify that calculate_freshness_tier() assigns exactly one
tier based on posting age, and calculate_timeout_deadline() returns the correct
duration for each tier.

Properties tested:
- Property 4: Freshness Tier and Timeout Calculation

Feature: human-in-the-loop-escalation, Property 4: Freshness Tier and Timeout Calculation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.escalation_engine import (
    TIMEOUT_BY_FRESHNESS,
    FreshnessTier,
    calculate_freshness_tier,
    calculate_timeout_deadline,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a "now" reference time — fixed to avoid flakiness from real clock
# Use a range of realistic reference times across 2024
reference_now_strategy = st.builds(
    lambda month, day, hour, minute, second: datetime(
        2024, month, day, hour, minute, second, tzinfo=UTC
    ),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),  # Avoid month-end issues
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)

# Age in seconds for FRESH tier: 0 to just under 24 hours
fresh_age_strategy = st.floats(
    min_value=0.0,
    max_value=24 * 3600 - 1,
    allow_nan=False,
    allow_infinity=False,
)

# Age in seconds for RECENT tier: exactly 24 hours to exactly 7 days
recent_age_strategy = st.floats(
    min_value=24 * 3600,
    max_value=7 * 24 * 3600,
    allow_nan=False,
    allow_infinity=False,
)

# Age in seconds for STALE tier: more than 7 days (up to 365 days)
stale_age_strategy = st.floats(
    min_value=7 * 24 * 3600 + 1,
    max_value=365 * 24 * 3600,
    allow_nan=False,
    allow_infinity=False,
)

# Any valid age (0 to 365 days)
any_age_strategy = st.floats(
    min_value=0.0,
    max_value=365 * 24 * 3600,
    allow_nan=False,
    allow_infinity=False,
)

# Strategy for FreshnessTier enum values
freshness_tier_strategy = st.sampled_from(list(FreshnessTier))


# ---------------------------------------------------------------------------
# Property 4: Freshness Tier and Timeout Calculation
# ---------------------------------------------------------------------------


@given(
    now=reference_now_strategy,
    age_seconds=any_age_strategy,
)
@settings(max_examples=200)
def test_every_timestamp_maps_to_exactly_one_tier(
    now: datetime,
    age_seconds: float,
) -> None:
    """
    For any ISO 8601 timestamp representing a job's discovered_at value,
    the freshness calculation should assign exactly one tier from the set
    {FRESH, RECENT, STALE}.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    """
    discovered_at = (now - timedelta(seconds=age_seconds)).isoformat()

    with patch(
        "src.pipeline.escalation_engine.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = now
        mock_datetime.fromisoformat = datetime.fromisoformat
        tier = calculate_freshness_tier(discovered_at)

    # Must be exactly one of the three tiers
    assert tier in (FreshnessTier.FRESH, FreshnessTier.RECENT, FreshnessTier.STALE), (
        f"Tier {tier} is not a valid FreshnessTier"
    )


@given(
    now=reference_now_strategy,
    age_seconds=fresh_age_strategy,
)
@settings(max_examples=200)
def test_fresh_tier_assigned_for_age_less_than_24_hours(
    now: datetime,
    age_seconds: float,
) -> None:
    """
    For any timestamp with age less than 24 hours, the freshness calculation
    should assign the FRESH tier.

    **Validates: Requirements 4.1, 4.5**
    """
    discovered_at = (now - timedelta(seconds=age_seconds)).isoformat()

    with patch(
        "src.pipeline.escalation_engine.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = now
        mock_datetime.fromisoformat = datetime.fromisoformat
        tier = calculate_freshness_tier(discovered_at)

    assert tier == FreshnessTier.FRESH, (
        f"Age {age_seconds/3600:.2f}h should be FRESH, got {tier.value}"
    )


@given(
    now=reference_now_strategy,
    age_seconds=recent_age_strategy,
)
@settings(max_examples=200)
def test_recent_tier_assigned_for_age_between_24h_and_7d(
    now: datetime,
    age_seconds: float,
) -> None:
    """
    For any timestamp with age between 24 hours and 7 days (inclusive),
    the freshness calculation should assign the RECENT tier.

    **Validates: Requirements 4.2, 4.5**
    """
    discovered_at = (now - timedelta(seconds=age_seconds)).isoformat()

    with patch(
        "src.pipeline.escalation_engine.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = now
        mock_datetime.fromisoformat = datetime.fromisoformat
        tier = calculate_freshness_tier(discovered_at)

    assert tier == FreshnessTier.RECENT, (
        f"Age {age_seconds/3600:.2f}h should be RECENT, got {tier.value}"
    )


@given(
    now=reference_now_strategy,
    age_seconds=stale_age_strategy,
)
@settings(max_examples=200)
def test_stale_tier_assigned_for_age_more_than_7_days(
    now: datetime,
    age_seconds: float,
) -> None:
    """
    For any timestamp with age more than 7 days, the freshness calculation
    should assign the STALE tier.

    **Validates: Requirements 4.3, 4.5**
    """
    discovered_at = (now - timedelta(seconds=age_seconds)).isoformat()

    with patch(
        "src.pipeline.escalation_engine.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = now
        mock_datetime.fromisoformat = datetime.fromisoformat
        tier = calculate_freshness_tier(discovered_at)

    assert tier == FreshnessTier.STALE, (
        f"Age {age_seconds/3600:.2f}h should be STALE, got {tier.value}"
    )


@given(freshness=freshness_tier_strategy)
@settings(max_examples=100)
def test_timeout_duration_matches_tier(
    freshness: FreshnessTier,
) -> None:
    """
    For each freshness tier, the timeout should be exactly:
    - FRESH: 45 minutes
    - RECENT: 6 hours
    - STALE: 24 hours

    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    expected_timeouts = {
        FreshnessTier.FRESH: timedelta(minutes=45),
        FreshnessTier.RECENT: timedelta(hours=6),
        FreshnessTier.STALE: timedelta(hours=24),
    }

    # Verify the TIMEOUT_BY_FRESHNESS mapping is correct
    assert TIMEOUT_BY_FRESHNESS[freshness] == expected_timeouts[freshness], (
        f"Timeout for {freshness.value} should be {expected_timeouts[freshness]}, "
        f"got {TIMEOUT_BY_FRESHNESS[freshness]}"
    )


@given(
    freshness=freshness_tier_strategy,
    now=reference_now_strategy,
)
@settings(max_examples=200)
def test_deadline_is_always_in_the_future(
    freshness: FreshnessTier,
    now: datetime,
) -> None:
    """
    For any freshness tier, the calculated timeout deadline should always be
    in the future relative to "now" (the time of calculation).

    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    with patch(
        "src.pipeline.escalation_engine.datetime",
        wraps=datetime,
    ) as mock_datetime:
        mock_datetime.now.return_value = now
        deadline = calculate_timeout_deadline(freshness)

    assert deadline > now, (
        f"Deadline {deadline} should be in the future relative to now={now}"
    )

    # Also verify the deadline is exactly the expected duration from now
    expected_duration = TIMEOUT_BY_FRESHNESS[freshness]
    expected_deadline = now + expected_duration
    assert deadline == expected_deadline, (
        f"Deadline {deadline} should be {expected_deadline} "
        f"(now + {expected_duration})"
    )
