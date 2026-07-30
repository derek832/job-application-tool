"""Unit tests for shadow scoring error handling.

Tests verify that run_shadow_scoring:
- Catches exceptions and returns None (never raises)
- Respects the 500ms timeout and returns None on timeout
- Allows the pipeline to continue on any local scorer failure

Requirements: 3.4, 3.5
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.pipeline.shadow_scoring import run_shadow_scoring


def _make_job_record(job_id: str = "test-job-123") -> MagicMock:
    """Create a mock JobRecord with required attributes."""
    job = MagicMock()
    job.id = job_id
    job.description_text = "Senior Python developer with 5+ years experience in async programming."
    return job


def _make_local_scorer(predict_side_effect=None, predict_return_value=None) -> MagicMock:
    """Create a mock LocalScorer with configurable predict() behavior."""
    scorer = MagicMock()
    if predict_side_effect is not None:
        scorer.predict.side_effect = predict_side_effect
    elif predict_return_value is not None:
        scorer.predict.return_value = predict_return_value
    else:
        scorer.predict.return_value = 75
    return scorer


@pytest.mark.asyncio
async def test_run_shadow_scoring_returns_none_on_exception() -> None:
    """When predict() raises an exception, run_shadow_scoring returns None."""
    job = _make_job_record()
    session = AsyncMock()
    scorer = _make_local_scorer(predict_side_effect=RuntimeError("model exploded"))

    result = await run_shadow_scoring(
        job_record=job,
        session=session,
        local_scorer=scorer,
        cutoff=40,
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_shadow_scoring_returns_none_on_timeout() -> None:
    """When predict() takes longer than 500ms, run_shadow_scoring returns None."""
    job = _make_job_record()
    session = AsyncMock()

    def slow_predict(description: str) -> int:
        time.sleep(1)  # Exceeds the 500ms timeout
        return 80

    scorer = _make_local_scorer()
    scorer.predict.side_effect = slow_predict

    result = await run_shadow_scoring(
        job_record=job,
        session=session,
        local_scorer=scorer,
        cutoff=40,
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_shadow_scoring_returns_score_on_success() -> None:
    """When predict() returns normally, the score passes through."""
    job = _make_job_record()
    session = AsyncMock()
    scorer = _make_local_scorer(predict_return_value=72)

    result = await run_shadow_scoring(
        job_record=job,
        session=session,
        local_scorer=scorer,
        cutoff=40,
    )

    assert result == 72


@pytest.mark.asyncio
async def test_run_shadow_scoring_never_raises() -> None:
    """run_shadow_scoring never raises regardless of exception type.

    Tests multiple exception types: RuntimeError, ValueError, MemoryError.
    The function must catch all of them and return None.
    """
    job = _make_job_record()
    session = AsyncMock()

    exceptions_to_test = [
        RuntimeError("runtime failure"),
        ValueError("invalid value"),
        MemoryError("out of memory"),
    ]

    for exc in exceptions_to_test:
        scorer = _make_local_scorer(predict_side_effect=exc)

        # Must not raise — should return None
        result = await run_shadow_scoring(
            job_record=job,
            session=session,
            local_scorer=scorer,
            cutoff=40,
        )

        assert result is None, f"Expected None for {type(exc).__name__}, got {result}"
