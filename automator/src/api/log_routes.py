"""
Log streaming routes for the LinkedIn Job Automator.

Provides an endpoint to retrieve recent pipeline activity logs so the
extension can display real-time progress.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import verify_token
from src.db.database import get_session
from src.db.models import StatusTransition

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


class LogEntry(BaseModel):
    """A single activity log entry."""

    job_id: str
    from_status: str | None
    to_status: str
    reason: str | None
    timestamp: str


class LogsResponse(BaseModel):
    """Response for GET /logs/activity."""

    entries: list[LogEntry]


@router.get("/activity", response_model=LogsResponse)
async def get_activity_log(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> LogsResponse:
    """Return recent pipeline activity (status transitions).

    Shows the most recent job status changes, giving visibility into what
    the pipeline is doing.

    Args:
        limit: Maximum number of entries to return. Defaults to 50.
        session: Active async database session.
    """
    result = await session.execute(
        select(StatusTransition)
        .order_by(desc(StatusTransition.timestamp))
        .limit(limit)
    )
    transitions = result.scalars().all()

    entries = [
        LogEntry(
            job_id=t.job_id,
            from_status=t.from_status,
            to_status=t.to_status,
            reason=t.reason,
            timestamp=t.timestamp,
        )
        for t in transitions
    ]

    return LogsResponse(entries=entries)
