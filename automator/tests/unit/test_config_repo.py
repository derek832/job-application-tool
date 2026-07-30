"""
Unit tests for the config repository (automator/src/db/config_repo.py).

Tests cover:
- get_config returns None for missing keys
- get_config returns deserialized value for existing keys
- set_config inserts a new key
- set_config upserts (updates) an existing key
- Round-trip fidelity for various JSON-serializable types
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.config_repo import VALID_CONFIG_KEYS, get_config, set_config
from src.db.models import Base, Config


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


@pytest.mark.asyncio
async def test_get_config_returns_none_for_missing_key(session: AsyncSession) -> None:
    """get_config returns None when the key does not exist."""
    result = await get_config(session, "search_config")
    assert result is None


@pytest.mark.asyncio
async def test_set_config_inserts_new_key(session: AsyncSession) -> None:
    """set_config creates a new row when the key doesn't exist."""
    await set_config(session, "search_config", {"keywords": "python", "location": "remote"})
    await session.commit()

    value = await get_config(session, "search_config")
    assert value == {"keywords": "python", "location": "remote"}


@pytest.mark.asyncio
async def test_set_config_upserts_existing_key(session: AsyncSession) -> None:
    """set_config updates the value when the key already exists."""
    await set_config(session, "goals_profile", {"target_titles": ["SWE"]})
    await session.commit()

    await set_config(session, "goals_profile", {"target_titles": ["SWE", "Staff SWE"]})
    await session.commit()

    value = await get_config(session, "goals_profile")
    assert value == {"target_titles": ["SWE", "Staff SWE"]}


@pytest.mark.asyncio
async def test_set_config_updates_timestamp(session: AsyncSession) -> None:
    """set_config updates the updated_at timestamp on upsert."""
    await set_config(session, "settings", {"claude_api_key": "sk-test"})
    await session.commit()

    from sqlalchemy import select

    result = await session.execute(select(Config).where(Config.key == "settings"))
    row = result.scalar_one()
    first_ts = row.updated_at

    await set_config(session, "settings", {"claude_api_key": "sk-new"})
    await session.commit()

    # Re-fetch to get updated timestamp
    session.expire_all()
    result = await session.execute(select(Config).where(Config.key == "settings"))
    row = result.scalar_one()
    assert row.updated_at >= first_ts


@pytest.mark.asyncio
async def test_round_trip_dict(session: AsyncSession) -> None:
    """A dict value survives a set/get round trip."""
    data = {
        "keywords": "python,fastapi",
        "location": "San Francisco",
        "job_type": "full-time",
        "experience_level": "mid-senior",
        "remote_pref": "hybrid",
    }
    await set_config(session, "search_config", data)
    await session.commit()

    result = await get_config(session, "search_config")
    assert result == data


@pytest.mark.asyncio
async def test_round_trip_list(session: AsyncSession) -> None:
    """A list value survives a set/get round trip."""
    data = ["engineering", "product", "design"]
    await set_config(session, "goals_profile", data)
    await session.commit()

    result = await get_config(session, "goals_profile")
    assert result == data


@pytest.mark.asyncio
async def test_round_trip_string(session: AsyncSession) -> None:
    """A plain string value survives a set/get round trip."""
    await set_config(session, "api_token", "abc123hex")
    await session.commit()

    result = await get_config(session, "api_token")
    assert result == "abc123hex"


@pytest.mark.asyncio
async def test_round_trip_nested_object(session: AsyncSession) -> None:
    """A deeply nested object survives a set/get round trip."""
    data = {
        "status": "running",
        "last_run_at": "2024-01-15T09:00:00Z",
        "last_error": None,
        "nested": {"deep": [1, 2, 3]},
    }
    await set_config(session, "system_state", data)
    await session.commit()

    result = await get_config(session, "system_state")
    assert result == data


@pytest.mark.asyncio
async def test_round_trip_numeric_value(session: AsyncSession) -> None:
    """A numeric value survives a set/get round trip."""
    await set_config(session, "settings", 42)
    await session.commit()

    result = await get_config(session, "settings")
    assert result == 42


@pytest.mark.asyncio
async def test_round_trip_boolean_value(session: AsyncSession) -> None:
    """A boolean value survives a set/get round trip."""
    await set_config(session, "settings", True)
    await session.commit()

    result = await get_config(session, "settings")
    assert result is True


@pytest.mark.asyncio
async def test_valid_config_keys_matches_literal(session: AsyncSession) -> None:
    """VALID_CONFIG_KEYS contains exactly the keys defined in ConfigKey."""
    expected = {
        "search_config", "goals_profile", "user_profile",
        "settings", "system_state", "api_token",
        "ntfy_enabled", "ntfy_server_url", "ntfy_urgent_topic",
        "ntfy_info_topic", "lan_base_url",
        "schedule_config", "blacklist_config",
        "shadow_mode_enabled", "local_score_cutoff",
    }
    assert VALID_CONFIG_KEYS == expected
