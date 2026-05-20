"""Pre-scoring filters to eliminate obviously irrelevant jobs before Claude API calls.

Applies cheap local checks (title exclusion, keyword presence, salary floor) to
skip jobs that clearly don't match the candidate's profile. Saves Claude API tokens
by only scoring jobs that pass basic relevance thresholds.

Uses a tiered keyword system:
- Core keywords: high-signal domain/framework terms (need fewer matches)
- Supporting keywords: tools/generic terms that appear in relevant AND irrelevant jobs
"""

from __future__ import annotations

import hashlib
import json
import re

import structlog

from src.agents.claude_client import ClaudeClient
from src.db.models import JobRecord

logger = structlog.get_logger(__name__)

# Minimum description length to be worth scoring (filters recruiter spam)
MIN_DESCRIPTION_LENGTH = 200

# Title-based negative signals: roles that are clearly platform-specific
# implementation positions or wrong domain entirely. Only matched against title.
TITLE_NEGATIVE_SIGNALS: list[str] = [
    "sailpoint",
    "servicenow developer",
    "servicenow admin",
    "workday developer",
    "workday consultant",
    "workday adaptive",
    "sap consultant",
    "sap admin",
    "salesforce admin",
    "salesforce developer",
    "salesforce architect",
    "oracle dba",
    "mainframe",
    "cobol",
    "peoplesoft",
    "data scientist",
    "machine learning engineer",
    "ml engineer",
    "frontend developer",
    "backend developer",
    "full stack developer",
    "ios developer",
    "android developer",
    "ux designer",
    "ui designer",
    "graphic designer",
    "accountant",
    "financial analyst",
    "recruiter",
    "talent acquisition",
    "hr generalist",
    "marketing manager",
    "sales representative",
    "account executive",
    "customer success",
    "physical security",
]


def check_title_exclusions(job_record: JobRecord, deal_breakers: list[str]) -> str | None:
    """Check if the job title contains any deal-breaker terms or negative signals.

    Performs case-insensitive substring matching against the job title for both
    user-configured deal-breakers and built-in negative signals (platform-specific
    roles that are clearly wrong domain).

    Args:
        job_record: The job record to check.
        deal_breakers: List of terms that disqualify a job by title.

    Returns:
        The matched term if found, or None if the title is clean.
    """
    title_lower = (job_record.job_title or "").lower()

    # Check user-configured deal-breakers
    for term in deal_breakers:
        if term.lower() in title_lower:
            return term

    # Check built-in negative signals (title-only, never description)
    for signal in TITLE_NEGATIVE_SIGNALS:
        if signal in title_lower:
            return f"title_signal:{signal}"

    return None


def check_description_length(job_record: JobRecord) -> bool:
    """Check if the job description meets the minimum length threshold.

    Very short descriptions are typically recruiter spam, aggregator noise,
    or placeholder postings not worth spending Claude tokens on.

    Args:
        job_record: The job record with description_text populated.

    Returns:
        True if the description is long enough to score. False if too short.
    """
    description = job_record.description_text or ""
    return len(description.strip()) >= MIN_DESCRIPTION_LENGTH


def check_keyword_presence(
    job_record: JobRecord,
    keywords: list[str],
    min_matches: int = 1,
) -> bool:
    """Check if the job description contains enough matching keywords.

    Supports tiered keyword matching when keywords are provided as a structured
    dict with 'core' and 'supporting' lists. Falls back to flat list matching
    for backward compatibility.

    Tiered logic:
    - Pass if ≥2 core keyword matches, OR
    - Pass if ≥1 core + ≥2 supporting matches, OR
    - Pass if ≥4 supporting matches

    Flat list logic (legacy):
    - Pass if ≥min_matches total keyword matches

    Args:
        job_record: The job record with description_text populated.
        keywords: List of relevant keywords for matching.
        min_matches: Minimum matches for flat list mode. Defaults to 1.

    Returns:
        True if the description contains sufficient keyword signal.
    """
    if not keywords:
        return True  # No keywords configured — pass everything through

    description_lower = (job_record.description_text or "").lower()
    if not description_lower:
        return False

    matches = sum(1 for kw in keywords if kw.lower() in description_lower)
    return matches >= min_matches


