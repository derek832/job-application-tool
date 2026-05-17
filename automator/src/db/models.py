"""
SQLAlchemy ORM models for the LinkedIn Job Automator State_DB.

Maps the four core tables — job_records, status_transitions, notification_log,
and config — to Python classes using the async-compatible declarative base.
All timestamps are stored as ISO 8601 TEXT in SQLite.
"""

from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Valid status values (Requirements 10.3)
# ---------------------------------------------------------------------------

VALID_STATUSES: frozenset[str] = frozenset(
    {
        "discovered",
        "extracted",
        "extraction_failed",
        "scored",
        "approved_for_apply",
        "skipped",
        "rejected_by_user",
        "resume_failed",
        "applying",
        "apply_failed",
        "applied",
        "manually_applied",
    }
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# JobRecord
# ---------------------------------------------------------------------------


class JobRecord(Base):
    """Persisted entry representing a discovered job and its processing state.

    Maps to the ``job_records`` table.  All timestamp columns store ISO 8601
    strings so that SQLite's text-based date functions work without a separate
    datetime type.

    Attributes:
        id: LinkedIn job ID (e.g. "3987654321"), used as the primary key.
        job_title: Title of the job posting.
        company: Name of the hiring company.
        location: Geographic location of the role (nullable).
        linkedin_url: Canonical LinkedIn URL for the job listing.
        external_url: Third-party application URL; NULL for Easy Apply jobs.
        apply_type: Either ``'easy_apply'`` or ``'external_apply'``.
        status: Current pipeline status; must be one of ``VALID_STATUSES``.
        fit_score: Claude-assigned fit score 0–100; NULL until scored.
        fit_rationale: Claude's explanation of the score (max 200 words).
        description_text: Full extracted job description (plain text, no HTML).
        resume_snapshot: JSON-encoded pre-tailoring Resume_Base content.
        tailored_resume_pdf: Absolute path to the exported tailored PDF.
        cover_letter_text: Generated cover letter text, if any.
        error_message: Most recent error message, if any.
        queue_reason: Reason the job was added to the Human_Queue.
        discovered_at: ISO 8601 timestamp when the record was created.
        extracted_at: ISO 8601 timestamp when description was extracted.
        scored_at: ISO 8601 timestamp when fit scoring completed.
        approved_at: ISO 8601 timestamp when job was approved for apply.
        applied_at: ISO 8601 timestamp when application was submitted.
        updated_at: ISO 8601 timestamp of the most recent update.
    """

    __tablename__ = "job_records"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="discovered")
    fit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fit_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailored_resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailored_resume_pdf: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queue_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    status_transitions: Mapped[list[StatusTransition]] = relationship(
        "StatusTransition",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="select",
    )
    notification_logs: Mapped[list[NotificationLog]] = relationship(
        "NotificationLog",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("idx_job_records_status", "status"),
        Index("idx_job_records_discovered_at", "discovered_at"),
    )

    def __repr__(self) -> str:
        return f"<JobRecord id={self.id!r} status={self.status!r} company={self.company!r}>"


# ---------------------------------------------------------------------------
# StatusTransition
# ---------------------------------------------------------------------------


class StatusTransition(Base):
    """Audit log of every status change for a job record.

    Maps to the ``status_transitions`` table.  A new row is written each time
    ``update_job_status`` is called so the full lifecycle of a job is
    reconstructable from this table.

    Attributes:
        id: Auto-incrementing surrogate primary key.
        job_id: Foreign key referencing ``job_records.id``.
        from_status: Previous status value; NULL for the initial transition.
        to_status: New status value after the transition.
        reason: Human-readable explanation of why the transition occurred.
        timestamp: ISO 8601 timestamp when the transition was recorded.
        job: Back-reference to the parent ``JobRecord``.
    """

    __tablename__ = "status_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationship
    job: Mapped[JobRecord] = relationship("JobRecord", back_populates="status_transitions")

    def __repr__(self) -> str:
        return (
            f"<StatusTransition job_id={self.job_id!r} {self.from_status!r} → {self.to_status!r}>"
        )


