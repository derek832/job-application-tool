"""
Configuration API endpoints for the LinkedIn Job Automator.

Provides GET/PUT endpoints for managing search config, goals profile,
user profile, and system settings. All endpoints require Bearer token
authentication. The GET /config/settings endpoint redacts secret fields.

Includes a LAN IP auto-detection endpoint that resolves the host machine's
LAN-routable IP address from within the Docker container.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
from src.db.config_repo import get_config, set_config
from src.db.database import get_session

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
