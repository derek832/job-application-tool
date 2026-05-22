# Requirements Document

## Introduction

This feature adds a tiered human-in-the-loop escalation system to the external application pipeline. When the Vision Agent encounters obstacles that require human intervention (CAPTCHAs) or high-value jobs that deserve personalized answers (open-ended questions on high-scoring jobs), the system pauses automation, notifies the user via ntfy, and provides a web-based review UI for editing Claude's draft answers before submission. Timeout behavior adapts to job freshness — fresh postings get short timeouts with auto-submit fallback to maximize speed-to-apply, while older postings give the user more time to personalize.

## Glossary

- **Escalation_Engine**: The component that evaluates whether a job application in progress requires human intervention, determines the escalation tier, and manages the pause/resume lifecycle
- **CAPTCHA_Detector**: The subsystem within the Vision Agent that identifies CAPTCHA challenges on external apply forms by detecting known CAPTCHA provider elements (reCAPTCHA, hCaptcha, Cloudflare Turnstile) via DOM inspection or visual recognition
- **Open_Ended_Detector**: The subsystem that classifies form fields as open-ended questions (textarea fields with prompts like "Why are you interested in this role?", "Describe your experience with...", or essay-type questions requiring more than a single sentence)
- **Escalation_Record**: A database record tracking a paused application, including the job ID, escalation tier, form state snapshot, Claude's draft answers, timeout deadline, and resolution status
- **Review_UI**: The web application interface where the user views the pre-filled form state, edits Claude's draft answers, and approves or skips submission
- **Human_Review_Threshold**: A configurable score (stored in the Config table as `human_review_threshold`, default 85) above which jobs with open-ended questions are escalated for human review instead of auto-submitted
- **Freshness_Tier**: A classification of job posting age into three categories: Fresh (less than 24 hours old), Recent (1-7 days old), and Stale (more than 7 days old), derived from the `discovered_at` timestamp compared to the posting date
- **Auto_Submit_Timeout**: The duration after which a paused escalation auto-submits with Claude's draft answers, determined by the Freshness_Tier of the job posting
- **Form_State_Snapshot**: A JSON object capturing the current state of a partially-filled form, including field labels, filled values, unfilled fields, the current page screenshot, and the external URL
- **Draft_Answer**: Claude's generated response to an open-ended question, produced using the user's goals profile, resume, and the job description as context

## Requirements

### Requirement 1: CAPTCHA Detection and Escalation

**User Story:** As a user, I want the system to pause and notify me when it encounters a CAPTCHA on an external apply form, so that I can solve it manually in the connected Chrome session and automation can continue.

#### Acceptance Criteria

1. WHEN the Vision_Agent detects a CAPTCHA element on an external apply form page, THE Escalation_Engine SHALL pause the application process, create an Escalation_Record with tier "captcha", and send a notification to the user via ntfy within 10 seconds of detection
2. WHEN a CAPTCHA escalation notification is sent, THE notification SHALL include the company name, job title, the ATS platform domain, and a direct link to open the Review_UI for that escalation
3. WHILE an application is paused for CAPTCHA resolution, THE Escalation_Engine SHALL NOT set an Auto_Submit_Timeout because CAPTCHAs cannot be bypassed by auto-submission
4. WHEN the user solves the CAPTCHA in the connected Chrome session, THE Escalation_Engine SHALL detect the CAPTCHA resolution by polling the page state every 5 seconds for up to 30 minutes, and resume automation from the point where it was paused
5. IF a CAPTCHA escalation remains unresolved for more than 24 hours, THEN THE Escalation_Engine SHALL mark the Escalation_Record as "expired", transition the job status to "apply_failed" with queue_reason "captcha_timeout", and log the expiration
6. WHEN a CAPTCHA is solved on a given ATS domain, THE Escalation_Engine SHALL record the domain in the session context so that subsequent applications to the same domain during the same browser session do not re-trigger CAPTCHA escalation unless a new CAPTCHA is actually encountered

### Requirement 2: High-Score Open-Ended Question Escalation

**User Story:** As a user, I want high-scoring jobs with open-ended questions to be escalated for my review with Claude's draft answers pre-filled, so that I can personalize responses for roles where my input adds the most value.

#### Acceptance Criteria

