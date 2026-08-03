"""Claude API client wrapper for the LinkedIn Job Automator.

Provides typed async methods for fit scoring, resume tailoring, and cover letter
generation. All responses are validated against Pydantic schemas. Retries 3Ã—
with exponential backoff on API errors.
"""

from __future__ import annotations

import asyncio
import json

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError

from src.exceptions import ScoringError, TailoringError

logger = structlog.get_logger()

MODEL_TEXT = "claude-sonnet-5"
RETRY_BACKOFFS = [2, 5, 10]


# ---------------------------------------------------------------------------
# Cached prompt constants â€” stable text that gets cache_control breakpoints.
# Extracted to module level to keep line lengths clean and make caching intent
# explicit. These MUST NOT include variable content (job descriptions, etc.).
# ---------------------------------------------------------------------------

_SCORING_SYSTEM_PROMPT = """\
You are an expert recruiter and career coach. Analyze job fit \
objectively using structured dimensional scoring.

Score this job's fit for the candidate using 5 dimensions, each scored \
0-20. The final fit_score is the SUM of all dimensions (0-100).

## Dimensions

### 1. Skills & Tools Match (0-20)
Does the candidate have the technical skills, tools, and certifications \
listed in the job requirements?
- 16-20: Candidate has nearly all listed skills/tools or direct equivalents
- 12-15: Candidate has most skills, missing 1-2 that are learnable
- 8-11: Candidate has some relevant skills but meaningful gaps exist
- 4-7: Limited skill overlap, mostly adjacent/transferable
- 0-3: Almost no relevant skills for this role

CODING/SCRIPTING CALIBRATION: The candidate can handle ancillary scripting \
(SQL queries, basic Python automation, PowerShell admin tasks) but cannot \
independently build software or write production code. Apply this rule:
- If coding/engineering IS the primary job function (the role exists to write \
code â€” Software Engineer, DevOps building pipelines, AppSec doing code reviews, \
SIEM detection rule engineering): cap skills_match at 6/20 maximum.
- If scripting is ancillary (automation for security tasks, SQL for audit \
evidence, Python for report generation, PowerShell for admin): no penalty â€” \
the candidate can handle this.
- The test: 'Is this a coding job that involves security?' vs 'Is this a \
security job that involves some scripting?'

### 2. Experience Level Fit (0-20)
Is the seniority level appropriate for the candidate's experience?
- 16-20: Level is exactly right for the candidate's years and scope
- 12-15: Close match, maybe slightly senior or junior but credible
- 8-11: One level off â€” candidate could stretch up or would be overqualified
- 4-7: Two levels off â€” significant mismatch in expected scope
- 0-3: Completely wrong level (entry-level vs director, etc.)

YEARS CALIBRATION: Military IT/communications experience counts toward total \
career years at 66% weight for security-specific year requirements (the \
military role was IT/communications, not explicitly cybersecurity). Example: \
6 years military IT + 3 years civilian security = ~7 equivalent years for a \
'7+ years security experience' requirement.

### 3. Domain Transferability (0-20)
Is the candidate's domain experience relevant to this role?

CRITICAL CALIBRATION: Security and compliance work is highly cross-functional. \
Evaluate based on ACTUAL WORK PERFORMED, not title matching:
- Compliance framework experience transfers across ALL frameworks. Someone who \
has run SOC 2 + HIPAA + GDPR programs has directly applicable methodology for \
ISO 27001, NIST CSF, CMMC, PCI-DSS, FedRAMP, or any framework-based program. \
These frameworks share 70-75% of their control requirements (access management, \
change management, incident response, risk assessment, vendor management).
- A security professional who OWNS the full security function (compliance + \
infrastructure + operations) has hands-on experience across multiple \
specializations: deploying/managing security tools IS security engineering, \
managing vulnerability scanning IS vulnerability management, handling incidents \
IS detection & response, managing cloud security IS cloud security engineering.
- The question is: 'Could they do this job based on what they've actually done?' \
NOT 'Does their current title match the job title?'

EXCEPTION â€” Government compliance frameworks: FedRAMP, StateRAMP, CMMC, NIST \
800-53 authorization packages, and DoD compliance programs involve unique \
government-specific processes (authorization boundaries, POA&Ms, agency liaison, \
continuous monitoring to FISMA standards) that don't transfer 1:1 from commercial \
SOC 2/HIPAA/GDPR experience. If these are PRIMARY job responsibilities (not just \
'nice to have'), score domain_transferability 3-4 points lower than pure \
methodology overlap would suggest.

EXCEPTION â€” Specialist depth: Owning a broad security function demonstrates \
breadth but does not demonstrate specialist depth. For roles requiring 5+ years \
in a specific sub-domain (DFIR, SOC operations, IAM engineering, AppSec), \
evaluate based on demonstrated depth in THAT specific area, not overall \
security breadth.

- 16-20: Candidate's actual work experience directly covers this domain
- 12-15: Strong transferability â€” candidate has done this work as part of a \
broader role or in an adjacent context
- 8-11: Moderate transferability â€” related domain but would need to deepen \
in a specific area
- 4-7: Weak transferability â€” same broad field but different specialization
- 0-3: No meaningful domain overlap

### 4. Requirements Coverage (0-20)
What proportion of the job's stated requirements (must-haves and nice-to-haves) \
can the candidate credibly meet?
- 16-20: Meets 90%+ of requirements including all must-haves
- 12-15: Meets 70-89% of requirements, all critical must-haves covered
- 8-11: Meets 50-69% of requirements, some must-haves are gaps
- 4-7: Meets 30-49% of requirements, multiple must-have gaps
- 0-3: Meets fewer than 30% of requirements

### 5. Interview Likelihood (0-20)
Holistic REALITY CHECK: would a recruiter reviewing this resume for this \
specific role put it in the 'yes' pile for a phone screen?

Apply these suppressors BEFORE scoring:
- If the candidate is applying DOWN in level/scope (e.g., manager applying \
for analyst/tier-2 role): cap at 10/20
- If location doesn't match an onsite/hybrid requirement and relocation \
isn't mentioned: cap at 6/20
- If a core skill in the JOB TITLE is missing from the candidate's \
background (e.g., 'IAM Engineer' without deep IAM): cap at 10/20
- If the role type is fundamentally different from the candidate's career \
trajectory (e.g., internal auditor vs. practitioner, SOC analyst vs. \
program manager): subtract 4 points from your score

Then score within the remaining range:
- 16-20: Very likely â€” strong match, recruiter would be excited
- 12-15: Probable â€” solid candidate, would make the first cut
- 8-11: Possible â€” depends on applicant pool strength
- 4-7: Unlikely â€” would need a thin applicant pool
- 0-3: Would not get a callback

## Deal-Breaker Check
For deal_breaker_found: only set to true if the JOB ITSELF requires or \
is at a level matching a deal-breaker term from the candidate's goals. \
For example, if 'Associate' is a deal-breaker, only flag it if the role \
IS an associate-level position, NOT if the word appears in other contexts \
like 'associate with teams' or 'Associate's degree preferred'.

LOCATION CHECK: If the job explicitly requires onsite or hybrid presence \
in a specific city/region and the candidate is not in that area (and the \
job does not mention relocation assistance or is not marked remote), set \
deal_breaker_found=true with deal_breaker_term='location: [city]'.

## Response Format
Respond with ONLY valid JSON (no markdown, no explanation):
{
  "dimensions": {
    "skills_match": <int 0-20>,
    "experience_level": <int 0-20>,
    "domain_transferability": <int 0-20>,
    "requirements_coverage": <int 0-20>,
    "interview_likelihood": <int 0-20>
  },
  "fit_score": <int, MUST equal sum of all 5 dimensions>,
  "rationale": "<string, max 200 words explaining the key factors>",
  "deal_breaker_found": <boolean>,
  "deal_breaker_term": "<string or null>"
}"""

