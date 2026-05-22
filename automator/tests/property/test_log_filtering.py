"""
Property-based tests for Docker log filtering by URL.

Uses Hypothesis to verify that filter_logs_by_url() returns exactly those
lines containing the target URL or its domain component — no false positives
and no false negatives.

Properties tested:
- Property 6: Log Entry Filtering by URL

Feature: visual-apply-validation, Property 6: Log Entry Filtering by URL
"""

from __future__ import annotations

from urllib.parse import urlparse

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.log_utils import filter_logs_by_url


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating valid-looking URLs with a non-empty netloc
url_strategy = st.builds(
    lambda scheme, domain, path: f"{scheme}://{domain}/{path}",
    scheme=st.sampled_from(["http", "https"]),
    domain=st.from_regex(r"[a-z][a-z0-9\-]{1,20}\.[a-z]{2,6}", fullmatch=True),
    path=st.from_regex(r"[a-z0-9/\-]{0,30}", fullmatch=True),
)

# Strategy for generating a log line that does NOT contain a given substring.
# We use st.text() filtered to exclude lines containing the target.
# To avoid excessive filtering, we use a character set unlikely to form URLs.
safe_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyz0123456789 _=[]{}|;,<>!@#$%^&*()\t\n"
)


def log_line_without(target_url: str, domain: str) -> st.SearchStrategy[str]:
    """Generate a log line guaranteed to NOT contain the URL or domain."""
    return st.text(
        alphabet=safe_chars,
        min_size=1,
        max_size=80,
    ).filter(lambda line: target_url not in line and (not domain or domain not in line))


def log_line_with_url(target_url: str) -> st.SearchStrategy[str]:
    """Generate a log line that contains the full target URL."""
    return st.builds(
        lambda prefix, suffix: f"{prefix} {target_url} {suffix}",
        prefix=st.text(alphabet=safe_chars, min_size=0, max_size=30),
        suffix=st.text(alphabet=safe_chars, min_size=0, max_size=30),
    )


def log_line_with_domain(domain: str) -> st.SearchStrategy[str]:
    """Generate a log line that contains the domain but not necessarily the full URL."""
    return st.builds(
        lambda prefix, suffix: f"{prefix} {domain} {suffix}",
        prefix=st.text(alphabet=safe_chars, min_size=0, max_size=30),
        suffix=st.text(alphabet=safe_chars, min_size=0, max_size=30),
    )


# ---------------------------------------------------------------------------
# Property 6: Log Entry Filtering by URL
# ---------------------------------------------------------------------------


@given(data=st.data())
@settings(max_examples=200)
def test_log_entry_filtering_by_url(data: st.DataObject) -> None:
    """
    For any set of Docker log lines and any target URL, filter_logs_by_url
    returns exactly those lines containing the target URL or its domain.

    - No false positives: lines without URL/domain are never included.
    - No false negatives: lines with URL/domain are never excluded.

    **Validates: Requirements 3.4**
    """
    # Draw a target URL
    target_url = data.draw(url_strategy, label="target_url")
    domain = urlparse(target_url).netloc

    # Draw lines that should match (contain URL or domain)
    matching_lines_url = data.draw(
        st.lists(log_line_with_url(target_url), min_size=0, max_size=5),
        label="lines_with_url",
    )
    matching_lines_domain = data.draw(
        st.lists(log_line_with_domain(domain), min_size=0, max_size=5),
        label="lines_with_domain",
    )

    # Draw lines that should NOT match
    non_matching_lines = data.draw(
        st.lists(log_line_without(target_url, domain), min_size=0, max_size=5),
        label="lines_without_url_or_domain",
    )

    # Combine all matching lines
    expected_matching = matching_lines_url + matching_lines_domain

    # Interleave all lines in a random order
    all_lines = expected_matching + non_matching_lines
    shuffled_indices = data.draw(
        st.permutations(range(len(all_lines))),
        label="shuffle_order",
    )
    shuffled_lines = [all_lines[i] for i in shuffled_indices]

    # Run the filter
    result = filter_logs_by_url(shuffled_lines, target_url)

    # Build the expected set: lines that contain target_url OR domain
    expected_result = [
        line
        for line in shuffled_lines
        if target_url in line or (domain and domain in line)
    ]

    # Assert no false positives and no false negatives
    assert result == expected_result, (
        f"Filter mismatch for target_url={target_url!r}, domain={domain!r}\n"
        f"Expected {len(expected_result)} lines, got {len(result)} lines.\n"
        f"Missing: {set(expected_result) - set(result)}\n"
        f"Extra: {set(result) - set(expected_result)}"
    )
