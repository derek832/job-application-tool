# Feature: local-scoring-trial, Property 8: Query filter correctness
"""
Property-based test for query filter correctness.

For any set of ScoringComparison records and any filter combination of
(date_from, date_to, min_claude_score), every returned record SHALL satisfy
all specified filter criteria, and no record satisfying all criteria SHALL
be excluded from the results.

**Validates: Requirements 4.4, 6.1**
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, ScoringComparison
from src.db.scoring_comparison_repo import query_comparisons


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate ISO 8601 datetime strings across a 2-year range
_BASE_DT = datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)
_MAX_OFFSET_HOURS = 365 * 2 * 24  # ~2 years in hours


def _offset_to_iso(offset_hours: int) -> str:
    """Convert an hour offset to an ISO 8601 string."""
    dt = _BASE_DT + timedelta(hours=offset_hours)
    return dt.isoformat()


# Strategy for a scored_at timestamp (as hour offset from base)
scored_at_offset_st = st.integers(min_value=0, max_value=_MAX_OFFSET_HOURS)

# Strategy for claude_score (0-100)
claude_score_st = st.integers(min_value=0, max_value=100)

# Strategy for local_score (nullable 0-100)
local_score_st = st.one_of(st.none(), st.integers(min_value=0, max_value=100))

# Strategy for a single comparison record
comparison_record_st = st.fixed_dictionaries(
    {
        "scored_at_offset": scored_at_offset_st,
        "claude_score": claude_score_st,
        "local_score": local_score_st,
    }
)

# Strategy for a list of comparison records (1 to 20 records)
comparison_records_st = st.lists(comparison_record_st, min_size=1, max_size=20)

# Strategy for filter parameters (each can be None to indicate "not applied")
filter_params_st = st.fixed_dictionaries(
    {
        "date_from_offset": st.one_of(
            st.none(), st.integers(min_value=0, max_value=_MAX_OFFSET_HOURS)
        ),
        "date_to_offset": st.one_of(
            st.none(), st.integers(min_value=0, max_value=_MAX_OFFSET_HOURS)
        ),
        "min_claude_score": st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    }
)


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
# Helper: determine if a record satisfies filters
# ---------------------------------------------------------------------------


def _record_satisfies_filters(
    scored_at: str,
    claude_score: int,
    date_from: str | None,
    date_to: str | None,
    min_claude_score: int | None,
) -> bool:
    """Check whether a record with given values satisfies all filter criteria."""
    if date_from is not None and scored_at < date_from:
        return False
    if date_to is not None and scored_at > date_to:
        return False
    if min_claude_score is not None and claude_score < min_claude_score:
        return False
    return True


# ---------------------------------------------------------------------------
# Property 8: Query filter correctness
# ---------------------------------------------------------------------------


@given(
    records=comparison_records_st,
    filters=filter_params_st,
)
@settings(max_examples=150)
def test_query_filter_correctness(
    records: list[dict],
    filters: dict,
) -> None:
    """
    For any set of ScoringComparison records and any filter combination of
    (date_from, date_to, min_claude_score), every returned record SHALL
    satisfy all specified filter criteria, and no record satisfying all
    criteria SHALL be excluded from the results.

    **Validates: Requirements 4.4, 6.1**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # First insert a parent JobRecord for the FK constraint
            job_id = str(uuid4())
            job_record = JobRecord(
                id=job_id,
                job_title="Test Job",
                company="Test Company",
                linkedin_url=f"https://linkedin.com/jobs/{job_id}",
                apply_type="easy_apply",
                status="scored",
                discovered_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
            session.add(job_record)
            await session.flush()

            # Insert comparison records with generated data
            inserted_records: list[dict] = []
            for i, rec in enumerate(records):
                scored_at = _offset_to_iso(rec["scored_at_offset"])
                local_score = rec["local_score"]
                claude_score = rec["claude_score"]

                # Compute derived fields
                score_difference = (
                    claude_score - local_score if local_score is not None else None
                )
                would_skip = (
                    1 if local_score is not None and local_score < 40 else 0
                )

                comparison = ScoringComparison(
                    job_id=job_id,
                    local_score=local_score,
                    claude_score=claude_score,
                    score_difference=score_difference,
                    would_skip=would_skip,
                    model_version="v1_test",
                    scored_at=scored_at,
                )
                session.add(comparison)
                inserted_records.append(
                    {
                        "scored_at": scored_at,
                        "claude_score": claude_score,
                        "local_score": local_score,
                    }
                )

            await session.flush()

            # Build filter params
            date_from = (
                _offset_to_iso(filters["date_from_offset"])
                if filters["date_from_offset"] is not None
                else None
            )
            date_to = (
                _offset_to_iso(filters["date_to_offset"])
                if filters["date_to_offset"] is not None
                else None
            )
            min_claude_score = filters["min_claude_score"]

            # Query with a page_size large enough to get all records
            results = await query_comparisons(
                session=session,
                date_from=date_from,
                date_to=date_to,
                min_claude_score=min_claude_score,
                page=1,
                page_size=1000,
            )

            # PROPERTY CHECK 1: Every returned record satisfies all filters
            for result in results:
                if date_from is not None:
                    assert result.scored_at >= date_from, (
                        f"Returned record scored_at={result.scored_at!r} "
                        f"violates date_from={date_from!r}"
                    )
                if date_to is not None:
                    assert result.scored_at <= date_to, (
                        f"Returned record scored_at={result.scored_at!r} "
                        f"violates date_to={date_to!r}"
                    )
                if min_claude_score is not None:
                    assert result.claude_score >= min_claude_score, (
                        f"Returned record claude_score={result.claude_score} "
                        f"violates min_claude_score={min_claude_score}"
                    )

            # PROPERTY CHECK 2: No valid record is excluded
            # Count how many inserted records should match all filters
            expected_matching = [
                rec
                for rec in inserted_records
                if _record_satisfies_filters(
                    rec["scored_at"],
                    rec["claude_score"],
                    date_from,
                    date_to,
                    min_claude_score,
                )
            ]

            assert len(results) == len(expected_matching), (
                f"Expected {len(expected_matching)} matching records but got "
                f"{len(results)}. Filters: date_from={date_from!r}, "
                f"date_to={date_to!r}, min_claude_score={min_claude_score}"
            )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
