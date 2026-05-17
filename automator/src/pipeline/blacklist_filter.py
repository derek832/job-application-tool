"""Blacklist filter for excluding unwanted companies and title patterns.

Checks discovered jobs against user-configured blacklists before any Claude
API call. This is the cheapest possible filter point — it runs immediately
after discovery and saves tokens on obviously unwanted jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BlacklistConfig:
    """User-configured blacklist entries for filtering jobs at discovery time.

    Attributes:
        companies: Company names to exclude (case-insensitive exact match).
        title_patterns: Title substrings to exclude (case-insensitive substring match).
    """

    companies: list[str] = field(default_factory=list)
    title_patterns: list[str] = field(default_factory=list)


def check_blacklist(
    company: str,
    title: str,
    blacklist: BlacklistConfig,
) -> tuple[bool, str | None]:
    """Check if a job matches any blacklist entry.

    Performs company exact match first, then title substring match.
    Short-circuits on the first match found.

    Args:
        company: The job's company name.
        title: The job's title.
        blacklist: The configured blacklist to check against.

    Returns:
        A tuple of (is_blacklisted, matched_entry). matched_entry is a string
        like "company:Revature" or "title:intern" indicating which entry
        caused the match, or None if no match.
    """
    # Company matching: case-insensitive exact match
    company_lower = company.lower()
    for entry in blacklist.companies:
        if company_lower == entry.lower():
            logger.info(
                "blacklist_company_match",
                company=company,
                matched_entry=entry,
            )
            return True, f"company:{entry}"

    # Title pattern matching: case-insensitive substring match
    title_lower = title.lower()
    for pattern in blacklist.title_patterns:
        if pattern.lower() in title_lower:
            logger.info(
                "blacklist_title_match",
                title=title,
                matched_pattern=pattern,
            )
            return True, f"title:{pattern}"

    return False, None
