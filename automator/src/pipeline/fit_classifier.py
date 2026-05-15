"""Fit score classification and deal-breaker detection for the job pipeline.

Pure functions that classify jobs based on fit scores, detect deal-breaker terms,
and identify threshold boundary conditions requiring human review.
"""

from typing import Literal


def classify_fit(
    score: int,
    good_fit_threshold: int,
    stretch_threshold: int,
) -> Literal["good_fit", "stretch_role", "skip"]:
    """Classify a job based on its fit score relative to configured thresholds.

    Args:
        score: The fit score (0-100) returned by the Claude API.
        good_fit_threshold: Score at or above which a job is a good fit.
        stretch_threshold: Score at or above which (but below good_fit_threshold)
            a job is a stretch role.

    Returns:
        One of "good_fit", "stretch_role", or "skip".
    """
    if score >= good_fit_threshold:
        return "good_fit"
    if score >= stretch_threshold:
        return "stretch_role"
    return "skip"


def has_deal_breaker(
    description_text: str,
    deal_breakers: list[str],
) -> tuple[bool, str | None]:
    """Check if a job description contains any deal-breaker terms.

    Performs case-insensitive substring matching against the description text
    for each term in the deal-breakers list.

    Args:
        description_text: The full job description text to search.
        deal_breakers: List of deal-breaker keywords/phrases to check for.

    Returns:
        A tuple of (found, matched_term). If a deal-breaker is found, returns
        (True, matched_term). Otherwise returns (False, None).
    """
    description_lower = description_text.lower()
    for term in deal_breakers:
        if term.lower() in description_lower:
            return (True, term)
    return (False, None)


def is_threshold_boundary(
    score: int,
    good_fit_threshold: int,
    stretch_threshold: int,
    margin: int = 2,
) -> bool:
    """Determine if a score falls within the boundary margin of either threshold.

    Scores near threshold boundaries require human review because small scoring
    variations could change the classification.

    Args:
        score: The fit score (0-100) to check.
        good_fit_threshold: The good-fit threshold value.
        stretch_threshold: The stretch-role threshold value.
        margin: The boundary margin (inclusive). Defaults to 2.

    Returns:
        True if the score is within ±margin of either threshold, False otherwise.
    """
    return abs(score - good_fit_threshold) <= margin or abs(score - stretch_threshold) <= margin
