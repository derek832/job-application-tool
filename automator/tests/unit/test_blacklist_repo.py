"""
Unit tests for the blacklist repository (automator/src/db/blacklist_repo.py).

Tests cover:
- get_all_entries returns empty list when no entries exist
- get_all_entries returns all entries
- get_entries_by_type filters correctly
- add_entry creates a new entry with correct defaults
- add_entry sets hit_count to 0 and populates created_at
- remove_entry removes an existing entry and returns True
- remove_entry returns False for non-existent entry
- increment_hit_count increments by 1 each call
- increment_hit_count handles non-existent entry gracefully
- build_blacklist_config separates companies and title_patterns

Requirements: 4.1, 4.2, 4.9
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.blacklist_repo import (
    add_entry,
    build_blacklist_config,
    get_all_entries,
    get_entries_by_type,
    increment_hit_count,
    remove_entry,
)
from src.db.models import Base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()

    await engine.dispose()


# ---------------------------------------------------------------------------
# get_all_entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_entries_empty(session: AsyncSession) -> None:
    """get_all_entries returns an empty list when no entries exist."""
    entries = await get_all_entries(session)
    assert entries == []


@pytest.mark.asyncio
async def test_get_all_entries_returns_all(session: AsyncSession) -> None:
    """get_all_entries returns all entries regardless of type."""
    await add_entry(session, "company", "Revature")
    await add_entry(session, "title_pattern", "intern")
    await add_entry(session, "company", "Infosys")
    await session.commit()

    entries = await get_all_entries(session)
    assert len(entries) == 3
    values = {e.value for e in entries}
    assert values == {"Revature", "intern", "Infosys"}


# ---------------------------------------------------------------------------
# get_entries_by_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entries_by_type_company(session: AsyncSession) -> None:
    """get_entries_by_type returns only entries matching the given type."""
    await add_entry(session, "company", "Revature")
    await add_entry(session, "title_pattern", "intern")
    await add_entry(session, "company", "Wipro")
    await session.commit()

    companies = await get_entries_by_type(session, "company")
    assert len(companies) == 2
    assert all(e.entry_type == "company" for e in companies)
    assert {e.value for e in companies} == {"Revature", "Wipro"}


@pytest.mark.asyncio
async def test_get_entries_by_type_title_pattern(session: AsyncSession) -> None:
    """get_entries_by_type returns only title_pattern entries."""
    await add_entry(session, "company", "Revature")
    await add_entry(session, "title_pattern", "intern")
    await add_entry(session, "title_pattern", "junior")
    await session.commit()

    patterns = await get_entries_by_type(session, "title_pattern")
    assert len(patterns) == 2
    assert all(e.entry_type == "title_pattern" for e in patterns)
    assert {e.value for e in patterns} == {"intern", "junior"}


@pytest.mark.asyncio
async def test_get_entries_by_type_empty(session: AsyncSession) -> None:
    """get_entries_by_type returns empty list when no entries of that type exist."""
    await add_entry(session, "company", "Revature")
    await session.commit()

    patterns = await get_entries_by_type(session, "title_pattern")
    assert patterns == []


# ---------------------------------------------------------------------------
# add_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_entry_creates_with_defaults(session: AsyncSession) -> None:
    """add_entry creates an entry with hit_count=0 and a populated created_at."""
    entry = await add_entry(session, "company", "Revature")
    await session.commit()

    assert entry.entry_type == "company"
    assert entry.value == "Revature"
    assert entry.hit_count == 0
    assert entry.created_at is not None
    assert len(entry.created_at) > 0


@pytest.mark.asyncio
async def test_add_entry_assigns_id(session: AsyncSession) -> None:
    """add_entry assigns an auto-incremented ID."""
    entry = await add_entry(session, "title_pattern", "intern")
    await session.commit()

    assert entry.id is not None
    assert entry.id > 0


@pytest.mark.asyncio
async def test_add_multiple_entries(session: AsyncSession) -> None:
    """Multiple entries can be added and retrieved."""
    e1 = await add_entry(session, "company", "Revature")
    e2 = await add_entry(session, "company", "Infosys")
    e3 = await add_entry(session, "title_pattern", "intern")
    await session.commit()

    assert e1.id != e2.id != e3.id
    entries = await get_all_entries(session)
    assert len(entries) == 3


# ---------------------------------------------------------------------------
# remove_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_entry_existing(session: AsyncSession) -> None:
    """remove_entry removes an existing entry and returns True."""
    await add_entry(session, "company", "Revature")
    await session.commit()

    result = await remove_entry(session, "company", "Revature")
    await session.commit()

    assert result is True
    entries = await get_all_entries(session)
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_remove_entry_nonexistent(session: AsyncSession) -> None:
    """remove_entry returns False when the entry doesn't exist."""
    result = await remove_entry(session, "company", "NonExistent")
    assert result is False


