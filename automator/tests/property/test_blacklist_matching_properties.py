"""
Property-based tests for blacklist matching correctness.

Uses Hypothesis to verify that the blacklist filter correctly identifies
jobs that match company names (case-insensitive exact match) or title
patterns (case-insensitive substring match), and returns (False, None)
when neither matches.

Properties tested:
- Property 13: Blacklist Matching Correctness
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.blacklist_filter import BlacklistConfig, check_blacklist


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Use ASCII alphabet to avoid Unicode case-folding edge cases (e.g., Turkish ı/İ).
# The blacklist filter uses Python's .lower() which is correct for the English
# company names and job titles this system processes.
_ascii_alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_&.,"

# Strategy for company names — ASCII text that isn't empty
company_name_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip())

# Strategy for job titles — ASCII text that isn't empty
title_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=2,
    max_size=60,
).filter(lambda s: s.strip())

# Strategy for blacklist pattern entries — shorter ASCII strings for substring matching
pattern_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=2,
    max_size=15,
).filter(lambda s: s.strip())

# Strategy for case transformations to verify case-insensitivity
case_transform_strategy = st.sampled_from(["lower", "upper", "title", "swapcase"])


def apply_case_transform(s: str, transform: str) -> str:
    """Apply a case transformation to a string."""
    if transform == "lower":
        return s.lower()
    elif transform == "upper":
        return s.upper()
    elif transform == "title":
        return s.title()
    elif transform == "swapcase":
        return s.swapcase()
    return s


# ---------------------------------------------------------------------------
# Property 13: Blacklist Matching Correctness
# ---------------------------------------------------------------------------


@given(
    company=company_name_strategy,
    title=title_strategy,
    blacklist_companies=st.lists(company_name_strategy, min_size=1, max_size=10),
    case_transform=case_transform_strategy,
)
@settings(max_examples=150)
def test_company_blacklist_match_is_case_insensitive(
    company: str,
    title: str,
    blacklist_companies: list[str],
    case_transform: str,
) -> None:
    """
    If a company name is in the blacklist (case-insensitive exact match),
    check_blacklist() SHALL return (True, "company:...") regardless of the
    casing used in the input company name or the blacklist entry.

    **Validates: Requirements 4.5, 4.11**
    """
    # Pick the first blacklist entry and use it as the company (with a case transform)
    target_entry = blacklist_companies[0]
    transformed_company = apply_case_transform(target_entry, case_transform)

    blacklist = BlacklistConfig(
        companies=blacklist_companies,
        title_patterns=[],
    )

    is_blacklisted, matched_entry = check_blacklist(transformed_company, title, blacklist)

    assert is_blacklisted is True, (
        f"Expected company '{transformed_company}' to match blacklist entry "
        f"'{target_entry}' (case-insensitive exact match), but got False. "
        f"Transform applied: {case_transform}"
    )
    assert matched_entry is not None, (
        f"Expected matched_entry to be non-None when company matches blacklist"
    )
    assert matched_entry.startswith("company:"), (
        f"Expected matched_entry to start with 'company:', got '{matched_entry}'"
    )


@given(
    title=title_strategy,
    company=company_name_strategy,
    blacklist_patterns=st.lists(pattern_strategy, min_size=1, max_size=10),
    case_transform=case_transform_strategy,
)
@settings(max_examples=150)
def test_title_blacklist_match_is_case_insensitive_substring(
    title: str,
    company: str,
    blacklist_patterns: list[str],
    case_transform: str,
) -> None:
    """
    If a title contains a blacklist pattern (case-insensitive substring match),
    check_blacklist() SHALL return (True, "title:...") regardless of the
    casing used in the title or the pattern.

    **Validates: Requirements 4.5, 4.11**
    """
    # Embed the first pattern into the title with a case transform
    target_pattern = blacklist_patterns[0]
    transformed_pattern = apply_case_transform(target_pattern, case_transform)
    # Build a title that contains the pattern as a substring
    constructed_title = f"Senior {transformed_pattern} Engineer"

    blacklist = BlacklistConfig(
        companies=[],  # No company matches — force title path
        title_patterns=blacklist_patterns,
    )

    is_blacklisted, matched_entry = check_blacklist(company, constructed_title, blacklist)

    assert is_blacklisted is True, (
        f"Expected title '{constructed_title}' to match blacklist pattern "
        f"'{target_pattern}' (case-insensitive substring), but got False. "
        f"Transform applied: {case_transform}"
    )
    assert matched_entry is not None, (
        f"Expected matched_entry to be non-None when title matches blacklist"
    )
    assert matched_entry.startswith("title:"), (
        f"Expected matched_entry to start with 'title:', got '{matched_entry}'"
    )


@given(
    blacklist_companies=st.lists(company_name_strategy, min_size=1, max_size=5),
    blacklist_patterns=st.lists(pattern_strategy, min_size=1, max_size=5),
)
@settings(max_examples=150)
def test_no_match_returns_false_none(
    blacklist_companies: list[str],
    blacklist_patterns: list[str],
) -> None:
    """
    If neither the company matches any blacklist company entry (case-insensitive
    exact match) nor the title contains any blacklist pattern (case-insensitive
    substring), check_blacklist() SHALL return (False, None).

    **Validates: Requirements 4.5, 4.11**
    """
    # Use characters (emoji/symbols) that cannot appear in the pattern_strategy
    # alphabet (which is purely alphanumeric). This guarantees no substring match.
    safe_company = "\u2603\u2764\u2605_NOMATCH_\u2603"
    safe_title = "\u2603\u2764\u2605 \u2603\u2764\u2605"

    # Double-check our safe values don't accidentally match
    assert not any(
        safe_company.lower() == entry.lower() for entry in blacklist_companies
    ), "Test setup error: safe_company matched a blacklist entry"
    assert not any(
        pattern.lower() in safe_title.lower() for pattern in blacklist_patterns
    ), "Test setup error: safe_title contained a blacklist pattern"

    blacklist = BlacklistConfig(
        companies=blacklist_companies,
        title_patterns=blacklist_patterns,
    )

    is_blacklisted, matched_entry = check_blacklist(safe_company, safe_title, blacklist)

    assert is_blacklisted is False, (
        f"Expected no match for company='{safe_company}', title='{safe_title}', "
        f"but got True with matched_entry='{matched_entry}'. "
        f"Blacklist companies: {blacklist_companies}, patterns: {blacklist_patterns}"
    )
    assert matched_entry is None, (
        f"Expected matched_entry to be None when no match, got '{matched_entry}'"
    )


@given(
    company=company_name_strategy,
    title=title_strategy,
    blacklist_companies=st.lists(company_name_strategy, min_size=2, max_size=5),
    blacklist_patterns=st.lists(pattern_strategy, min_size=2, max_size=5),
    case_transform=case_transform_strategy,
)
@settings(max_examples=150)
def test_short_circuits_on_first_company_match(
    company: str,
    title: str,
    blacklist_companies: list[str],
    blacklist_patterns: list[str],
    case_transform: str,
) -> None:
    """
    When both a company match and a title pattern match would succeed,
    check_blacklist() SHALL short-circuit on the first match (company check
    runs before title check), returning a "company:..." matched entry.

    **Validates: Requirements 4.5, 4.11**
    """
    # Use the first blacklist company as the input company (with case transform)
    target_company_entry = blacklist_companies[0]
    transformed_company = apply_case_transform(target_company_entry, case_transform)

    # Also embed a title pattern so both would match
    target_pattern = blacklist_patterns[0]
    constructed_title = f"Senior {target_pattern} Engineer"

    blacklist = BlacklistConfig(
        companies=blacklist_companies,
        title_patterns=blacklist_patterns,
    )

    is_blacklisted, matched_entry = check_blacklist(
        transformed_company, constructed_title, blacklist
    )

    assert is_blacklisted is True, (
        f"Expected match when both company and title would match"
    )
    # Short-circuit: company match should come first
    assert matched_entry is not None and matched_entry.startswith("company:"), (
        f"Expected short-circuit to return 'company:...' when both company and "
        f"title would match, but got '{matched_entry}'. "
        f"Company: '{transformed_company}', blacklist entry: '{target_company_entry}'"
    )
