# Implementation Plan: Visual Apply Validation

## Overview

This plan implements the pure-logic components that support the agent-driven validation workflow. Since Kiro IS the validation runner (no test harness to build), the implementation focuses on the reusable utility functions and evaluation logic that the agent invokes during validation: URL classification, pass criteria evaluation, failure classification, log filtering, retry/limit state management, report generation, and diagnostic marker cleanup. These are the building blocks the agent uses in its closed-loop validation cycle.

## Tasks

- [x] 1. Implement core validation utilities and data models
  - [x] 1.1 Create validation data models and state tracking
    - Create `automator/src/pipeline/validation_models.py`
    - Implement `PlatformValidationState` and `ValidationSession` dataclasses as defined in the design
    - Implement `FillResult` dataclass if not already present (check existing code first)
    - Implement `PlatformReport` and `ValidationReport` dataclasses
    - Implement `meets_pass_criteria(result: FillResult) -> bool` function
    - _Requirements: 3.1, 3.5, 6.3, 6.5_

  - [x] 1.2 Write property test for pass criteria evaluation
    - **Property 4: Pass Criteria Evaluation**
    - Generate random FillResult with arbitrary `ok`, `fields_filled`, and `reason` values
    - Assert function returns True iff `ok is True AND fields_filled >= 3 AND reason not in ("captcha_detected", "vision_api_error")`
    - Use Hypothesis with `st.booleans()`, `st.integers(min_value=0)`, `st.sampled_from(reasons + [None])`
    - Minimum 100 iterations
    - **Validates: Requirements 3.1, 3.5**

  - [x] 1.3 Implement URL active/closed classifier
    - Create `automator/src/pipeline/url_validator.py`
    - Implement `classify_url_status(status_code: int, body_text: str) -> str` returning "active" or "inactive"
    - Return "inactive" if status is 404 or 410, OR body contains (case-insensitive): "position closed", "job closed", "no longer accepting applications", "this position has been filled"
    - Return "active" for status 200 with no closed-job indicators
    - _Requirements: 1.2_

  - [x] 1.4 Write property test for URL classification
    - **Property 1: URL Active/Closed Classification**
    - Generate random (status_code, body_text) pairs using `st.integers()` and `st.text()` with optional closed-job phrases injected
    - Assert classifier returns "inactive" iff status is 404/410 OR body contains any closed-job phrase (case-insensitive)
    - Minimum 100 iterations
    - **Validates: Requirements 1.2**

- [x] 2. Implement failure classification and log filtering
  - [x] 2.1 Implement failure classifier
    - Create `automator/src/pipeline/failure_classifier.py`
    - Implement `classify_failure(fill_result: FillResult, docker_logs: str) -> str` returning exactly one category from: `no_fields_detected`, `vision_api_error`, `captcha_detected`, `no_submit_button`, `low_fill_count`, `platform_specific_error`
    - Classification logic per design: check fields_found==0 for no_fields_detected, reason contains "vision" for vision_api_error, reason=="captcha_detected" for captcha, fields_filled>0 but not ok for no_submit_button, ok but fields_filled<3 for low_fill_count, else platform_specific_error
    - _Requirements: 3.3_

  - [x] 2.2 Write property test for failure classification completeness
    - **Property 5: Failure Classification Completeness**
    - Generate FillResult + log content combinations that do NOT meet pass criteria
    - Assert classifier always returns exactly one category from the defined set
    - Never returns None, never returns multiple categories
    - Minimum 100 iterations
    - **Validates: Requirements 3.3**

  - [x] 2.3 Implement Docker log filter by URL
    - Add `filter_logs_by_url(log_lines: list[str], target_url: str) -> list[str]` to `automator/src/pipeline/log_utils.py`
    - Extract domain component from target_url
    - Return only lines containing the full target_url OR its domain component
    - _Requirements: 3.4_

  - [x] 2.4 Write property test for log entry filtering
    - **Property 6: Log Entry Filtering by URL**
    - Generate log lines with/without target URL or domain injected
    - Assert returned lines are exactly those containing the URL or domain
    - No false positives (lines without URL/domain never included), no false negatives (lines with URL/domain never excluded)
    - Minimum 100 iterations
    - **Validates: Requirements 3.4**

