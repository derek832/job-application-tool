# Requirements Document

## Introduction

This feature replaces the Claude API calls for job scoring and resume tailoring with local LLM inference via Ollama (Qwen2.5-32B-Instruct Q4_K_M). The system supports a phased rollout with three operating modes: claude-only (current behavior), shadow (both models run, Claude drives decisions), and local-primary (local LLM drives, Claude handles low-confidence escalations). The local model is loaded into VRAM on-demand before scheduled pipeline runs and unloaded afterward to avoid idle GPU consumption.

The existing `local-scoring-trial` feature provides an embedding-based KNN scorer running in shadow mode. This feature supersedes that approach for scoring by using full generative inference (structured prompt → score), and extends local processing to resume tailoring — a capability the embedding scorer cannot provide. The scoring_comparisons infrastructure is extended to store LLM comparison data.

Hardware constraints: NVIDIA 4080 Super (16GB VRAM), 32GB system RAM, 980 Pro NVMe SSD. The Qwen2.5-32B Q4_K_M quantization (~20GB) fits across GPU VRAM and system RAM via Ollama's automatic layer splitting. Ollama runs on the host machine; the Docker-based automator reaches it via `host.docker.internal`.

Performance expectations: 30–60 seconds per job for scoring, 60–90 seconds per tailoring. Speed is not a concern — cost elimination and privacy are the drivers.

## Glossary

- **Ollama**: The local LLM inference server running on the host machine, serving models via an HTTP API on port 11434.
- **Local_LLM**: The Qwen2.5-32B-Instruct Q4_K_M model served by Ollama for scoring and tailoring inference.
- **Automator**: The FastAPI backend service running inside Docker that orchestrates the job application pipeline.
- **Pipeline**: The sequential processing stages: discovery → pre-filter → scoring → tailoring → apply.
- **Claude_Scorer**: The existing Claude API-based scoring system that produces fit_score (0–100) with sub-dimensional breakdown and deal-breaker detection.
- **Claude_Tailor**: The existing Claude API-based resume tailoring system that produces JSON replacement instructions for the Google Docs resume.
- **LLM_Scorer**: The module that invokes the Local_LLM via Ollama to produce fit scores in the same structured format as the Claude_Scorer.
- **LLM_Tailor**: The module that invokes the Local_LLM via Ollama to produce resume tailoring replacements in the same structured format as the Claude_Tailor.
- **Operating_Mode**: The system's current inference routing strategy — one of: `claude-only`, `shadow`, or `local-primary`.
- **Shadow_Mode**: An Operating_Mode where both Claude and the Local_LLM run on every job, but only Claude's output drives pipeline decisions. Comparison data is stored for quality evaluation.
- **Local_Primary_Mode**: An Operating_Mode where the Local_LLM drives pipeline decisions, with Claude used only as a fallback for low-confidence escalations.
- **Confidence_Score**: A numeric indicator (0–100) produced alongside the LLM_Scorer output representing the model's certainty in its fit_score prediction.
- **Escalation_Threshold**: The configurable confidence score boundary below which a job is escalated to Claude for re-scoring in Local_Primary_Mode.
- **Escalation_Signal**: Any condition — self-assessed confidence, threshold proximity, parse instability, short job description, noisy role title, or disagreement history — that triggers escalation to Claude in Local_Primary_Mode.
- **Model_Lifecycle_Manager**: The component responsible for loading and unloading the Local_LLM in Ollama on demand, timed to pipeline schedule.
- **Prompt_Config**: A versioned configuration object storing the scoring or tailoring prompt template, generation parameters, identified by name and version number.
- **LLM_Comparison**: A database record storing the outputs of both Claude and the Local_LLM for a single job, enabling quality comparison during shadow mode.
- **Ollama_API**: The HTTP REST API exposed by Ollama at `http://host.docker.internal:11434` for model management and inference.
- **Keep_Alive_Timeout**: The Ollama parameter controlling how long a model stays loaded in memory after the last request (set to 0 for immediate unload, or a duration for graceful window).
- **JSON_Repair_Layer**: A pre-retry processing step that attempts to fix common LLM output formatting issues (markdown fences, trailing commas, smart quotes, extra prose, single quotes, missing wrappers) before resorting to a full retry or escalation.
- **False_Skip_Rate**: The percentage of jobs where the local model recommended skip but Claude recommended approve — the primary safety metric that must be below 5% before local-primary mode is recommended.

## Requirements

### Requirement 1: Local LLM Scoring