# ---------------------------------------------------------------------------
# NotificationLog
# ---------------------------------------------------------------------------


class NotificationLog(Base):
    """Record of every notification attempt made by the Automator.

    Maps to the ``notification_log`` table.  A row is written for every
    notification attempt — including failures — so the rate limiter can query
    recent sends and the user has a full audit trail.

    Attributes:
        id: Auto-incrementing surrogate primary key.
        job_id: Foreign key referencing ``job_records.id``; nullable because
            some system-level notifications are not tied to a specific job.
        trigger_reason: The ``Notification_Trigger`` condition that caused
            this notification (e.g. ``"stretch_role"``, ``"captcha_detected"``).
        sms_body: The exact text that was (or was attempted to be) sent.
        sent_at: ISO 8601 timestamp of the send attempt.
        success: ``1`` if the notification was delivered successfully, ``0`` otherwise.
        error_message: Error detail when ``success`` is ``0``.
        channel: Delivery channel used for this attempt. Valid values:
            ``'ntfy'``, ``'sms'``, ``'sms_fallback'``, ``'none'``.
        job: Back-reference to the parent ``JobRecord`` (nullable).
    """

    __tablename__ = "notification_log"

    # Valid channel values for notification delivery
    VALID_CHANNELS: frozenset[str] = frozenset({"ntfy", "sms", "sms_fallback", "none"})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="SET NULL"), nullable=True
    )
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    sms_body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="sms")

    # Relationship
    job: Mapped[JobRecord | None] = relationship("JobRecord", back_populates="notification_logs")

    def __repr__(self) -> str:
        return (
            f"<NotificationLog id={self.id} job_id={self.job_id!r} "
            f"trigger={self.trigger_reason!r} channel={self.channel!r} success={self.success}>"
        )


# ---------------------------------------------------------------------------
# RunSummary
# ---------------------------------------------------------------------------


class RunSummary(Base):
    """Post-run summary record storing pipeline execution results.

    Maps to the ``run_summaries`` table.  One row is created per completed
    pipeline run.  A retention policy keeps at most 20 records; older entries
    are deleted after each new insert.

    Attributes:
        id: UUID4 string primary key.
        summary: Plain-English summary paragraph (max 500 characters).
        jobs_discovered: Number of jobs found during the run.
        jobs_scored: Number of jobs that were scored.
        jobs_approved: Number of jobs approved for application.
        jobs_applied: Number of jobs successfully applied to.
        jobs_skipped: Number of jobs skipped.
        jobs_escalated: Number of jobs escalated to the Human Queue.
        errors: JSON array of error strings (nullable).
        created_at: ISO 8601 timestamp when the summary was created.
    """

    __tablename__ = "run_summaries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    jobs_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_escalated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_run_summaries_created_at", desc("created_at")),
    )

    def __repr__(self) -> str:
        return (
            f"<RunSummary id={self.id!r} created_at={self.created_at!r} "
            f"discovered={self.jobs_discovered} applied={self.jobs_applied}>"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class Config(Base):
    """Key-value configuration store for the Automator.

    Maps to the ``config`` table.  Values are JSON-encoded strings so that
    complex objects (Goals_Profile, Settings, etc.) can be stored without
    additional schema changes.

    Attributes:
        key: Unique configuration key (e.g. ``"search_config"``).
        value: JSON-encoded configuration value.
        updated_at: ISO 8601 timestamp of the most recent write.
    """

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    # Enforce uniqueness at the ORM level as well (the PK already does this,
    # but the explicit constraint makes the intent clear).
    __table_args__ = (UniqueConstraint("key", name="uq_config_key"),)

    def __repr__(self) -> str:
        return f"<Config key={self.key!r} updated_at={self.updated_at!r}>"


# ---------------------------------------------------------------------------
# ATS Accounts
# ---------------------------------------------------------------------------


class ATSAccount(Base):
    """Stored credentials for external ATS platforms.

    When the Vision Agent encounters a registration page, it creates an account
    using the user's email and a generated password. Credentials are stored here
    so they can be reused on subsequent applications to the same ATS platform.

    Attributes:
        id: Auto-incrementing primary key.
        domain: The ATS domain (e.g. 'bamboohr.com', 'greenhouse.io').
        email: The email used to register.
        password: The generated password.
        auth_method: How authentication was done ('password' or 'google_oauth').
        created_at: ISO 8601 timestamp when the account was created.
        last_used_at: ISO 8601 timestamp of the most recent login.
        notes: Optional notes (e.g. 'verified via email link').
    """

    __tablename__ = "ats_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_method: Mapped[str] = mapped_column(Text, nullable=False, default="password")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_ats_accounts_domain", "domain"),
        UniqueConstraint("domain", "email", name="uq_ats_domain_email"),
    )

    def __repr__(self) -> str:
        return f"<ATSAccount domain={self.domain!r} email={self.email!r}>"


