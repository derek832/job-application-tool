# Feature: local-scoring-trial, Property 4: Prediction determinism
"""
Property-based tests for LocalScorer prediction determinism.

Uses Hypothesis to verify that calling predict() twice with the same
trained model produces identical results for any job description string.

Properties tested:
- Property 4: Prediction determinism
  - For any job description string, predict(x) == predict(x) with the same model.

**Validates: Requirements 2.5**
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from sklearn.neighbors import NearestNeighbors

from src.scoring.local_scorer import LocalScorer


# ---------------------------------------------------------------------------
# Deterministic hash-based mock for EmbeddingManager.encode
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384


def _hash_based_encode(text: str) -> np.ndarray:
    """Generate a deterministic 384-dim vector from a text string using its hash.

    The same input text always produces the same vector, which is exactly
    what a real embedding model does (deterministic encoding).
    """
    seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    rng = np.random.default_rng(
        int.from_bytes(seed_bytes[:8], byteorder="big")
    )
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    # Normalize to unit vector for cosine similarity stability
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


# ---------------------------------------------------------------------------
# Fixture: Build a trained LocalScorer with fake data and real KNN index
# ---------------------------------------------------------------------------


def _build_trained_scorer() -> LocalScorer:
    """Create a LocalScorer with a real KNN index built from fake training data.

    Uses 60 fake training samples (above the 50 minimum) with deterministic
    embeddings and scores. The KNN index is real (sklearn NearestNeighbors),
    ensuring the full predict path is exercised.

    The EmbeddingManager is replaced with a MagicMock whose encode() uses
    a hash-based approach — same input text always returns the same vector.
    """
    scorer = LocalScorer(data_dir="data/models")

    # Generate 60 fake training embeddings using deterministic seeds
    n_samples = 60
    rng = np.random.default_rng(42)
    train_embeddings = rng.standard_normal((n_samples, EMBEDDING_DIM)).astype(
        np.float32
    )
    # Normalize each row
    norms = np.linalg.norm(train_embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    train_embeddings = train_embeddings / norms

    # Fake scores (integers 0-100)
    train_scores = rng.integers(0, 101, size=n_samples).astype(np.int32)

    # Fake profile embedding
    profile_embedding = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    profile_norm = np.linalg.norm(profile_embedding)
    if profile_norm > 0:
        profile_embedding = profile_embedding / profile_norm

    # Build real KNN index
    k = min(LocalScorer.KNN_K, n_samples)
    knn_index = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
    knn_index.fit(train_embeddings)

    # Mock the EmbeddingManager with hash-based deterministic encode
    mock_embedding_manager = MagicMock()
    mock_embedding_manager.is_loaded = True
    mock_embedding_manager.encode = _hash_based_encode

    # Inject trained state and mocked embedding manager
    scorer._embedding_manager = mock_embedding_manager
    scorer._model_data = {
        "version": "v1_60samples",
        "sample_count": n_samples,
        "embeddings": train_embeddings,
        "scores": train_scores,
        "profile_embedding": profile_embedding,
        "knn_k": LocalScorer.KNN_K,
        "weights": {
            "knn": LocalScorer.WEIGHT_KNN,
            "profile_sim": LocalScorer.WEIGHT_PROFILE_SIM,
        },
    }
    scorer._knn_index = knn_index
    scorer._version = "v1_60samples"

    return scorer


# ---------------------------------------------------------------------------
# Module-level trained scorer (shared across all test examples for efficiency)
# ---------------------------------------------------------------------------

_TRAINED_SCORER = _build_trained_scorer()


# ---------------------------------------------------------------------------
# Property 4: Prediction determinism
# ---------------------------------------------------------------------------


@given(job_description=st.text(min_size=1))
@settings(max_examples=200)
def test_prediction_determinism(job_description: str) -> None:
    """
    For any job description string, calling predict() twice with the same
    trained model SHALL produce identical results.

    **Validates: Requirements 2.5**
    """
    result_1 = _TRAINED_SCORER.predict(job_description)
    result_2 = _TRAINED_SCORER.predict(job_description)

    assert result_1 is not None, "predict() returned None despite model being ready"
    assert result_2 is not None, "predict() returned None on second call"
    assert result_1 == result_2, (
        f"predict() is not deterministic: "
        f"first call returned {result_1}, second call returned {result_2} "
        f"for the same input"
    )
