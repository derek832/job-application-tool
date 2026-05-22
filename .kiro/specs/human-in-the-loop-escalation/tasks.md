# Implementation Plan: Human-in-the-Loop Escalation

## Overview

This plan implements a tiered escalation system for the external application pipeline. The implementation proceeds bottom-up: data models and core logic first, then the escalation engine orchestration, API routes, notification integration, Vision Agent integration, and finally the Review UI. Each step builds on the previous, ensuring no orphaned code.

## Tasks

- [x] 1. Data models and database schema
  - [x] 1.1 Create the EscalationRecord ORM model and migration
    - Add `EscalationRecord` class to `automator/src/db/models.py` with all fields (id, job_id, tier, form_state_snapshot, draft_answers, timeout_deadline, freshness_tier, status, resolution_method, created_at, resolved_at)
    - Add relationship to `JobRecord`
    - Create indexes on status, job_id, and timeout_deadline
    - Add Alembic migration (or SQLite schema creation) for the `escalation_records` table
    - _Requirements: 7.1_

  - [x] 1.2 Add API schemas for escalation records
    - Add `EscalationRecordOut`, `EscalationSubmitRequest`, and `EscalationListResponse` to `automator/src/api/schemas.py`
    - Include denormalized fields (job_title, company, fit_score) in `EscalationRecordOut`
    - Add JSON parsing for form_state_snapshot and draft_answers fields
    - _Requirements: 7.1, 7.3_

  - [x] 1.3 Add `human_review_threshold` to Settings schema
    - Extend the existing Settings model with `human_review_threshold: int = 85`
    - Add field validator ensuring value is between 50 and 100 inclusive
    - Add warning log when threshold <= `external_apply_threshold`
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

- [x] 2. Core logic modules
  - [x] 2.1 Implement the Open-Ended Detector module
    - Create `automator/src/pipeline/open_ended_detector.py`
    - Define `OpenEndedField` dataclass with field_id, label, selector, question_text, char_limit
    - Implement `classify_open_ended_fields(dom_fields)` function
    - Classification logic: textarea OR text input with maxlength > 200, AND label contains question phrasing (interrogative words, description/explanation requests, or ends with '?')
    - _Requirements: 2.6_

  - [x] 2.2 Write property test for Open-Ended Field Classification
    - **Property 2: Open-Ended Field Classification**
    - **Validates: Requirements 2.6**

  - [x] 2.3 Implement Freshness Tier calculator
    - Add `FreshnessTier` enum (FRESH, RECENT, STALE) to `automator/src/pipeline/escalation_engine.py`
    - Add `TIMEOUT_BY_FRESHNESS` mapping (45 min, 6 hours, 24 hours)
    - Implement `calculate_freshness_tier(discovered_at: str) -> FreshnessTier`
    - Implement `calculate_timeout_deadline(freshness: FreshnessTier) -> datetime`
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [x] 2.4 Write property test for Freshness Tier and Timeout Calculation
    - **Property 4: Freshness Tier and Timeout Calculation**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**

  - [x] 2.5 Write property test for Human Review Threshold Validation
    - **Property 3: Human Review Threshold Validation**
    - **Validates: Requirements 3.2**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Escalation Engine — creation and decision logic
  - [x] 4.1 Implement `create_escalation` function
    - Create `automator/src/pipeline/escalation_engine.py` main module structure
    - Implement `create_escalation(session, job_record, tier, form_state_snapshot, draft_answers, page, notification_settings) -> EscalationRecord`
    - Enforce one-pending-per-job uniqueness (check before insert, return existing if found)
    - Generate UUID, set created_at, compute freshness tier and timeout deadline for human_review tier
    - Set timeout_deadline to NULL for CAPTCHA tier
    - Persist the record to the database
    - _Requirements: 1.1, 2.1, 2.3, 4.1, 4.2, 4.3, 7.1, 7.5_

  - [x] 4.2 Write property test for Escalation Decision Boundary
    - **Property 1: Escalation Decision Boundary**
    - **Validates: Requirements 2.1, 2.5**

  - [x] 4.3 Write property test for CAPTCHA Escalations Have No Timeout
    - **Property 5: CAPTCHA Escalations Have No Timeout**
    - **Validates: Requirements 1.3**

  - [x] 4.4 Write property test for One Pending Escalation Per Job
    - **Property 10: One Pending Escalation Per Job**
    - **Validates: Requirements 7.5**

  - [x] 4.5 Implement `resolve_escalation` function
    - Implement `resolve_escalation(session, escalation_id, resolution, edited_answers) -> EscalationRecord`
    - Handle "resolved" resolution: set status, resolution_method="user_submit", store edited answers, set resolved_at
    - Handle "skipped" resolution: set status="skipped", resolution_method="user_skip", transition job to "skipped" with queue_reason="user_skipped_escalation"
    - Return 404-equivalent if not found, 409-equivalent if already resolved
    - _Requirements: 6.3, 6.4, 7.2, 8.2_

  - [x] 4.6 Write property test for Submit Resolution Stores Edited Answers
    - **Property 11: Submit Resolution Stores Edited Answers**
    - **Validates: Requirements 6.3**

  - [x] 4.7 Write property test for Skip Resolution Transitions Correctly
    - **Property 12: Skip Resolution Transitions Correctly**
    - **Validates: Requirements 6.4**

  - [x] 4.8 Implement `handle_timeout` function
    - Implement `handle_timeout(session, escalation_id) -> None`
    - No-op if escalation already resolved (log info)
    - Set status="auto_submitted", resolution_method="auto_submit", resolved_at=now
    - Trigger resume mechanism with original draft_answers
    - Log auto-submission with timeout duration and freshness tier
    - _Requirements: 4.4, 4.6_

  - [x] 4.9 Write property test for Timeout Handler Auto-Submits
    - **Property 13: Timeout Handler Auto-Submits**
    - **Validates: Requirements 4.4**

  - [x] 4.10 Write property test for Resolution Metadata Completeness
    - **Property 8: Resolution Metadata Completeness**
    - **Validates: Requirements 7.2**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. CAPTCHA detection and polling
  - [x] 6.1 Implement CAPTCHA polling loop in Escalation Engine
    - Add `poll_captcha_resolution(page, escalation_id, session)` async function
    - Poll page state every 5 seconds for up to 30 minutes
    - On resolution: update escalation status to "resolved", resolution_method="captcha_solved", resume automation
    - Record solved domain in session context for deduplication
    - _Requirements: 1.4, 1.6_

  - [x] 6.2 Implement CAPTCHA expiry handler
    - Add logic to detect CAPTCHA escalations older than 24 hours
    - Mark as "expired", resolution_method="timeout_expired"
    - Transition job to "apply_failed" with queue_reason="captcha_timeout"
    - Register check on startup for expired CAPTCHA escalations
    - _Requirements: 1.5_

  - [x] 6.3 Write property test for CAPTCHA Expiry After 24 Hours
    - **Property 14: CAPTCHA Expiry After 24 Hours**
    - **Validates: Requirements 1.5**

