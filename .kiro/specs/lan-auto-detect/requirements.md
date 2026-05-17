# Requirements Document

## Introduction

This feature adds automatic LAN IP detection to the Job Application Tool, eliminating the need for users to manually find and enter their machine's LAN IP address when configuring ntfy action buttons. It also updates the Docker Compose configuration to expose the automator's LAN port (7432) so that ntfy action buttons on the user's phone can reach the automator over the local network.

The detection strategy accounts for the Docker container environment: since the container's own network interfaces report the Docker bridge IP (not the host's LAN IP), the backend uses `host.docker.internal` (already configured via `extra_hosts`) to resolve the host machine's LAN-routable IP address. A fallback mechanism uses an optional `LAN_IP` environment variable for environments where `host.docker.internal` resolution is unreliable.

## Glossary

- **Automator**: The FastAPI backend service running inside Docker that orchestrates the job application pipeline.
- **LAN_Server**: The restricted secondary FastAPI application that exposes only queue and health endpoints on the LAN interface.
- **Settings_UI**: The Settings page in the web application frontend where users configure ntfy notification settings.
- **Detect_Endpoint**: The new backend API endpoint that resolves the host machine's LAN IP address.
- **LAN_IP_Field**: The "LAN IP / Hostname" input field in the ntfy settings section of the Settings_UI.
- **Docker_Compose**: The `docker-compose.yml` file that defines service configuration, port bindings, and networking.
- **host.docker.internal**: A special DNS name that Docker Desktop resolves to the host machine's IP address from within a container.

## Requirements

### Requirement 1: LAN IP Detection Endpoint

**User Story:** As a user, I want the backend to detect my machine's LAN IP address, so that I don't have to manually look it up and type it into the settings.

#### Acceptance Criteria

1. WHEN a GET request is made to `/config/lan-detect`, THE Detect_Endpoint SHALL return a JSON response with HTTP status 200 containing a `lan_base_url` field with the detected base URL and a `port` field with the value 7432.
2. IF the `LAN_IP` environment variable is set to a non-empty value, THEN THE Detect_Endpoint SHALL use its value as the detected IP address without performing DNS resolution.
3. IF the `LAN_IP` environment variable is not set or is empty, THEN THE Detect_Endpoint SHALL attempt to resolve `host.docker.internal` to obtain the host machine's LAN-routable IP address, with a resolution timeout of 5 seconds.
4. IF `host.docker.internal` resolution fails or times out and no valid `LAN_IP` environment variable is set, THEN THE Detect_Endpoint SHALL return an HTTP 503 response with a JSON body containing an `error` field with a message indicating that auto-detection failed.
5. THE Detect_Endpoint SHALL require bearer token authentication consistent with all other config endpoints.
6. WHEN detection succeeds, THE Detect_Endpoint SHALL return the IP address formatted as a full base URL in the `lan_base_url` field (e.g., `http://192.168.1.100:7432`).

---

### Requirement 2: Detect Button in Settings UI

**User Story:** As a user, I want a "Detect" button next to the LAN IP field in settings, so that I can auto-populate the field with one click instead of manually finding my IP.

#### Acceptance Criteria

1. THE Settings_UI SHALL display a "Detect" button adjacent to the LAN_IP_Field within the ntfy configuration section.
2. WHEN the user clicks the Detect button, THE Settings_UI SHALL call the Detect_Endpoint and populate the LAN_IP_Field with the returned base URL.
3. WHILE the detection request is in progress, THE Settings_UI SHALL display a loading indicator on the Detect button and disable the button to prevent duplicate requests. IF the detection request does not complete within 10 seconds, THEN THE Settings_UI SHALL abort the request, re-enable the button, and display an error message indicating the detection timed out.
4. IF the Detect_Endpoint returns an error or the request times out, THEN THE Settings_UI SHALL display the error message inline beneath the LAN_IP_Field for 8 seconds or until the user initiates another detection attempt, without clearing the existing LAN_IP_Field value.
5. WHEN detection succeeds, THE Settings_UI SHALL replace the current contents of the LAN_IP_Field with the detected value regardless of whether the field was previously empty or populated, but SHALL NOT auto-save the ntfy configuration — the user must still click "Save Ntfy Settings" to persist.

---

### Requirement 3: Docker Compose Port Exposure

**User Story:** As a user, I want the automator port to be accessible from my phone on the LAN, so that ntfy action buttons (Approve/Reject) can reach the automator.

#### Acceptance Criteria

1. THE Docker_Compose SHALL map port 7432 from the host to the container using the binding `0.0.0.0:7432:7432` so that devices on the local network can reach the Automator container on port 7432.
2. THE Docker_Compose SHALL retain the existing `extra_hosts` mapping for `host.docker.internal:host-gateway` so that LAN IP detection continues to function.
3. WHEN the container starts with port 7432 exposed on 0.0.0.0, THE LAN_Server SHALL bind to `0.0.0.0` inside the container and expose only queue and health endpoints to LAN devices.
4. WHEN a LAN request includes a valid bearer token matching the configured API_TOKEN, THE LAN_Server SHALL process the request using the same authentication logic as localhost requests.
5. IF a LAN request is missing the bearer token or provides an invalid token, THEN THE LAN_Server SHALL reject the request with an HTTP 401 response and SHALL NOT process the requested action.

---

### Requirement 4: Environment Variable Override

**User Story:** As a user with a non-standard Docker setup, I want to override the auto-detected IP with an environment variable, so that I can use a static IP or hostname when auto-detection doesn't work for my network.

#### Acceptance Criteria

1. WHERE the `LAN_IP` environment variable is set to a non-empty value in the `.env` file, THE Detect_Endpoint SHALL skip DNS resolution and return that value formatted as a full base URL (e.g., `http://<LAN_IP>:7432`).
2. IF the `LAN_IP` environment variable is present but set to an empty string or contains only whitespace, THEN THE Detect_Endpoint SHALL ignore it and proceed with normal `host.docker.internal` DNS resolution.
3. THE Docker_Compose SHALL include `LAN_IP` in the automator container's environment list so that any value defined in the `.env` file is passed through to the container.
4. THE `.env.example` file SHALL document the `LAN_IP` variable with a comment explaining its purpose as an optional override for auto-detection, including an example value (e.g., `LAN_IP=192.168.1.100`).

---

### Requirement 5: Detection Response Validation

**User Story:** As a user, I want the detected IP to be validated before it's shown to me, so that I don't accidentally save an invalid or unreachable address.

#### Acceptance Criteria

1. WHEN the Detect_Endpoint resolves an IP address, THE Detect_Endpoint SHALL validate that the resolved address is a valid IPv4 address in a private network range (10.0.0.0/8, 172.16.0.0/12, or 192.168.0.0/16).
2. IF the resolved address is not in a private network range, THEN THE Detect_Endpoint SHALL return an error response indicating that the detected address does not appear to be a LAN IP and SHALL include the rejected address in the error message for troubleshooting.
3. IF the `LAN_IP` environment variable contains a value that does not match IPv4 dotted-decimal format (four dot-separated octets of 0–255), THEN THE Detect_Endpoint SHALL treat it as a hostname and accept it without private-range validation.
4. IF the resolved address is a loopback address (127.0.0.0/8) or a link-local address (169.254.0.0/16), THEN THE Detect_Endpoint SHALL return an error response indicating that the detected address is not routable on the LAN.
