"""Claude API client wrapper for the LinkedIn Job Automator.

Provides typed async methods for fit scoring, resume tailoring, cover letter
generation, and visual form field identification. All responses are validated
against Pydantic schemas. Retries 3× with exponential backoff on API errors.
"""

from __future__ import annotations

import asyncio
import base64
import json

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError

from src.exceptions import ScoringError, TailoringError, VisionAgentError

logger = structlog.get_logger()

MODEL_TEXT = "claude-sonnet-4-6"
MODEL_VISION = "claude-sonnet-4-6"
RETRY_BACKOFFS = [2, 5, 10]


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
        interview_likelihood: Holistic — would a recruiter put this in the "yes" pile?
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


class FormField(BaseModel):
    """A single form field identified by the Vision Agent.

    Attributes:
        field_id: Unique identifier for the field on the page.
        label: Human-readable label of the field.
        field_type: Type of form input (text, select, checkbox, etc.).
        suggested_value: Suggested value to fill, or None if unknown.
    """

    field_id: str
    label: str
    field_type: str
    suggested_value: str | None = None


# ---------------------------------------------------------------------------
# Claude API client
# ---------------------------------------------------------------------------


class ClaudeClient:
    """Async wrapper around the Anthropic Claude API.

    Provides domain-specific methods for the job application pipeline.
    All methods validate responses against Pydantic schemas and retry
    on transient API errors.

    Args:
        api_key: The Anthropic API key. Never logged.
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

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
        system_prompt = (
            "You are an expert recruiter and career coach. Analyze job fit "
            "objectively using structured dimensional scoring."
        )
        user_prompt = (
            "## Job Description\n"
            f"{description}\n\n"
            "## Candidate Resume\n"
            f"{resume}\n\n"
            "## Career Goals\n"
            f"{goals}\n\n"
            "Score this job's fit for the candidate using 5 dimensions, each scored "
            "0-20. The final fit_score is the SUM of all dimensions (0-100).\n\n"
            "## Dimensions\n\n"
            "### 1. Skills & Tools Match (0-20)\n"
            "Does the candidate have the technical skills, tools, and certifications "
            "listed in the job requirements?\n"
            "- 16-20: Candidate has nearly all listed skills/tools or direct equivalents\n"
            "- 12-15: Candidate has most skills, missing 1-2 that are learnable\n"
            "- 8-11: Candidate has some relevant skills but meaningful gaps exist\n"
            "- 4-7: Limited skill overlap, mostly adjacent/transferable\n"
            "- 0-3: Almost no relevant skills for this role\n\n"
            "### 2. Experience Level Fit (0-20)\n"
            "Is the seniority level appropriate for the candidate's experience?\n"
            "- 16-20: Level is exactly right for the candidate's years and scope\n"
            "- 12-15: Close match, maybe slightly senior or junior but credible\n"
            "- 8-11: One level off — candidate could stretch up or would be overqualified\n"
            "- 4-7: Two levels off — significant mismatch in expected scope\n"
            "- 0-3: Completely wrong level (entry-level vs director, etc.)\n\n"
            "### 3. Domain Transferability (0-20)\n"
            "Is the candidate's domain experience relevant to this role?\n\n"
            "CRITICAL CALIBRATION: Security and compliance work is highly cross-functional. "
            "Evaluate based on ACTUAL WORK PERFORMED, not title matching:\n"
            "- Compliance framework experience transfers across ALL frameworks. Someone who "
            "has run SOC 2 + HIPAA + GDPR programs has directly applicable methodology for "
            "ISO 27001, NIST CSF, CMMC, PCI-DSS, FedRAMP, or any framework-based program. "
            "These frameworks share 70-75%% of their control requirements (access management, "
            "change management, incident response, risk assessment, vendor management).\n"
            "- A security professional who OWNS the full security function (compliance + "
            "infrastructure + operations) has hands-on experience across multiple "
            "specializations: deploying/managing security tools IS security engineering, "
            "managing vulnerability scanning IS vulnerability management, handling incidents "
            "IS detection & response, managing cloud security IS cloud security engineering.\n"
            "- The question is: 'Could they do this job based on what they've actually done?' "
            "NOT 'Does their current title match the job title?'\n\n"
            "- 16-20: Candidate's actual work experience directly covers this domain\n"
            "- 12-15: Strong transferability — candidate has done this work as part of a "
            "broader role or in an adjacent context\n"
            "- 8-11: Moderate transferability — related domain but would need to deepen "
            "in a specific area\n"
            "- 4-7: Weak transferability — same broad field but different specialization\n"
            "- 0-3: No meaningful domain overlap\n\n"
            "### 4. Requirements Coverage (0-20)\n"
            "What proportion of the job's stated requirements (must-haves and nice-to-haves) "
            "can the candidate credibly meet?\n"
            "- 16-20: Meets 90%%+ of requirements including all must-haves\n"
            "- 12-15: Meets 70-89%% of requirements, all critical must-haves covered\n"
            "- 8-11: Meets 50-69%% of requirements, some must-haves are gaps\n"
            "- 4-7: Meets 30-49%% of requirements, multiple must-have gaps\n"
            "- 0-3: Meets fewer than 30%% of requirements\n\n"
            "### 5. Interview Likelihood (0-20)\n"
            "Holistic assessment: would a recruiter reviewing this resume for this specific "
            "role put it in the 'yes' pile for a phone screen?\n"
            "- 16-20: Very likely — strong match, recruiter would be excited\n"
            "- 12-15: Probable — solid candidate, would make the first cut\n"
            "- 8-11: Possible — depends on applicant pool strength\n"
            "- 4-7: Unlikely — would need a thin applicant pool\n"
            "- 0-3: Would not get a callback\n\n"
            "## Deal-Breaker Check\n"
            "For deal_breaker_found: only set to true if the JOB ITSELF requires or "
            "is at a level matching a deal-breaker term from the candidate's goals. "
            "For example, if 'Associate' is a deal-breaker, only flag it if the role "
            "IS an associate-level position, NOT if the word appears in other contexts "
            "like 'associate with teams' or 'Associate's degree preferred'.\n\n"
            "## Response Format\n"
            "Respond with ONLY valid JSON (no markdown, no explanation):\n"
            "{\n"
            '  "dimensions": {\n'
            '    "skills_match": <int 0-20>,\n'
            '    "experience_level": <int 0-20>,\n'
            '    "domain_transferability": <int 0-20>,\n'
            '    "requirements_coverage": <int 0-20>,\n'
            '    "interview_likelihood": <int 0-20>\n'
            "  },\n"
            '  "fit_score": <int, MUST equal sum of all 5 dimensions>,\n'
            '  "rationale": "<string, max 200 words explaining the key factors>",\n'
            '  "deal_breaker_found": <boolean>,\n'
            '  "deal_breaker_term": "<string or null>"\n'
            "}"
        )

        response_text = await self._call_with_retry(
            system=system_prompt,
            user=user_prompt,
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
            raise ScoringError(
                message=f"Failed to parse fit scoring response: {exc}"
            ) from exc

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
        system_prompt = (
            "You are an expert resume writer specializing in ATS optimization. "
            "You optimize resumes by providing targeted text replacements that "
            "incorporate keywords from job descriptions. You NEVER fabricate "
            "experience, skills, or credentials. You only rephrase existing "
            "content to better match ATS keyword scanning."
        )

        context_section = ""
        if supplementary_context:
            context_section = (
                "\n\n## Additional Candidate Context (use this to inform keyword "
                "choices, but do NOT add content that isn't already in the resume)\n"
                f"{supplementary_context}\n"
            )

        user_prompt = (
            "## Job Description\n"
            f"{description}\n\n"
            "## Original Resume (plain text)\n"
            f"{resume_base}\n"
            f"{context_section}\n"
            "Analyze the job description and provide targeted text replacements to "
            "optimize this resume for ATS keyword matching. Rules:\n"
            "- Each replacement must be an EXACT substring from the original resume\n"
            "- Replace with ATS-optimized phrasing that incorporates job description keywords\n"
            "- Preserve the meaning and factual accuracy of each bullet point\n"
            "- Focus on: skill terms, action verbs, technical keywords, and industry phrases\n"
            "- Do NOT change the person's name, contact info, dates, or company names\n"
            "- Do NOT swap specific tool or product names for different ones (e.g. don't "
            "replace 'Vanta' with 'Drata' or 'Qualys' with 'Rapid7'). Only rephrase "
            "descriptions of what was done, not which tools were used to do it\n"
            "- Do NOT change section headers (SUMMARY, CORE SKILLS, WORK EXPERIENCE, etc.)\n"
            "- Do NOT change the bold category labels before colons (e.g. 'Security Operations:', "
            "'Cloud & Infrastructure:'). Only replace the skill list text AFTER the colon\n"
            "- Keep find strings SHORT (one phrase or clause, not entire bullet points)\n"
            "- Aim for 8-15 targeted replacements (quality over quantity)\n\n"
            "Respond with ONLY a valid JSON array of objects, no commentary:\n"
            '[{"find": "exact text from resume", "replace": "optimized text"}]\n'
        )

        return await self._call_with_retry(
            system=system_prompt,
            user=user_prompt,
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

    async def identify_form_fields(
        self,
        screenshot_bytes: bytes,
        profile: str,
    ) -> list[FormField]:
        """Identify form fields from a screenshot using Claude Vision.

        Args:
            screenshot_bytes: Raw PNG/JPEG screenshot bytes of the form.
            profile: User profile data as JSON string for context.

        Returns:
            List of identified FormField objects with suggested values.

        Raises:
            VisionAgentError: If the API call fails after all retries or
                response validation fails.
        """
        image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        system_prompt = (
            "You are an expert at identifying form fields in web page screenshots. "
            "Analyze the screenshot and identify all visible form fields."
        )
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            },
            {
                "type": "text",
                "text": (
                    "## User Profile (for context)\n"
                    f"{profile}\n\n"
                    "Identify all visible form fields in this screenshot. "
                    "For each field, provide a JSON array of objects with:\n"
                    "- field_id: a unique identifier (e.g., 'field_1', 'field_2')\n"
                    "- label: the visible label text\n"
                    "- field_type: the input type (text, select, checkbox, radio, "
                    "textarea, file)\n"
                    "- suggested_value: a suggested value based on the user profile, "
                    "or null if unknown\n\n"
                    "Respond with ONLY a valid JSON array, no commentary."
                ),
            },
        ]

        response_text = await self._call_with_retry_vision(
            system=system_prompt,
            user_content=user_content,
            error_cls=VisionAgentError,
            context="form field identification",
        )

        try:
            cleaned = self._extract_json(response_text)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                raise ValidationError.from_exception_data(
                    title="FormField",
                    line_errors=[],
                )
            return [FormField.model_validate(item) for item in data]
        except (json.JSONDecodeError, ValidationError) as exc:
            raise VisionAgentError(message=f"Failed to parse form field response: {exc}") from exc

    # -----------------------------------------------------------------------
    # Internal retry helpers
    # -----------------------------------------------------------------------

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
        system: str,
        user: str,
        error_cls: type[Exception],
        context: str,
    ) -> str:
        """Make a Claude API text call with retry logic.

        Args:
            system: System prompt.
            user: User prompt.
            error_cls: Exception class to raise on exhaustion.
            context: Description of the operation for logging.

        Returns:
            The text content from Claude's response.

        Raises:
            error_cls: If all retries are exhausted.
        """
        last_error: Exception | None = None

        for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
            try:
                response = await self._client.messages.create(
                    model=MODEL_TEXT,
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text
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

    async def _call_with_retry_vision(
        self,
        *,
        system: str,
        user_content: list[dict],
        error_cls: type[Exception],
        context: str,
    ) -> str:
        """Make a Claude API vision call with retry logic.

        Args:
            system: System prompt.
            user_content: List of content blocks (image + text).
            error_cls: Exception class to raise on exhaustion.
            context: Description of the operation for logging.

        Returns:
            The text content from Claude's response.

        Raises:
            error_cls: If all retries are exhausted.
        """
        last_error: Exception | None = None

        for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
            try:
                response = await self._client.messages.create(
                    model=MODEL_VISION,
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                )
                return response.content[0].text
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