- [x] 7. Notification composition and delivery
  - [x] 7.1 Implement escalation notification composer
    - Create `compose_escalation_notification` function
    - For CAPTCHA tier: priority 4, include job title, company, ATS domain, "Solve CAPTCHA in Chrome to continue", Review action button
    - For human_review tier: priority 3, include job title, company, fit score, open-ended question count, freshness tier label, relative timeout deadline, Review action button
    - Integrate with existing ntfy notification service
    - _Requirements: 1.2, 2.4, 5.1, 5.2, 5.3, 5.4_

  - [x] 7.2 Write property test for Notification Composition Completeness
    - **Property 6: Notification Composition Completeness**
    - **Validates: Requirements 1.2, 2.4, 5.1, 5.2, 5.3, 5.4**

  - [x] 7.3 Wire notification delivery with fallback
    - Call ntfy publish from `create_escalation`
    - On ntfy failure after 3 retries, fall back to SMS via existing fallback mechanism
    - Log delivery failures
    - _Requirements: 5.5_

- [x] 8. APScheduler timeout integration
  - [x] 8.1 Register timeout jobs with APScheduler
    - Schedule one-shot APScheduler job when human_review escalation is created
    - Job calls `handle_timeout` at the computed deadline
    - Cancel scheduled job when escalation is resolved before timeout
    - _Requirements: 4.4, 4.6_

  - [x] 8.2 Implement startup recovery for pending timeouts
    - On application startup, query all pending escalations with non-null timeout_deadline
    - For deadlines in the past: trigger immediate auto-submit
    - For future deadlines: re-register APScheduler jobs
    - _Requirements: 4.4_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. API routes for escalation management
  - [x] 10.1 Create escalation API route file and list endpoint
    - Create `automator/src/api/escalation_routes.py`
    - Implement `GET /escalations` — list pending escalations (sorted by timeout_deadline ascending, NULL last)
    - Support `?include_resolved=true` query parameter to include all statuses
    - Require bearer token authentication
    - Return denormalized job info (title, company, fit_score)
    - _Requirements: 6.1, 7.3, 7.4_

  - [x] 10.2 Write property test for Pending List Filtering and Sorting
    - **Property 9: Pending List Filtering and Sorting**
    - **Validates: Requirements 6.1, 7.4**

  - [x] 10.3 Implement single escalation detail endpoint
    - Implement `GET /escalations/{id}` — return full escalation record with form state and draft answers
    - Require bearer token authentication
    - Return 404 if not found
    - _Requirements: 6.2, 7.3_

  - [x] 10.4 Implement submit and skip endpoints
    - Implement `POST /escalations/{id}/submit` — accept edited_answers, call `resolve_escalation` with resolution="resolved"
    - Implement `POST /escalations/{id}/skip` — call `resolve_escalation` with resolution="skipped"
    - Return 409 if escalation already resolved
    - Require bearer token authentication
    - _Requirements: 6.3, 6.4, 6.5_

  - [x] 10.5 Register escalation routes with the FastAPI app
    - Import and include the escalation router in the main app
    - _Requirements: 7.3_

