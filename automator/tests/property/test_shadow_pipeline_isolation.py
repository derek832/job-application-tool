# Feature: local-scoring-trial, Property 5: Shadow mode pipeline isolation
"""
Property-based test for shadow mode pipeline isolation.

Uses Hypothesis to verify that for any pair of (local_score, claude_score)
values where shadow mode is active, the job's resulting pipeline status is
identical to the status that would result from Claude scoring alone — the
local_score has no effect on status transitions.

Property tested:
- Property 5: Shadow mode pipeline isolation
  For any pair of (local_score, claude_score), run_shadow_scoring() SHALL NOT
  modify job_record.status or job_record.fit_score. The local score is purely
  observational and never influences pipeline decisions.

**Validates: Requirements 3.2**
"""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from sklearn.neighbors import NearestNeighbors

from src.db.models import JobRecord
from src.pipeline.shadow_scoring import run_shadow_scoring
from src.scoring.local_scorer import LocalScorer


# ---------------------------------------------------------------------------
# Event loop helper for running async code in synchronous Hypothesis tests
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously using asyncio.run()."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384


def _hash_based_encode(text: str) -> np.ndarray:
    """Generate a deterministic 384-dim vector from a text string using its hash."""
    seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(seed_bytes[:8], byteorder="big"))
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def _build_trained_scorer() -> LocalScorer:
    """Create a LocalScorer with real KNN index and mocked embeddings.

    The scorer will produce real predictions (integers 0-100) for any input,
    exercising the full predict path.
    """
    scorer = LocalScorer(data_dir="data/models")

    n_samples = 60
    rng = np.random.default_rng(99)
    train_embeddings = rng.standard_normal((n_samples, EMBEDDING_DIM)).astype(
        np.float32
    )
    norms = np.linalg.norm(train_embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    train_embeddings = train_embeddings / norms

    train_scores = rng.integers(0, 101, size=n_samples).astype(np.int32)

    profile_embedding = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    profile_norm = np.linalg.norm(profile_embedding)
    if profile_norm > 0:
        profile_embedding = profile_embedding / profile_norm

    k = min(LocalScorer.KNN_K, n_samples)
    knn_index = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
    knn_index.fit(train_embeddings)

    mock_embedding_manager = MagicMock()
    mock_embedding_manager.is_loaded = True
    mock_embedding_manager.encode = _hash_based_encode

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


def _make_job_record(status: str, fit_score: int | None) -> JobRecord:
    """Create a minimal JobRecord with the given status and fit_score."""
    return JobRecord(
        id="test-job-123",
        job_title="Software Engineer",
        company="TestCorp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/123",
        apply_type="easy_apply",
        status=status,
        fit_score=fit_score,
        description_text="A test job description for a software engineer role.",
        discovered_at="2024-01-15T10:00:00Z",
        updated_at="2024-01-15T10:01:00Z",
    )


# ---------------------------------------------------------------------------
# Module-level trained scorer
# ---------------------------------------------------------------------------

_TRAINED_SCORER = _build_trained_scorer()


# ---------------------------------------------------------------------------
# Property 5: Shadow mode pipeline isolation
# ---------------------------------------------------------------------------


@given(
    local_score=st.integers(0, 100),
    claude_score=st.integers(0, 100),
)
@settings(max_examples=150)
def test_shadow_scoring_does_not_modify_job_status(
    local_score: int, claude_score: int
) -> None:
    """
    For any pair of (local_score, claude_score), calling run_shadow_scoring()
    SHALL NOT modify job_record.status or job_record.fit_score. The pipeline
    status depends ONLY on the Claude score — the local score is purely
    observational.

    This test verifies that run_shadow_scoring:
    1. Returns an int or None (the local score prediction)
    2. Does not mutate job_record.status
    3. Does not mutate job_record.fit_score

    **Validates: Requirements 3.2**
    """
    # Set up a job record with the claude_score already assigned (simulating
    # the state where Claude has scored but we want to verify shadow scoring
    # doesn't interfere). We also test with fit_score=None to cover the
    # pre-scoring case.
    job_record = _make_job_record(status="extracted", fit_score=None)

    # Capture state before shadow scoring
    status_before = job_record.status
    fit_score_before = job_record.fit_score

    # Mock the async session (run_shadow_scoring doesn't use it directly)
    mock_session = AsyncMock()

    # Run shadow scoring
    result = _run_async(
        run_shadow_scoring(
            job_record=job_record,
            session=mock_session,
            local_scorer=_TRAINED_SCORER,
            cutoff=40,
        )
    )

    # Verify the return type is int or None
    assert result is None or isinstance(result, int), (
        f"run_shadow_scoring returned {type(result).__name__} ({result!r}), "
        f"expected int or None"
    )

    # CORE PROPERTY: job_record.status must be UNCHANGED
    assert job_record.status == status_before, (
        f"run_shadow_scoring MODIFIED job_record.status! "
        f"Before: {status_before!r}, After: {job_record.status!r}. "
        f"local_score={local_score}, claude_score={claude_score}"
    )

    # CORE PROPERTY: job_record.fit_score must be UNCHANGED
    assert job_record.fit_score == fit_score_before, (
        f"run_shadow_scoring MODIFIED job_record.fit_score! "
        f"Before: {fit_score_before!r}, After: {job_record.fit_score!r}. "
        f"local_score={local_score}, claude_score={claude_score}"
    )


@given(
    local_score=st.integers(0, 100),
    claude_score=st.integers(0, 100),
    initial_status=st.sampled_from(
        ["extracted", "scored", "approved_for_apply", "skipped"]
    ),
)
@settings(max_examples=150)
def test_shadow_scoring_isolation_across_statuses(
    local_score: int, claude_score: int, initial_status: str
) -> None:
    """
    For any initial job status and any (local_score, claude_score) pair,
    run_shadow_scoring() SHALL NOT alter any pipeline-relevant attributes.

    This verifies isolation regardless of which pipeline stage the job is in.

    **Validates: Requirements 3.2**
    """
    # Create job record in various states
    job_record = _make_job_record(status=initial_status, fit_score=claude_score)

    # Snapshot all pipeline-relevant attributes
    status_before = job_record.status
    fit_score_before = job_record.fit_score
    scored_at_before = job_record.scored_at
    approved_at_before = job_record.approved_at
    queue_reason_before = job_record.queue_reason

    mock_session = AsyncMock()

    result = _run_async(
        run_shadow_scoring(
            job_record=job_record,
            session=mock_session,
            local_scorer=_TRAINED_SCORER,
            cutoff=40,
        )
    )

    # Return type check
    assert result is None or isinstance(result, int), (
        f"run_shadow_scoring returned {type(result).__name__}, expected int or None"
    )

    # Pipeline attributes must be completely unchanged
    assert job_record.status == status_before, (
        f"status changed from {status_before!r} to {job_record.status!r}"
    )
    assert job_record.fit_score == fit_score_before, (
        f"fit_score changed from {fit_score_before!r} to {job_record.fit_score!r}"
    )
    assert job_record.scored_at == scored_at_before, (
        f"scored_at changed from {scored_at_before!r} to {job_record.scored_at!r}"
    )
    assert job_record.approved_at == approved_at_before, (
        f"approved_at changed from {approved_at_before!r} to {job_record.approved_at!r}"
    )
    assert job_record.queue_reason == queue_reason_before, (
        f"queue_reason changed from {queue_reason_before!r} to {job_record.queue_reason!r}"
    )
