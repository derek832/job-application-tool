"""
Run history API routes for the LinkedIn Job Automator.

Provides the GET /runs/history endpoint that returns recent pipeline run
summaries for display on the web app Dashboard.

Validates: Requirements 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.models import RunSummary
from src.pipeline.run_summary import get_recent_summaries

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class RunHistoryOut(BaseModel):
    """A single run history entry.

    Attributes:
        id: Unique run identifier (UUID4 string).
        created_at: ISO 8601 timestamp of when the run completed.
        summary: Plain-English summary of the run results.
        claude_cost_usd: Total Claude API cost for this run in USD.
    """

    id: str
    created_at: str
    summary: str
    claude_cost_usd: float | None = None


class RunHistoryResponse(BaseModel):
    """Wrapper response containing a list of run history items.

    Attributes:
        items: List of run history entries, ordered most recent first.
    """

    items: list[RunHistoryOut]


# ---------------------------------------------------------------------------
# GET /runs/history
# ---------------------------------------------------------------------------


@router.get("/history", response_model=RunHistoryResponse)
async def get_run_history(
    limit: int = Query(default=5, ge=1, le=20, description="Number of results to return"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> RunHistoryResponse:
    """Return the most recent pipeline run summaries.

    Args:
        limit: Number of summaries to return (1–20, default 5).
        session: Active async database session.

    Returns:
        A response containing a list of run history items with id,
        created_at (ISO 8601), and summary text.
    """
    logger.info("get_run_history_requested", limit=limit)

    records = await get_recent_summaries(session, limit=limit)

    items = [
        RunHistoryOut(
            id=record.id,
            created_at=record.created_at,
            summary=record.summary,
            claude_cost_usd=float(record.claude_cost_usd) if record.claude_cost_usd else None,
        )
        for record in records
    ]

    return RunHistoryResponse(items=items)


# ---------------------------------------------------------------------------
# Cost stats response schema
# ---------------------------------------------------------------------------


class CostStatsOut(BaseModel):
    """Aggregated Claude API cost statistics.

    Attributes:
        today_usd: Total cost for today (UTC).
        last_7_days_usd: Total cost for the last 7 days.
        last_30_days_usd: Total cost for the last 30 days.
        all_time_usd: Total cost across all tracked runs and jobs.
        per_run_avg_usd: Average cost per pipeline run.
    """

    today_usd: float = 0.0
    last_7_days_usd: float = 0.0
    last_30_days_usd: float = 0.0
    all_time_usd: float = 0.0
    per_run_avg_usd: float = 0.0


# ---------------------------------------------------------------------------
# GET /runs/cost-stats
# ---------------------------------------------------------------------------


@router.get("/cost-stats", response_model=CostStatsOut)
async def get_cost_stats(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> CostStatsOut:
    """Return aggregated Claude API cost statistics.

    Computes cost totals from run_summaries (per-run cost) for time-based
    aggregations (today, 7 days, 30 days, all time).

    Returns:
        CostStatsOut with daily, weekly, monthly, and all-time cost totals.
    """
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # Query all run summaries that have cost data
    stmt = select(RunSummary.created_at, RunSummary.claude_cost_usd).where(
        RunSummary.claude_cost_usd.isnot(None)
    )
    result = await session.execute(stmt)
    rows = result.all()

    today_total = 0.0
    week_total = 0.0
    month_total = 0.0
    all_time_total = 0.0
    run_count = 0

    for created_at, cost_str in rows:
        try:
            cost = float(cost_str)
        except (ValueError, TypeError):
            continue

        all_time_total += cost
        run_count += 1

        if created_at >= today_start:
            today_total += cost
        if created_at >= seven_days_ago:
            week_total += cost
        if created_at >= thirty_days_ago:
            month_total += cost

    per_run_avg = all_time_total / run_count if run_count > 0 else 0.0

    return CostStatsOut(
        today_usd=round(today_total, 4),
        last_7_days_usd=round(week_total, 4),
        last_30_days_usd=round(month_total, 4),
        all_time_usd=round(all_time_total, 4),
        per_run_avg_usd=round(per_run_avg, 4),
    )