def check_tiered_keyword_presence(
    job_record: JobRecord,
    core_keywords: list[str],
    supporting_keywords: list[str],
) -> bool:
    """Check if the job description passes tiered keyword matching.

    Uses a weighted approach where core keywords (high-signal domain terms)
    require fewer matches than supporting keywords (common tools/generic terms).

    Pass conditions (any one is sufficient):
    - ≥2 core keyword matches
    - ≥1 core + ≥2 supporting matches
    - ≥4 supporting matches

    Args:
        job_record: The job record with description_text populated.
        core_keywords: High-signal domain/framework terms.
        supporting_keywords: Tools and generic terms that appear broadly.

    Returns:
        True if the description passes the tiered keyword filter.
    """
    if not core_keywords and not supporting_keywords:
        return True  # No keywords configured — pass everything through

    description_lower = (job_record.description_text or "").lower()
    if not description_lower:
        return False

    core_matches = sum(1 for kw in core_keywords if kw.lower() in description_lower)
    supporting_matches = sum(
        1 for kw in supporting_keywords if kw.lower() in description_lower
    )

    # Tiered pass conditions
    if core_matches >= 2:
        return True
    if core_matches >= 1 and supporting_matches >= 2:
        return True
    if supporting_matches >= 4:
        return True

    logger.debug(
        "prefilter_tiered_keyword_failed",
        job_id=job_record.id,
        title=job_record.job_title,
        core_matches=core_matches,
        supporting_matches=supporting_matches,
    )
    return False


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

    Makes a single cheap API call to extract 50-60 keywords organized into
    core (high-signal) and supporting (common/generic) tiers. These are used
    for pre-filtering job descriptions before full scoring.

    Args:
        claude_client: Configured Claude API client.
        supplementary_context: Additional experience notes.
        career_objective: Career objective statement.
        target_titles: List of target job titles.

    Returns:
        A list of lowercase keyword strings for matching (flat, for backward compat).
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
        "Return only a JSON object with tiered keyword lists."
    )
    user_prompt = (
        f"## Candidate Profile\n{profile_text}\n\n"
        "Extract 50-60 keywords and short phrases organized into two tiers. "
        "These will be used to pre-filter job descriptions before detailed scoring.\n\n"
        "## Tier Definitions\n\n"
        "**Core keywords** (25-30): High-signal terms that strongly indicate a relevant "
        "job. If a job description contains 2+ of these, it's almost certainly worth "
        "scoring. Include:\n"
        "- Compliance frameworks the candidate has used OR could credibly work with "
        "(SOC 2, HIPAA, GDPR, ISO 27001, NIST CSF, CMMC, PCI-DSS, FedRAMP, CCPA, etc.)\n"
        "- Core domain terms (grc, compliance, risk management, security program, "
        "vulnerability management, third-party risk, vendor risk, audit, controls, "
        "security governance, information security, data protection)\n"
        "- Security program activities (risk assessment, policy, security awareness, "
        "access control, change management, business continuity, incident response)\n"
        "- Role-level terms from target titles\n\n"
        "**Supporting keywords** (25-30): Terms that appear in relevant jobs but ALSO "
        "appear in many irrelevant jobs. Useful as confirming signal but not sufficient "
        "alone. Include:\n"
        "- Specific tools the candidate uses (crowdstrike, okta, vanta, qualys, rapid7, etc.)\n"
        "- Cloud/infrastructure terms (aws, azure, cloud security, iam)\n"
        "- Generic security terms (endpoint security, siem, firewall, encryption)\n"
        "- Adjacent domain terms (penetration testing, security operations, soc, "
        "detection, monitoring)\n\n"
        "Do NOT include:\n"
        "- Generic soft skills (leadership, communication, team player)\n"
        "- Overly broad terms that match everything (technology, software, management)\n"
        "- Platform-specific implementation terms (sailpoint, servicenow, workday) — "
        "these are handled separately as negative signals\n\n"
        "Respond with ONLY valid JSON matching this schema:\n"
        '{"core": ["keyword1", "keyword2", ...], "supporting": ["keyword1", ...]}\n'
    )

    try:
        response = await claude_client._call_with_retry(
            system=system_prompt,
            user=user_prompt,
            error_cls=ScoringError,
            context="keyword extraction",
        )
        cleaned = claude_client._extract_json(response)
        data = json.loads(cleaned)

        if isinstance(data, dict) and "core" in data and "supporting" in data:
            core = [str(kw).lower().strip() for kw in data["core"] if kw]
            supporting = [str(kw).lower().strip() for kw in data["supporting"] if kw]
            logger.info(
                "prefilter_tiered_keywords_generated",
                core_count=len(core),
                supporting_count=len(supporting),
            )
            # Return flat list for backward compat (stored together)
            # The tiered structure is preserved in the config store
            return core + supporting
        elif isinstance(data, list):
            # Fallback: Claude returned a flat list
            keywords = [str(kw).lower().strip() for kw in data if kw]
            logger.info("prefilter_keywords_generated_flat", count=len(keywords))
            return keywords
    except Exception as exc:
        logger.error("prefilter_keyword_generation_failed", error=str(exc))

    return []


