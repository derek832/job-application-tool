# Requirements Document

## Introduction

The New User Experience feature replaces the current manual setup process (SETUP_GUIDE.md) with an in-app guided wizard, first-run gating, and integrated troubleshooting. The goal is to make a non-technical user fully operational without reading documentation, terminal commands, or understanding Docker internals. The web app at `http://127.0.0.1:3000` becomes self-sufficient for configuration and diagnostics.

## Glossary

- **Setup_Wizard**: A 6-step sequential UI flow that collects and validates all required configuration before granting access to the main application.
- **Wizard_Step**: A single screen within the Setup_Wizard that collects one category of configuration and validates it before allowing progression.
- **Validation_Endpoint**: A backend API route that performs a live connectivity or data-completeness check for a specific configuration item and returns a pass/fail result with an error message.
- **First_Run_Gate**: The mechanism that detects unconfigured state on app load and renders the Setup_Wizard as the only available UI path.
- **Diagnostics_Page**: A dedicated page in the web app that runs individual service checks and displays remediation guidance.
- **Health_Check**: The existing `GET /health` endpoint that tests connectivity to Claude API, Gmail, and Google Apps Script.
- **Remediation_Guidance**: Plain-English instructions shown to the user explaining what is wrong and how to fix it, without requiring technical knowledge.
- **Web_App**: The React + Tailwind + Vite single-page application served by nginx at `http://127.0.0.1:3000`.
- **Automator**: The FastAPI backend service that manages the job pipeline, configuration, and external service connectivity.

## Requirements

### Requirement 1: Setup Wizard Flow Control

**User Story:** As a new user, I want a guided step-by-step wizard so that I can configure the tool without reading documentation or using a terminal.

#### Acceptance Criteria

1.1. THE Setup_Wizard SHALL present exactly 6 sequential steps: Claude API Key, Google Apps Script URL, Gmail/Notifications, Profile Info, Goals Profile, and Search Config.

1.2. WHEN a user attempts to advance to the next Wizard_Step, THE Setup_Wizard SHALL invoke the corresponding Validation_Endpoint and block progression until validation passes.

1.3. WHILE a Wizard_Step validation is in progress, THE Setup_Wizard SHALL display a loading indicator and disable the advance button.

1.4. WHEN validation fails for a Wizard_Step, THE Setup_Wizard SHALL display the error message returned by the Validation_Endpoint in plain English below the input fields.

1.5. THE Setup_Wizard SHALL display a progress indicator showing the current step number and total steps (e.g., "Step 3 of 6").

1.6. WHEN a user is on any Wizard_Step after Step 1, THE Setup_Wizard SHALL allow navigation back to any previously completed step without losing entered data.

1.7. WHEN the user completes all 6 steps, THE Setup_Wizard SHALL persist all configuration to the Automator via the existing `PUT /config/*` endpoints.

### Requirement 2: Step 1 — Claude API Key Validation

**User Story:** As a new user, I want to enter my Claude API key and know immediately if it works so that I don't proceed with a broken configuration.

#### Acceptance Criteria

2.1. THE Wizard_Step for Claude API Key SHALL provide a single text input field for the API key.

2.2. WHEN the user submits a Claude API key, THE Automator SHALL make a test API call to the Anthropic models endpoint using the provided key.

2.3. WHEN the test API call returns a non-5xx HTTP response, THE Validation_Endpoint SHALL report success.

2.4. IF the test API call returns a 401 response, THEN THE Validation_Endpoint SHALL report failure with the message "This API key was rejected by Anthropic. Double-check that you copied the full key starting with sk-ant-."

2.5. IF the test API call times out or returns a 5xx response, THEN THE Validation_Endpoint SHALL report failure with the message "Could not reach the Claude API. Check your internet connection and try again."

### Requirement 3: Step 2 — Google Apps Script URL Validation

**User Story:** As a new user, I want to verify my Google Apps Script deployment works so that resume tailoring will function correctly.

#### Acceptance Criteria

3.1. THE Wizard_Step for Google Apps Script URL SHALL provide a single text input field for the deployed web app URL.

3.2. WHEN the user submits a Google Apps Script URL, THE Automator SHALL send an HTTP GET request to the provided URL.

3.3. WHEN the endpoint responds with an HTTP 200 status, THE Validation_Endpoint SHALL report success.

