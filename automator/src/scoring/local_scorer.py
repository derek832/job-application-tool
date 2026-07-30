"""Local embedding-based fit score predictor.

Uses sentence-transformer embeddings (all-MiniLM-L6-v2) trained on historically
scored jobs to predict fit scores via KNN regression + profile similarity,
without any API calls. All computation is local.

Algorithm:
    Training: Batch-encode job descriptions, compute profile embedding, serialize.
    Prediction: Encode input → cosine sim to profile + K=10 NN weighted avg → blend.
"""

from __future__ import annotations

import asyncio
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import structlog
from sklearn.neighbors import NearestNeighbors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord
from src.scoring.embeddings import EmbeddingManager

logger = structlog.get_logger(__name__)


class InsufficientDataError(Exception):
    """Raised when training data has fewer than 50 samples."""

    def __init__(self, sample_count: int) -> None:
        self.sample_count = sample_count
        super().__init__(
            f"Insufficient training data: {sample_count} samples (minimum 50 required)"
        )


@dataclass
class TrainingResult:
    """Result of a successful training run."""

    sample_count: int
    model_path: str
    duration_seconds: float
    version: str


class LocalScorer:
    """Embedding-based local fit score predictor.

    Holds the embedding model and trained artifacts in memory for fast prediction.
    Thread-safe for concurrent reads; writes (train/retrain) use atomic swap.
    """

    MINIMUM_SAMPLES = 50
    KNN_K = 10
    WEIGHT_KNN = 0.6
    WEIGHT_PROFILE_SIM = 0.4
    ACTIVE_VERSION_FILE = "local_scorer_active.txt"

    def __init__(self, data_dir: str = "data/models") -> None:
        self._data_dir = Path(data_dir)
        self._embedding_manager = EmbeddingManager(
            cache_dir=str(self._data_dir / "embeddings")
        )
        # Trained model artifacts (atomically swappable)
        self._model_data: dict | None = None
        self._knn_index: NearestNeighbors | None = None
        self._version: str | None = None

    @property
    def is_ready(self) -> bool:
        """True if model is trained and loaded, ready for predictions."""
        return (
            self._model_data is not None
            and self._knn_index is not None
            and self._embedding_manager.is_loaded
        )

    @property
    def model_version(self) -> str | None:
        """Current model version identifier (e.g. 'v3_870samples')."""
        return self._version

    async def initialize(self) -> None:
        """Load embedding model + trained artifacts from disk.

        Called once at startup. If artifacts are missing, enters dormant state.
        Completes within 10 seconds on typical hardware.
        """
        # Load embedding model
        loaded = await self._embedding_manager.load()
        if not loaded:
            logger.warning(
                "local_scorer_dormant",
                reason="embedding_model_unavailable",
            )
            return

        # Try to load trained artifacts from the active version pointer
        active_path = self._data_dir / self.ACTIVE_VERSION_FILE
        if not active_path.exists():
            logger.info(
                "local_scorer_dormant",
                reason="no_trained_model",
                hint="Call /scoring-trial/retrain to train the model",
            )
            return

        try:
            model_filename = await asyncio.to_thread(
                active_path.read_text
            )
            model_filename = model_filename.strip()
            model_path = self._data_dir / model_filename
            if not model_path.exists():
                logger.warning(
                    "local_scorer_dormant",
                    reason="model_file_missing",
                    expected_path=str(model_path),
                )
                return

            model_data = await asyncio.to_thread(self._load_pickle, model_path)
            knn_index = self._build_knn_index(model_data["embeddings"])
            self._model_data = model_data
            self._knn_index = knn_index
            self._version = model_data["version"]

            logger.info(
                "local_scorer_ready",
                version=self._version,
                sample_count=model_data["sample_count"],
            )
        except Exception as exc:
            logger.error(
                "local_scorer_init_failed",
                error=str(exc),
                hint="Model artifacts may be corrupt. Retrain via API.",
            )
            self._model_data = None
            self._knn_index = None
            self._version = None

    async def train(
        self,
        job_descriptions: list[str],
        fit_scores: list[int],
        profile_text: str,
    ) -> TrainingResult:
        """Train the model on historical data.

        Args:
            job_descriptions: List of job description texts.
            fit_scores: Corresponding Claude fit_scores (0-100).
            profile_text: Concatenated SKILLS_AND_CONTEXT + supplementary_context.

        Returns:
            TrainingResult with sample_count, model_path, duration_seconds, version.

        Raises:
            InsufficientDataError: If len(job_descriptions) < 50.
        """
        sample_count = len(job_descriptions)
        if sample_count < self.MINIMUM_SAMPLES:
            raise InsufficientDataError(sample_count)

        start_time = time.time()

        # Ensure embedding model is loaded
        if not self._embedding_manager.is_loaded:
            loaded = await self._embedding_manager.load()
            if not loaded:
                raise RuntimeError("Failed to load embedding model for training")

        # Compute embeddings (CPU-bound, run in thread)
        embeddings = await asyncio.to_thread(
            self._embedding_manager.encode_batch, job_descriptions
        )
        profile_embedding = await asyncio.to_thread(
            self._embedding_manager.encode, profile_text
        )
        scores_array = np.array(fit_scores, dtype=np.int32)

        # Determine version number
        version_num = self._next_version_number()
        version = f"v{version_num}_{sample_count}samples"

        # Build model data
        model_data = {
            "version": version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": sample_count,
            "embeddings": embeddings,
            "scores": scores_array,
            "profile_embedding": profile_embedding,
            "knn_k": self.KNN_K,
            "weights": {"knn": self.WEIGHT_KNN, "profile_sim": self.WEIGHT_PROFILE_SIM},
        }

        # Serialize to disk
        self._data_dir.mkdir(parents=True, exist_ok=True)
        model_filename = f"local_scorer_v{version_num}.pkl"
        model_path = self._data_dir / model_filename
        await asyncio.to_thread(self._save_pickle, model_data, model_path)

        # Update active version pointer
        active_path = self._data_dir / self.ACTIVE_VERSION_FILE
        await asyncio.to_thread(active_path.write_text, model_filename)

        # Build KNN index and swap into active state
        knn_index = self._build_knn_index(embeddings)
        self._model_data = model_data
        self._knn_index = knn_index
        self._version = version

        duration = time.time() - start_time
        logger.info(
            "local_scorer_trained",
            version=version,
            sample_count=sample_count,
            model_path=str(model_path),
            duration_seconds=round(duration, 2),
        )

        return TrainingResult(
            sample_count=sample_count,
            model_path=str(model_path),
            duration_seconds=round(duration, 2),
            version=version,
        )

    def predict(self, job_description: str) -> int | None:
        """Predict a fit score for a single job description.

        Returns:
            Integer 0-100, or None if model not ready.

        Performance: <500ms per call, typically ~5ms.
        Deterministic: same input + model = same output.
        """
        if not self.is_ready:
            return None

        # Compute job embedding
        job_embedding = self._embedding_manager.encode(job_description)

        # Cosine similarity to profile embedding
        profile_embedding = self._model_data["profile_embedding"]
        profile_sim = self._cosine_similarity(job_embedding, profile_embedding)

        # KNN regression: find K nearest neighbors by cosine distance
        # NearestNeighbors returns (distances, indices) for the query
        job_embedding_2d = job_embedding.reshape(1, -1)
        distances, indices = self._knn_index.kneighbors(job_embedding_2d)
        distances = distances[0]  # shape (K,)
        indices = indices[0]  # shape (K,)

        # Distance-weighted average of neighbor scores
        scores = self._model_data["scores"]
        knn_score = self._distance_weighted_average(distances, scores[indices])

        # Combine: 0.6 * knn_score + 0.4 * (profile_sim * 100)
        final_score = (
            self.WEIGHT_KNN * knn_score
            + self.WEIGHT_PROFILE_SIM * (profile_sim * 100)
        )

        # Clip to [0, 100] and round to integer
        final_score = np.clip(final_score, 0, 100)
        return int(round(final_score))

    async def retrain_atomic(
        self,
        job_descriptions: list[str],
        fit_scores: list[int],
        profile_text: str,
    ) -> TrainingResult:
        """Retrain and atomically swap the active model.

        The old model continues serving predictions during training.
        On success, the new model replaces the old one in a single assignment.
        On failure, the old model remains active.
        """
        sample_count = len(job_descriptions)
        if sample_count < self.MINIMUM_SAMPLES:
            raise InsufficientDataError(sample_count)

        start_time = time.time()

        # Ensure embedding model is loaded
        if not self._embedding_manager.is_loaded:
            loaded = await self._embedding_manager.load()
            if not loaded:
                raise RuntimeError("Failed to load embedding model for retraining")

        # Compute embeddings in thread (old model continues serving)
        embeddings = await asyncio.to_thread(
            self._embedding_manager.encode_batch, job_descriptions
        )
        profile_embedding = await asyncio.to_thread(
            self._embedding_manager.encode, profile_text
        )
        scores_array = np.array(fit_scores, dtype=np.int32)

        # Determine version number
        version_num = self._next_version_number()
        version = f"v{version_num}_{sample_count}samples"

        # Build model data
        model_data = {
            "version": version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": sample_count,
            "embeddings": embeddings,
            "scores": scores_array,
            "profile_embedding": profile_embedding,
            "knn_k": self.KNN_K,
            "weights": {"knn": self.WEIGHT_KNN, "profile_sim": self.WEIGHT_PROFILE_SIM},
        }

        # Serialize to disk
        self._data_dir.mkdir(parents=True, exist_ok=True)
        model_filename = f"local_scorer_v{version_num}.pkl"
        model_path = self._data_dir / model_filename
        await asyncio.to_thread(self._save_pickle, model_data, model_path)

        # Build KNN index before atomic swap
        knn_index = self._build_knn_index(embeddings)

        # Atomic swap — single assignment replaces the active model
        self._model_data = model_data
        self._knn_index = knn_index
        self._version = version

        # Update active version pointer on disk
        active_path = self._data_dir / self.ACTIVE_VERSION_FILE
        await asyncio.to_thread(active_path.write_text, model_filename)

        duration = time.time() - start_time
        logger.info(
            "local_scorer_retrained",
            version=version,
            sample_count=sample_count,
            model_path=str(model_path),
            duration_seconds=round(duration, 2),
        )

        return TrainingResult(
            sample_count=sample_count,
            model_path=str(model_path),
            duration_seconds=round(duration, 2),
            version=version,
        )

    # ─── Private helpers ────────────────────────────────────────────────

    def _next_version_number(self) -> int:
        """Determine the next version number by scanning existing model files."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        existing = list(self._data_dir.glob("local_scorer_v*.pkl"))
        if not existing:
            return 1
        # Extract version numbers from filenames like local_scorer_v3.pkl
        version_nums = []
        for p in existing:
            stem = p.stem  # e.g. "local_scorer_v3"
            try:
                num_str = stem.split("_v")[1]
                version_nums.append(int(num_str))
            except (IndexError, ValueError):
                continue
        return max(version_nums, default=0) + 1

    @staticmethod
    def _build_knn_index(embeddings: np.ndarray) -> NearestNeighbors:
        """Build a NearestNeighbors index with cosine metric."""
        k = min(LocalScorer.KNN_K, len(embeddings))
        knn = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
        knn.fit(embeddings)
        return knn

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors. Returns value in [-1, 1]."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def _distance_weighted_average(
        distances: np.ndarray, scores: np.ndarray
    ) -> float:
        """Compute distance-weighted average of scores.

        Closer neighbors (smaller distance) get higher weight.
        Uses inverse distance weighting: weight_i = 1 / (distance_i + epsilon).
        """
        epsilon = 1e-8  # avoid division by zero for exact matches
        weights = 1.0 / (distances + epsilon)
        weighted_sum = np.sum(weights * scores)
        total_weight = np.sum(weights)
        if total_weight == 0:
            return float(np.mean(scores))
        return float(weighted_sum / total_weight)

    @staticmethod
    def _load_pickle(path: Path) -> dict:
        """Load pickle from disk (called via asyncio.to_thread)."""
        with open(path, "rb") as f:
            return pickle.load(f)

    @staticmethod
    def _save_pickle(data: dict, path: Path) -> None:
        """Save pickle to disk (called via asyncio.to_thread)."""
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)


# ---------------------------------------------------------------------------
# Module-level helper: training data loader
# ---------------------------------------------------------------------------


async def _load_training_data(session: AsyncSession) -> tuple[list[str], list[int]]:
    """Load training data from the database.

    Queries all JobRecord rows where both fit_score and description_text are
    non-null, returning the descriptions and scores as parallel lists.

    Args:
        session: Active async database session.

    Returns:
        Tuple of (descriptions, scores) where each list has the same length.
    """
    stmt = select(JobRecord).where(
        JobRecord.fit_score.is_not(None),
        JobRecord.description_text.is_not(None),
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    descriptions: list[str] = []
    scores: list[int] = []
    for record in records:
        descriptions.append(record.description_text)  # type: ignore[arg-type]
        scores.append(record.fit_score)  # type: ignore[arg-type]

    return descriptions, scores


# ---------------------------------------------------------------------------
# Module-level singleton reference
# ---------------------------------------------------------------------------

# Set by the application lifespan (src/main.py startup) so that the pipeline
# can access the scorer without circular imports.  Remains None until
# initialize() is called at startup.
_active_scorer: LocalScorer | None = None
