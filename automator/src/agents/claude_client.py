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


class FitScoreResult(BaseModel):
    """Validated response from the Claude fit scoring call.

    Attributes:
        fit_score: Integer 0-100 representing job fit.
        rationale: Brief explanation of the score (max 200 words).
        deal_breaker_found: Whether a deal-breaker term was detected.
        deal_breaker_term: The specific deal-breaker term found, or None.
    """

    fit_score: int = Field(ge=0, le=100)
    rationale: str
    deal_breaker_found: bool
    deal_breaker_term: str | None = None


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

        Args:
            description: Full job description text.
            resume: Resume_Base content as plain text.
            goals: Goals_Profile as JSON string.

        Returns:
            Validated FitScoreResult with score, rationale, and deal-breaker info.

        Raises:
            ScoringError: If the API call fails after all retries or response
                validation fails.
        """
        system_prompt = (
            "You are an expert technical recruiter scoring job fit. "
            "You score using a weighted rubric and use the FULL 0-100 range. "
            "Most jobs should score either above 70 (strong fit) or below 40 (poor fit). "
            "Scores of 45-65 should be rare and reserved for genuinely ambiguous cases."
        )
        user_prompt = (
            "## Job Description\n"
            f"{description}\n\n"
            "## Candidate Resume\n"
            f"{resume}\n\n"
            "## Career Goals\n"
            f"{goals}\n\n"
            "## Scoring Rubric\n"
            "Score each dimension independently, then sum for the total fit_score.\n\n"
            "1. **Skills Match (0-35)**: Does this role use the candidate's actual "
            "technical skills, tools, and methodologies? Score 30-35 if core skills "
            "are a direct match. Score 15-25 if there's partial overlap. Score 0-10 "
            "if the required skills are in a different domain entirely.\n\n"
            "2. **Seniority/Level Fit (0-25)**: Is this the right career level? "
            "Score 20-25 if the years of experience and responsibility level match. "
            "Score 10-15 if slightly above or below. Score 0-5 if it requires "
            "15+ years, C-suite, or is entry-level.\n\n"
            "3. **Compensation Signals (0-20)**: Does the listed salary (if any) "
            "meet the candidate's minimum? Are there senior-level comp indicators "
            "(equity, bonus, band level)? Score 15-20 if comp looks right or isn't "
            "listed (benefit of the doubt). Score 5-10 if it seems low. Score 0 if "
            "salary is explicitly below minimum.\n\n"
            "4. **Role Substance (0-10)**: Is this a real hands-on technical/operational "
            "role? Score 8-10 for IC or hands-on leadership. Score 3-5 for consulting, "
            "sales engineering, or mostly-meetings roles. Score 0-2 for pure sales, "
            "recruiting, or compliance paperwork.\n\n"
            "5. **Logistics (0-10)**: Any hard blockers? Score 10 if US-based remote "
            "(any timezone PST-EST is fine). Deduct for: active security clearance "
            "required (-10), significant travel required (-5), non-US location (-10).\n\n"
            "## Deal-Breaker Rules\n"
            "Set deal_breaker_found=true ONLY if the job itself requires something "
            "listed in the candidate's deal-breakers. Only flag it if the role IS that "
            "thing (e.g., if 'Associate' is a deal-breaker, only flag if the role IS "
            "associate-level, NOT if the word appears in other contexts).\n\n"
            "## Response Format\n"
            "Respond with ONLY valid JSON (no markdown, no explanation):\n"
            "{\n"
            '  "fit_score": <integer 0-100, sum of all dimensions>,\n'
            '  "rationale": "<string, max 200 words, mention each dimension score>",\n'
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