3.4. IF the endpoint returns an HTTP 401 or a JSON body containing an authorization error, THEN THE Validation_Endpoint SHALL report failure with the message "The Apps Script isn't authorized yet. Open the URL in your browser, click 'Review Permissions', and grant access."

3.5. IF the endpoint is unreachable or times out, THEN THE Validation_Endpoint SHALL report failure with the message "Could not reach your Apps Script URL. Make sure you copied the full URL ending in /exec."

### Requirement 4: Step 3 — Gmail/Notifications Validation

**User Story:** As a new user, I want to confirm my Gmail OAuth token is working so that I receive text notifications when the tool needs my attention.

#### Acceptance Criteria

4.1. THE Wizard_Step for Gmail/Notifications SHALL display the currently configured Gmail address (if any) and the status of the OAuth token.

4.2. WHEN the user triggers validation, THE Automator SHALL verify that the Gmail OAuth token file exists and is not expired by attempting a Gmail API authentication check.

4.3. WHEN the OAuth token is valid and the Gmail API responds successfully, THE Validation_Endpoint SHALL report success.

4.4. IF the OAuth token file does not exist, THEN THE Validation_Endpoint SHALL report failure with the message "Gmail isn't authorized yet. Run the authorization script: open a terminal, navigate to the automator folder, and run 'python authorize_gmail.py'."

4.5. IF the OAuth token exists but is expired or revoked, THEN THE Validation_Endpoint SHALL report failure with the message "Your Gmail authorization has expired. Run 'python authorize_gmail.py' again to refresh it."

### Requirement 5: Step 4 — Profile Info Validation

**User Story:** As a new user, I want to enter my personal details so that the tool can fill out job applications on my behalf.

#### Acceptance Criteria

5.1. THE Wizard_Step for Profile Info SHALL provide input fields for full name, email, phone number, and work authorization status.

5.2. THE Validation_Endpoint SHALL require that full name, email, phone, and work authorization fields are non-empty strings after trimming whitespace.

5.3. IF any required field is empty, THEN THE Validation_Endpoint SHALL report failure listing the specific missing fields in the message.

5.4. WHEN all required fields are non-empty, THE Validation_Endpoint SHALL report success.

### Requirement 6: Step 5 — Goals Profile Validation

**User Story:** As a new user, I want to define my career goals so that the tool knows which jobs to pursue and which to skip.

#### Acceptance Criteria

6.1. THE Wizard_Step for Goals Profile SHALL provide input fields for target titles, deal-breakers, and career objective.

6.2. THE Validation_Endpoint SHALL require at least one target title in the target_titles list.

6.3. THE Validation_Endpoint SHALL require a non-empty career_objective string.

6.4. IF target_titles is empty, THEN THE Validation_Endpoint SHALL report failure with the message "Add at least one target job title so the tool knows what to look for."

6.5. IF career_objective is empty, THEN THE Validation_Endpoint SHALL report failure with the message "Write a brief career objective so the AI understands your goals when scoring jobs."

6.6. WHEN the minimum configuration is met, THE Validation_Endpoint SHALL report success.

### Requirement 7: Step 6 — Search Config Validation

**User Story:** As a new user, I want to configure my job search parameters so that the tool searches for relevant positions.

#### Acceptance Criteria

7.1. THE Wizard_Step for Search Config SHALL provide input fields for search keywords/queries and location.

7.2. THE Validation_Endpoint SHALL require at least one non-empty entry in either the keywords field or the search_queries list.

7.3. IF both keywords and search_queries are empty, THEN THE Validation_Endpoint SHALL report failure with the message "Add at least one search keyword or query so the tool knows what jobs to find."

7.4. WHEN at least one search query is configured, THE Validation_Endpoint SHALL report success.

### Requirement 8: First-Run Gate

**User Story:** As a new user opening the web app for the first time, I want to be guided through setup automatically so that I don't accidentally use an unconfigured tool.

#### Acceptance Criteria

8.1. WHEN the Web_App loads, THE Web_App SHALL query the Automator to determine whether all required configuration is present and valid.

8.2. WHILE the Automator reports that required configuration is missing or invalid, THE Web_App SHALL render the Setup_Wizard as the only accessible UI and block navigation to all other pages.

8.3. WHEN the Automator reports that all required configuration is present and valid, THE Web_App SHALL render the normal application UI (Dashboard, Queue, History, etc.).

8.4. WHEN the Web_App detects that some wizard steps are already configured (e.g., Claude API key already saved from a previous partial setup), THE Setup_Wizard SHALL mark those steps as complete and allow the user to skip directly to the first incomplete step.