# ---------------------------------------------------------------------------
# External Apply Log (Vision tracking)
# ---------------------------------------------------------------------------


class ExternalApplyLog(Base):
    """Tracks each external apply attempt and which method was used.

    Used to measure how often DOM-based extraction succeeds vs. when the
    Claude Vision fallback is needed, informing cost/architecture decisions.

    Attributes:
        id: Auto-incrementing primary key.
        job_id: Foreign key referencing ``job_records.id``.
        domain: The ATS domain (e.g. 'greenhouse.io').
        method: Which extraction method was used: 'dom', 'vision', or 'none'.
        dom_fields_found: Number of fields extracted from the DOM.
        vision_fields_found: Number of fields identified by Claude Vision (0 if not used).
        fields_filled: Number of fields successfully filled.
        outcome: Result of the attempt: 'submitted', 'dry_run', 'escalated', 'failed'.
        failure_reason: Machine-readable reason if outcome is 'escalated' or 'failed'.
        timestamp: ISO 8601 timestamp of the attempt.
    """

    __tablename__ = "external_apply_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)  # 'dom', 'vision', 'none'
    dom_fields_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vision_fields_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    # outcome values: 'submitted', 'dry_run', 'escalated', 'failed'
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_external_apply_log_job_id", "job_id"),
        Index("idx_external_apply_log_method", "method"),
    )


# ---------------------------------------------------------------------------
# PreviewRun (Wave 3 — Pipeline Intelligence)
# ---------------------------------------------------------------------------


class PreviewRun(Base):
    """A preview/dry-run pipeline execution record.

    Maps to the ``preview_runs`` table. Preview mode executes discovery and
    scoring stages without proceeding to tailoring or application. Each run
    tracks aggregate counts and completion status.

    Attributes:
        id: UUID string primary key.
        status: Current run status — 'running', 'completed', or 'failed'.
        started_at: ISO 8601 timestamp when the preview run began.
        completed_at: ISO 8601 timestamp when the run finished (nullable).
        error_message: Error details if the run failed (nullable).
        total_discovered: Number of jobs discovered during the run.
        total_scored: Number of jobs that were scored.
        total_blacklisted: Number of jobs filtered by the blacklist.
    """

    __tablename__ = "preview_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_blacklisted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    preview_jobs: Mapped[list[PreviewJob]] = relationship(
        "PreviewJob",
        back_populates="preview_run",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (Index("idx_preview_runs_started_at", "started_at"),)

    def __repr__(self) -> str:
        return (
            f"<PreviewRun id={self.id!r} status={self.status!r} "
            f"discovered={self.total_discovered}>"
        )


# ---------------------------------------------------------------------------
# PreviewJob (Wave 3 — Pipeline Intelligence)
# ---------------------------------------------------------------------------


