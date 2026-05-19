"""Pre-scoring filters to eliminate obviously irrelevant jobs before Claude API calls.

Applies cheap local checks (title exclusion, keyword presence) to skip jobs
that clearly don't match the candidate's profile. Saves Claude API tokens by
only scoring jobs that pass basic relevance thresholds.
"""

from __future__ import annotations

import hashlib
import json
import re

import structlog

from src.agents.claude_client import ClaudeClient
from src.db.models import JobRecord

logger = structlog.get_logger(__name__)

# Minimum number of matching keywords required in a job description
MIN_KEYWORD_MATCHES = 1


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


# ---------------------------------------------------------------------------
# Salary extraction and filtering
# ---------------------------------------------------------------------------

# Regex patterns for salary extraction from job descriptions
_SALARY_PATTERNS: list[re.Pattern[str]] = [
    # $120,000 - $150,000 or $120000-$150000
    re.compile(
        r"\$\s*([\d,]+)\s*(?:[-–—to]+)\s*\$\s*([\d,]+)\s*(?:per\s*year|\/yr|annually|a\s*year)?",
        re.IGNORECASE,
    ),
    # $120K - $150K or $120k-$150k or $115K/yr - $125K/yr
    re.compile(
        r"\$\s*(\d+)\s*[kK]\s*(?:\/yr|\/year)?\s*[-–—to]+\s*\$?\s*(\d+)\s*[kK]\s*(?:\/yr|\/year|per\s*year|annually)?",
        re.IGNORECASE,
    ),
    # $60/hr - $75/hr or $60-$75 per hour
    re.compile(
        r"\$\s*([\d.]+)\s*(?:\/hr|\/hour)?\s*[-–—to]+\s*\$?\s*([\d.]+)\s*(?:per\s*hour|\/hr|\/hour|hourly|an?\s*hour)",
        re.IGNORECASE,
    ),
    # 120,000 - 150,000 (no dollar sign but with range)
    re.compile(
        r"(\d{2,3},\d{3})\s*[-–—to]+\s*(\d{2,3},\d{3})\s*(?:per\s*year|\/yr|annually)?",
        re.IGNORECASE,
    ),
    # Single salary: $120,000 or $120K
    re.compile(
        r"\$\s*([\d,]+)\s*(?:per\s*year|\/yr|annually|a\s*year)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\$\s*(\d+)\s*[kK]\s*(?:per\s*year|\/yr|annually)?",
        re.IGNORECASE,
    ),
]

HOURS_PER_YEAR = 2080


def extract_salary_range(text: str) -> tuple[int | None, int | None]:
    """Extract salary range from job description or title text.

    Parses various salary formats and normalizes to annual amounts.
    Hourly rates are converted to annual (×2080 hours).

    Args:
        text: The job description or card subtitle text.

    Returns:
        Tuple of (min_salary, max_salary) as integers, or (None, None)
        if no salary information is found.
    """
    if not text:
        return None, None

    # Try hourly pattern first (needs conversion)
    hourly_match = _SALARY_PATTERNS[2].search(text)
    if hourly_match:
        low = float(hourly_match.group(1))
        high = float(hourly_match.group(2))
        return int(low * HOURS_PER_YEAR), int(high * HOURS_PER_YEAR)

    # Try range patterns (annual)
    for pattern in [_SALARY_PATTERNS[0], _SALARY_PATTERNS[3]]:
        match = pattern.search(text)
        if match:
            low = int(match.group(1).replace(",", ""))
            high = int(match.group(2).replace(",", ""))
            # Sanity check: if values look like they're in thousands already
            if low < 1000:
                low *= 1000
            if high < 1000:
                high *= 1000
            return low, high

    # Try K notation range
    k_match = _SALARY_PATTERNS[1].search(text)
    if k_match:
        low = int(k_match.group(1)) * 1000
        high = int(k_match.group(2)) * 1000
        return low, high

    # Try single salary with /yr
    single_match = _SALARY_PATTERNS[4].search(text)
    if single_match:
        val = int(single_match.group(1).replace(",", ""))
        if val < 1000:
            val *= 1000
        return val, val

    # Single K notation
    single_k = _SALARY_PATTERNS[5].search(text)
    if single_k:
        val = int(single_k.group(1)) * 1000
        return val, val

    return None, None


def check_salary_filter(
    job_record: JobRecord,
    min_salary: int | None,
) -> bool:
    """Check if a job's salary range meets the minimum salary requirement.

    Extracts salary from the job description and compares the maximum
    offered salary against the user's minimum requirement. If the max
    salary is below the minimum, the job is filtered out.

    Args:
        job_record: The job record with description_text.
        min_salary: The user's minimum acceptable salary, or None to skip.

    Returns:
        True if the job passes the salary filter (should proceed to scoring).
        False if the salary is definitively below the minimum.
    """
    if min_salary is None:
        return True  # No minimum set — pass everything

    # Try to extract salary from description
    text = job_record.description_text or ""
    sal_min, sal_max = extract_salary_range(text)

    if sal_min is None and sal_max is None:
        return True  # No salary info found — can't filter, pass through

    # Use the max of the range for comparison (give benefit of the doubt)
    max_offered = sal_max or sal_min
    if max_offered is None:
        return True

    # Filter out if the max offered is below the user's minimum
    if max_offered < min_salary:
        logger.info(
            "prefilter_salary_excluded",
            job_id=job_record.id,
            title=job_record.job_title,
            salary_range=f"{sal_min}-{sal_max}",
            min_salary=min_salary,
        )
        return False

    return True
