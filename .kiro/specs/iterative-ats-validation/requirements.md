# Requirements Document

## Introduction

This spec defines the success criteria and iterative workflow for agent-driven validation of the job application tool's core automation features. There is no test harness to build — Kiro (the AI agent) IS the validation runner. When the user clicks "Run All Tasks," Kiro autonomously executes the existing pipeline code against real sites using a real browser, observes results via Docker logs and page state, diagnoses failures, patches the code, cleans up, and re-runs until all features pass on all target platforms.

## Glossary

- **Kiro_Agent**: The AI agent executing spec tasks — it runs the pipeline, reads logs, diagnoses failures, fixes code, and re-verifies
- **Vision_Agent**: The existing DOM-based form filling agent (vision_agent.py) that handles external ATS applications
- **Easy_Apply_Stage**: The existing LinkedIn Easy Apply automation module (easy_apply_stage.py)
- **ATS_Registration_Handler**: The existing module that detects and handles account creation/login on external ATS platforms (ats_registration.py)
- **LinkedIn_Scraper**: The existing module that handles job discovery and pagination (linkedin_scraper.py)
- **Pipeline**: The full job pipeline (job_pipeline.py) that orchestrates discovery, scoring, tailoring, and application
- **Fix_Cycle**: One iteration of the run → diagnose → fix → cleanup → re-verify loop
- **Code_Cleanup**: Removal of dead code, moving inline imports to top-level, resolving lint warnings, and ensuring consistent style after a fix
- **Target_Platform**: One of the ATS platforms that must pass validation (Greenhouse, Lever, Workday, iCIMS, BambooHR)
- **Target_URL**: A real job posting URL on a specific Target_Platform used as a validation target during task execution
- **Docker_Logs**: The structured log output from the automator container, observable via `docker compose logs automator`
- **Page_State**: The browser DOM state after an action, used to verify success beyond log messages
- **Completion_Gate**: The condition under which the spec is considered done — all features pass on all target platforms with clean code

## Requirements

### Requirement 1: Easy Apply Success Criteria

**User Story:** As a user, I want the Easy Apply automation to successfully submit applications through LinkedIn's multi-step modal, so that jobs marked "easy_apply" are applied to without manual intervention.

#### Acceptance Criteria

1. WHEN the Kiro_Agent runs Easy_Apply_Stage against a LinkedIn job with Easy Apply, THE Easy_Apply_Stage SHALL click the Easy Apply button and the application modal SHALL appear within 10 seconds
2. WHEN the Easy Apply modal is open, THE Easy_Apply_Stage SHALL fill all empty standard fields (name, email, phone, location) from the user profile, skipping fields that LinkedIn has pre-populated
3. WHEN a resume upload field is present in the modal, THE Easy_Apply_Stage SHALL attach the tailored resume PDF from the job record
4. WHEN the modal presents a multi-step form, THE Easy_Apply_Stage SHALL navigate through steps using Next and Review buttons until reaching Submit, up to a maximum of 10 steps
5. WHEN the Submit button is clicked, THE Easy_Apply_Stage SHALL detect the submission confirmation (success message or modal closure) within 10 seconds and the Docker_Logs SHALL contain a structured entry with event "easy_apply_submitted"
6. IF an unanswered question is encountered that cannot be mapped to the user profile or common answers, THEN THE Easy_Apply_Stage SHALL dismiss the modal, log the unmapped field label, and mark the job as "apply_failed" with the unanswered question recorded
7. IF no Next, Review, or Submit button is found on a form step, THEN THE Easy_Apply_Stage SHALL raise an error indicating an unexpected modal state, and the Docker_Logs SHALL contain the error details

### Requirement 2: External Apply (Vision Agent) Success Criteria

**User Story:** As a user, I want the Vision Agent to successfully fill and submit application forms on Greenhouse, Lever, Workday, iCIMS, and BambooHR, so that external applications are completed without manual intervention.

#### Acceptance Criteria

