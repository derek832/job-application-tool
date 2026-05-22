# Requirements Document

## Introduction

This spec defines the success criteria and iterative workflow for agent-driven validation of the visual form filler (`fill_form_visually()` and `identify_fields_visual()`) on the `feat/visual-form-filling` branch. There is no test harness to build — Kiro (the AI agent) IS the validation runner. When the user clicks "Run All Tasks," Kiro autonomously finds real job URLs on each target ATS platform, invokes the visual filler via the test-apply endpoint or direct Docker exec, observes results from Docker logs and the FillResult response, diagnoses failures, patches code, rebuilds containers, and re-runs until all platforms pass. No human intervention is required after the initial trigger.

## Glossary

- **Kiro_Agent**: The AI agent executing spec tasks — it finds URLs, triggers dry-runs, reads logs, diagnoses failures, patches code, rebuilds containers, and re-verifies
- **Visual_Form_Filler**: The screenshot-based form filling system (`visual_form_filler.py`) that uses Claude Vision to identify fields by pixel coordinates and fills them via mouse/keyboard actions
- **Target_Platform**: One of the five ATS platforms under validation: Greenhouse, Lever, Workday, iCIMS, BambooHR
- **Target_URL**: A real, active job posting URL on a specific Target_Platform used as a validation target
- **Dry_Run**: A mode where the visual filler fills all form fields but does not click Submit (`dry_run=True`)
- **Test_Apply_Endpoint**: The API endpoint `POST /jobs/{id}/test-apply?dry_run=true` that triggers a dry-run application against a specified job URL
- **Direct_Invocation**: Running the visual filler directly via `docker compose exec automator python -c "..."` to call `fill_form_visually()` without going through the API
- **Fill_Result**: The structured result dataclass from `fill_form_visually()` containing ok, fields_filled, fields_found, pages_completed, error, and reason
- **Docker_Logs**: Structured log output from the automator container, observable via `docker compose logs automator`; includes events `visual_fields_identified`, `visual_field_filled`, `visual_clicking_submit`
- **Fix_Cycle**: One iteration of the run → diagnose → patch → rebuild → re-run loop
- **Pass_Criteria**: A dry-run is considered passing when Fill_Result.ok is True, fields_filled >= 3, and no escalation reason is present
- **Platform_Pass**: A Target_Platform is considered validated when at least one Target_URL on that platform meets Pass_Criteria
- **Visual_Fallback_Trigger**: The visual filler is invoked when DOM extraction fails or achieves less than 40% fill rate on a form

## Requirements

### Requirement 1: Target URL Discovery

**User Story:** As a user, I want Kiro to autonomously find real job posting URLs on each Target_Platform, so that validation runs against actual ATS forms without manual URL curation.

#### Acceptance Criteria

1. WHEN the Kiro_Agent begins validation for a Target_Platform, THE Kiro_Agent SHALL locate at least one real, active Target_URL on that platform by using web search to find external apply jobs filtered by the platform's domain or by navigating directly to the platform's public job board (e.g., boards.greenhouse.io, jobs.lever.co, myworkdayjobs.com, icims.com, bamboohr.com)
2. WHEN the Kiro_Agent selects a Target_URL, THE Kiro_Agent SHALL verify the URL is active by loading the page (via curl or browser navigation) within 15 seconds and confirming the response does not contain a 404 status, a 410 status, or text matching "position closed", "job closed", "no longer accepting applications", or "this position has been filled"
3. THE Kiro_Agent SHALL prefer Target_URLs with simple application forms (at least 1 page but fewer than 4 pages, no CAPTCHA, and fields limited to text inputs, dropdowns, radio buttons, checkboxes, and file uploads) for initial validation, escalating to complex forms only after simple forms pass
4. IF a Target_URL becomes stale during validation (job posting closed between runs), THEN THE Kiro_Agent SHALL find a replacement Target_URL for the same platform, attempting up to 3 replacements; IF no active replacement is found after 3 attempts, THEN THE Kiro_Agent SHALL document the platform as temporarily unavailable and continue validation for remaining platforms
5. THE Kiro_Agent SHALL document each Target_URL used, its associated Target_Platform, and the timestamp of verification in the task execution log so results are reproducible

### Requirement 2: Dry-Run Execution

**User Story:** As a user, I want Kiro to run the visual form filler in dry_run mode against each Target_URL, so that forms are filled without submitting real applications.

#### Acceptance Criteria

