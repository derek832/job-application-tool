# Implementation Plan: Wave 3 — Pipeline Intelligence

## Overview

This plan implements five sub-features across the existing FastAPI + SQLAlchemy backend (`automator/src/`) and React + TypeScript frontend (`webapp/src/`). Tasks are ordered to build foundational data models first, then backend logic, then API endpoints, then frontend UI — with each sub-feature wired end-to-end before moving to the next.

## Tasks

- [ ] 1. Database models and migrations
  - [ ] 1.1 Add SQLAlchemy models for preview_runs, preview_jobs, blacklist_entries, and notification_queue tables
    - Add `PreviewRun`, `PreviewJob`, `BlacklistEntry`, and `NotificationQueue` models to `automator/src/db/models.py`
    - Include all columns, indexes, and foreign key relationships as specified in the design
    - Add the `schedule_config` and `blacklist_config` keys to the config table schema
    - _Requirements: 1.2, 1.7, 4.1, 4.2, 3.8_

  - [ ] 1.2 Create Alembic migration or table-creation logic for the new tables
    - Ensure `preview_runs`, `preview_jobs`, `blacklist_entries`, and `notification_queue` tables are created on startup
    - Add indexes: `idx_preview_runs_started_at`, `idx_preview_jobs_run_id`, `idx_preview_jobs_job_id`, `idx_blacklist_entries_type`, `idx_blacklist_entries_unique`, `idx_notification_queue_delivered`
    - _Requirements: 1.2, 4.1, 4.2, 3.8_

- [ ] 2. Blacklist filter module
  - [ ] 2.1 Implement `automator/src/pipeline/blacklist_filter.py` with `BlacklistConfig` dataclass and `check_blacklist()` function
    - Company matching: case-insensitive exact match
    - Title pattern matching: case-insensitive substring match
    - Return `(is_blacklisted, matched_entry)` tuple with short-circuit on first match
    - _Requirements: 4.3, 4.4, 4.5, 4.11_

  - [ ]* 2.2 Write property test for blacklist matching correctness
    - **Property 13: Blacklist Matching Correctness**
    - **Validates: Requirements 4.5, 4.11**

  - [ ] 2.3 Implement blacklist database repository in `automator/src/db/blacklist_repo.py`
    - CRUD operations: get all entries, add entry, remove entry, increment hit_count
    - Build `BlacklistConfig` from database entries for pipeline use
    - _Requirements: 4.1, 4.2, 4.9, 4.10_

  - [ ]* 2.4 Write unit tests for blacklist repository CRUD operations
    - Test add/remove/get operations with in-memory SQLite
    - Test hit_count increment
    - _Requirements: 4.1, 4.2, 4.9_

- [ ] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Session health checker
  - [ ] 4.1 Implement `automator/src/pipeline/health_checker.py` with `HealthCheckResult` dataclass and `check_session_health()` function
    - Step 1: HTTP GET to `{cdp_url}/json/version` to verify Chrome is reachable
    - Step 2: Connect via Playwright CDP, navigate to `linkedin.com/feed`, check for login redirect
    - Return structured result with `chrome_reachable`, `linkedin_authenticated`, `error_message`, `checked_at`
    - 15-second timeout on the entire check
    - _Requirements: 2.1, 2.2, 2.3, 2.6_

  - [ ]* 4.2 Write property test for health check failure notification specificity
    - **Property 5: Health Check Failure Notification Specificity**
    - **Validates: Requirements 2.4, 2.9**

  - [ ] 4.3 Integrate health check into pipeline entry point
    - Call `check_session_health()` at the start of `run_pipeline()` in `automator/src/pipeline/job_pipeline.py`
    - On failure: skip the pipeline run, send ntfy notification with specific failure reason
    - On success: update `system_state.last_health_check_at`
    - _Requirements: 2.1, 2.4, 2.8, 2.9_

