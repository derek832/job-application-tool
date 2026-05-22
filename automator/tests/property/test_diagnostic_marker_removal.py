"""
Property-based tests for diagnostic marker removal.

Uses Hypothesis to verify that remove_diagnostic_markers() correctly removes
all lines containing diagnostic markers while preserving all other lines
unchanged in their original order and indentation.

Properties tested:
- Property 11: Diagnostic Marker Removal

Feature: visual-apply-validation, Property 11: Diagnostic Marker Removal
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.cleanup_utils import DIAGNOSTIC_MARKERS, remove_diagnostic_markers


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Indentation options to simulate real Python source
indentation_strategy = st.sampled_from(["", "    ", "        ", "\t", "\t\t"])

# Normal code lines that should never be removed
normal_line_strategy = st.sampled_from([
    "import os",
    "from typing import Any",
    "x = 42",
    "def foo():",
    "    return bar()",
    "class MyClass:",
    "    pass",
    "# a comment",
    "logger.info('processing')",
    "print('hello world')",
    "result = await some_func()",
    "if condition:",
    "    do_something()",
    "",
])

# Diagnostic marker lines that should always be removed
marker_line_strategy = st.one_of(
    st.builds(
        lambda indent, marker, suffix: f"{indent}{marker}{suffix}",
        indentation_strategy,
        st.sampled_from(list(DIAGNOSTIC_MARKERS)),
        st.sampled_from([
            ": starting validation",
            " field count = 5",
            "_LOG: page loaded",
            " - checking element",
            "",
        ]),
    ),
)


def source_line_strategy():
    """Generate a single source line that is either normal or contains a marker."""
    return st.one_of(normal_line_strategy, marker_line_strategy)


# ---------------------------------------------------------------------------
# Property 11: Diagnostic Marker Removal
# ---------------------------------------------------------------------------


@given(
    source_lines=st.lists(source_line_strategy(), min_size=0, max_size=50),
)
@settings(max_examples=200)
def test_diagnostic_marker_removal(source_lines: list[str]) -> None:
    """
    For any list of Python source lines containing a mix of normal lines and
    diagnostic logging lines (identified by markers "DEBUG_VISUAL", "VERBOSE",
    "DIAG"), remove_diagnostic_markers should:

    1. Remove all lines containing any diagnostic marker
    2. Preserve all lines that do NOT contain any marker
    3. Preserve the original order of non-marker lines
    4. Preserve indentation (lines are unchanged)

    **Validates: Requirements 8.2**
    """
    result = remove_diagnostic_markers(source_lines)

    # Compute expected: lines that do NOT contain any marker
    expected_lines = [
        line for line in source_lines
        if not any(marker in line for marker in DIAGNOSTIC_MARKERS)
    ]

    # Property 1: No line in the output contains any diagnostic marker
    for line in result:
        assert not any(marker in line for marker in DIAGNOSTIC_MARKERS), (
            f"Output contains a diagnostic marker line: {line!r}"
        )

    # Property 2: All non-marker lines from input appear in the output
    assert len(result) == len(expected_lines), (
        f"Expected {len(expected_lines)} lines but got {len(result)}. "
        f"Some non-marker lines were incorrectly removed or marker lines were kept."
    )

    # Property 3: Output preserves the original order of non-marker lines
    # Property 4: Lines are unchanged (indentation preserved)
    assert result == expected_lines, (
        f"Output does not match expected non-marker lines in order and content.\n"
        f"Expected: {expected_lines!r}\n"
        f"Got:      {result!r}"
    )