_TAILORING_SYSTEM_PROMPT = """\
You are an expert resume writer specializing in ATS optimization. \
You optimize resumes by providing targeted text replacements that \
incorporate keywords from job descriptions. You NEVER fabricate \
experience, skills, or credentials. You only rephrase existing \
content to better match ATS keyword scanning.

Analyze the job description and provide targeted text replacements to \
optimize the resume for ATS keyword matching. Rules:
- Each replacement must be an EXACT substring from the original resume
- Replace with ATS-optimized phrasing that incorporates job description keywords
- Preserve the meaning and factual accuracy of each bullet point
- Focus on: skill terms, action verbs, technical keywords, and industry phrases
- Do NOT change the person's name, contact info, dates, or company names
- Do NOT swap specific tool or product names for different ones (e.g. don't \
replace 'Vanta' with 'Drata' or 'Qualys' with 'Rapid7'). Only rephrase \
descriptions of what was done, not which tools were used to do it
- Do NOT change section headers (SUMMARY, CORE SKILLS, WORK EXPERIENCE, etc.)
- Do NOT change the bold category labels before colons (e.g. 'Security \
Operations:', 'Cloud & Infrastructure:'). Only replace the skill list text \
AFTER the colon
- Do NOT replace the SUMMARY's first sentence (the bold/italic headline that \
ends with a period before 'Built the program from scratch'). It has special \
formatting that breaks when replaced. Only replace text in the plain sentences \
that follow it
- For the CORE SKILLS section, do NOT include the category label in your find \
string. Find ONLY the skill list text after the colon and space
- Keep find strings SHORT (one phrase or clause, not entire bullet points)
- Aim for 8-15 targeted replacements (quality over quantity)

Respond with ONLY a valid JSON array of objects, no commentary:
[{"find": "exact text from resume", "replace": "optimized text"}]"""


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class DimensionScores(BaseModel):
    """Individual dimension scores from the sub-dimensional scoring system.

    Each dimension is scored 0-20. The sum produces the final fit_score (0-100).

    Attributes:
        skills_match: Does the candidate have the technical skills and tools listed?
        experience_level: Is the seniority level appropriate?
        domain_transferability: Is the candidate's domain experience relevant?
        requirements_coverage: What proportion of stated requirements can they meet?
        interview_likelihood: Holistic â€” would a recruiter put this in the "yes" pile?
    """

    skills_match: int = Field(ge=0, le=20)
    experience_level: int = Field(ge=0, le=20)
    domain_transferability: int = Field(ge=0, le=20)
    requirements_coverage: int = Field(ge=0, le=20)
    interview_likelihood: int = Field(ge=0, le=20)

    @property
    def total(self) -> int:
        """Sum of all dimension scores (0-100)."""
        return (
            self.skills_match
            + self.experience_level
            + self.domain_transferability
            + self.requirements_coverage
            + self.interview_likelihood
        )


