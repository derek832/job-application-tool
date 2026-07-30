# Feature: local-scoring-trial, Property 1: Training data filter correctness
"""
Property-based test for training data filter correctness.

For any database containing job records with arbitrary combinations of
null/non-null fit_score and description_text, the training data loader SHALL
return exactly the set of records where both fit_score IS NOT NULL and
description_text IS NOT NULL.

**Validates: Requirements 1.1**
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord
from src.scoring.local_scorer import _load_training_data


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for description_text: either None or a non-empty string
description_st = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=200),
)

# Strategy for fit_score: either None or an integer 0-100
fit_score_st = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=100),
)

# Strategy for a single job record's nullable fields
job_record_st = st.fixed_dictionaries(
    {
        "description_text": description_st,
        "fit_score": fit_score_st,
    }
)

# Strategy for a list of job records (1 to 30 records)
job_records_st = st.lists(job_record_st, min_size=1, max_size=30)


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
# Property 1: Training data filter correctness
# ---------------------------------------------------------------------------


@given(records=job_records_st)
@settings(max_examples=150)
def test_training_data_filter_returns_only_records_with_both_non_null(
    records: list[dict],
) -> None:
    """
    For any database containing job records with arbitrary combinations of
    null/non-null fit_score and description_text, the training data loader
    SHALL return exactly the set of records where both fit_score IS NOT NULL
    and description_text IS NOT NULL.

    **Validates: Requirements 1.1**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(UTC).isoformat()

            # Insert job records with various null/non-null combinations
            expected_descriptions: list[str] = []
            expected_scores: list[int] = []

            for rec in records:
                job_id = str(uuid4())
                job = JobRecord(
                    id=job_id,
                    job_title="Test Job",
                    company="Test Company",
                    linkedin_url=f"https://linkedin.com/jobs/{job_id}",
                    apply_type="easy_apply",
                    status="scored",
                    discovered_at=now,
                    updated_at=now,
                    description_text=rec["description_text"],
                    fit_score=rec["fit_score"],
                )
                session.add(job)

                # Track which records should be returned
                if rec["description_text"] is not None and rec["fit_score"] is not None:
                    expected_descriptions.append(rec["description_text"])
                    expected_scores.append(rec["fit_score"])

            await session.flush()

            # Call the function under test
            descriptions, scores = await _load_training_data(session)

            # PROPERTY CHECK 1: The count matches
            assert len(descriptions) == len(expected_descriptions), (
                f"Expected {len(expected_descriptions)} records but got "
                f"{len(descriptions)}. Input had {len(records)} total records."
            )
            assert len(scores) == len(expected_scores), (
                f"Expected {len(expected_scores)} scores but got {len(scores)}."
            )

            # PROPERTY CHECK 2: Every returned description is non-null
            for desc in descriptions:
                assert desc is not None, "Returned a None description_text"

            # PROPERTY CHECK 3: Every returned score is non-null
            for score in scores:
                assert score is not None, "Returned a None fit_score"

            # PROPERTY CHECK 4: The returned values match the expected set
            # (order may differ due to DB, so compare as multisets)
            assert sorted(descriptions) == sorted(expected_descriptions), (
                f"Returned descriptions don't match expected. "
                f"Got {sorted(descriptions)[:5]}... "
                f"Expected {sorted(expected_descriptions)[:5]}..."
            )
            assert sorted(scores) == sorted(expected_scores), (
                f"Returned scores don't match expected. "
                f"Got {sorted(scores)[:5]}... "
                f"Expected {sorted(expected_scores)[:5]}..."
            )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
