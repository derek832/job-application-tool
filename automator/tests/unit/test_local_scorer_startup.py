"""Unit tests for LocalScorer startup initialization behavior.

Tests verify that:
- The model loads eagerly when artifacts exist on disk (Requirement 10.1)
- The scorer enters dormant state when artifacts are missing, without
  blocking service startup (Requirement 10.2)

Requirements: 10.1, 10.2
"""

from __future__ import annotations

import pickle
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.scoring.local_scorer import LocalScorer


@pytest.mark.asyncio
async def test_startup_loads_model_eagerly(tmp_path: Path) -> None:
    """When model artifacts exist on disk, initialize() loads them eagerly.

    Validates Requirement 10.1: WHEN the Automator service starts, THE
    Local_Scorer SHALL eagerly load the Embedding_Model and trained model
    artifacts into memory if both are present on disk.
    """
    # Create fake model artifacts on disk
    model_data = {
        "version": "v1_100samples",
        "trained_at": "2024-01-15T10:30:00Z",
        "sample_count": 100,
        "embeddings": np.random.randn(100, 384).astype(np.float32),
        "scores": np.random.randint(0, 100, size=100).astype(np.int32),
        "profile_embedding": np.random.randn(384).astype(np.float32),
        "knn_k": 10,
        "weights": {"knn": 0.6, "profile_sim": 0.4},
    }

    model_filename = "local_scorer_v1.pkl"
    model_path = tmp_path / model_filename
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f, protocol=pickle.HIGHEST_PROTOCOL)

    # Write the active version pointer file
    active_path = tmp_path / "local_scorer_active.txt"
    active_path.write_text(model_filename)

    # Create the scorer pointing to tmp_path
    scorer = LocalScorer(data_dir=str(tmp_path))

    # Mock the EmbeddingManager.load() to succeed without downloading
    with patch.object(
        scorer._embedding_manager, "load", new_callable=AsyncMock, return_value=True
    ):
        # Also mark the embedding manager as loaded
        scorer._embedding_manager._model = MagicMock()

        await scorer.initialize()

    # After initialization, model should be loaded and ready
    assert scorer.is_ready is True
    assert scorer.model_version == "v1_100samples"


@pytest.mark.asyncio
async def test_startup_dormant_state_without_artifacts(tmp_path: Path) -> None:
    """When model artifacts are missing, initialize() enters dormant state.

    Validates Requirement 10.2: IF the Embedding_Model or trained artifacts
    are missing at startup, THEN THE Local_Scorer SHALL log an informational
    message and remain in a dormant state without blocking service startup.
    """
    # tmp_path exists but has no model files — no pickle, no active pointer
    scorer = LocalScorer(data_dir=str(tmp_path))

    # Mock EmbeddingManager.load() to succeed (model downloads fine)
    with patch.object(
        scorer._embedding_manager, "load", new_callable=AsyncMock, return_value=True
    ):
        scorer._embedding_manager._model = MagicMock()

        # initialize should NOT raise despite missing artifacts
        await scorer.initialize()

    # Scorer should be in dormant state: not ready but no exception
    assert scorer.is_ready is False
    assert scorer.model_version is None