class FitScoreResult(BaseModel):
    """Validated response from the Claude fit scoring call.

    Attributes:
        fit_score: Integer 0-100 representing job fit (sum of dimensions).
        rationale: Brief explanation of the score (max 200 words).
        deal_breaker_found: Whether a deal-breaker term was detected.
        deal_breaker_term: The specific deal-breaker term found, or None.
        dimensions: Individual dimension scores for debuggability.
    """

    fit_score: int = Field(ge=0, le=100)
    rationale: str
    deal_breaker_found: bool
    deal_breaker_term: str | None = None
    dimensions: DimensionScores | None = None



# ---------------------------------------------------------------------------
# Claude API client
# ---------------------------------------------------------------------------


class UsageResult(BaseModel):
    """Token usage and cost from a single Claude API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


# Pricing per million tokens (Claude Sonnet 5 â€” introductory through Aug 31, 2026)
_INPUT_COST_PER_M = 2.0
_OUTPUT_COST_PER_M = 10.0
_CACHE_WRITE_COST_PER_M = 2.50  # 1.25x input price
_CACHE_READ_COST_PER_M = 0.20  # 0.1x input price


def _calculate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Calculate USD cost from token counts including cache pricing.

    Args:
        input_tokens: Standard (uncached) input tokens.
        output_tokens: Output tokens generated.
        cache_creation_tokens: Tokens written to cache (1.25x input price).
        cache_read_tokens: Tokens read from cache (0.1x input price).
    """
    return (
        input_tokens * _INPUT_COST_PER_M
        + output_tokens * _OUTPUT_COST_PER_M
        + cache_creation_tokens * _CACHE_WRITE_COST_PER_M
        + cache_read_tokens * _CACHE_READ_COST_PER_M
    ) / 1_000_000


