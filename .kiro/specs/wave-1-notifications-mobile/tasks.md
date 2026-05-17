# Implementation Plan: Notifications & Mobile Access

## Overview

Replace SMS as the primary notification channel with ntfy.sh push notifications. Implement the Ntfy_Client (httpx-based), refactor the Notification_Service into a channel router with SMS fallback, add ntfy action buttons for Human Queue resolution over LAN, generate post-run summaries with retention, expose a Run History API, and build the corresponding web app UI (settings + dashboard section). The existing 10-per-hour rate limit is shared across both channels.

## Tasks

- [ ] 1. Data layer: new models, schema migration, and config keys
  - [ ] 1.1 Add `RunSummary` ORM model and `channel` column to `NotificationLog`
    - Create `RunSummary` model in `src/db/models.py` with fields: id (UUID4 TEXT PK), summary (TEXT, max 500), jobs_discovered, jobs_scored, jobs_approved, jobs_applied, jobs_skipped, jobs_escalated (all INTEGER), errors (TEXT nullable, JSON array), created_at (TEXT ISO 8601)
    - Add index `idx_run_summaries_created_at` on `created_at DESC`
    - Add `channel` column (TEXT NOT NULL DEFAULT 'sms') to `NotificationLog` model; valid values: 'ntfy', 'sms', 'sms_fallback', 'none'
    - _Requirements: 5.4, 5.5, 9.3_

  - [ ] 1.2 Create ntfy config key seeding in startup
    - In `src/main.py` lifespan, after existing settings seeding, call `ensure_topics(session)` to auto-generate `ntfy_urgent_topic` and `ntfy_info_topic` if absent
    - Seed default config keys: `ntfy_enabled` = `false`, `ntfy_server_url` = `"https://ntfy.sh"`, `lan_base_url` = `null`
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 1.3 Write property tests for topic generation
    - **Property 2: Topic Generation Produces Valid Hex Strings**
    - **Property 3: Topic Initialization Idempotence**
    - **Validates: Requirements 2.1, 2.3**

- [ ] 2. Ntfy client and topic generator
  - [ ] 2.1 Implement `src/integrations/ntfy_client.py`
    - Define dataclasses: `NtfySettings`, `NtfyPayload`, `NtfyAction`, `NtfyResult`
    - Implement `async def publish(payload, settings) -> NtfyResult` using httpx with 10s timeout
    - Retry logic: 3 attempts, backoff 5s/15s/30s; do not retry on 4xx
    - Set title to "Job Automator", include tags per payload
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

  - [ ] 2.2 Implement `src/integrations/ntfy_topic_gen.py`
    - Implement `async def ensure_topics(session) -> tuple[str, str]` using `secrets.token_hex(8)`
    - Read from config table; generate only if absent; store and commit
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 2.3 Write property tests for ntfy payload composition
    - **Property 1: Urgent Notification Payload Completeness**
    - **Validates: Requirements 1.2, 1.5**

  - [ ]* 2.4 Write property tests for action button conditional inclusion
    - **Property 4: Action Button Conditional Inclusion**
    - **Property 5: Action Button URL Construction**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.6**

- [ ] 3. Notification service refactor
  - [ ] 3.1 Refactor `src/pipeline/notification_service.py` into channel router
    - Define `NotificationSettings` dataclass combining ntfy + SMS settings
    - Implement `determine_channel(settings)` routing logic: ntfy primary → SMS fallback → none
    - Refactor `notify()` to accept `NotificationSettings`, route to ntfy or SMS
    - On ntfy failure after retries, fall back to SMS if configured
    - Log every attempt (sent, failed, rate-limited) with `channel` field to `notification_log`
    - When both channels disabled, log warning and skip delivery
    - Implement `send_run_summary()` for info-topic publishing (no action buttons, no SMS fallback)
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 9.3_

  - [ ] 3.2 Implement ntfy message composition helpers
    - Implement `compose_urgent_payload(job, trigger_reason, settings) -> NtfyPayload` in notification_service or a dedicated composer module
    - Include job title, company, fit score (when available), trigger reason in message
    - Set priority=4, title="Job Automator", tags=["briefcase"]
    - Conditionally include Approve/Reject action buttons when `queue_reason` is not None AND `lan_base_url` is configured
    - Action button URLs: `{lan_base_url}/queue/{job_id}/approve` and `/reject` with bearer token header
    - Implement `compose_info_payload(summary_text, settings) -> NtfyPayload` with priority=3, tags=["chart_with_upwards_trend"]
    - _Requirements: 1.2, 1.5, 3.1, 3.2, 3.3, 3.5, 3.6, 5.3_

  - [ ] 3.3 Update rate limiter to be channel-agnostic
    - Modify `src/integrations/sms_rate_limiter.py` to count all successful sends (ntfy + sms) in the shared rolling window
    - Ensure the rate limit query counts rows where `success=1` regardless of `channel` value
    - _Requirements: 9.1, 9.2, 9.4_

  - [ ]* 3.4 Write property tests for notification channel routing
    - **Property 8: Notification Channel Routing**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.5**

  - [ ]* 3.5 Write property tests for rate limit enforcement
    - **Property 9: Shared Rate Limit Enforcement**
    - **Property 10: Notification Attempt Logging Completeness**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Run summary generator and API
  - [ ] 5.1 Implement `src/pipeline/run_summary.py`
    - Define `RunStats` dataclass with fields: jobs_discovered, jobs_scored, jobs_approved, jobs_applied, jobs_skipped, jobs_escalated, errors
    - Implement `generate_summary_text(stats) -> str` producing plain-English paragraph, max 500 chars
    - Implement `store_run_summary(session, stats, summary_text) -> RunSummaryRecord` that persists to DB
    - Implement `enforce_retention(session, max_records=20)` to delete oldest entries beyond limit
    - Implement `get_recent_summaries(session, limit=5) -> list[RunSummaryRecord]`
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [ ] 5.2 Create `src/api/run_routes.py` with `GET /runs/history` endpoint
    - Accept optional `limit` query param (default=5, ge=1, le=20)
    - Require bearer token authentication via `verify_token` dependency
    - Return list of `RunHistoryOut` items with id, created_at (ISO 8601), summary
    - Register router in `src/main.py`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 5.3 Write property tests for run summary generation and retention
    - **Property 6: Run Summary Generation Correctness**
    - **Property 7: Run Summary Retention Policy**
    - **Validates: Requirements 5.1, 5.2, 5.5**

  - [ ]* 5.4 Write property test for run history pagination
    - **Property 11: Run History Pagination**
    - **Validates: Requirements 10.1, 10.2, 10.4**