**User Story:** As a user, I want job descriptions scored by a local LLM instead of Claude, so that I eliminate per-job API costs while maintaining scoring quality.

#### Acceptance Criteria

1. WHEN a job description is submitted for scoring, THE LLM_Scorer SHALL send a structured prompt to the Local_LLM via the Ollama_API and parse the response into a fit_score (integer 0–100), a rationale (string, maximum 200 words), a deal_breaker_found (boolean) with an optional deal_breaker_term (string, maximum 100 characters), and a Confidence_Score (integer 0–100).
2. THE LLM_Scorer SHALL produce output in the same structured format as the Claude_Scorer (fit_score, rationale, deal_breaker_found, deal_breaker_term) so that downstream pipeline stages require no modification.
3. WHEN the Local_LLM response cannot be parsed into the expected structured format, THE LLM_Scorer SHALL first apply the JSON_Repair_Layer to attempt automatic correction of common formatting issues (markdown code fences, trailing commas, smart quotes, extra prose before/after JSON, single quotes, and missing top-level wrappers), then perform strict JSON validation on the repaired output; IF the repaired output still fails validation, THEN THE LLM_Scorer SHALL retry the request once with a retry prompt that includes an explicit JSON schema example and reduced instruction complexity; IF parsing fails after the retry, THE LLM_Scorer SHALL return a parsing error that causes the Pipeline to fall back to the Claude_Scorer for that job.
4. THE LLM_Scorer SHALL include a Confidence_Score (integer 0–100) derived from the model's self-assessed certainty in its scoring, extracted from the structured prompt response.
5. IF the Local_LLM does not return a complete response within 90 seconds, THEN THE LLM_Scorer SHALL terminate the request, log a timeout error, and the Pipeline SHALL fall back to the Claude_Scorer for that job. THE LLM_Scorer SHALL log a warning if any single scoring call exceeds 60 seconds.
6. THE LLM_Scorer SHALL produce a fit_score for the same job description that is within ±15 points of a previous scoring of the same description 90% of the time (approximate determinism, validated during shadow mode).

---

### Requirement 2: Local LLM Resume Tailoring

**User Story:** As a user, I want resumes tailored by the local LLM instead of Claude, so that I eliminate tailoring API costs while maintaining resume quality.

#### Acceptance Criteria

1. WHEN a job description and resume base are submitted for tailoring, THE LLM_Tailor SHALL send a structured prompt to the Local_LLM via the Ollama_API and parse the response into a JSON array of replacement instructions, where each element contains a "find" string and a "replace" string, compatible with the existing GDocs write-back format.
2. THE LLM_Tailor SHALL produce output in the same JSON replacement format as the Claude_Tailor so that the GDocs client, PDF export, and restore flow require no modification.
3. WHEN the Local_LLM response cannot be parsed into valid JSON replacement instructions, THE LLM_Tailor SHALL first apply the JSON_Repair_Layer to attempt automatic correction of common formatting issues (markdown code fences, trailing commas, smart quotes, extra prose before/after JSON, single quotes, and missing top-level wrappers), then perform strict JSON validation on the repaired output; IF the repaired output still fails validation, THEN THE LLM_Tailor SHALL retry the request once with a simplified prompt; IF parsing fails after the retry, THE LLM_Tailor SHALL set the job status to "resume_failed" with queue_reason "resume_tailoring_failed" and log the parsing error.
4. THE LLM_Tailor SHALL complete tailoring for a single job within 120 seconds, and log a warning if any single tailoring call exceeds 90 seconds.
5. THE LLM_Tailor SHALL preserve all factual content from the resume base — the tailored output SHALL NOT introduce experiences, skills, certifications, or employment dates that do not exist in the original resume or supplementary context, and every "find" value in the replacement array SHALL correspond to text present in the resume base.
6. IF the Local_LLM returns a valid JSON response containing an empty replacement array, THEN THE LLM_Tailor SHALL treat this as a tailoring failure, retry once, and if the second response also yields an empty array, set the job status to "resume_failed" with queue_reason "resume_tailoring_failed".
7. THE LLM_Tailor SHALL ensure that every replacement preserves or reduces factual specificity unless the added detail is explicitly present in the supplementary context provided to the prompt. The LLM_Tailor SHALL NOT inflate claims (e.g., turning "worked with ISO-aligned controls" into "led ISO certification") unless the supplementary context supports the stronger assertion.

---

### Requirement 3: On-Demand Model Lifecycle Management

