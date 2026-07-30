# Implementation Plan: Local Scoring Trial

## Overview

Implement a local embedding-based scoring system that runs in shadow mode alongside Claude scoring. The implementation is ordered for incremental buildability: data layer first, then the core scorer, then pipeline integration, then API endpoints, and finally frontend. Each task produces a testable, working state.

## Tasks

- [x] 1. Add dependencies and create scoring module structure
  - [x] 1.1 Add `sentence-transformers`, `scikit-learn`, and `numpy` to `automator/requirements.in` and run `pip-compile`
    - Add the three packages to `requirements.in`
    - Run `pip-compile requirements.in --output-file requirements.txt`
    - _Requirements: 8.1_

  - [x] 1.2 Create the `automator/src/scoring/` package with `__init__.py`
    - Create directory `automator/src/scoring/`
    - Create empty `__init__.py`
    - _Requirements: N/A (project structure)_

- [x] 2. Implement data layer — ScoringComparison model and repository
  - [x] 2.1 Add `ScoringComparison` model to `automator/src/db/models.py`
    - Add the `ScoringComparison` class with columns: `id`, `job_id` (FK to job_records), `local_score` (nullable int), `claude_score` (int), `score_difference` (nullable int), `would_skip` (int, default 0), `model_version` (nullable text), `scored_at` (text)
    - Add indexes on `job_id`, `scored_at`, and `claude_score`
    - _Requirements: 4.1, 4.3, 11.1_

  - [x] 2.2 Add `shadow_mode_enabled` and `local_score_cutoff` to `ConfigKey` and `VALID_CONFIG_KEYS` in `automator/src/db/config_repo.py`
    - Add `"shadow_mode_enabled"` and `"local_score_cutoff"` to the `Literal` type and `frozenset`
    - _Requirements: 9.1, 11.2_

  - [x] 2.3 Create `automator/src/db/scoring_comparison_repo.py` with CRUD and query functions
    - Implement `create_comparison(session, job_id, local_score, claude_score, model_version, cutoff)` — computes `score_difference` and `would_skip` at insert time
    - Implement `query_comparisons(session, date_from, date_to, min_claude_score, page, page_size)` — paginated filtered query
    - Implement `count_comparisons(session)` — total record count
    - Implement `get_all_comparisons_for_metrics(session)` — returns all records with non-null local_score for metrics computation
    - _Requirements: 4.1, 4.2, 4.4, 11.1, 11.4_

  - [x] 2.4 Write property test for computed fields correctness (Property 6)
    - **Property 6: Computed fields correctness**
    - Test that `score_difference = claude_score - local_score` when local_score is not None, else NULL
    - Test that `would_skip = (local_score < cutoff)` when local_score is not None, else 0
    - **Validates: Requirements 4.1, 11.1**

  - [x] 2.5 Write property test for query filter correctness (Property 8)
    - **Property 8: Query filter correctness**
    - Generate random comparison records and random filter params, verify every returned record satisfies all filters and no valid record is excluded
    - **Validates: Requirements 4.4, 6.1**

  - [x] 2.6 Write property test for record immutability on cutoff change (Property 9)
    - **Property 9: Record immutability on cutoff change**
    - Store records with one cutoff, change the cutoff config, verify existing records' `would_skip` and `score_difference` are unchanged
    - **Validates: Requirements 11.4**

