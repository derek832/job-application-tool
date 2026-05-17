"""Unit tests for the preview job promotion logic.

Tests the promote_preview_jobs() function which copies preview jobs to
job_records with status "approved_for_apply" and marks them as promoted.

Requirements: 1.4
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, PreviewJob, PreviewRun
from src.pipeline.preview_pipeline import promote_preview_jobs


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


@pytest_asyncio.fixture
async def preview_run_with_jobs(session: AsyncSession) -> tuple[str, list[str]]:
    """Create a completed preview run with 3 preview jobs.

    Returns:
        Tuple of (run_id, list of job_ids).
    """
    run_id = "test-run-001"
    preview_run = PreviewRun(
        id=run_id,
        status="completed",
        started_at="2024-03-15T09:00:00Z",
        completed_at="2024-03-15T09:03:00Z",
        total_discovered=3,
        total_scored=3,
        total_blacklisted=0,
    )
    session.add(preview_run)

    job_ids = ["job-111", "job-222", "job-333"]
    for job_id in job_ids:
        pj = PreviewJob(
            run_id=run_id,
            job_id=job_id,
            job_title=f"Engineer at {job_id}",
            company=f"Company-{job_id}",
            linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
            fit_score=85,
            fit_rationale="Good match",
            projected_action="auto_apply",
            promoted=0,
            promoted_at=None,
        )
        session.add(pj)

    await session.flush()
    return run_id, job_ids


@pytest.mark.asyncio
async def test_promote_creates_job_records(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Promoted preview jobs appear in job_records with status approved_for_apply."""
    run_id, job_ids = preview_run_with_jobs

    promoted = await promote_preview_jobs(session, run_id, [job_ids[0], job_ids[1]])

    assert set(promoted) == {job_ids[0], job_ids[1]}

    # Verify job_records were created
    for jid in [job_ids[0], job_ids[1]]:
        result = await session.execute(select(JobRecord).where(JobRecord.id == jid))
        record = result.scalar_one()
        assert record.status == "approved_for_apply"
        assert record.apply_type == "easy_apply"
        assert record.discovered_at is not None
        assert record.updated_at is not None


@pytest.mark.asyncio
async def test_promote_sets_promoted_flag(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Promoted preview jobs have promoted=1 and promoted_at set."""
    run_id, job_ids = preview_run_with_jobs

    await promote_preview_jobs(session, run_id, [job_ids[0]])

    result = await session.execute(
        select(PreviewJob).where(PreviewJob.job_id == job_ids[0])
    )
    pj = result.scalar_one()
    assert pj.promoted == 1
    assert pj.promoted_at is not None


@pytest.mark.asyncio
async def test_promote_does_not_affect_unpromoted_jobs(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Jobs not in the promotion list remain unpromoted."""
    run_id, job_ids = preview_run_with_jobs

    await promote_preview_jobs(session, run_id, [job_ids[0]])

    # job_ids[2] should still be unpromoted
    result = await session.execute(
        select(PreviewJob).where(PreviewJob.job_id == job_ids[2])
    )
    pj = result.scalar_one()
    assert pj.promoted == 0
    assert pj.promoted_at is None

    # No job_record should exist for the unpromoted job
    result = await session.execute(select(JobRecord).where(JobRecord.id == job_ids[2]))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_promote_empty_list_returns_empty(session: AsyncSession) -> None:
    """Promoting an empty list returns an empty list without errors."""
    promoted = await promote_preview_jobs(session, "nonexistent-run", [])
    assert promoted == []


@pytest.mark.asyncio
async def test_promote_nonexistent_job_ids_returns_empty(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Promoting job IDs that don't exist in the run returns empty."""
    run_id, _ = preview_run_with_jobs

    promoted = await promote_preview_jobs(session, run_id, ["nonexistent-job"])
    assert promoted == []


@pytest.mark.asyncio
async def test_promote_already_promoted_jobs_skipped(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Jobs that are already promoted are not promoted again."""
    run_id, job_ids = preview_run_with_jobs

    # Promote once
    first_result = await promote_preview_jobs(session, run_id, [job_ids[0]])
    assert first_result == [job_ids[0]]

    # Try to promote the same job again
    second_result = await promote_preview_jobs(session, run_id, [job_ids[0]])
    assert second_result == []


@pytest.mark.asyncio
async def test_promote_copies_job_title_and_company(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Promoted job records have the correct title, company, and URL from preview."""
    run_id, job_ids = preview_run_with_jobs

    await promote_preview_jobs(session, run_id, [job_ids[0]])

    result = await session.execute(select(JobRecord).where(JobRecord.id == job_ids[0]))
    record = result.scalar_one()
    assert record.job_title == f"Engineer at {job_ids[0]}"
    assert record.company == f"Company-{job_ids[0]}"
    assert record.linkedin_url == f"https://linkedin.com/jobs/view/{job_ids[0]}"


@pytest.mark.asyncio
async def test_promote_wrong_run_id_returns_empty(
    session: AsyncSession, preview_run_with_jobs: tuple[str, list[str]]
) -> None:
    """Promoting with a wrong run_id returns empty even if job_ids exist."""
    _, job_ids = preview_run_with_jobs

    promoted = await promote_preview_jobs(session, "wrong-run-id", job_ids)
    assert promoted == []
