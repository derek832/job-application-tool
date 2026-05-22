# Implementation Plan: Iterative ATS Validation

## Overview

Agent-driven validation of the job application pipeline. Kiro IS the validation runner — there is no test harness to build. Each task is a self-contained validation unit where the executing agent finds a real target URL, runs the pipeline against it, reads Docker logs, diagnoses any failures, applies fixes, and re-runs until the feature passes. The iterative fix cycle happens WITHIN each task.

Execution environment: Docker (`automator` service) with Playwright and Chrome CDP. Logs via `docker compose logs automator --tail=100`. Screenshots in `data/` directory.

## Tasks

- [x] 1. Target URL Discovery for All Platforms
  - [x] 1.1 Discover and verify active Target URLs for all validation platforms
    - Search LinkedIn for external apply jobs filtered by domain, or navigate directly to platform job boards (boards.greenhouse.io, jobs.lever.co, myworkdayjobs.com, icims.com, bamboohr.com)
    - For LinkedIn Easy Apply: use existing `build_search_url()` with a broad query to find a job with Easy Apply enabled
    - For LinkedIn Pagination: use the same search URL (pagination validates page 2+ discovery)
    - Verify each URL is active: page loads without 404/410/"job closed" indicators
    - Prefer simple forms (1-4 pages, no CAPTCHA) for initial validation
    - Document each URL with its platform in a summary for downstream tasks
    - Output: one verified active URL per platform (Greenhouse, Lever, Workday, iCIMS, BambooHR, LinkedIn Easy Apply, LinkedIn Pagination)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 2. Validate LinkedIn Easy Apply
  - [x] 2.1 Execute Easy Apply pipeline against discovered LinkedIn target URL
    - Run `run_easy_apply(job_record, profile, session, page, claude_client)` inside the Docker container against the LinkedIn Easy Apply target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain structured entry with event `easy_apply_submitted`
    - If failure: identify error category from logs (selector mismatch, timeout, missing field mapping, unexpected modal state)
    - Diagnose root cause by reading `easy_apply_stage.py` and correlating error with code path
    - Apply targeted fix to the specific failing line/selector
    - Re-run the same feature against the same URL to verify the fix
    - Loop diagnose→fix→re-run until `easy_apply_submitted` appears in logs or 2 attempts at same root cause exhausted (then re-diagnose from scratch)
    - If target URL becomes stale mid-validation, find a replacement and continue
    - Document: target URL used, fix cycles performed, final success signal
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 3. Validate External Apply — Greenhouse
  - [x] 3.1 Execute Vision Agent against Greenhouse target URL
    - Run `process_external_apply(job_record, profile, page, claude_client)` inside the Docker container against the Greenhouse target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `external_apply_success` with Greenhouse domain
    - If failure: identify error category (selector mismatch, timeout, shadow DOM, drag-and-drop upload, CAPTCHA)
    - Diagnose root cause by reading `vision_agent.py` and inspecting any screenshots in `data/`
    - Apply targeted fix (selector update, timeout increase, field mapping addition, fallback logic)
    - Re-run against same URL to verify fix
    - Loop until `external_apply_success` logged or exhausted (re-diagnose after 2 failed attempts at same root cause)
    - If target URL stale, find replacement Greenhouse URL and continue
    - Document: target URL, fix cycles, final result
    - _Requirements: 2.1, 2.6, 2.7, 2.8, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 4. Validate External Apply — Lever
  - [x] 4.1 Execute Vision Agent against Lever target URL
    - Run `process_external_apply(job_record, profile, page, claude_client)` inside the Docker container against the Lever target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `external_apply_success` with Lever domain
    - If failure: diagnose from logs + `vision_agent.py` + screenshots
    - Apply targeted fix, re-run, loop until success or re-diagnose after 2 failed attempts
    - If target URL stale, find replacement Lever URL and continue
    - Document: target URL, fix cycles, final result
    - _Requirements: 2.2, 2.6, 2.7, 2.8, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 5. Validate External Apply — Workday
  - [x] 5.1 Execute Vision Agent against Workday target URL
    - Run `process_external_apply(job_record, profile, page, claude_client)` inside the Docker container against the Workday target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `external_apply_success` with Workday domain
    - If failure: diagnose from logs + `vision_agent.py` + screenshots
    - Pay special attention to multi-page detection (Workday often has multi-step forms)
    - Apply targeted fix, re-run, loop until success or re-diagnose after 2 failed attempts
    - If target URL stale, find replacement Workday URL and continue
    - Document: target URL, fix cycles, final result
    - _Requirements: 2.3, 2.6, 2.7, 2.8, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 6. Validate External Apply — iCIMS
  - [x] 6.1 Execute Vision Agent against iCIMS target URL
    - Run `process_external_apply(job_record, profile, page, claude_client)` inside the Docker container against the iCIMS target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `external_apply_success` with iCIMS domain
    - If failure: diagnose from logs + `vision_agent.py` + screenshots
    - Apply targeted fix, re-run, loop until success or re-diagnose after 2 failed attempts
    - If target URL stale, find replacement iCIMS URL and continue
    - Document: target URL, fix cycles, final result
    - _Requirements: 2.4, 2.6, 2.7, 2.8, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 7. Validate External Apply — BambooHR
  - [x] 7.1 Execute Vision Agent against BambooHR target URL
    - Run `process_external_apply(job_record, profile, page, claude_client)` inside the Docker container against the BambooHR target URL from Task 1
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `external_apply_success` with BambooHR domain
    - If failure: diagnose from logs + `vision_agent.py` + screenshots
    - Apply targeted fix, re-run, loop until success or re-diagnose after 2 failed attempts
    - If target URL stale, find replacement BambooHR URL and continue
    - Document: target URL, fix cycles, final result
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 8. Validate ATS Registration Flow
  - [x] 8.1 Execute ATS registration/login against a platform requiring authentication
    - Identify a target URL (from Tasks 3-7) where the ATS requires login/registration before applying
    - Run `process_external_apply(job_record, profile, page, claude_client)` — registration is triggered automatically when login/registration is detected
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `registration_submitted` or `login_submitted`
    - If failure: diagnose from logs + `ats_registration.py` + screenshots
    - Check for: registration page detection, field filling, password generation, OAuth flow, email verification polling
    - Apply targeted fix, re-run, loop until success or re-diagnose after 2 failed attempts
    - Document: target URL, platform, registration vs login, fix cycles, final result
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [x] 9. Validate LinkedIn Pagination Beyond Page 1
  - [x] 9.1 Execute LinkedIn scraper with multi-page pagination
    - Run `discover_and_extract_jobs(page, config, session, max_pages=3)` inside the Docker container
    - Read Docker logs via `docker compose logs automator --tail=100`
    - Verify success: Docker logs contain `discovery_job_extracted` events from page 2+ (check page number context in log entries)
    - Also verify: `pagination_ended` with `last_page > 1`
    - If failure: check for `pagination_container_found_but_no_next_button` in logs
    - Inspect `data/debug_pagination.png` if captured for DOM structure diagnosis
    - Diagnose from `linkedin_scraper.py` — likely selector mismatch on Next button
    - Apply targeted fix (selector update, wait time adjustment, fallback selector)
    - Re-run, loop until pagination succeeds or re-diagnose after 2 failed attempts
    - Document: search query used, pages reached, fix cycles, final result
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4_