async def generate_tiered_filter_keywords(
    claude_client: ClaudeClient,
    supplementary_context: str | None,
    career_objective: str | None,
    target_titles: list[str],
) -> dict[str, list[str]]:
    """Use Claude to extract tiered filter keywords from the user's profile.

    Returns a structured dict with 'core' and 'supporting' keyword lists
    for use with the tiered matching logic.

    Args:
        claude_client: Configured Claude API client.
        supplementary_context: Additional experience notes.
        career_objective: Career objective statement.
        target_titles: List of target job titles.

    Returns:
        Dict with 'core' and 'supporting' keyword lists.
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
        return {"core": [], "supporting": []}

    profile_text = "\n\n".join(context_parts)

    system_prompt = (
        "You extract job-matching keywords from candidate profiles. "
        "Return only a JSON object with tiered keyword lists."
    )
    user_prompt = (
        f"## Candidate Profile\n{profile_text}\n\n"
        "Extract 50-60 keywords and short phrases organized into two tiers. "
        "These will be used to pre-filter job descriptions before detailed scoring.\n\n"
        "## Tier Definitions\n\n"
        "**Core keywords** (25-30): High-signal terms that strongly indicate a relevant "
        "job. If a job description contains 2+ of these, it's almost certainly worth "
        "scoring. Include:\n"
        "- Compliance frameworks the candidate has used OR could credibly work with "
        "(SOC 2, HIPAA, GDPR, ISO 27001, NIST CSF, CMMC, PCI-DSS, FedRAMP, CCPA, etc.)\n"
        "- Core domain terms (grc, compliance, risk management, security program, "
        "vulnerability management, third-party risk, vendor risk, audit, controls, "
        "security governance, information security, data protection)\n"
        "- Security program activities (risk assessment, policy, security awareness, "
        "access control, change management, business continuity, incident response)\n"
        "- Role-level terms from target titles\n\n"
        "**Supporting keywords** (25-30): Terms that appear in relevant jobs but ALSO "
        "appear in many irrelevant jobs. Useful as confirming signal but not sufficient "
        "alone. Include:\n"
        "- Specific tools the candidate uses (crowdstrike, okta, vanta, qualys, rapid7, etc.)\n"
        "- Cloud/infrastructure terms (aws, azure, cloud security, iam)\n"
        "- Generic security terms (endpoint security, siem, firewall, encryption)\n"
        "- Adjacent domain terms (penetration testing, security operations, soc, "
        "detection, monitoring)\n\n"
        "Do NOT include:\n"
        "- Generic soft skills (leadership, communication, team player)\n"
        "- Overly broad terms that match everything (technology, software, management)\n"
        "- Platform-specific implementation terms (sailpoint, servicenow, workday) — "
        "these are handled separately as negative signals\n\n"
        "Respond with ONLY valid JSON matching this schema:\n"
        '{"core": ["keyword1", "keyword2", ...], "supporting": ["keyword1", ...]}\n'
    )

    try:
        response = await claude_client._call_with_retry(
            system=system_prompt,
            user=user_prompt,
            error_cls=ScoringError,
            context="tiered keyword extraction",
        )
        cleaned = claude_client._extract_json(response)
        data = json.loads(cleaned)

        if isinstance(data, dict) and "core" in data and "supporting" in data:
            core = [str(kw).lower().strip() for kw in data["core"] if kw]
            supporting = [str(kw).lower().strip() for kw in data["supporting"] if kw]
            logger.info(
                "prefilter_tiered_keywords_generated",
                core_count=len(core),
                supporting_count=len(supporting),
            )
            return {"core": core, "supporting": supporting}
        elif isinstance(data, list):
            # Fallback: split flat list roughly in half
            keywords = [str(kw).lower().strip() for kw in data if kw]
            mid = len(keywords) // 2
            return {"core": keywords[:mid], "supporting": keywords[mid:]}
    except Exception as exc:
        logger.error("prefilter_tiered_keyword_generation_failed", error=str(exc))

    return {"core": [], "supporting": []}


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
