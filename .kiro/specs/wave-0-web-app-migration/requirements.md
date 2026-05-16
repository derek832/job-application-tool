# Requirements Document

## Introduction

Wave 0 replaces the Chrome Extension control panel with a standalone React web application served by an nginx container within Docker Compose. After this migration, the user accesses the same Dashboard, Human Queue, Job History, Search Config, Goals Profile, Profile Config, and Settings views through a standard browser tab at a local URL. The Chrome Extension is fully removed from the project. The FastAPI Automator backend remains unchanged — same endpoints, same authentication, same behavior. The user experience goal is zero-friction: `docker compose up` starts both the backend and the frontend, and the web app is immediately usable.

---

## Glossary

- **Web_App**: The React single-page application that replaces the Chrome Extension as the user-facing control panel.
- **Frontend_Container**: The nginx Docker service that serves the Web_App static files and proxies API requests to the Automator.
- **Automator**: The existing FastAPI backend service running in Docker that exposes the REST API on port 7432.
- **SPA**: Single-Page Application — a web application that loads a single HTML page and dynamically updates content without full page reloads.
- **Reverse_Proxy**: The nginx configuration that forwards requests matching `/api/*` from the Frontend_Container to the Automator container.
- **Bearer_Token**: The shared secret used to authenticate all API requests between the Web_App and the Automator.
- **Badge_Indicator**: A visual notification in the browser tab (title prefix or favicon) showing the count of pending Human Queue items.
- **Polling_Interval**: The time period between automatic background requests to refresh data from the Automator API.

---

## Requirements

### Requirement 1: Docker Compose Frontend Service

**User Story:** As a user, I want the web app to start automatically when I run `docker compose up`, so that I don't need to install or configure anything beyond Docker.

#### Acceptance Criteria

1. THE Docker Compose configuration SHALL define a second service named `frontend` that runs an nginx container serving the Web_App.
2. THE Frontend_Container SHALL expose port 3000 on localhost (127.0.0.1:3000) and SHALL NOT bind to external network interfaces.
3. WHEN `docker compose up` is executed, THE Frontend_Container SHALL start alongside the Automator service without requiring additional user commands.
4. THE Frontend_Container SHALL use an official nginx base image with a pinned version tag.
5. THE Frontend_Container SHALL run as a non-root user inside the container.
6. THE Docker Compose configuration SHALL define a dependency so that the Frontend_Container starts after the Automator service is available.

---

### Requirement 2: Nginx Reverse Proxy Configuration

**User Story:** As a user, I want the web app to communicate with the backend seamlessly, so that I don't need to configure CORS or know the backend port.

#### Acceptance Criteria

1. THE Frontend_Container SHALL serve all static files (HTML, JS, CSS, assets) from the Web_App build output at the root path (`/`).
2. THE Frontend_Container SHALL proxy all requests matching the path prefix `/api/` to the Automator container on port 7432.
3. WHEN a proxied request is forwarded to the Automator, THE Reverse_Proxy SHALL strip the `/api` prefix so that `/api/status` maps to the Automator's `/status` endpoint.
4. THE Reverse_Proxy SHALL forward the `Authorization` header from the client to the Automator without modification.
5. THE Frontend_Container SHALL return the SPA `index.html` for all non-file, non-API routes to support client-side routing.
6. IF the Automator is unreachable, THEN THE Reverse_Proxy SHALL return an HTTP 502 response to the Web_App.

---

### Requirement 3: Web App SPA Structure

**User Story:** As a user, I want the web app to provide the same pages and navigation as the Chrome Extension, so that my workflow doesn't change.

#### Acceptance Criteria

1. THE Web_App SHALL provide the following views accessible via client-side navigation: Dashboard, Human Queue, Job History, Search Config, Goals Profile, Profile Config, and Settings.
2. THE Web_App SHALL use React with functional components and Tailwind CSS for styling, matching the existing extension's technology stack.
3. THE Web_App SHALL be built with Vite and produce static output suitable for serving by nginx.
4. THE Web_App source code SHALL reside in a `webapp/` directory at the project root, separate from the removed `extension/` directory.
5. THE Web_App SHALL include a persistent navigation element allowing the user to switch between all views without a full page reload.

---

### Requirement 4: API Client Migration

**User Story:** As a developer, I want the API client to work identically in the web app context, so that all backend communication continues to function without changes to the Automator.

#### Acceptance Criteria

