"""Embedding model management for the local scoring system.

Handles downloading, caching, and loading the sentence-transformer model
(all-MiniLM-L6-v2). The model is cached on the data volume and persists
across container restarts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class EmbeddingManager:
    """Manages the sentence-transformer embedding model lifecycle.

    Downloads the model on first use and caches it in the specified directory.
    Subsequent loads use the cached model without network access.

    The model (all-MiniLM-L6-v2) produces 384-dimensional embeddings and
    consumes approximately 80–100MB of memory when loaded.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384

    def __init__(self, cache_dir: str = "data/models/embeddings") -> None:
        self._cache_dir = cache_dir
        self._model: object | None = None

    @property
    def is_loaded(self) -> bool:
        """True if the embedding model is loaded and ready for encoding."""
        return self._model is not None

    async def load(self) -> bool:
        """Load or download the embedding model.

        Downloads the model to cache_dir on first run; loads from cache
        thereafter. Uses asyncio.to_thread to avoid blocking the event loop
        during the potentially slow model loading/download.

        Returns:
            True if model is ready for encoding, False if download/load failed.
        """
        try:
            self._model = await asyncio.to_thread(self._load_model_sync)
            logger.info(
                "embedding_model_loaded",
                model=self.MODEL_NAME,
                cache_dir=self._cache_dir,
            )
            return True
        except Exception as exc:
            logger.error(
                "embedding_model_load_failed",
                model=self.MODEL_NAME,
                cache_dir=self._cache_dir,
                error=str(exc),
            )
            self._model = None
            return False

    def _load_model_sync(self) -> object:
        """Synchronous model loading — called via asyncio.to_thread.

        Imports sentence_transformers lazily to keep import time minimal
        when the module is loaded but the model isn't needed yet.
        """
        from sentence_transformers import SentenceTransformer

        # Ensure the cache directory exists
        Path(self._cache_dir).mkdir(parents=True, exist_ok=True)

        model = SentenceTransformer(
            self.MODEL_NAME,
            cache_folder=self._cache_dir,
        )
        return model

    def encode(self, text: str) -> np.ndarray:
        """Encode a single text into a 384-dimensional vector.

        Args:
            text: The input text to encode.

        Returns:
            A numpy array of shape (384,) with float32 values.

        Raises:
            RuntimeError: If the model has not been loaded yet.
        """
        if self._model is None:
            raise RuntimeError(
                "Embedding model not loaded. Call load() before encoding."
            )
        embedding: np.ndarray = self._model.encode(text, convert_to_numpy=True)
        return embedding

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        """Encode multiple texts efficiently into a matrix.

        Args:
            texts: List of input texts to encode.

        Returns:
            A numpy array of shape (N, 384) with float32 values,
            where N is the number of input texts.

        Raises:
            RuntimeError: If the model has not been loaded yet.
        """
        if self._model is None:
            raise RuntimeError(
                "Embedding model not loaded. Call load() before encoding."
            )
        embeddings: np.ndarray = self._model.encode(texts, convert_to_numpy=True)
        return embeddings