1. WHEN the Kiro_Agent runs Vision_Agent against a Greenhouse Target_URL, THE Vision_Agent SHALL navigate to the form, identify and fill all required fields from the user profile, and reach a submission confirmation state (confirmation message, redirect URL, or thank-you page content)
2. WHEN the Kiro_Agent runs Vision_Agent against a Lever Target_URL, THE Vision_Agent SHALL navigate to the form, identify and fill all required fields from the user profile, and reach a submission confirmation state
3. WHEN the Kiro_Agent runs Vision_Agent against a Workday Target_URL, THE Vision_Agent SHALL navigate to the form, detect multi-page structure if present, and fill required fields on each page sequentially until reaching submission confirmation or an escalation condition; IF the form is a single-page form with no multi-page structure detected, THE Vision_Agent SHALL proceed to fill the fields and complete the submission
4. WHEN the Kiro_Agent runs Vision_Agent against an iCIMS Target_URL, THE Vision_Agent SHALL navigate to the form, identify and fill all required fields from the user profile, and reach a submission confirmation state
5. WHEN the Kiro_Agent runs Vision_Agent against a BambooHR Target_URL, THE Vision_Agent SHALL navigate to the form, identify and fill all required fields from the user profile, and reach a submission confirmation state
6. IF the Vision_Agent encounters a CAPTCHA or more than 3 pages on any platform, THEN THE Vision_Agent SHALL stop form filling, log the escalation reason, and the Docker_Logs SHALL contain a structured entry with the reason and platform domain
7. IF the Vision_Agent encounters a shadow DOM or custom React component that prevents field identification, THEN THE Vision_Agent SHALL log the element tag name, attempted selectors, and platform domain
8. IF the Vision_Agent encounters a drag-and-drop file upload without a standard file input element, THEN THE Vision_Agent SHALL attempt to locate a hidden file input as a fallback and, if none is found within 10 seconds, log the unsupported upload mechanism

### Requirement 3: ATS Account Creation Success Criteria

**User Story:** As a user, I want the ATS registration handler to correctly detect login/registration pages, create accounts, and handle email verification, so that external apply can proceed on sites requiring authentication.

#### Acceptance Criteria

1. WHEN the ATS_Registration_Handler encounters a page with registration indicators (text matching "create account", "sign up", "register", or "new user"), THE ATS_Registration_Handler SHALL detect the page type as "registration" and the Docker_Logs SHALL contain a "detected_registration_page" entry
2. WHEN the ATS_Registration_Handler encounters a page with Google OAuth indicators (text matching "sign in with Google" or "continue with Google"), THE ATS_Registration_Handler SHALL click the OAuth button and wait up to 30 seconds for the redirect to complete
3. WHEN a registration form is detected, THE ATS_Registration_Handler SHALL generate a password of at least 16 characters, fill the email, password, confirm-password, and name fields from the user profile, and submit the form
4. WHEN a verification email is expected after registration, THE ATS_Registration_Handler SHALL poll the Gmail API at 5-second intervals for a verification link within 60 seconds, and navigate to the extracted verification URL upon receipt
5. IF stored credentials exist in the database for the current ATS domain and user email, THEN THE ATS_Registration_Handler SHALL use the stored credentials to log in rather than creating a new account
6. IF registration fails because no form fields could be filled, THEN THE ATS_Registration_Handler SHALL log the page URL and the list of detected form field labels, and the Docker_Logs SHALL contain a "registration_no_fields_filled" entry
7. IF the Google OAuth flow fails to complete within 30 seconds, THEN THE ATS_Registration_Handler SHALL fall back to standard registration if a registration form is available on the page

### Requirement 4: LinkedIn Pagination Success Criteria

**User Story:** As a user, I want LinkedIn job discovery to correctly paginate beyond page 1, so that the tool finds all available jobs matching my search criteria rather than stopping at 25 results.

#### Acceptance Criteria