- [x] 3. Implement submit button matching and retry logic
  - [x] 3.1 Implement submit button pattern matcher
    - Create `automator/src/pipeline/submit_matcher.py`
    - Implement `is_submit_button(text: str) -> bool` returning True iff text matches (case-insensitive) one of: "submit", "apply", "send application", "complete application"
    - This is used in dry_run mode to identify buttons that must NOT be clicked
    - _Requirements: 2.2_

  - [x] 3.2 Write property test for submit button matching
    - **Property 3: Submit Button Pattern Matching**
    - Generate random button text strings using `st.text()` with optional submit-like substrings
    - Assert matcher returns True iff text case-insensitively equals one of the four patterns
    - Minimum 100 iterations
    - **Validates: Requirements 2.2**

  - [x] 3.3 Implement URL replacement bounded retry logic
    - Add retry tracking to `automator/src/pipeline/url_validator.py`
    - Implement `URLReplacementTracker` class with `attempt_replacement(platform: str) -> bool` that returns False after 3 attempts
    - Track attempts per platform; after 3 failed replacements, mark platform as "unavailable"
    - _Requirements: 1.4, 2.5_

  - [x] 3.4 Write property test for URL replacement bounded retry
    - **Property 2: URL Replacement Bounded Retry**
    - Generate sequences of stale/active URL results using `st.lists(st.booleans())`
    - Assert at most 3 replacement attempts are made; after 3 failures, platform is marked "unavailable"
    - Minimum 100 iterations
    - **Validates: Requirements 1.4, 2.5**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement fix cycle management and patch retry logic
  - [x] 5.1 Implement fix cycle limit enforcement
    - Create `automator/src/pipeline/fix_cycle_manager.py`
    - Implement `FixCycleManager` class tracking cycles per platform (max 5)
    - `consume_cycle(platform: str) -> bool` returns True if cycle available, False if limit reached
    - `is_exhausted(platform: str) -> bool` returns True after 5 cycles
    - When exhausted, platform status set to "fail"
    - _Requirements: 5.5, 5.6_

  - [x] 5.2 Write property test for fix cycle limit enforcement
    - **Property 8: Fix Cycle Limit Enforcement**
    - Generate sequences of fix cycle attempts using `st.lists(st.booleans(), max_size=10)`
    - Assert total cycles consumed never exceeds 5 per platform
    - After 5 cycles, platform is marked "fail"
    - Minimum 100 iterations
    - **Validates: Requirements 5.5, 5.6**

  - [x] 5.3 Implement patch retry discard logic
    - Add to `FixCycleManager`: `PatchRetryTracker` tracking attempts per root cause
    - `record_patch_attempt(platform: str, root_cause: str, success: bool) -> str` returns "continue", "discard_and_rediagnose", or "resolved"
    - After 2 failed patches at same root cause, return "discard_and_rediagnose"
    - _Requirements: 5.3_

  - [x] 5.4 Write property test for patch retry discard
    - **Property 7: Patch Retry Discard After Two Failures**
    - Generate sequences of patch outcomes targeting the same root cause
    - Assert: after 2 failures at same root cause, system discards and triggers re-diagnosis
    - Never attempts a third patch at same root cause without re-diagnosing
    - Minimum 100 iterations
    - **Validates: Requirements 5.3**

