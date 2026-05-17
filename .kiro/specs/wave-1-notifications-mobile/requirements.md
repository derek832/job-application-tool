# Requirements Document

## Introduction

This feature replaces the primary SMS notification channel with ntfy.sh push notifications, enabling instant mobile alerts without carrier SMS gateway dependencies. The Automator will publish to two auto-generated ntfy topics (urgent and info), with action buttons on Human Queue notifications that allow approve/reject directly from the phone over LAN. A plain-English post-run summary is sent to the info topic and displayed in a new "Run History" section on the Extension Dashboard. SMS is retained as an optional fallback. The existing 10-per-hour rate limit carries over to ntfy notifications.

---

## Glossary

- **Automator**: The FastAPI orchestration service running inside Docker on the user's local machine.
- **Extension**: The Chrome browser extension that serves as the user-facing control panel.
- **Ntfy_Client**: The module within the Automator responsible for publishing messages to ntfy.sh topics via HTTP POST.
- **Ntfy_Server**: The ntfy.sh instance (public or self-hosted) that receives and distributes push notifications to subscribed devices.
- **Urgent_Topic**: The randomly-generated ntfy topic name used for time-sensitive Human Queue notifications requiring user action.
- **Info_Topic**: The randomly-generated ntfy topic name used for informational messages such as post-run summaries.
- **Action_Button**: An ntfy notification action (type: http) that triggers an HTTP request to the Automator's LAN-accessible queue endpoint when tapped.
- **LAN_Base_URL**: The user-configured base URL (IP or hostname plus port) used to construct action button callback URLs reachable from the user's phone on the local network.
- **Run_Summary**: A plain-English summary of a completed pipeline run, including counts of jobs discovered, scored, applied, skipped, and escalated.
- **Run_History**: A section on the Extension Dashboard displaying the last 5 Run_Summaries with timestamps.
- **Human_Queue**: The list of jobs or actions awaiting manual user review or input.
- **Notification_Service**: The orchestration layer that routes notifications to ntfy (primary) or SMS (fallback) and enforces rate limiting.
- **State_DB**: The local SQLite database that tracks all job records, configuration, and notification logs.

---

## Requirements

### Requirement 1: Ntfy Push Notification Delivery

**User Story:** As a job seeker, I want to receive instant push notifications on my phone via ntfy.sh, so that I can respond to Human Queue items without relying on degraded carrier SMS gateways.

#### Acceptance Criteria

1. WHEN a Notification_Trigger condition is met and ntfy is enabled, THE Ntfy_Client SHALL publish a message to the Urgent_Topic via HTTP POST within 60 seconds of detecting the condition.
2. THE Ntfy_Client SHALL include in each urgent notification: the job title, company name, fit score (when available), trigger reason, and a priority level of "high" (ntfy priority 4).
3. IF the ntfy HTTP POST fails, THEN THE Ntfy_Client SHALL retry up to 3 times with backoff delays of 5 seconds, 15 seconds, and 30 seconds before logging the failure and continuing.
4. THE Ntfy_Client SHALL authenticate with the Ntfy_Server using the configured server URL and topic name without requiring user account creation.
5. THE Ntfy_Client SHALL set the notification title to "Job Automator" and include a tag of "briefcase" on all urgent notifications.

---

### Requirement 2: Ntfy Topic Auto-Generation

**User Story:** As a job seeker, I want two unique ntfy topic names generated automatically, so that my notification channels are private without manual setup.

#### Acceptance Criteria

1. WHEN the Automator starts for the first time and no Urgent_Topic or Info_Topic is configured, THE Automator SHALL generate two random topic names using a cryptographically secure random generator producing 16-character hexadecimal strings.
2. THE Automator SHALL store the generated Urgent_Topic and Info_Topic values in the State_DB configuration table.
3. WHEN the Urgent_Topic and Info_Topic already exist in the State_DB, THE Automator SHALL reuse the stored values without regenerating them.
4. THE Extension SHALL display both topic names in the Settings section so the user can subscribe to them in the ntfy mobile app.

---

### Requirement 3: Ntfy Action Buttons for Human Queue

**User Story:** As a job seeker, I want approve and reject buttons on my phone notifications, so that I can resolve Human Queue items without opening my computer.

#### Acceptance Criteria

1. WHEN a notification is published to the Urgent_Topic for a job in the Human_Queue, THE Ntfy_Client SHALL include two action buttons: "Approve" and "Reject".
2. THE "Approve" action button SHALL send an HTTP POST request to `{LAN_Base_URL}/queue/{job_id}/approve` with the configured bearer token in the Authorization header.
3. THE "Reject" action button SHALL send an HTTP POST request to `{LAN_Base_URL}/queue/{job_id}/reject` with the configured bearer token in the Authorization header.
4. THE Automator SHALL bind the queue API endpoints to the LAN_Base_URL address (in addition to localhost) so that action button callbacks are reachable from the user's phone on the local network.
5. THE Automator SHALL require bearer token authentication on all LAN-bound queue endpoints, using the same API token as localhost requests.
6. WHEN a notification does not correspond to a Human_Queue item (e.g., informational alerts), THE Ntfy_Client SHALL omit action buttons from that notification.

---

### Requirement 4: LAN Network Binding for Queue Endpoints

**User Story:** As a job seeker, I want the queue endpoints accessible over my home network, so that ntfy action buttons can reach the Automator from my phone.

#### Acceptance Criteria

