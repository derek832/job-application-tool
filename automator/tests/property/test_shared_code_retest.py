"""
Property-based tests for shared code re-testing trigger.

Uses Hypothesis to verify that should_retest_passing_platforms() correctly
identifies when passing platforms need re-testing after a code patch modifies
shared code paths.

Properties tested:
- Property 9: Shared Code Modification Triggers Re-Testing

Feature: visual-apply-validation, Property 9: Shared Code Modification Triggers Re-Testing
"""

from __future__ import annotations

import os

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.validation_models import should_retest_passing_platforms


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Shared files that should trigger re-testing (various directory prefixes)
SHARED_FILES = [
    "visual_form_filler.py",
    "vision_agent.py",
    "src/pipeline/visual_form_filler.py",
    "src/agents/vision_agent.py",
    "automator/src/pipeline/visual_form_filler.py",
    "automator/src/agents/vision_agent.py",
    "/app/src/pipeline/visual_form_filler.py",
    "/app/src/agents/vision_agent.py",
]

# Non-shared files that should NOT trigger re-testing
NON_SHARED_FILES = [
    "claude_client.py",
    "config.py",
    "src/pipeline/failure_classifier.py",
    "src/pipeline/url_validator.py",
    "src/pipeline/validation_models.py",
    "src/pipeline/submit_matcher.py",
    "src/pipeline/log_utils.py",
    "automator/src/pipeline/cleanup_utils.py",
    "tests/test_something.py",
    "README.md",
]

# Combined pool for mixed generation
ALL_FILES = SHARED_FILES + NON_SHARED_FILES

modified_files_strategy = st.lists(st.sampled_from(ALL_FILES), min_size=0, max_size=10)


# ---------------------------------------------------------------------------
# Property 9: Shared Code Modification Triggers Re-Testing
# ---------------------------------------------------------------------------


@given(modified_files=modified_files_strategy)
@settings(max_examples=200)
def test_shared_code_modification_triggers_retest(
    modified_files: list[str],
) -> None:
    """
    For any list of modified files, should_retest_passing_platforms returns True
    if and only if any file in the list has a basename of "visual_form_filler.py"
    or "vision_agent.py".

    If modified files include shared paths, passing platforms are flagged for
    re-test; otherwise not.

    **Validates: Requirements 6.2**
    """
    actual = should_retest_passing_platforms(modified_files)

    # Compute expected: True iff any file has a shared basename
    shared_filenames = {"visual_form_filler.py", "vision_agent.py"}
    expected = any(os.path.basename(f) in shared_filenames for f in modified_files)

    assert actual == expected, (
        f"should_retest_passing_platforms returned {actual}, expected {expected} "
        f"for modified_files={modified_files!r}"
    )


@given(
    non_shared_files=st.lists(
        st.sampled_from(NON_SHARED_FILES), min_size=1, max_size=10
    )
)
@settings(max_examples=200)
def test_returns_false_for_only_non_shared_files(
    non_shared_files: list[str],
) -> None:
    """
    When only non-shared files are modified, should_retest_passing_platforms
    always returns False.

    **Validates: Requirements 6.2**
    """
    actual = should_retest_passing_platforms(non_shared_files)

    assert actual is False, (
        f"should_retest_passing_platforms returned True for non-shared files: "
        f"{non_shared_files!r}"
    )


def test_returns_false_for_empty_list() -> None:
    """
    An empty modified files list should never trigger re-testing.

    **Validates: Requirements 6.2**
    """
    assert should_retest_passing_platforms([]) is False
