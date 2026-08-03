"""
Pydantic v2 request/response schemas for the LinkedIn Job Automator API.

All configuration schemas, job record outputs, queue items, stats, and system
status/health responses are defined here. Secret fields in Settings serialize
to "***" via a custom field_serializer to prevent credential leakage.
"""

from __future__ import annotations

import json
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration schemas (used for both GET responses and PUT request bodies)
# ---------------------------------------------------------------------------


class SearchConfig(BaseModel):
    """LinkedIn search parameters.

    Supports multiple keyword queries per cycle. If ``search_queries`` is
    populated, each query string is run as a separate LinkedIn search during
    the same pipeline cycle. The legacy ``keywords`` field is used as a
    fallback when ``search_queries`` is empty.

    Attributes:
        keywords: Single search keywords string (legacy, used if search_queries is empty).
        search_queries: List of keyword query strings to run each cycle.
        location: Geographic location filter.
        job_type: Employment type filter.
        experience_level: Seniority level filter.
        remote_pref: Remote work preference filter.
    """

    model_config = ConfigDict(strict=False)

    keywords: str | None = None
    search_queries: list[str] = []
    location: str | None = None
    job_type: str | None = None
    experience_level: str | None = None
    remote_pref: str | None = None
    time_range: str | None = None
    sort_by: str | None = None

    @field_validator("search_queries", mode="before")
    @classmethod
    def coerce_search_queries(cls, v: list[str] | None) -> list[str]:
        """Coerce None to empty list for backward compatibility with stored configs."""
        if v is None:
            return []
        return v

    def get_keyword_list(self) -> list[str]:
        """Return the list of keyword queries to execute this cycle.

        If ``search_queries`` is populated, returns that list. Otherwise falls
        back to the single ``keywords`` field wrapped in a list. Returns an
        empty list if neither is configured.
        """
        if self.search_queries:
            return self.search_queries
        if self.keywords:
            return [self.keywords]
        return []


class GoalsProfile(BaseModel):
    """Career goals and job-seeking preferences.

    Attributes:
        target_titles: List of desired job titles.
        industries: Preferred industries.
        company_sizes: Preferred company size categories.
        geo_prefs: Geographic preferences.
        min_salary: Minimum acceptable salary (optional).
        deal_breakers: Keywords that disqualify a job regardless of fit score.
        open_to_stretch: Whether the user is open to stretch roles.
        career_objective: Free-text career objective statement.
        supplementary_context: Additional experience notes, project details, or
            weekly work notes passed to Claude alongside the resume during scoring
            and tailoring. Keeps the resume clean for PDF export while giving
            Claude richer context for matching and keyword optimization.
    """

    model_config = ConfigDict(strict=False)

    target_titles: list[str] = []
    industries: list[str] = []
    company_sizes: list[str] = []
    geo_prefs: list[str] = []
    min_salary: int | None = None
    deal_breakers: list[str] = []
    open_to_stretch: bool = True
    career_objective: str | None = None
    supplementary_context: str | None = None


class UserProfile(BaseModel):
    """Personal application data used to fill forms.

    Attributes:
        full_name: User's full legal name.
        email: Contact email address.
        phone: Contact phone number.
        location: User's current location.
        work_auth: Work authorization status.
        linkedin_url: User's LinkedIn profile URL.
        common_answers: Pre-filled answers to common application questions.
    """

    model_config = ConfigDict(strict=False)

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    work_auth: str | None = None
    linkedin_url: str | None = None
    common_answers: dict[str, str] = {}


