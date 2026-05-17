"""
Property-based tests for preview deduplication.

Uses Hypothesis to verify that the _deduplicate_jobs() function correctly
filters out jobs that already exist in the job_records table, returning only
newly discovered job IDs. No duplicate job ID shall appear in the preview
results.

Properties tested:
- Property 4: Preview Deduplication

**Validates: Requirements 1.9**
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord
from src.integrations.linkedin_scraper import DiscoveredJob
from src.pipeline.preview_pipeline import _deduplicate_jobs


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for LinkedIn-style job IDs (numeric strings, 8-12 digits)
job_id_strategy = st.text(
    alphabet="0123456789",
    min_size=8,
    max_size=12,
).filter(lambda s: s.strip() and len(s) >= 8)

# Strategy for sets of job IDs (unique within each set)
job_id_set_strategy = st.lists(
    job_id_strategy,
    min_size=1,
    max_size=20,
    unique=True,
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


def _make_discovered_job(job_id: str) -> DiscoveredJob:
    """Create a minimal DiscoveredJob instance for testing."""
    return DiscoveredJob(
        job_id=job_id,
        title=f"Software Engineer {job_id[-4:]}",
        company=f"Company {job_id[-3:]}",
        description=f"Job description for {job_id}",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        apply_type="easy_apply",
    )


def _make_job_record(job_id: str) -> JobRecord:
    """Create a minimal JobRecord instance for inserting into the database."""
    now = datetime.now(UTC).isoformat()
    return JobRecord(
        id=job_id,
        job_title=f"Existing Job {job_id[-4:]}",
        company=f"Existing Company {job_id[-3:]}",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        apply_type="easy_apply",
        status="discovered",
        discovered_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Property 4: Preview Deduplication
# ---------------------------------------------------------------------------


@given(
    discovered_ids=job_id_set_strategy,
    existing_ids=job_id_set_strategy,
)
@settings(max_examples=150)
def test_deduplicated_results_exclude_existing_jobs(
    discovered_ids: list[str],
    existing_ids: list[str],
) -> None:
    """
    For any set of job IDs discovered during a preview run where some already
    exist in the job_records table, the result of _deduplicate_jobs() shall
    contain only job IDs that are NOT already present in job_records.

    **Validates: Requirements 1.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert existing job records into the database
            for job_id in existing_ids:
                session.add(_make_job_record(job_id))
            await session.flush()

            # Create discovered jobs
            discovered_jobs = [_make_discovered_job(jid) for jid in discovered_ids]

            # Run deduplication
            result = await _deduplicate_jobs(session, discovered_jobs)

            # Compute expected: discovered IDs that are NOT in existing_ids
            existing_set = set(existing_ids)
            result_ids = [job.job_id for job in result]

            # Property: no result job ID should be in the existing set
            for job_id in result_ids:
                assert job_id not in existing_set, (
                    f"Job ID '{job_id}' exists in job_records but was NOT "
                    f"filtered out by _deduplicate_jobs(). "
                    f"Existing IDs: {existing_ids}, Discovered IDs: {discovered_ids}"
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    discovered_ids=job_id_set_strategy,
    existing_ids=job_id_set_strategy,
)
@settings(max_examples=150)
def test_deduplicated_results_retain_all_new_jobs(
    discovered_ids: list[str],
    existing_ids: list[str],
) -> None:
    """
    For any set of discovered job IDs, all IDs that do NOT exist in
    job_records shall be present in the deduplication result. No new job
    shall be incorrectly removed.

    **Validates: Requirements 1.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert existing job records
            for job_id in existing_ids:
                session.add(_make_job_record(job_id))
            await session.flush()

            # Create discovered jobs
            discovered_jobs = [_make_discovered_job(jid) for jid in discovered_ids]

            # Run deduplication
            result = await _deduplicate_jobs(session, discovered_jobs)

            # Compute expected new IDs
            existing_set = set(existing_ids)
            expected_new_ids = {jid for jid in discovered_ids if jid not in existing_set}
            result_ids = set(job.job_id for job in result)

            # Property: every expected new ID must be in the result
            assert result_ids == expected_new_ids, (
                f"Expected new job IDs {expected_new_ids} but got {result_ids}. "
                f"Missing: {expected_new_ids - result_ids}, "
                f"Extra: {result_ids - expected_new_ids}"
            )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    discovered_ids=job_id_set_strategy,
)
@settings(max_examples=100)
def test_deduplicated_results_contain_no_duplicates(
    discovered_ids: list[str],
) -> None:
    """
    For any set of discovered job IDs, the deduplication result shall contain
    no duplicate job IDs — each job ID appears at most once.

    **Validates: Requirements 1.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # No existing records — all discovered jobs are new
            discovered_jobs = [_make_discovered_job(jid) for jid in discovered_ids]

            # Run deduplication
            result = await _deduplicate_jobs(session, discovered_jobs)

            # Property: no duplicate IDs in the result
            result_ids = [job.job_id for job in result]
            assert len(result_ids) == len(set(result_ids)), (
                f"Duplicate job IDs found in deduplication result. "
                f"Result IDs: {result_ids}, "
                f"Duplicates: {[x for x in result_ids if result_ids.count(x) > 1]}"
            )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    existing_ids=job_id_set_strategy,
)
@settings(max_examples=100)
def test_all_existing_jobs_are_fully_filtered(
    existing_ids: list[str],
) -> None:
    """
    When ALL discovered job IDs already exist in job_records, the
    deduplication result shall be an empty list.

    **Validates: Requirements 1.9**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            # Insert all IDs as existing records
            for job_id in existing_ids:
                session.add(_make_job_record(job_id))
            await session.flush()

            # Discover the same IDs
            discovered_jobs = [_make_discovered_job(jid) for jid in existing_ids]

            # Run deduplication
            result = await _deduplicate_jobs(session, discovered_jobs)

            # Property: result should be empty since all are duplicates
            assert len(result) == 0, (
                f"Expected empty result when all discovered jobs already exist, "
                f"but got {len(result)} jobs: {[j.job_id for j in result]}"
            )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
