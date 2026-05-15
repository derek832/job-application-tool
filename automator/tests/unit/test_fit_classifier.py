"""Unit tests for the fit score classifier module."""

import pytest

from src.pipeline.fit_classifier import classify_fit, has_deal_breaker, is_threshold_boundary


class TestClassifyFit:
    """Tests for classify_fit function."""

    def test_score_at_good_fit_threshold_returns_good_fit(self) -> None:
        assert classify_fit(75, good_fit_threshold=75, stretch_threshold=50) == "good_fit"

    def test_score_above_good_fit_threshold_returns_good_fit(self) -> None:
        assert classify_fit(90, good_fit_threshold=75, stretch_threshold=50) == "good_fit"

    def test_score_at_stretch_threshold_returns_stretch_role(self) -> None:
        assert classify_fit(50, good_fit_threshold=75, stretch_threshold=50) == "stretch_role"

    def test_score_between_thresholds_returns_stretch_role(self) -> None:
        assert classify_fit(60, good_fit_threshold=75, stretch_threshold=50) == "stretch_role"

    def test_score_just_below_good_fit_returns_stretch_role(self) -> None:
        assert classify_fit(74, good_fit_threshold=75, stretch_threshold=50) == "stretch_role"

    def test_score_below_stretch_threshold_returns_skip(self) -> None:
        assert classify_fit(49, good_fit_threshold=75, stretch_threshold=50) == "skip"

    def test_score_zero_returns_skip(self) -> None:
        assert classify_fit(0, good_fit_threshold=75, stretch_threshold=50) == "skip"

    def test_score_100_returns_good_fit(self) -> None:
        assert classify_fit(100, good_fit_threshold=75, stretch_threshold=50) == "good_fit"

    def test_custom_thresholds(self) -> None:
        assert classify_fit(80, good_fit_threshold=90, stretch_threshold=70) == "stretch_role"
        assert classify_fit(91, good_fit_threshold=90, stretch_threshold=70) == "good_fit"
        assert classify_fit(69, good_fit_threshold=90, stretch_threshold=70) == "skip"


class TestHasDealBreaker:
    """Tests for has_deal_breaker function."""

    def test_no_deal_breakers_returns_false(self) -> None:
        found, term = has_deal_breaker("Great Python job", [])
        assert found is False
        assert term is None

    def test_matching_term_returns_true_with_term(self) -> None:
        found, term = has_deal_breaker(
            "Must have 10 years of COBOL experience",
            ["cobol", "fortran"],
        )
        assert found is True
        assert term == "cobol"

    def test_case_insensitive_match(self) -> None:
        found, term = has_deal_breaker("Requires PHP expertise", ["php"])
        assert found is True
        assert term == "php"

    def test_case_insensitive_deal_breaker_term(self) -> None:
        found, term = has_deal_breaker("requires php expertise", ["PHP"])
        assert found is True
        assert term == "PHP"

    def test_no_match_returns_false(self) -> None:
        found, term = has_deal_breaker("Python and TypeScript role", ["cobol", "fortran"])
        assert found is False
        assert term is None

    def test_returns_first_matching_term(self) -> None:
        found, term = has_deal_breaker(
            "Need COBOL and Fortran skills",
            ["cobol", "fortran"],
        )
        assert found is True
        assert term == "cobol"

    def test_substring_match(self) -> None:
        found, term = has_deal_breaker("Must relocate to office", ["relocate"])
        assert found is True
        assert term == "relocate"

    def test_empty_description(self) -> None:
        found, term = has_deal_breaker("", ["cobol"])
        assert found is False
        assert term is None


class TestIsThresholdBoundary:
    """Tests for is_threshold_boundary function."""

    def test_score_at_good_fit_threshold_is_boundary(self) -> None:
        assert is_threshold_boundary(75, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_at_stretch_threshold_is_boundary(self) -> None:
        assert is_threshold_boundary(50, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_within_margin_above_good_fit(self) -> None:
        assert is_threshold_boundary(77, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_within_margin_below_good_fit(self) -> None:
        assert is_threshold_boundary(73, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_within_margin_above_stretch(self) -> None:
        assert is_threshold_boundary(52, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_within_margin_below_stretch(self) -> None:
        assert is_threshold_boundary(48, good_fit_threshold=75, stretch_threshold=50) is True

    def test_score_outside_both_margins(self) -> None:
        assert is_threshold_boundary(60, good_fit_threshold=75, stretch_threshold=50) is False

    def test_score_just_outside_margin(self) -> None:
        assert is_threshold_boundary(72, good_fit_threshold=75, stretch_threshold=50) is False
        assert is_threshold_boundary(78, good_fit_threshold=75, stretch_threshold=50) is False

    def test_custom_margin(self) -> None:
        assert is_threshold_boundary(70, good_fit_threshold=75, stretch_threshold=50, margin=5) is True
        assert is_threshold_boundary(69, good_fit_threshold=75, stretch_threshold=50, margin=5) is False

    def test_default_margin_is_2(self) -> None:
        # Exactly 2 away should be True
        assert is_threshold_boundary(73, good_fit_threshold=75, stretch_threshold=50) is True
        # Exactly 3 away should be False
        assert is_threshold_boundary(72, good_fit_threshold=75, stretch_threshold=50) is False