**User Story:** As a user, I want the LLM loaded into VRAM only when the pipeline is about to run and unloaded after it completes, so that my GPU is available for other tasks between pipeline runs.

#### Acceptance Criteria

1. WHEN a pipeline run is scheduled to begin, THE Model_Lifecycle_Manager SHALL send a pre-warm request to Ollama_API to load the Local_LLM into memory at least 30 seconds before the pipeline scoring stage starts.
2. WHEN all scoring and tailoring work for a pipeline run completes, THE Model_Lifecycle_Manager SHALL instruct Ollama to unload the Local_LLM from memory by setting the Keep_Alive_Timeout to zero on the final request.
3. WHEN the pre-warm request completes successfully, THE Model_Lifecycle_Manager SHALL verify the model is loaded by sending a health-check inference request that must return a parseable response within 10 seconds; IF the health-check does not receive a valid response within 10 seconds, THEN THE Model_Lifecycle_Manager SHALL retry the health-check once and, if it fails again, treat the model as failed to load.
4. IF the model fails to load within 120 seconds of the pre-warm request, THEN THE Model_Lifecycle_Manager SHALL log an error and the pipeline SHALL fall back to Claude for that run.
5. THE Model_Lifecycle_Manager SHALL expose the current model load state (unloaded, loading, loaded, error) via an API endpoint queryable by the frontend.
6. WHILE the pipeline is not running and no inference requests are pending, THE Local_LLM SHALL NOT occupy GPU VRAM or system RAM allocated by Ollama.
7. IF the unload request to Ollama fails or does not receive a success response within 30 seconds, THEN THE Model_Lifecycle_Manager SHALL retry the unload request once and wait for the retry result; IF the retry also fails, THEN THE Model_Lifecycle_Manager SHALL log an error and report the model load state as "error" via the status endpoint.

---

### Requirement 4: Shadow Mode Operation

**User Story:** As a user, I want to run both Claude and the local LLM side-by-side for at least a week, so that I can compare quality before committing to the local model.

#### Acceptance Criteria

1. WHILE Operating_Mode is set to `shadow`, THE Pipeline SHALL invoke the LLM_Scorer first and the Claude_Scorer second on every job that passes pre-filtering, and store both outputs in an LLM_Comparison record.
2. WHILE Operating_Mode is set to `shadow`, THE Pipeline SHALL use only the Claude_Scorer output for all pipeline decisions (status transitions, skip/approve thresholds, notification triggers).
3. WHILE Operating_Mode is set to `shadow`, THE Pipeline SHALL invoke both the LLM_Tailor and the Claude_Tailor for every job approved for tailoring, and store both outputs in an LLM_Comparison record without applying the local tailoring to the resume document. IF the Claude_Tailor fails and the LLM_Tailor succeeds during shadow mode, THE Pipeline SHALL still block the local tailoring output from being applied to the resume document.
4. IF the LLM_Scorer or LLM_Tailor raises an exception or times out during shadow mode, THEN THE Pipeline SHALL log the error, store a null local output in the LLM_Comparison record, and continue with Claude output without interruption.
5. IF the Claude_Scorer or Claude_Tailor raises an exception or times out during shadow mode, THEN THE Pipeline SHALL log the error, store the local output in the LLM_Comparison record with a null Claude output, and mark the job for retry on the next pipeline run following existing retry logic.
6. WHILE Operating_Mode is set to `shadow`, THE Pipeline SHALL log the latency of both Claude and Local_LLM calls for each job in structured log output including: job_id, operation_type (scoring or tailoring), model_name, latency_ms, and timestamp.
7. THE shadow mode comparison period SHALL require a minimum of 7 calendar days elapsed since the first LLM_Comparison record was created, with at least 50 scoring comparison records and at least 20 tailoring comparison records, before the Dashboard presents a mode-switch recommendation. Ideally 100+ scoring comparisons should be accumulated before local-primary is recommended (shown as a soft recommendation on the Dashboard).

---

### Requirement 5: Confidence-Based Escalation

**User Story:** As a user, I want uncertain local model predictions escalated to Claude, so that borderline jobs get reliable scoring without sending every job to the API.

#### Acceptance Criteria