class ClaudeClient:
    """Async wrapper around the Anthropic Claude API.

    Provides domain-specific methods for the job application pipeline.
    All methods validate responses against Pydantic schemas and retry
    on transient API errors.

    Tracks cumulative token usage and cost across all API calls made through
    this instance via the ``total_cost_usd`` and ``last_call_cost`` attributes.

    Args:
        api_key: The Anthropic API key. Never logged.
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.total_cost_usd: float = 0.0
        self.last_call_cost: float = 0.0

    async def score_fit(
        self,
        description: str,
        resume: str,
        goals: str,
    ) -> FitScoreResult:
        """Score how well a job matches the candidate's resume and goals.

        Uses a sub-dimensional scoring approach: 5 dimensions scored 0-20 each,
        summed to produce a final 0-100 score. This prevents score clustering
        and provides transparent, debuggable scoring.

        Args:
            description: Full job description text.
            resume: Resume_Base content as plain text.
            goals: Goals_Profile as JSON string.

        Returns:
            Validated FitScoreResult with score, rationale, dimensions, and
            deal-breaker info.

        Raises:
            ScoringError: If the API call fails after all retries or response
                validation fails.
        """
        system_prompt = [
            {
                "type": "text",
                "text": _SCORING_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user_content = [
            {
                "type": "text",
                "text": ("## Candidate Resume\n" f"{resume}\n\n" "## Career Goals\n" f"{goals}"),
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"## Job Description\n{description}",
            },
        ]

        response_text = await self._call_with_retry(
            system=system_prompt,
            user=user_content,
            error_cls=ScoringError,
            context="fit scoring",
        )

        try:
            # Claude sometimes wraps JSON in markdown code blocks
            cleaned = self._extract_json(response_text)
            data = json.loads(cleaned)

            # Validate dimensions and compute/verify fit_score from sum
            if "dimensions" in data:
                dims = DimensionScores.model_validate(data["dimensions"])
                computed_score = dims.total
                # Use the computed sum as the authoritative score
                data["fit_score"] = computed_score
                data["dimensions"] = dims
            else:
                # Fallback: if Claude omits dimensions, still accept the score
                data["dimensions"] = None

            return FitScoreResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ScoringError(message=f"Failed to parse fit scoring response: {exc}") from exc

    async def tailor_resume(
        self,
        description: str,
        resume_base: str,
        supplementary_context: str | None = None,
    ) -> str:
        """Generate ATS-optimized text replacements for the resume.

        Returns a JSON array of {find, replace} pairs that can be applied
        to the original formatted document to optimize it for ATS without
        destroying the document's formatting/structure.

        Args:
            description: Full job description text.
            resume_base: The canonical Resume_Base content.
            supplementary_context: Additional experience notes or work details
                for richer keyword matching. Not included in the output resume.

        Returns:
            A JSON string containing an array of {find, replace} objects.

        Raises:
            TailoringError: If the API call fails after all retries.
        """
        system_prompt = [
            {
                "type": "text",
                "text": _TAILORING_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # Build cached resume + supplementary context block
        resume_text = f"## Original Resume (plain text)\n{resume_base}"
        if supplementary_context:
            resume_text += (
                "\n\n## Additional Candidate Context (use this to inform "
                "keyword choices, but do NOT add content that isn't already "
                "in the resume)\n"
                f"{supplementary_context}"
            )

        user_content = [
            {
                "type": "text",
                "text": resume_text,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"## Job Description\n{description}",
            },
        ]

        return await self._call_with_retry(
            system=system_prompt,
            user=user_content,
            error_cls=TailoringError,
            context="resume tailoring",
        )

    async def generate_cover_letter(
        self,
        description: str,
        tailored_resume: str,
        goals: str,
    ) -> str:
        """Generate a tailored cover letter for a job application.

        Args:
            description: Full job description text.
            tailored_resume: The ATS-optimized tailored resume content.
            goals: Goals_Profile as JSON string (includes career_objective).

        Returns:
            The generated cover letter text (250-400 words).

        Raises:
            TailoringError: If the API call fails after all retries.
        """
        system_prompt = (
            "You are an expert cover letter writer. Write compelling, concise cover "
            "letters that highlight relevant qualifications. Do NOT fabricate experience "
            "or credentials not present in the resume."
        )
        user_prompt = (
            "## Job Description\n"
            f"{description}\n\n"
            "## Tailored Resume\n"
            f"{tailored_resume}\n\n"
            "## Career Goals\n"
            f"{goals}\n\n"
            "Write a cover letter for this job application. Requirements:\n"
            "- Address it to the hiring team\n"
            "- Reference the specific job title and company name\n"
            "- Highlight 2-3 relevant qualifications from the resume\n"
            "- Be 250-400 words in length\n"
            "- Return only the cover letter text, no commentary"
        )

        return await self._call_with_retry(
            system=system_prompt,
            user=user_prompt,
            error_cls=TailoringError,
            context="cover letter generation",
        )


    # -----------------------------------------------------------------------
    # Internal retry helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_text_from_response(response) -> str:
        """Extract the text content from a Claude API response.

        Handles responses that include ThinkingBlocks (extended thinking)
        by finding the first TextBlock in the content array.

        Args:
            response: The raw API response from messages.create().

        Returns:
            The text content string.

        Raises:
            ValueError: If no text block is found in the response.
        """
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        raise ValueError(
            f"No text block found in response. "
            f"Block types: {[type(b).__name__ for b in response.content]}"
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from Claude's response, handling markdown code blocks.

        Claude sometimes wraps JSON in ```json ... ``` blocks. This strips
        that wrapper and returns the raw JSON string.

        Args:
            text: Raw response text from Claude.

        Returns:
            Cleaned JSON string ready for parsing.
        """
        text = text.strip()

        # Remove markdown code block wrapper if present
        if text.startswith("```"):
            # Remove opening ``` (with optional language tag)
            first_newline = text.index("\n") if "\n" in text else 3
            text = text[first_newline + 1 :]
            # Remove closing ```
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        # If it still doesn't start with { or [, try to find JSON in the text
        if not text.startswith(("{", "[")):
            start = text.find("{")
            if start != -1:
                # Find the matching closing brace
                text = text[start:]

        return text

    async def _call_with_retry(
        self,
        *,
        system: str | list[dict],
        user: str | list[dict],
        error_cls: type[Exception],
        context: str,
    ) -> str:
        """Make a Claude API text call with retry logic.

        Supports both simple string prompts and structured content blocks
        with cache_control markers for prompt caching.

        Args:
            system: System prompt as string or list of content blocks.
                Each block can include ``cache_control`` for caching.
            user: User prompt as string or list of content blocks.
                Each block can include ``cache_control`` for caching.
            error_cls: Exception class to raise on exhaustion.
            context: Description of the operation for logging.

        Returns:
            The text content from Claude's response.

        Raises:
            error_cls: If all retries are exhausted.
        """
        # Normalize system to structured format for the API
        if isinstance(system, str):
            system_param: str | list[dict] = system
        else:
            system_param = system

        # Normalize user content
        if isinstance(user, str):
            messages = [{"role": "user", "content": user}]
        else:
            messages = [{"role": "user", "content": user}]

        last_error: Exception | None = None

        for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
            try:
                response = await self._client.messages.create(
                    model=MODEL_TEXT,
                    max_tokens=4096,
                    system=system_param,
                    messages=messages,
                )
                # Track cost from usage data (including cache tokens)
                usage = response.usage
                cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                call_cost = _calculate_cost(
                    usage.input_tokens,
                    usage.output_tokens,
                    cache_creation,
                    cache_read,
                )
                self.last_call_cost = call_cost
                self.total_cost_usd += call_cost
                logger.info(
                    "claude_api_cost",
                    context=context,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                    cost_usd=round(call_cost, 6),
                    total_cost_usd=round(self.total_cost_usd, 6),
                )
                return self._extract_text_from_response(response)
            except anthropic.APIError as exc:
                last_error = exc
                logger.warning(
                    "claude_api_error",
                    context=context,
                    attempt=attempt,
                    max_attempts=len(RETRY_BACKOFFS),
                    error=str(exc),
                )
                if attempt < len(RETRY_BACKOFFS):
                    await asyncio.sleep(backoff)

        raise error_cls(
            message=f"Claude API call failed after {len(RETRY_BACKOFFS)} attempts "
            f"for {context}: {last_error}"
        )

