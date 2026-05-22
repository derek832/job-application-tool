"""URL active/closed classifier and replacement retry tracking for job posting validation.

Classifies a URL's status based on HTTP response code and page body content.
Used by the validation engine to determine whether a job posting is still
accepting applications before attempting a dry-run.

Also provides bounded retry tracking for URL replacements per platform,
preventing infinite loops when all available URLs are stale or unsuitable.
"""

from __future__ import annotations

# Phrases that indicate a job posting is no longer active (case-insensitive).
_CLOSED_PHRASES: tuple[str, ...] = (
    "position closed",
    "job closed",
    "no longer accepting applications",
    "this position has been filled",
)

# HTTP status codes that definitively indicate an inactive posting.
_INACTIVE_STATUS_CODES: frozenset[int] = frozenset({404, 410})


def classify_url_status(status_code: int, body_text: str) -> str:
    """Classify a job posting URL as active or inactive.

    A URL is classified as "inactive" if:
    - The HTTP status code is 404 (Not Found) or 410 (Gone), OR
    - The response body contains any closed-job indicator phrase
      (case-insensitive match).

    Otherwise the URL is classified as "active".

    Args:
        status_code: The HTTP response status code.
        body_text: The response body text content.

    Returns:
        "active" if the posting appears open, "inactive" if closed or gone.
    """
    if status_code in _INACTIVE_STATUS_CODES:
        return "inactive"

    body_lower = body_text.lower()
    for phrase in _CLOSED_PHRASES:
        if phrase in body_lower:
            return "inactive"

    return "active"


class URLReplacementTracker:
    """Tracks URL replacement attempts per platform.

    After 3 failed replacements for a platform, the platform is marked
    as "unavailable" and no further replacements are attempted.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._unavailable: set[str] = set()

    def attempt_replacement(self, platform: str) -> bool:
        """Record a replacement attempt. Returns True if allowed, False if limit reached."""
        if platform in self._unavailable:
            return False
        self._attempts[platform] = self._attempts.get(platform, 0) + 1
        if self._attempts[platform] >= 3:
            self._unavailable.add(platform)
            return False
        return True

    def is_unavailable(self, platform: str) -> bool:
        """Check if a platform has been marked unavailable."""
        return platform in self._unavailable
