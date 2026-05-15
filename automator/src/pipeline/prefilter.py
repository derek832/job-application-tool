"""Pre-scoring filters to eliminate obviously irrelevant jobs before Claude API calls.

Applies cheap local checks (title exclusion, keyword presence) to skip jobs
that clearly don't match the candidate's profile. Saves Claude API tokens by
only scoring jobs that pass basic relevance thresholds.
"""

from __future__ import annotations

import hashlib
import json

import structlog

from src.agents.claude_client import ClaudeClient
from src.db.models import JobRecord

logger = structlog.get_logger(__name__)

# Minimum number of matching keywords required in a job description
MIN_KEYWORD_MATCHES = 2


def check_title_exclusions(job_record: JobRecord, deal_breakers: list[str]) -> str | None:
    """Check if the job title contains any deal-breaker terms.

    Performs case-insensitive word-boundary matching against the job title.
    This is a quick pre-filter — Claude still does contextual deal-breaker
    analysis during scoring for edge cases.

    Args:
        job_record: The job record to check.
        deal_breakers: List of terms that disqualify a job by title.

    Returns:
        The matched deal-breaker term if found, or None if the title is clean.
    """
    title_lower = (job_record.job_title or "").lower()

    for term in deal_breakers:
        if term.lower() in title_lower:
            return term

    return None


def check_keyword_presence(
    job_record: JobRecord,
    keywords: list[str],
    min_matches: int = MIN_KEYWORD_MATCHES,
) -> bool:
    """Check if the job description contains enough matching keywords.

    Performs case-insensitive substring matching of extracted keywords against
    the full job description text.

    Args:
        job_record: The job record with description_text populated.
        keywords: List of relevant skill/domain keywords to check for.
        min_matches: Minimum number of keywords that must appear. Defaults to 2.

    Returns:
        True if the description contains at least min_matches keywords.
    """
    if not keywords:
        return True  # No keywords configured — pass everything through

    description_lower = (job_record.description_text or "").lower()
    if not description_lower:
        return False

    matches = sum(1 for kw in keywords if kw.lower() in description_lower)
    return matches >= min_matches


def compute_context_hash(
    supplementary_context: str | None,
    career_objective: str | None,
    target_titles: list[str],
) -> str:
    """Compute a hash of the inputs used to generate filter keywords.

    Used to detect when the user's profile has changed and keywords need
    to be regenerated.

    Args:
        supplementary_context: The supplementary context text.
        career_objective: The career objective text.
        target_titles: List of target job titles.

    Returns:
        A hex digest string representing the current state.
    """
    content = json.dumps(
        {
            "supplementary_context": supplementary_context or "",
            "career_objective": career_objective or "",
            "target_titles": sorted(target_titles),
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def generate_filter_keywords(
    claude_client: ClaudeClient,
    supplementary_context: str | None,
    career_objective: str | None,
    target_titles: list[str],
) -> list[str]:
    """Use Claude to extract relevant filter keywords from the user's profile.

    Makes a single cheap API call to extract 20-30 keywords that represent
    the candidate's skills, tools, and domain expertise. These are used for
    pre-filtering job descriptions before full scoring.

    Args:
        claude_client: Configured Claude API client.
        supplementary_context: Additional experience notes.
        career_objective: Career objective statement.
        target_titles: List of target job titles.

    Returns:
        A list of lowercase keyword strings for matching.
    """
    from src.exceptions import ScoringError

    context_parts = []
    if target_titles:
        context_parts.append(f"Target roles: {', '.join(target_titles)}")
    if career_objective:
        context_parts.append(f"Career objective: {career_objective}")
    if supplementary_context:
        context_parts.append(f"Experience details:\n{supplementary_context}")

    if not context_parts:
        logger.warning("prefilter_no_context_for_keywords")
        return []

    profile_text = "\n\n".join(context_parts)

    system_prompt = (
        "You extract job-matching keywords from candidate profiles. "
        "Return only a JSON array of lowercase keyword strings."
    )
    user_prompt = (
        f"## Candidate Profile\n{profile_text}\n\n"
        "Extract 20-30 keywords and short phrases that represent this candidate's "
        "skills, tools, certifications, and domain expertise. These will be used to "
        "pre-filter job descriptions — a job should contain at least 2 of these "
        "keywords to be worth detailed analysis.\n\n"
        "Include:\n"
        "- Technical skills and tools (e.g. 'vulnerability management', 'aws', 'soc 2')\n"
        "- Domain terms (e.g. 'grc', 'compliance', 'incident response')\n"
        "- Certifications (e.g. 'security+', 'cissp', 'cisa')\n"
        "- Role-level terms (e.g. 'security manager', 'security engineer')\n\n"
        "Do NOT include generic terms like 'leadership', 'communication', 'team'.\n\n"
        "Respond with ONLY a valid JSON array of lowercase strings, no commentary."
    )

    try:
        response = await claude_client._call_with_retry(
            system=system_prompt,
            user=user_prompt,
            error_cls=ScoringError,
            context="keyword extraction",
        )
        cleaned = claude_client._extract_json(response)
        keywords = json.loads(cleaned)
        if isinstance(keywords, list):
            keywords = [str(kw).lower().strip() for kw in keywords if kw]
            logger.info("prefilter_keywords_generated", count=len(keywords))
            return keywords
    except Exception as exc:
        logger.error("prefilter_keyword_generation_failed", error=str(exc))

    return []