1. WHILE Operating_Mode is set to `local-primary`, THE Pipeline SHALL escalate a job to the Claude_Scorer for re-scoring WHEN ANY of the following Escalation_Signals are true: (a) the LLM_Scorer produces a Confidence_Score below the configured Escalation_Threshold, (b) the local fit_score is within ±5 points of the configured good_fit_threshold or stretch_threshold (threshold proximity), (c) the JSON_Repair_Layer was required or a parsing retry was triggered for that job, (d) the job description word count is below a configurable minimum (default: 50 words), (e) multiple must-have skill gaps were detected in the scoring rationale, (f) the role title contains noisy terms (configurable list, default: engineer, analyst, architect, principal, director), or (g) deal_breaker_found is true AND the Confidence_Score is below 80. THE Pipeline SHALL use Claude's output for pipeline decisions on escalated jobs.
2. WHILE Operating_Mode is set to `local-primary`, WHEN none of the Escalation_Signals defined in criterion 1 are true for a job, THE Pipeline SHALL use the local fit_score for pipeline decisions without calling Claude.
3. THE Escalation_Threshold SHALL be configurable via the Model Configuration UI with a default value of 60, accepting integer values from 0 to 100 inclusive, where 0 means never escalate on confidence alone and 100 means always escalate on confidence.
4. WHEN a job is escalated to Claude, THE Pipeline SHALL store both the local and Claude scores in an LLM_Comparison record with an `escalated` flag set to true and an `escalation_reasons` array listing which Escalation_Signals triggered the escalation.
5. WHILE Operating_Mode is set to `local-primary`, THE LLM_Tailor SHALL handle all tailoring without Claude fallback, unless the LLM_Tailor produces unparseable output after JSON repair and one retry (as defined in Requirement 2 criterion 3), in which case THE Pipeline SHALL escalate that job's tailoring to the Claude_Tailor.
6. IF the Claude_Scorer is unreachable or returns an error during an escalation attempt, THEN THE Pipeline SHALL log the error, retain the local LLM fit_score for pipeline decisions for that job, and flag the job in the LLM_Comparison record with an `escalation_failed` indicator.
7. THE configurable minimum job description word count for the short-description Escalation_Signal SHALL default to 50 words and be adjustable via the Model Configuration UI (integer, range 20–200).
8. THE configurable noisy role title terms list SHALL be stored in system configuration and editable via the Model Configuration UI, with defaults: engineer, analyst, architect, principal, director.

---

### Requirement 6: Quality Comparison Dashboard

**User Story:** As a user, I want to see side-by-side comparisons of scoring and tailoring output from both models, so that I can evaluate when the local model is ready to take over.

#### Acceptance Criteria

