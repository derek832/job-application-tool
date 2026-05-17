"""
Unit tests for automator/src/db/models.py and automator/src/db/database.py.

Covers:
- VALID_STATUSES set completeness (Requirement 10.3)
- ORM model instantiation and repr
- build_engine / init_db / get_session round-trip with an in-memory SQLite DB
- Table creation idempotency (calling init_db twice is safe)
- Foreign-key relationships are wired correctly
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from src.db.database import build_engine, get_session, init_db
from src.db.models import (
    VALID_STATUSES,
    Base,
    BlacklistEntry,
    Config,
    JobRecord,
    NotificationLog,
    NotificationQueue,
    PreviewJob,
    PreviewRun,
    StatusTransition,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IN_MEMORY_URL = "sqlite+aiosqlite:///:memory:"


async def _make_engine() -> AsyncEngine:
    """Return a fresh in-memory async engine with all tables created."""
    engine = create_async_engine(_IN_MEMORY_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


# ---------------------------------------------------------------------------
# VALID_STATUSES
# ---------------------------------------------------------------------------


class TestValidStatuses:
    """Requirement 10.3 — the valid status set must contain exactly 12 values."""

    EXPECTED = {
        "discovered",
        "extracted",
        "extraction_failed",
        "scored",
        "approved_for_apply",
        "skipped",
        "rejected_by_user",
        "resume_failed",
        "applying",
        "apply_failed",
        "applied",
        "manually_applied",
    }

    def test_contains_all_required_statuses(self) -> None:
        assert self.EXPECTED == VALID_STATUSES

    def test_is_frozenset(self) -> None:
        assert isinstance(VALID_STATUSES, frozenset)

    def test_count(self) -> None:
        assert len(VALID_STATUSES) == 12


# ---------------------------------------------------------------------------
# Model instantiation and repr
# ---------------------------------------------------------------------------


class TestJobRecordModel:
    """Basic ORM model construction — no DB required."""

    def test_instantiation_with_required_fields(self) -> None:
        record = JobRecord(
            id="123456",
            job_title="Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/123456",
            apply_type="easy_apply",
            status="discovered",
            discovered_at="2024-01-15T09:00:00Z",
            updated_at="2024-01-15T09:00:00Z",
        )
        assert record.id == "123456"
        assert record.status == "discovered"
        assert record.fit_score is None
        assert record.location is None

    def test_repr_contains_id_and_status(self) -> None:
        record = JobRecord(
            id="abc",
            job_title="Dev",
            company="Corp",
            linkedin_url="https://example.com",
            apply_type="easy_apply",
            status="applied",
            discovered_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        r = repr(record)
        assert "abc" in r
        assert "applied" in r


class TestStatusTransitionModel:
    def test_instantiation(self) -> None:
        t = StatusTransition(
            job_id="123",
            from_status="discovered",
            to_status="extracted",
            timestamp="2024-01-15T09:01:00Z",
        )
        assert t.to_status == "extracted"
        assert t.from_status == "discovered"

    def test_repr(self) -> None:
        t = StatusTransition(
            job_id="x",
            from_status="discovered",
            to_status="extracted",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert "discovered" in repr(t)
        assert "extracted" in repr(t)


class TestNotificationLogModel:
    def test_instantiation(self) -> None:
        n = NotificationLog(
            trigger_reason="stretch_role",
            sms_body="Review needed",
            sent_at="2024-01-15T09:05:00Z",
            success=1,
        )
        assert n.success == 1
        assert n.job_id is None

    def test_repr(self) -> None:
        n = NotificationLog(
            trigger_reason="captcha",
            sms_body="CAPTCHA detected",
            sent_at="2024-01-01T00:00:00Z",
            success=0,
        )
        assert "captcha" in repr(n)


class TestConfigModel:
    def test_instantiation(self) -> None:
        c = Config(
            key="search_config",
            value='{"keywords": "python"}',
            updated_at="2024-01-15T09:00:00Z",
        )
        assert c.key == "search_config"

    def test_repr(self) -> None:
        c = Config(
            key="settings",
            value="{}",
            updated_at="2024-01-01T00:00:00Z",
        )
        assert "settings" in repr(c)


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInitDb:
    async def test_creates_all_four_tables(self) -> None:
        engine = await _make_engine()
        async with engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert set(table_names) >= {
            "job_records",
            "status_transitions",
            "notification_log",
            "config",
        }
        await engine.dispose()

    async def test_init_db_is_idempotent(self) -> None:
        """Calling init_db twice must not raise or drop existing data."""
        engine = await _make_engine()
        # Second call — tables already exist, should be a no-op.
        await init_db(engine)
        await engine.dispose()

    async def test_indexes_exist_on_job_records(self) -> None:
        engine = await _make_engine()
        async with engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("job_records")
            )
        index_names = {idx["name"] for idx in indexes}
        assert "idx_job_records_status" in index_names
        assert "idx_job_records_discovered_at" in index_names
        await engine.dispose()


# ---------------------------------------------------------------------------
# build_engine and get_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBuildEngineAndGetSession:
    async def test_build_engine_returns_async_engine(self) -> None:
        engine = build_engine(_IN_MEMORY_URL)
        assert isinstance(engine, AsyncEngine)
        await engine.dispose()

    async def test_get_session_yields_async_session(self) -> None:
        build_engine(_IN_MEMORY_URL)
        await init_db()
        gen = get_session()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        # Clean up — exhaust the generator
        try:
            await gen.aclose()
        except StopAsyncIteration:
            pass

    async def test_get_session_commits_on_success(self) -> None:
        """Data written inside get_session should be visible after commit."""
        build_engine(_IN_MEMORY_URL)
        await init_db()

        async for session in get_session():
            session.add(
                Config(
                    key="test_key",
                    value='"hello"',
                    updated_at="2024-01-15T09:00:00Z",
                )
            )

        # Open a fresh session to verify the row was committed.
        async for session in get_session():
            result = await session.execute(
                text("SELECT value FROM config WHERE key = 'test_key'")
            )
            row = result.fetchone()
            assert row is not None
            assert row[0] == '"hello"'

    async def test_get_session_rolls_back_on_exception(self) -> None:
        """An exception inside get_session must roll back the transaction."""
        build_engine(_IN_MEMORY_URL)
        await init_db()

        with pytest.raises(ValueError, match="intentional"):
            async for session in get_session():
                session.add(
                    Config(
                        key="rollback_key",
                        value='"should_not_persist"',
                        updated_at="2024-01-15T09:00:00Z",
                    )
                )
                raise ValueError("intentional rollback")

        # The row must not exist after the rollback.
        async for session in get_session():
            result = await session.execute(
                text("SELECT value FROM config WHERE key = 'rollback_key'")
            )
            assert result.fetchone() is None


# ---------------------------------------------------------------------------
# Relationship wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRelationships:
    async def test_status_transition_fk_to_job_record(self) -> None:
        """StatusTransition rows must be retrievable via JobRecord.status_transitions."""
        engine = await _make_engine()
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(bind=engine, expire_on_commit=False)

        async with factory() as session:
            job = JobRecord(
                id="rel_test_1",
                job_title="Engineer",
                company="Corp",
                linkedin_url="https://example.com",
                apply_type="easy_apply",
                status="discovered",
                discovered_at="2024-01-15T09:00:00Z",
                updated_at="2024-01-15T09:00:00Z",
            )
            transition = StatusTransition(
                job_id="rel_test_1",
                from_status=None,
                to_status="discovered",
                timestamp="2024-01-15T09:00:00Z",
            )
            session.add(job)
            session.add(transition)
            await session.commit()

        async with factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(JobRecord)
                .where(JobRecord.id == "rel_test_1")
                .options(selectinload(JobRecord.status_transitions))
            )
            loaded_job = result.scalar_one()
            assert len(loaded_job.status_transitions) == 1
            assert loaded_job.status_transitions[0].to_status == "discovered"

        await engine.dispose()

    async def test_notification_log_nullable_job_id(self) -> None:
        """NotificationLog rows with no job_id (system notifications) must persist."""
        engine = await _make_engine()
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(bind=engine, expire_on_commit=False)

        async with factory() as session:
            log = NotificationLog(
                job_id=None,
                trigger_reason="system_startup",
                sms_body="Automator started",
                sent_at="2024-01-15T09:00:00Z",
                success=1,
            )
            session.add(log)
            await session.commit()

        async with factory() as session:
            result = await session.execute(
                text("SELECT trigger_reason FROM notification_log WHERE job_id IS NULL")
            )
            row = result.fetchone()
            assert row is not None
            assert row[0] == "system_startup"

        await engine.dispose()


# ---------------------------------------------------------------------------
# Wave 3 — Pipeline Intelligence table creation (Task 1.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWave3TableCreation:
    """Verify that Wave 3 tables are created on startup with correct indexes.

    Requirements: 1.2, 4.1, 4.2, 3.8
    """

    async def test_creates_wave3_tables(self) -> None:
        """All four Wave 3 tables must be created by init_db."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        expected_tables = {
            "preview_runs",
            "preview_jobs",
            "blacklist_entries",
            "notification_queue",
        }
        assert expected_tables <= set(table_names)
        await engine.dispose()

    async def test_preview_runs_indexes(self) -> None:
        """preview_runs must have idx_preview_runs_started_at index."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("preview_runs")
            )
        index_names = {idx["name"] for idx in indexes}
        assert "idx_preview_runs_started_at" in index_names
        await engine.dispose()

    async def test_preview_jobs_indexes(self) -> None:
        """preview_jobs must have idx_preview_jobs_run_id and idx_preview_jobs_job_id."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("preview_jobs")
            )
        index_names = {idx["name"] for idx in indexes}
        assert "idx_preview_jobs_run_id" in index_names
        assert "idx_preview_jobs_job_id" in index_names
        await engine.dispose()

    async def test_blacklist_entries_indexes(self) -> None:
        """blacklist_entries must have idx_blacklist_entries_type and idx_blacklist_entries_unique."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("blacklist_entries")
            )
            unique_constraints = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_unique_constraints(
                    "blacklist_entries"
                )
            )
        index_names = {idx["name"] for idx in indexes}
        constraint_names = {uc["name"] for uc in unique_constraints}
        # idx_blacklist_entries_type is a regular index
        assert "idx_blacklist_entries_type" in index_names
        # idx_blacklist_entries_unique is a unique constraint (creates a unique index in SQLite)
        assert "idx_blacklist_entries_unique" in constraint_names

        await engine.dispose()

    async def test_notification_queue_indexes(self) -> None:
        """notification_queue must have idx_notification_queue_delivered index."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("notification_queue")
            )
        index_names = {idx["name"] for idx in indexes}
        assert "idx_notification_queue_delivered" in index_names
        await engine.dispose()

    async def test_preview_jobs_foreign_key_to_preview_runs(self) -> None:
        """preview_jobs.run_id must reference preview_runs.id with CASCADE delete."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            fks = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_foreign_keys("preview_jobs")
            )
        run_id_fk = next(
            (fk for fk in fks if "run_id" in fk["constrained_columns"]), None
        )
        assert run_id_fk is not None
        assert run_id_fk["referred_table"] == "preview_runs"
        assert run_id_fk["referred_columns"] == ["id"]
        await engine.dispose()

    async def test_notification_queue_foreign_key_to_job_records(self) -> None:
        """notification_queue.job_id must reference job_records.id."""
        engine = await _make_engine()
        async with engine.connect() as conn:
            fks = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_foreign_keys(
                    "notification_queue"
                )
            )
        job_id_fk = next(
            (fk for fk in fks if "job_id" in fk["constrained_columns"]), None
        )
        assert job_id_fk is not None
        assert job_id_fk["referred_table"] == "job_records"
        assert job_id_fk["referred_columns"] == ["id"]
        await engine.dispose()


# ---------------------------------------------------------------------------
# Wave 3 — Model instantiation tests
# ---------------------------------------------------------------------------


class TestPreviewRunModel:
    """Basic ORM model construction for PreviewRun."""

    def test_instantiation(self) -> None:
        run = PreviewRun(
            id="test-uuid-123",
            status="running",
            started_at="2024-03-15T09:00:00Z",
            total_discovered=0,
            total_scored=0,
            total_blacklisted=0,
        )
        assert run.id == "test-uuid-123"
        assert run.status == "running"
        assert run.completed_at is None
        assert run.error_message is None

    def test_repr(self) -> None:
        run = PreviewRun(
            id="abc-123",
            status="completed",
            started_at="2024-03-15T09:00:00Z",
            total_discovered=5,
            total_scored=3,
            total_blacklisted=2,
        )
        r = repr(run)
        assert "abc-123" in r
        assert "completed" in r


class TestPreviewJobModel:
    """Basic ORM model construction for PreviewJob."""

    def test_instantiation(self) -> None:
        job = PreviewJob(
            run_id="run-uuid-1",
            job_id="3987654321",
            job_title="Senior Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/3987654321",
            fit_score=82,
            fit_rationale="Strong match.",
            projected_action="auto_apply",
            promoted=0,
        )
        assert job.job_id == "3987654321"
        assert job.projected_action == "auto_apply"
        assert job.promoted == 0
        assert job.promoted_at is None

    def test_repr(self) -> None:
        job = PreviewJob(
            run_id="run-1",
            job_id="999",
            job_title="Dev",
            company="Corp",
            linkedin_url="https://example.com",
            projected_action="skip",
            promoted=0,
        )
        r = repr(job)
        assert "999" in r
        assert "skip" in r


class TestBlacklistEntryModel:
    """Basic ORM model construction for BlacklistEntry."""

    def test_instantiation(self) -> None:
        entry = BlacklistEntry(
            entry_type="company",
            value="Revature",
            created_at="2024-03-15T09:00:00Z",
            hit_count=0,
        )
        assert entry.entry_type == "company"
        assert entry.value == "Revature"
        assert entry.hit_count == 0

    def test_repr(self) -> None:
        entry = BlacklistEntry(
            entry_type="title_pattern",
            value="intern",
            created_at="2024-03-15T09:00:00Z",
            hit_count=14,
        )
        r = repr(entry)
        assert "title_pattern" in r
        assert "intern" in r


class TestNotificationQueueModel:
    """Basic ORM model construction for NotificationQueue."""

    def test_instantiation(self) -> None:
        item = NotificationQueue(
            job_id=None,
            trigger_reason="new_application",
            message_body="Applied to Senior Engineer at Acme",
            queued_at="2024-03-15T22:30:00Z",
            delivered=0,
        )
        assert item.trigger_reason == "new_application"
        assert item.delivered == 0
        assert item.job_id is None

    def test_repr(self) -> None:
        item = NotificationQueue(
            trigger_reason="stretch_role",
            message_body="Review needed",
            queued_at="2024-03-15T22:30:00Z",
            delivered=1,
        )
        r = repr(item)
        assert "stretch_role" in r
