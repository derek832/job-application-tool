"""Unit tests for src/pipeline/run_summary.py.

Covers:
- RunStats dataclass instantiation
- generate_summary_text output format, max length, and edge cases
- store_run_summary persistence and retention call
- enforce_retention deletion of old records
- get_recent_summaries ordering and limit

Validates: Requirements 5.1, 5.2, 5.4, 5.5
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, RunSummary
from src.pipeline.run_summary import (
    RunStats,
    enforce_retention,
    generate_summary_text,
    get_recent_summaries,
    store_run_summary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_IN_MEMORY_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    """Create an in-memory async engine with all tables."""
    eng = create_async_engine(_IN_MEMORY_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    """Create an async session for testing."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as sess:
        yield sess


# ---------------------------------------------------------------------------
# RunStats dataclass
# ---------------------------------------------------------------------------


class TestRunStats:
    """Tests for the RunStats dataclass."""

    def test_basic_instantiation(self) -> None:
        stats = RunStats(
            jobs_discovered=10,
            jobs_scored=8,
            jobs_prefiltered=0,
            jobs_approved=5,
            jobs_applied=3,
            jobs_skipped=4,
            jobs_escalated=1,
            errors=[],
        )
        assert stats.jobs_discovered == 10
        assert stats.jobs_scored == 8
        assert stats.jobs_approved == 5
        assert stats.jobs_applied == 3
        assert stats.jobs_skipped == 4
        assert stats.jobs_escalated == 1
        assert stats.errors == []

    def test_errors_default_empty_list(self) -> None:
        stats = RunStats(
            jobs_discovered=0,
            jobs_scored=0,
            jobs_prefiltered=0,
            jobs_approved=0,
            jobs_applied=0,
            jobs_skipped=0,
            jobs_escalated=0,
        )
        assert stats.errors == []

    def test_with_errors(self) -> None:
        stats = RunStats(
            jobs_discovered=5,
            jobs_scored=3,
            jobs_prefiltered=0,
            jobs_approved=2,
            jobs_applied=1,
            jobs_skipped=1,
            jobs_escalated=1,
            errors=["timeout", "API error"],
        )
        assert len(stats.errors) == 2


# ---------------------------------------------------------------------------
# generate_summary_text
# ---------------------------------------------------------------------------


class TestGenerateSummaryText:
    """Tests for the generate_summary_text function."""

    def test_typical_run(self) -> None:
        stats = RunStats(
            jobs_discovered=12,
            jobs_scored=10,
            jobs_prefiltered=0,
            jobs_approved=5,
            jobs_applied=3,
            jobs_skipped=5,
            jobs_escalated=2,
        )
        result = generate_summary_text(stats)
        assert "found 12 new jobs" in result
        assert "scored 10" in result
        assert "applied to 3" in result
        assert "skipped 5" in result
        assert "2 need your review" in result
        assert "No errors" in result

    def test_zero_jobs(self) -> None:
        stats = RunStats(
            jobs_discovered=0,
            jobs_scored=0,
            jobs_prefiltered=0,
            jobs_approved=0,
            jobs_applied=0,
            jobs_skipped=0,
            jobs_escalated=0,
        )
        result = generate_summary_text(stats)
        assert "found 0 new jobs" in result
        assert "No errors" in result

    def test_with_errors(self) -> None:
        stats = RunStats(
            jobs_discovered=5,
            jobs_scored=3,
            jobs_prefiltered=0,
            jobs_approved=2,
            jobs_applied=1,
            jobs_skipped=1,
            jobs_escalated=0,
            errors=["timeout on page load", "API rate limit"],
        )
        result = generate_summary_text(stats)
        assert "Errors:" in result
        assert "timeout on page load" in result
        assert "API rate limit" in result

    def test_max_500_chars(self) -> None:
        # Create stats with very long error messages
        long_errors = [f"Error message number {i} with extra detail" * 5 for i in range(10)]
        stats = RunStats(
            jobs_discovered=999,
            jobs_scored=888,
            jobs_prefiltered=0,
            jobs_approved=777,
            jobs_applied=666,
            jobs_skipped=555,
            jobs_escalated=444,
            errors=long_errors,
        )
        result = generate_summary_text(stats)
        assert len(result) <= 500

    def test_non_empty(self) -> None:
        stats = RunStats(
            jobs_discovered=0,
            jobs_scored=0,
            jobs_prefiltered=0,
            jobs_approved=0,
            jobs_applied=0,
            jobs_skipped=0,
            jobs_escalated=0,
        )
        result = generate_summary_text(stats)
        assert len(result) > 0

    def test_contains_discovered_count(self) -> None:
        stats = RunStats(
            jobs_discovered=42,
            jobs_scored=0,
            jobs_prefiltered=0,
            jobs_approved=0,
            jobs_applied=0,
            jobs_skipped=0,
            jobs_escalated=0,
        )
        result = generate_summary_text(stats)
        assert "42" in result


# ---------------------------------------------------------------------------
# store_run_summary
# ---------------------------------------------------------------------------