1. THE Quality Comparison Dashboard SHALL extend the existing "Scoring Trial" tab to include an "LLM Comparison" section that displays both scoring and tailoring comparisons.
2. THE Dashboard SHALL display a paginated table of LLM_Comparison records for scoring showing: job title, company, local_fit_score, claude_fit_score, score_difference, local_confidence, escalated flag, escalation_reasons, and comparison timestamp, sorted by timestamp descending, with 25 records per page.
3. THE Dashboard SHALL display aggregate scoring metrics including: total jobs compared, mean absolute error between local and Claude fit_scores, percentage of jobs where both models agree on skip/approve (using the pipeline's configured good_fit_threshold), False_Skip_Rate (local said skip, Claude said approve), false-approve rate (local said approve, Claude said skip), threshold-adjacent disagreement count, deal-breaker agreement rate, human override rate (when user overrides local decisions), and escalation rate, calculated over all available comparison data with a date-range filter defaulting to the last 7 days.
4. THE Dashboard SHALL display a tailoring comparison view showing the local and Claude tailoring outputs side-by-side for a selected job, with a word-level text diff that visually distinguishes additions and removals.
5. WHEN fewer than 50 LLM_Comparison scoring records exist, THE Dashboard SHALL display a message indicating that more data is needed before metrics are meaningful, along with a progress indicator showing current count vs. the 50-record minimum; THE progress indicator SHALL only appear when the insufficient data message is displayed.
6. THE Dashboard SHALL display a mode-switch recommendation WHEN all of the following are met: (a) at least 7 calendar days have elapsed since the first shadow-mode LLM_Comparison record, (b) at least 50 scoring comparisons exist, (c) at least 20 tailoring comparisons exist, (d) the mean absolute error across all scoring comparisons is below 10 points, AND (e) the False_Skip_Rate is below 5%. IF 100+ scoring comparisons exist, THE Dashboard SHALL show a stronger "recommended" indicator; IF between 50–99, THE Dashboard SHALL show a "sufficient data" indicator with a note that more comparisons improve confidence.
7. THE Dashboard SHALL visually highlight the False_Skip_Rate as the primary safety metric, displayed prominently above other metrics with color coding (orange at 0–1% indicating potentially insufficient skipping, green at 1–3%, yellow at 3–5%, red above 5%).

---

### Requirement 7: Model Configuration UI

**User Story:** As a user, I want to configure the local model parameters from the dashboard, so that I can tune performance without editing config files.

#### Acceptance Criteria

1. THE Model Configuration UI SHALL provide a dropdown to select the Ollama model name (populated from the list of models available in Ollama), with the current active model indicated; THE dropdown SHALL synchronize with Ollama's reported active model on each page load so that the displayed selection matches the actual loaded model.
2. IF the Ollama model list cannot be retrieved (Ollama unreachable or returns error), THEN THE Model Configuration UI SHALL display the last-known model name as the current selection and show an inline error indicating the model list is unavailable; THE requirement is satisfied only when both the dropdown is available AND the displayed model is synchronized with Ollama's actual state.
3. THE Model Configuration UI SHALL provide a numeric input for the number of GPU layers to offload (integer, range 0–99, default: 99 representing maximum available), which is passed to Ollama on model load.
4. THE Model Configuration UI SHALL provide a selector for the Keep_Alive_Timeout value with options: "0s" (immediate unload), "5m", "15m", "30m", and "until next run" (default: "0s").
5. THE Model Configuration UI SHALL display the current Operating_Mode as a three-way toggle (claude-only, shadow, local-primary) with confirmation required before switching away from claude-only.
6. THE Model Configuration UI SHALL provide a numeric input for the Escalation_Threshold (integer, range 0–100, default: 60), visible only when Operating_Mode is `local-primary`.
7. WHEN any configuration value is changed, THE Model Configuration UI SHALL persist the change via API within 5 seconds and display a success confirmation visible for at least 3 seconds.
8. IF a configuration change fails to persist (API error or timeout), THEN THE Model Configuration UI SHALL revert the UI control to the previous value and display an error message indicating the change was not saved.

---

### Requirement 8: Ollama Health Check and Auto-Recovery

**User Story:** As a user, I want the system to gracefully handle Ollama failures, so that my job applications continue processing even if the local model is unavailable.

#### Acceptance Criteria

1. WHEN the Pipeline attempts to use the Local_LLM, THE Automator SHALL first verify that Ollama is reachable by querying the Ollama_API health endpoint within a 5-second timeout.
2. IF Ollama is unreachable or returns an error status, THEN THE Automator SHALL log an error, record the failure timestamp, and fall back to Claude for all scoring and tailoring for that pipeline run.
3. IF the Local_LLM fails to respond to an inference request within the configured timeout (90s scoring, 120s tailoring), THEN THE Automator SHALL terminate the request and fall back to Claude for that specific job.
4. WHEN the Automator starts a new pipeline run after a previous Ollama failure, THE Automator SHALL re-check Ollama reachability using the standard health check (criterion 1) and automatically resume using the Local_LLM if reachable, without requiring manual intervention.
5. THE Automator SHALL expose Ollama health status (reachable, model_loaded, last_error, last_success_at) via an API endpoint for the dashboard.
6. IF three consecutive pipeline runs fail to reach Ollama, THEN THE Automator SHALL send a notification to the user via the existing notification system indicating persistent Ollama connectivity issues and including the timestamp of the first failure.

---

### Requirement 9: Prompt Versioning

**User Story:** As a user, I want scoring and tailoring prompts stored as versioned configs, so that I can iterate on prompts and compare results across versions.

#### Acceptance Criteria

1. THE Automator SHALL store each Prompt_Config with the following fields: name (string identifier, max 100 characters, e.g. "scoring_v1"), prompt_type ("scoring" or "tailoring"), template_text (the full prompt template with placeholders, max 50,000 characters), version (integer auto-incremented per name), created_at (ISO 8601 timestamp), is_active (boolean, only one active per prompt_type), and generation parameters: temperature (float), top_p (float), repeat_penalty (float), max_tokens (integer), seed (integer, optional, for reproducibility), and model_version_hash (string, optional).
2. WHEN a new prompt version is created, THE Automator SHALL deactivate the previously active prompt of the same type and activate the new version; IF the deactivation of the previous prompt fails, THEN THE Automator SHALL roll back the new activation to maintain the "only one active per type" constraint, keeping the original prompt active.
3. THE LLM_Scorer and LLM_Tailor SHALL load the active Prompt_Config for their respective prompt_type at the start of each pipeline run and use that template for all inferences during the run, passing the stored generation parameters (temperature, top_p, repeat_penalty, max_tokens, seed) to the Ollama_API on each inference call.
4. THE Automator SHALL expose CRUD endpoints for Prompt_Config records under `/llm-pipeline/prompts`, requiring bearer token authentication.
5. IF a Prompt_Config is created or updated with an empty template_text, a template_text exceeding 50,000 characters, or a prompt_type other than "scoring" or "tailoring", THEN THE Automator SHALL reject the request with a validation error.
6. WHEN an LLM_Comparison record is created, THE Automator SHALL store the prompt version identifier and the generation parameters used for that inference, enabling filtering comparisons by prompt version and parameter set.
7. THE Prompt_Config template_text SHALL support placeholder variables for: `{job_description}`, `{resume_content}`, `{supplementary_context}`, `{goals_profile}`, and `{deal_breakers}`, which are substituted at inference time.
8. IF a placeholder variable referenced in template_text has no value available at inference time, THEN THE LLM_Scorer or LLM_Tailor SHALL substitute an empty string for that placeholder and log a warning identifying the missing variable.

---

### Requirement 10: Cost and Time Tracking

**User Story:** As a user, I want to see how much money and time each model costs per job, so that I can quantify the savings from switching to local inference.

#### Acceptance Criteria

1. THE Automator SHALL log for each scored or tailored job: the model used (claude or local), the operation type (scoring or tailoring), the wall-clock latency in milliseconds, and the estimated Claude cost based on input and output token counts multiplied by configurable per-token rates stored in the system configuration.
2. THE Automator SHALL store per-job cost/time data in the LLM_Comparison record with fields: local_latency_ms, claude_latency_ms (nullable if not run), estimated_claude_cost_usd, and actual_cost_usd (0.0 for local, actual cost for Claude).
3. THE Dashboard SHALL display cumulative cost savings (sum of estimated_claude_cost_usd for jobs processed locally) and average latency comparison between models, with a date range filter defaulting to the last 30 days.
4. THE Dashboard SHALL display a daily cost chart showing: estimated Claude cost (what it would have cost), actual cost (what was actually spent on Claude calls), and the savings difference; all displayed cost values (estimated, actual, savings) SHALL be non-negative.
5. WHEN Operating_Mode is `local-primary`, THE cost tracker SHALL calculate estimated savings by multiplying the local-processed job count by the average Claude cost per operation observed during shadow mode.
6. IF no shadow mode cost data exists when calculating estimated savings in local-primary mode, THEN THE cost tracker SHALL use the configurable per-token rates and an average token count of 2000 input / 500 output tokens as the estimate basis, and display a note indicating the estimate is approximate. WHENEVER Operating_Mode is `local-primary` and no shadow mode cost data is available, THE cost tracker SHALL use these fallback token estimates and display the approximation note regardless of whether a savings calculation was actively requested.

---

### Requirement 11: Operating Mode Switch

**User Story:** As a user, I want three clear operating modes with safe transitions, so that I can gradually shift from Claude to local inference with rollback capability.

#### Acceptance Criteria

1. THE Automator SHALL support three Operating_Modes stored in the config table: `claude-only` (default — existing behavior, no local LLM involvement), `shadow` (both run, Claude drives), and `local-primary` (local drives, Claude fallback for escalations).
2. WHEN Operating_Mode is switched from `claude-only` to `shadow`, THE Automator SHALL verify Ollama connectivity and model availability before activating, and return an error if Ollama is unreachable.
3. WHEN Operating_Mode is switched from `shadow` to `local-primary`, THE Automator SHALL verify that at least 7 calendar days have elapsed since the first LLM_Comparison record, that at least 50 scoring comparisons and 20 tailoring comparisons exist, that the mean absolute scoring error across all shadow comparisons is below 15 points, and that the False_Skip_Rate is below 5%, and warn the user (without blocking the switch) if any threshold is not met.
4. WHEN Operating_Mode is switched from `local-primary` or `shadow` back to `claude-only`, THE Automator SHALL stop issuing new local LLM invocations immediately and unload the model from memory after any in-progress pipeline run completes.
5. THE Operating_Mode switch SHALL take effect on the next pipeline run — an in-progress run SHALL complete using the mode that was active when it started. WHILE no mode switch is explicitly requested, THE Automator SHALL enforce that the operating mode for the next pipeline run matches the current configured mode.
6. THE Automator SHALL expose the current Operating_Mode and available transitions via a GET endpoint at `/llm-pipeline/mode`.
