# Implementation Plan: Wave 2 — New User Experience

## Overview

This plan implements the in-app setup wizard, first-run gating, and integrated troubleshooting for the web app. The backend gets two new unauthenticated endpoints (`GET /setup/status`, `POST /setup/validate/{step}`) with per-step validation logic and server-side persistence. The frontend gets a 6-step wizard component that gates the entire app, a Diagnostics page, and health alert banners on the Dashboard.

The implementation assumes Wave 0 (web app migration) is complete — the `webapp/` directory exists with the React + Tailwind + Vite stack, nginx proxy, and the existing page components (Dashboard, Settings, etc.).

## Tasks

- [ ] 1. Backend: Pydantic schemas and setup routes scaffold
  - [ ] 1.1 Add setup-related Pydantic schemas to `automator/src/api/schemas.py`
    - Add `SetupSteps`, `SetupStatusResponse`, `ValidationResponse`, and `StepValidationRequest` models
    - `SetupSteps` has 6 boolean fields: `claude_api`, `google_apps_script`, `gmail`, `profile`, `goals`, `search`
    - `SetupStatusResponse` has `complete: bool` and `steps: SetupSteps`
    - `ValidationResponse` has `valid: bool` and `message: str`
    - `StepValidationRequest` has `data: dict = {}`
    - _Requirements: 9.1, 9.2, 10.3, 10.4, 10.5_

  - [ ] 1.2 Create `automator/src/api/setup_routes.py` with route stubs
    - Create the router with `GET /setup/status` and `POST /setup/validate/{step}` endpoints
    - Both endpoints are unauthenticated (no `verify_token` dependency)
    - Return 404 for unknown step names in the validate endpoint
    - Register the router in the FastAPI app (prefix `/setup`)
    - _Requirements: 9.4, 10.1_

- [ ] 2. Backend: Setup status endpoint logic
  - [ ] 2.1 Implement `GET /setup/status` with config-presence checks
    - Read `settings`, `goals_profile`, `user_profile`, `search_config` from the config table
    - `claude_api`: True if `settings.claude_api_key` is non-empty
    - `google_apps_script`: True if `settings.gdocs_script_url` is non-empty
    - `gmail`: True if Gmail OAuth token file exists and credentials load successfully
    - `profile`: True if full_name, email, phone, work_auth are all non-empty strings
    - `goals`: True if target_titles has at least one non-empty entry AND career_objective is non-empty
    - `search`: True if keywords is non-empty OR search_queries has at least one non-empty entry
    - `complete` = logical AND of all 6 step booleans
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ]* 2.2 Write property test for setup status completeness derivation
    - **Property 10: Setup Status Completeness Derivation**
    - Use Hypothesis to generate all combinations of 6 booleans, verify `complete` equals their logical AND
    - **Validates: Requirements 9.2, 9.3**

- [ ] 3. Backend: Step validation logic — connectivity checks
  - [ ] 3.1 Implement `_validate_claude_api` with live Anthropic API call
    - Send GET to `https://api.anthropic.com/v1/models` with the provided key
    - Return `valid: true` for non-5xx responses
    - Return specific error messages for 401 (rejected key) and 5xx/timeout (unreachable)
    - On successful validation, persist the key to `settings.claude_api_key` in the config table
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

  - [ ] 3.2 Implement `_validate_gas_url` with live HTTP GET
    - Send GET to the provided URL with `follow_redirects=True`
    - Return `valid: true` for HTTP 200
    - Return authorization error message for 401 or JSON body containing authorization error
    - Return unreachable message for network errors or timeout
    - On successful validation, persist the URL to `settings.gdocs_script_url`
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [ ] 3.3 Implement `_validate_gmail` with OAuth token check
    - Use existing `load_credentials()` from `src.integrations.gmail_oauth`
    - Return `valid: true` if credentials exist and are valid
    - Return specific messages for missing token vs expired token
    - _Requirements: 4.2, 4.3, 4.4, 4.5_

  - [ ] 3.4 Wrap all connectivity validators in `asyncio.wait_for(timeout=10.0)`
    - Catch `asyncio.TimeoutError` and return the timeout-specific failure message
    - Apply to claude_api, google_apps_script, and gmail validators
    - _Requirements: 10.6_

  - [ ]* 3.5 Write property test for Claude API validation status mapping
    - **Property 4: Claude API Validation Status Mapping**
    - Use Hypothesis to generate HTTP status codes, verify correct valid/message mapping
    - **Validates: Requirements 2.3, 2.4, 2.5**

  - [ ]* 3.6 Write property test for Google Apps Script validation status mapping
    - **Property 5: Google Apps Script Validation Status Mapping**
    - Use Hypothesis to generate HTTP status codes and response bodies, verify correct mapping
    - **Validates: Requirements 3.3, 3.4, 3.5**

  - [ ]* 3.7 Write property test for validation timeout enforcement
    - **Property 12: Validation Timeout Enforcement**
    - Use Hypothesis to generate delay durations, verify that delays > 10s produce timeout failure
    - **Validates: Requirements 10.6**