1. WHEN the Kiro_Agent executes a dry-run against a Target_URL, THE Kiro_Agent SHALL invoke the Test_Apply_Endpoint via `curl -X POST http://localhost:8000/jobs/{id}/test-apply?dry_run=true` or use Direct_Invocation via `docker compose exec automator python -c "..."` to trigger the Visual_Form_Filler, and the Visual_Form_Filler SHALL begin execution within 30 seconds of invocation
2. WHILE the Visual_Form_Filler is executing in dry_run mode, THE Visual_Form_Filler SHALL fill all identified form fields but SHALL NOT click any button whose visible text or aria-label matches "submit", "apply", "send application", or "complete application" (case-insensitive)
3. WHEN a dry-run completes, THE Kiro_Agent SHALL read the Fill_Result from the API response or stdout, capturing fields_filled count, fields_found count, pages_completed, and any error category (timeout, CAPTCHA, navigation_failure, or field_identification_failure) with a descriptive reason string
4. WHEN a dry-run completes, THE Kiro_Agent SHALL read Docker_Logs via `docker compose logs automator --tail=200` and confirm the presence of structured entries for `visual_fields_identified` and `visual_field_filled` events, each including the field label or selector used and the page number on which the field was processed
5. IF the Visual_Form_Filler encounters a CAPTCHA during a dry-run, THEN THE Kiro_Agent SHALL mark that Target_URL as unsuitable and find a different Target_URL for the same platform, up to a maximum of 3 replacement attempts per platform
6. IF the Visual_Form_Filler fails to load the Target_URL page within 30 seconds or encounters a navigation error during a dry-run, THEN THE Kiro_Agent SHALL record the Fill_Result with an error category of "navigation_failure" and the Docker_Logs SHALL contain a structured entry with the failed URL and error details

### Requirement 3: Result Observation and Pass Criteria

**User Story:** As a user, I want Kiro to determine pass/fail for each platform based on concrete metrics from Fill_Result and Docker logs, so that validation results are objective and reproducible.

#### Acceptance Criteria

1. WHEN a dry-run completes, THE Kiro_Agent SHALL evaluate the Fill_Result against Pass_Criteria: ok is True, fields_filled is 3 or greater, and reason is not "captcha_detected" or "vision_api_error"
2. WHEN a dry-run meets Pass_Criteria, THE Kiro_Agent SHALL record the Target_Platform as validated with the Target_URL, fields_filled count, and pages_completed count (where pages_completed is the number of form pages on which at least one field was filled)
3. WHEN a dry-run does not meet Pass_Criteria, THE Kiro_Agent SHALL classify the failure into one of these categories based on Docker_Logs content: no_fields_detected, vision_api_error, captcha_detected, no_submit_button, low_fill_count, or platform_specific_error, and SHALL record the category in the task execution log
4. THE Kiro_Agent SHALL read Docker_Logs via `docker compose logs automator --tail=200` after each dry-run and identify which log entries correspond to the current run by matching the Target_URL or platform domain in the log output
5. IF the Fill_Result reports ok as True but fields_filled is fewer than 3, THEN THE Kiro_Agent SHALL treat this as a failure with category low_fill_count and SHALL re-run with verbose logging enabled to identify which expected fields were not detected or not filled

### Requirement 4: Failure Diagnosis

**User Story:** As a user, I want Kiro to autonomously diagnose why a dry-run failed by reading source code and logs, so that targeted fixes can be applied without human analysis.

#### Acceptance Criteria

1. WHEN a dry-run fails with category "no_fields_detected", THE Kiro_Agent SHALL inspect the Docker_Logs for Claude Vision API response details, read the `visual_form_filler.py` source to trace the `identify_fields_visual()` code path, examine navigation logs for page load errors (HTTP 4xx/5xx, timeout, or blank page indicators), and record the diagnosed cause in the task execution log
2. WHEN a dry-run fails with category "no_submit_button", THE Kiro_Agent SHALL read the relevant source code to check whether fields were filled successfully (fields_filled > 0) and whether the form uses multi-step navigation (multiple pages or SPA-style step transitions), and record the diagnosed cause in the task execution log
3. WHEN a dry-run fails with an error traceback referencing `visual_form_filler.py`, `vision_agent.py`, or `claude_client.py`, THE Kiro_Agent SHALL read the referenced source file, identify the function and line number that produced the error, and document the correlation between the error message and the code path in the task execution log
4. WHEN diagnosing a failure, THE Kiro_Agent SHALL examine any debug screenshots captured during the run (files matching `data/debug_*.png`) and document observable page state findings (e.g., page not loaded, form not visible, error banner present, unexpected redirect) in the task execution log
5. IF the Kiro_Agent cannot determine a root cause after examining Docker_Logs, source code, and debug screenshots, THEN THE Kiro_Agent SHALL add temporary verbose logging to the relevant code path in `visual_form_filler.py` and re-run the failing dry-run a maximum of 2 additional times to gather diagnostic data before documenting the issue as undiagnosed

### Requirement 5: Autonomous Code Patching

**User Story:** As a user, I want Kiro to fix code issues it discovers during validation, so that the visual form filler improves iteratively without manual intervention.

#### Acceptance Criteria

