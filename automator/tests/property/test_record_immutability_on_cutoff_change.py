"""
Property-based test for record immutability on cutoff change (Property 9).

Verifies that when the local_score_cutoff configuration value is changed,
the would_skip and score_difference values of all previously stored
ScoringComparison records remain unchanged. Computed fields are frozen
at insert time.

Feature: local-scoring-trial, Property 9: Record immutability on cutoff change
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, JobRecord, ScoringComparison
from src.db.scoring_comparison_repo import create_comparison


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Scores in the valid range 0-100
score_strategy = st.integers(min_value=0, max_value=100)

# Cutoff values in the valid range 0-100, generate two distinct cutoffs
cutoff_strategy = st.integers(min_value=0, max_value=100)

# Local score can be an int 0-100 or None (prediction failure)
local_score_strategy = st.one_of(st.none(), score_strategy)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Property 9: Record immutability on cutoff change
# ---------------------------------------------------------------------------


@given(
    local_scores=st.lists(local_score_strategy, min_size=1, max_size=10),
    claude_scores=st.lists(score_strategy, min_size=1, max_size=10),
    cutoff_1=cutoff_strategy,
    cutoff_2=cutoff_strategy,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_record_immutability_on_cutoff_change(
    local_scores: list[int | None],
    claude_scores: list[int],
    cutoff_1: int,
    cutoff_2: int,
    async_engine,
) -> None:
    """
    For any existing set of ScoringComparison records, when the
    local_score_cutoff configuration value is changed, the would_skip
    and score_difference values of all previously stored records SHALL
    remain unchanged.

    Steps:
    1. Create records with cutoff_1
    2. Snapshot their would_skip and score_difference values
    3. Create new records with cutoff_2 (simulating a cutoff change)
    4. Verify the first set of records' computed fields haven't changed

    **Validates: Requirements 11.4**

    Feature: local-scoring-trial, Property 9: Record immutability on cutoff change
    """
    # Ensure lists are the same length by zipping
    pairs = list(zip(local_scores, claude_scores))

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Step 1: Create a job record and comparison records with cutoff_1
    async with async_session_factory() as session:
        # Create a job record to satisfy FK constraint
        job = JobRecord(
            id="job-immut-test",
            job_title="Immutability Test",
            company="Test Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/immut-test",
            apply_type="easy_apply",
            status="scored",
            fit_score=75,
            discovered_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        session.add(job)
        await session.flush()

        # Create comparison records with cutoff_1
        first_batch_ids: list[int] = []
        for local_score, claude_score in pairs:
            record = await create_comparison(
                session=session,
                job_id="job-immut-test",
                local_score=local_score,
                claude_score=claude_score,
                model_version="v1_test",
                cutoff=cutoff_1,
            )
            first_batch_ids.append(record.id)

        await session.commit()

    # Step 2: Snapshot the computed fields from first batch
    async with async_session_factory() as session:
        stmt = select(ScoringComparison).where(
            ScoringComparison.id.in_(first_batch_ids)
        )
        result = await session.execute(stmt)
        first_batch_records = list(result.scalars().all())

        # Store snapshots: {id: (would_skip, score_difference)}
        snapshots: dict[int, tuple[int, int | None]] = {
            r.id: (r.would_skip, r.score_difference)
            for r in first_batch_records
        }

    # Step 3: Create NEW records with cutoff_2 (simulating cutoff change)
    async with async_session_factory() as session:
        for local_score, claude_score in pairs:
            await create_comparison(
                session=session,
                job_id="job-immut-test",
                local_score=local_score,
                claude_score=claude_score,
                model_version="v2_test",
                cutoff=cutoff_2,
            )
        await session.commit()

    # Step 4: Re-read the FIRST batch and verify computed fields unchanged
    async with async_session_factory() as session:
        stmt = select(ScoringComparison).where(
            ScoringComparison.id.in_(first_batch_ids)
        )
        result = await session.execute(stmt)
        first_batch_after = list(result.scalars().all())

        assert len(first_batch_after) == len(first_batch_ids), (
            "Some records from the first batch are missing after cutoff change"
        )

        for record in first_batch_after:
            original_would_skip, original_score_diff = snapshots[record.id]
            assert record.would_skip == original_would_skip, (
                f"Record {record.id}: would_skip changed from "
                f"{original_would_skip} to {record.would_skip} after "
                f"cutoff change ({cutoff_1} -> {cutoff_2})"
            )
            assert record.score_difference == original_score_diff, (
                f"Record {record.id}: score_difference changed from "
                f"{original_score_diff} to {record.score_difference} after "
                f"cutoff change ({cutoff_1} -> {cutoff_2})"
            )

    # Cleanup
    async with async_session_factory() as session:
        # Delete all scoring comparisons
        stmt = select(ScoringComparison).where(
            ScoringComparison.job_id == "job-immut-test"
        )
        result = await session.execute(stmt)
        for record in result.scalars().all():
            await session.delete(record)

        # Delete the job record
        job_stmt = select(JobRecord).where(JobRecord.id == "job-immut-test")
        job_result = await session.execute(job_stmt)
        job_record = job_result.scalars().first()
        if job_record:
            await session.delete(job_record)
        await session.commit()