- [ ] 5. Chrome CDP launcher
  - [ ] 5.1 Implement `automator/src/integrations/chrome_launcher.py` with `get_chrome_status()` and `launch_chrome()` functions
    - `get_chrome_status()`: HTTP GET to CDP `/json/version`, return `ChromeStatus` with `connected`, `browser_version`, `debugger_url`
    - `launch_chrome()`: spawn Chrome as detached subprocess with `--remote-debugging-port=9222`, `--user-data-dir=data/chrome-automation-profile`, `--no-first-run`
    - If Chrome already reachable, return success without launching
    - Never use the user's default Chrome profile directory
    - _Requirements: 5.1, 5.3, 5.4, 5.7, 5.8, 5.9_

  - [ ]* 5.2 Write property test for Chrome launch command correctness
    - **Property 14: Chrome Launch Command Correctness**
    - **Validates: Requirements 5.3, 5.4, 5.8**

- [ ] 6. Preview pipeline mode
  - [ ] 6.1 Implement `automator/src/pipeline/preview_pipeline.py` with `run_preview()` function
    - Reuse discovery and scoring stages from `job_pipeline.py`
    - Call `check_session_health()` before executing stages
    - Apply blacklist filter after discovery, before scoring
    - Persist `PreviewRun` and `PreviewJob` records
    - Compute `projected_action` using `compute_projected_action()` helper
    - Skip jobs that already exist in `job_records` table (deduplication)
    - Never proceed to tailoring or application stages
    - _Requirements: 1.1, 1.2, 1.6, 1.9_

  - [ ]* 6.2 Write property test for preview mode never advancing beyond scoring
    - **Property 1: Preview Mode Never Advances Beyond Scoring**
    - **Validates: Requirements 1.1**

  - [ ]* 6.3 Write property test for preview result persistence completeness
    - **Property 2: Preview Result Persistence Completeness**
    - **Validates: Requirements 1.2**

  - [ ]* 6.4 Write property test for preview deduplication
    - **Property 4: Preview Deduplication**
    - **Validates: Requirements 1.9**

  - [ ] 6.5 Implement preview job promotion logic
    - Accept list of job IDs, copy from `preview_jobs` to `job_records` with status `"approved_for_apply"`
    - Set `preview_jobs.promoted = 1` and `promoted_at` timestamp
    - _Requirements: 1.4_

  - [ ]* 6.6 Write property test for preview job promotion state transition
    - **Property 3: Preview Job Promotion State Transition**
    - **Validates: Requirements 1.4**

- [ ] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Schedule manager
  - [ ] 8.1 Implement `automator/src/scheduler/schedule_manager.py` with `ScheduleConfig` dataclass, `compute_next_run_times()`, and `apply_schedule()` functions
    - `compute_next_run_times_specific()`: generate next N run times from configured daily times
    - `compute_next_run_times_interval()`: generate next N run times from interval within window
    - `apply_schedule()`: remove existing APScheduler pipeline jobs, register new triggers from config
    - Support `specific_times` mode (multiple CronTriggers) and `interval` mode (IntervalTrigger with window)
    - Weekend toggle via `day_of_week` parameter
    - Validate: reject zero times in specific_times mode, reject invalid time formats
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.11, 3.12_

  - [ ]* 8.2 Write property test for specific times schedule correctness
    - **Property 6: Specific Times Schedule Correctness**
    - **Validates: Requirements 3.1**

  - [ ]* 8.3 Write property test for interval schedule correctness
    - **Property 7: Interval Schedule Correctness**
    - **Validates: Requirements 3.2**

  - [ ]* 8.4 Write property test for weekend day filtering
    - **Property 8: Weekend Day Filtering**
    - **Validates: Requirements 3.4, 3.5, 3.6**

  - [ ]* 8.5 Write property test for schedule validation rejecting zero times
    - **Property 11: Schedule Validation Rejects Zero Times**
    - **Validates: Requirements 3.12**

