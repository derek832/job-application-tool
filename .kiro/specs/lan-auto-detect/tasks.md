# Implementation Plan: LAN Auto-Detect

## Overview

Add a LAN IP auto-detection endpoint to the automator backend and a "Detect" button in the Settings UI. The backend resolves the host machine's LAN IP via `host.docker.internal` DNS (with `LAN_IP` env var override), validates it against private ranges, and returns a formatted base URL. The frontend provides a one-click detection flow with loading/error states. Docker Compose exposes port 7432 on all interfaces for LAN access.

## Tasks

- [x] 1. Backend validation module and detection logic
  - [x] 1.1 Create `automator/src/api/lan_detect.py` with pure validation functions
    - Implement `is_ipv4(value: str) -> bool` using regex for four dot-separated octets 0-255
    - Implement `is_private_ip(address: str) -> bool` checking 10/8, 172.16/12, 192.168/16
    - Implement `is_loopback(address: str) -> bool` checking 127.0.0.0/8
    - Implement `is_link_local(address: str) -> bool` checking 169.254.0.0/16
    - Implement `validate_lan_ip(address: str) -> str | None` orchestrating checks, returning error message or None
    - Implement `format_base_url(host: str, port: int = 7432) -> str` returning `http://{host}:{port}`
    - Implement `async def detect_lan_ip() -> str` resolving IP via LAN_IP env var (priority) or `host.docker.internal` DNS with 5s timeout
    - Define `LanDetectionError` exception class for detection failures
    - _Requirements: 1.2, 1.3, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4_

  - [x] 1.2 Add `GET /config/lan-detect` endpoint to `automator/src/api/config_routes.py`
    - Define `LanDetectResponse` Pydantic model with `lan_base_url: str` and `port: int`
    - Define `LanDetectError` Pydantic model with `error: str`
    - Implement route handler: call `detect_lan_ip()`, validate result, return formatted response
    - Return HTTP 503 on `LanDetectionError` (DNS timeout/failure)
    - Return HTTP 422 when resolved IP fails validation (public, loopback, link-local)
    - If value is not IPv4 format (hostname), bypass validation and return as-is
    - Endpoint inherits existing router-level `Depends(verify_token)` authentication
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 5.4_

- [x] 2. Backend property tests
  - [x] 2.1 Write property test for URL formatting correctness
    - **Property 1: URL Formatting Correctness**
    - Generate random valid private IPv4 addresses, verify `format_base_url` produces `http://<address>:7432`
    - **Validates: Requirements 1.1, 1.6**

  - [x] 2.2 Write property test for environment variable override
    - **Property 2: Environment Variable Override Skips DNS**
    - Generate random non-empty, non-whitespace strings as LAN_IP, verify detection returns that value without DNS call
    - **Validates: Requirements 1.2, 4.1**

  - [x] 2.3 Write property test for whitespace-only env var handling
    - **Property 3: Whitespace-Only Environment Variable Is Ignored**
    - Generate random whitespace-only strings, verify detection treats them as unset and proceeds with DNS
    - **Validates: Requirements 4.2**

  - [x] 2.4 Write property test for IP validation logic
    - **Property 4: IP Validation Accepts Only Private Range Addresses**
    - Generate random IPv4 addresses across all ranges, verify validation accepts only private non-loopback non-link-local
    - **Validates: Requirements 5.1, 5.2, 5.4**

  - [x] 2.5 Write property test for hostname bypass
    - **Property 5: Non-IPv4 Values Bypass IP Validation**
    - Generate random strings not matching IPv4 format, verify they are accepted without private-range validation
    - **Validates: Requirements 5.3**

- [x] 3. Backend unit tests
  - [x] 3.1 Write pytest unit tests for the LAN detect endpoint
    - Create `automator/tests/unit/test_lan_detect.py`
    - Test happy path: mock DNS returns private IP, verify 200 response with correct `lan_base_url` and `port`
    - Test env var override: set LAN_IP, verify DNS not called, correct response returned
    - Test DNS timeout: mock 5s timeout, verify 503 with descriptive error message
    - Test public IP rejected: mock DNS returns public IP (e.g., 8.8.8.8), verify 422
    - Test loopback rejected: mock DNS returns 127.0.0.1, verify 422
    - Test link-local rejected: mock DNS returns 169.254.x.x, verify 422
    - Test hostname passthrough: set LAN_IP to non-IPv4 string, verify accepted without validation
    - Test auth required: request without token, verify 401
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4_

- [x] 4. Checkpoint - Backend complete
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 5. Docker Compose and environment configuration
  - [x] 5.1 Update `docker-compose.yml` for LAN port exposure and env var
    - Add port mapping `"0.0.0.0:7432:7432"` to the automator service
    - Add `LAN_IP=${LAN_IP:-}` to the automator service environment list
    - Verify existing `extra_hosts` mapping for `host.docker.internal:host-gateway` is retained
    - _Requirements: 3.1, 3.2, 4.3_

  - [x] 5.2 Update LAN server binding to `0.0.0.0`
    - In `automator/src/main.py`, update the `start_lan_server` call to bind to `"0.0.0.0"` so the LAN server accepts connections from any interface inside the container
    - _Requirements: 3.3_

  - [x] 5.3 Document `LAN_IP` in `.env.example`
    - Add `LAN_IP=` entry with a comment explaining it as an optional override for auto-detection
    - Include example value in comment (e.g., `# LAN_IP=192.168.1.100`)
    - _Requirements: 4.4_

- [x] 6. Frontend API client and Detect button
  - [x] 6.1 Add `detectLanIp` function to `webapp/src/api/client.ts`
    - Define `LanDetectResponseSchema` using Zod with `lan_base_url: z.string()` and `port: z.number().int()`
    - Export `LanDetectResponse` type inferred from schema
    - Implement `detectLanIp()` async function calling `GET /config/lan-detect` with the existing `request` helper
    - _Requirements: 1.1, 1.6_

  - [x] 6.2 Add "Detect" button to Settings UI in `webapp/src/pages/Settings.tsx`
    - Add a "Detect" button adjacent to the LAN IP/Hostname field in the ntfy configuration section
    - On click: call `detectLanIp()`, populate the LAN IP field with `lan_base_url` from response
    - Implement loading state: disable button and show spinner during request
    - Implement 10-second client-side timeout via `AbortController`
    - On error/timeout: display error message inline beneath the LAN IP field, auto-dismiss after 8 seconds
    - On error: preserve existing field value, re-enable button for retry
    - On success: replace field contents but do NOT auto-save (user must click "Save Ntfy Settings")
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 7. Frontend unit tests
  - [x] 7.1 Write Vitest tests for the Detect button component
    - Create test file in `webapp/src/__tests__/`
    - Test button renders in ntfy settings section
    - Test successful detection populates the LAN IP field
    - Test loading state: button disabled + spinner during request
    - Test error display: error shown inline, existing field value preserved
    - Test timeout: 10s timeout triggers error message
    - Test no auto-save: detection success does not trigger save API call
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 8. Final checkpoint - All tests pass
  - Ensure all backend and frontend tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Backend uses Python (FastAPI, pytest, Hypothesis); frontend uses TypeScript (React, Vitest, Zod)
- The LAN server already exists at `automator/src/api/lan_server.py`; task 5.2 only changes the bind address
- Property test file: `automator/tests/property/test_lan_detect_properties.py`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1", "5.3"] },
    { "id": 1, "tasks": ["1.2", "5.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "3.1"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2"] },
    { "id": 5, "tasks": ["7.1"] }
  ]
}
```
