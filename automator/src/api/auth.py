"""
Authentication dependency for the LinkedIn Job Automator API.

Provides a FastAPI dependency that validates the Bearer token from the
``Authorization`` header against the stored API token in the config table.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config_repo import get_config
from src.db.database import get_session

_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Validate the Bearer token against the stored API token.

    Args:
        credentials: The HTTP Bearer credentials extracted from the request.
        session: An active async SQLAlchemy session.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or does not match
            the stored API token.
    """
    stored_token = await get_config(session, "api_token")

    if stored_token is None or credentials.credentials != stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