1. THE Web_App API client SHALL send all requests to the relative path `/api/` (proxied by nginx) instead of the absolute URL `http://127.0.0.1:7432`.
2. THE Web_App API client SHALL include the Bearer_Token in the `Authorization` header of every request to the Automator.
3. THE Web_App API client SHALL validate all API responses using Zod schemas, preserving the same validation logic as the extension client.
4. WHEN the Automator returns an error response, THE Web_App API client SHALL surface a typed error object containing the HTTP status code and detail message.
5. WHEN the Automator is unreachable (network error or 502 from nginx), THE Web_App SHALL display a clear connection error state with the last known connection timestamp.

---

### Requirement 5: Authentication Token Storage

**User Story:** As a user, I want to enter my API token once and have it persist across browser sessions, so that I don't need to re-enter it every time I open the web app.

#### Acceptance Criteria

1. THE Web_App SHALL store the Bearer_Token in the browser's localStorage under a defined key.
2. WHEN the user enters a token in the Settings view and saves it, THE Web_App SHALL persist the token to localStorage immediately.
3. WHEN the Web_App loads, THE Web_App SHALL read the Bearer_Token from localStorage and use it for all subsequent API requests.
4. IF no Bearer_Token is found in localStorage on load, THEN THE Web_App SHALL display a prompt directing the user to enter a token in Settings before other views become functional.
5. THE Web_App SHALL NOT transmit the Bearer_Token to any destination other than the local Automator via the nginx proxy.

---

### Requirement 6: Background Polling and Badge Indicator

**User Story:** As a user, I want to see at a glance how many items need my attention, so that I know when to check the Human Queue without manually navigating to it.

#### Acceptance Criteria

1. THE Web_App SHALL poll the Automator's queue endpoint at a Polling_Interval of 60 seconds to retrieve the count of pending Human Queue items.
2. WHEN the pending queue count is greater than zero, THE Web_App SHALL update the browser tab title to include the count as a prefix (e.g., `(3) Job Application Tool`).
3. WHEN the pending queue count is zero, THE Web_App SHALL display the default tab title without a count prefix.
4. THE Web_App SHALL use `setInterval` for the Polling_Interval, replacing the Chrome Extension's `chrome.alarms` API.
5. WHEN the Web_App tab is closed or navigated away from, THE polling interval SHALL be cleared to avoid unnecessary background requests.

---

### Requirement 7: Chrome Extension Removal

**User Story:** As a developer, I want the Chrome Extension fully removed from the project, so that there is a single interface and no maintenance burden for deprecated code.

#### Acceptance Criteria

1. THE project SHALL NOT contain the `extension/` directory or any Chrome Extension source files after migration.
2. THE project SHALL NOT reference Chrome Extension APIs (`chrome.storage`, `chrome.alarms`, `chrome.action`, `chrome.sidePanel`, `chrome.runtime`) in any active source code.
3. THE `manifest.json` file for the Chrome Extension SHALL be removed from the project.
4. THE project documentation (README, setup guides) SHALL reference the Web_App as the sole user interface and SHALL NOT reference the Chrome Extension.

---

### Requirement 8: Web App Build and Deployment in Docker

**User Story:** As a user, I want the web app to be pre-built inside the Docker image, so that I never need Node.js installed on my machine.

#### Acceptance Criteria

1. THE Frontend_Container SHALL use a multi-stage Docker build: a Node.js stage to build the Web_App, and an nginx stage to serve the output.
2. THE Node.js build stage SHALL run `npm ci` to install dependencies from the lockfile, ensuring reproducible builds.
3. THE Node.js build stage SHALL run the Vite production build command to generate optimized static assets.
4. THE final nginx stage SHALL copy only the built static assets from the build stage, keeping the production image minimal.
5. THE final nginx image SHALL NOT contain Node.js, npm, or source code.

---

### Requirement 9: Dashboard View Parity

**User Story:** As a user, I want the web app Dashboard to show the same information as the extension Dashboard, so that I can monitor system status identically.

#### Acceptance Criteria

1. THE Dashboard view SHALL display the current system status (running, paused, idle, or error) with a color-coded indicator.
2. THE Dashboard view SHALL display summary statistics: total discovered, total applied, total skipped, and total pending review.
3. THE Dashboard view SHALL provide a "Run Now" button that triggers an immediate job search run via the API.
4. THE Dashboard view SHALL provide a "Pause / Resume" toggle that stops or resumes scheduled runs via the API.
5. THE Dashboard view SHALL display service health indicators for Claude API, Gmail, and Google Docs connectivity.
6. THE Dashboard view SHALL display the last run timestamp and next scheduled run timestamp.
7. THE Dashboard view SHALL display a recent activity log showing status transitions with timestamps.
8. THE Dashboard view SHALL poll the status endpoint at the Polling_Interval to keep displayed data current.