- [x] 11. Draft answer generation
  - [x] 11.1 Implement Claude draft answer generation
    - Add `generate_draft_answers(questions, job_description, goals_profile, supplementary_context)` function
    - Call Claude API with job description, user goals, supplementary_context, and each question
    - Return list of DraftAnswer objects (field_id, question_text, draft_answer)
    - Handle Claude API failures: retry 3x with backoff, create escalation without drafts if all fail
    - _Requirements: 2.1, 2.2_

- [x] 12. Vision Agent integration
  - [x] 12.1 Integrate escalation into `process_external_apply` flow
    - Replace current `Result(ok=False, reason="captcha_detected")` with call to `create_escalation(tier="captcha")`
    - Add open-ended field detection after form field identification
    - When open-ended fields found AND fit_score >= threshold: call `create_escalation(tier="human_review")`
    - When open-ended fields found AND fit_score < threshold: auto-fill with Claude drafts and proceed
    - _Requirements: 1.1, 2.1, 2.5_

  - [x] 12.2 Implement `resume_from_escalation` in Vision Agent
    - For CAPTCHA resolution: continue form filling from current page state
    - For human_review resolution: navigate to stored external URL, re-fill all fields from snapshot + edited answers, proceed to submission
    - For auto-submit: same as human_review but use original draft_answers
    - Detect form expiry (page load failure, structure mismatch): mark escalation "expired", job "apply_failed"
    - Handle navigation/submission errors: mark escalation "expired", log error details
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 12.3 Write property test for Resume Error Handling
    - **Property 15: Resume Error Handling**
    - **Validates: Requirements 8.3, 8.5**

  - [x] 12.4 Write property test for Escalation Record Persistence Round-Trip
    - **Property 7: Escalation Record Persistence Round-Trip**
    - **Validates: Requirements 7.1**

- [x] 13. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Review UI — webapp frontend
  - [x] 14.1 Create escalation list page component
    - Add `/escalations` route to the React webapp
    - Fetch pending escalations from `GET /escalations`
    - Display sorted list: job title, company, fit score, tier badge, countdown timer
    - Color-code urgency (red < 15 min, amber < 1 hour, green > 1 hour)
    - Reuse existing auth mechanism and Tailwind styling
    - _Requirements: 6.1, 6.5_

  - [x] 14.2 Create escalation detail page component
    - Add `/escalations/:id` route to the React webapp
    - Fetch single escalation from `GET /escalations/{id}`
    - Display Form State Snapshot: field labels and values in form-like layout
    - Show page screenshot as reference image
    - Editable textarea for each Draft Answer
    - "Submit" button calls `POST /escalations/{id}/submit` with edited answers
    - "Skip" button calls `POST /escalations/{id}/skip`
    - _Requirements: 6.2, 6.3, 6.4_

  - [x] 14.3 Implement read-only mode for resolved escalations
    - When escalation status is not "pending", display as read-only
    - Show resolution status badge and resolved_at timestamp
    - Disable edit controls and action buttons
    - _Requirements: 6.6_

  - [x] 14.4 Write frontend tests for escalation components
    - Test list component renders pending items sorted by urgency
    - Test detail component renders form state and editable draft answers
    - Test countdown timer displays correct relative time
    - Test read-only mode for resolved records
    - Test submit/skip button handlers call correct API endpoints
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

- [x] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python for the automator backend and TypeScript/React for the webapp frontend
- APScheduler is used for timeout scheduling; pending timeouts are recovered from DB on container restart
- The existing ntfy notification service and SMS fallback mechanism are reused

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "2.1", "2.3"] },
    { "id": 2, "tasks": ["2.2", "2.4", "2.5"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.8"] },
    { "id": 5, "tasks": ["4.6", "4.7", "4.9", "4.10"] },
    { "id": 6, "tasks": ["6.1", "6.2", "7.1", "8.1", "11.1"] },
    { "id": 7, "tasks": ["6.3", "7.2", "7.3", "8.2"] },
    { "id": 8, "tasks": ["10.1", "10.3", "10.4"] },
    { "id": 9, "tasks": ["10.2", "10.5", "12.1", "12.2"] },
    { "id": 10, "tasks": ["12.3", "12.4"] },
    { "id": 11, "tasks": ["14.1", "14.2"] },
    { "id": 12, "tasks": ["14.3", "14.4"] }
  ]
}
```
