# Design Document: Local Scoring Trial

## Overview

This design adds a local embedding-based scoring system that runs in shadow mode alongside Claude scoring during a trial period. The local scorer uses `sentence-transformers` (all-MiniLM-L6-v2) to embed job descriptions and a k-nearest-neighbors regression against historically scored jobs to predict fit scores without API calls.

The system introduces:
- A `LocalScorer` module that trains on ~870 historical jobs and predicts scores locally
- Shadow mode integration into the existing scoring pipeline
- A `scoring_comparisons` table for side-by-side analysis
- API endpoints under `/scoring-trial/` for the trial dashboard
- Model management (training, retraining, atomic swap)

**Key Design Decisions:**
1. **KNN regression over linear models** — fit scores have non-linear relationships with embedding similarity. KNN captures local patterns in the embedding space without assuming linearity.
2. **Cosine similarity to profile + KNN interpolation** — combines "how similar is this job to what I want" (profile similarity) with "what did Claude score similar jobs" (historical correlation).
3. **Eager loading at startup** — the embedding model (~80MB) and trained artifacts load into memory once at startup, making per-prediction latency negligible (~5ms).
4. **Shadow mode as a pipeline wrapper** — the local scorer is invoked as a pre-step before `run_scoring()`, not inside it. This keeps the existing scoring stage untouched and makes shadow mode trivially removable.

## Architecture

```mermaid
graph TD
    subgraph Pipeline
        PF[Pre-filter Stage] --> LS[Local Scorer<br/>shadow mode]
        LS --> CS[Claude Scoring Stage]
        CS --> SC[Store ScoringComparison]
    end

    subgraph Local Scorer Module
        EM[Embedding Model<br/>all-MiniLM-L6-v2] --> PE[Profile Embedding]
        EM --> JE[Job Embedding]
        JE --> SIM[Cosine Similarity]
        PE --> SIM
        JE --> KNN[KNN Regression]
        SIM --> COMBINE[Combine: weighted score]
        KNN --> COMBINE
        COMBINE --> SCORE[Local Score 0-100]
    end

    subgraph Storage
        DB[(SQLite DB)]
        FS[/data/models/<br/>local_scorer_v{N}.pkl/]
    end

    subgraph API
        API_COMP[GET /scoring-trial/comparisons]
        API_MET[GET /scoring-trial/metrics]
        API_ST[GET /scoring-trial/status]
        API_RT[POST /scoring-trial/retrain]
        API_CFG[PUT /scoring-trial/config]
    end

    LS -->|predict| SCORE
    SC -->|insert| DB
    API_COMP -->|query| DB
    API_MET -->|compute| DB
    API_RT -->|trigger| LS
```

### Component Layout

```
automator/src/
├── scoring/
│   ├── __init__.py
│   ├── local_scorer.py          # Core LocalScorer class
│   ├── embeddings.py            # Embedding model management
│   └── metrics.py               # Metrics computation (MAE, recall, etc.)
├── api/
│   └── scoring_trial_routes.py  # /scoring-trial/* endpoints
├── db/
│   └── scoring_comparison_repo.py  # ScoringComparison CRUD + queries
└── pipeline/
    └── shadow_scoring.py        # Shadow mode orchestration
```

## Components and Interfaces

### 1. LocalScorer (`src/scoring/local_scorer.py`)

The core prediction engine. Stateful — holds the embedding model and trained artifacts in memory.

```python
class LocalScorer:
    """Embedding-based local fit score predictor."""

    def __init__(self, data_dir: str = "data/models") -> None: ...

    @property
    def is_ready(self) -> bool:
        """True if model is trained and loaded."""

    @property
    def model_version(self) -> str | None:
        """Current model version identifier (e.g. 'v3_870samples')."""

    async def initialize(self) -> None:
        """Load embedding model + trained artifacts from disk.
        
        Called once at startup. If artifacts missing, enters dormant state.
        Completes within 10 seconds.
        """

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

    def predict(self, job_description: str) -> int | None:
        """Predict a fit score for a single job description.
        
        Returns:
            Integer 0-100, or None if model not ready.
            
        Performance: <500ms per call, typically ~5ms.
        Deterministic: same input + model = same output.
        """

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
```

**Internal Algorithm:**

1. **Training Phase:**
   - Compute embeddings for all job descriptions (batch encode)
   - Compute profile embedding from concatenated user context
   - Store: embeddings matrix, scores array, profile embedding, KNN parameters
   - Serialize to `data/models/local_scorer_v{N}.pkl` using pickle

2. **Prediction Phase:**
   - Compute embedding for input job description
   - Calculate cosine similarity between job embedding and profile embedding → `profile_sim` (0 to 1)
   - Find K=10 nearest neighbors in training embeddings (cosine distance)
   - Compute distance-weighted average of neighbors' Claude scores → `knn_score`
   - Final score = `clip(0.6 * knn_score + 0.4 * (profile_sim * 100), 0, 100)`
   - Round to integer

