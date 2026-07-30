# Feature: local-scoring-trial, Property 6: Computed fields correctness
"""
Property-based tests for ScoringComparison computed fields.

Uses Hypothesis to verify that `create_comparison` correctly computes
`score_difference` and `would_skip` for any combination of inputs.

Properties tested:
- Property 6: Computed fields correctness
  - score_difference = claude_score - local_score when local_score is not None, else NULL
  - would_skip = (local_score < cutoff) when local_score is not None, else 0
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, ScoringComparison
from src.db.scoring_comparison_repo import create_comparison


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Scores are integers 0-100
score_strategy = st.integers(min_value=0, max_value=100)

# Local score is nullable: either None or an integer 0-100
local_score_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=100))

# Cutoff threshold is an integer 0-100
cutoff_strategy = st.integers(min_value=0, max_value=100)


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


async def _insert_job_record(session: AsyncSession, job_id: str) -> None:
    """Insert a minimal JobRecord to satisfy the foreign key constraint."""
    now = datetime.now(UTC).isoformat()
    job = JobRecord(
        id=job_id,
        job_title="Test Job",
        company="Test Company",
        linkedin_url=f"https://linkedin.com/jobs/{job_id}",
        apply_type="easy_apply",
        status="scored",
        discovered_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()


# ---------------------------------------------------------------------------
# Property 6: Computed fields correctness
# ---------------------------------------------------------------------------


@given(
    local_score=local_score_strategy,
    claude_score=score_strategy,
    cutoff=cutoff_strategy,
)
@settings(max_examples=200)
def test_computed_fields_score_difference(
    local_score: int | None,
    claude_score: int,
    cutoff: int,
) -> None:
    """
    For any ScoringComparison record with local_score L (nullable),
    claude_score C, and cutoff T:
    - score_difference SHALL equal C - L when L is not None, or NULL when L is None.

    **Validates: Requirements 4.1, 11.1**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = str(uuid4())
            await _insert_job_record(session, job_id)

            record = await create_comparison(
                session=session,
                job_id=job_id,
                local_score=local_score,
                claude_score=claude_score,
                model_version="v1_test",
                cutoff=cutoff,
            )

            if local_score is not None:
                assert record.score_difference == claude_score - local_score, (
                    f"Expected score_difference={claude_score - local_score}, "
                    f"got {record.score_difference} "
                    f"(claude={claude_score}, local={local_score})"
                )
            else:
                assert record.score_difference is None, (
                    f"Expected score_difference=None when local_score is None, "
                    f"got {record.score_difference}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    local_score=local_score_strategy,
    claude_score=score_strategy,
    cutoff=cutoff_strategy,
)
@settings(max_examples=200)
def test_computed_fields_would_skip(
    local_score: int | None,
    claude_score: int,
    cutoff: int,
) -> None:
    """
    For any ScoringComparison record with local_score L (nullable),
    claude_score C, and cutoff T:
    - would_skip SHALL equal (L < T) when L is not None, or 0 when L is None.

    **Validates: Requirements 4.1, 11.1**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = str(uuid4())
            await _insert_job_record(session, job_id)

            record = await create_comparison(
                session=session,
                job_id=job_id,
                local_score=local_score,
                claude_score=claude_score,
                model_version="v1_test",
                cutoff=cutoff,
            )

            if local_score is not None:
                expected_would_skip = 1 if local_score < cutoff else 0
                assert record.would_skip == expected_would_skip, (
                    f"Expected would_skip={expected_would_skip}, "
                    f"got {record.would_skip} "
                    f"(local={local_score}, cutoff={cutoff})"
                )
            else:
                assert record.would_skip == 0, (
                    f"Expected would_skip=0 when local_score is None, "
                    f"got {record.would_skip}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
