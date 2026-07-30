# Requirements Document

## Introduction

This feature adds a local embedding-based scoring model that runs in shadow mode alongside the existing Claude API scoring during a trial period. The local scorer uses sentence-transformer embeddings trained on 870 historically scored jobs to predict fit scores without API calls. During Phase 1 (this spec), both scores are recorded for every job but only the Claude score drives pipeline decisions. A temporary "Scoring Trial" tab in the web app displays side-by-side comparison data with accuracy metrics so the user can evaluate whether the local model is reliable enough to eventually replace Claude scoring for low-confidence jobs.

The local scorer is tuned for high recall on good-fit jobs (fit_score ≥ 65). False positives (local model predicts skip when Claude would score 65+) are unacceptable. False negatives (local model predicts keep when Claude scores low) are tolerable because they only cost a scoring API call. The local scorer adds zero API cost per prediction — all computation is local.

This is a temporary analytical feature for evaluating model readiness. The Trial Dashboard is not a consumer-facing feature and will be removed or replaced once the user decides on a cutoff threshold (Phase 2).

## Glossary

- **Local_Scorer**: The Python module that computes embedding-based fit scores using a sentence-transformer model trained on historical job data.
- **Claude_Scorer**: The existing Claude API-based scoring system that produces fit_score (0–100) with sub-dimensional breakdown.
- **Shadow_Mode**: An operational mode where the Local_Scorer runs on every pre-filtered job and records its prediction alongside the Claude score, without influencing pipeline decisions.
- **Training_Set**: The set of historically scored job records with Claude-assigned fit_scores (currently ~870 jobs) used to train the Local_Scorer.
- **Embedding_Model**: A sentence-transformer model (all-MiniLM-L6-v2, ~80MB) that converts text into dense vector representations.
- **Profile_Embedding**: The reference embedding computed from the user's SKILLS_AND_CONTEXT.md and goals_profile supplementary context.
- **Local_Score**: The numeric prediction (0–100) produced by the Local_Scorer for a given job description.
- **Scoring_Comparison**: A database record that stores both the local_score and claude_score for a single job, enabling trial analysis.
- **Trial_Dashboard**: A temporary tab in the web application that displays scoring comparison data and accuracy metrics. This is an analytical developer tool, not a permanent consumer feature.
- **Recall**: The proportion of good-fit jobs (Claude score ≥ 65) that the Local_Scorer correctly identifies as worth scoring.
- **Automator**: The FastAPI backend service running inside Docker that orchestrates the job application pipeline.
- **Pipeline**: The sequential processing stages: discovery → pre-filter → scoring → tailoring → apply.

## Requirements

### Requirement 1: Local Scorer Model Training

**User Story:** As a user, I want the local scorer to learn from my historically scored jobs, so that it can predict fit scores based on my actual preferences rather than generic heuristics.

#### Acceptance Criteria

1. WHEN a training command is invoked, THE Local_Scorer SHALL load all job records from the database that have a non-null fit_score and non-null description_text as the Training_Set.
2. WHEN training data is loaded, THE Local_Scorer SHALL compute an embedding for each job description using the Embedding_Model and store the resulting vectors alongside their corresponding Claude fit_scores.
3. WHEN training completes, THE Local_Scorer SHALL persist the trained model artifacts (embeddings, scores, and any fitted regression parameters) to a file on disk within the data directory so that the model survives container restarts.
4. THE Local_Scorer SHALL compute the Profile_Embedding from the concatenation of the user's SKILLS_AND_CONTEXT.md content and the goals_profile supplementary_context field.
5. IF the Training_Set contains fewer than 50 job records with non-null fit_score, THEN THE Local_Scorer SHALL log a warning and refuse to produce predictions until more training data is available.
6. WHEN the training command completes successfully, THE Local_Scorer SHALL log the number of training samples used, the model file path, and the total training duration.

---

### Requirement 2: Local Score Prediction

**User Story:** As a user, I want the local scorer to produce a numeric fit prediction for each job, so that I can compare it against Claude's scores and evaluate accuracy.

#### Acceptance Criteria

1. WHEN a job description is provided for scoring, THE Local_Scorer SHALL compute an embedding for the description using the same Embedding_Model used during training.
2. THE Local_Scorer SHALL produce a Local_Score in the range 0–100 by combining the cosine similarity between the job embedding and the Profile_Embedding with a learned mapping from the Training_Set that correlates embedding distances to Claude fit_scores.
3. WHEN the trained model artifacts are not found on disk, THE Local_Scorer SHALL return a null Local_Score and log a warning indicating that training has not been completed.
4. THE Local_Scorer SHALL produce a prediction within 500 milliseconds per job on the host hardware (no GPU required).
5. THE Local_Scorer SHALL be deterministic — the same job description and model artifacts SHALL produce the same Local_Score on every invocation.
6. THE Local_Scorer SHALL add zero API cost per prediction — all computation occurs locally using the cached Embedding_Model.

