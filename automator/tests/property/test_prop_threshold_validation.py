"""
Property-based tests for Human Review Threshold Validation.

Uses Hypothesis to verify that the SettingsUpdate schema's
human_review_threshold field validator accepts values in [50, 100]
and rejects values outside that range.

Feature: human-in-the-loop-escalation, Property 3: Human Review Threshold Validation
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from src.api.schemas import SettingsUpdate


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Integers within the valid range [50, 100]
_valid_threshold = st.integers(min_value=50, max_value=100)

# Integers below the valid range (< 50)
_below_range_threshold = st.integers(max_value=49)

# Integers above the valid range (> 100)
_above_range_threshold = st.integers(min_value=101)

# All invalid integers (outside [50, 100])
_invalid_threshold = st.one_of(_below_range_threshold, _above_range_threshold)


# ---------------------------------------------------------------------------
# Property 3: Human Review Threshold Validation
# ---------------------------------------------------------------------------


@given(value=_valid_threshold)
@settings(max_examples=150)
def test_valid_threshold_values_are_accepted(value: int) -> None:
    """
    For any integer value in [50, 100], the threshold validation function
    should accept the value without raising a validation error.

    **Validates: Requirements 3.2**
    """
    result = SettingsUpdate(human_review_threshold=value)
    assert result.human_review_threshold == value


@given(value=_invalid_threshold)
@settings(max_examples=150)
def test_invalid_threshold_values_are_rejected(value: int) -> None:
    """
    For any integer value outside [50, 100], the threshold validation function
    should reject the value with a ValidationError.

    **Validates: Requirements 3.2**
    """
    with pytest.raises(ValidationError, match="human_review_threshold must be between 50 and 100"):
        SettingsUpdate(human_review_threshold=value)


@given(data=st.data())
@settings(max_examples=100)
def test_none_threshold_is_always_accepted(data: st.DataObject) -> None:
    """
    For any SettingsUpdate with human_review_threshold set to None (the default),
    the validation should pass since the field is optional.

    **Validates: Requirements 3.2**
    """
    # Draw other optional fields to ensure None threshold works regardless of context
    ext_threshold = data.draw(
        st.one_of(st.none(), st.integers(min_value=50, max_value=100)),
        label="external_apply_threshold",
    )
    result = SettingsUpdate(
        human_review_threshold=None,
        external_apply_threshold=ext_threshold,
    )
    assert result.human_review_threshold is None
