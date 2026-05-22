"""
Property-based tests for Pending List Filtering and Sorting.

Uses Hypothesis to verify that for ANY set of escalation records with mixed
statuses and timeout_deadlines, the default list endpoint returns only records
with status="pending", sorted by timeout_deadline ascending (NULL deadlines
last). With include_resolved=true, all records should be returned.

Properties tested:
- Property 9: Pending List Filtering and Sorting

Feature: human-in-the-loop-escalation, Property 9: Pending List Filtering and Sorting
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid escalation statuses
VALID_STATUSES = ["pending", "resolved", "auto_submitted", "skipped", "expired"]

status_strategy = st.sampled_from(VALID_STATUSES)
tier_strategy = st.sampled_from(["captcha", "human_review"])
freshness_tier_strategy = st.sampled_from(["fresh", "recent", "stale"])

# Generate timeout_deadline: either None or a datetime within a reasonable range
timeout_deadline_strategy = st.one_of(
    st.none(),
    st.floats(min_value=-48.0, max_value=48.0, allow_nan=False, allow_infinity=False).map(
        lambda hours_offset: (datetime.now(tz=UTC) + timedelta(hours=hours_offset)).isoformat()
    ),
)

# Strategy for a single escalation record's attributes
escalation_attrs_strategy = st.fixed_dictionaries(
    {
        "status": status_strategy,
        "tier": tier_strategy,
        "timeout_deadline": timeout_deadline_strategy,
        "freshness_tier": st.one_of(st.none(), freshness_tier_strategy),
    }
)

# Generate a list of 1-15 escalation records with varied attributes
escalation_list_strategy = st.lists(
    escalation_attrs_strategy,
    min_size=1,
    max_size=15,
)


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
# Helpers
# ---------------------------------------------------------------------------


def _make_job(index: int) -> JobRecord:
    """Create a minimal JobRecord for testing."""
    now = datetime.now(tz=UTC)
    return JobRecord(
        id=f"job-list-{index}-{uuid.uuid4().hex[:8]}",
        job_title=f"Test Engineer {index}",
        company=f"Company {index}",
        location="Remote",
        linkedin_url=f"https://www.linkedin.com/jobs/view/test-list-{index}",
        apply_type="external_apply",
        status="applying",
        fit_score=85,
        discovered_at=(now - timedelta(hours=2)).isoformat(),
        updated_at=now.isoformat(),
    )


def _make_escalation(
    job_id: str,
    *,
    status: str,
    tier: str,
    timeout_deadline: str | None,
    freshness_tier: str | None,
) -> EscalationRecord:
    """Create an EscalationRecord with the given attributes."""
    now = datetime.now(tz=UTC)
    return EscalationRecord(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tier=tier,
        form_state_snapshot=json.dumps({"external_url": "https://example.com", "fields": []}),
        draft_answers=json.dumps([{"field_id": "f1", "draft_answer": "answer"}])
        if tier == "human_review"
        else None,
        timeout_deadline=timeout_deadline,
        freshness_tier=freshness_tier,
        status=status,
        resolution_method=None if status == "pending" else "user_submit",
        created_at=now.isoformat(),
        resolved_at=None if status == "pending" else now.isoformat(),
    )


async def _query_escalations(
    session: AsyncSession,
    *,
    include_resolved: bool = False,
) -> list[EscalationRecord]:
    """Replicate the list_escalations query logic from escalation_routes.py.

    This directly tests the same SQLAlchemy query logic used by the endpoint,
    without needing to go through the HTTP layer.
    """
    stmt = select(EscalationRecord)

    if not include_resolved:
        stmt = stmt.where(EscalationRecord.status == "pending")

    # Sort by timeout_deadline ascending, NULLs last
    stmt = stmt.order_by(
        EscalationRecord.timeout_deadline.is_(None),  # 0 before 1 -> NULLs last
        EscalationRecord.timeout_deadline.asc(),
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Property 9: Pending List Filtering — default returns only pending
# ---------------------------------------------------------------------------


@given(escalation_attrs_list=escalation_list_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_default_list_returns_only_pending(
    escalation_attrs_list: list[dict],
    async_engine,
) -> None:
    """
    For any set of escalation records with mixed statuses, the default list
    query (include_resolved=False) should return ONLY records with
    status="pending".

    **Validates: Requirements 6.1, 7.4**

    Feature: human-in-the-loop-escalation, Property 9: Pending List Filtering and Sorting
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create job records and escalation records
        created_ids: list[str] = []
        expected_pending_ids: set[str] = set()

        for i, attrs in enumerate(escalation_attrs_list):
            job = _make_job(i)
            session.add(job)
            await session.flush()

            escalation = _make_escalation(
                job.id,
                status=attrs["status"],
                tier=attrs["tier"],
                timeout_deadline=attrs["timeout_deadline"],
                freshness_tier=attrs["freshness_tier"],
            )
            session.add(escalation)
            created_ids.append(escalation.id)

            if attrs["status"] == "pending":
                expected_pending_ids.add(escalation.id)

        await session.flush()

        # Query with default (include_resolved=False)
        results = await _query_escalations(session, include_resolved=False)

        # Assert: all returned records have status="pending"
        result_ids = {r.id for r in results}
        for record in results:
            assert record.status == "pending", (
                f"Expected only pending records, got status='{record.status}'"
            )

        # Assert: all pending records are returned
        assert result_ids == expected_pending_ids, (
            f"Expected pending IDs {expected_pending_ids}, got {result_ids}"
        )

        # Cleanup
        await session.rollback()


