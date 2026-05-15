"""
Database layer for the LinkedIn Job Automator.

Public API:
    - ``models`` — SQLAlchemy ORM models (JobRecord, StatusTransition, etc.)
    - ``database`` — Engine factory, session dependency, and DB init logic
    - ``config_repo`` — Typed get/set access to the config table
"""

from src.db.config_repo import VALID_CONFIG_KEYS, ConfigKey, get_config, set_config
from src.db.database import build_engine, get_session, init_db
from src.db.models import (
    VALID_STATUSES,
    Base,
    Config,
    JobRecord,
    NotificationLog,
    StatusTransition,
)

__all__ = [
    "Base",
    "Config",
    "ConfigKey",
    "JobRecord",
    "NotificationLog",
    "StatusTransition",
    "VALID_CONFIG_KEYS",
    "VALID_STATUSES",
    "build_engine",
    "get_config",
    "get_session",
    "init_db",
    "set_config",
]