- [ ] 6. LAN server binding
  - [ ] 6.1 Implement `src/api/lan_server.py`
    - Implement `create_lan_app(main_app)` that creates a restricted FastAPI app mounting only `queue_router` and a health endpoint
    - Implement `start_lan_server(lan_ip, port, app)` that starts uvicorn as a background asyncio task
    - Require same bearer token auth on all LAN endpoints
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 6.2 Integrate LAN server startup into application lifespan
    - In `src/main.py` lifespan, read `lan_base_url` from config
    - If configured, parse IP/hostname and port, call `start_lan_server`
    - If not configured, log warning that action buttons are disabled
    - _Requirements: 4.4, 4.5_

  - [ ]* 6.3 Write unit tests for LAN server creation
    - Verify only queue + health routes are mounted
    - Verify auth is required on all LAN endpoints
    - _Requirements: 4.2, 4.3_

- [ ] 7. Ntfy configuration API endpoints
  - [ ] 7.1 Add `GET /config/ntfy` and `PUT /config/ntfy` endpoints
    - Add to `src/api/config_routes.py` or create a dedicated ntfy config router
    - `GET /config/ntfy` returns: ntfy_enabled, ntfy_server_url, urgent_topic, info_topic, lan_base_url (redact api_token)
    - `PUT /config/ntfy` accepts: ntfy_enabled (bool), ntfy_server_url (str), lan_base_url (str|null)
    - Validate server URL starts with http:// or https://
    - Validate LAN address is valid IPv4 or hostname with optional port
    - Require bearer token auth
    - _Requirements: 7.1, 7.3, 7.4, 7.5_

- [ ] 8. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Web App: Ntfy settings UI
  - [ ] 9.1 Add ntfy settings section to `webapp/src/pages/Settings.tsx`
    - Add ntfy enabled toggle (boolean)
    - Add ntfy server URL text field (default "https://ntfy.sh")
    - Display Urgent_Topic and Info_Topic as read-only with copy buttons
    - Add LAN IP/hostname text field with placeholder "e.g., 192.168.1.100:7432"
    - Validate server URL starts with http:// or https:// before save
    - Validate LAN field contains valid IPv4/hostname with optional port
    - Retain existing SMS gateway field alongside ntfy settings
    - Wire save to `PUT /config/ntfy` via the typed API client
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 2.4, 8.4_

  - [ ] 9.2 Add API client methods for ntfy config
    - Add `getNtfyConfig()` and `updateNtfyConfig(data)` to `webapp/src/api/client.ts`
    - Add Zod schemas for ntfy config response validation in `webapp/src/types/`
    - _Requirements: 7.1, 7.3_

- [ ] 10. Web App: Run History dashboard section
  - [ ] 10.1 Add Run History section to `webapp/src/pages/Dashboard.tsx`
    - Display "Run History" section showing the 5 most recent run summaries
    - Each entry shows: relative timestamp (e.g., "2 hours ago") and full summary text
    - When fewer than 5 summaries exist, display all available
    - When no summaries exist, display "No runs have completed yet" message
    - Fetch data from `GET /runs/history` via the typed API client
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 10.2 Add API client method for run history
    - Add `getRunHistory(limit?)` to `webapp/src/api/client.ts`
    - Add Zod schema for run history response validation
    - _Requirements: 10.1, 10.2_

- [ ] 11. Integration wiring: pipeline → notification service
  - [ ] 11.1 Wire pipeline stages to use refactored notification service
    - Update all callers of the old `notify()` function to pass `NotificationSettings` instead of `SMSSettings`
    - Load `NotificationSettings` from config at pipeline start (ntfy_enabled, ntfy settings, sms settings)
    - After pipeline run completes, call `store_run_summary()` then `send_run_summary()` to publish to info topic
    - _Requirements: 1.1, 5.1, 5.3, 8.1, 8.2_

  - [ ]* 11.2 Write integration tests for end-to-end notification flow
    - Test ntfy publish with mocked httpx
    - Test SMS fallback when ntfy fails
    - Test rate limiting across both channels
    - Test run summary generation and delivery after pipeline run
    - _Requirements: 1.1, 1.3, 8.1, 8.5, 9.1_

- [ ] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The LAN server binds selectively (queue + health only) per the security-standards steering — the main server remains localhost-only
- The `channel` column on `notification_log` enables the shared rate limiter to count both ntfy and SMS sends together
- httpx is already available in the project; no new dependency needed for the ntfy client
- Frontend tasks reference `webapp/src/` (the React SPA created in Wave 0), not the removed `extension/` directory

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["3.4", "3.5", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.1"] },
    { "id": 5, "tasks": ["5.4", "6.2", "6.3", "7.1"] },
    { "id": 6, "tasks": ["9.1", "9.2", "10.1", "10.2"] },
    { "id": 7, "tasks": ["11.1"] },
    { "id": 8, "tasks": ["11.2"] }
  ]
}
```