### 2. EmbeddingManager (`src/scoring/embeddings.py`)

Handles downloading, caching, and loading the sentence-transformer model.

```python
class EmbeddingManager:
    """Manages the sentence-transformer embedding model lifecycle."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384

    def __init__(self, cache_dir: str = "data/models/embeddings") -> None: ...

    async def load(self) -> bool:
        """Load or download the embedding model.
        
        Returns True if model is ready, False if download failed.
        Downloads to cache_dir on first run; loads from cache thereafter.
        """

    def encode(self, text: str) -> np.ndarray:
        """Encode a single text into a 384-dim vector."""

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        """Encode multiple texts efficiently. Returns (N, 384) matrix."""
```

### 3. Shadow Scoring Orchestrator (`src/pipeline/shadow_scoring.py`)

Wraps the local scorer invocation with error handling and comparison record creation.

```python
async def run_shadow_scoring(
    job_record: JobRecord,
    session: AsyncSession,
    local_scorer: LocalScorer,
    cutoff: int,
) -> int | None:
    """Run local scoring in shadow mode for a single job.
    
    - Invokes local_scorer.predict() with a 500ms timeout
    - On success: returns the local score
    - On exception/timeout: logs error, returns None
    - Never raises — always allows pipeline to continue
    """


async def store_comparison(
    session: AsyncSession,
    job_id: str,
    local_score: int | None,
    claude_score: int,
    model_version: str | None,
    cutoff: int,
) -> None:
    """Create a ScoringComparison record after both scores are available."""
```

### 4. Metrics Calculator (`src/scoring/metrics.py`)

Pure functions for computing trial accuracy metrics.

```python
@dataclass
class TrialMetrics:
    total_compared: int
    mean_absolute_error: float
    recall_at_cutoff: float      # proportion of claude>=65 that local>=cutoff
    false_positive_count: int    # local < cutoff but claude >= 65
    cutoff: int

def compute_metrics(
    comparisons: list[ScoringComparison],
    cutoff: int = 40,
) -> TrialMetrics:
    """Compute aggregate accuracy metrics from comparison records.
    
    Pure function — deterministic for same inputs.
    Excludes records where local_score is None.
    """
```

### 5. API Routes (`src/api/scoring_trial_routes.py`)

```python
router = APIRouter(prefix="/scoring-trial", tags=["scoring-trial"])

@router.get("/comparisons")
async def get_comparisons(
    date_from: str | None = None,
    date_to: str | None = None,
    min_claude_score: int | None = None,
    page: int = 1,
    page_size: int = 50,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> PaginatedComparisons: ...

@router.get("/metrics")
async def get_metrics(
    cutoff: int = 40,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> TrialMetrics: ...

@router.get("/status")
async def get_status(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ScoringTrialStatus: ...

@router.post("/retrain")
async def trigger_retrain(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> RetrainResponse: ...

@router.put("/config")
async def update_config(
    body: ScoringTrialConfigUpdate,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ScoringTrialConfig: ...
```

### 6. Pipeline Integration Point

In `job_pipeline.py`, after pre-filtering and before Claude scoring:

```python
# Inside the scoring loop for each extracted job:
local_score: int | None = None
if local_scorer.is_ready and shadow_mode_enabled:
    local_score = await run_shadow_scoring(
        job_record=job_record,
        session=session,
        local_scorer=local_scorer,
        cutoff=local_score_cutoff,
    )

# Existing Claude scoring (unchanged)
await run_scoring(job_record=job_record, session=session, ...)

# After Claude scoring completes:
if shadow_mode_enabled:
    await store_comparison(
        session=session,
        job_id=job_record.id,
        local_score=local_score,
        claude_score=job_record.fit_score,
        model_version=local_scorer.model_version,
        cutoff=local_score_cutoff,
    )
```

## Data Models

### ScoringComparison (new table: `scoring_comparisons`)

```python
class ScoringComparison(Base):
    """Side-by-side scoring comparison record for the local scoring trial."""

    __tablename__ = "scoring_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="CASCADE"), nullable=False
    )
    local_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claude_score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_difference: Mapped[int | None] = mapped_column(Integer, nullable=True)
    would_skip: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_scoring_comparisons_job_id", "job_id"),
        Index("idx_scoring_comparisons_scored_at", "scored_at"),
        Index("idx_scoring_comparisons_claude_score", "claude_score"),
    )
```

**Computed fields at insert time:**
- `score_difference` = `claude_score - local_score` (NULL if local_score is NULL)
- `would_skip` = 1 if `local_score is not None and local_score < cutoff`, else 0