1. WHEN the Kiro_Agent diagnoses a root cause, THE Kiro_Agent SHALL apply a patch to the relevant source file (typically `visual_form_filler.py`, `vision_agent.py`, or `claude_client.py`) that modifies only the function or code block identified in the diagnosis, without altering lines unrelated to the diagnosed issue
2. WHEN a patch is applied, THE Kiro_Agent SHALL rebuild the affected Docker container via `docker compose build automator` and restart it via `docker compose up -d automator`, then re-run the same dry-run against the same Target_URL to verify the patch resolved the failure
3. IF a patch does not resolve the failure after 2 attempts at the same root cause, THEN THE Kiro_Agent SHALL discard the failed patches, re-diagnose from scratch using a different diagnostic approach (e.g., adding verbose logging, inspecting page state, or comparing against known-good behavior), and record each failed attempt with the root cause hypothesis and patch description
4. WHEN a patch is verified as successful (re-run meets Pass_Criteria), THE Kiro_Agent SHALL proceed to the next failing platform before performing any code cleanup
5. THE Kiro_Agent SHALL limit total Fix_Cycles to 5 per Target_Platform to prevent infinite loops on intractable issues
6. IF a Target_Platform exhausts all 5 Fix_Cycles without achieving Platform_Pass, THEN THE Kiro_Agent SHALL document the platform as failing with the last diagnosed root cause, the list of patches attempted, and the final Fill_Result observed

### Requirement 6: Iterative Validation Loop

**User Story:** As a user, I want Kiro to keep running until all five platforms pass or a maximum retry limit is reached, so that I can trigger it once and return to fully validated code.

#### Acceptance Criteria

1. THE Kiro_Agent SHALL iterate through all five Target_Platforms (Greenhouse, Lever, Workday, iCIMS, BambooHR) in a fixed order and attempt validation on each
2. WHEN a Target_Platform achieves Platform_Pass, THE Kiro_Agent SHALL move to the next unvalidated platform without re-testing the passing one unless a code patch has modified shared code paths in `visual_form_filler.py` or `vision_agent.py`
3. WHEN all five Target_Platforms achieve Platform_Pass, THE Kiro_Agent SHALL report overall validation success with a summary listing: each platform name, the Target_URL used, the fields_filled count, and the number of Fix_Cycles consumed (0 if none)
4. IF a Target_Platform cannot achieve Platform_Pass after exhausting Fix_Cycles (5 attempts) and alternative Target_URLs (3 URLs per platform), THEN THE Kiro_Agent SHALL document the platform as failing with the last observed Fill_Result and continue to the next platform
5. WHEN the validation loop completes (all platforms pass or all retries exhausted), THE Kiro_Agent SHALL produce a final summary report listing each platform's status (pass or fail), the Target_URLs tested, fields_filled counts per platform, Fix_Cycles consumed per platform, and any outstanding issues for failing platforms

### Requirement 7: Environment Prerequisites

**User Story:** As a user, I want Kiro to verify the runtime environment is ready before starting validation, so that failures due to infrastructure issues are caught early.

#### Acceptance Criteria

1. WHEN the Kiro_Agent starts validation, THE Kiro_Agent SHALL verify Docker containers are running by executing `docker compose ps` and confirming the automator service reports a "healthy" status
2. WHEN the Kiro_Agent starts validation, THE Kiro_Agent SHALL verify Chrome is accessible via CDP by executing `curl http://localhost:9222/json/version` (or the configured CDP endpoint) and receiving a valid JSON response within 10 seconds
3. WHEN the Kiro_Agent starts validation, THE Kiro_Agent SHALL verify the `feat/visual-form-filling` branch code is deployed by checking that `visual_form_filler.py` exists in the automator container via `docker compose exec automator ls src/pipeline/visual_form_filler.py`
4. WHEN the Kiro_Agent starts validation, THE Kiro_Agent SHALL verify a user profile exists in the database containing all of the following non-empty fields: name, email, phone, and a resume file path that resolves to an existing file
5. IF any prerequisite check fails, THEN THE Kiro_Agent SHALL report which specific prerequisite failed (Docker health, CDP connectivity, branch deployment, or user profile completeness), include the observed state (e.g., container status, missing file, or missing field name), and halt without proceeding to platform validation

### Requirement 8: Code Cleanup After Validation

**User Story:** As a user, I want the codebase to remain clean after the validation and patching process, so that patches don't introduce technical debt.

#### Acceptance Criteria

1. WHEN all platforms have been validated (pass or documented failure), THE Kiro_Agent SHALL run `ruff check --fix` and `ruff format` on all modified Python files in the automator source
2. WHEN the Kiro_Agent performs cleanup, THE Kiro_Agent SHALL remove any logging statements that were added during Fix_Cycles and contain diagnostic markers (e.g., "DEBUG_VISUAL", "VERBOSE", or "DIAG" prefixes) that distinguish them from permanent application logging
3. WHEN the Kiro_Agent performs cleanup, THE Kiro_Agent SHALL move inline imports to top-level module imports in all modified files
4. AFTER cleanup is complete, THE Kiro_Agent SHALL rebuild the container and re-run dry-runs on all passing platforms to confirm cleanup did not introduce regressions, where a regression is defined as a platform that previously achieved Platform_Pass now failing its dry-run
5. IF a regression is detected after cleanup, THEN THE Kiro_Agent SHALL revert only the specific cleanup change that caused the regression (identified by reverting changes one file at a time until the regression disappears) and retain the remaining cleanup changes
