"""Pipeline stage: shadow scoring via the local embedding-based model.

Runs the LocalScorer in parallel with Claude scoring during the trial period.
Never raises — any failure results in a null local_score and the pipeline
continues uninterrupted.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import JobRecord
from src.db.scoring_comparison_repo import create_comparison
from src.scoring.local_scorer import LocalScorer

logger = structlog.get_logger(__name__)


async def run_shadow_scoring(
    job_record: JobRecord,
    session: AsyncSession,
    local_scorer: LocalScorer,
    cutoff: int,
) -> int | None:
    """Run local scoring in shadow mode for a single job.

    Invokes local_scorer.predict() with a 500ms timeout via asyncio.to_thread
    (since predict() is synchronous). On success returns the local score.
    On exception or timeout, logs the error and returns None.

    Never raises — always allows the pipeline to continue.
    """
    try:
        local_score: int | None = await asyncio.wait_for(
            asyncio.to_thread(local_scorer.predict, job_record.description_text),
            timeout=0.5,
        )
        return local_score
    except TimeoutError:
        logger.warning(
            "shadow_scoring_timeout",
            job_id=job_record.id,
            timeout_ms=500,
        )
        return None
    except Exception as exc:
        logger.error(
            "shadow_scoring_error",
            job_id=job_record.id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


async def store_comparison(
    session: AsyncSession,
    job_id: str,
    local_score: int | None,
    claude_score: int,
    model_version: str | None,
    cutoff: int,
) -> None:
    """Create a ScoringComparison record after both scores are available.

    Delegates to the scoring_comparison_repo for actual persistence.
    """
    await create_comparison(
        session=session,
        job_id=job_id,
        local_score=local_score,
        claude_score=claude_score,
        model_version=model_version,
        cutoff=cutoff,
    )