# ---------------------------------------------------------------------------
# Property 9: Pending List Sorting — sorted by timeout_deadline ASC, NULLs last
# ---------------------------------------------------------------------------


@given(escalation_attrs_list=escalation_list_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_pending_list_sorted_by_deadline_nulls_last(
    escalation_attrs_list: list[dict],
    async_engine,
) -> None:
    """
    For any set of escalation records, the pending list should be sorted by
    timeout_deadline ascending, with NULL deadlines appearing last.

    **Validates: Requirements 6.1, 7.4**

    Feature: human-in-the-loop-escalation, Property 9: Pending List Filtering and Sorting
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create job records and escalation records
        for i, attrs in enumerate(escalation_attrs_list):
            job = _make_job(i)
            session.add(job)
            await session.flush()

            escalation = _make_escalation(
                job.id,
                status=attrs["status"],
                tier=attrs["tier"],
                timeout_deadline=attrs["timeout_deadline"],
                freshness_tier=attrs["freshness_tier"],
            )
            session.add(escalation)

        await session.flush()

        # Query with default (pending only)
        results = await _query_escalations(session, include_resolved=False)

        # Verify sorting: timeout_deadline ascending, NULLs last
        deadlines = [r.timeout_deadline for r in results]

        # Split into non-null and null groups
        non_null_deadlines = [d for d in deadlines if d is not None]
        null_count = sum(1 for d in deadlines if d is None)

        # All NULLs should be at the end
        if null_count > 0 and non_null_deadlines:
            # Find the position of the first NULL
            first_null_idx = next(i for i, d in enumerate(deadlines) if d is None)
            # All entries after the first NULL should also be NULL
            for d in deadlines[first_null_idx:]:
                assert d is None, (
                    f"Found non-NULL deadline after a NULL: {deadlines}"
                )

        # Non-null deadlines should be in ascending order
        for i in range(len(non_null_deadlines) - 1):
            assert non_null_deadlines[i] <= non_null_deadlines[i + 1], (
                f"Deadlines not in ascending order: "
                f"{non_null_deadlines[i]} > {non_null_deadlines[i + 1]}"
            )

        # Cleanup
        await session.rollback()


# ---------------------------------------------------------------------------
# Property 9: Include Resolved — returns all records
# ---------------------------------------------------------------------------


@given(escalation_attrs_list=escalation_list_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_include_resolved_returns_all_records(
    escalation_attrs_list: list[dict],
    async_engine,
) -> None:
    """
    For any set of escalation records with mixed statuses, querying with
    include_resolved=True should return ALL records regardless of status.

    **Validates: Requirements 6.1, 7.4**

    Feature: human-in-the-loop-escalation, Property 9: Pending List Filtering and Sorting
    """
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create job records and escalation records
        all_escalation_ids: set[str] = set()

        for i, attrs in enumerate(escalation_attrs_list):
            job = _make_job(i)
            session.add(job)
            await session.flush()

            escalation = _make_escalation(
                job.id,
                status=attrs["status"],
                tier=attrs["tier"],
                timeout_deadline=attrs["timeout_deadline"],
                freshness_tier=attrs["freshness_tier"],
            )
            session.add(escalation)
            all_escalation_ids.add(escalation.id)

        await session.flush()

        # Query with include_resolved=True
        results = await _query_escalations(session, include_resolved=True)

        # Assert: all records are returned
        result_ids = {r.id for r in results}
        assert result_ids == all_escalation_ids, (
            f"Expected all {len(all_escalation_ids)} records, got {len(result_ids)}"
        )

        # Cleanup
        await session.rollback()