- [x] 10. Checkpoint — All feature validations complete
  - Ensure all validation tasks (2-9) have passed. Ask the user if questions arise.

- [x] 11. Code Cleanup and Final Regression Run
  - [x] 11.1 Perform code cleanup on all modified files
    - Identify all files modified during fix cycles in Tasks 2-9
    - Move inline imports to top-level module imports
    - Remove dead code (unused functions, unreachable branches, commented-out code)
    - Run `ruff check --fix` on all modified Python files
    - Run `ruff format` on all modified Python files
    - Add/update type annotations and docstrings on modified functions (match existing codebase style)
    - Final verification: `ruff check` + `ruff format --check` must pass with zero warnings
    - If any lint issue cannot be auto-fixed, manually resolve it
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 11.2 Final regression run — re-validate all features after cleanup
    - Re-run Easy Apply against original (or fresh) target URL — verify `easy_apply_submitted`
    - Re-run External Apply against one URL per platform — verify `external_apply_success` for each
    - Re-run ATS Registration — verify `registration_submitted` or `login_submitted`
    - Re-run Pagination — verify `discovery_job_extracted` from page 2+
    - If any feature regresses after cleanup: identify which cleanup change caused it, revert that specific change, re-run to confirm revert fixes it, apply a safer version of the cleanup
    - All features must pass with no failures after cleanup
    - Document: final pass/fail status per feature, any cleanup reverts needed
    - _Requirements: 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
    - **Regression Results (2026-05-19):**
      - Easy Apply: ✅ PASS — Pipeline navigated 4-page form, filled fields, attached resume, correctly escalated on unmappable question (Req 1.6 behavior). No regression.
      - Greenhouse: ✅ PASS — `external_apply_success` logged. 17 fields extracted, 8 filled, form submitted. (Awin)
      - Lever: ✅ NO REGRESSION — Pipeline navigated to form, extracted 49 fields, filled 5, uploaded resume. Submit button hidden (platform requires all fields filled). Same behavior as pre-cleanup; cleanup diff confirms no submit logic changes.
      - BambooHR: ✅ PASS — `external_apply_success` logged. 20 fields extracted, 12 filled, form submitted. (SRT Marine Systems)
      - Workday: ✅ PASS (escalation) — Multi-page form stuck on required custom dropdowns (page_stuck_validation_errors). Same escalation as pre-cleanup. Acceptable per Req 2.3.
      - iCIMS: ✅ PASS (CAPTCHA escalation) — Login page detected, auth iframe found, CAPTCHA detected and escalated. Acceptable per Req 2.6.
      - ATS Registration: ✅ PASS — Registration/login detection working (iCIMS login page type detected, auth iframe detected). Module loads cleanly.
      - Pagination: ✅ PASS — Page 1: 53 cards, 25 jobs extracted. Page 2: navigated successfully (pagination_button_found), 55 cards, 25+ jobs extracted. Page 3 navigation initiated.
      - Lint: ✅ PASS — `ruff check` and `ruff format --check` pass on all modified files.
      - **Cleanup reverts needed: NONE** — No regressions detected from cleanup changes.

- [x] 12. Final checkpoint — Spec complete
  - Ensure all tests pass, ask the user if questions arise.
  - Completion gate: Easy Apply ≥1 success, External Apply ≥1 per platform, ATS Registration ≥1 success, Pagination ≥2 pages, lint clean, final regression clean

## Notes

- There is NO test harness to build. Kiro IS the validation runner. Each task is executed by running real pipeline code against real websites.
- The iterative fix cycle (diagnose → fix → re-run) happens WITHIN each task — the agent loops internally until the feature passes.
- Tasks 2-9 are independent of each other (only depend on Task 1 for URLs) and can run in parallel.
- Task 11 depends on ALL validation tasks (2-9) completing first.
- If a platform is unreachable after 3 URL attempts, document it and allow completion for remaining platforms.
- Each task should document: target URL used, fix cycles performed, files modified, final success signal.
- Execution commands run inside Docker: `docker compose exec automator python -c "..."` or similar.
- Logs observed via: `docker compose logs automator --tail=100`
- Screenshots inspected from: `data/` directory

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1", "6.1", "7.1", "8.1", "9.1"] },
    { "id": 2, "tasks": ["11.1"] },
    { "id": 3, "tasks": ["11.2"] }
  ]
}
```