class TestStoreRunSummary:
    """Tests for the store_run_summary function."""

    @pytest.mark.asyncio
    async def test_creates_record(self, session: AsyncSession) -> None:
        stats = RunStats(
            jobs_discovered=10,
            jobs_scored=8,
            jobs_prefiltered=0,
            jobs_approved=5,
            jobs_applied=3,
            jobs_skipped=4,
            jobs_escalated=1,
            errors=["one error"],
        )
        summary_text = "Run complete: found 10 jobs. No errors."

        record = await store_run_summary(session, stats, summary_text)

        assert record.id is not None
        assert record.summary == summary_text
        assert record.jobs_discovered == 10
        assert record.jobs_scored == 8
        assert record.jobs_approved == 5
        assert record.jobs_applied == 3
        assert record.jobs_skipped == 4
        assert record.jobs_escalated == 1
        assert json.loads(record.errors) == ["one error"]
        assert record.created_at is not None

    @pytest.mark.asyncio
    async def test_no_errors_stores_null(self, session: AsyncSession) -> None:
        stats = RunStats(
            jobs_discovered=5,
            jobs_scored=3,
            jobs_prefiltered=0,
            jobs_approved=2,
            jobs_applied=1,
            jobs_skipped=1,
            jobs_escalated=0,
            errors=[],
        )
        summary_text = "Run complete: found 5 jobs. No errors."

        record = await store_run_summary(session, stats, summary_text)

        assert record.errors is None

    @pytest.mark.asyncio
    async def test_uuid_format(self, session: AsyncSession) -> None:
        stats = RunStats(
            jobs_discovered=1,
            jobs_scored=1,
            jobs_prefiltered=0,
            jobs_approved=0,
            jobs_applied=0,
            jobs_skipped=0,
            jobs_escalated=0,
        )
        record = await store_run_summary(session, stats, "Test summary.")

        # UUID4 format: 8-4-4-4-12 hex chars
        parts = record.id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12


# ---------------------------------------------------------------------------
# enforce_retention
# ---------------------------------------------------------------------------


class TestEnforceRetention:
    """Tests for the enforce_retention function."""

    @pytest.mark.asyncio
    async def test_keeps_max_records(self, session: AsyncSession) -> None:
        # Insert 25 records
        for i in range(25):
            record = RunSummary(
                id=f"id-{i:03d}",
                summary=f"Summary {i}",
                jobs_discovered=i,
                jobs_scored=0,
                jobs_prefiltered=0,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=None,
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            )
            session.add(record)
        await session.flush()

        await enforce_retention(session, max_records=20)

        remaining = await get_recent_summaries(session, limit=100)
        assert len(remaining) == 20

    @pytest.mark.asyncio
    async def test_no_deletion_when_under_limit(self, session: AsyncSession) -> None:
        # Insert 5 records
        for i in range(5):
            record = RunSummary(
                id=f"id-{i:03d}",
                summary=f"Summary {i}",
                jobs_discovered=i,
                jobs_scored=0,
                jobs_prefiltered=0,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=None,
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            )
            session.add(record)
        await session.flush()

        await enforce_retention(session, max_records=20)

        remaining = await get_recent_summaries(session, limit=100)
        assert len(remaining) == 5

    @pytest.mark.asyncio
    async def test_keeps_most_recent(self, session: AsyncSession) -> None:
        # Insert 5 records, keep only 3
        for i in range(5):
            record = RunSummary(
                id=f"id-{i:03d}",
                summary=f"Summary {i}",
                jobs_discovered=i,
                jobs_scored=0,
                jobs_prefiltered=0,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=None,
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            )
            session.add(record)
        await session.flush()

        await enforce_retention(session, max_records=3)

        remaining = await get_recent_summaries(session, limit=100)
        assert len(remaining) == 3
        # Most recent should be kept (Jan 5, 4, 3)
        ids = [r.id for r in remaining]
        assert "id-004" in ids
        assert "id-003" in ids
        assert "id-002" in ids


# ---------------------------------------------------------------------------
# get_recent_summaries
# ---------------------------------------------------------------------------


class TestGetRecentSummaries:
    """Tests for the get_recent_summaries function."""

    @pytest.mark.asyncio
    async def test_returns_ordered_by_created_at_desc(self, session: AsyncSession) -> None:
        for i in range(5):
            record = RunSummary(
                id=f"id-{i:03d}",
                summary=f"Summary {i}",
                jobs_discovered=i,
                jobs_scored=0,
                jobs_prefiltered=0,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=None,
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            )
            session.add(record)
        await session.flush()

        results = await get_recent_summaries(session, limit=5)

        assert len(results) == 5
        # Most recent first
        assert results[0].id == "id-004"
        assert results[4].id == "id-000"

    @pytest.mark.asyncio
    async def test_respects_limit(self, session: AsyncSession) -> None:
        for i in range(10):
            record = RunSummary(
                id=f"id-{i:03d}",
                summary=f"Summary {i}",
                jobs_discovered=i,
                jobs_scored=0,
                jobs_prefiltered=0,
                jobs_approved=0,
                jobs_applied=0,
                jobs_skipped=0,
                jobs_escalated=0,
                errors=None,
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00",
            )
            session.add(record)
        await session.flush()

        results = await get_recent_summaries(session, limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_table(self, session: AsyncSession) -> None:
        results = await get_recent_summaries(session, limit=5)
        assert results == []
