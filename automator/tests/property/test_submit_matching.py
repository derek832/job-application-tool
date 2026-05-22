"""
Property-based tests for submit button pattern matching.

Uses Hypothesis to verify that is_submit_button() correctly identifies
submit buttons by exact case-insensitive matching against the four
known patterns.

Properties tested:
- Property 3: Submit Button Pattern Matching

Feature: visual-apply-validation, Property 3: Submit Button Pattern Matching
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.submit_matcher import is_submit_button

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBMIT_PATTERNS = frozenset({"submit", "apply", "send application", "complete application"})

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def random_casing(s: str) -> st.SearchStrategy[str]:
    """Generate a string with random upper/lower casing per character."""
    return st.tuples(
        *(st.sampled_from([c.lower(), c.upper()]) for c in s)
    ).map("".join)


# Strategy that produces one of the four patterns with random casing (should return True)
submit_pattern_strategy = st.sampled_from(sorted(SUBMIT_PATTERNS)).flatmap(random_casing)

# Strategy that mixes random text (mostly False) with known patterns (True)
button_text_strategy = st.one_of(
    st.text(),  # Random text — should mostly return False
    submit_pattern_strategy,  # Known patterns with random casing — should return True
)


# ---------------------------------------------------------------------------
# Property 3: Submit Button Pattern Matching
# ---------------------------------------------------------------------------


@given(text=button_text_strategy)
@settings(max_examples=200)
def test_submit_button_pattern_matching(text: str) -> None:
    """
    For any string representing a button's visible text or aria-label,
    is_submit_button returns True if and only if the string matches
    (case-insensitive) one of: "submit", "apply", "send application",
    or "complete application".

    **Validates: Requirements 2.2**
    """
    actual = is_submit_button(text)

    # Compute expected result from the specification
    expected = text.lower() in SUBMIT_PATTERNS

    assert actual == expected, (
        f"is_submit_button({text!r}) returned {actual}, expected {expected}"
    )
