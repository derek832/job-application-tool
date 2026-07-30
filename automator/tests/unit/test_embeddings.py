"""Unit tests for the EmbeddingManager class.

Tests cover initialization, graceful failure handling, encoding interface,
and batch encoding. Uses mocking to avoid downloading the actual model.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.scoring.embeddings import EmbeddingManager


class TestEmbeddingManagerInit:
    """Tests for EmbeddingManager initialization."""

    def test_default_cache_dir(self) -> None:
        manager = EmbeddingManager()
        assert manager._cache_dir == "data/models/embeddings"

    def test_custom_cache_dir(self) -> None:
        manager = EmbeddingManager(cache_dir="/tmp/test-cache")
        assert manager._cache_dir == "/tmp/test-cache"

    def test_model_not_loaded_initially(self) -> None:
        manager = EmbeddingManager()
        assert manager.is_loaded is False
        assert manager._model is None


class TestEmbeddingManagerLoad:
    """Tests for the async load() method."""

    @pytest.mark.asyncio
    async def test_load_success(self) -> None:
        manager = EmbeddingManager(cache_dir="/tmp/test-cache")
        mock_model = MagicMock()

        with patch.object(manager, "_load_model_sync", return_value=mock_model):
            result = await manager.load()

        assert result is True
        assert manager.is_loaded is True
        assert manager._model is mock_model

    @pytest.mark.asyncio
    async def test_load_failure_returns_false(self) -> None:
        manager = EmbeddingManager(cache_dir="/tmp/test-cache")

        with patch.object(
            manager, "_load_model_sync", side_effect=OSError("Network unreachable")
        ):
            result = await manager.load()

        assert result is False
        assert manager.is_loaded is False
        assert manager._model is None

    @pytest.mark.asyncio
    async def test_load_failure_on_import_error(self) -> None:
        manager = EmbeddingManager(cache_dir="/tmp/test-cache")

        with patch.object(
            manager,
            "_load_model_sync",
            side_effect=ImportError("No module named sentence_transformers"),
        ):
            result = await manager.load()

        assert result is False
        assert manager.is_loaded is False

    @pytest.mark.asyncio
    async def test_load_failure_on_runtime_error(self) -> None:
        manager = EmbeddingManager(cache_dir="/tmp/test-cache")

        with patch.object(
            manager,
            "_load_model_sync",
            side_effect=RuntimeError("Corrupted model cache"),
        ):
            result = await manager.load()

        assert result is False
        assert manager.is_loaded is False


class TestEmbeddingManagerEncode:
    """Tests for the encode() and encode_batch() methods."""

    def _make_loaded_manager(self) -> EmbeddingManager:
        """Helper to create a manager with a mocked loaded model."""
        manager = EmbeddingManager()
        mock_model = MagicMock()
        # encode returns a 384-dim vector for single text
        mock_model.encode.return_value = np.random.randn(384).astype(np.float32)
        manager._model = mock_model
        return manager

    def test_encode_returns_384_dim_vector(self) -> None:
        manager = self._make_loaded_manager()
        result = manager.encode("test text")
        assert isinstance(result, np.ndarray)
        assert result.shape == (384,)

    def test_encode_raises_when_not_loaded(self) -> None:
        manager = EmbeddingManager()
        with pytest.raises(RuntimeError, match="not loaded"):
            manager.encode("test text")

    def test_encode_passes_text_to_model(self) -> None:
        manager = self._make_loaded_manager()
        manager.encode("hello world")
        manager._model.encode.assert_called_once_with(
            "hello world", convert_to_numpy=True
        )

    def test_encode_batch_returns_n_by_384_matrix(self) -> None:
        manager = EmbeddingManager()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)
        manager._model = mock_model

        result = manager.encode_batch(["a", "b", "c"])
        assert isinstance(result, np.ndarray)
        assert result.shape == (3, 384)

    def test_encode_batch_raises_when_not_loaded(self) -> None:
        manager = EmbeddingManager()
        with pytest.raises(RuntimeError, match="not loaded"):
            manager.encode_batch(["test"])

    def test_encode_batch_passes_texts_to_model(self) -> None:
        manager = self._make_loaded_manager()
        # Override for batch return shape
        manager._model.encode.return_value = np.random.randn(2, 384).astype(np.float32)
        manager.encode_batch(["hello", "world"])
        manager._model.encode.assert_called_once_with(
            ["hello", "world"], convert_to_numpy=True
        )


class TestEmbeddingManagerConstants:
    """Tests for class-level constants."""

    def test_model_name(self) -> None:
        assert EmbeddingManager.MODEL_NAME == "all-MiniLM-L6-v2"

    def test_embedding_dim(self) -> None:
        assert EmbeddingManager.EMBEDDING_DIM == 384