1. WHEN the Vision_Agent encounters open-ended form fields AND the job's fit_score is greater than or equal to the Human_Review_Threshold, THE Escalation_Engine SHALL pause the application, generate Draft_Answers for each open-ended field using Claude, and create an Escalation_Record with tier "human_review"
2. WHEN generating Draft_Answers, THE Escalation_Engine SHALL provide Claude with the job description, the user's goals profile, the user's supplementary_context, and the specific question text for each open-ended field, producing answers that are specific to the role and the user's background
3. WHEN a human_review escalation is created, THE Escalation_Engine SHALL capture a Form_State_Snapshot including all field labels and their current values (both auto-filled standard fields and draft open-ended answers), the current page screenshot as a PNG, and the external apply URL
4. WHEN a human_review escalation notification is sent, THE notification SHALL include the job title, company name, fit score, the number of open-ended questions detected, and a direct link to the Review_UI
5. WHEN the job's fit_score is below the Human_Review_Threshold AND open-ended questions are detected, THE Vision_Agent SHALL auto-fill the open-ended fields with Claude's Draft_Answers and proceed with submission without escalation
6. THE Open_Ended_Detector SHALL classify a form field as open-ended when the field is a textarea element or a text input with a character limit above 200 characters, AND the field label or associated prompt text contains question phrasing (interrogative words, phrases requesting description or explanation, or prompts ending with a question mark)

### Requirement 3: Configurable Human Review Threshold

**User Story:** As a user, I want to configure the score threshold that triggers human review escalation, so that I can control how many applications require my attention based on my available time.

#### Acceptance Criteria

1. THE System SHALL store the Human_Review_Threshold as a configuration key `human_review_threshold` in the Config table with a default value of 85
2. WHEN the user updates the Human_Review_Threshold via the settings API, THE System SHALL validate that the new value is an integer between 50 and 100 inclusive
3. WHEN the Human_Review_Threshold is changed, THE Escalation_Engine SHALL use the updated value for all subsequent escalation decisions without requiring a restart
4. THE Settings API SHALL expose the Human_Review_Threshold in the `GET /config/settings` response and accept updates via `PUT /config/settings`
5. WHEN the Human_Review_Threshold is set equal to or below the existing `external_apply_threshold` (default 80), THE System SHALL accept the value but log a warning that most external apply jobs will be escalated for review

### Requirement 4: Freshness-Based Timeout Behavior

**User Story:** As a user, I want timeout behavior to adapt to how fresh a job posting is, so that I don't miss the window on new postings but still have time to personalize answers for older ones.

#### Acceptance Criteria

1. WHEN a human_review escalation is created for a Fresh posting (less than 24 hours old), THE Escalation_Engine SHALL set the Auto_Submit_Timeout to 45 minutes
2. WHEN a human_review escalation is created for a Recent posting (between 24 hours and 7 days old), THE Escalation_Engine SHALL set the Auto_Submit_Timeout to 6 hours
3. WHEN a human_review escalation is created for a Stale posting (more than 7 days old), THE Escalation_Engine SHALL set the Auto_Submit_Timeout to 24 hours
4. WHEN the Auto_Submit_Timeout expires without user action, THE Escalation_Engine SHALL auto-submit the application using Claude's Draft_Answers, mark the Escalation_Record as "auto_submitted", and log the auto-submission with the timeout duration and freshness tier
5. THE Escalation_Engine SHALL determine posting freshness by comparing the current time to the job's `discovered_at` timestamp, using `discovered_at` as a proxy for posting date
6. WHEN the user resolves an escalation before the Auto_Submit_Timeout expires, THE Escalation_Engine SHALL cancel the pending timeout and proceed with the user's chosen action (submit with edits, or skip)

### Requirement 5: Escalation Notification Flow

**User Story:** As a user, I want to receive actionable notifications when an application needs my attention, so that I can quickly decide whether to intervene or let the system auto-submit.

#### Acceptance Criteria

1. WHEN an escalation is created, THE Escalation_Engine SHALL send a notification via the existing ntfy notification service with priority level 4 (high) for CAPTCHA escalations and priority level 3 (default) for human_review escalations
2. WHEN a human_review notification is sent, THE notification body SHALL include: the job title, company name, fit score, number of open-ended questions, the Freshness_Tier label, and the Auto_Submit_Timeout deadline formatted as a relative time (e.g., "auto-submits in 45 min")
3. WHEN a CAPTCHA notification is sent, THE notification body SHALL include: the job title, company name, ATS platform name, and the instruction "Solve CAPTCHA in Chrome to continue"
4. THE notification SHALL include an ntfy action button labeled "Review" that opens the Review_UI URL for the specific Escalation_Record
5. IF the ntfy notification fails to deliver after the standard retry policy (3 attempts), THEN THE Escalation_Engine SHALL fall back to SMS notification using the existing fallback mechanism and log the delivery failure

