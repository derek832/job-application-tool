# Requirements Document

## Introduction

Wave 3 — Pipeline Intelligence adds five capabilities that make the job automation pipeline smarter, more reliable, and more configurable: a preview/dry-run mode that lets the user see what the pipeline would do before committing; automatic session health monitoring that catches broken Chrome or LinkedIn sessions before wasting a run; flexible scheduling with multiple run times, intervals, and quiet hours; a company/title blacklist that filters unwanted jobs before they consume Claude tokens; and Chrome CDP setup automation that detects and launches Chrome with remote debugging from the web app.

## Glossary

- **Pipeline**: The sequential job search and application workflow (discovery → scoring → tailoring → apply).
- **Preview_Run**: A pipeline execution mode that performs discovery and scoring but stops before tailoring and application submission.
- **Preview_Result**: A persisted record of a Preview_Run's output including discovered jobs, scores, and projected actions.
- **Session_Health_Check**: An automated verification that Chrome CDP is reachable and the LinkedIn session is authenticated.
- **Scheduler**: The APScheduler instance embedded in the FastAPI Automator that triggers pipeline runs.
- **Blacklist**: User-configured lists of company names and title patterns that cause jobs to be filtered out at discovery time.
- **Quiet_Hours**: A configurable time window during which notifications are queued rather than delivered immediately.
- **CDP**: Chrome DevTools Protocol, used by Playwright to control the user's Chrome browser.
- **Automator**: The FastAPI backend service that orchestrates the pipeline.
- **Web_App**: The React single-page application served at localhost:3000.
- **ntfy**: The push notification service used for user alerts.

## Requirements

### Requirement 1: Preview/Dry-Run Mode

**User Story:** As a user, I want to preview what the pipeline would do without actually applying to jobs, so that I can verify my configuration is working correctly and review candidates before committing.

#### Acceptance Criteria

1. WHEN the user clicks the "Preview Run" button in the Web_App, THE Automator SHALL execute the discovery and scoring stages of the Pipeline without proceeding to the tailoring or application stages.
2. WHEN a Preview_Run completes, THE Automator SHALL persist the Preview_Result (discovered jobs, fit scores, rationales, and projected actions) in the database.
3. THE Web_App SHALL provide a dedicated "Preview Results" view that displays all jobs found during the Preview_Run with their scores, companies, titles, and the action that would be taken (auto-apply, stretch queue, skip).
4. WHEN the user selects one or more jobs from the Preview Results view and clicks "Approve for Apply", THE Automator SHALL transition those jobs to the approved_for_apply status and process them in the next full pipeline run.
5. WHEN a Preview_Run is in progress, THE Web_App SHALL display a status indicator distinguishing it from a full pipeline run.
6. IF a Preview_Run fails due to a Chrome CDP connection error or LinkedIn session issue, THEN THE Automator SHALL record the error in the Preview_Result and notify the user via ntfy.
7. THE Automator SHALL expose a `POST /preview` API endpoint that triggers a Preview_Run and returns immediately with a run identifier.
8. THE Automator SHALL expose a `GET /preview/{run_id}` API endpoint that returns the Preview_Result for a given run.
9. WHEN a Preview_Run discovers jobs that already exist in the database, THE Automator SHALL skip those jobs and include only newly discovered jobs in the Preview_Result.

### Requirement 2: Session Health Monitoring

**User Story:** As a user, I want the system to automatically verify that Chrome and LinkedIn are working before each run, so that I don't waste time on failed runs or miss job opportunities due to expired sessions.

#### Acceptance Criteria

1. WHEN a scheduled or manual pipeline run is about to start, THE Automator SHALL perform a Session_Health_Check before executing any pipeline stages.
2. WHEN performing a Session_Health_Check, THE Automator SHALL verify that Chrome CDP is reachable at the configured remote debugging port.
3. WHEN performing a Session_Health_Check, THE Automator SHALL navigate to a lightweight LinkedIn page and verify that no login redirect occurs, confirming the session is authenticated.
4. IF the Session_Health_Check fails (Chrome unreachable or LinkedIn session expired), THEN THE Automator SHALL skip the pipeline run and send a notification via ntfy indicating which check failed.
5. THE Web_App SHALL display a "Check Session Health" button on the Dashboard that triggers a manual Session_Health_Check.
6. WHEN the user clicks "Check Session Health", THE Automator SHALL perform the Session_Health_Check and return the result within 15 seconds.
7. THE Web_App SHALL display the current session health status on the Dashboard, showing Chrome CDP status and LinkedIn session status as separate indicators.
8. WHEN a Session_Health_Check succeeds, THE Automator SHALL record the timestamp of the last successful check in the system state.
9. IF the Session_Health_Check detects a LinkedIn login redirect, THEN THE Automator SHALL include the message "LinkedIn session expired — please log in to Chrome" in the ntfy notification.

### Requirement 3: Scheduling Flexibility