1. THE Automator SHALL bind its HTTP server to the user-configured LAN IP address (or hostname) in addition to the existing localhost (127.0.0.1) binding.
2. THE LAN binding SHALL expose only the queue-related endpoints (`/queue`, `/queue/{job_id}/approve`, `/queue/{job_id}/reject`, `/queue/{job_id}/manual`) and the `/health` endpoint.
3. THE Automator SHALL require the same bearer token authentication on LAN-bound endpoints as on localhost endpoints.
4. THE LAN IP address SHALL be configurable via the Extension Settings and stored in the State_DB configuration table.
5. IF no LAN IP address is configured, THEN THE Automator SHALL bind only to localhost (127.0.0.1) and log a warning that action buttons are disabled.

---

### Requirement 5: Post-Run Summary Generation and Delivery

**User Story:** As a job seeker, I want a plain-English summary after each pipeline run, so that I know what happened without checking the dashboard.

#### Acceptance Criteria

1. WHEN a pipeline run completes (all stages finished or skipped), THE Automator SHALL generate a Run_Summary containing: total jobs discovered, total jobs scored, jobs approved for apply, jobs applied successfully, jobs skipped, jobs escalated to Human_Queue, and any errors encountered.
2. THE Run_Summary SHALL be written in plain English as a short paragraph (maximum 500 characters).
3. WHEN ntfy is enabled, THE Automator SHALL publish the Run_Summary to the Info_Topic with a priority level of "default" (ntfy priority 3) and a tag of "chart_with_upwards_trend".
4. THE Automator SHALL store each Run_Summary with its timestamp in the State_DB.
5. THE Automator SHALL retain the 20 most recent Run_Summaries in the State_DB and delete older entries.

---

### Requirement 6: Run History Dashboard Display

**User Story:** As a job seeker, I want to see my recent run summaries on the Extension Dashboard, so that I can review activity at a glance.

#### Acceptance Criteria

1. THE Extension SHALL display a "Run History" section on the Dashboard page showing the 5 most recent Run_Summaries.
2. EACH Run_History entry SHALL display: the run timestamp (formatted as relative time, e.g., "2 hours ago") and the full Run_Summary text.
3. WHEN fewer than 5 Run_Summaries exist, THE Extension SHALL display all available entries.
4. WHEN no Run_Summaries exist, THE Extension SHALL display a message indicating no runs have completed yet.
5. THE Extension SHALL fetch Run_History data from a new Automator API endpoint.

---

### Requirement 7: Ntfy Settings Configuration

**User Story:** As a job seeker, I want to configure ntfy settings in the Extension, so that I can control where notifications are sent and enable or disable the feature.

#### Acceptance Criteria

1. THE Extension SHALL provide the following ntfy-related settings fields: ntfy enabled toggle (boolean), ntfy server URL (text, default "https://ntfy.sh"), Urgent_Topic (text, read-only display with copy button), Info_Topic (text, read-only display with copy button), and LAN IP/hostname (text, placeholder "e.g., 192.168.1.100:7432").
2. WHEN the user toggles ntfy enabled to off, THE Notification_Service SHALL stop publishing to ntfy topics and fall back to SMS only (if configured).
3. WHEN the user saves ntfy settings, THE Extension SHALL persist the values to the Automator's configuration store and confirm the save was successful.
4. THE Extension SHALL validate that the ntfy server URL starts with "https://" or "http://" before saving.
5. THE Extension SHALL validate that the LAN IP/hostname field, when provided, contains a valid IPv4 address or hostname with an optional port number.

---

### Requirement 8: SMS Fallback Retention

**User Story:** As a job seeker, I want SMS kept as an optional fallback notification channel, so that I have a backup if ntfy is unavailable or for use with other carriers.

#### Acceptance Criteria

1. WHEN ntfy is enabled and the SMS gateway is also configured, THE Notification_Service SHALL send notifications via ntfy as the primary channel and skip SMS delivery.
2. WHEN ntfy is disabled and the SMS gateway is configured, THE Notification_Service SHALL send notifications via SMS as the sole channel.
3. WHEN both ntfy and SMS are disabled or unconfigured, THE Notification_Service SHALL log a warning and skip notification delivery while still adding items to the Human_Queue.
4. THE Extension SHALL retain the existing SMS gateway address field in Settings alongside the new ntfy settings.
5. IF an ntfy publish attempt fails after all retries, THEN THE Notification_Service SHALL attempt SMS delivery as a fallback (when the SMS gateway is configured).

---

### Requirement 9: Notification Rate Limiting for Ntfy

**User Story:** As a job seeker, I want ntfy notifications rate-limited to 10 per hour, so that I am not overwhelmed by alerts during high-volume runs.

#### Acceptance Criteria

1. THE Notification_Service SHALL enforce a maximum of 10 notifications within any rolling 1-hour window, counting ntfy publishes and SMS sends together in a single shared counter.
2. WHEN the 10-notification limit has been reached within the current hour, THE Notification_Service SHALL skip delivery of additional notifications and log a rate-limit warning.
3. THE Notification_Service SHALL record every notification attempt (sent, failed, or rate-limited) in the notification_log table with a timestamp for rate-limit enforcement.
4. THE rate limit SHALL apply identically regardless of whether the notification is delivered via ntfy or SMS.

---

### Requirement 10: Run History API Endpoint

**User Story:** As a job seeker, I want the Automator to expose run history data via its API, so that the Extension can display it on the Dashboard.

#### Acceptance Criteria

1. THE Automator SHALL expose a `GET /runs/history` endpoint that returns the most recent Run_Summaries (default limit: 5, maximum: 20).
2. EACH Run_Summary in the response SHALL include: a unique run identifier, the run timestamp (ISO 8601), and the summary text.
3. THE `GET /runs/history` endpoint SHALL require bearer token authentication.
4. THE `GET /runs/history` endpoint SHALL accept an optional `limit` query parameter to control the number of results returned.