### Requirement 6: Web App Review UI

**User Story:** As a user, I want to review and edit Claude's draft answers in the web app before submission, so that I can personalize high-value applications without needing to navigate to the ATS form directly.

#### Acceptance Criteria

1. THE Review_UI SHALL display a list of pending Escalation_Records sorted by Auto_Submit_Timeout deadline ascending (most urgent first), showing job title, company, fit score, escalation tier, and time remaining before auto-submit
2. WHEN the user opens a specific Escalation_Record in the Review_UI, THE Review_UI SHALL display the Form_State_Snapshot including: all form field labels and their current values, the page screenshot, and editable text areas for each Draft_Answer
3. WHEN the user edits a Draft_Answer in the Review_UI and clicks "Submit", THE Escalation_Engine SHALL resume the paused application using the user's edited answers in place of the original Draft_Answers, fill the edited values into the form fields, and proceed with submission
4. WHEN the user clicks "Skip" on an Escalation_Record in the Review_UI, THE Escalation_Engine SHALL cancel the application, mark the Escalation_Record as "skipped", and transition the job status to "skipped" with queue_reason "user_skipped_escalation"
5. THE Review_UI SHALL require bearer token authentication consistent with the existing web app authentication mechanism
6. WHEN an Escalation_Record has already been resolved (submitted, auto-submitted, skipped, or expired), THE Review_UI SHALL display the record as read-only with its resolution status and timestamp

### Requirement 7: Escalation Record Lifecycle

**User Story:** As a user, I want escalation records to track the full lifecycle from creation to resolution, so that I can review past escalations and understand system behavior.

#### Acceptance Criteria

1. THE Escalation_Engine SHALL persist each Escalation_Record with the following fields: id (UUID), job_id (foreign key to job_records), tier ("captcha" or "human_review"), form_state_snapshot (JSON), draft_answers (JSON, nullable for CAPTCHA tier), timeout_deadline (ISO 8601 timestamp, nullable for CAPTCHA tier), status ("pending", "resolved", "auto_submitted", "skipped", "expired"), created_at (ISO 8601), resolved_at (ISO 8601, nullable)
2. WHEN an Escalation_Record transitions from "pending" to any terminal status, THE Escalation_Engine SHALL record the resolved_at timestamp and the resolution method
3. THE System SHALL expose escalation records via `GET /escalations` (list pending) and `GET /escalations/{id}` (single record with full form state and draft answers) API endpoints, both requiring bearer token authentication
4. WHEN listing escalation records, THE API SHALL return only records with status "pending" by default, with an optional query parameter `include_resolved=true` to include all statuses
5. THE Escalation_Engine SHALL enforce that only one Escalation_Record with status "pending" can exist per job_id at any time

### Requirement 8: Automation Resume After Resolution

**User Story:** As a user, I want automation to seamlessly resume after I resolve an escalation, so that the application is completed without requiring me to interact with the ATS form directly.

#### Acceptance Criteria

1. WHEN a CAPTCHA escalation is resolved (CAPTCHA solved), THE Escalation_Engine SHALL instruct the Vision_Agent to continue form filling from the current page state, re-identifying fields and resuming the fill sequence from where it was paused
2. WHEN a human_review escalation is resolved with user edits, THE Escalation_Engine SHALL instruct the Vision_Agent to navigate back to the form (using the stored external URL), re-fill all fields using the Form_State_Snapshot values combined with the user's edited answers, and proceed to submission
3. IF the form page has changed or expired between escalation creation and resolution (detected by page load failure or form structure mismatch), THEN THE Escalation_Engine SHALL mark the Escalation_Record as "expired", transition the job to "apply_failed" with error_message "Form expired during escalation", and notify the user
4. WHEN auto-submission occurs after timeout expiry, THE Escalation_Engine SHALL use the same resume mechanism as user-resolved submissions, filling Draft_Answers into the form and clicking submit
5. WHEN the Vision_Agent encounters an error during the resume process (navigation failure, field mismatch, or submission error), THE Escalation_Engine SHALL mark the Escalation_Record as "expired", transition the job to "apply_failed", and log the error details