class PreviewJob(Base):
    """A job discovered and scored during a preview run.

    Maps to the ``preview_jobs`` table. Each record represents a single job
    found during a preview run, with its fit score and the projected action
    that would be taken in a full pipeline run.

    Attributes:
        id: Auto-incrementing surrogate primary key.
        run_id: Foreign key referencing ``preview_runs.id``.
        job_id: LinkedIn job ID string.
        job_title: Title of the job posting.
        company: Name of the hiring company.
        linkedin_url: Canonical LinkedIn URL for the job listing.
        fit_score: Claude-assigned fit score 0–100; NULL if blacklisted.
        fit_rationale: Claude's explanation of the score (nullable).
        projected_action: What would happen in a full run —
            'auto_apply', 'stretch_queue', 'skip', or 'blacklisted'.
        promoted: Whether this job was promoted to the real pipeline (0 or 1).
        promoted_at: ISO 8601 timestamp when promoted (NULL until promoted).
    """

    __tablename__ = "preview_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("preview_runs.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    linkedin_url: Mapped[str] = mapped_column(Text, nullable=False)
    fit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fit_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    projected_action: Mapped[str] = mapped_column(Text, nullable=False)
    promoted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promoted_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    preview_run: Mapped[PreviewRun] = relationship(
        "PreviewRun", back_populates="preview_jobs"
    )

    __table_args__ = (
        Index("idx_preview_jobs_run_id", "run_id"),
        Index("idx_preview_jobs_job_id", "job_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PreviewJob id={self.id} job_id={self.job_id!r} "
            f"action={self.projected_action!r} score={self.fit_score}>"
        )


# ---------------------------------------------------------------------------
# BlacklistEntry (Wave 3 — Pipeline Intelligence)
# ---------------------------------------------------------------------------


class BlacklistEntry(Base):
    """A company or title pattern blacklist entry.

    Maps to the ``blacklist_entries`` table. Blacklisted companies are matched
    case-insensitively by exact name; title patterns are matched as
    case-insensitive substrings. The hit_count tracks how many jobs have been
    filtered by each entry.

    Attributes:
        id: Auto-incrementing surrogate primary key.
        entry_type: Either 'company' or 'title_pattern'.
        value: The blacklist string (company name or title pattern).
        created_at: ISO 8601 timestamp when the entry was created.
        hit_count: Number of jobs filtered by this entry.
    """

    __tablename__ = "blacklist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("idx_blacklist_entries_type", "entry_type"),
        UniqueConstraint("entry_type", "value", name="idx_blacklist_entries_unique"),
    )

    def __repr__(self) -> str:
        return (
            f"<BlacklistEntry id={self.id} type={self.entry_type!r} "
            f"value={self.value!r} hits={self.hit_count}>"
        )


# ---------------------------------------------------------------------------
# NotificationQueue (Wave 3 — Pipeline Intelligence)
# ---------------------------------------------------------------------------


class NotificationQueue(Base):
    """A queued notification for delivery after quiet hours end.

    Maps to the ``notification_queue`` table. During quiet hours, notifications
    are stored here instead of being delivered immediately. When quiet hours
    end, all pending items are composed into a batch summary and delivered.

    Attributes:
        id: Auto-incrementing surrogate primary key.
        job_id: Foreign key referencing ``job_records.id``; nullable because
            some notifications are not tied to a specific job.
        trigger_reason: The condition that caused this notification.
        message_body: The notification text content.
        queued_at: ISO 8601 timestamp when the notification was queued.
        delivered: Whether the notification has been delivered (0 or 1).
    """

    __tablename__ = "notification_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="SET NULL"), nullable=True
    )
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    queued_at: Mapped[str] = mapped_column(Text, nullable=False)
    delivered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("idx_notification_queue_delivered", "delivered"),)

    def __repr__(self) -> str:
        return (
            f"<NotificationQueue id={self.id} reason={self.trigger_reason!r} "
            f"delivered={self.delivered}>"
        )