- [ ] 9. Quiet hours manager
  - [ ] 9.1 Implement `automator/src/pipeline/quiet_hours.py` with `is_quiet_hours()`, `queue_notification()`, and `flush_notification_queue()` functions
    - `is_quiet_hours()`: handle same-day and overnight ranges
    - `queue_notification()`: insert into `notification_queue` table
    - `flush_notification_queue()`: compose batch summary, send via ntfy, mark all as delivered
    - Register APScheduler job at `quiet_hours_end` time to trigger flush
    - _Requirements: 3.7, 3.8, 3.9_

  - [ ]* 9.2 Write property test for quiet hours notification queueing
    - **Property 9: Quiet Hours Notification Queueing**
    - **Validates: Requirements 3.8**

  - [ ]* 9.3 Write property test for quiet hours batch delivery
    - **Property 10: Quiet Hours Batch Delivery**
    - **Validates: Requirements 3.9**

  - [ ] 9.4 Integrate quiet hours into notification service
    - Wrap existing `notify()` in `automator/src/pipeline/notification_service.py` with `is_quiet_hours()` check
    - If quiet hours active: call `queue_notification()` instead of immediate delivery
    - _Requirements: 3.8_

- [ ] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Backend API endpoints
  - [ ] 11.1 Create `automator/src/api/preview_routes.py` with preview endpoints
    - `POST /preview`: trigger preview run, return 202 with `run_id`
    - `GET /preview/{run_id}`: return preview run status and job results
    - `POST /preview/{run_id}/promote`: promote selected job IDs to real pipeline
    - Add Pydantic request/response schemas
    - _Requirements: 1.3, 1.4, 1.7, 1.8_

  - [ ] 11.2 Create `automator/src/api/health_routes.py` with session health endpoint
    - `GET /health/session`: perform session health check, return structured result
    - Enforce 15-second timeout
    - _Requirements: 2.5, 2.6_

  - [ ] 11.3 Add schedule endpoints to `automator/src/api/config_routes.py`
    - `GET /config/schedule`: return current schedule configuration
    - `PUT /config/schedule`: validate and save new schedule, call `apply_schedule()` for hot-reload
    - `GET /schedule/next`: compute and return next 3 upcoming run times
    - Return 422 for zero times or invalid formats
    - _Requirements: 3.10, 3.11, 3.12_

  - [ ] 11.4 Add blacklist endpoints to `automator/src/api/config_routes.py`
    - `GET /config/blacklist`: return companies and title patterns with hit counts
    - `PUT /config/blacklist`: replace both blacklists entirely
    - `POST /config/blacklist/companies`: add a company entry
    - `DELETE /config/blacklist/companies/{entry}`: remove a company entry
    - `POST /config/blacklist/titles`: add a title pattern entry
    - `DELETE /config/blacklist/titles/{entry}`: remove a title pattern entry
    - _Requirements: 4.6, 4.7, 4.8, 4.9, 4.10_

  - [ ]* 11.5 Write property test for blacklist configuration round-trip
    - **Property 12: Blacklist Configuration Round-Trip**
    - **Validates: Requirements 4.1, 4.2, 4.10**

  - [ ] 11.6 Create `automator/src/api/chrome_routes.py` with Chrome CDP endpoints
    - `GET /chrome/status`: check Chrome CDP reachability, respond within 3 seconds
    - `POST /chrome/launch`: launch Chrome with automation flags, return success/error
    - _Requirements: 5.1, 5.5, 5.6, 5.7, 5.9_

  - [ ] 11.7 Register all new route modules in `automator/src/main.py`
    - Include `preview_routes`, `health_routes`, `chrome_routes`
    - Ensure new config_routes additions are active
    - _Requirements: 1.7, 1.8, 2.5, 5.1, 5.7_

- [ ] 12. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Frontend — Preview mode UI
  - [ ] 13.1 Create `webapp/src/pages/PreviewResults.tsx` page component
    - Display list of preview jobs with columns: title, company, fit score, projected action
    - Color-code projected actions (green=auto_apply, yellow=stretch_queue, red=skip, gray=blacklisted)
    - Add checkboxes for selecting jobs to promote
    - Add "Approve for Apply" button that calls `POST /preview/{run_id}/promote`
    - _Requirements: 1.3, 1.4_

  - [ ] 13.2 Add "Preview Run" button to Dashboard and preview status indicator
    - Add button to `webapp/src/pages/Dashboard.tsx` that calls `POST /preview`
    - Show running/completed status indicator distinguishing preview from full runs
    - Navigate to PreviewResults page when preview completes
    - _Requirements: 1.1, 1.5_

