"""Draft answer generation for open-ended application questions.

Uses Claude to generate personalized draft answers for open-ended form fields
detected during external apply. Each answer is tailored to the specific job
description, the user's goals profile, and any supplementary context.

On Claude API failure: retries 3x with exponential backoff. If all retries
fail, returns None so the escalation can be created without drafts (the user
writes from scratch in the Review UI).

Validates: Requirements 2.1, 2.2
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypedDict

import structlog

from src.agents.claude_client import ClaudeClient

logger = structlog.get_logger(__name__)

# Retry configuration — matches the project's standard 3x with backoff
RETRY_BACKOFFS: list[int] = [2, 5, 10]


class DraftAnswer(TypedDict):
    """A single draft answer for an open-ended form field."""

    field_id: str
    question_text: str
    draft_answer: str


@dataclass
class OpenEndedQuestion:
    """Input representation of an open-ended question to answer.

    Can be constructed from an OpenEndedField or a plain dict.
    """

    field_id: str
    question_text: str


def _normalize_questions(
    questions: list[dict] | list,
) -> list[OpenEndedQuestion]:
    """Normalize question inputs into OpenEndedQuestion objects.

    Accepts either dicts with field_id/question_text keys, or objects
    with those attributes (like OpenEndedField dataclass instances).

    Args:
        questions: List of question dicts or OpenEndedField-like objects.

    Returns:
        List of normalized OpenEndedQuestion instances.
    """
    normalized: list[OpenEndedQuestion] = []
    for q in questions:
        if isinstance(q, dict):
            normalized.append(
                OpenEndedQuestion(
                    field_id=q["field_id"],
                    question_text=q.get("question_text") or q.get("label", ""),
                )
            )
        else:
            # Duck-type: assume it has field_id and question_text attributes
            normalized.append(
                OpenEndedQuestion(
                    field_id=q.field_id,
                    question_text=q.question_text,
                )
            )
    return normalized


def _build_prompt(
    question_text: str,
    job_description: str,
    goals_profile: str,
    supplementary_context: str | None,
) -> tuple[str, str]:
    """Build the system and user prompts for draft answer generation.

    Args:
        question_text: The specific open-ended question to answer.
        job_description: Full job description text.
        goals_profile: User's goals profile as a string (JSON or plain text).
        supplementary_context: Additional experience notes or context, or None.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are an expert job application writer. You write compelling, "
        "authentic answers to open-ended application questions. Your answers "
        "are specific to the role and draw on the candidate's real background. "
        "Do NOT fabricate experience, skills, or credentials not present in "
        "the provided context. Keep answers concise but substantive — typically "
        "3-5 sentences unless the question clearly warrants more."
    )

    context_section = ""
    if supplementary_context:
        context_section = (
            "\n\n## Additional Candidate Context\n"
            f"{supplementary_context}\n"
        )

    user_prompt = (
        "## Job Description\n"
        f"{job_description}\n\n"
        "## Candidate Background & Goals\n"
        f"{goals_profile}\n"
        f"{context_section}\n"
        "## Question\n"
        f"{question_text}\n\n"
        "Write a compelling answer to this application question. Requirements:\n"
        "- Be specific to this role and company\n"
        "- Draw on the candidate's actual background and goals\n"
        "- Be authentic and conversational, not generic or templated\n"
        "- Do NOT fabricate experience or credentials\n"
        "- Return only the answer text, no commentary or labels"
    )

    return system_prompt, user_prompt


async def _generate_single_answer(
    claude_client: ClaudeClient,
    question: OpenEndedQuestion,
    job_description: str,
    goals_profile: str,
    supplementary_context: str | None,
) -> DraftAnswer | None:
    """Generate a draft answer for a single question with retry logic.

    Retries 3x with exponential backoff on Claude API errors. Returns None
    if all retries are exhausted.

    Args:
        claude_client: The Claude API client instance.
        question: The question to answer.
        job_description: Full job description text.
        goals_profile: User's goals profile string.
        supplementary_context: Additional context or None.

    Returns:
        A DraftAnswer dict on success, or None if all retries fail.
    """
    system_prompt, user_prompt = _build_prompt(
        question_text=question.question_text,
        job_description=job_description,
        goals_profile=goals_profile,
        supplementary_context=supplementary_context,
    )

    last_error: Exception | None = None

    for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
        try:
            response_text = await claude_client._call_with_retry(
                system=system_prompt,
                user=user_prompt,
                error_cls=Exception,
                context=f"draft answer generation (field: {question.field_id})",
            )

            return DraftAnswer(
                field_id=question.field_id,
                question_text=question.question_text,
                draft_answer=response_text.strip(),
            )

        except Exception as exc:
            last_error = exc
            logger.warning(
                "draft_answer_generation_failed",
                field_id=question.field_id,
                attempt=attempt,
                max_attempts=len(RETRY_BACKOFFS),
                error=str(exc),
            )
            if attempt < len(RETRY_BACKOFFS):
                await asyncio.sleep(backoff)

    logger.error(
        "draft_answer_generation_exhausted",
        field_id=question.field_id,
        error=str(last_error),
    )
    return None


async def generate_draft_answers(
    questions: list[dict] | list,
    job_description: str,
    goals_profile: str,
    supplementary_context: str | None = None,
    *,
    claude_client: ClaudeClient | None = None,
) -> list[DraftAnswer] | None:
    """Generate draft answers for open-ended application questions using Claude.

    Calls Claude API with the job description, user goals, supplementary context,
    and each question to produce personalized answers. Questions are processed
    sequentially to avoid rate limiting.

    On Claude API failure for individual questions: retries 3x with exponential
    backoff. If ALL questions fail, returns None (escalation will be created
    without drafts). If some succeed and some fail, returns the successful
    answers only.

    Args:
        questions: List of open-ended questions — either dicts with
            ``field_id`` and ``question_text`` keys, or OpenEndedField
            dataclass instances.
        job_description: Full job description text for the role.
        goals_profile: User's goals profile as a string (typically JSON from
            GoalsProfile.model_dump_json()).
        supplementary_context: Additional experience notes, project details,
            or weekly work notes. Passed to Claude for richer context. None
            if not configured.
        claude_client: The Claude API client instance. Required for actual
            API calls; if None, returns None immediately (useful for testing
            or when Claude is unavailable).

    Returns:
        List of DraftAnswer dicts on success (may be partial if some questions
        failed). Returns None if claude_client is None or if ALL questions
        fail after retries.

    Validates: Requirements 2.1, 2.2
    """
    if claude_client is None:
        logger.warning("draft_answer_generation_skipped_no_client")
        return None

    if not questions:
        logger.debug("draft_answer_generation_skipped_no_questions")
        return []

    normalized = _normalize_questions(questions)

    logger.info(
        "draft_answer_generation_started",
        question_count=len(normalized),
        field_ids=[q.field_id for q in normalized],
    )

    draft_answers: list[DraftAnswer] = []

    for question in normalized:
        answer = await _generate_single_answer(
            claude_client=claude_client,
            question=question,
            job_description=job_description,
            goals_profile=goals_profile,
            supplementary_context=supplementary_context,
        )
        if answer is not None:
            draft_answers.append(answer)

    # If ALL questions failed, return None so escalation is created without drafts
    if not draft_answers:
        logger.error(
            "draft_answer_generation_all_failed",
            question_count=len(normalized),
        )
        return None

    logger.info(
        "draft_answer_generation_complete",
        total_questions=len(normalized),
        successful_answers=len(draft_answers),
        failed_answers=len(normalized) - len(draft_answers),
    )

    return draft_answers
