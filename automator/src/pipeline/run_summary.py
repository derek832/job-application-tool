"""Run summary generator — post-pipeline summary creation and persistence.

Generates a plain-English summary from pipeline run statistics, stores it in
the ``run_summaries`` table, and manages the 20-record retention policy.

Validates: Requirements 5.1, 5.2, 5.4, 5.5
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RunSummary

logger = structlog.get_logger(__name__)


@dataclass
class RunStats:
    """Statistics collected from a completed pipeline run (delta-based).

    All counts represent NEW activity since the previous run — not cumulative
    totals from the entire database.

    Attributes:
        jobs_discovered: Number of new jobs found during this run.
        jobs_scored: Number of jobs scored by Claude during this run.
        jobs_prefiltered: Number of jobs eliminated by keyword pre-filter
            (never sent to Claude).
        jobs_approved: Number of jobs auto-approved during this run.
        jobs_applied: Number of jobs applied to during this run.
        jobs_skipped: Number of jobs skipped after scoring (low fit score).
        jobs_escalated: Number of jobs escalated to the Human Queue this run.
        jobs_applied_from_queue: Number of jobs applied to after being approved
            from the Human Queue since the previous run (inter-run activity).
        errors: List of error strings encountered during the run.
    """

    jobs_discovered: int
    jobs_scored: int
    jobs_prefiltered: int
    jobs_approved: int
    jobs_applied: int
    jobs_skipped: int
    jobs_escalated: int
    jobs_applied_from_queue: int = 0
    claude_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


def generate_summary_text(stats: RunStats) -> str:
    """Generate a plain-English summary paragraph from run statistics.

    Produces a human-readable summary reporting only NEW activity this run:
    "Run complete: found 159 new jobs, pre-filtered 77, scored 82, applied to 0,
    skipped 50, 19 need your review. No errors."

    The output is guaranteed to be at most 500 characters.

    Args:
        stats: The pipeline run statistics (delta-based).

    Returns:
        A plain-English summary string, max 500 characters.
    """
    parts = [f"Run complete: found {stats.jobs_discovered} new jobs"]

    if stats.jobs_prefiltered:
        parts.append(f"pre-filtered {stats.jobs_prefiltered}")
    if stats.jobs_scored:
        parts.append(f"scored {stats.jobs_scored}")
    if stats.jobs_applied:
        parts.append(f"applied to {stats.jobs_applied}")
    if stats.jobs_skipped:
        parts.append(f"skipped {stats.jobs_skipped}")
    if stats.jobs_escalated:
        parts.append(f"{stats.jobs_escalated} need your review")

    summary = ", ".join(parts) + "."

    # Add inter-run queue activity
    if stats.jobs_applied_from_queue:
        queue_suffix = (
            f" Also applied to {stats.jobs_applied_from_queue} "
            f"job{'s' if stats.jobs_applied_from_queue != 1 else ''} approved from queue."
        )
        if len(summary) + len(queue_suffix) <= 500:
            summary += queue_suffix

    if stats.errors:
        error_suffix = f" Errors: {'; '.join(stats.errors[:3])}"
        if len(summary) + len(error_suffix) <= 500:
            summary += error_suffix
        else:
            summary += f" {len(stats.errors)} error(s) occurred."
    else:
        summary += " No errors."

    return summary[:500]


async def store_run_summary(
    session: AsyncSession,
    stats: RunStats,
    summary_text: str,
) -> RunSummary:
    """Store a run summary in the database and enforce retention.

    Creates a new ``RunSummary`` record with a UUID4 identifier, persists the
    stats and summary text, then calls ``enforce_retention`` to keep only the
    20 most recent records.

    Args:
        session: Active async database session.
        stats: The pipeline run statistics.
        summary_text: The generated plain-English summary.

    Returns:
        The newly created RunSummary record.
    """
    record = RunSummary(
        id=str(uuid4()),
        summary=summary_text,
        jobs_discovered=stats.jobs_discovered,
        jobs_scored=stats.jobs_scored,
        jobs_approved=stats.jobs_approved,
        jobs_applied=stats.jobs_applied,
        jobs_skipped=stats.jobs_skipped,
        jobs_escalated=stats.jobs_escalated,
        jobs_applied_from_queue=stats.jobs_applied_from_queue,
        claude_cost_usd=str(round(stats.claude_cost_usd, 6)) if stats.claude_cost_usd > 0 else None,
        errors=json.dumps(stats.errors) if stats.errors else None,
        created_at=datetime.now(UTC).isoformat(),
    )
    session.add(record)
    await session.flush()

    await enforce_retention(session)

    logger.info(
        "run_summary_stored",
        summary_id=record.id,
        jobs_discovered=stats.jobs_discovered,
        jobs_applied=stats.jobs_applied,
    )

    return record


async def enforce_retention(
    session: AsyncSession,
    max_records: int = 20,
) -> None:
    """Delete run summaries beyond the retention limit.

    Keeps only the ``max_records`` most recent entries (by ``created_at`` DESC)
    and deletes the rest.

    Args:
        session: Active async database session.
        max_records: Maximum number of records to retain. Defaults to 20.
    """
    stmt = (
        select(RunSummary.id)
        .order_by(RunSummary.created_at.desc())
        .offset(max_records)
    )
    result = await session.execute(stmt)
    old_ids = result.scalars().all()

    if old_ids:
        await session.execute(
            delete(RunSummary).where(RunSummary.id.in_(old_ids))
        )
        logger.info(
            "run_summary_retention_enforced",
            deleted_count=len(old_ids),
            max_records=max_records,
        )


async def get_recent_summaries(
    session: AsyncSession,
    limit: int = 5,
) -> list[RunSummary]:
    """Retrieve the N most recent run summaries.

    Args:
        session: Active async database session.
        limit: Maximum number of summaries to return. Defaults to 5.

    Returns:
        List of RunSummary records ordered by created_at DESC.
    """
    stmt = (
        select(RunSummary)
        .order_by(RunSummary.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