- [x] 6. Implement shared code detection and report generation
  - [x] 6.1 Implement shared code modification detection
    - Add to `automator/src/pipeline/validation_models.py`
    - Implement `should_retest_passing_platforms(modified_files: list[str]) -> bool`
    - Return True if modified_files includes `visual_form_filler.py` or `vision_agent.py` (match by filename, not full path)
    - _Requirements: 6.2_

  - [x] 6.2 Write property test for shared code re-testing trigger
    - **Property 9: Shared Code Modification Triggers Re-Testing**
    - Generate platform states (some passing) and modified file lists using `st.lists(st.sampled_from(files))`
    - Assert: if modified files include shared paths, passing platforms are flagged for re-test; otherwise not
    - Minimum 100 iterations
    - **Validates: Requirements 6.2**

  - [x] 6.3 Implement validation report generator
    - Add `generate_report(session: ValidationSession) -> ValidationReport` to `validation_models.py`
    - Set `overall_pass` to True iff all 5 platforms have status "pass"
    - Include entry for every platform with status, target URL, fields_filled, fix_cycles consumed
    - Include outstanding issues for every platform with status "fail"
    - _Requirements: 6.3, 6.5_

  - [x] 6.4 Write property test for validation report correctness
    - **Property 10: Validation Report Correctness**
    - Generate ValidationSession with arbitrary platform states (pass, fail, unavailable)
    - Assert: overall_pass is True iff all 5 pass; every platform has an entry; failing platforms have outstanding issues
    - Minimum 100 iterations
    - **Validates: Requirements 6.3, 6.5**

- [x] 7. Implement diagnostic marker cleanup
  - [x] 7.1 Implement diagnostic marker removal function
    - Create `automator/src/pipeline/cleanup_utils.py`
    - Implement `remove_diagnostic_markers(source_lines: list[str]) -> list[str]`
    - Remove lines containing prefixes "DEBUG_VISUAL", "VERBOSE", or "DIAG" (as diagnostic markers)
    - Preserve all other lines unchanged including indentation and ordering
    - _Requirements: 8.2_

  - [x] 7.2 Write property test for diagnostic marker removal
    - **Property 11: Diagnostic Marker Removal**
    - Generate Python source lines with a mix of normal and diagnostic logging (markers: "DEBUG_VISUAL", "VERBOSE", "DIAG")
    - Assert: all marker lines removed, all non-marker lines preserved in original order and indentation
    - Minimum 100 iterations
    - **Validates: Requirements 8.2**

- [x] 8. Integration wiring and final verification
  - [x] 8.1 Wire all validation utilities into a cohesive module
    - Create `automator/src/pipeline/validation_engine.py` that imports and orchestrates all components
    - Implement `run_prerequisite_checks() -> tuple[bool, str]` that runs Docker, CDP, branch, and profile checks per Requirement 7
    - Implement `get_platform_order() -> list[str]` returning fixed order: ["greenhouse", "lever", "workday", "icims", "bamboohr"]
    - Implement `evaluate_dry_run(fill_result: FillResult, docker_logs: str, target_url: str) -> dict` combining pass criteria, failure classification, and log filtering
    - _Requirements: 6.1, 7.1, 7.2, 7.3, 7.4_

  - [x] 8.2 Write unit tests for validation engine integration
    - Test prerequisite check reports correct failure message for each check type
    - Test platform iteration order is Greenhouse → Lever → Workday → iCIMS → BambooHR
    - Test evaluate_dry_run correctly combines pass criteria, classification, and log filtering
    - Test full workflow state transitions: pending → pass, pending → fail after 5 cycles
    - _Requirements: 6.1, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis (minimum 100 iterations each)
- Unit tests validate specific examples and edge cases
- The agent workflow itself (finding URLs, running dry-runs, diagnosing, patching) is NOT implemented as code — Kiro executes those steps directly during task execution
- All Python code uses type annotations, async where appropriate, and follows ruff formatting standards per engineering steering

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "2.1", "2.3", "3.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "2.2", "2.4", "3.2", "3.3"] },
    { "id": 2, "tasks": ["3.4", "5.1", "5.3", "6.1", "6.3", "7.1"] },
    { "id": 3, "tasks": ["5.2", "5.4", "6.2", "6.4", "7.2"] },
    { "id": 4, "tasks": ["8.1"] },
    { "id": 5, "tasks": ["8.2"] }
  ]
}
```
