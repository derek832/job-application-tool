"""
Ntfy topic auto-generation and persistence.

Handles first-time topic generation using cryptographically secure random
hex strings and stores them in the config table for reuse on subsequent starts.

Validates: Requirements 2.1, 2.2, 2.3
"""

from __future__ import annotations

import secrets

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config_repo import get_config, set_config

logger = structlog.get_logger(__name__)


async def ensure_topics(session: AsyncSession) -> tuple[str, str]:
    """Return (urgent_topic, info_topic), generating if absent.

    Uses secrets.token_hex(8) for 16-char hex strings.
    Stores in config table under keys 'ntfy_urgent_topic' and 'ntfy_info_topic'.

    Args:
        session: An active async SQLAlchemy session.

    Returns:
        A tuple of (urgent_topic, info_topic) strings.
    """
    urgent = await get_config(session, "ntfy_urgent_topic")
    info = await get_config(session, "ntfy_info_topic")

    if urgent and info:
        logger.info("ntfy_topics_loaded", urgent_topic=urgent, info_topic=info)
        return (urgent, info)

    # Generate new topics for any that are missing
    urgent = urgent or secrets.token_hex(8)  # 16 hex chars
    info = info or secrets.token_hex(8)

    await set_config(session, "ntfy_urgent_topic", urgent)
    await set_config(session, "ntfy_info_topic", info)
    await session.commit()

    logger.info("ntfy_topics_generated", urgent_topic=urgent, info_topic=info)
    return (urgent, info)
