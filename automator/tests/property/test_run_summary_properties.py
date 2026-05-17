"""
Property-based tests for run summary generation and retention.

Uses Hypothesis to verify correctness properties of the run summary
generation and retention logic in src/pipeline/run_summary.py.

Properties tested:
- Property 6: Run Summary Generation Correctness
- Property 7: Run Summary Retention Policy
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, RunSummary
from src.pipeline.run_summary import RunStats, enforce_retention, generate_summary_text


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-negative integers for job counts (realistic upper bound to keep tests fast)
non_negative_int = st.integers(min_value=0, max_value=10_000)

# Error strings: non-empty text of varying lengths
error_string = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=200,
)

# Strategy for RunStats with any valid combination of counts and errors
run_stats_strategy = st.builds(
    RunStats,
    jobs_discovered=non_negative_int,
    jobs_scored=non_negative_int,
    jobs_approved=non_negative_int,
    jobs_applied=non_negative_int,
    jobs_skipped=non_negative_int,
    jobs_escalated=non_negative_int,
    errors=st.lists(error_string, min_size=0, max_size=20),
)

# Number of summaries to store (always > 20 for retention test)
num_summaries_strategy = st.integers(min_value=21, max_value=60)


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
# Property 6: Run Summary Generation Correctness
# ---------------------------------------------------------------------------


@given(stats=run_stats_strategy)
@settings(max_examples=200)
def test_run_summary_generation_correctness(stats: RunStats) -> None:
    """
    For any set of pipeline run statistics (with any non-negative integer
    counts for discovered, scored, approved, applied, skipped, escalated,
    and any list of error strings), the generated summary text SHALL be at
    most 500 characters, SHALL be non-empty, and SHALL contain the
    jobs_discovered count.

    **Validates: Requirements 5.1, 5.2**
    """
    summary = generate_summary_text(stats)

    # SHALL be non-empty
    assert len(summary) > 0, "Summary text must be non-empty"

    # SHALL be at most 500 characters
    assert len(summary) <= 500, (
        f"Summary text exceeds 500 characters: length={len(summary)}, text='{summary[:50]}...'"
    )

    # SHALL contain the jobs_discovered count
    assert str(stats.jobs_discovered) in summary, (
        f"Summary does not contain jobs_discovered count ({stats.jobs_discovered}): "
        f"'{summary}'"
    )


# ---------------------------------------------------------------------------
# Property 7: Run Summary Retention Policy
# ---------------------------------------------------------------------------


@given(num_summaries=num_summaries_strategy)
@settings(max_examples=50)
def test_run_summary_retention_policy(num_summaries: int) -> None:
    """
    For any number N of run summaries stored in the database where N > 20,
    after the retention enforcement function executes, exactly 20 summaries
    SHALL remain, and they SHALL be the 20 with the most recent created_at
    timestamps.

    **Validates: Requirements 5.5**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert N summaries with distinct timestamps
            base_time = datetime(2024, 1, 1, tzinfo=UTC)
            all_records = []

            for i in range(num_summaries):
                ts = (base_time + timedelta(minutes=i)).isoformat()
                record = RunSummary(
                    id=str(uuid4()),
                    summary=f"Test summary {i}",
                    jobs_discovered=i,
                    jobs_scored=0,
                    jobs_approved=0,
                    jobs_applied=0,
                    jobs_skipped=0,
                    jobs_escalated=0,
                    errors=None,
                    created_at=ts,
                )
                session.add(record)
                all_records.append((record.id, ts))

            await session.flush()

            # Execute retention enforcement
            await enforce_retention(session, max_records=20)
            await session.flush()

            # Query remaining records
            from sqlalchemy import func, select

            count_result = await session.execute(
                select(func.count()).select_from(RunSummary)
            )
            remaining_count = count_result.scalar()

            # Exactly 20 summaries SHALL remain
            assert remaining_count == 20, (
                f"Expected 20 summaries after retention, got {remaining_count} "
                f"(started with {num_summaries})"
            )

            # They SHALL be the 20 with the most recent created_at timestamps
            remaining_result = await session.execute(
                select(RunSummary.created_at).order_by(RunSummary.created_at.desc())
            )
            remaining_timestamps = remaining_result.scalars().all()

            # Sort all original timestamps descending and take top 20
            all_timestamps_sorted = sorted(
                [ts for _, ts in all_records], reverse=True
            )
            expected_top_20 = all_timestamps_sorted[:20]

            assert sorted(remaining_timestamps, reverse=True) == sorted(
                expected_top_20, reverse=True
            ), (
                f"Remaining summaries are not the 20 most recent. "
                f"Expected newest: {expected_top_20[0]}, got: {remaining_timestamps[0]}"
            )
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