- [x] 3. Checkpoint — Ensure data layer tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement EmbeddingManager
  - [x] 4.1 Create `automator/src/scoring/embeddings.py` with the `EmbeddingManager` class
    - Implement `__init__(self, cache_dir)` defaulting to `data/models/embeddings`
    - Implement `async load() -> bool` — downloads/loads sentence-transformer model from cache
    - Implement `encode(text: str) -> np.ndarray` — returns 384-dim vector
    - Implement `encode_batch(texts: list[str]) -> np.ndarray` — returns (N, 384) matrix
    - Handle download failure gracefully (return False from `load()`)
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 5. Implement LocalScorer core
  - [x] 5.1 Create `automator/src/scoring/local_scorer.py` with the `LocalScorer` class
    - Implement `__init__(self, data_dir)` defaulting to `data/models`
    - Implement `is_ready` property and `model_version` property
    - Implement `async initialize()` — loads embedding model + trained artifacts from disk
    - Implement `async train(job_descriptions, fit_scores, profile_text) -> TrainingResult`
      - Compute embeddings for all descriptions (batch encode)
      - Compute profile embedding
      - Store embeddings matrix, scores array, profile embedding, KNN params
      - Serialize to `data/models/local_scorer_v{N}.pkl`
      - Raise `InsufficientDataError` if < 50 samples
    - Implement `predict(job_description: str) -> int | None`
      - Compute job embedding
      - Cosine similarity to profile embedding → `profile_sim`
      - K=10 nearest neighbors, distance-weighted average → `knn_score`
      - Final = `clip(0.6 * knn_score + 0.4 * (profile_sim * 100), 0, 100)`
      - Return integer, or None if not ready
    - Implement `async retrain_atomic(...)` — trains new model, swaps atomically
    - Define `TrainingResult` and `InsufficientDataError` in the module
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 5.2 Implement training data loader helper in `local_scorer.py`
    - Function `_load_training_data(session) -> tuple[list[str], list[int]]` that queries job_records with non-null fit_score AND non-null description_text
    - _Requirements: 1.1_

  - [x] 5.3 Write property test for training data filter correctness (Property 1)
    - **Property 1: Training data filter correctness**
    - Generate random lists of (description: str|None, fit_score: int|None) tuples, verify only records with both non-null are returned
    - **Validates: Requirements 1.1**

  - [x] 5.4 Write property test for minimum training threshold (Property 2)
    - **Property 2: Minimum training threshold enforcement**
    - Generate random integers [0, 200] for sample count, verify `train()` raises `InsufficientDataError` when < 50 and succeeds when >= 50
    - **Validates: Requirements 1.5**

  - [x] 5.5 Write property test for score output range (Property 3)
    - **Property 3: Score output range invariant**
    - Generate random non-empty strings, verify `predict()` returns int in [0, 100]
    - **Validates: Requirements 2.2**

  - [x] 5.6 Write property test for prediction determinism (Property 4)
    - **Property 4: Prediction determinism**
    - Generate random strings, verify `predict(x) == predict(x)` for same model
    - **Validates: Requirements 2.5**

- [x] 6. Checkpoint — Ensure scorer tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement shadow scoring pipeline integration
  - [x] 7.1 Create `automator/src/pipeline/shadow_scoring.py`
    - Implement `async run_shadow_scoring(job_record, session, local_scorer, cutoff) -> int | None`
      - Calls `local_scorer.predict()` with 500ms `asyncio.wait_for` timeout
      - On success: returns the local score
      - On exception/timeout: logs error, returns None
      - Never raises
    - Implement `async store_comparison(session, job_id, local_score, claude_score, model_version, cutoff) -> None`
      - Creates a `ScoringComparison` record via the repo
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.2_

  - [x] 7.2 Integrate shadow scoring into the pipeline loop in `automator/src/pipeline/job_pipeline.py`
    - After pre-filtering, before Claude scoring: invoke `run_shadow_scoring` if model is ready and shadow mode enabled
    - After Claude scoring completes: call `store_comparison` if shadow mode enabled
    - Read `shadow_mode_enabled` and `local_score_cutoff` from config
    - Log both scores in structured log output
    - _Requirements: 3.1, 3.2, 3.6, 9.2_

  - [x] 7.3 Write property test for pipeline isolation (Property 5)
    - **Property 5: Shadow mode pipeline isolation**
    - Generate random (local_score, claude_score) pairs, verify job status is identical to Claude-only scoring
    - **Validates: Requirements 3.2**

  - [x] 7.4 Write unit tests for shadow scoring error handling
    - Test that `run_shadow_scoring` catches exceptions and returns None
    - Test 500ms timeout behavior
    - Test that pipeline continues on any local scorer failure
    - _Requirements: 3.4, 3.5_

- [x] 8. Implement metrics calculator
  - [x] 8.1 Create `automator/src/scoring/metrics.py`
    - Define `TrialMetrics` dataclass with: `total_compared`, `mean_absolute_error`, `recall_at_cutoff`, `false_positive_count`, `cutoff`
    - Implement `compute_metrics(comparisons, cutoff=40) -> TrialMetrics` as a pure function
      - MAE = mean of |claude_score - local_score| for records with non-null local_score
      - recall_at_cutoff = count(local >= cutoff AND claude >= 65) / count(claude >= 65), or 1.0 if no claude >= 65
      - false_positive_count = count(local < cutoff AND claude >= 65)
    - _Requirements: 5.3, 6.2, 6.3_

  - [x] 8.2 Write property test for metrics computation (Property 7)
    - **Property 7: Metrics computation correctness**
    - Generate random lists of ScoringComparison records and random cutoff, verify MAE, recall, and false_positive_count formulas
    - **Validates: Requirements 5.3, 6.2, 6.3**

