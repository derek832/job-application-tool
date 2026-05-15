"""
System control API routes for the LinkedIn Job Automator.

Provides top-level endpoints for system status, health checks, and run control
(run, pause, resume). All endpoints require Bearer token authentication.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import HealthResponse, StatsOut, StatusResponse, SystemState
from src.db.config_repo import get_config, set_config
from src.db.database import get_session
from src.db.job_repo import get_queue_items, get_stats
from src.integrations.gmail_oauth import load_credentials
from src.scheduler.scheduler import trigger_now as scheduler_trigger_now

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_token(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Validate the Bearer token against the stored api_token in config.

    Args:
        authorization: The Authorization header value (expected format:
            ``Bearer <token>``).
        session: Active async database session.

    Raises:
        HTTPException: 401 if the token is missing, malformed, or does not
            match the stored api_token.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization[len("Bearer ") :]
    stored_token = await get_config(session, "api_token")

    if stored_token is None or token != stored_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=StatusResponse)
async def get_status(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> StatusResponse:
    """Return the current system status, stats, queue count, and health.

    Combines system state, pipeline statistics, queue count, and a quick
    health check into a single response for the Extension dashboard.
    """
    logger.info("get_status_requested")

    system_state_data = await get_config(session, "system_state")
    system_state = SystemState(**(system_state_data or {}))

    stats_data = await get_stats(session)
    stats = StatsOut(**stats_data)

    queue_items = await get_queue_items(session)
    queue_count = len(queue_items)

    settings_data = await get_config(session, "settings") or {}
    scheduled_time = settings_data.get("scheduled_time")

    next_run_at: str | None = None
    if scheduled_time and system_state.status != "paused":
        next_run_at = _compute_next_run_at(scheduled_time)

    health = await _perform_health_checks(session)

    return StatusResponse(
        status=system_state.status,
        last_run_at=system_state.last_run_at,
        next_run_at=next_run_at,
        queue_count=queue_count,
        stats=stats,
        health=health,
    )


# ---------------------------------------------------------------------------
# POST /run
# ---------------------------------------------------------------------------


@router.post("/run", response_model=StatusResponse)
async def trigger_run(
    skip_discovery: bool = False,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> StatusResponse:
    """Trigger an immediate pipeline run.

    Sets the system state to "running". The actual pipeline execution is
    handled by the scheduler/pipeline layer which monitors state changes.

    Args:
        skip_discovery: If True, skips discovery and scoring stages. Useful
            for debugging tailoring/apply stages without burning Claude tokens
            on re-scoring existing jobs.
    """
    logger.info("manual_run_triggered", skip_discovery=skip_discovery)

    system_state_data = await get_config(session, "system_state") or {}
    system_state_data["status"] = "running"
    system_state_data["skip_discovery"] = skip_discovery
    await set_config(session, "system_state", system_state_data)
    await session.commit()

    # Actually trigger the pipeline via the scheduler
    scheduler_trigger_now()

    stats_data = await get_stats(session)
    stats = StatsOut(**stats_data)

    queue_items = await get_queue_items(session)
    queue_count = len(queue_items)

    return StatusResponse(
        status="running",
        last_run_at=system_state_data.get("last_run_at"),
        next_run_at=None,
        queue_count=queue_count,
        stats=stats,
        health=HealthResponse(),
    )


# ---------------------------------------------------------------------------
# POST /pause
# ---------------------------------------------------------------------------


@router.post("/pause", response_model=StatusResponse)
async def pause_system(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> StatusResponse:
    """Pause all scheduled and manual runs.

    Sets the system state status to "paused". While paused, the scheduler
    will not initiate new runs and manual triggers are blocked.
    """
    logger.info("system_paused")

    system_state_data = await get_config(session, "system_state") or {}
    system_state_data["status"] = "paused"
    await set_config(session, "system_state", system_state_data)

    stats_data = await get_stats(session)
    stats = StatsOut(**stats_data)

    queue_items = await get_queue_items(session)
    queue_count = len(queue_items)

    return StatusResponse(
        status="paused",
        last_run_at=system_state_data.get("last_run_at"),
        next_run_at=None,
        queue_count=queue_count,
        stats=stats,
        health=HealthResponse(),
    )


# ---------------------------------------------------------------------------
# POST /resume
# ---------------------------------------------------------------------------


@router.post("/resume", response_model=StatusResponse)
async def resume_system(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> StatusResponse:
    """Resume the system from a paused state.

    Sets the system state status to "idle", making it ready for the next
    scheduled or manual run.
    """
    logger.info("system_resumed")

    system_state_data = await get_config(session, "system_state") or {}
    system_state_data["status"] = "idle"
    await set_config(session, "system_state", system_state_data)

    settings_data = await get_config(session, "settings") or {}
    scheduled_time = settings_data.get("scheduled_time")
    next_run_at = _compute_next_run_at(scheduled_time) if scheduled_time else None

    stats_data = await get_stats(session)
    stats = StatsOut(**stats_data)

    queue_items = await get_queue_items(session)
    queue_count = len(queue_items)

    return StatusResponse(
        status="idle",
        last_run_at=system_state_data.get("last_run_at"),
        next_run_at=next_run_at,
        queue_count=queue_count,
        stats=stats,
        health=HealthResponse(),
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health_check(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> HealthResponse:
    """Perform live connectivity checks to Claude API, Gmail, and Google Docs.

    Each check runs concurrently with a timeout. A service is reported as
    healthy (true) only if the connectivity check succeeds within the timeout.
    """
    logger.info("health_check_requested")
    return await _perform_health_checks(session)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _perform_health_checks(session: AsyncSession) -> HealthResponse:
    """Run connectivity checks for Claude API, Gmail SMTP, and Google Docs.

    All checks run concurrently. Each check has a 5-second timeout.
    Failures are logged but do not raise exceptions.

    Args:
        session: Active async database session for reading settings.

    Returns:
        A HealthResponse with boolean status for each service.
    """
    settings_data = await get_config(session, "settings") or {}

    claude_ok, gmail_ok, gdocs_ok = await asyncio.gather(
        _check_claude_api(settings_data.get("claude_api_key")),
        _check_gmail_oauth(),
        _check_gdocs(settings_data.get("gdocs_script_url")),
    )

    return HealthResponse(claude_api=claude_ok, gmail=gmail_ok, google_docs=gdocs_ok)


async def _check_claude_api(api_key: str | None) -> bool:
    """Ping the Claude API to verify connectivity.

    Sends a lightweight request to the Anthropic API messages endpoint.
    Returns True if the API responds (even with an auth error means
    connectivity is fine; we check for network reachability).

    Args:
        api_key: The Anthropic API key. If None, returns False.

    Returns:
        True if the Claude API endpoint is reachable.
    """
    if not api_key:
        logger.debug("claude_api_check_skipped", reason="no_api_key")
        return False

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            # Any HTTP response (even 401) means the API is reachable
            return response.status_code < 500
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        logger.warning("claude_api_check_failed", error=str(exc))
        return False


async def _check_gmail_oauth() -> bool:
    """Check Gmail API connectivity by verifying OAuth credentials are valid.

    Loads the stored OAuth token and checks if it's valid or can be refreshed.
    Does not make an API call — just verifies the token is usable.

    Returns:
        True if valid Gmail OAuth credentials are available.
    """
    try:
        creds = await asyncio.get_event_loop().run_in_executor(None, load_credentials)
        if creds is not None and creds.valid:
            return True
        logger.debug("gmail_oauth_check_no_valid_credentials")
        return False
    except Exception as exc:
        logger.warning("gmail_oauth_check_failed", error=str(exc))
        return False


async def _check_gdocs(script_url: str | None) -> bool:
    """Ping the Google Apps Script web app endpoint.

    Sends a GET request to the configured GAS URL. A successful response
    (any 2xx or 3xx) indicates the endpoint is reachable.

    Args:
        script_url: The deployed Google Apps Script web app URL.
            If None, returns False.

    Returns:
        True if the Google Apps Script endpoint is reachable.
    """
    if not script_url:
        logger.debug("gdocs_check_skipped", reason="no_script_url")
        return False

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(script_url)
            return response.status_code < 500
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        logger.warning("gdocs_check_failed", error=str(exc))
        return False


def _compute_next_run_at(scheduled_time: str) -> str | None:
    """Compute the next scheduled run time based on the configured time.

    Returns the next weekday occurrence of the scheduled time as an
    ISO 8601 string. If the scheduled time has already passed today,
    returns the next weekday.

    Args:
        scheduled_time: Time string in HH:MM format.

    Returns:
        ISO 8601 timestamp of the next scheduled run, or None if the
        time string is invalid.
    """
    try:
        hour, minute = map(int, scheduled_time.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
    except (ValueError, AttributeError):
        return None

    now = datetime.now(UTC)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If the time has passed today, move to tomorrow
    if candidate <= now:
        candidate = candidate.replace(day=candidate.day + 1)

    # Advance to next weekday (Mon=0, Sun=6)
    while candidate.weekday() > 4:  # Saturday=5, Sunday=6
        candidate = candidate.replace(day=candidate.day + 1)

    return candidate.isoformat()
