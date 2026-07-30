"""
Scoring comparison repository — CRUD and query operations for the
scoring_comparisons table.

All functions are async and operate on an ``AsyncSession`` passed by the caller.
Computed fields (``score_difference``, ``would_skip``) are derived at insert time
and are immutable after creation — changing the cutoff config does not retroactively
update existing records.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ScoringComparison

logger = structlog.get_logger(__name__)


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


async def create_comparison(
    session: AsyncSession,
    job_id: str,
    local_score: int | None,
    claude_score: int,
    model_version: str | None,
    cutoff: int,
) -> ScoringComparison:
    """Create a new ScoringComparison record with computed fields.

    Computes ``score_difference`` and ``would_skip`` at insert time based on
    the provided scores and cutoff threshold.

    Args:
        session: Active async database session.
        job_id: The LinkedIn job ID (FK to job_records).
        local_score: Local model's predicted fit score (0–100), or None if
            prediction failed or model not trained.
        claude_score: Claude's authoritative fit score (0–100).
        model_version: Identifier of the local model version used.
        cutoff: The current local_score_cutoff threshold for would_skip.

    Returns:
        The newly created ``ScoringComparison`` instance.
    """
    # Computed fields per design spec:
    # score_difference = claude_score - local_score (NULL if local_score is NULL)
    # would_skip = 1 if local_score is not None and local_score < cutoff, else 0
    score_difference: int | None = None
    would_skip: int = 0

    if local_score is not None:
        score_difference = claude_score - local_score
        would_skip = 1 if local_score < cutoff else 0

    record = ScoringComparison(
        job_id=job_id,
        local_score=local_score,
        claude_score=claude_score,
        score_difference=score_difference,
        would_skip=would_skip,
        model_version=model_version,
        scored_at=_utcnow_iso(),
    )
    session.add(record)
    await session.flush()

    logger.info(
        "scoring_comparison_created",
        job_id=job_id,
        local_score=local_score,
        claude_score=claude_score,
        score_difference=score_difference,
        would_skip=would_skip,
    )
    return record


async def query_comparisons(
    session: AsyncSession,
    date_from: str | None = None,
    date_to: str | None = None,
    min_claude_score: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[ScoringComparison]:
    """Return a paginated list of ScoringComparison records with optional filters.

    Args:
        session: Active async database session.
        date_from: If provided, filter to records with scored_at >= this value
            (ISO 8601 string comparison).
        date_to: If provided, filter to records with scored_at <= this value.
        min_claude_score: If provided, filter to records with claude_score >= this value.
        page: Page number (1-indexed). Defaults to 1.
        page_size: Maximum records per page. Defaults to 50.

    Returns:
        List of matching ``ScoringComparison`` instances for the requested page,
        sorted by scored_at descending.
    """
    query = select(ScoringComparison)

    if date_from is not None:
        query = query.where(ScoringComparison.scored_at >= date_from)

    if date_to is not None:
        query = query.where(ScoringComparison.scored_at <= date_to)

    if min_claude_score is not None:
        query = query.where(ScoringComparison.claude_score >= min_claude_score)

    offset = (page - 1) * page_size
    query = query.order_by(ScoringComparison.scored_at.desc()).offset(offset).limit(page_size)

    result = await session.execute(query)
    return list(result.scalars().all())


async def count_comparisons(session: AsyncSession) -> int:
    """Return the total count of ScoringComparison records.

    Args:
        session: Active async database session.

    Returns:
        Total number of records in the scoring_comparisons table.
    """
    result = await session.execute(select(func.count(ScoringComparison.id)))
    return result.scalar_one()


async def get_all_comparisons_for_metrics(session: AsyncSession) -> list[ScoringComparison]:
    """Return all ScoringComparison records with non-null local_score.

    Used for computing aggregate trial metrics (MAE, recall, false positives).
    Only records where the local scorer successfully produced a prediction are
    included — records with null local_score are excluded.

    Args:
        session: Active async database session.

    Returns:
        List of ``ScoringComparison`` instances where local_score is not None.
    """
    query = (
        select(ScoringComparison)
        .where(ScoringComparison.local_score.isnot(None))
        .order_by(ScoringComparison.scored_at.desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())
