"""
Blacklist entry repository — CRUD operations for the blacklist_entries table.

Provides async functions to manage blacklist entries (companies and title
patterns) and to build a ``BlacklistConfig`` from the database for use in
pipeline filtering.

All functions are async and operate on an ``AsyncSession`` passed by the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import BlacklistEntry
from src.pipeline.blacklist_filter import BlacklistConfig

logger = structlog.get_logger(__name__)


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


async def get_all_entries(session: AsyncSession) -> list[BlacklistEntry]:
    """Fetch all blacklist entries.

    Args:
        session: Active async database session.

    Returns:
        List of all ``BlacklistEntry`` records.
    """
    result = await session.execute(select(BlacklistEntry).order_by(BlacklistEntry.created_at))
    return list(result.scalars().all())


async def get_entries_by_type(session: AsyncSession, entry_type: str) -> list[BlacklistEntry]:
    """Fetch blacklist entries filtered by type.

    Args:
        session: Active async database session.
        entry_type: Either 'company' or 'title_pattern'.

    Returns:
        List of ``BlacklistEntry`` records matching the given type.
    """
    result = await session.execute(
        select(BlacklistEntry)
        .where(BlacklistEntry.entry_type == entry_type)
        .order_by(BlacklistEntry.created_at)
    )
    return list(result.scalars().all())


async def add_entry(session: AsyncSession, entry_type: str, value: str) -> BlacklistEntry:
    """Add a new blacklist entry.

    Creates a new entry with the current timestamp and hit_count of 0.

    Args:
        session: Active async database session.
        entry_type: Either 'company' or 'title_pattern'.
        value: The blacklist string (company name or title pattern).

    Returns:
        The newly created ``BlacklistEntry`` instance.
    """
    now = _utcnow_iso()
    entry = BlacklistEntry(
        entry_type=entry_type,
        value=value,
        created_at=now,
        hit_count=0,
    )
    session.add(entry)
    await session.flush()

    logger.info(
        "blacklist_entry_added",
        entry_type=entry_type,
        value=value,
    )
    return entry


async def remove_entry(session: AsyncSession, entry_type: str, value: str) -> bool:
    """Remove a blacklist entry by type and value.

    Args:
        session: Active async database session.
        entry_type: Either 'company' or 'title_pattern'.
        value: The blacklist string to remove.

    Returns:
        True if the entry was found and removed, False otherwise.
    """
    result = await session.execute(
        select(BlacklistEntry).where(
            BlacklistEntry.entry_type == entry_type,
            BlacklistEntry.value == value,
        )
    )
    entry = result.scalar_one_or_none()

    if entry is None:
        logger.debug(
            "blacklist_entry_not_found",
            entry_type=entry_type,
            value=value,
        )
        return False

    await session.delete(entry)
    await session.flush()

    logger.info(
        "blacklist_entry_removed",
        entry_type=entry_type,
        value=value,
    )
    return True


async def increment_hit_count(session: AsyncSession, entry_id: int) -> None:
    """Increment the hit_count for a blacklist entry by 1.

    Args:
        session: Active async database session.
        entry_id: The primary key of the blacklist entry to update.
    """
    result = await session.execute(select(BlacklistEntry).where(BlacklistEntry.id == entry_id))
    entry = result.scalar_one_or_none()

    if entry is None:
        logger.warning("blacklist_entry_not_found_for_increment", entry_id=entry_id)
        return

    entry.hit_count += 1
    await session.flush()

    logger.debug(
        "blacklist_hit_count_incremented",
        entry_id=entry_id,
        new_count=entry.hit_count,
    )


async def build_blacklist_config(session: AsyncSession) -> BlacklistConfig:
    """Build a BlacklistConfig from all database entries for pipeline use.

    Queries all blacklist entries and separates them into companies and
    title patterns, returning a ``BlacklistConfig`` ready for use with
    ``check_blacklist()``.

    Args:
        session: Active async database session.

    Returns:
        A ``BlacklistConfig`` populated with all current blacklist entries.
    """
    entries = await get_all_entries(session)

    companies: list[str] = []
    title_patterns: list[str] = []

    for entry in entries:
        if entry.entry_type == "company":
            companies.append(entry.value)
        elif entry.entry_type == "title_pattern":
            title_patterns.append(entry.value)

    logger.debug(
        "blacklist_config_built",
        company_count=len(companies),
        title_pattern_count=len(title_patterns),
    )

    return BlacklistConfig(companies=companies, title_patterns=title_patterns)