**User Story:** As a user, I want to configure multiple specific run times or interval-based scheduling with weekend controls and notification quiet hours, so that the pipeline runs when I want it to and notifications arrive at appropriate times.

#### Acceptance Criteria

1. THE Scheduler SHALL support a "specific times" mode where the user configures one or more exact run times (e.g., 9:00 AM, 1:00 PM, 5:00 PM) in the user's local timezone.
2. THE Scheduler SHALL support an "interval" mode where the pipeline runs every N hours within a configurable time window (e.g., every 2 hours between 8:00 AM and 8:00 PM).
3. THE Web_App SHALL provide a scheduling configuration UI that allows the user to choose between "specific times" mode and "interval" mode.
4. THE Scheduler SHALL support a "weekend runs" toggle that enables or disables pipeline runs on Saturday and Sunday.
5. WHEN weekend runs are disabled, THE Scheduler SHALL execute pipeline runs only on Monday through Friday.
6. WHEN weekend runs are enabled, THE Scheduler SHALL execute pipeline runs on all seven days of the week.
7. THE Web_App SHALL provide a "quiet hours" configuration where the user specifies a start time and end time (e.g., 10:00 PM to 7:00 AM).
8. WHILE quiet hours are active, THE Automator SHALL queue notifications rather than delivering them immediately.
9. WHEN quiet hours end, THE Automator SHALL deliver all queued notifications in a single batch summary rather than sending each individually.
10. THE Web_App scheduling UI SHALL display the next three upcoming scheduled run times based on the current configuration.
11. WHEN the user saves a new schedule configuration, THE Scheduler SHALL apply the changes immediately without requiring a restart.
12. IF the user configures zero run times in "specific times" mode, THEN THE Web_App SHALL display a validation error and prevent saving.

### Requirement 4: Company/Title Blacklist

**User Story:** As a user, I want to permanently exclude specific companies and title patterns from my job search, so that I never waste Claude tokens scoring jobs I know I don't want.

#### Acceptance Criteria

1. THE Automator SHALL maintain a configurable list of blacklisted company names stored in the database.
2. THE Automator SHALL maintain a configurable list of blacklisted title patterns (substring matches, case-insensitive) stored in the database.
3. WHEN the Pipeline discovers a job, THE Automator SHALL check the job's company name against the company blacklist before scoring.
4. WHEN the Pipeline discovers a job, THE Automator SHALL check the job's title against the title pattern blacklist before scoring.
5. IF a discovered job matches any entry in the company blacklist (case-insensitive exact match) or the title pattern blacklist (case-insensitive substring match), THEN THE Automator SHALL skip that job with status "skipped" and reason "blacklisted" without sending it to Claude for scoring.
6. THE Web_App SHALL provide a Blacklist configuration page with separate sections for companies and title patterns.
7. WHEN the user adds an entry to the company blacklist, THE Web_App SHALL add it to the list immediately and persist it via the API.
8. WHEN the user removes an entry from the company blacklist or title pattern list, THE Web_App SHALL remove it immediately and persist the change via the API.
9. THE Web_App blacklist UI SHALL display the current count of jobs that have been filtered by each blacklist entry.
10. THE Automator SHALL expose `GET /config/blacklist` and `PUT /config/blacklist` API endpoints for reading and updating both blacklists.
11. WHEN a job is skipped due to a blacklist match, THE Automator SHALL log the skip reason including which blacklist entry matched.

### Requirement 5: Chrome CDP Setup Automation

**User Story:** As a user, I want the web app to detect whether Chrome is running with remote debugging and offer a one-click launch if it isn't, so that I don't have to remember command-line flags.

#### Acceptance Criteria

1. THE Automator SHALL expose a `GET /chrome/status` API endpoint that checks whether Chrome is running with remote debugging on port 9222 and returns the connection status.
2. WHEN Chrome is not reachable on port 9222, THE Web_App SHALL display a "Launch Chrome for Automation" button on the Dashboard.
3. WHEN the user clicks "Launch Chrome for Automation", THE Automator SHALL start a Chrome process with the flags `--remote-debugging-port=9222` and a separate `--user-data-dir` dedicated to automation.
4. WHEN launching Chrome for automation, THE Automator SHALL use a user-data-dir that is separate from the user's default Chrome profile, ensuring existing Chrome windows and normal browsing are unaffected.
5. WHEN Chrome is successfully running with remote debugging, THE Web_App SHALL display a green status indicator on the Dashboard showing "Chrome Connected".
6. WHEN Chrome is not reachable, THE Web_App SHALL display a red status indicator on the Dashboard showing "Chrome Not Connected".
7. THE Automator SHALL expose a `POST /chrome/launch` API endpoint that starts Chrome with the required remote debugging flags.
8. IF Chrome is already running with remote debugging when the user clicks "Launch Chrome for Automation", THEN THE Automator SHALL return a success response without launching a duplicate process.
9. WHEN the `GET /chrome/status` endpoint is called, THE Automator SHALL respond within 3 seconds with the current Chrome CDP reachability status.