class Settings(BaseModel):
    """System settings including secrets and operational thresholds.

    Secret fields (claude_api_key) serialize to "***" in API responses to
    prevent credential leakage. Gmail authentication uses OAuth2 (token stored
    on disk), so no password field is needed.

    The pipeline schedule is fixed at Mon-Fri 8AM-8PM Eastern and is not
    configurable.

    Attributes:
        claude_api_key: Anthropic API key for Claude access.
        gmail_user: Gmail/Workspace account used for SMS gateway sending.
        sms_gateway: Carrier email-to-SMS gateway address.
        gdocs_script_url: Deployed Google Apps Script web app URL.
        good_fit_threshold: Minimum score for automatic application (default 75).
        stretch_threshold: Minimum score for human review (default 50).
        external_apply_threshold: Minimum score for auto-submitting external
            applications via Vision Agent (default 80). Jobs scoring between
            good_fit_threshold and this value get tailored PDF but go to human
            queue for manual submission.
        human_review_threshold: Minimum fit score for escalating external apply
            jobs with open-ended questions for human review (default 85). Jobs
            at or above this threshold pause for user review instead of
            auto-submitting Claude's draft answers.
        backup_dir: Local directory path for daily DB backups.
        dry_run: When True, the pipeline runs all stages but skips actual form
            submission. Jobs reach "applying" status but are not submitted.
    """

    model_config = ConfigDict(strict=False)

    claude_api_key: str | None = None
    gmail_user: str | None = None
    sms_gateway: str | None = None
    gdocs_script_url: str | None = None
    good_fit_threshold: int = 75
    stretch_threshold: int = 50
    external_apply_threshold: int = 80
    human_review_threshold: int = 85
    skip_viewed_jobs: bool = True
    backup_dir: str | None = None
    dry_run: bool = True

    @field_serializer("claude_api_key")
    def redact_secrets(self, value: str | None) -> str:
        """Redact secret fields to prevent credential leakage in API responses."""
        return "***"


class SystemState(BaseModel):
    """Current operational state of the Automator.

    Attributes:
        status: Current system status.
        last_run_at: ISO 8601 timestamp of the last completed run.
        last_error: Most recent error message, if any.
    """

    model_config = ConfigDict(strict=False)

    status: Literal["running", "paused", "idle", "error"] = "idle"
    last_run_at: str | None = None
    last_error: str | None = None


# ---------------------------------------------------------------------------
# Job record output schema
# ---------------------------------------------------------------------------


class JobRecordOut(BaseModel):
    """API representation of a persisted job record.

    Attributes:
        id: LinkedIn job ID (primary key).
        job_title: Title of the job posting.
        company: Hiring company name.
        location: Geographic location of the role.
        linkedin_url: Canonical LinkedIn URL for the listing.
        external_url: Third-party application URL (None for Easy Apply).
        apply_type: Either 'easy_apply' or 'external_apply'.
        status: Current pipeline status.
        fit_score: Claude-assigned fit score 0-100.
        fit_rationale: Claude's explanation of the score.
        description_text: Full extracted job description.
        resume_snapshot: JSON-encoded pre-tailoring resume content.
        tailored_resume_pdf: Absolute path to the exported tailored PDF.
        cover_letter_text: Generated cover letter text.
        error_message: Most recent error message.
        queue_reason: Reason the job was added to the Human Queue.
        discovered_at: ISO 8601 timestamp when the record was created.
        extracted_at: ISO 8601 timestamp when description was extracted.
        scored_at: ISO 8601 timestamp when fit scoring completed.
        approved_at: ISO 8601 timestamp when job was approved for apply.
        applied_at: ISO 8601 timestamp when application was submitted.
        updated_at: ISO 8601 timestamp of the most recent update.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_title: str
    company: str
    location: str | None = None
    linkedin_url: str
    external_url: str | None = None
    apply_type: str
    status: str
    fit_score: int | None = None
    fit_rationale: str | None = None
    description_text: str | None = None
    resume_snapshot: str | None = None
    tailored_resume_text: str | None = None
    tailored_resume_pdf: str | None = None
    cover_letter_text: str | None = None
    error_message: str | None = None
    queue_reason: str | None = None
    application_notes: str | None = None
    run_id: str | None = None
    claude_cost_usd: float | None = None
    discovered_at: str
    extracted_at: str | None = None
    scored_at: str | None = None
    approved_at: str | None = None
    applied_at: str | None = None
    updated_at: str

    @field_validator("claude_cost_usd", mode="before")
    @classmethod
    def coerce_cost(cls, v: str | float | None) -> float | None:
        """Coerce TEXT-stored cost to float for API responses."""
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Queue item output schema
# ---------------------------------------------------------------------------


class QueueItemOut(BaseModel):
    """API representation of a Human Queue item.

    Attributes:
        job_id: LinkedIn job ID.
        job_title: Title of the job posting.
        company: Hiring company name.
        linkedin_url: Canonical LinkedIn URL for the listing.
        queue_reason: Reason the job was escalated to the queue.
        fit_score: Claude-assigned fit score (may be None if not yet scored).
        fit_rationale: Claude's explanation of the score.
        status: Current job status (scored, tailored, etc.).
        tailored_resume_pdf: Path to tailored PDF if available.
        tailored_resume_text: JSON array of find/replace edits if available.
        added_at: ISO 8601 timestamp when the item was added to the queue.
    """

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    job_title: str
    company: str
    linkedin_url: str
    queue_reason: str | None = None
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str
    tailored_resume_pdf: str | None = None
    tailored_resume_text: str | None = None
    added_at: str


# ---------------------------------------------------------------------------
# Statistics output schema
# ---------------------------------------------------------------------------


class StatsOut(BaseModel):
    """Summary statistics for the job pipeline.

    Attributes:
        total_discovered: Total number of jobs discovered.
        total_applied: Total number of successful applications.
        total_skipped: Total number of skipped jobs.
        total_pending_review: Total number of jobs awaiting human review.
        application_success_rate: Ratio of applied to approved_for_apply (0 if none).
    """

    total_discovered: int = 0
    total_applied: int = 0
    total_skipped: int = 0
    total_pending_review: int = 0
    application_success_rate: float = 0.0


# ---------------------------------------------------------------------------
# System status and health response schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Connectivity health check results.

    Attributes:
        claude_api: Whether the Claude API is reachable.
        gmail: Whether the Gmail SMTP server is reachable.
        google_docs: Whether the Google Apps Script endpoint is reachable.
    """

    claude_api: bool = False
    gmail: bool = False
    google_docs: bool = False