### Config Keys (added to config table)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `shadow_mode_enabled` | bool | true (when model exists) | Whether shadow scoring is active |
| `local_score_cutoff` | int | 40 | Threshold for would_skip computation |

These are stored as JSON values in the existing `config` table via `get_config`/`set_config`. Since the config repo uses a `Literal` type for keys, the new keys will be added to `ConfigKey` and `VALID_CONFIG_KEYS`.

### Model Artifacts (filesystem)

```
data/models/
├── embeddings/                    # sentence-transformers cache
│   └── all-MiniLM-L6-v2/        # ~80MB cached model files
├── local_scorer_v1.pkl           # trained model (embeddings + scores + params)
├── local_scorer_v2.pkl           # previous version (kept for rollback)
└── local_scorer_active.txt       # pointer to current active version filename
```

**Pickle contents (`local_scorer_v{N}.pkl`):**
```python
{
    "version": "v1_870samples",
    "trained_at": "2024-01-15T10:30:00Z",
    "sample_count": 870,
    "embeddings": np.ndarray,        # shape (N, 384)
    "scores": np.ndarray,            # shape (N,) int
    "profile_embedding": np.ndarray, # shape (384,)
    "knn_k": 10,
    "weights": {"knn": 0.6, "profile_sim": 0.4},
}
```

### Pydantic Response Schemas

```python
class ScoringComparisonResponse(BaseModel):
    id: int
    job_id: str
    job_title: str | None
    company: str | None
    local_score: int | None
    claude_score: int
    score_difference: int | None
    would_skip: bool
    scored_at: str

class PaginatedComparisons(BaseModel):
    items: list[ScoringComparisonResponse]
    total: int
    page: int
    page_size: int

class TrialMetricsResponse(BaseModel):
    total_compared: int
    mean_absolute_error: float
    recall_at_cutoff: float
    false_positive_count: int
    cutoff: int

class ScoringTrialStatus(BaseModel):
    model_trained: bool
    training_samples_count: int
    model_version: str | None
    shadow_mode_active: bool
    total_predictions_made: int

class RetrainResponse(BaseModel):
    success: bool
    sample_count: int
    model_version: str
    duration_seconds: float

class ScoringTrialConfigUpdate(BaseModel):
    shadow_mode_enabled: bool | None = None
    cutoff: int | None = None

class ScoringTrialConfig(BaseModel):
    shadow_mode_enabled: bool
    cutoff: int
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Training data filter correctness

*For any* database containing job records with arbitrary combinations of null/non-null `fit_score` and `description_text`, the training data loader SHALL return exactly the set of records where both `fit_score IS NOT NULL` and `description_text IS NOT NULL`.

**Validates: Requirements 1.1**

### Property 2: Minimum training threshold enforcement

*For any* training set with fewer than 50 records, the `train()` method SHALL raise `InsufficientDataError`. *For any* training set with 50 or more records, the method SHALL complete successfully without raising.

**Validates: Requirements 1.5**

### Property 3: Score output range invariant

*For any* non-empty job description string, when the model is trained, `predict()` SHALL return an integer in the inclusive range [0, 100].

**Validates: Requirements 2.2**

### Property 4: Prediction determinism

*For any* job description string, calling `predict()` twice with the same trained model SHALL produce identical results.

**Validates: Requirements 2.5**

### Property 5: Shadow mode pipeline isolation

*For any* pair of (local_score, claude_score) values where shadow mode is active, the job's resulting pipeline status SHALL be identical to the status that would result from Claude scoring alone — the local_score SHALL have no effect on status transitions.

**Validates: Requirements 3.2**

### Property 6: Computed fields correctness

*For any* `ScoringComparison` record with `local_score` L (nullable), `claude_score` C, and `cutoff` T:
- `score_difference` SHALL equal `C - L` when L is not None, or NULL when L is None
- `would_skip` SHALL equal `L < T` when L is not None, or False when L is None

**Validates: Requirements 4.1, 11.1**

### Property 7: Metrics computation correctness

*For any* non-empty set of `ScoringComparison` records (with non-null local_score) and *any* cutoff value in [0, 100]:
- `mean_absolute_error` SHALL equal the arithmetic mean of `|claude_score - local_score|` across all records
- `recall_at_cutoff` SHALL equal `count(local_score >= cutoff AND claude_score >= 65) / count(claude_score >= 65)` (or 1.0 if no claude_score >= 65 exists)
- `false_positive_count` SHALL equal `count(local_score < cutoff AND claude_score >= 65)`

**Validates: Requirements 5.3, 6.2, 6.3**

### Property 8: Query filter correctness

*For any* set of `ScoringComparison` records and *any* filter combination of (date_from, date_to, min_claude_score), every returned record SHALL satisfy all specified filter criteria, and no record satisfying all criteria SHALL be excluded from the results.

**Validates: Requirements 4.4, 6.1**

### Property 9: Record immutability on cutoff change

*For any* existing set of `ScoringComparison` records, when the `local_score_cutoff` configuration value is changed, the `would_skip` and `score_difference` values of all previously stored records SHALL remain unchanged.

**Validates: Requirements 11.4**

## Error Handling

| Scenario | Behavior | User Impact |
|----------|----------|-------------|
| Embedding model download fails | `LocalScorer` enters dormant state, all predictions return None | Pipeline continues normally with Claude-only scoring |
| Model not trained yet | `predict()` returns None, shadow scoring creates comparison with null local_score | Dashboard shows "needs training" status |
| Prediction exception (any) | Caught in `run_shadow_scoring()`, logged, None stored | Zero pipeline disruption |
| Prediction timeout (>500ms) | `asyncio.wait_for` cancels, None stored | Zero pipeline disruption |
| Retraining fails | HTTP 500 returned, old model retained, error logged | User retries or investigates |
| Retraining with <50 samples | HTTP 500 with "insufficient data" message | User adds more scored jobs first |
| Corrupt pickle file on disk | Caught during `initialize()`, enters dormant state | Needs retrain via API |
| Shadow mode enabled but no model | HTTP 409 on toggle attempt | User must train first |
| OOM from embedding model | Container restart (Docker), model reloads on next start | Brief downtime, auto-recovers |

**Error Propagation Rule:** No error in the local scoring subsystem ever propagates to the main pipeline. Every exception path in `run_shadow_scoring()` is caught and results in a null local_score, not a pipeline failure.

## Testing Strategy

### Property-Based Tests (Hypothesis)

The project already uses `hypothesis` (listed in `requirements.in`). Each property test runs a minimum of 100 iterations.

**Library:** `hypothesis` (already installed)

| Property | Test Target | Generator Strategy |
|----------|-------------|-------------------|
| Property 1: Training data filter | `_load_training_data()` | Random lists of `(description: str|None, fit_score: int|None)` tuples |
| Property 2: Minimum threshold | `LocalScorer.train()` | Random integers [0, 200] for sample count |
| Property 3: Score range | `LocalScorer.predict()` | Random strings (st.text), trained model fixture |
| Property 4: Determinism | `LocalScorer.predict()` | Random strings, verify `predict(x) == predict(x)` |
| Property 5: Pipeline isolation | `run_scoring()` result comparison | Random (local_score, claude_score) pairs, mock pipeline |
| Property 6: Computed fields | `store_comparison()` | Random int|None for local_score, random int for claude_score, random int for cutoff |
| Property 7: Metrics | `compute_metrics()` | Random lists of `ScoringComparison` records, random cutoff |
| Property 8: Query filters | `query_comparisons()` | Random comparison records, random filter params |
| Property 9: Immutability | `store_comparison()` before/after cutoff change | Random records, then random new cutoff |

Each test is tagged: `# Feature: local-scoring-trial, Property {N}: {description}`