---

### Requirement 3: Shadow Mode Pipeline Integration

**User Story:** As a user, I want the local scorer to run alongside Claude scoring on every job without affecting pipeline decisions, so that I can collect comparison data safely.

#### Acceptance Criteria

1. WHILE Shadow_Mode is active, THE Pipeline SHALL invoke the Local_Scorer on every job that passes pre-filtering, before the Claude scoring call.
2. WHILE Shadow_Mode is active, THE Pipeline SHALL use only the Claude fit_score for all pipeline decisions (skip/approve thresholds, notifications, tailoring triggers). The Local_Score SHALL have no effect on job status transitions.
3. WHEN both scores are available for a job, THE Pipeline SHALL store the Local_Score in the Scoring_Comparison record linked to that job.
4. IF the Local_Scorer raises an exception or times out during prediction, THEN THE Pipeline SHALL log the error, record a null Local_Score for that job, and continue with Claude scoring without interruption.
5. THE Local_Scorer invocation SHALL NOT increase the total pipeline time for 20 jobs by more than 30 seconds (well within the existing 5-minute target for discovery + scoring of 20 jobs).
6. WHEN Shadow_Mode is active, THE Pipeline SHALL log both scores for each scored job in the structured log output.

---

### Requirement 4: Scoring Comparison Data Storage

**User Story:** As a user, I want both scores stored together with metadata, so that I can analyze accuracy, correlation, and drift over time.

#### Acceptance Criteria

1. THE Automator SHALL store each Scoring_Comparison record with the following fields: job_id, local_score (nullable integer 0–100), claude_score (integer 0–100), score_difference (computed: claude_score minus local_score), scored_at (ISO 8601 timestamp), and model_version (string identifying the Local_Scorer model file).
2. WHEN a job is scored in Shadow_Mode, THE Automator SHALL create a Scoring_Comparison record regardless of whether the Local_Score is null (due to model not trained or prediction failure).
3. THE Automator SHALL retain all Scoring_Comparison records without automatic deletion so that the full trial history is available for analysis.
4. WHEN queried, THE Scoring_Comparison data SHALL support filtering by date range, by score threshold, and by whether the local model would have been a false positive (local predicted skip but Claude scored ≥ 65).

---

### Requirement 5: Trial Dashboard — Comparison View

**User Story:** As a user, I want a dedicated tab showing side-by-side scores and accuracy metrics, so that I can decide when the local model is trustworthy enough to use for filtering.

#### Acceptance Criteria

1. THE Trial_Dashboard SHALL appear as a tab labeled "Scoring Trial" in the web application navigation, visually distinct from permanent tabs to indicate its temporary nature.
2. THE Trial_Dashboard SHALL display a table of recent Scoring_Comparison records showing: job title, company, local_score, claude_score, score_difference, and scored_at, sorted by scored_at descending.
3. THE Trial_Dashboard SHALL display aggregate accuracy metrics including: total jobs compared, mean absolute error between local and Claude scores, recall at the 65-threshold (percentage of Claude ≥ 65 jobs that Local_Scorer also scored above the trial cutoff), and count of false positives (local below cutoff but Claude ≥ 65).
4. THE Trial_Dashboard SHALL highlight false positive rows (where local_score is below the trial cutoff but claude_score ≥ 65) with a distinct visual indicator so the user can inspect which good jobs would have been missed.
5. WHEN fewer than 10 Scoring_Comparison records exist, THE Trial_Dashboard SHALL display a message indicating that more data is needed before metrics are meaningful.
6. THE Trial_Dashboard SHALL include a numeric input field labeled "Trial Cutoff" (default: 40) that dynamically recalculates the recall and false positive metrics when changed, without requiring a page reload or API call.

---

### Requirement 6: Trial Dashboard — API Endpoints

**User Story:** As a user, I want the comparison data accessible via API, so that the frontend can render the trial dashboard and I can query data programmatically if needed.

#### Acceptance Criteria

1. WHEN a GET request is made to `/scoring-trial/comparisons`, THE Automator SHALL return a paginated list of Scoring_Comparison records with optional query parameters for date_from, date_to, and min_claude_score.
2. WHEN a GET request is made to `/scoring-trial/metrics`, THE Automator SHALL return the aggregate metrics object containing: total_compared, mean_absolute_error, recall_at_cutoff, false_positive_count, and the cutoff value used for calculation.
3. THE `/scoring-trial/metrics` endpoint SHALL accept an optional `cutoff` query parameter (integer 0–100, default 40) that determines the threshold used for recall and false positive calculations.
4. WHEN a GET request is made to `/scoring-trial/status`, THE Automator SHALL return the current state of the local scoring system including: model_trained (boolean), training_samples_count (integer), model_version (string or null), shadow_mode_active (boolean), and total_predictions_made (integer).
5. THE scoring trial endpoints SHALL require bearer token authentication consistent with all other Automator API endpoints.