@pytest.mark.asyncio
async def test_remove_entry_wrong_type(session: AsyncSession) -> None:
    """remove_entry returns False when type doesn't match even if value exists."""
    await add_entry(session, "company", "Revature")
    await session.commit()

    # Try to remove as title_pattern — should fail
    result = await remove_entry(session, "title_pattern", "Revature")
    assert result is False

    # Original entry should still exist
    entries = await get_all_entries(session)
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_remove_entry_only_removes_target(session: AsyncSession) -> None:
    """remove_entry only removes the specified entry, leaving others intact."""
    await add_entry(session, "company", "Revature")
    await add_entry(session, "company", "Infosys")
    await add_entry(session, "title_pattern", "intern")
    await session.commit()

    result = await remove_entry(session, "company", "Revature")
    await session.commit()

    assert result is True
    entries = await get_all_entries(session)
    assert len(entries) == 2
    values = {e.value for e in entries}
    assert "Revature" not in values
    assert "Infosys" in values
    assert "intern" in values


# ---------------------------------------------------------------------------
# increment_hit_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_hit_count_single(session: AsyncSession) -> None:
    """increment_hit_count increments hit_count by 1."""
    entry = await add_entry(session, "company", "Revature")
    await session.commit()
    assert entry.hit_count == 0

    await increment_hit_count(session, entry.id)
    await session.commit()

    # Re-fetch to verify
    entries = await get_entries_by_type(session, "company")
    assert entries[0].hit_count == 1


@pytest.mark.asyncio
async def test_increment_hit_count_multiple(session: AsyncSession) -> None:
    """increment_hit_count increments correctly when called multiple times."""
    entry = await add_entry(session, "title_pattern", "intern")
    await session.commit()

    await increment_hit_count(session, entry.id)
    await increment_hit_count(session, entry.id)
    await increment_hit_count(session, entry.id)
    await session.commit()

    entries = await get_entries_by_type(session, "title_pattern")
    assert entries[0].hit_count == 3


@pytest.mark.asyncio
async def test_increment_hit_count_nonexistent_entry(session: AsyncSession) -> None:
    """increment_hit_count handles non-existent entry gracefully (no error)."""
    # Should not raise — just logs a warning
    await increment_hit_count(session, 9999)


@pytest.mark.asyncio
async def test_increment_hit_count_independent(session: AsyncSession) -> None:
    """Incrementing one entry's hit_count doesn't affect others."""
    e1 = await add_entry(session, "company", "Revature")
    e2 = await add_entry(session, "company", "Infosys")
    await session.commit()

    await increment_hit_count(session, e1.id)
    await increment_hit_count(session, e1.id)
    await session.commit()

    entries = await get_entries_by_type(session, "company")
    entry_map = {e.value: e.hit_count for e in entries}
    assert entry_map["Revature"] == 2
    assert entry_map["Infosys"] == 0


# ---------------------------------------------------------------------------
# build_blacklist_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_blacklist_config_empty(session: AsyncSession) -> None:
    """build_blacklist_config returns empty lists when no entries exist."""
    config = await build_blacklist_config(session)
    assert config.companies == []
    assert config.title_patterns == []


@pytest.mark.asyncio
async def test_build_blacklist_config_separates_types(session: AsyncSession) -> None:
    """build_blacklist_config correctly separates companies and title_patterns."""
    await add_entry(session, "company", "Revature")
    await add_entry(session, "company", "Infosys")
    await add_entry(session, "title_pattern", "intern")
    await add_entry(session, "title_pattern", "junior")
    await add_entry(session, "title_pattern", "entry level")
    await session.commit()

    config = await build_blacklist_config(session)
    assert set(config.companies) == {"Revature", "Infosys"}
    assert set(config.title_patterns) == {"intern", "junior", "entry level"}


@pytest.mark.asyncio
async def test_build_blacklist_config_only_companies(session: AsyncSession) -> None:
    """build_blacklist_config works with only company entries."""
    await add_entry(session, "company", "Wipro")
    await session.commit()

    config = await build_blacklist_config(session)
    assert config.companies == ["Wipro"]
    assert config.title_patterns == []


@pytest.mark.asyncio
async def test_build_blacklist_config_only_title_patterns(session: AsyncSession) -> None:
    """build_blacklist_config works with only title_pattern entries."""
    await add_entry(session, "title_pattern", "part-time")
    await session.commit()

    config = await build_blacklist_config(session)
    assert config.companies == []
    assert config.title_patterns == ["part-time"]
