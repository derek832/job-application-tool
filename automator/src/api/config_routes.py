"""
Configuration API endpoints for the LinkedIn Job Automator.

Provides GET/PUT endpoints for managing search config, goals profile,
user profile, system settings, and ntfy notification configuration.
All endpoints require Bearer token authentication. The GET /config/settings
endpoint redacts secret fields. The GET /config/ntfy endpoint omits the
api_token for security.
"""

from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import verify_token
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
_LAN_PATTERN = re.compile(
    r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9\-\.]+)(:\d{1,5})?$"
)


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
