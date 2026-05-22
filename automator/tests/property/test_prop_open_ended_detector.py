"""
Property-based tests for open-ended field classification.

Uses Hypothesis to verify that the Open_Ended_Detector correctly classifies
form fields as open-ended based on field type, character limit, and label
question phrasing.

Properties tested:
- Property 2: Open-Ended Field Classification

Feature: human-in-the-loop-escalation, Property 2: Open-Ended Field Classification
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.open_ended_detector import (
    INTERROGATIVE_WORDS,
    REQUEST_PHRASES,
    _has_question_phrasing,
    _is_open_ended_type,
    classify_open_ended_fields,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Field types that qualify as open-ended (when other criteria met)
OPEN_ENDED_TYPES = ["textarea", "text"]

# Field types that never qualify as open-ended
NON_OPEN_ENDED_TYPES = [
    "select",
    "checkbox",
    "radio",
    "email",
    "number",
    "tel",
    "url",
    "date",
    "hidden",
    "password",
    "file",
]

ALL_FIELD_TYPES = OPEN_ENDED_TYPES + NON_OPEN_ENDED_TYPES

# Labels that contain question phrasing
question_label_strategy = st.one_of(
    # Labels ending with '?'
    st.text(min_size=1, max_size=50).map(lambda s: s.rstrip("?") + "?"),
    # Labels containing an interrogative word
    st.tuples(
        st.text(min_size=0, max_size=20),
        st.sampled_from(INTERROGATIVE_WORDS),
        st.text(min_size=0, max_size=20),
    ).map(lambda t: f"{t[0]} {t[1]} {t[2]}".strip()),
    # Labels containing a request phrase
    st.tuples(
        st.text(min_size=0, max_size=20),
        st.sampled_from(REQUEST_PHRASES),
        st.text(min_size=0, max_size=20),
    ).map(lambda t: f"{t[0]} {t[1]} {t[2]}".strip()),
)

# Labels that do NOT contain question phrasing:
# - No interrogative words at word boundaries
# - No request phrases
# - Does not end with '?'
# We use a curated set of safe labels to avoid accidental matches.
non_question_label_strategy = st.sampled_from(
    [
        "First Name",
        "Last Name",
        "Email Address",
        "Phone Number",
        "City",
        "State",
        "Zip Code",
        "LinkedIn URL",
        "Company Name",
        "Job Title",
        "Start Date",
        "End Date",
        "Salary",
        "Years of Experience",
        "Resume",
        "Cover Letter",
        "Portfolio URL",
        "GitHub Profile",
        "Preferred Location",
        "Availability",
    ]
)

# Maxlength values: None (unlimited) or positive integers
maxlength_strategy = st.one_of(
    st.none(),
    st.integers(min_value=1, max_value=10000),
)


# ---------------------------------------------------------------------------
# Helper: compute expected classification
# ---------------------------------------------------------------------------


def _expected_is_open_ended_type(field_type: str, maxlength: int | None) -> bool:
    """Compute expected type qualification per the specification."""
    ft = field_type.lower().strip()
    if ft == "textarea":
        return True
    if ft == "text":
        if maxlength is None:
            return True  # No limit = potentially open-ended
        return maxlength > 200
    return False


# ---------------------------------------------------------------------------
# Property 2: Open-Ended Field Classification
# ---------------------------------------------------------------------------


@given(
    field_type=st.sampled_from(ALL_FIELD_TYPES),
    maxlength=maxlength_strategy,
    label=st.one_of(question_label_strategy, non_question_label_strategy),
)
@settings(max_examples=200)
def test_open_ended_field_classification(
    field_type: str,
    maxlength: int | None,
    label: str,
) -> None:
    """
    For any form field with a type, a character limit (or none), and a label,
    the Open_Ended_Detector should classify the field as open-ended if and
    only if:
    - (the field is a textarea OR the field is a text input with char limit > 200
      or no char limit)
    AND
    - the label contains question phrasing (interrogative words,
      description/explanation requests, or ends with '?')

    Fields not meeting both criteria should be classified as not open-ended.

    **Validates: Requirements 2.6**
    """
    # Build a DOM field dict
    field = {
        "type": field_type,
        "maxlength": maxlength,
        "label": label,
        "field_id": "test_field_1",
        "selector": "#test_field_1",
    }

    # Classify using the implementation
    results = classify_open_ended_fields([field])
    actual_is_open_ended = len(results) > 0

    # Compute expected result from the specification
    type_qualifies = _expected_is_open_ended_type(field_type, maxlength)
    has_question = _has_question_phrasing(label)
    expected_is_open_ended = type_qualifies and has_question

    assert actual_is_open_ended == expected_is_open_ended, (
        f"classify_open_ended_fields returned is_open_ended={actual_is_open_ended}, "
        f"expected {expected_is_open_ended} for type={field_type!r}, "
        f"maxlength={maxlength}, label={label!r} "
        f"(type_qualifies={type_qualifies}, has_question={has_question})"
    )


@given(
    field_type=st.sampled_from(ALL_FIELD_TYPES),
    maxlength=maxlength_strategy,
)
@settings(max_examples=200)
def test_is_open_ended_type_classification(
    field_type: str,
    maxlength: int | None,
) -> None:
    """
    For any field type and maxlength combination, _is_open_ended_type should
    return True if and only if the field is a textarea OR a text input with
    maxlength > 200 (or no maxlength).

    This is the type-qualification sub-property of Property 2.

    **Validates: Requirements 2.6**
    """
    field = {"type": field_type, "maxlength": maxlength}

    actual = _is_open_ended_type(field)
    expected = _expected_is_open_ended_type(field_type, maxlength)

    assert actual == expected, (
        f"_is_open_ended_type returned {actual}, expected {expected} "
        f"for type={field_type!r}, maxlength={maxlength}"
    )


@given(label=question_label_strategy)
@settings(max_examples=200)
def test_question_phrasing_detected_for_question_labels(label: str) -> None:
    """
    For any label that contains an interrogative word, a request phrase, or
    ends with '?', _has_question_phrasing should return True.

    This is the label-classification sub-property of Property 2.

    **Validates: Requirements 2.6**
    """
    assert _has_question_phrasing(label), (
        f"_has_question_phrasing returned False for label={label!r}, "
        f"which should contain question phrasing"
    )


@given(label=non_question_label_strategy)
@settings(max_examples=200)
def test_no_question_phrasing_for_plain_labels(label: str) -> None:
    """
    For any label that does NOT contain interrogative words, request phrases,
    or end with '?', _has_question_phrasing should return False.

    This is the negative label-classification sub-property of Property 2.

    **Validates: Requirements 2.6**
    """
    assert not _has_question_phrasing(label), (
        f"_has_question_phrasing returned True for label={label!r}, "
        f"which should NOT contain question phrasing"
    )
