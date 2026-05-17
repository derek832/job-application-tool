"""
Property-based tests for ntfy topic generation.

Uses Hypothesis to verify correctness properties of the topic generation
and persistence logic in src/integrations/ntfy_topic_gen.py.

Properties tested:
- Property 2: Topic Generation Produces Valid Hex Strings
- Property 3: Topic Initialization Idempotence
"""

from __future__ import annotations

import asyncio
import re

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.config_repo import set_config
from src.db.models import Base
from src.integrations.ntfy_topic_gen import ensure_topics

HEX_16_PATTERN = re.compile(r"^[0-9a-f]{16}$")

# Strategy for valid 16-char hex strings (simulating pre-stored topics)
hex_topic_strategy = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)


# ---------------------------------------------------------------------------
# Async DB helper
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh in-memory SQLite session with schema initialized."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    return session, engine


async def _cleanup(session: AsyncSession, engine) -> None:
    """Close session and dispose engine."""
    await session.close()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2: Topic Generation Produces Valid Hex Strings
# ---------------------------------------------------------------------------


@given(st.data())
@settings(max_examples=100)
def test_topic_generation_produces_valid_hex_strings(data) -> None:
    """
    For any invocation of the topic generation function, the produced topic
    name SHALL be exactly 16 characters long and consist exclusively of
    hexadecimal characters (0-9, a-f).

    **Validates: Requirements 2.1**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            urgent, info = await ensure_topics(session)

            # Both topics must be exactly 16 hex characters
            assert HEX_16_PATTERN.match(urgent), (
                f"Urgent topic is not a valid 16-char hex string: '{urgent}'"
            )
            assert HEX_16_PATTERN.match(info), (
                f"Info topic is not a valid 16-char hex string: '{info}'"
            )

            # Length check (redundant with regex but explicit per property spec)
            assert len(urgent) == 16, f"Urgent topic length is {len(urgent)}, expected 16"
            assert len(info) == 16, f"Info topic length is {len(info)}, expected 16"
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 3: Topic Initialization Idempotence
# ---------------------------------------------------------------------------


@given(
    urgent_topic=hex_topic_strategy,
    info_topic=hex_topic_strategy,
)
@settings(max_examples=100)
def test_topic_initialization_idempotence(urgent_topic: str, info_topic: str) -> None:
    """
    For any pair of topic values already stored in the config table, calling
    the ensure_topics function SHALL return the same values without
    modification — the stored topics are never regenerated or overwritten.

    **Validates: Requirements 2.3**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Pre-store topics in the config table
            await set_config(session, "ntfy_urgent_topic", urgent_topic)
            await set_config(session, "ntfy_info_topic", info_topic)
            await session.commit()

            # Call ensure_topics — should return stored values unchanged
            result_urgent, result_info = await ensure_topics(session)

            assert result_urgent == urgent_topic, (
                f"Urgent topic was modified: expected '{urgent_topic}', got '{result_urgent}'"
            )
            assert result_info == info_topic, (
                f"Info topic was modified: expected '{info_topic}', got '{result_info}'"
            )

            # Call again to verify repeated idempotence
            result_urgent2, result_info2 = await ensure_topics(session)

            assert result_urgent2 == urgent_topic, (
                f"Urgent topic changed on second call: expected '{urgent_topic}', "
                f"got '{result_urgent2}'"
            )
            assert result_info2 == info_topic, (
                f"Info topic changed on second call: expected '{info_topic}', "
                f"got '{result_info2}'"
            )
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