---

### Requirement 7: Model Retraining

**User Story:** As a user, I want to retrain the local model as new scored jobs accumulate, so that the model stays current with my evolving preferences and the job market.

#### Acceptance Criteria

1. WHEN a POST request is made to `/scoring-trial/retrain`, THE Automator SHALL trigger a full retraining of the Local_Scorer using all current job records with non-null fit_score and description_text.
2. WHILE retraining is in progress, THE Automator SHALL continue using the previously trained model for predictions without interruption.
3. WHEN retraining completes successfully, THE Automator SHALL atomically swap the active model to the newly trained version and increment the model_version identifier.
4. WHEN retraining completes, THE Automator SHALL log the training duration, sample count, and new model_version.
5. IF retraining fails due to insufficient data or an internal error, THEN THE Automator SHALL log the error, retain the existing model, and return an HTTP 500 response with error details.

---

### Requirement 8: Embedding Model Management

**User Story:** As a user, I want the embedding model to be downloaded and cached inside the Docker container, so that scoring works offline without external API dependencies.

#### Acceptance Criteria

1. THE Automator Docker image SHALL include the sentence-transformers Python package and its dependencies in the container build.
2. WHEN the Local_Scorer is first initialized, THE Local_Scorer SHALL download the Embedding_Model (all-MiniLM-L6-v2, ~80MB) to a cache directory within the data volume if not already present.
3. WHEN the Embedding_Model is already cached in the data volume, THE Local_Scorer SHALL load it from cache without network access.
4. THE Embedding_Model cache SHALL persist across container restarts via the mounted data volume.
5. IF the Embedding_Model download fails on first initialization (no network, timeout, or corrupted download), THEN THE Local_Scorer SHALL log an error and operate in a degraded state where all predictions return null until the model is successfully downloaded.
6. THE loaded Embedding_Model SHALL consume no more than 200MB of additional memory beyond the Automator baseline, keeping the container within the 512MB baseline memory target when not actively processing.

---

### Requirement 9: Shadow Mode Configuration

**User Story:** As a user, I want to enable or disable shadow mode, so that I can control when the local scorer is actively running and collecting comparison data.

#### Acceptance Criteria

1. THE Automator SHALL store a `shadow_mode_enabled` boolean flag in the config table, defaulting to true when the Local_Scorer model artifacts exist on disk.
2. WHEN shadow_mode_enabled is false, THE Pipeline SHALL skip Local_Scorer invocation entirely and create no Scoring_Comparison records.
3. WHEN a PUT request is made to `/scoring-trial/config` with a JSON body containing `shadow_mode_enabled`, THE Automator SHALL update the configuration flag and return the updated state.
4. THE `/scoring-trial/config` endpoint SHALL require bearer token authentication.
5. WHEN shadow_mode is toggled from disabled to enabled, THE Automator SHALL verify that trained model artifacts exist on disk before activating, and return an HTTP 409 response with an error message if no trained model is found.

---

### Requirement 10: Service Startup Behavior

**User Story:** As a user, I want the local scorer to be ready when the pipeline runs, so that scoring predictions don't delay the first pipeline execution.

#### Acceptance Criteria

1. WHEN the Automator service starts, THE Local_Scorer SHALL eagerly load the Embedding_Model and trained model artifacts into memory if both are present on disk.
2. IF the Embedding_Model or trained artifacts are missing at startup, THEN THE Local_Scorer SHALL log an informational message and remain in a dormant state without blocking service startup.
3. WHEN the Local_Scorer is in dormant state, THE Pipeline SHALL skip local scoring without error and proceed directly to Claude scoring.
4. THE Local_Scorer initialization SHALL complete within 10 seconds of service startup.

---

### Requirement 11: Phase 2 Schema Accommodation

**User Story:** As a user, I want the data schema to support eventual cutoff-based filtering, so that transitioning to Phase 2 (skipping Claude for low local scores) requires no schema migrations.

#### Acceptance Criteria

1. THE Scoring_Comparison table schema SHALL include a `would_skip` boolean column (computed at insert time based on whether local_score is below the configured trial cutoff) to enable future filtering analysis.
2. THE config table SHALL store a `local_score_cutoff` integer value (default: 40) that is used for the `would_skip` computation and exposed in the Trial_Dashboard.
3. THE `/scoring-trial/config` endpoint SHALL accept a `cutoff` integer parameter to update the stored cutoff value.
4. WHEN the cutoff value is changed, THE Automator SHALL NOT retroactively update existing Scoring_Comparison records — only new records SHALL use the updated cutoff for the `would_skip` field.