- [ ] 4. Backend: Step validation logic — data completeness checks
  - [ ] 4.1 Implement `_validate_profile` with field completeness check
    - Require non-empty strings (after trim) for: full_name, email, phone, work_auth
    - On failure, list the specific missing field labels in the message
    - On success, persist to `user_profile` config key
    - _Requirements: 5.2, 5.3, 5.4_

  - [ ] 4.2 Implement `_validate_goals` with minimum configuration check
    - Require at least one non-empty target_title AND non-empty career_objective
    - Return specific messages for missing titles vs missing objective
    - On success, persist to `goals_profile` config key
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 4.3 Implement `_validate_search` with query presence check
    - Require at least one non-empty keyword OR at least one non-empty search_query
    - Return specific message when both are empty
    - On success, persist to `search_config` config key
    - _Requirements: 7.2, 7.3, 7.4_

  - [ ]* 4.4 Write property test for profile field completeness validation
    - **Property 6: Profile Field Completeness Validation**
    - Use Hypothesis to generate combinations of field values (empty, whitespace, valid strings)
    - Verify valid=true iff all 4 fields are non-empty after trim; verify error lists exactly the empty fields
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [ ]* 4.5 Write property test for goals minimum configuration validation
    - **Property 7: Goals Minimum Configuration Validation**
    - Use Hypothesis to generate target_titles lists and career_objective strings
    - Verify valid=true iff at least one non-empty title AND non-empty objective
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6**

  - [ ]* 4.6 Write property test for search config validation
    - **Property 8: Search Config Validation**
    - Use Hypothesis to generate keywords strings and search_queries lists
    - Verify valid=true iff at least one non-empty keyword OR one non-empty query
    - **Validates: Requirements 7.2, 7.3, 7.4**

- [ ] 5. Checkpoint — Backend validation complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Frontend: TypeScript types and API client additions
  - [ ] 6.1 Create `webapp/src/types/setup.ts` with setup-related interfaces
    - Define `SetupSteps`, `SetupStatus`, and `ValidationResult` interfaces
    - _Requirements: 9.2, 10.3_

  - [ ] 6.2 Add setup API functions to `webapp/src/api/client.ts`
    - `fetchSetupStatus()`: GET `/api/setup/status` (no auth header required)
    - `validateStep(step: string, data: Record<string, unknown>)`: POST `/api/setup/validate/{step}` (no auth)
    - Both functions skip the Bearer token since setup endpoints are unauthenticated
    - _Requirements: 8.1, 9.4, 10.1_

- [ ] 7. Frontend: Setup Wizard component
  - [ ] 7.1 Create `webapp/src/components/SetupWizard.tsx` with step navigation shell
    - Define the 6-step configuration with keys, titles, and descriptions
    - Manage wizard state: currentStep, stepData, stepValidated, validating, errorMessage
    - On mount, read `initialStatus.steps` to skip already-complete steps
    - Implement Next/Back navigation with data preservation
    - Show progress indicator ("Step N of 6")
    - _Requirements: 1.1, 1.5, 1.6, 8.4_

  - [ ] 7.2 Implement step form components for each wizard step
    - Step 1 (Claude API Key): single password-type text input
    - Step 2 (Google Apps Script): single URL text input
    - Step 3 (Gmail): status display with "Check" button (read-only — user runs external script)
    - Step 4 (Profile): inputs for full_name, email, phone, work_auth
    - Step 5 (Goals): target_titles list input + career_objective textarea
    - Step 6 (Search): keywords input + search_queries list input
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 6.1, 7.1_

  - [ ] 7.3 Wire validation calls to the Next button
    - On "Next" click, call `validateStep(stepKey, stepData[stepKey])`
    - While validating: show spinner on button, disable button
    - On success: mark step validated, advance to next step
    - On failure: display `message` from response below form fields
    - After final step validates: show "Setup Complete" celebration screen
    - _Requirements: 1.2, 1.3, 1.4, 8.5_

  - [ ]* 7.4 Write unit tests for wizard step navigation logic (Vitest)
    - Test advancing only on valid=true, blocking on valid=false
    - Test back navigation preserves all step data
    - Test skipping to first incomplete step on mount
    - _Requirements: 1.2, 1.6, 8.4_