- [x] 9. Implement API endpoints
  - [x] 9.1 Create `automator/src/api/scoring_trial_routes.py` with the router
    - Define Pydantic response schemas: `ScoringComparisonResponse`, `PaginatedComparisons`, `TrialMetricsResponse`, `ScoringTrialStatus`, `RetrainResponse`, `ScoringTrialConfigUpdate`, `ScoringTrialConfig`
    - Implement `GET /scoring-trial/comparisons` — paginated, filtered by date_from, date_to, min_claude_score
    - Implement `GET /scoring-trial/metrics` — accepts optional `cutoff` param (default 40)
    - Implement `GET /scoring-trial/status` — returns model_trained, training_samples_count, model_version, shadow_mode_active, total_predictions_made
    - Implement `POST /scoring-trial/retrain` — triggers full retrain using all eligible records, returns RetrainResponse
    - Implement `PUT /scoring-trial/config` — update shadow_mode_enabled and/or cutoff; returns HTTP 409 if enabling shadow mode without a trained model
    - All endpoints require bearer token auth via `verify_token` dependency
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 9.3, 9.4, 9.5, 11.3_

  - [x] 9.2 Register the scoring trial router in `automator/src/main.py`
    - Import and include the router with `app.include_router()`
    - _Requirements: 6.5_

  - [x] 9.3 Write unit tests for API endpoints
    - Test pagination math on `/comparisons`
    - Test `/metrics` returns appropriate response when < 10 comparisons
    - Test `/retrain` returns 409 when insufficient data
    - Test `/config` returns 409 when enabling shadow mode without trained model
    - _Requirements: 6.1, 6.2, 6.4, 7.5, 9.5_

- [x] 10. Implement startup initialization
  - [x] 10.1 Add `LocalScorer` eager initialization to the lifespan in `automator/src/main.py`
    - Instantiate `LocalScorer` and call `await local_scorer.initialize()` during startup
    - Store on `app.state.local_scorer` so API routes and pipeline can access it
    - If model/embedding not found, log informational message and continue (dormant state)
    - Complete within 10 seconds
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 10.2 Write unit test for startup initialization
    - Verify model loads eagerly when artifacts exist
    - Verify dormant state when artifacts are missing, service still starts
    - _Requirements: 10.1, 10.2_

- [x] 11. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement Trial Dashboard frontend tab
  - [x] 12.1 Create the "Scoring Trial" tab component with comparison table
    - Add a new tab labeled "Scoring Trial" to the web app navigation
    - Display a table of recent comparisons: job title, company, local_score, claude_score, score_difference, scored_at (sorted descending)
    - Highlight false positive rows (local < cutoff but claude >= 65) with a distinct visual indicator
    - Implement pagination controls
    - _Requirements: 5.1, 5.2, 5.4_

  - [x] 12.2 Add aggregate metrics display and trial cutoff input
    - Display metrics: total compared, MAE, recall at cutoff, false positive count
    - Add numeric input field "Trial Cutoff" (default: 40) that dynamically recalculates metrics client-side without API call
    - Show "insufficient data" message when < 10 comparisons exist
    - _Requirements: 5.3, 5.5, 5.6_

  - [x] 12.3 Add model status display and retrain button
    - Show model status: trained/not trained, sample count, model version, shadow mode active/inactive
    - Add "Retrain Model" button that calls `POST /scoring-trial/retrain`
    - Add shadow mode toggle that calls `PUT /scoring-trial/config`
    - _Requirements: 6.4, 7.1, 9.3_

- [x] 13. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The frontend tasks (12.x) can be implemented in parallel with backend tasks after task 9.2
- The `data/models/` directory is created on first train — no manual setup needed
- Docker image size will increase ~500MB due to sentence-transformers + scikit-learn + numpy

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6", "4.1"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3", "5.4", "5.5", "5.6", "8.1"] },
    { "id": 6, "tasks": ["7.1", "8.2"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 8, "tasks": ["9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 10, "tasks": ["10.2", "12.1"] },
    { "id": 11, "tasks": ["12.2", "12.3"] }
  ]
}
```
