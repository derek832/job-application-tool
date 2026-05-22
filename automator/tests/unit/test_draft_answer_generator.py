"""Unit tests for the draft answer generator module.

Tests the generate_draft_answers function including:
- Successful generation for single and multiple questions
- Handling of dict and object inputs
- Retry behavior on Claude API failures
- Return None when all questions fail
- Partial success (some questions succeed, some fail)
- Edge cases: empty questions list, no claude_client
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from src.pipeline.draft_answer_generator import (
    _build_prompt,
    _normalize_questions,
    generate_draft_answers,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeOpenEndedField:
    """Mimics the OpenEndedField dataclass for testing duck-typing."""

    field_id: str
    label: str
    selector: str
    question_text: str
    char_limit: int | None


@pytest.fixture
def sample_questions_dicts() -> list[dict]:
    """Sample questions as dicts."""
    return [
        {
            "field_id": "field_1",
            "question_text": "Why are you interested in this role?",
        },
        {
            "field_id": "field_2",
            "question_text": "Describe your experience with distributed systems.",
        },
    ]


@pytest.fixture
def sample_questions_objects() -> list[FakeOpenEndedField]:
    """Sample questions as OpenEndedField-like objects."""
    return [
        FakeOpenEndedField(
            field_id="field_1",
            label="Interest",
            selector="#q1",
            question_text="Why are you interested in this role?",
            char_limit=500,
        ),
    ]


@pytest.fixture
def job_description() -> str:
    return "Senior Python Engineer at Acme Corp. Build scalable backend services."


@pytest.fixture
def goals_profile() -> str:
    return '{"target_titles": ["Senior Engineer"], "career_objective": "Build impactful systems"}'


@pytest.fixture
def mock_claude_client() -> AsyncMock:
    """Create a mock Claude client with _call_with_retry."""
    client = AsyncMock()
    client._call_with_retry = AsyncMock(
        return_value="I'm drawn to Acme's mission of building scalable systems."
    )
    return client


# ---------------------------------------------------------------------------
# Tests: _normalize_questions
# ---------------------------------------------------------------------------


class TestNormalizeQuestions:
    """Tests for the _normalize_questions helper."""

    def test_normalizes_dicts(self, sample_questions_dicts: list[dict]) -> None:
        """Dict inputs are normalized to OpenEndedQuestion objects."""
        result = _normalize_questions(sample_questions_dicts)
        assert len(result) == 2
        assert result[0].field_id == "field_1"
        assert result[0].question_text == "Why are you interested in this role?"
        assert result[1].field_id == "field_2"

    def test_normalizes_objects(self, sample_questions_objects: list[FakeOpenEndedField]) -> None:
        """Object inputs with field_id/question_text attributes are normalized."""
        result = _normalize_questions(sample_questions_objects)
        assert len(result) == 1
        assert result[0].field_id == "field_1"
        assert result[0].question_text == "Why are you interested in this role?"

    def test_dict_falls_back_to_label(self) -> None:
        """If question_text is missing from dict, falls back to label."""
        questions = [{"field_id": "f1", "label": "Tell us about yourself"}]
        result = _normalize_questions(questions)
        assert result[0].question_text == "Tell us about yourself"


# ---------------------------------------------------------------------------
# Tests: _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for the _build_prompt helper."""

    def test_includes_job_description(self) -> None:
        """Job description appears in the user prompt."""
        _, user = _build_prompt(
            "Why this role?", "Engineer at Acme", '{"goals": "grow"}', None
        )
        assert "Engineer at Acme" in user

    def test_includes_goals_profile(self) -> None:
        """Goals profile appears in the user prompt."""
        _, user = _build_prompt(
            "Why this role?", "Job desc", '{"career_objective": "lead teams"}', None
        )
        assert "lead teams" in user

    def test_includes_supplementary_context_when_provided(self) -> None:
        """Supplementary context section is included when not None."""
        _, user = _build_prompt(
            "Why this role?", "Job desc", "goals", "Built a distributed cache at scale"
        )
        assert "Additional Candidate Context" in user
        assert "distributed cache" in user

    def test_excludes_supplementary_context_when_none(self) -> None:
        """No supplementary context section when None."""
        _, user = _build_prompt("Why this role?", "Job desc", "goals", None)
        assert "Additional Candidate Context" not in user

    def test_includes_question_text(self) -> None:
        """The specific question appears in the user prompt."""
        _, user = _build_prompt(
            "What motivates you?", "Job desc", "goals", None
        )
        assert "What motivates you?" in user

    def test_system_prompt_prevents_fabrication(self) -> None:
        """System prompt instructs Claude not to fabricate."""
        system, _ = _build_prompt("Q?", "desc", "goals", None)
        assert "fabricate" in system.lower()


