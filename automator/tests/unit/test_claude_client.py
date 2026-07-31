"""Unit tests for the Claude API client wrapper.

Tests cover:
- Successful API calls with valid responses
- Pydantic validation of responses
- Retry logic on API errors
- Proper exception raising on exhaustion
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from src.agents.claude_client import (
    RETRY_BACKOFFS,
    ClaudeClient,
    FitScoreResult,
)
from src.exceptions import ScoringError, TailoringError


@pytest.fixture
def client() -> ClaudeClient:
    """Create a ClaudeClient with a dummy API key."""
    return ClaudeClient(api_key="test-key-not-real")


def _make_response(text: str) -> MagicMock:
    """Create a mock Claude API response with the given text content."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# FitScoreResult model tests
# ---------------------------------------------------------------------------


class TestFitScoreResult:
    """Tests for the FitScoreResult Pydantic model."""

    def test_valid_result(self) -> None:
        result = FitScoreResult(
            fit_score=85,
            rationale="Strong Python match.",
            deal_breaker_found=False,
            deal_breaker_term=None,
        )
        assert result.fit_score == 85
        assert result.deal_breaker_found is False

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            FitScoreResult(
                fit_score=-1,
                rationale="Invalid.",
                deal_breaker_found=False,
            )

    def test_score_above_100_rejected(self) -> None:
        with pytest.raises(Exception):
            FitScoreResult(
                fit_score=101,
                rationale="Invalid.",
                deal_breaker_found=False,
            )

    def test_deal_breaker_with_term(self) -> None:
        result = FitScoreResult(
            fit_score=30,
            rationale="Requires clearance.",
            deal_breaker_found=True,
            deal_breaker_term="security clearance",
        )
        assert result.deal_breaker_found is True
        assert result.deal_breaker_term == "security clearance"


# ---------------------------------------------------------------------------
# score_fit tests
# ---------------------------------------------------------------------------


class TestScoreFit:
    """Tests for ClaudeClient.score_fit."""

    @pytest.mark.asyncio
    async def test_successful_scoring(self, client: ClaudeClient) -> None:
        response_data = {
            "fit_score": 82,
            "rationale": "Strong match for Python backend role.",
            "deal_breaker_found": False,
            "deal_breaker_term": None,
        }
        mock_response = _make_response(json.dumps(response_data))

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.score_fit(
                description="Python backend engineer needed.",
                resume="5 years Python experience.",
                goals='{"target_titles": ["Backend Engineer"]}',
            )

        assert isinstance(result, FitScoreResult)
        assert result.fit_score == 82
        assert result.deal_breaker_found is False

    @pytest.mark.asyncio
    async def test_invalid_json_raises_scoring_error(self, client: ClaudeClient) -> None:
        mock_response = _make_response("not valid json {{{")

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            with pytest.raises(ScoringError, match="Failed to parse"):
                await client.score_fit(
                    description="Job desc",
                    resume="Resume",
                    goals="{}",
                )

    @pytest.mark.asyncio
    async def test_invalid_schema_raises_scoring_error(self, client: ClaudeClient) -> None:
        response_data = {"fit_score": 200, "rationale": "Bad score"}
        mock_response = _make_response(json.dumps(response_data))

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            with pytest.raises(ScoringError, match="Failed to parse"):
                await client.score_fit(
                    description="Job desc",
                    resume="Resume",
                    goals="{}",
                )


# ---------------------------------------------------------------------------
# tailor_resume tests
# ---------------------------------------------------------------------------


class TestTailorResume:
    """Tests for ClaudeClient.tailor_resume."""

    @pytest.mark.asyncio
    async def test_successful_tailoring(self, client: ClaudeClient) -> None:
        tailored_text = "Tailored resume with ATS keywords."
        mock_response = _make_response(tailored_text)

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.tailor_resume(
                description="Looking for a Python developer.",
                resume_base="Original resume content.",
            )

        assert result == tailored_text


# ---------------------------------------------------------------------------
# generate_cover_letter tests
# ---------------------------------------------------------------------------


class TestGenerateCoverLetter:
    """Tests for ClaudeClient.generate_cover_letter."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, client: ClaudeClient) -> None:
        cover_letter = "Dear Hiring Team, I am excited to apply..."
        mock_response = _make_response(cover_letter)

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.generate_cover_letter(
                description="Senior Python Engineer at Acme Corp.",
                tailored_resume="Tailored resume content.",
                goals='{"career_objective": "Lead backend teams"}',
            )

        assert result == cover_letter


# ---------------------------------------------------------------------------
# identify_form_fields tests
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Tests for the retry mechanism on API errors."""

    @pytest.mark.asyncio
    async def test_retries_on_api_error_then_succeeds(self, client: ClaudeClient) -> None:
        response_data = {
            "fit_score": 70,
            "rationale": "Decent match.",
            "deal_breaker_found": False,
            "deal_breaker_term": None,
        }
        mock_response = _make_response(json.dumps(response_data))

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise anthropic.APIError(
                    message="Server error",
                    request=MagicMock(),
                    body=None,
                )
            return mock_response

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = side_effect
            with patch("src.agents.claude_client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.score_fit(
                    description="Job desc",
                    resume="Resume",
                    goals="{}",
                )

        assert result.fit_score == 70
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self, client: ClaudeClient) -> None:
        async def always_fail(**kwargs):
            raise anthropic.APIError(
                message="Persistent failure",
                request=MagicMock(),
                body=None,
            )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = always_fail
            with patch("src.agents.claude_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(ScoringError, match="failed after 3 attempts"):
                    await client.score_fit(
                        description="Job desc",
                        resume="Resume",
                        goals="{}",
                    )

        assert mock_create.call_count == len(RETRY_BACKOFFS)

    @pytest.mark.asyncio
    async def test_tailoring_raises_tailoring_error_on_exhaustion(
        self, client: ClaudeClient
    ) -> None:
        async def always_fail(**kwargs):
            raise anthropic.APIError(
                message="Persistent failure",
                request=MagicMock(),
                body=None,
            )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = always_fail
            with patch("src.agents.claude_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(TailoringError, match="failed after 3 attempts"):
                    await client.tailor_resume(
                        description="Job desc",
                        resume_base="Resume",
                    )

    @pytest.mark.asyncio
    async def test_backoff_delays_are_correct(self, client: ClaudeClient) -> None:
        sleep_calls: list[float] = []

        async def track_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        async def always_fail(**kwargs):
            raise anthropic.APIError(
                message="Failure",
                request=MagicMock(),
                body=None,
            )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = always_fail
            with patch("src.agents.claude_client.asyncio.sleep", side_effect=track_sleep):
                with pytest.raises(ScoringError):
                    await client.score_fit(
                        description="Job desc",
                        resume="Resume",
                        goals="{}",
                    )

        # Should sleep between attempts 1→2 and 2→3, but not after the last attempt
        assert sleep_calls == [2, 5]
