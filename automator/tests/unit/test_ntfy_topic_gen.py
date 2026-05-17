"""
Unit tests for ntfy topic auto-generation (src/integrations/ntfy_topic_gen.py).

Tests cover:
- Topics are generated when absent from config
- Topics are reused when already present
- Generated topics are valid 16-char hex strings
"""

from __future__ import annotations

import re

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.config_repo import get_config, set_config
from src.db.models import Base
from src.integrations.ntfy_topic_gen import ensure_topics

HEX_16_PATTERN = re.compile(r"^[0-9a-f]{16}$")


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
async def test_ensure_topics_generates_when_absent(session: AsyncSession) -> None:
    """ensure_topics generates new topics when none exist in config."""
    urgent, info = await ensure_topics(session)

    assert HEX_16_PATTERN.match(urgent), f"Urgent topic not valid hex: {urgent}"
    assert HEX_16_PATTERN.match(info), f"Info topic not valid hex: {info}"
    assert urgent != info, "Urgent and info topics should be different"


@pytest.mark.asyncio
async def test_ensure_topics_persists_to_config(session: AsyncSession) -> None:
    """ensure_topics stores generated topics in the config table."""
    urgent, info = await ensure_topics(session)

    stored_urgent = await get_config(session, "ntfy_urgent_topic")
    stored_info = await get_config(session, "ntfy_info_topic")

    assert stored_urgent == urgent
    assert stored_info == info


@pytest.mark.asyncio
async def test_ensure_topics_reuses_existing(session: AsyncSession) -> None:
    """ensure_topics returns existing topics without regenerating."""
    await set_config(session, "ntfy_urgent_topic", "aaaa1111bbbb2222")
    await set_config(session, "ntfy_info_topic", "cccc3333dddd4444")
    await session.commit()

    urgent, info = await ensure_topics(session)

    assert urgent == "aaaa1111bbbb2222"
    assert info == "cccc3333dddd4444"


@pytest.mark.asyncio
async def test_ensure_topics_idempotent(session: AsyncSession) -> None:
    """Calling ensure_topics twice returns the same values."""
    urgent1, info1 = await ensure_topics(session)
    urgent2, info2 = await ensure_topics(session)

    assert urgent1 == urgent2
    assert info1 == info2
