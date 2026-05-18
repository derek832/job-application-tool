"""
Configuration API endpoints for the LinkedIn Job Automator.

Provides GET/PUT endpoints for managing search config, goals profile,
user profile, system settings, ntfy notification configuration, and
blacklist configuration. All endpoints require Bearer token authentication.
The GET /config/settings endpoint redacts secret fields. The GET /config/ntfy
endpoint omits the api_token for security.

Includes a LAN IP auto-detection endpoint that resolves the host machine's
LAN-routable IP address from within the Docker container.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import verify_token
from src.api.lan_detect import (
    LanDetectionError,
    detect_lan_ip,
    format_base_url,
    is_ipv4,
    validate_lan_ip,
)
from src.api.schemas import (
    GoalsProfile,
    GoalsProfileUpdate,
    SearchConfig,
    SearchConfigUpdate,
    Settings,
    SettingsUpdate,
    UserProfile,
    UserProfileUpdate,
)
from src.db.blacklist_repo import add_entry, get_all_entries, get_entries_by_type, remove_entry
from src.db.config_repo import get_config, set_config
from src.db.database import get_session
from src.integrations.ntfy_client import NtfyAction, NtfyPayload, NtfySettings, publish
from src.scheduler.schedule_manager import (
    ScheduleConfig,
    apply_schedule,
    compute_next_run_times,
    validate_schedule_config,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/config", dependencies=[Depends(verify_token)])


# ---------------------------------------------------------------------------
# Pydantic models for LAN detection
# ---------------------------------------------------------------------------


class LanDetectResponse(BaseModel):
    """Successful LAN detection response."""

    lan_base_url: str  # e.g., "http://192.168.1.100:7432"
    port: int  # Always 7432


class LanDetectError(BaseModel):
    """Error response when detection fails."""

    error: str  # Human-readable error message


# ---------------------------------------------------------------------------
# LAN Detection
# ---------------------------------------------------------------------------

LAN_PORT = 7432


@router.get("/lan-detect")
async def get_lan_detect() -> LanDetectResponse:
    """Detect the host machine's LAN IP address.

    Resolves the LAN-routable IP via the LAN_IP environment variable
    (if set) or DNS resolution of host.docker.internal. Validates that
    the resolved address is a private IPv4 address suitable for LAN use.

    Non-IPv4 values (hostnames) bypass validation and are accepted as-is.

    Returns:
        LanDetectResponse with the formatted base URL and port.

    Raises:
        HTTP 503: DNS resolution failed or timed out.
        HTTP 422: Resolved IP is not a valid LAN address.
    """
    try:
        detected = await detect_lan_ip()
    except LanDetectionError as exc:
        logger.warning("lan_detect_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"error": str(exc)},
        )

    # If the detected value is an IPv4 address, validate it
    if is_ipv4(detected):
        error_msg = validate_lan_ip(detected)
        if error_msg is not None:
            logger.warning("lan_detect_invalid_ip", address=detected, error=error_msg)
            return JSONResponse(
                status_code=422,
                content={"error": error_msg},
            )

    # Valid private IP or hostname — return formatted response
    base_url = format_base_url(detected, LAN_PORT)
    logger.info("lan_detect_success", base_url=base_url)
    return LanDetectResponse(lan_base_url=base_url, port=LAN_PORT)


# ---------------------------------------------------------------------------
# Search Config
# ---------------------------------------------------------------------------


@router.get("/search", response_model=SearchConfig)
async def get_search_config(
    session: AsyncSession = Depends(get_session),
) -> SearchConfig:
    """Retrieve the current LinkedIn search configuration.

    Returns the stored search parameters or defaults if not yet configured.
    """
    logger.info("get_search_config")
    data = await get_config(session, "search_config")
    if data is None:
        return SearchConfig()
    return SearchConfig(**data)


@router.put("/search", response_model=SearchConfig)
async def put_search_config(
    body: SearchConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> SearchConfig:
    """Update the LinkedIn search configuration.

    Validates the request body against the SearchConfigUpdate schema,
    persists it to the config store, and returns the saved configuration.
    """
    logger.info("put_search_config")
    data = body.model_dump()
    await set_config(session, "search_config", data)
    return SearchConfig(**data)


# ---------------------------------------------------------------------------
# Goals Profile
# ---------------------------------------------------------------------------


@router.get("/goals", response_model=GoalsProfile)
async def get_goals_profile(
    session: AsyncSession = Depends(get_session),
) -> GoalsProfile:
    """Retrieve the current career goals profile.

    Returns the stored goals profile or defaults if not yet configured.
    """
    logger.info("get_goals_profile")
    data = await get_config(session, "goals_profile")
    if data is None:
        return GoalsProfile()
    return GoalsProfile(**data)


@router.put("/goals", response_model=GoalsProfile)
async def put_goals_profile(
    body: GoalsProfileUpdate,
    session: AsyncSession = Depends(get_session),
) -> GoalsProfile:
    """Update the career goals profile.

    Validates the request body against the GoalsProfileUpdate schema,
    persists it to the config store, and returns the saved configuration.
    """
    logger.info("put_goals_profile")
    data = body.model_dump()
    await set_config(session, "goals_profile", data)
    return GoalsProfile(**data)


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------


@router.get("/profile", response_model=UserProfile)
async def get_user_profile(
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    """Retrieve the current user profile for application form filling.

    Returns the stored user profile or defaults if not yet configured.
    """
    logger.info("get_user_profile")
    data = await get_config(session, "user_profile")
    if data is None:
        return UserProfile()
    return UserProfile(**data)


@router.put("/profile", response_model=UserProfile)
async def put_user_profile(
    body: UserProfileUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    """Update the user profile for application form filling.

    Validates the request body against the UserProfileUpdate schema,
    persists it to the config store, and returns the saved configuration.
    """
    logger.info("put_user_profile")
    data = body.model_dump()
    await set_config(session, "user_profile", data)
    return UserProfile(**data)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=Settings)
async def get_settings(
    session: AsyncSession = Depends(get_session),
) -> Settings:
    """Retrieve system settings with secret fields redacted.

    Secret fields (claude_api_key, gmail_user, gmail_app_password) are
    serialized as ``"***"`` via the Settings schema's field_serializer to
    prevent credential leakage in API responses.
    """
    logger.info("get_settings")
    data = await get_config(session, "settings")
    if data is None:
        return Settings()
    return Settings(**data)


@router.put("/settings", response_model=Settings)
async def put_settings(
    body: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> Settings:
    """Update system settings.

    Validates the request body against the SettingsUpdate schema. Merges
    the update with existing settings (preserving fields not included in
    the request body) and persists the result. Returns the updated settings
    with secret fields redacted.
    """
    logger.info("put_settings")
    existing = await get_config(session, "settings") or {}
    update_data = body.model_dump(exclude_none=True)
    merged = {**existing, **update_data}
    await set_config(session, "settings", merged)
    return Settings(**merged)


# ---------------------------------------------------------------------------
# Ntfy Configuration
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(r"^https?://")
_LAN_PATTERN = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9\-\.]+)(:\d{1,5})?$")


class NtfyConfigResponse(BaseModel):
    """Response schema for GET /config/ntfy.

    Returns the current ntfy configuration. The api_token is never included
    in the response for security reasons.

    Attributes:
        ntfy_enabled: Whether ntfy notifications are enabled.
        ntfy_server_url: The ntfy server URL.
        urgent_topic: The auto-generated urgent topic name (read-only).
        info_topic: The auto-generated info topic name (read-only).
        lan_base_url: The LAN base URL for action button callbacks.
    """

    model_config = ConfigDict(strict=False)

    ntfy_enabled: bool = False
    ntfy_server_url: str = "https://ntfy.sh"
    urgent_topic: str | None = None
    info_topic: str | None = None
    lan_base_url: str | None = None


class NtfyConfigUpdate(BaseModel):
    """Request body for PUT /config/ntfy.

    Accepts ntfy_enabled, ntfy_server_url, and lan_base_url. Topics are
    read-only (auto-generated) and cannot be updated via this endpoint.

    Attributes:
        ntfy_enabled: Whether ntfy notifications are enabled.
        ntfy_server_url: The ntfy server URL (must start with http:// or https://).
        lan_base_url: The LAN base URL for action button callbacks (valid IPv4
            or hostname with optional port, or null to disable).
    """

    model_config = ConfigDict(strict=False)

    ntfy_enabled: bool
    ntfy_server_url: str
    lan_base_url: str | None = None

    @field_validator("ntfy_server_url")
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        """Validate that the server URL starts with http:// or https://."""
        if not _URL_PATTERN.match(v):
            raise ValueError("Server URL must start with http:// or https://")
        return v

    @field_validator("lan_base_url")
    @classmethod
    def validate_lan_base_url(cls, v: str | None) -> str | None:
        """Validate that the LAN address is a valid IPv4 or hostname with optional port."""
        if v is None:
            return None
        # Strip any protocol prefix for validation of the host:port portion
        # The LAN base URL is stored as a full URL (http://host:port)
        # but we validate the host:port portion
        stripped = v
        if stripped.startswith("http://"):
            stripped = stripped[7:]
        elif stripped.startswith("https://"):
            stripped = stripped[8:]
        # Remove trailing slash if present
        stripped = stripped.rstrip("/")
        if not _LAN_PATTERN.match(stripped):
            raise ValueError(
                "LAN address must be a valid IPv4 address or hostname "
                "with an optional port (e.g., 192.168.1.100:7432)"
            )
        return v


@router.get("/ntfy", response_model=NtfyConfigResponse)
async def get_ntfy_config(
    session: AsyncSession = Depends(get_session),
) -> NtfyConfigResponse:
    """Retrieve the current ntfy notification configuration.

    Returns ntfy_enabled, ntfy_server_url, urgent_topic, info_topic, and
    lan_base_url. The api_token is intentionally omitted for security.
    """
    logger.info("get_ntfy_config")

    ntfy_enabled = await get_config(session, "ntfy_enabled")
    ntfy_server_url = await get_config(session, "ntfy_server_url")
    urgent_topic = await get_config(session, "ntfy_urgent_topic")
    info_topic = await get_config(session, "ntfy_info_topic")
    lan_base_url = await get_config(session, "lan_base_url")

    return NtfyConfigResponse(
        ntfy_enabled=ntfy_enabled if ntfy_enabled is not None else False,
        ntfy_server_url=ntfy_server_url or "https://ntfy.sh",
        urgent_topic=urgent_topic,
        info_topic=info_topic,
        lan_base_url=lan_base_url,
    )


@router.put("/ntfy", response_model=NtfyConfigResponse)
async def put_ntfy_config(
    body: NtfyConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> NtfyConfigResponse:
    """Update the ntfy notification configuration.

    Accepts ntfy_enabled, ntfy_server_url, and lan_base_url. Topics are
    read-only and not updatable via this endpoint. Validates that the server
    URL starts with http:// or https:// and that the LAN address (when
    provided) is a valid IPv4 or hostname with optional port.

    Returns the full ntfy configuration after the update.
    """
    logger.info("put_ntfy_config")

    await set_config(session, "ntfy_enabled", body.ntfy_enabled)
    await set_config(session, "ntfy_server_url", body.ntfy_server_url)
    await set_config(session, "lan_base_url", body.lan_base_url)

    # Read back topics (read-only, not updatable)
    urgent_topic = await get_config(session, "ntfy_urgent_topic")
    info_topic = await get_config(session, "ntfy_info_topic")

    return NtfyConfigResponse(
        ntfy_enabled=body.ntfy_enabled,
        ntfy_server_url=body.ntfy_server_url,
        urgent_topic=urgent_topic,
        info_topic=info_topic,
        lan_base_url=body.lan_base_url,
    )


# ---------------------------------------------------------------------------
# Schedule Configuration — Pydantic models
# ---------------------------------------------------------------------------


class ScheduleConfigResponse(BaseModel):
    """Response schema for GET /config/schedule.

    Attributes:
        mode: Scheduling mode — "specific_times" or "interval".
        times: List of HH:MM strings (specific_times mode).
        interval_hours: Hours between runs (interval mode).
        window_start: HH:MM start of daily window (interval mode).
        window_end: HH:MM end of daily window (interval mode).
        weekend_runs: Whether to run on weekends.
        timezone: IANA timezone string.
        quiet_hours_start: HH:MM start of quiet hours, or null.
        quiet_hours_end: HH:MM end of quiet hours, or null.
    """

    mode: Literal["specific_times", "interval"] = "specific_times"
    times: list[str] = []
    interval_hours: int = 2
    window_start: str = "08:00"
    window_end: str = "20:00"
    weekend_runs: bool = False
    timezone: str = "America/New_York"
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


class ScheduleConfigUpdate(BaseModel):
    """Request body for PUT /config/schedule.

    Attributes:
        mode: Scheduling mode — "specific_times" or "interval".
        times: List of HH:MM strings (specific_times mode).
        interval_hours: Hours between runs (interval mode).
        window_start: HH:MM start of daily window (interval mode).
        window_end: HH:MM end of daily window (interval mode).
        weekend_runs: Whether to run on weekends.
        timezone: IANA timezone string.
        quiet_hours_start: HH:MM start of quiet hours, or null.
        quiet_hours_end: HH:MM end of quiet hours, or null.
    """

    mode: Literal["specific_times", "interval"]
    times: list[str] = []
    interval_hours: int = 2
    window_start: str = "08:00"
    window_end: str = "20:00"
    weekend_runs: bool = False
    timezone: str = "America/New_York"
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


class ScheduleNextResponse(BaseModel):
    """Response schema for GET /schedule/next.

    Attributes:
        next_runs: List of ISO 8601 datetime strings for upcoming run times.
    """

    next_runs: list[str]


# ---------------------------------------------------------------------------
# Schedule Configuration Endpoints
# ---------------------------------------------------------------------------


@router.get("/schedule", response_model=ScheduleConfigResponse)
async def get_schedule_config(
    session: AsyncSession = Depends(get_session),
) -> ScheduleConfigResponse:
    """Retrieve the current schedule configuration.

    Returns the stored schedule config or defaults if not yet configured.
    """
    logger.info("get_schedule_config")
    data = await get_config(session, "schedule_config")
    if data is None:
        return ScheduleConfigResponse()
    return ScheduleConfigResponse(**data)


@router.put("/schedule", response_model=ScheduleConfigResponse)
async def put_schedule_config(
    body: ScheduleConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ScheduleConfigResponse | JSONResponse:
    """Update the schedule configuration with hot-reload.

    Validates the new schedule config. If valid, persists it to the config
    store and calls apply_schedule() to update APScheduler triggers without
    requiring a restart.

    Returns:
        The saved schedule configuration on success.
        422 response if the config is invalid (zero times, invalid formats).
    """
    logger.info("put_schedule_config", mode=body.mode)

    # Build ScheduleConfig dataclass from request body
    config = ScheduleConfig(
        mode=body.mode,
        times=body.times,
        interval_hours=body.interval_hours,
        window_start=body.window_start,
        window_end=body.window_end,
        weekend_runs=body.weekend_runs,
        timezone=body.timezone,
        quiet_hours_start=body.quiet_hours_start,
        quiet_hours_end=body.quiet_hours_end,
    )

    # Validate the config — returns 422 on failure
    try:
        validate_schedule_config(config)
    except ValueError as exc:
        logger.warning("schedule_config_validation_failed", error=str(exc))
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )

    # Persist to database
    data = body.model_dump()
    await set_config(session, "schedule_config", data)

    # Hot-reload: apply the new schedule to APScheduler
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        try:
            apply_schedule(scheduler, config)
            logger.info("schedule_hot_reload_success")
        except Exception as exc:
            logger.error("schedule_hot_reload_failed", error=str(exc))
    else:
        logger.warning("schedule_hot_reload_skipped", reason="scheduler not available")

    return ScheduleConfigResponse(**data)


# ---------------------------------------------------------------------------
# Schedule Next Runs — separate router (not under /config prefix)
# ---------------------------------------------------------------------------

schedule_router = APIRouter(prefix="/schedule", dependencies=[Depends(verify_token)])


@schedule_router.get("/next", response_model=ScheduleNextResponse)
async def get_schedule_next(
    session: AsyncSession = Depends(get_session),
) -> ScheduleNextResponse | JSONResponse:
    """Compute and return the next 3 upcoming scheduled run times.

    Uses the current schedule configuration to compute future run times.
    Returns 422 if the schedule config is invalid or has zero times.
    """
    logger.info("get_schedule_next")

    data = await get_config(session, "schedule_config")
    if data is None:
        # No schedule configured — return empty list
        return ScheduleNextResponse(next_runs=[])

    # Build ScheduleConfig from stored data
    config = ScheduleConfig(
        mode=data.get("mode", "specific_times"),
        times=data.get("times", []),
        interval_hours=data.get("interval_hours", 2),
        window_start=data.get("window_start", "08:00"),
        window_end=data.get("window_end", "20:00"),
        weekend_runs=data.get("weekend_runs", False),
        timezone=data.get("timezone", "America/New_York"),
        quiet_hours_start=data.get("quiet_hours_start"),
        quiet_hours_end=data.get("quiet_hours_end"),
    )

    # Validate before computing — return 422 for invalid configs
    try:
        validate_schedule_config(config)
    except ValueError as exc:
        logger.warning("schedule_next_validation_failed", error=str(exc))
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )

    # Compute next 3 run times from now
    now = datetime.now(UTC)
    next_times = compute_next_run_times(config, now, count=3)

    # Format as ISO 8601 strings
    next_runs = [t.isoformat() for t in next_times]

    return ScheduleNextResponse(next_runs=next_runs)


# ---------------------------------------------------------------------------
# Blacklist Configuration — Pydantic models
# ---------------------------------------------------------------------------


class BlacklistEntryResponse(BaseModel):
    """A single blacklist entry with its hit count.

    Attributes:
        value: The blacklist string (company name or title pattern).
        hit_count: Number of jobs filtered by this entry.
    """

    value: str
    hit_count: int


class BlacklistConfigResponse(BaseModel):
    """Response schema for GET /config/blacklist.

    Attributes:
        companies: List of blacklisted companies with hit counts.
        title_patterns: List of blacklisted title patterns with hit counts.
    """

    companies: list[BlacklistEntryResponse]
    title_patterns: list[BlacklistEntryResponse]


class BlacklistConfigUpdate(BaseModel):
    """Request body for PUT /config/blacklist.

    Replaces both blacklists entirely.

    Attributes:
        companies: List of company names to blacklist.
        title_patterns: List of title patterns to blacklist.
    """

    companies: list[str]
    title_patterns: list[str]


class BlacklistAddEntry(BaseModel):
    """Request body for POST /config/blacklist/companies or /titles.

    Attributes:
        value: The blacklist string to add.
    """

    value: str


# ---------------------------------------------------------------------------
# Blacklist Configuration Endpoints
# ---------------------------------------------------------------------------


@router.get("/blacklist", response_model=BlacklistConfigResponse)
async def get_blacklist_config(
    session: AsyncSession = Depends(get_session),
) -> BlacklistConfigResponse:
    """Retrieve both company and title pattern blacklists with hit counts.

    Returns all blacklist entries grouped by type, each with its value
    and the number of jobs it has filtered.
    """
    logger.info("get_blacklist_config")

    entries = await get_all_entries(session)

    companies: list[BlacklistEntryResponse] = []
    title_patterns: list[BlacklistEntryResponse] = []

    for entry in entries:
        item = BlacklistEntryResponse(value=entry.value, hit_count=entry.hit_count)
        if entry.entry_type == "company":
            companies.append(item)
        elif entry.entry_type == "title_pattern":
            title_patterns.append(item)

    return BlacklistConfigResponse(companies=companies, title_patterns=title_patterns)


@router.put("/blacklist", response_model=BlacklistConfigResponse)
async def put_blacklist_config(
    body: BlacklistConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> BlacklistConfigResponse:
    """Replace both blacklists entirely.

    Clears all existing blacklist entries and replaces them with the
    provided lists. Hit counts are reset to 0 for all new entries.

    Returns the new blacklist configuration.
    """
    logger.info(
        "put_blacklist_config",
        company_count=len(body.companies),
        title_pattern_count=len(body.title_patterns),
    )

    # Remove all existing entries
    existing = await get_all_entries(session)
    for entry in existing:
        await session.delete(entry)
    await session.flush()

    # Add new company entries
    for company in body.companies:
        await add_entry(session, "company", company)

    # Add new title pattern entries
    for pattern in body.title_patterns:
        await add_entry(session, "title_pattern", pattern)

    # Build response
    companies = [BlacklistEntryResponse(value=c, hit_count=0) for c in body.companies]
    title_patterns = [BlacklistEntryResponse(value=p, hit_count=0) for p in body.title_patterns]

    return BlacklistConfigResponse(companies=companies, title_patterns=title_patterns)


@router.post("/blacklist/companies", response_model=BlacklistEntryResponse, status_code=201)
async def add_blacklist_company(
    body: BlacklistAddEntry,
    session: AsyncSession = Depends(get_session),
) -> BlacklistEntryResponse | JSONResponse:
    """Add a company to the blacklist.

    Creates a new company blacklist entry with hit_count of 0.
    Returns 409 if the entry already exists.
    """
    logger.info("add_blacklist_company", value=body.value)

    # Check if entry already exists
    existing = await get_entries_by_type(session, "company")
    for entry in existing:
        if entry.value.lower() == body.value.lower():
            return JSONResponse(
                status_code=409,
                content={"detail": f"Company '{body.value}' is already blacklisted"},
            )

    entry = await add_entry(session, "company", body.value)
    return BlacklistEntryResponse(value=entry.value, hit_count=entry.hit_count)


@router.delete("/blacklist/companies/{entry}")
async def remove_blacklist_company(
    entry: str,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Remove a company from the blacklist.

    Args:
        entry: The company name to remove (URL-encoded if needed).

    Returns:
        200 with success message if removed.
        404 if the entry was not found.
    """
    logger.info("remove_blacklist_company", value=entry)

    removed = await remove_entry(session, "company", entry)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Company '{entry}' not found in blacklist"},
        )

    return JSONResponse(
        status_code=200,
        content={"detail": f"Company '{entry}' removed from blacklist"},
    )


@router.post("/blacklist/titles", response_model=BlacklistEntryResponse, status_code=201)
async def add_blacklist_title(
    body: BlacklistAddEntry,
    session: AsyncSession = Depends(get_session),
) -> BlacklistEntryResponse | JSONResponse:
    """Add a title pattern to the blacklist.

    Creates a new title pattern blacklist entry with hit_count of 0.
    Returns 409 if the entry already exists.
    """
    logger.info("add_blacklist_title", value=body.value)

    # Check if entry already exists
    existing = await get_entries_by_type(session, "title_pattern")
    for entry in existing:
        if entry.value.lower() == body.value.lower():
            return JSONResponse(
                status_code=409,
                content={"detail": f"Title pattern '{body.value}' is already blacklisted"},
            )

    entry = await add_entry(session, "title_pattern", body.value)
    return BlacklistEntryResponse(value=entry.value, hit_count=entry.hit_count)


@router.delete("/blacklist/titles/{entry}")
async def remove_blacklist_title(
    entry: str,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Remove a title pattern from the blacklist.

    Args:
        entry: The title pattern to remove (URL-encoded if needed).

    Returns:
        200 with success message if removed.
        404 if the entry was not found.
    """
    logger.info("remove_blacklist_title", value=entry)

    removed = await remove_entry(session, "title_pattern", entry)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Title pattern '{entry}' not found in blacklist"},
        )

    return JSONResponse(
        status_code=200,
        content={"detail": f"Title pattern '{entry}' removed from blacklist"},
    )


# ---------------------------------------------------------------------------
# Ntfy Connection Test
# ---------------------------------------------------------------------------


class NtfyTestResponse(BaseModel):
    """Response schema for POST /config/ntfy/test.

    Attributes:
        sent: Whether the test notification was published successfully.
        error: Error message if the publish failed.
        test_id: Unique ID for this test (used to confirm button press).
    """

    sent: bool
    error: str | None = None
    test_id: str | None = None


class NtfyTestStatusResponse(BaseModel):
    """Response schema for GET /config/ntfy/test/status.

    Attributes:
        confirmed: Whether the action button was pressed.
        confirmed_at: ISO 8601 timestamp of when the button was pressed.
        test_id: The test ID that was confirmed.
    """

    confirmed: bool
    confirmed_at: str | None = None
    test_id: str | None = None


@router.post("/ntfy/test", response_model=NtfyTestResponse)
async def test_ntfy_connection(
    session: AsyncSession = Depends(get_session),
) -> NtfyTestResponse | JSONResponse:
    """Send a test notification to verify ntfy connectivity.

    Publishes a test message to the urgent topic with an action button.
    When the user taps the button on their phone, it calls back to the
    /config/ntfy/test/confirm endpoint, which records the confirmation.

    Requires ntfy to be enabled and fully configured (server URL, urgent
    topic, LAN base URL, and API token).
    """
    import secrets

    logger.info("ntfy_test_requested")

    # Load ntfy config
    ntfy_enabled_raw = await get_config(session, "ntfy_enabled")
    ntfy_enabled = ntfy_enabled_raw is True or ntfy_enabled_raw == "true"

    if not ntfy_enabled:
        return JSONResponse(
            status_code=422,
            content={"detail": "Ntfy is not enabled. Enable it first."},
        )

    ntfy_server_url = await get_config(session, "ntfy_server_url")
    ntfy_urgent_topic = await get_config(session, "ntfy_urgent_topic")
    lan_base_url = await get_config(session, "lan_base_url")
    api_token = await get_config(session, "api_token")

    if not ntfy_server_url or not ntfy_urgent_topic:
        return JSONResponse(
            status_code=422,
            content={"detail": "Ntfy server URL and urgent topic must be configured."},
        )

    # Generate a unique test ID
    test_id = secrets.token_hex(8)

    # Build settings
    settings = NtfySettings(
        server_url=ntfy_server_url,
        urgent_topic=ntfy_urgent_topic,
        info_topic="",  # Not used for test
        lan_base_url=lan_base_url,
        api_token=api_token or "",
    )

    # Build action button (only if LAN base URL is configured)
    actions: list[NtfyAction] | None = None
    if lan_base_url and api_token:
        actions = [
            NtfyAction(
                action="http",
                label="✓ Confirm Connection",
                url=f"{lan_base_url}/config/ntfy/test/confirm?test_id={test_id}",
                method="POST",
                headers={"Authorization": f"Bearer {api_token}"},
            ),
        ]

    payload = NtfyPayload(
        topic=ntfy_urgent_topic,
        title="Job Automator — Connection Test",
        message="Tap the button below to confirm notifications are working.",
        priority=4,
        tags=["white_check_mark"],
        actions=actions,
    )

    result = await publish(payload, settings)

    if result.ok:
        # Store the test_id and timestamp so we can check for confirmation
        await set_config(
            session,
            "ntfy_test_pending",
            {
                "test_id": test_id,
                "sent_at": datetime.now(UTC).isoformat(),
                "confirmed": False,
                "confirmed_at": None,
            },
        )
        await session.commit()

        logger.info("ntfy_test_sent", test_id=test_id)
        return NtfyTestResponse(sent=True, test_id=test_id)
    else:
        logger.error("ntfy_test_failed", error=result.error)
        return NtfyTestResponse(sent=False, error=result.error)


@router.get("/ntfy/test/status", response_model=NtfyTestStatusResponse)
async def get_ntfy_test_status(
    session: AsyncSession = Depends(get_session),
) -> NtfyTestStatusResponse:
    """Check whether the ntfy test action button has been pressed.

    Returns the confirmation status of the most recent test notification.
    The UI polls this endpoint after sending a test to detect when the
    user taps the action button on their phone.
    """
    data = await get_config(session, "ntfy_test_pending")

    if not data or not isinstance(data, dict):
        return NtfyTestStatusResponse(confirmed=False)

    return NtfyTestStatusResponse(
        confirmed=data.get("confirmed", False),
        confirmed_at=data.get("confirmed_at"),
        test_id=data.get("test_id"),
    )


@router.post("/ntfy/test/confirm")
async def confirm_ntfy_test(
    test_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Callback endpoint for the ntfy test action button.

    When the user taps "Confirm Connection" on the test notification,
    ntfy sends a POST to this endpoint. We record the confirmation so
    the UI can detect it via polling.

    This endpoint does NOT require auth — it's called by ntfy's action
    button mechanism which includes the Bearer token in the request headers.
    The auth is handled by the verify_token dependency on the router.
    """
    logger.info("ntfy_test_confirm_received", test_id=test_id)

    data = await get_config(session, "ntfy_test_pending")

    if data and isinstance(data, dict):
        # Verify test_id matches if provided
        if test_id and data.get("test_id") != test_id:
            return JSONResponse(
                status_code=404,
                content={"detail": "Test ID does not match pending test."},
            )

        data["confirmed"] = True
        data["confirmed_at"] = datetime.now(UTC).isoformat()
        await set_config(session, "ntfy_test_pending", data)
        await session.commit()

    return JSONResponse(
        status_code=200,
        content={"detail": "Connection confirmed."},
    )