### Unit Tests (pytest)

- `test_local_scorer_predict_returns_none_when_not_ready` — verifies dormant state
- `test_local_scorer_retrain_atomic_swap` — verifies old model serves during retraining
- `test_shadow_scoring_exception_handling` — verifies pipeline continues on error
- `test_shadow_scoring_timeout` — verifies 500ms timeout behavior
- `test_api_comparisons_pagination` — verifies page/page_size math
- `test_api_metrics_empty_data` — verifies response when <10 comparisons
- `test_api_retrain_no_model` — verifies 409 response
- `test_api_config_toggle_requires_model` — verifies 409 on enable without model
- `test_config_keys_registered` — verifies new config keys in `VALID_CONFIG_KEYS`
- `test_startup_loads_model_eagerly` — verifies model in memory after startup

### Integration Tests

- `test_full_shadow_scoring_pipeline` — end-to-end: train → predict → store comparison → query via API
- `test_retrain_while_predicting` — concurrent retrain + predict operations
- `test_model_persistence_across_restart` — save, reload from disk, verify same predictions

### Dependencies to Add

```
# requirements.in additions:
sentence-transformers
scikit-learn
numpy
```

These are significant additions (~500MB installed). The Docker image size will increase accordingly. The embedding model itself (~80MB) is downloaded at runtime to the data volume, not baked into the image.

### Performance Budget

| Operation | Budget | Expected |
|-----------|--------|----------|
| Single prediction | <500ms | ~5ms |
| 20 predictions (full batch) | <30s | ~100ms |
| Model training (870 samples) | <60s | ~15s |
| Startup model load | <10s | ~3s |
| Embedding model download (first run) | <120s | ~30s (network dependent) |
