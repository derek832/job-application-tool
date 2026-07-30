# Feature: local-scoring-trial, Property 3: Score output range invariant
"""
Property-based test for LocalScorer.predict() output range.

Uses Hypothesis to verify that for any non-empty job description string,
when the model is trained, predict() returns an integer in [0, 100].

Property tested:
- Property 3: Score output range invariant
  For any non-empty job description string, when the model is trained,
  predict() SHALL return an integer in the inclusive range [0, 100].

**Validates: Requirements 2.2**
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from sklearn.neighbors import NearestNeighbors

from src.scoring.local_scorer import LocalScorer


# ---------------------------------------------------------------------------
# Fixtures / Setup Helpers
# ---------------------------------------------------------------------------

NUM_TRAINING_SAMPLES = 60  # Above the 50 minimum


def _make_normalized_vector(rng: np.random.Generator) -> np.ndarray:
    """Generate a random normalized 384-dim vector (realistic for sentence-transformers)."""
    vec = rng.standard_normal(384).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def _build_trained_scorer() -> LocalScorer:
    """Create a LocalScorer with fake trained model data and a mocked EmbeddingManager.

    Sets up:
    - 60 training embeddings (normalized 384-dim vectors) with random scores [0, 100]
    - A real KNN index built from those embeddings
    - A mocked EmbeddingManager whose encode() returns normalized random vectors
    - _model_data and _knn_index set directly to make is_ready return True
    """
    rng = np.random.default_rng(42)

    # Generate training embeddings and scores
    training_embeddings = np.array(
        [_make_normalized_vector(rng) for _ in range(NUM_TRAINING_SAMPLES)],
        dtype=np.float32,
    )
    training_scores = rng.integers(0, 101, size=NUM_TRAINING_SAMPLES).astype(np.int32)
    profile_embedding = _make_normalized_vector(rng)

    # Build a real KNN index from the training embeddings
    k = min(LocalScorer.KNN_K, len(training_embeddings))
    knn_index = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
    knn_index.fit(training_embeddings)

    # Create model data dict matching the expected structure
    model_data = {
        "version": "v1_60samples",
        "trained_at": "2024-01-15T10:30:00Z",
        "sample_count": NUM_TRAINING_SAMPLES,
        "embeddings": training_embeddings,
        "scores": training_scores,
        "profile_embedding": profile_embedding,
        "knn_k": LocalScorer.KNN_K,
        "weights": {"knn": LocalScorer.WEIGHT_KNN, "profile_sim": LocalScorer.WEIGHT_PROFILE_SIM},
    }

    # Create the scorer with a mocked embedding manager
    scorer = LocalScorer(data_dir="data/models")

    # Mock the EmbeddingManager to return normalized random vectors
    mock_embedding_manager = MagicMock()
    mock_embedding_manager.is_loaded = True

    # Use a seeded RNG per call so encode is deterministic for a given input,
    # but produces different vectors for different inputs (simulating real embeddings)
    def mock_encode(text: str) -> np.ndarray:
        """Return a normalized 384-dim vector seeded by the input text hash."""
        seed = hash(text) % (2**32)
        local_rng = np.random.default_rng(seed)
        vec = local_rng.standard_normal(384).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    mock_embedding_manager.encode = mock_encode

    # Inject the mock and trained artifacts
    scorer._embedding_manager = mock_embedding_manager
    scorer._model_data = model_data
    scorer._knn_index = knn_index
    scorer._version = "v1_60samples"

    return scorer


# ---------------------------------------------------------------------------
# Module-level trained scorer (shared across all test examples for efficiency)
# ---------------------------------------------------------------------------

_TRAINED_SCORER = _build_trained_scorer()


# ---------------------------------------------------------------------------
# Property 3: Score output range invariant
# ---------------------------------------------------------------------------


@given(job_description=st.text(min_size=1))
@settings(max_examples=150)
def test_predict_returns_int_in_valid_range(job_description: str) -> None:
    """
    For any non-empty job description string, when the model is trained,
    predict() SHALL return an integer in the inclusive range [0, 100].

    **Validates: Requirements 2.2**
    """
    result = _TRAINED_SCORER.predict(job_description)

    # Must not be None since the model is ready
    assert result is not None, (
        f"predict() returned None for input {job_description!r}, "
        f"but model is_ready={_TRAINED_SCORER.is_ready}"
    )

    # Must be an integer
    assert isinstance(result, int), (
        f"predict() returned {type(result).__name__} ({result!r}), expected int"
    )

    # Must be in [0, 100]
    assert 0 <= result <= 100, (
        f"predict() returned {result}, which is outside [0, 100] "
        f"for input {job_description!r}"
    )
