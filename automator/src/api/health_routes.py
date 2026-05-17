"""
Session health API routes for the LinkedIn Job Automator.

Provides the GET /health/session endpoint that performs a live session health
check (Chrome CDP reachability + LinkedIn authentication) and returns a
structured result within a 15-second timeout.

Validates: Requirements 2.5, 2.6
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.system_routes import verify_token
from src.db.database import get_session
from src.pipeline.health_checker import check_session_health

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Default CDP URL for Chrome remote debugging.
_CDP_URL = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class SessionHealthResponse(BaseModel):
    """Response schema for the session health check endpoint.

    Attributes:
        chrome_reachable: Whether Chrome CDP responded successfully.
        linkedin_authenticated: Whether LinkedIn session is valid (no login redirect).
        error_message: Human-readable error description, or None if healthy.
        checked_at: ISO 8601 timestamp of when the check was performed.
    """

    chrome_reachable: bool
    linkedin_authenticated: bool
    error_message: str | None = None
    checked_at: str


# ---------------------------------------------------------------------------
# GET /health/session
# ---------------------------------------------------------------------------


@router.get("/session", response_model=SessionHealthResponse)
async def get_session_health(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> SessionHealthResponse:
    """Perform a live session health check and return the result.

    Verifies Chrome CDP reachability and LinkedIn session authentication.
    The entire check is bounded by a 15-second timeout (enforced internally
    by check_session_health).

    Returns:
        A SessionHealthResponse with Chrome and LinkedIn status.
    """
    logger.info("session_health_check_requested")

    result = await check_session_health(_CDP_URL)

    logger.info(
        "session_health_check_completed",
        chrome_reachable=result.chrome_reachable,
        linkedin_authenticated=result.linkedin_authenticated,
        error_message=result.error_message,
    )

    return SessionHealthResponse(
        chrome_reachable=result.chrome_reachable,
        linkedin_authenticated=result.linkedin_authenticated,
        error_message=result.error_message,
        checked_at=result.checked_at,
    )