1. WHEN a LinkedIn search returns multiple pages of results, THE LinkedIn_Scraper SHALL navigate to page 2 and continue paginating up to the configured max_pages limit, waiting no longer than 15 seconds for each page to load
2. WHEN the pagination Next button selector does not match the current LinkedIn DOM, THE LinkedIn_Scraper SHALL log the mismatch with the expected and actual DOM structure, and the Docker_Logs SHALL contain a "pagination_container_found_but_no_next_button" entry with an HTML snippet
3. WHEN pagination succeeds on any page beyond page 1, THE LinkedIn_Scraper SHALL discover job URLs on that page that are not present in the set of job URLs discovered on previous pages, and this postcondition SHALL apply throughout the entire pagination process from page 2 onwards
4. IF pagination fails due to a navigation timeout or missing Next button on a non-final page, THEN THE LinkedIn_Scraper SHALL capture a debug screenshot to data/debug_pagination.png for the Kiro_Agent to inspect
5. IF the LinkedIn_Scraper reaches a page where no Next button is present and the button is disabled, THEN THE LinkedIn_Scraper SHALL treat this as the final page and stop pagination without reporting an error

### Requirement 5: Agent Observation Method

**User Story:** As a user, I want Kiro to verify success by reading Docker logs and inspecting page state, so that validation is based on actual outcomes rather than assumptions.

#### Acceptance Criteria

1. WHEN the Kiro_Agent runs a feature against a Target_URL, THE Kiro_Agent SHALL observe the outcome by reading Docker_Logs via `docker compose logs automator --tail=100`
2. WHEN a feature execution completes, THE Kiro_Agent SHALL verify success by confirming the Docker_Logs contain structured log entries indicating successful completion (e.g., "easy_apply_submitted", "external_apply_success", "registration_submitted", "discovery_job_extracted")
3. WHEN the Docker_Logs indicate a failure, THE Kiro_Agent SHALL identify the error category from the log entry (selector mismatch, timeout, missing field mapping, authentication failure, navigation failure, or platform-specific quirk)
4. WHEN a screenshot has been captured by the pipeline code (e.g., debug_pagination.png, debug_extraction_*.png), THE Kiro_Agent SHALL inspect the screenshot to diagnose DOM structure issues
5. IF the Docker_Logs report success but the Kiro_Agent has reason to doubt (e.g., suspiciously fast completion or missing expected log entries), THEN THE Kiro_Agent SHALL always re-run the feature with additional logging to confirm the result, regardless of rate limits, resource constraints, or time-sensitive operations

### Requirement 6: Iterative Fix Cycle

**User Story:** As a user, I want Kiro to autonomously loop through test-diagnose-fix-cleanup-verify until everything works, so that I press go once and come back to working code.

#### Acceptance Criteria

1. WHEN the Kiro_Agent identifies a failure from Docker_Logs, THE Kiro_Agent SHALL diagnose the root cause by reading the relevant source file, correlating the error with the code path, and identifying the specific line or selector that failed
2. WHEN the Kiro_Agent diagnoses a root cause, THE Kiro_Agent SHALL patch the relevant source file with a targeted fix and the fix SHALL address the diagnosed root cause without introducing unrelated changes
3. WHEN a fix is applied, THE Kiro_Agent SHALL re-run the same feature against the same Target_URL to verify the fix resolved the failure; WHEN the re-run succeeds, THE Kiro_Agent SHALL automatically mark the targeted fix as applied (targeted_fix_applied = true), tying fix tracking directly to verification results
4. IF a fix does not resolve the failure after 2 attempts at the same root cause, THEN THE Kiro_Agent SHALL step back, re-diagnose from scratch using a different approach, and document what was tried; IF the Kiro_Agent cannot identify any root cause initially, THEN THE Kiro_Agent SHALL attempt a different diagnostic approach (e.g., adding verbose logging, inspecting page state, or comparing against known-good behavior) before giving up
5. WHEN a fix is verified as successful, THE Kiro_Agent SHALL proceed to the next failing feature or platform before performing Code_Cleanup
6. WHEN all features pass on all target platforms, THE Kiro_Agent SHALL perform a final Code_Cleanup pass across all modified files

