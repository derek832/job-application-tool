"""Unit tests for the Escalation Engine — Freshness Tier calculator.

Tests specific examples and boundary conditions for:
- FreshnessTier enum values
- TIMEOUT_BY_FRESHNESS mapping
- calculate_freshness_tier() function
- calculate_timeout_deadline() function

Validates: Requirements 4.1, 4.2, 4.3, 4.5
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.pipeline.escalation_engine import (
    TIMEOUT_BY_FRESHNESS,
    FreshnessTier,
    calculate_freshness_tier,
    calculate_timeout_deadline,
)


# ---------------------------------------------------------------------------
# FreshnessTier enum
# ---------------------------------------------------------------------------


class TestFreshnessTierEnum:
    """Verify FreshnessTier enum structure and values."""

    def test_fresh_value(self) -> None:
        assert FreshnessTier.FRESH.value == "fresh"

    def test_recent_value(self) -> None:
        assert FreshnessTier.RECENT.value == "recent"

    def test_stale_value(self) -> None:
        assert FreshnessTier.STALE.value == "stale"

    def test_is_string_enum(self) -> None:
        """FreshnessTier should be usable as a string."""
        assert isinstance(FreshnessTier.FRESH, str)
        assert FreshnessTier.FRESH == "fresh"

    def test_has_exactly_three_members(self) -> None:
        assert len(FreshnessTier) == 3


# ---------------------------------------------------------------------------
# TIMEOUT_BY_FRESHNESS mapping
# ---------------------------------------------------------------------------


class TestTimeoutByFreshness:
    """Verify timeout durations match requirements."""

    def test_fresh_timeout_is_45_minutes(self) -> None:
        """Requirement 4.1: Fresh → 45 minute timeout."""
        assert TIMEOUT_BY_FRESHNESS[FreshnessTier.FRESH] == timedelta(minutes=45)

    def test_recent_timeout_is_6_hours(self) -> None:
        """Requirement 4.2: Recent → 6 hour timeout."""
        assert TIMEOUT_BY_FRESHNESS[FreshnessTier.RECENT] == timedelta(hours=6)

    def test_stale_timeout_is_24_hours(self) -> None:
        """Requirement 4.3: Stale → 24 hour timeout."""
        assert TIMEOUT_BY_FRESHNESS[FreshnessTier.STALE] == timedelta(hours=24)

    def test_all_tiers_have_timeouts(self) -> None:
        """Every tier must have a corresponding timeout."""
        for tier in FreshnessTier:
            assert tier in TIMEOUT_BY_FRESHNESS


# ---------------------------------------------------------------------------
# calculate_freshness_tier()
# ---------------------------------------------------------------------------


class TestCalculateFreshnessTier:
    """Test freshness tier calculation from discovered_at timestamps."""

    def test_one_hour_ago_is_fresh(self) -> None:
        """A job discovered 1 hour ago should be FRESH."""
        one_hour_ago = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
        assert calculate_freshness_tier(one_hour_ago) == FreshnessTier.FRESH

    def test_23_hours_59_minutes_is_fresh(self) -> None:
        """Just under 24 hours should still be FRESH."""
        almost_24h = (
            datetime.now(tz=UTC) - timedelta(hours=23, minutes=59)
        ).isoformat()
        assert calculate_freshness_tier(almost_24h) == FreshnessTier.FRESH

    def test_exactly_24_hours_is_recent(self) -> None:
        """Exactly 24 hours should be RECENT (boundary)."""
        exactly_24h = (datetime.now(tz=UTC) - timedelta(hours=24)).isoformat()
        assert calculate_freshness_tier(exactly_24h) == FreshnessTier.RECENT

    def test_3_days_ago_is_recent(self) -> None:
        """3 days old should be RECENT."""
        three_days = (datetime.now(tz=UTC) - timedelta(days=3)).isoformat()
        assert calculate_freshness_tier(three_days) == FreshnessTier.RECENT

    def test_just_under_7_days_is_recent(self) -> None:
        """Just under 7 days should still be RECENT (boundary)."""
        just_under_7d = (
            datetime.now(tz=UTC) - timedelta(days=6, hours=23, minutes=59)
        ).isoformat()
        assert calculate_freshness_tier(just_under_7d) == FreshnessTier.RECENT

    def test_7_days_and_1_second_is_stale(self) -> None:
        """Just over 7 days should be STALE."""
        over_7_days = (
            datetime.now(tz=UTC) - timedelta(days=7, seconds=1)
        ).isoformat()
        assert calculate_freshness_tier(over_7_days) == FreshnessTier.STALE

    def test_30_days_ago_is_stale(self) -> None:
        """30 days old should be STALE."""
        thirty_days = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        assert calculate_freshness_tier(thirty_days) == FreshnessTier.STALE

    def test_naive_timestamp_treated_as_utc(self) -> None:
        """Timestamps without timezone info should be treated as UTC."""
        one_hour_ago = (datetime.now(tz=UTC) - timedelta(hours=1)).replace(
            tzinfo=None
        )
        # Format without timezone suffix
        naive_iso = one_hour_ago.strftime("%Y-%m-%dT%H:%M:%S")
        assert calculate_freshness_tier(naive_iso) == FreshnessTier.FRESH

    def test_timezone_aware_timestamp(self) -> None:
        """Timestamps with explicit timezone should be handled correctly."""
        # 2 hours ago in UTC, expressed with +00:00
        two_hours_ago = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
        assert calculate_freshness_tier(two_hours_ago) == FreshnessTier.FRESH

    def test_just_discovered_is_fresh(self) -> None:
        """A job discovered right now should be FRESH."""
        now = datetime.now(tz=UTC).isoformat()
        assert calculate_freshness_tier(now) == FreshnessTier.FRESH


# ---------------------------------------------------------------------------
# calculate_timeout_deadline()
# ---------------------------------------------------------------------------


class TestCalculateTimeoutDeadline:
    """Test timeout deadline calculation from freshness tier."""

    def test_fresh_deadline_is_45_minutes_from_now(self) -> None:
        """Requirement 4.1: FRESH → deadline 45 minutes from now."""
        fixed_now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        with patch(
            "src.pipeline.escalation_engine.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat = datetime.fromisoformat
            deadline = calculate_timeout_deadline(FreshnessTier.FRESH)

        expected = fixed_now + timedelta(minutes=45)
        assert deadline == expected

    def test_recent_deadline_is_6_hours_from_now(self) -> None:
        """Requirement 4.2: RECENT → deadline 6 hours from now."""
        fixed_now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        with patch(
            "src.pipeline.escalation_engine.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat = datetime.fromisoformat
            deadline = calculate_timeout_deadline(FreshnessTier.RECENT)

        expected = fixed_now + timedelta(hours=6)
        assert deadline == expected

    def test_stale_deadline_is_24_hours_from_now(self) -> None:
        """Requirement 4.3: STALE → deadline 24 hours from now."""
        fixed_now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        with patch(
            "src.pipeline.escalation_engine.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat = datetime.fromisoformat
            deadline = calculate_timeout_deadline(FreshnessTier.STALE)

        expected = fixed_now + timedelta(hours=24)
        assert deadline == expected

    def test_deadline_is_timezone_aware(self) -> None:
        """Deadline should always be timezone-aware (UTC)."""
        deadline = calculate_timeout_deadline(FreshnessTier.FRESH)
        assert deadline.tzinfo is not None

    def test_deadline_is_in_the_future(self) -> None:
        """Deadline should always be after the current time."""
        before = datetime.now(tz=UTC)
        deadline = calculate_timeout_deadline(FreshnessTier.FRESH)
        assert deadline > before