---

### Requirement 10: Human Queue View Parity

**User Story:** As a user, I want the web app Human Queue to let me approve, reject, or mark jobs as manually applied, so that I can resolve pending items from the web interface.

#### Acceptance Criteria

1. THE Human Queue view SHALL display all pending queue items, each showing: job title, company, LinkedIn URL, reason for escalation, fit score (if available), fit rationale (if available), and timestamp added.
2. THE Human Queue view SHALL provide an "Approve" action for each item that sends an approve request to the API and removes the item from the displayed list on success.
3. THE Human Queue view SHALL provide a "Reject" action for each item that sends a reject request to the API and removes the item from the displayed list on success.
4. THE Human Queue view SHALL provide a "Mark as Applied" action for each item that sends a manual-applied request to the API and removes the item from the displayed list on success.
5. WHEN a queue action fails, THE Human Queue view SHALL display an error message without removing the item from the list.

---

### Requirement 11: Job History View Parity

**User Story:** As a user, I want the web app Job History to show all processed jobs with search and filter capabilities, so that I can review my application history.

#### Acceptance Criteria

1. THE Job History view SHALL display a list of all Job Records retrieved from the API, showing: job title, company, status, fit score, apply type, and discovered date.
2. THE Job History view SHALL provide a text search input that filters jobs by title or company name.
3. THE Job History view SHALL provide a status filter dropdown that limits displayed jobs to a selected status value.
4. THE Job History view SHALL support pagination or infinite scroll for large result sets.
5. WHEN a job entry is selected, THE Job History view SHALL display the full job details including description, fit rationale, tailored resume text, cover letter, application notes, and error messages.

---

### Requirement 12: Configuration Views Parity

**User Story:** As a user, I want the web app to provide the same configuration editors as the extension, so that I can manage Search Config, Goals Profile, Profile Config, and Settings from the browser.

#### Acceptance Criteria

1. THE Search Config view SHALL provide an editor for: keywords, search queries list, location, job type, experience level, and remote preference, and SHALL save changes to the Automator via the API.
2. THE Goals Profile view SHALL provide an editor for: target titles, industries, company sizes, geographic preferences, minimum salary, deal-breaker keywords, openness to stretch roles, career objective, and supplementary context, and SHALL save changes to the Automator via the API.
3. THE Profile Config view SHALL provide an editor for: full name, email, phone, location, work authorization, LinkedIn URL, and common application answers (key-value pairs), and SHALL save changes to the Automator via the API.
4. THE Settings view SHALL provide fields for: Claude API key, Gmail user, SMS gateway, Google Docs script URL, good-fit threshold, stretch threshold, external apply threshold, skip viewed jobs toggle, dry run toggle, and backup directory, and SHALL save changes to the Automator via the API.
5. THE Settings view SHALL provide a separate section for entering and saving the Bearer_Token to localStorage.
6. WHEN any configuration save succeeds, THE Web_App SHALL display a brief success confirmation to the user.
7. WHEN any configuration save fails, THE Web_App SHALL display the error message returned by the API.

---

### Requirement 13: Connection State Handling

**User Story:** As a user, I want to clearly see when the backend is unreachable, so that I know the system isn't running and can take action.

#### Acceptance Criteria

1. WHEN the Web_App cannot reach the Automator (network error or HTTP 502), THE Web_App SHALL display a connection error banner visible across all views.
2. THE connection error banner SHALL show the last successful connection timestamp if one exists.
3. WHEN the Automator becomes reachable again (next successful poll or API call), THE Web_App SHALL automatically dismiss the connection error banner.
4. THE Web_App SHALL store the connection state (connected/disconnected, last connected timestamp, last error message) in component state, replacing the Chrome Extension's use of `chrome.storage.local` for connection tracking.

---

### Requirement 14: Extension-Specific API Replacement

**User Story:** As a developer, I want all Chrome Extension APIs replaced with standard web equivalents, so that the web app runs in any modern browser without extensions.

#### Acceptance Criteria

1. THE Web_App SHALL use `localStorage` for token persistence, replacing `chrome.storage.local`.
2. THE Web_App SHALL use `setInterval` for periodic polling, replacing `chrome.alarms`.
3. THE Web_App SHALL use browser tab title updates for the badge indicator, replacing `chrome.action.setBadgeText`.
4. THE Web_App SHALL render as a standard browser page, replacing the Chrome Extension's side panel (`chrome.sidePanel`) presentation.
5. THE Web_App SHALL NOT depend on any browser extension APIs or require any browser extension to be installed.
