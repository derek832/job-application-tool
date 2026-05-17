"""
Chrome CDP API routes for the LinkedIn Job Automator.

Provides endpoints to check Chrome CDP reachability and launch Chrome with
remote debugging flags for automation. The status endpoint responds within
3 seconds; the launch endpoint spawns Chrome as a detached subprocess with
a dedicated user-data-dir.

Validates: Requirements 5.1, 5.5, 5.6, 5.7, 5.9
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.system_routes import verify_token
from src.db.database import get_session
from src.integrations.chrome_launcher import get_chrome_status, launch_chrome

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chrome", tags=["chrome"])

# Default CDP URL for Chrome remote debugging (from Docker container perspective).
_CDP_URL = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ChromeStatusResponse(BaseModel):
    """Response schema for GET /chrome/status.

    Attributes:
        connected: Whether Chrome is reachable on the CDP port.
        browser_version: Chrome version string, or None if not connected.
        debugger_url: WebSocket debugger URL, or None if not connected.
    """

    connected: bool
    browser_version: str | None = None
    debugger_url: str | None = None


class ChromeLaunchResponse(BaseModel):
    """Response schema for POST /chrome/launch.

    Attributes:
        success: Whether Chrome is now reachable on the CDP port.
        message: Human-readable description of what happened.
        already_running: True if Chrome was already reachable (no launch needed).
    """

    success: bool
    message: str
    already_running: bool = False


# ---------------------------------------------------------------------------
# GET /chrome/status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ChromeStatusResponse)
async def get_status(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ChromeStatusResponse:
    """Check Chrome CDP reachability and return connection status.

    Performs an HTTP GET to the Chrome DevTools Protocol /json/version
    endpoint. Responds within 3 seconds (enforced by the CDP_TIMEOUT in
    chrome_launcher).

    Returns:
        ChromeStatusResponse with connection status and version info.
    """
    logger.info("chrome_status_check_requested", cdp_url=_CDP_URL)

    status = await get_chrome_status(_CDP_URL)

    logger.info(
        "chrome_status_check_completed",
        connected=status.connected,
        browser_version=status.browser_version,
    )

    return ChromeStatusResponse(
        connected=status.connected,
        browser_version=status.browser_version,
        debugger_url=status.debugger_url,
    )


# ---------------------------------------------------------------------------
# POST /chrome/launch
# ---------------------------------------------------------------------------


@router.post("/launch", response_model=ChromeLaunchResponse)
async def post_launch(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ChromeLaunchResponse:
    """Launch Chrome with remote debugging flags for automation.

    If Chrome is already reachable on the CDP port, returns success without
    launching a duplicate process. Otherwise, spawns Chrome as a detached
    subprocess with --remote-debugging-port=9222, a dedicated --user-data-dir,
    and --no-first-run.

    The user's default Chrome profile is never touched.

    Returns:
        ChromeLaunchResponse indicating success/failure and whether Chrome
        was already running.
    """
    logger.info("chrome_launch_requested")

    result = await launch_chrome()

    logger.info(
        "chrome_launch_completed",
        success=result.success,
        already_running=result.already_running,
        message=result.message,
    )

    return ChromeLaunchResponse(
        success=result.success,
        message=result.message,
        already_running=result.already_running,
    )