- [ ] 8. Frontend: First-run gate in App.tsx
  - [ ] 8.1 Modify `webapp/src/App.tsx` to gate on setup status
    - On mount, call `fetchSetupStatus()`
    - If `complete` is false, render `SetupWizard` as the only UI (block all routes)
    - If `complete` is true, render the normal app shell (Dashboard, Queue, etc.)
    - Show a loading screen while the status check is in flight
    - Handle network errors gracefully (show connection error banner)
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 8.2 Write unit test for first-run gate conditional rendering (Vitest)
    - Test wizard renders when complete=false
    - Test main app renders when complete=true
    - Test loading state while fetching
    - _Requirements: 8.2, 8.3_

- [ ] 9. Checkpoint — Wizard flow complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Frontend: Dashboard health banners
  - [ ] 10.1 Create `webapp/src/components/HealthBanner.tsx`
    - Accept health object `{ claude_api: boolean, gmail: boolean, google_docs: boolean }`
    - Render amber alert banners for each unhealthy service with plain-English guidance
    - Render nothing when all services are healthy
    - Use the specific guidance messages from Requirements 11.3, 11.4, 11.5
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ] 10.2 Integrate `HealthBanner` into the Dashboard page
    - Place the banner above the stats cards
    - Feed it the health data from the existing polling response
    - Auto-dismiss when next health poll returns all-healthy
    - _Requirements: 11.1, 11.6_

  - [ ]* 10.3 Write property test for health state to dashboard banner mapping (Vitest + fast-check)
    - **Property 13: Health State to Dashboard Banner Mapping**
    - Use fast-check to generate all combinations of 3 booleans
    - Verify: banner count equals number of false values; zero banners when all true
    - **Validates: Requirements 11.1, 11.2, 11.6**

- [ ] 11. Frontend: Diagnostics page
  - [ ] 11.1 Create `webapp/src/pages/Diagnostics.tsx`
    - Add "Run Diagnostics" button that calls `GET /api/health`
    - Display each service with green checkmark (pass) or red X (fail)
    - For failing services, render remediation guidance block with service name and fix instructions
    - Show "All systems are working correctly" when all pass
    - Show loading state while checks are running
    - Allow re-running without navigating away
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ] 11.2 Add Diagnostics page to the app navigation and router
    - Add route entry in App.tsx router
    - Add navigation link in the sidebar (Navigation component)
    - _Requirements: 12.1_

  - [ ]* 11.3 Write unit tests for Diagnostics page rendering (Vitest)
    - Test loading state while running
    - Test pass/fail indicators per service
    - Test remediation guidance appears for failing services
    - Test "all working" message when all pass
    - _Requirements: 12.3, 12.4, 12.5_

- [ ] 12. Backend: Integration tests for setup endpoints
  - [ ]* 12.1 Write integration tests for `GET /setup/status` and `POST /setup/validate/{step}`
    - Test `GET /setup/status` returns correct structure with no auth header
    - Test `POST /setup/validate/claude_api` with mocked httpx (success, 401, timeout)
    - Test `POST /setup/validate/google_apps_script` with mocked httpx (200, 401, unreachable)
    - Test `POST /setup/validate/gmail` with mocked credentials loader (valid, missing, expired)
    - Test `POST /setup/validate/profile` with various field combinations
    - Test `POST /setup/validate/goals` with various field combinations
    - Test `POST /setup/validate/search` with various field combinations
    - Test unknown step name returns 404
    - Test that successful validation persists data to config table
    - _Requirements: 9.1, 9.4, 10.1, 10.2, 10.4, 10.5, 10.6_

  - [ ]* 12.2 Write property test for validation response structure consistency
    - **Property 11: Validation Response Structure Consistency**
    - Use Hypothesis to generate arbitrary step names and request bodies
    - Verify response always has exactly `valid` (bool) and `message` (str)
    - When valid=true, message is empty; when valid=false, message is non-empty
    - **Validates: Requirements 10.3, 10.4, 10.5**

- [ ] 13. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend persists step data immediately on successful validation (server-side), eliminating the need for authenticated config calls during the wizard flow
- The frontend web app structure follows the Wave 0 conventions: `webapp/src/` with `api/`, `components/`, `hooks/`, `pages/`, `types/` directories

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "6.2"] },
    { "id": 2, "tasks": ["2.1", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3"] },
    { "id": 3, "tasks": ["2.2", "3.4", "3.5", "3.6", "3.7", "4.4", "4.5", "4.6"] },
    { "id": 4, "tasks": ["7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3"] },
    { "id": 6, "tasks": ["7.4", "8.1"] },
    { "id": 7, "tasks": ["8.2", "10.1", "11.1"] },
    { "id": 8, "tasks": ["10.2", "10.3", "11.2", "11.3"] },
    { "id": 9, "tasks": ["12.1", "12.2"] }
  ]
}
```