class StatusResponse(BaseModel):
    """Combined system status response for GET /status.

    Attributes:
        status: Current system status.
        last_run_at: ISO 8601 timestamp of the last completed run.
        next_run_at: ISO 8601 timestamp of the next scheduled run.
        queue_count: Number of items pending in the Human Queue.
        stats: Summary pipeline statistics.
        health: Connectivity health check results.
    """

    status: Literal["running", "paused", "idle", "error"] = "idle"
    last_run_at: str | None = None
    next_run_at: str | None = None
    queue_count: int = 0
    stats: StatsOut = StatsOut()
    health: HealthResponse = HealthResponse()


# ---------------------------------------------------------------------------
# PUT request body schemas
# ---------------------------------------------------------------------------


class SearchConfigUpdate(BaseModel):
    """Request body for PUT /config/search.

    Attributes:
        keywords: Single search keywords string (legacy).
        search_queries: List of keyword query strings to run each cycle.
        location: Geographic location filter.
        job_type: Employment type filter.
        experience_level: Seniority level filter.
        remote_pref: Remote work preference filter.
    """

    model_config = ConfigDict(strict=False)

    keywords: str | None = None
    search_queries: list[str] | None = None
    location: str | None = None
    job_type: str | None = None
    experience_level: str | None = None
    remote_pref: str | None = None


class GoalsProfileUpdate(BaseModel):
    """Request body for PUT /config/goals.

    Attributes:
        target_titles: List of desired job titles.
        industries: Preferred industries.
        company_sizes: Preferred company size categories.
        geo_prefs: Geographic preferences.
        min_salary: Minimum acceptable salary (optional).
        deal_breakers: Keywords that disqualify a job regardless of fit score.
        open_to_stretch: Whether the user is open to stretch roles.
        career_objective: Free-text career objective statement.
        supplementary_context: Additional experience notes passed to Claude
            alongside the resume during scoring and tailoring.
    """

    model_config = ConfigDict(strict=False)

    target_titles: list[str] = []
    industries: list[str] = []
    company_sizes: list[str] = []
    geo_prefs: list[str] = []
    min_salary: int | None = None
    deal_breakers: list[str] = []
    open_to_stretch: bool = True
    career_objective: str | None = None
    supplementary_context: str | None = None


class UserProfileUpdate(BaseModel):
    """Request body for PUT /config/profile.

    Attributes:
        full_name: User's full legal name.
        email: Contact email address.
        phone: Contact phone number.
        location: User's current location.
        work_auth: Work authorization status.
        linkedin_url: User's LinkedIn profile URL.
        common_answers: Pre-filled answers to common application questions.
    """

    model_config = ConfigDict(strict=False)

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    work_auth: str | None = None
    linkedin_url: str | None = None
    common_answers: dict[str, str] = {}


