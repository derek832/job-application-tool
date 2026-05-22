"""
Property-based tests for URL active/closed classification.

Uses Hypothesis to verify correctness properties of the classify_url_status
function in src/pipeline/url_validator.py.

Properties tested:
- Property 1: URL Active/Closed Classification
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.url_validator import (
    _CLOSED_PHRASES,
    _INACTIVE_STATUS_CODES,
    classify_url_status,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for HTTP status codes (full range of valid codes)
status_code_strategy = st.integers(min_value=100, max_value=599)

# Strategy for body text that does NOT contain any closed-job phrase
safe_body_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    max_size=200,
).filter(
    lambda t: not any(phrase in t.lower() for phrase in _CLOSED_PHRASES)
)

# Strategy for body text that contains at least one closed-job phrase
closed_phrase_strategy = st.sampled_from(_CLOSED_PHRASES)

# Strategy for inactive status codes (404, 410)
inactive_status_strategy = st.sampled_from(sorted(_INACTIVE_STATUS_CODES))

# Strategy for active status codes (anything not in _INACTIVE_STATUS_CODES)
active_status_strategy = st.integers(min_value=100, max_value=599).filter(
    lambda c: c not in _INACTIVE_STATUS_CODES
)


# ---------------------------------------------------------------------------
# Property 1: URL Active/Closed Classification
# ---------------------------------------------------------------------------


@given(
    status_code=status_code_strategy,
    body_text=st.text(max_size=300),
)
@settings(max_examples=200)
def test_url_classification_inactive_iff_status_or_phrase(
    status_code: int,
    body_text: str,
) -> None:
    """
    For any (status_code, body_text) pair, classify_url_status returns
    "inactive" if and only if the status code is 404 or 410, OR the body
    text contains (case-insensitive) any of the closed-job phrases.
    Otherwise it returns "active".

    **Validates: Requirements 1.2**
    """
    result = classify_url_status(status_code, body_text)

    # Determine expected classification independently
    is_inactive_status = status_code in _INACTIVE_STATUS_CODES
    body_lower = body_text.lower()
    has_closed_phrase = any(phrase in body_lower for phrase in _CLOSED_PHRASES)

    expected_inactive = is_inactive_status or has_closed_phrase

    if expected_inactive:
        assert result == "inactive", (
            f"Expected 'inactive' for status_code={status_code}, "
            f"body contains closed phrase={has_closed_phrase}, "
            f"but got '{result}'"
        )
    else:
        assert result == "active", (
            f"Expected 'active' for status_code={status_code}, "
            f"body contains closed phrase={has_closed_phrase}, "
            f"but got '{result}'"
        )


@given(
    status_code=inactive_status_strategy,
    body_text=st.text(max_size=200),
)
@settings(max_examples=200)
def test_inactive_status_always_returns_inactive(
    status_code: int,
    body_text: str,
) -> None:
    """
    For any body text, if the status code is 404 or 410, the classifier
    always returns "inactive" regardless of body content.

    **Validates: Requirements 1.2**
    """
    result = classify_url_status(status_code, body_text)
    assert result == "inactive", (
        f"Expected 'inactive' for status_code={status_code}, but got '{result}'"
    )


@given(
    status_code=active_status_strategy,
    closed_phrase=closed_phrase_strategy,
    prefix=st.text(max_size=100),
    suffix=st.text(max_size=100),
)
@settings(max_examples=200)
def test_closed_phrase_in_body_returns_inactive(
    status_code: int,
    closed_phrase: str,
    prefix: str,
    suffix: str,
) -> None:
    """
    For any non-404/410 status code, if the body text contains a closed-job
    phrase (case-insensitive), the classifier returns "inactive".

    **Validates: Requirements 1.2**
    """
    body_text = prefix + closed_phrase + suffix
    result = classify_url_status(status_code, body_text)
    assert result == "inactive", (
        f"Expected 'inactive' for body containing '{closed_phrase}' "
        f"with status_code={status_code}, but got '{result}'"
    )


@given(
    status_code=active_status_strategy,
    body_text=safe_body_strategy,
)
@settings(max_examples=200)
def test_active_status_no_phrase_returns_active(
    status_code: int,
    body_text: str,
) -> None:
    """
    For any non-404/410 status code with body text that does NOT contain
    any closed-job phrase, the classifier returns "active".

    **Validates: Requirements 1.2**
    """
    result = classify_url_status(status_code, body_text)
    assert result == "active", (
        f"Expected 'active' for status_code={status_code} with no closed phrases, "
        f"but got '{result}'"
    )