### Requirement 7: Code Cleanup After Fixes

**User Story:** As a user, I want the codebase to stay clean throughout the fix process, so that I don't inherit technical debt from the debugging session.

#### Acceptance Criteria

1. WHEN the Kiro_Agent performs Code_Cleanup, THE Kiro_Agent SHALL move inline imports to top-level module imports in all modified files
2. WHEN the Kiro_Agent performs Code_Cleanup, THE Kiro_Agent SHALL remove dead code (unused functions, unreachable branches, commented-out code) from all modified files
3. WHEN the Kiro_Agent performs Code_Cleanup, THE Kiro_Agent SHALL run `ruff check --fix` and `ruff format` on all modified Python files and resolve any remaining lint violations
4. WHEN the Kiro_Agent performs Code_Cleanup, THE Kiro_Agent SHALL ensure all modified functions have type annotations and docstrings consistent with the existing codebase style
5. AFTER Code_Cleanup is complete, THE Kiro_Agent SHALL re-run all features one final time to confirm cleanup did not introduce regressions

### Requirement 8: Completion Gate

**User Story:** As a user, I want a clear definition of "done" for this spec, so that I know when all validation work is complete and the code is production-ready.

#### Acceptance Criteria

1. THE Kiro_Agent SHALL consider the spec complete WHEN Easy_Apply_Stage successfully submits at least 1 application through LinkedIn's Easy Apply modal with confirmation logged
2. THE Kiro_Agent SHALL consider the spec complete WHEN Vision_Agent successfully submits or reaches confirmation state on at least 1 Target_URL for each of the 5 Target_Platforms (Greenhouse, Lever, Workday, iCIMS, BambooHR)
3. THE Kiro_Agent SHALL consider the spec complete WHEN ATS_Registration_Handler successfully detects and handles at least 1 registration or login flow on a real ATS site
4. THE Kiro_Agent SHALL consider the spec complete WHEN LinkedIn_Scraper successfully paginates beyond page 1 and discovers jobs from at least 2 pages
5. THE Kiro_Agent SHALL consider the spec complete WHEN all modified files pass `ruff check` and `ruff format --check` with zero warnings
6. THE Kiro_Agent SHALL consider the spec complete WHEN a final full validation run (all features, all platforms) passes with no failures after Code_Cleanup
7. IF any Target_Platform is unreachable due to all Target_URLs being stale (job postings closed), THEN THE Kiro_Agent SHALL attempt to find a fresh Target_URL for that platform up to 3 times; IF no fresh URL can be found after 3 attempts, THEN THE Kiro_Agent SHALL document the platform as temporarily unavailable and allow the spec to complete for the remaining platforms

### Requirement 9: Target URL Selection

**User Story:** As a user, I want Kiro to use real job posting URLs for validation, so that testing happens against actual ATS behavior rather than mocked environments.

#### Acceptance Criteria

1. WHEN the Kiro_Agent begins validation for a Target_Platform, THE Kiro_Agent SHALL locate a real, active job posting URL on that platform by searching LinkedIn for external apply jobs or by navigating directly to the platform's job board
2. WHEN the Kiro_Agent selects a Target_URL, THE Kiro_Agent SHALL verify the URL is active by confirming the page loads without a 404, 410, or "job closed" indicator
3. IF a Target_URL becomes stale during the validation process (job posting closed between runs), THEN THE Kiro_Agent SHALL find a replacement Target_URL for the same platform and continue validation
4. THE Kiro_Agent SHALL prefer Target_URLs with simple application forms (at least 1 application page but fewer than 5 pages, no CAPTCHA) for initial validation, skipping zero-page postings (external redirects or email-only contacts), and escalating to complex forms only after simple forms pass
5. THE Kiro_Agent SHALL document each Target_URL used and its platform in the task execution log so results are reproducible
