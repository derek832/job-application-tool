"""
Unit tests for the job record repository (src/db/job_repo.py).

Uses a real in-memory SQLite database to validate repository operations
against the actual ORM models and schema.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, JobRecord, StatusTransition, VALID_STATUSES
from src.db.job_repo import (
    create_job_record,
    get_job_record,
    get_queue_items,
    get_stats,
    list_jobs,
    update_job_status,
    TERMINAL_STATUSES,
)


@pytest.fixture
async def engine():
    """Create an in-memory async SQLite engine for testing."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncSession:
    """Yield a fresh AsyncSession for each test."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# create_job_record
# ---------------------------------------------------------------------------


class TestCreateJobRecord:
    async def test_creates_record_with_discovered_status(self, session: AsyncSession):
        record = await create_job_record(
            session,
            id="123456",
            job_title="Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/123456",
            apply_type="easy_apply",
        )

        assert record.id == "123456"
        assert record.status == "discovered"
        assert record.job_title == "Software Engineer"
        assert record.company == "Acme Corp"
        assert record.discovered_at is not None
        assert record.updated_at is not None

    async def test_sets_timestamps(self, session: AsyncSession):
        record = await create_job_record(
            session,
            id="789",
            job_title="Data Scientist",
            company="BigCo",
            linkedin_url="https://linkedin.com/jobs/view/789",
            apply_type="external_apply",
        )

        assert record.discovered_at == record.updated_at
        # ISO 8601 format check
        assert "T" in record.discovered_at

    async def test_optional_fields_default_to_none(self, session: AsyncSession):
        record = await create_job_record(
            session,
            id="456",
            job_title="PM",
            company="StartupX",
            linkedin_url="https://linkedin.com/jobs/view/456",
            apply_type="easy_apply",
        )

        assert record.location is None
        assert record.external_url is None
        assert record.fit_score is None
        assert record.queue_reason is None


# ---------------------------------------------------------------------------
# get_job_record
# ---------------------------------------------------------------------------


class TestGetJobRecord:
    async def test_returns_existing_record(self, session: AsyncSession):
        await create_job_record(
            session,
            id="111",
            job_title="Engineer",
            company="TestCo",
            linkedin_url="https://linkedin.com/jobs/view/111",
            apply_type="easy_apply",
        )

        found = await get_job_record(session, "111")
        assert found is not None
        assert found.id == "111"
        assert found.company == "TestCo"

    async def test_returns_none_for_missing_record(self, session: AsyncSession):
        found = await get_job_record(session, "nonexistent")
        assert found is None


# ---------------------------------------------------------------------------
# update_job_status
# ---------------------------------------------------------------------------


class TestUpdateJobStatus:
    async def test_updates_status_and_timestamp(self, session: AsyncSession):
        await create_job_record(
            session,
            id="200",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/200",
            apply_type="easy_apply",
        )

        updated = await update_job_status(session, "200", "extracted", reason="scraped ok")
        assert updated.status == "extracted"
        assert updated.updated_at is not None

    async def test_writes_status_transition_row(self, session: AsyncSession):
        await create_job_record(
            session,
            id="201",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/201",
            apply_type="easy_apply",
        )

        await update_job_status(session, "201", "extracted", reason="success")

        from sqlalchemy import select

        result = await session.execute(
            select(StatusTransition).where(StatusTransition.job_id == "201")
        )
        transitions = list(result.scalars().all())
        assert len(transitions) == 1
        assert transitions[0].from_status == "discovered"
        assert transitions[0].to_status == "extracted"
        assert transitions[0].reason == "success"
        assert transitions[0].timestamp is not None

    async def test_raises_value_error_for_invalid_status(self, session: AsyncSession):
        await create_job_record(
            session,
            id="202",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/202",
            apply_type="easy_apply",
        )

        with pytest.raises(ValueError, match="Invalid status"):
            await update_job_status(session, "202", "bogus_status")

    async def test_raises_value_error_for_missing_job(self, session: AsyncSession):
        with pytest.raises(ValueError, match="No JobRecord found"):
            await update_job_status(session, "nonexistent", "extracted")

    async def test_accepts_all_valid_statuses(self, session: AsyncSession):
        """Every status in VALID_STATUSES should be accepted without error."""
        for i, status in enumerate(sorted(VALID_STATUSES)):
            job_id = f"valid_{i}"
            await create_job_record(
                session,
                id=job_id,
                job_title="Test",
                company="Co",
                linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )
            updated = await update_job_status(session, job_id, status)
            assert updated.status == status


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    async def _seed_jobs(self, session: AsyncSession):
        """Seed 5 jobs with varying statuses and names."""
        jobs = [
            ("j1", "Python Developer", "Acme", "discovered"),
            ("j2", "Java Engineer", "BigCo", "extracted"),
            ("j3", "Python Lead", "StartupX", "applied"),
            ("j4", "Data Scientist", "Acme", "skipped"),
            ("j5", "ML Engineer", "DataCorp", "discovered"),
        ]
        for job_id, title, company, status in jobs:
            record = await create_job_record(
                session,
                id=job_id,
                job_title=title,
                company=company,
                linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )
            if status != "discovered":
                await update_job_status(session, job_id, status)

    async def test_returns_all_jobs_without_filters(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session)
        assert len(jobs) == 5

    async def test_filters_by_status(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session, status="discovered")
        assert len(jobs) == 2
        assert all(j.status == "discovered" for j in jobs)

    async def test_filters_by_search_in_title(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session, search="Python")
        assert len(jobs) == 2

    async def test_filters_by_search_in_company(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session, search="Acme")
        assert len(jobs) == 2

    async def test_search_is_case_insensitive(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session, search="python")
        assert len(jobs) == 2

    async def test_pagination(self, session: AsyncSession):
        await self._seed_jobs(session)
        page1 = await list_jobs(session, page=1, limit=2)
        page2 = await list_jobs(session, page=2, limit=2)
        page3 = await list_jobs(session, page=3, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

    async def test_combined_filters(self, session: AsyncSession):
        await self._seed_jobs(session)
        jobs = await list_jobs(session, status="discovered", search="Python")
        assert len(jobs) == 1
        assert jobs[0].job_title == "Python Developer"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    async def test_empty_db_returns_zeros(self, session: AsyncSession):
        stats = await get_stats(session)
        assert stats["total_discovered"] == 0
        assert stats["total_applied"] == 0
        assert stats["total_skipped"] == 0
        assert stats["total_pending_review"] == 0
        assert stats["application_success_rate"] == 0.0

    async def test_counts_statuses_correctly(self, session: AsyncSession):
        # Create jobs in various states
        for i in range(3):
            await create_job_record(
                session,
                id=f"applied_{i}",
                job_title="Dev",
                company="Co",
                linkedin_url=f"https://linkedin.com/jobs/view/applied_{i}",
                apply_type="easy_apply",
            )
            await update_job_status(session, f"applied_{i}", "approved_for_apply")
            await update_job_status(session, f"applied_{i}", "applied")

        for i in range(2):
            await create_job_record(
                session,
                id=f"skipped_{i}",
                job_title="Dev",
                company="Co",
                linkedin_url=f"https://linkedin.com/jobs/view/skipped_{i}",
                apply_type="easy_apply",
            )
            await update_job_status(session, f"skipped_{i}", "skipped")

        stats = await get_stats(session)
        assert stats["total_discovered"] == 5
        assert stats["total_applied"] == 3
        assert stats["total_skipped"] == 2

    async def test_success_rate_calculation(self, session: AsyncSession):
        # 2 applied, 1 still at approved_for_apply → rate = 2 / (2 + 1) = 0.666...
        for i in range(2):
            await create_job_record(
                session,
                id=f"done_{i}",
                job_title="Dev",
                company="Co",
                linkedin_url=f"https://linkedin.com/jobs/view/done_{i}",
                apply_type="easy_apply",
            )
            await update_job_status(session, f"done_{i}", "approved_for_apply")
            await update_job_status(session, f"done_{i}", "applied")

        await create_job_record(
            session,
            id="pending_apply",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/pending_apply",
            apply_type="easy_apply",
        )
        await update_job_status(session, "pending_apply", "approved_for_apply")

        stats = await get_stats(session)
        # denominator = applied(2) + approved_for_apply(1) = 3
        assert stats["application_success_rate"] == pytest.approx(2 / 3)

    async def test_pending_review_counts_queued_non_terminal(self, session: AsyncSession):
        # Job in queue with non-terminal status
        record = await create_job_record(
            session,
            id="queued_1",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/queued_1",
            apply_type="easy_apply",
        )
        record.queue_reason = "stretch_role"
        await update_job_status(session, "queued_1", "scored")

        # Job in queue but terminal (should NOT count)
        record2 = await create_job_record(
            session,
            id="queued_2",
            job_title="Dev",
            company="Co",
            linkedin_url="https://linkedin.com/jobs/view/queued_2",
            apply_type="easy_apply",
        )
        record2.queue_reason = "manually_resolved"
        await update_job_status(session, "queued_2", "applied")

        await session.flush()
        stats = await get_stats(session)
        assert stats["total_pending_review"] == 1


# ---------------------------------------------------------------------------
# get_queue_items
# ---------------------------------------------------------------------------


class TestGetQueueItems:
    async def test_returns_jobs_with_queue_reason_non_terminal(self, session: AsyncSession):
        record = await create_job_record(
            session,
            id="q1",
            job_title="Engineer",
            company="QueueCo",
            linkedin_url="https://linkedin.com/jobs/view/q1",
            apply_type="easy_apply",
        )
        record.queue_reason = "stretch_role"
        await update_job_status(session, "q1", "scored")
        await session.flush()

        items = await get_queue_items(session)
        assert len(items) == 1
        assert items[0].id == "q1"

    async def test_excludes_terminal_status_jobs(self, session: AsyncSession):
        record = await create_job_record(
            session,
            id="q2",
            job_title="Engineer",
            company="TermCo",
            linkedin_url="https://linkedin.com/jobs/view/q2",
            apply_type="easy_apply",
        )
        record.queue_reason = "was_stretch"
        await update_job_status(session, "q2", "applied")
        await session.flush()

        items = await get_queue_items(session)
        assert len(items) == 0

    async def test_excludes_jobs_without_queue_reason(self, session: AsyncSession):
        await create_job_record(
            session,
            id="q3",
            job_title="Engineer",
            company="NoCo",
            linkedin_url="https://linkedin.com/jobs/view/q3",
            apply_type="easy_apply",
        )

        items = await get_queue_items(session)
        assert len(items) == 0

    async def test_returns_multiple_queue_items(self, session: AsyncSession):
        for i in range(3):
            record = await create_job_record(
                session,
                id=f"mq_{i}",
                job_title=f"Role {i}",
                company="MultiCo",
                linkedin_url=f"https://linkedin.com/jobs/view/mq_{i}",
                apply_type="easy_apply",
            )
            record.queue_reason = "stretch_role"
            await update_job_status(session, f"mq_{i}", "scored")

        await session.flush()
        items = await get_queue_items(session)
        assert len(items) == 3