- [ ] 14. Frontend — Session health and Chrome status UI
  - [ ] 14.1 Add session health indicators and Chrome status to Dashboard
    - Display Chrome CDP status (green "Connected" / red "Not Connected") on `webapp/src/pages/Dashboard.tsx`
    - Display LinkedIn session status as separate indicator
    - Add "Check Session Health" button that calls `GET /health/session`
    - Add "Launch Chrome for Automation" button (shown only when Chrome not connected) that calls `POST /chrome/launch`
    - _Requirements: 2.5, 2.7, 5.2, 5.5, 5.6_

- [ ] 15. Frontend — Schedule configuration UI
  - [ ] 15.1 Create schedule configuration section in Settings page
    - Add schedule config UI to `webapp/src/pages/Settings.tsx` (or create `webapp/src/pages/ScheduleConfig.tsx`)
    - Mode toggle: "Specific Times" vs "Interval"
    - Specific times: add/remove time inputs (HH:MM)
    - Interval: hours input + window start/end time pickers
    - Weekend runs toggle
    - Quiet hours: start/end time pickers (optional)
    - Display next 3 upcoming run times from `GET /schedule/next`
    - Validate: prevent saving with zero times, show validation error
    - Save calls `PUT /config/schedule`
    - _Requirements: 3.3, 3.7, 3.10, 3.12_

- [ ] 16. Frontend — Blacklist configuration UI
  - [ ] 16.1 Create `webapp/src/pages/BlacklistConfig.tsx` page component
    - Two sections: Companies and Title Patterns
    - Each section: list of entries with hit count badge and remove button
    - Add input + button for adding new entries
    - Add calls `POST /config/blacklist/companies` or `POST /config/blacklist/titles`
    - Remove calls `DELETE /config/blacklist/companies/{entry}` or `DELETE /config/blacklist/titles/{entry}`
    - _Requirements: 4.6, 4.7, 4.8, 4.9_

- [ ] 17. Frontend routing and navigation
  - [ ] 17.1 Wire new pages into App router and navigation
    - Add routes for PreviewResults, BlacklistConfig, and ScheduleConfig (if separate page) in `webapp/src/App.tsx`
    - Add navigation links/tabs for new pages
    - _Requirements: 1.3, 4.6_

- [ ] 18. Integration wiring and pipeline integration
  - [ ] 18.1 Integrate blacklist filter into the full pipeline run
    - Call `check_blacklist()` in `automator/src/pipeline/job_pipeline.py` after discovery, before scoring
    - Increment `hit_count` on matched blacklist entries
    - Log skip reason including matched entry
    - _Requirements: 4.3, 4.4, 4.5, 4.11_

  - [ ] 18.2 Wire schedule manager into application startup
    - Load `schedule_config` from database on startup in `automator/src/main.py`
    - Call `apply_schedule()` to register initial APScheduler triggers
    - Register quiet hours flush job at `quiet_hours_end` time
    - _Requirements: 3.1, 3.2, 3.11_

- [ ] 19. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python (FastAPI + SQLAlchemy + APScheduler) and the frontend uses TypeScript (React + Tailwind + Vite) in `webapp/`
- All API endpoints require the same Bearer token authentication as existing endpoints
- Chrome launch never touches the user's default profile — always uses `data/chrome-automation-profile/`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "4.1", "5.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "4.2", "4.3", "5.2"] },
    { "id": 4, "tasks": ["2.4", "6.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4", "6.5", "8.2", "8.3", "8.4", "8.5", "9.2", "9.3", "9.4"] },
    { "id": 6, "tasks": ["6.6", "11.1", "11.2", "11.3", "11.4", "11.6"] },
    { "id": 7, "tasks": ["11.5", "11.7", "18.1", "18.2"] },
    { "id": 8, "tasks": ["13.1", "13.2", "14.1", "15.1", "16.1"] },
    { "id": 9, "tasks": ["17.1"] }
  ]
}
```