class SettingsUpdate(BaseModel):
    """Request body for PUT /config/settings.

    Attributes:
        claude_api_key: Anthropic API key for Claude access.
        gmail_user: Gmail/Workspace account used for SMS gateway sending.
        sms_gateway: Carrier email-to-SMS gateway address.
        gdocs_script_url: Deployed Google Apps Script web app URL.
        good_fit_threshold: Minimum score for automatic application.
        stretch_threshold: Minimum score for human review.
        external_apply_threshold: Minimum score for auto-submitting external applies.
        human_review_threshold: Minimum fit score for escalating external apply
            jobs with open-ended questions for human review (50-100).
        backup_dir: Local directory path for daily DB backups.
        dry_run: When True, skip actual form submission.
    """

    model_config = ConfigDict(strict=False)

    claude_api_key: str | None = None
    gmail_user: str | None = None
    sms_gateway: str | None = None
    gdocs_script_url: str | None = None
    good_fit_threshold: int | None = None
    stretch_threshold: int | None = None
    external_apply_threshold: int | None = None
    human_review_threshold: int | None = None
    skip_viewed_jobs: bool | None = None
    backup_dir: str | None = None
    dry_run: bool | None = None

    @field_validator("human_review_threshold")
    @classmethod
    def validate_human_review_threshold(cls, v: int | None) -> int | None:
        """Ensure human_review_threshold is between 50 and 100 inclusive."""
        if v is not None and (v < 50 or v > 100):
            raise ValueError("human_review_threshold must be between 50 and 100")
        return v

    @model_validator(mode="after")
    def warn_threshold_overlap(self) -> SettingsUpdate:
        """Log a warning when human_review_threshold <= external_apply_threshold.

        When the human review threshold is at or below the external apply
        threshold, most external apply jobs will be escalated for review.
        """
        hrt = self.human_review_threshold
        eat = self.external_apply_threshold
        if hrt is not None and eat is not None and hrt <= eat:
            logger.warning(
                "human_review_threshold_at_or_below_external_apply_threshold",
                human_review_threshold=hrt,
                external_apply_threshold=eat,
                msg="Most external apply jobs will be escalated for review",
            )
        return self


# ---------------------------------------------------------------------------
# Escalation schemas
# ---------------------------------------------------------------------------


class EscalationRecordOut(BaseModel):
    """API representation of an escalation record.

    The form_state_snapshot and draft_answers fields are stored as JSON strings
    in the database but are parsed to dict/list in the API response via
    field validators.

    Attributes:
        id: UUID4 primary key.
        job_id: Foreign key to job_records.
        tier: Escalation tier ("captcha" or "human_review").
        form_state_snapshot: Parsed JSON of the form state at escalation time.
        draft_answers: Parsed JSON array of Claude's draft answers (None for captcha tier).
        timeout_deadline: ISO 8601 auto-submit deadline (None for captcha tier).
        freshness_tier: Job freshness classification (None for captcha tier).
        status: Current escalation status.
        resolution_method: How the escalation was resolved (None while pending).
        created_at: ISO 8601 timestamp of creation.
        resolved_at: ISO 8601 timestamp of resolution (None while pending).
        job_title: Denormalized from job_record for list display.
        company: Denormalized from job_record for list display.
        fit_score: Denormalized from job_record for list display.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    tier: Literal["captcha", "human_review"]
    form_state_snapshot: dict  # Parsed JSON
    draft_answers: list[dict] | None = None  # Parsed JSON
    timeout_deadline: str | None = None
    freshness_tier: str | None = None
    status: str
    resolution_method: str | None = None
    created_at: str
    resolved_at: str | None = None
    # Denormalized from job_record for list display
    job_title: str | None = None
    company: str | None = None
    fit_score: int | None = None

    @field_validator("form_state_snapshot", mode="before")
    @classmethod
    def parse_form_state_snapshot(cls, v: str | dict) -> dict:
        """Parse JSON string from DB into a dict."""
        if isinstance(v, str):
            return json.loads(v)
        return v

    @field_validator("draft_answers", mode="before")
    @classmethod
    def parse_draft_answers(cls, v: str | list | None) -> list[dict] | None:
        """Parse JSON string from DB into a list of dicts."""
        if v is None:
            return None
        if isinstance(v, str):
            return json.loads(v)
        return v


class EscalationSubmitRequest(BaseModel):
    """Request body for POST /escalations/{id}/submit.

    Attributes:
        edited_answers: List of edited answer objects, each containing
            field_id and edited_answer.
    """

    edited_answers: list[dict]  # [{field_id, edited_answer}]


class EscalationListResponse(BaseModel):
    """Response body for GET /escalations.

    Attributes:
        escalations: List of escalation records.
        total: Total count of matching records.
    """

    escalations: list[EscalationRecordOut]
    total: int
