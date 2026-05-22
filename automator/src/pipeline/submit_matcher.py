"""Submit button pattern matcher for dry-run mode.

Identifies buttons that must NOT be clicked during a dry-run application.
A button is considered a submit button if its visible text or aria-label
exactly matches (case-insensitive) one of the known submit patterns.
"""

from __future__ import annotations

# Button text patterns that indicate a form submission action.
# Match is exact and case-insensitive — no substring matching.
_SUBMIT_PATTERNS: frozenset[str] = frozenset(
    {
        "submit",
        "apply",
        "send application",
        "complete application",
    }
)


def is_submit_button(text: str) -> bool:
    """Determine whether a button's text identifies it as a submit button.

    Used in dry_run mode to prevent clicking buttons that would submit
    a real application. The match is exact (not substring) and
    case-insensitive.

    Args:
        text: The button's visible text or aria-label.

    Returns:
        True if the text exactly matches one of the known submit patterns
        (case-insensitive), False otherwise.
    """
    return text.lower() in _SUBMIT_PATTERNS
