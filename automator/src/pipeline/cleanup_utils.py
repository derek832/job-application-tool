"""Cleanup utilities for post-validation code hygiene.

Provides functions to remove diagnostic logging statements and other
temporary artifacts added during the validation fix cycle process.
"""

from __future__ import annotations

# Diagnostic marker prefixes that identify temporary logging added during
# fix cycles. Lines containing any of these strings are removed during cleanup.
DIAGNOSTIC_MARKERS: tuple[str, ...] = ("DEBUG_VISUAL", "VERBOSE", "DIAG")


def remove_diagnostic_markers(source_lines: list[str]) -> list[str]:
    """Remove lines containing diagnostic markers from source code.

    Diagnostic markers are identified by the presence of any of these
    strings anywhere in the line: "DEBUG_VISUAL", "VERBOSE", "DIAG".

    All other lines are preserved unchanged, including their indentation
    and relative ordering.

    Args:
        source_lines: List of source code lines.

    Returns:
        List of lines with diagnostic marker lines removed.
    """
    return [
        line for line in source_lines if not any(marker in line for marker in DIAGNOSTIC_MARKERS)
    ]
