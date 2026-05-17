"""
Property-based tests for run history pagination.

Uses Hypothesis to verify correctness properties of the GET /runs/history
endpoint in src/api/run_routes.py.

Properties tested:
- Property 11: Run History Pagination
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, RunSummary
from src.pipeline.run_summary import get_recent_summaries


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Number of stored run summaries (0 to 30 to cover empty, under-limit, and over-limit)
stored_count_strategy = st.integers(min_value=0, max_value=30)

# Requested limit value between 1 and 20 (the valid range for the endpoint)
limit_strategy = st.integers(min_value=1, max_value=20)

# Non-empty summary text (realistic content)
summary_text_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=5,
    max_size=200,
).filter(lambda s: s.strip())


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
# Property 11: Run History Pagination
# ---------------------------------------------------------------------------


@given(
    stored_count=stored_count_strategy,
    limit=limit_strategy,
)
@settings(max_examples=200)
def test_run_history_pagination(stored_count: int, limit: int) -> None:
    """
    For any number of stored run summaries and any requested limit value
    between 1 and 20, the GET /runs/history endpoint SHALL return at most
    min(limit, stored_count) entries, each containing a non-empty id, a valid
    ISO 8601 created_at timestamp, and a non-empty summary text.

    **Validates: Requirements 10.1, 10.2, 10.4**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert stored_count summaries with distinct timestamps
            base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

            for i in range(stored_count):
                ts = (base_time + timedelta(minutes=i)).isoformat()
                record = RunSummary(
                    id=str(uuid4()),
                    summary=f"Run complete: found {i + 1} jobs, applied to {i}. No errors.",
                    jobs_discovered=i + 1,
                    jobs_scored=i,
                    jobs_approved=0,
                    jobs_applied=i,
                    jobs_skipped=0,
                    jobs_escalated=0,
                    errors=None,
                    created_at=ts,
                )
                session.add(record)

            await session.flush()

            # Call get_recent_summaries (the underlying function used by the endpoint)
            results = await get_recent_summaries(session, limit=limit)

            # SHALL return at most min(limit, stored_count) entries
            expected_count = min(limit, stored_count)
            assert len(results) == expected_count, (
                f"Expected {expected_count} results (min({limit}, {stored_count})), "
                f"got {len(results)}"
            )

            # Each entry SHALL contain a non-empty id, valid ISO 8601 created_at,
            # and non-empty summary text
            for record in results:
                # Non-empty id
                assert record.id is not None and len(record.id) > 0, (
                    f"Record has empty or None id: {record.id!r}"
                )

                # Valid ISO 8601 created_at timestamp
                assert record.created_at is not None and len(record.created_at) > 0, (
                    f"Record has empty or None created_at: {record.created_at!r}"
                )
                # Verify it parses as a valid ISO 8601 timestamp
                parsed_ts = datetime.fromisoformat(record.created_at)
                assert parsed_ts is not None, (
                    f"created_at is not a valid ISO 8601 timestamp: {record.created_at!r}"
                )

                # Non-empty summary text
                assert record.summary is not None and len(record.summary) > 0, (
                    f"Record has empty or None summary: {record.summary!r}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
