"""
Property-based tests for preview job promotion state transition.

Uses Hypothesis to verify that the promote_preview_jobs() function correctly
transitions preview jobs to the job_records table with status
"approved_for_apply" and marks the corresponding preview_jobs.promoted field
as 1.

Properties tested:
- Property 3: Preview Job Promotion State Transition

**Validates: Requirements 1.4**
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, PreviewJob, PreviewRun
from src.pipeline.preview_pipeline import promote_preview_jobs


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for LinkedIn-style job IDs (numeric strings, 8-12 digits)
job_id_strategy = st.text(
    alphabet="0123456789",
    min_size=8,
    max_size=12,
).filter(lambda s: s.strip() and len(s) >= 8)

# Strategy for unique sets of preview job IDs
preview_job_ids_strategy = st.lists(
    job_id_strategy,
    min_size=1,
    max_size=15,
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


def _make_preview_run(run_id: str) -> PreviewRun:
    """Create a completed PreviewRun record."""
    now = datetime.now(UTC).isoformat()
    return PreviewRun(
        id=run_id,
        status="completed",
        started_at=now,
        completed_at=now,
        total_discovered=0,
        total_scored=0,
        total_blacklisted=0,
    )


def _make_preview_job(run_id: str, job_id: str) -> PreviewJob:
    """Create a PreviewJob record ready for promotion."""
    return PreviewJob(
        run_id=run_id,
        job_id=job_id,
        job_title=f"Software Engineer {job_id[-4:]}",
        company=f"Company {job_id[-3:]}",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        fit_score=75,
        fit_rationale="Good match for the role.",
        projected_action="auto_apply",
        promoted=0,
        promoted_at=None,
    )


# ---------------------------------------------------------------------------
# Property 3: Preview Job Promotion State Transition
# ---------------------------------------------------------------------------


@given(
    all_job_ids=preview_job_ids_strategy,
    data=st.data(),
)
@settings(max_examples=150)
def test_promoted_jobs_exist_in_job_records_with_approved_status(
    all_job_ids: list[str],
    data: st.DataObject,
) -> None:
    """
    For any set of preview job IDs submitted for promotion, after the promote
    operation completes, each promoted job shall exist in the job_records table
    with status "approved_for_apply".

    **Validates: Requirements 1.4**
    """
    # Draw a subset of job IDs to promote (at least 1, up to all)
    promote_ids = data.draw(
        st.lists(
            st.sampled_from(all_job_ids),
            min_size=1,
            max_size=len(all_job_ids),
            unique=True,
        )
    )

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            run_id = "test-run-001"

            # Set up the preview run and preview jobs
            session.add(_make_preview_run(run_id))
            for job_id in all_job_ids:
                session.add(_make_preview_job(run_id, job_id))
            await session.flush()

            # Promote the selected subset
            promoted = await promote_preview_jobs(session, run_id, promote_ids)

            # Property: every promoted job ID exists in job_records
            # with status "approved_for_apply"
            for job_id in promoted:
                result = await session.execute(
                    select(JobRecord).where(JobRecord.id == job_id)
                )
                job_record = result.scalar_one_or_none()

                assert job_record is not None, (
                    f"Promoted job ID '{job_id}' does not exist in job_records. "
                    f"Promoted IDs: {promoted}"
                )
                assert job_record.status == "approved_for_apply", (
                    f"Promoted job ID '{job_id}' has status '{job_record.status}' "
                    f"instead of 'approved_for_apply'."
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    all_job_ids=preview_job_ids_strategy,
    data=st.data(),
)
@settings(max_examples=150)
def test_promoted_preview_jobs_have_promoted_flag_set(
    all_job_ids: list[str],
    data: st.DataObject,
) -> None:
    """
    For any set of preview job IDs submitted for promotion, after the promote
    operation completes, the corresponding preview_jobs.promoted field shall
    be 1.

    **Validates: Requirements 1.4**
    """
    # Draw a subset of job IDs to promote
    promote_ids = data.draw(
        st.lists(
            st.sampled_from(all_job_ids),
            min_size=1,
            max_size=len(all_job_ids),
            unique=True,
        )
    )

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            run_id = "test-run-002"

            # Set up the preview run and preview jobs
            session.add(_make_preview_run(run_id))
            for job_id in all_job_ids:
                session.add(_make_preview_job(run_id, job_id))
            await session.flush()

            # Promote the selected subset
            promoted = await promote_preview_jobs(session, run_id, promote_ids)

            # Property: every promoted job has preview_jobs.promoted == 1
            for job_id in promoted:
                result = await session.execute(
                    select(PreviewJob).where(
                        PreviewJob.run_id == run_id,
                        PreviewJob.job_id == job_id,
                    )
                )
                preview_job = result.scalar_one_or_none()

                assert preview_job is not None, (
                    f"Preview job for ID '{job_id}' not found after promotion."
                )
                assert preview_job.promoted == 1, (
                    f"Preview job '{job_id}' has promoted={preview_job.promoted} "
                    f"instead of 1 after promotion."
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    all_job_ids=preview_job_ids_strategy,
    data=st.data(),
)
@settings(max_examples=100)
def test_non_promoted_jobs_remain_unchanged(
    all_job_ids: list[str],
    data: st.DataObject,
) -> None:
    """
    For any set of preview jobs where only a subset is promoted, the
    non-promoted preview jobs shall retain promoted=0 and shall NOT appear
    in the job_records table.

    **Validates: Requirements 1.4**
    """
    # Need at least 2 jobs to have a meaningful subset
    if len(all_job_ids) < 2:
        return

    # Draw a strict subset to promote (not all)
    max_promote = len(all_job_ids) - 1
    promote_ids = data.draw(
        st.lists(
            st.sampled_from(all_job_ids),
            min_size=1,
            max_size=max_promote,
            unique=True,
        )
    )

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            run_id = "test-run-003"

            # Set up the preview run and preview jobs
            session.add(_make_preview_run(run_id))
            for job_id in all_job_ids:
                session.add(_make_preview_job(run_id, job_id))
            await session.flush()

            # Promote the selected subset
            await promote_preview_jobs(session, run_id, promote_ids)

            # Property: non-promoted jobs remain with promoted=0
            # and do NOT exist in job_records
            non_promoted_ids = set(all_job_ids) - set(promote_ids)
            for job_id in non_promoted_ids:
                # Check preview_jobs.promoted is still 0
                result = await session.execute(
                    select(PreviewJob).where(
                        PreviewJob.run_id == run_id,
                        PreviewJob.job_id == job_id,
                    )
                )
                preview_job = result.scalar_one_or_none()
                assert preview_job is not None
                assert preview_job.promoted == 0, (
                    f"Non-promoted job '{job_id}' has promoted={preview_job.promoted} "
                    f"but should remain 0."
                )

                # Check job_records does NOT contain this job
                jr_result = await session.execute(
                    select(JobRecord).where(JobRecord.id == job_id)
                )
                job_record = jr_result.scalar_one_or_none()
                assert job_record is None, (
                    f"Non-promoted job '{job_id}' was found in job_records "
                    f"but should not have been inserted."
                )

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


@given(
    all_job_ids=preview_job_ids_strategy,
)
@settings(max_examples=100)
def test_promote_all_jobs_creates_matching_records(
    all_job_ids: list[str],
) -> None:
    """
    When ALL preview jobs in a run are submitted for promotion, every single
    one shall exist in job_records with status "approved_for_apply" and every
    preview_jobs.promoted field shall be 1.

    **Validates: Requirements 1.4**
    """

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            run_id = "test-run-004"

            # Set up the preview run and preview jobs
            session.add(_make_preview_run(run_id))
            for job_id in all_job_ids:
                session.add(_make_preview_job(run_id, job_id))
            await session.flush()

            # Promote ALL jobs
            promoted = await promote_preview_jobs(session, run_id, all_job_ids)

            # Property: all job IDs were promoted
            assert set(promoted) == set(all_job_ids), (
                f"Expected all jobs to be promoted. "
                f"Promoted: {promoted}, Expected: {all_job_ids}"
            )

            # Property: each promoted job exists in job_records with correct status
            for job_id in all_job_ids:
                jr_result = await session.execute(
                    select(JobRecord).where(JobRecord.id == job_id)
                )
                job_record = jr_result.scalar_one_or_none()
                assert job_record is not None, (
                    f"Job '{job_id}' not found in job_records after promotion."
                )
                assert job_record.status == "approved_for_apply"

                # Check preview_jobs.promoted == 1
                pj_result = await session.execute(
                    select(PreviewJob).where(
                        PreviewJob.run_id == run_id,
                        PreviewJob.job_id == job_id,
                    )
                )
                preview_job = pj_result.scalar_one_or_none()
                assert preview_job is not None
                assert preview_job.promoted == 1

        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
