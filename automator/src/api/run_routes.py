"""
Run history API routes for the LinkedIn Job Automator.

Provides the GET /runs/history endpoint that returns recent pipeline run
summaries for display on the web app Dashboard.

Validates: Requirements 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.system_routes import verify_token
from src.db.database import get_session
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
    """

    id: str
    created_at: str
    summary: str


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
        )
        for record in records
    ]

    return RunHistoryResponse(items=items)
