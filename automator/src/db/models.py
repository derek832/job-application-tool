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
            f"<StatusTransition job_id={self.job_id!r} "
            f"{self.from_status!r} → {self.to_status!r}>"
        )


# ---------------------------------------------------------------------------
# NotificationLog
# ---------------------------------------------------------------------------


class NotificationLog(Base):
    """Record of every SMS notification attempt made by the Automator.

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
        success: ``1`` if the SMS was delivered successfully, ``0`` otherwise.
        error_message: SMTP or gateway error detail when ``success`` is ``0``.
        job: Back-reference to the parent ``JobRecord`` (nullable).
    """

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_records.id", ondelete="SET NULL"), nullable=True
    )
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    sms_body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    job: Mapped[JobRecord | None] = relationship("JobRecord", back_populates="notification_logs")

    def __repr__(self) -> str:
        return (
            f"<NotificationLog id={self.id} job_id={self.job_id!r} "
            f"trigger={self.trigger_reason!r} success={self.success}>"
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
