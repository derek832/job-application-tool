"""Unit tests for the preview pipeline module.

Tests the compute_projected_action() helper and verifies the module's
core logic without requiring external services.
"""

from __future__ import annotations

import pytest

from src.pipeline.preview_pipeline import compute_projected_action


class TestComputeProjectedAction:
    """Tests for compute_projected_action() threshold classification."""

    def test_blacklisted_overrides_score(self) -> None:
        """Blacklisted flag takes priority over any score."""
        result = compute_projected_action(
            fit_score=95,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=True,
        )
        assert result == "blacklisted"

    def test_none_score_returns_skip(self) -> None:
        """A None fit_score (not scored) results in skip."""
        result = compute_projected_action(
            fit_score=None,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "skip"

    def test_score_above_good_fit_threshold(self) -> None:
        """Score at or above good_fit_threshold returns auto_apply."""
        result = compute_projected_action(
            fit_score=80,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "auto_apply"

    def test_score_at_good_fit_threshold(self) -> None:
        """Score exactly at good_fit_threshold returns auto_apply."""
        result = compute_projected_action(
            fit_score=75,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "auto_apply"

    def test_score_in_stretch_range(self) -> None:
        """Score between stretch and good_fit thresholds returns stretch_queue."""
        result = compute_projected_action(
            fit_score=60,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "stretch_queue"

    def test_score_at_stretch_threshold(self) -> None:
        """Score exactly at stretch_threshold returns stretch_queue."""
        result = compute_projected_action(
            fit_score=50,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "stretch_queue"

    def test_score_below_stretch_threshold(self) -> None:
        """Score below stretch_threshold returns skip."""
        result = compute_projected_action(
            fit_score=30,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "skip"

    def test_score_zero(self) -> None:
        """A score of 0 returns skip."""
        result = compute_projected_action(
            fit_score=0,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "skip"

    def test_score_100(self) -> None:
        """A perfect score of 100 returns auto_apply."""
        result = compute_projected_action(
            fit_score=100,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=False,
        )
        assert result == "auto_apply"

    def test_blacklisted_with_none_score(self) -> None:
        """Blacklisted with None score still returns blacklisted."""
        result = compute_projected_action(
            fit_score=None,
            good_fit_threshold=75,
            stretch_threshold=50,
            is_blacklisted=True,
        )
        assert result == "blacklisted"