# ---------------------------------------------------------------------------
# Tests: generate_draft_answers
# ---------------------------------------------------------------------------


class TestGenerateDraftAnswers:
    """Tests for the main generate_draft_answers function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_client(
        self, sample_questions_dicts: list[dict], job_description: str, goals_profile: str
    ) -> None:
        """Returns None when claude_client is None."""
        result = await generate_draft_answers(
            questions=sample_questions_dicts,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_questions(
        self, mock_claude_client: AsyncMock, job_description: str, goals_profile: str
    ) -> None:
        """Returns empty list when no questions provided."""
        result = await generate_draft_answers(
            questions=[],
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_generates_answers_for_dict_questions(
        self,
        sample_questions_dicts: list[dict],
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Successfully generates draft answers from dict inputs."""
        result = await generate_draft_answers(
            questions=sample_questions_dicts,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is not None
        assert len(result) == 2
        assert result[0]["field_id"] == "field_1"
        assert result[0]["question_text"] == "Why are you interested in this role?"
        assert "Acme" in result[0]["draft_answer"]
        assert result[1]["field_id"] == "field_2"

    @pytest.mark.asyncio
    async def test_generates_answers_for_object_questions(
        self,
        sample_questions_objects: list[FakeOpenEndedField],
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Successfully generates draft answers from object inputs."""
        result = await generate_draft_answers(
            questions=sample_questions_objects,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["field_id"] == "field_1"

    @pytest.mark.asyncio
    async def test_passes_supplementary_context(
        self,
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Supplementary context is passed through to the Claude prompt."""
        questions = [{"field_id": "f1", "question_text": "Why this role?"}]
        await generate_draft_answers(
            questions=questions,
            job_description=job_description,
            goals_profile=goals_profile,
            supplementary_context="Led a team of 5 engineers",
            claude_client=mock_claude_client,
        )
        # Verify the user prompt passed to _call_with_retry contains the context
        call_kwargs = mock_claude_client._call_with_retry.call_args_list[0].kwargs
        assert "Led a team of 5 engineers" in call_kwargs["user"]

    @pytest.mark.asyncio
    @patch("src.pipeline.draft_answer_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_returns_none_when_all_fail(
        self,
        mock_sleep: AsyncMock,
        sample_questions_dicts: list[dict],
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Returns None when all questions fail after retries."""
        mock_claude_client._call_with_retry = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        result = await generate_draft_answers(
            questions=sample_questions_dicts,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("src.pipeline.draft_answer_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_partial_success(
        self,
        mock_sleep: AsyncMock,
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Returns successful answers even when some questions fail."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # First question succeeds on first try, second always fails
            if "field_1" in kwargs.get("context", ""):
                return "Great answer for field 1"
            raise Exception("API error")

        mock_claude_client._call_with_retry = AsyncMock(side_effect=side_effect)

        questions = [
            {"field_id": "field_1", "question_text": "Q1?"},
            {"field_id": "field_2", "question_text": "Q2?"},
        ]

        result = await generate_draft_answers(
            questions=questions,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["field_id"] == "field_1"
        assert result[0]["draft_answer"] == "Great answer for field 1"

    @pytest.mark.asyncio
    @patch("src.pipeline.draft_answer_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_failure_then_succeeds(
        self,
        mock_sleep: AsyncMock,
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Retries on first failure and succeeds on subsequent attempt."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Transient error")
            return "Answer after retry"

        mock_claude_client._call_with_retry = AsyncMock(side_effect=side_effect)

        questions = [{"field_id": "f1", "question_text": "Q?"}]

        result = await generate_draft_answers(
            questions=questions,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["draft_answer"] == "Answer after retry"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(
        self,
        mock_claude_client: AsyncMock,
        job_description: str,
        goals_profile: str,
    ) -> None:
        """Response text is stripped of leading/trailing whitespace."""
        mock_claude_client._call_with_retry = AsyncMock(
            return_value="  Answer with spaces  \n"
        )

        questions = [{"field_id": "f1", "question_text": "Q?"}]

        result = await generate_draft_answers(
            questions=questions,
            job_description=job_description,
            goals_profile=goals_profile,
            claude_client=mock_claude_client,
        )
        assert result is not None
        assert result[0]["draft_answer"] == "Answer with spaces"
