"""
Configuration API endpoints for the LinkedIn Job Automator.

Provides GET/PUT endpoints for managing search config, goals profile,
user profile, and system settings. All endpoints require Bearer token
authentication. The GET /config/settings endpoint redacts secret fields.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
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
