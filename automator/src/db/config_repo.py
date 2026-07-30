"""
Configuration repository for the LinkedIn Job Automator.

Provides typed get/set access to the ``config`` table, storing values as
JSON-encoded strings. All valid configuration keys are defined as a
``Literal`` type to prevent typos and invalid key usage at the type level.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Config

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Valid configuration keys
# ---------------------------------------------------------------------------

ConfigKey = Literal[
    "api_token",
    "blacklist_config",
    "goals_profile",
    "lan_base_url",
    "local_score_cutoff",
    "ntfy_enabled",
    "ntfy_info_topic",
    "ntfy_server_url",
    "ntfy_urgent_topic",
    "schedule_config",
    "search_config",
    "settings",
    "shadow_mode_enabled",
    "system_state",
    "user_profile",
]

VALID_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "api_token",
        "blacklist_config",
        "goals_profile",
        "lan_base_url",
        "local_score_cutoff",
        "ntfy_enabled",
        "ntfy_info_topic",
        "ntfy_server_url",
        "ntfy_urgent_topic",
        "schedule_config",
        "search_config",
        "settings",
        "shadow_mode_enabled",
        "system_state",
        "user_profile",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_config(session: AsyncSession, key: ConfigKey) -> Any | None:
    """Retrieve a configuration value by key.

    Looks up the given key in the ``config`` table and deserializes the
    JSON-encoded value back into a Python object.

    Args:
        session: An active async SQLAlchemy session.
        key: One of the valid configuration keys.

    Returns:
        The deserialized Python object, or ``None`` if the key does not exist
        in the database.
    """
    logger.debug("get_config", key=key)

    result = await session.execute(select(Config).where(Config.key == key))
    row = result.scalar_one_or_none()

    if row is None:
        logger.debug("config_key_not_found", key=key)
        return None

    value = json.loads(row.value)
    logger.debug("config_key_found", key=key)
    return value


async def set_config(session: AsyncSession, key: ConfigKey, value: Any) -> None:
    """Store a configuration value, serialized as JSON.

    Performs an upsert: if the key already exists, its value and
    ``updated_at`` timestamp are updated in place. If the key does not
    exist, a new row is inserted.

    Args:
        session: An active async SQLAlchemy session.
        key: One of the valid configuration keys.
        value: Any JSON-serializable Python object to store.
    """
    now = datetime.now(UTC).isoformat()
    json_value = json.dumps(value)

    logger.info("set_config", key=key)

    result = await session.execute(select(Config).where(Config.key == key))
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.value = json_value
        existing.updated_at = now
        logger.debug("config_key_updated", key=key)
    else:
        new_config = Config(key=key, value=json_value, updated_at=now)
        session.add(new_config)
        logger.debug("config_key_created", key=key)

    await session.flush()