8.5. WHEN the user completes the final wizard step, THE Web_App SHALL display a "Setup Complete" celebration screen with a button to proceed to the Dashboard.

### Requirement 9: Setup Completeness Check Endpoint

**User Story:** As the web app, I need a backend endpoint that reports which configuration items are present and valid so that I can determine whether to show the wizard or the main app.

#### Acceptance Criteria

9.1. THE Automator SHALL expose a `GET /setup/status` endpoint that returns the completion state of each wizard step.

9.2. THE `GET /setup/status` endpoint SHALL return a JSON object with a boolean field for each of the 6 wizard steps indicating whether that step's configuration is present and valid.

9.3. THE `GET /setup/status` endpoint SHALL return a top-level `complete` boolean that is true only when all 6 step booleans are true.

9.4. THE `GET /setup/status` endpoint SHALL NOT require authentication so that the Web_App can check setup state before the user has configured a token.

### Requirement 10: Step Validation Endpoints

**User Story:** As the setup wizard, I need backend endpoints that validate individual configuration items with live connectivity checks so that I can confirm each step works before proceeding.

#### Acceptance Criteria

10.1. THE Automator SHALL expose a `POST /setup/validate/{step}` endpoint for each of the 6 wizard steps.

10.2. WHEN called, THE Validation_Endpoint SHALL perform the live check appropriate to the step (API call, HTTP request, file existence check, or field completeness check).

10.3. THE Validation_Endpoint SHALL return a JSON response containing a `valid` boolean and a `message` string.

10.4. WHEN validation passes, THE Validation_Endpoint SHALL return `{"valid": true, "message": ""}`.

10.5. WHEN validation fails, THE Validation_Endpoint SHALL return `{"valid": false, "message": "<plain-English explanation>"}`.

10.6. THE Validation_Endpoint SHALL complete within 10 seconds; IF a connectivity check exceeds this timeout, THEN THE Validation_Endpoint SHALL return a failure response with a timeout-specific message.

### Requirement 11: Dashboard Inline Troubleshooting

**User Story:** As a user whose tool has stopped working, I want to see what's wrong and how to fix it directly on the dashboard so that I don't need to dig through logs or documentation.

#### Acceptance Criteria

11.1. WHEN the Health_Check reports any service as unhealthy, THE Dashboard SHALL display an inline alert banner identifying the failing service.

11.2. THE inline alert banner SHALL include a plain-English description of the problem and a specific remediation action.

11.3. WHEN the Claude API health check fails, THE Dashboard SHALL display the guidance: "Claude API is unreachable. Check your internet connection, or verify your API key in Settings."

11.4. WHEN the Gmail health check fails, THE Dashboard SHALL display the guidance: "Gmail notifications are down. Your OAuth token may have expired — run 'python authorize_gmail.py' in the automator folder to refresh it."

11.5. WHEN the Google Docs health check fails, THE Dashboard SHALL display the guidance: "Google Docs connection failed. Re-deploy your Apps Script and update the URL in Settings."

11.6. WHEN all services are healthy, THE Dashboard SHALL NOT display any troubleshooting banners.

### Requirement 12: Diagnostics Page

**User Story:** As a user experiencing issues, I want a dedicated diagnostics page that checks each service individually and tells me exactly what to fix so that I can resolve problems without technical knowledge.

#### Acceptance Criteria

12.1. THE Web_App SHALL include a Diagnostics page accessible from the main navigation.

12.2. THE Diagnostics_Page SHALL display a "Run Diagnostics" button that triggers individual checks for each configured service.

12.3. WHEN the user clicks "Run Diagnostics", THE Diagnostics_Page SHALL call the Health_Check endpoint and display the result for each service (Claude API, Gmail, Google Docs) as a pass/fail indicator.

12.4. WHEN a service check fails, THE Diagnostics_Page SHALL display a Remediation_Guidance block for that service containing: the service name, the specific error detected, and step-by-step plain-English instructions to resolve the issue.

12.5. WHEN all service checks pass, THE Diagnostics_Page SHALL display a confirmation message: "All systems are working correctly."

12.6. WHILE diagnostics are running, THE Diagnostics_Page SHALL display a loading state for each service being checked.

12.7. THE Diagnostics_Page SHALL allow the user to re-run diagnostics after making fixes without navigating away from the page.
