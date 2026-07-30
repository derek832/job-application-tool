# Feature: local-scoring-trial, Property 2: Minimum training threshold enforcement
"""
Property-based test for LocalScorer minimum training threshold.

Uses Hypothesis to verify that `train()` raises `InsufficientDataError` when
the training set has fewer than 50 records, and succeeds (returning a
TrainingResult) when the training set has 50 or more records.

Property tested:
- Property 2: Minimum training threshold enforcement
  - For any training set with fewer than 50 records, train() SHALL raise InsufficientDataError
  - For any training set with 50 or more records, train() SHALL complete successfully

**Validates: Requirements 1.5**
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Mock the automator package to allow importing local_scorer without
# the full automator.src.db.models dependency
# ---------------------------------------------------------------------------

_automator_mock = types.ModuleType("automator")
_automator_src_mock = types.ModuleType("automator.src")
_automator_src_db_mock = types.ModuleType("automator.src.db")
_automator_src_db_models_mock = types.ModuleType("automator.src.db.models")
_automator_src_scoring_mock = types.ModuleType("automator.src.scoring")
_automator_src_scoring_embeddings_mock = types.ModuleType("automator.src.scoring.embeddings")

# Create a mock JobRecord class
_automator_src_db_models_mock.JobRecord = MagicMock()

# Wire up the module hierarchy
_automator_mock.src = _automator_src_mock
_automator_src_mock.db = _automator_src_db_mock
_automator_src_db_mock.models = _automator_src_db_models_mock
_automator_src_mock.scoring = _automator_src_scoring_mock
_automator_src_scoring_mock.embeddings = _automator_src_scoring_embeddings_mock

sys.modules.setdefault("automator", _automator_mock)
sys.modules.setdefault("automator.src", _automator_src_mock)
sys.modules.setdefault("automator.src.db", _automator_src_db_mock)
sys.modules.setdefault("automator.src.db.models", _automator_src_db_models_mock)
sys.modules.setdefault("automator.src.scoring", _automator_src_scoring_mock)
sys.modules.setdefault("automator.src.scoring.embeddings", _automator_src_scoring_embeddings_mock)

from src.scoring.local_scorer import InsufficientDataError, LocalScorer, TrainingResult  # noqa: E402


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random sample counts from 0 to 200
sample_count_strategy = st.integers(min_value=0, max_value=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dummy_data(n: int) -> tuple[list[str], list[int], str]:
    """Create n dummy job descriptions, scores, and a profile text."""
    descriptions = [f"Job description number {i}" for i in range(n)]
    scores = [int(x) for x in np.random.randint(0, 101, size=max(n, 1))[:n]]
    profile_text = "Software engineer with 5 years of experience in Python."
    return descriptions, scores, profile_text


def _mock_encode_batch(texts: list[str]) -> np.ndarray:
    """Return random embeddings of shape (N, 384)."""
    return np.random.rand(len(texts), 384).astype(np.float32)


def _mock_encode(text: str) -> np.ndarray:
    """Return a random embedding of shape (384,)."""
    return np.random.rand(384).astype(np.float32)


# ---------------------------------------------------------------------------
# Property 2: Minimum training threshold enforcement
# ---------------------------------------------------------------------------


@given(sample_count=sample_count_strategy)
@settings(max_examples=150)
def test_minimum_training_threshold_enforcement(sample_count: int) -> None:
    """
    For any training set with fewer than 50 records, the train() method
    SHALL raise InsufficientDataError. For any training set with 50 or more
    records, the method SHALL complete successfully without raising.

    **Validates: Requirements 1.5**
    """

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            scorer = LocalScorer(data_dir=tmp_dir)

            # Replace the EmbeddingManager with a mock to avoid downloading the real model
            mock_em = MagicMock()
            mock_em.is_loaded = True
            mock_em.load = AsyncMock(return_value=True)
            mock_em.encode_batch = _mock_encode_batch
            mock_em.encode = _mock_encode
            scorer._embedding_manager = mock_em

            descriptions, scores, profile_text = _make_dummy_data(sample_count)

            if sample_count < 50:
                # Should raise InsufficientDataError
                raised = False
                try:
                    await scorer.train(descriptions, scores, profile_text)
                except InsufficientDataError as e:
                    raised = True
                    assert e.sample_count == sample_count, (
                        f"Expected InsufficientDataError.sample_count={sample_count}, "
                        f"got {e.sample_count}"
                    )

                assert raised, (
                    f"Expected InsufficientDataError for sample_count={sample_count} "
                    f"(< 50), but no exception was raised"
                )
            else:
                # Should succeed and return TrainingResult
                result = await scorer.train(descriptions, scores, profile_text)
                assert isinstance(result, TrainingResult), (
                    f"Expected TrainingResult for sample_count={sample_count} "
                    f"(>= 50), got {type(result)}"
                )
                assert result.sample_count == sample_count, (
                    f"Expected result.sample_count={sample_count}, "
                    f"got {result.sample_count}"
                )

    asyncio.run(_run())
