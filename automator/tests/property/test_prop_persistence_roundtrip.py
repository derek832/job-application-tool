"""
Property-based tests for Escalation Record Persistence Round-Trip.

Uses Hypothesis to verify that after creating an escalation record and reading
it back from the database, all fields are preserved exactly — no data dropped
or altered. This includes JSON fields (form_state_snapshot, draft_answers)
which must round-trip correctly through serialization/deserialization.

Properties tested:
- Property 7: Escalation Record Persistence Round-Trip

Feature: human-in-the-loop-escalation, Property 7: Escalation Record Persistence Round-Trip
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_engine import create_escalation
from src.pipeline.notification_service import NotificationSettings


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

tier_strategy = st.sampled_from(["captcha", "human_review"])

# Generate varied form_state_snapshot dicts with different field structures
form_state_strategy = st.fixed_dictionaries(
    {
        "external_url": st.from_regex(
            r"https://[a-z]+\.(greenhouse|lever|workday)\.(io|com)/jobs/[0-9]+",
            fullmatch=True,
        ),
        "fields": st.lists(
            st.fixed_dictionaries(
                {
                    "field_id": st.text(
                        alphabet=st.characters(whitelist_categories=("L", "N")),
                        min_size=1,
                        max_size=20,
                    ),
                    "label": st.text(min_size=1, max_size=80),
                    "value": st.text(max_size=150),
                    "type": st.sampled_from(["text", "textarea", "select", "radio", "checkbox"]),
                    "selector": st.from_regex(r"#[a-z_]+[0-9]*", fullmatch=True),
                }
            ),
            min_size=0,
            max_size=8,
        ),
        "page_title": st.text(min_size=1, max_size=120),
    },
    optional={
        "screenshot_path": st.text(min_size=5, max_size=80),
    },
)

# Generate varied draft_answers lists
draft_answer_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "field_id": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            ),
            "question_text": st.text(min_size=1, max_size=150),
            "draft_answer": st.text(min_size=1, max_size=500),
            "edited_answer": st.none(),
        }
    ),
    min_size=1,
    max_size=5,
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


@pytest.fixture
def notification_settings() -> NotificationSettings:
    """Return notification settings with all channels disabled (for testing)."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=False,
        sms=None,
    )


# ---------------------------------------------------------------------------
# Property 7: Escalation Record Persistence Round-Trip
# ---------------------------------------------------------------------------


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_all_fields_preserved_after_create_and_readback(
    tier: str,
    form_state: dict,
    draft_answers: list[dict],
    async_engine,
    notification_settings: NotificationSettings,
) -> None:
    """
    For any valid escalation input data (job_id, tier, form_state_snapshot,
    draft_answers, timeout_deadline), after creating an escalation record and
    reading it back from the database, all fields should be preserved exactly
    — no data dropped or altered.

    Verifies: id, job_id, tier, form_state_snapshot, draft_answers,
    timeout_deadline, freshness_tier, status, created_at are all preserved.

    **Validates: Requirements 7.1**

    Feature: human-in-the-loop-escalation, Property 7: Escalation Record Persistence Round-Trip
    """
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        # Create a job record
        job = JobRecord(
            id=f"job-rt-{hash((tier, str(form_state)))!s}",
            job_title="Roundtrip Engineer",
            company="Persistence Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/roundtrip",
            apply_type="external_apply",
            status="applying",
            fit_score=92,
            discovered_at=discovered.isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Use draft_answers only for human_review tier
        answers = draft_answers if tier == "human_review" else None

        # Create the escalation record
        created_record = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        # Commit to persist
        await session.commit()

    # Read back in a fresh session to ensure we're reading from DB
    async with async_session_factory() as session:
        stmt = select(EscalationRecord).where(
            EscalationRecord.id == created_record.id
        )
        result = await session.execute(stmt)
        read_back = result.scalars().first()

        assert read_back is not None, "Escalation record not found after creation"

        # Verify all fields are preserved
        assert read_back.id == created_record.id
        assert read_back.job_id == created_record.job_id
        assert read_back.tier == tier
        assert read_back.status == "pending"
        assert read_back.created_at == created_record.created_at
        assert read_back.resolved_at is None
        assert read_back.resolution_method is None

        # Verify tier-specific fields
        if tier == "human_review":
            assert read_back.freshness_tier is not None
            assert read_back.freshness_tier in ("fresh", "recent", "stale")
            assert read_back.timeout_deadline is not None
        else:
            assert read_back.freshness_tier is None
            assert read_back.timeout_deadline is None

        # Cleanup
        await session.delete(read_back)
        # Also delete the job record
        job_stmt = select(JobRecord).where(JobRecord.id == created_record.job_id)
        job_result = await session.execute(job_stmt)
        job_record = job_result.scalars().first()
        if job_record:
            await session.delete(job_record)
        await session.commit()


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_json_fields_roundtrip_correctly(
    tier: str,
    form_state: dict,
    draft_answers: list[dict],
    async_engine,
    notification_settings: NotificationSettings,
) -> None:
    """
    For any valid form_state_snapshot dict and draft_answers list, after
    creating an escalation record and reading it back, the JSON fields
    should deserialize to exactly the same Python objects — no data dropped
    or altered during JSON serialization/deserialization.

    **Validates: Requirements 7.1**

    Feature: human-in-the-loop-escalation, Property 7: Escalation Record Persistence Round-Trip
    """
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-json-{hash((tier, str(form_state)))!s}",
            job_title="JSON Engineer",
            company="Roundtrip Inc",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/json-rt",
            apply_type="external_apply",
            status="applying",
            fit_score=88,
            discovered_at=discovered.isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        answers = draft_answers if tier == "human_review" else None

        created_record = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        await session.commit()

    # Read back in a fresh session
    async with async_session_factory() as session:
        stmt = select(EscalationRecord).where(
            EscalationRecord.id == created_record.id
        )
        result = await session.execute(stmt)
        read_back = result.scalars().first()

        assert read_back is not None, "Escalation record not found after creation"

        # Deserialize form_state_snapshot and compare
        stored_form_state = json.loads(read_back.form_state_snapshot)
        assert stored_form_state == form_state, (
            f"form_state_snapshot mismatch.\n"
            f"Original: {form_state}\n"
            f"Stored:   {stored_form_state}"
        )

        # Deserialize draft_answers and compare
        if tier == "human_review":
            assert read_back.draft_answers is not None
            stored_answers = json.loads(read_back.draft_answers)
            assert stored_answers == draft_answers, (
                f"draft_answers mismatch.\n"
                f"Original: {draft_answers}\n"
                f"Stored:   {stored_answers}"
            )
        else:
            # CAPTCHA tier: draft_answers should be NULL
            assert read_back.draft_answers is None

        # Cleanup
        await session.delete(read_back)
        job_stmt = select(JobRecord).where(JobRecord.id == created_record.job_id)
        job_result = await session.execute(job_stmt)
        job_record = job_result.scalars().first()
        if job_record:
            await session.delete(job_record)
        await session.commit()


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answer_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_no_data_dropped_or_altered(
    tier: str,
    form_state: dict,
    draft_answers: list[dict],
    async_engine,
    notification_settings: NotificationSettings,
) -> None:
    """
    For any valid escalation input, after create + read-back, no data should
    be dropped or altered. This test verifies that every non-null field on the
    created record matches the read-back record exactly, including the
    timeout_deadline and freshness_tier for human_review tier.

    **Validates: Requirements 7.1**

    Feature: human-in-the-loop-escalation, Property 7: Escalation Record Persistence Round-Trip
    """
    now = datetime.now(tz=UTC)
    discovered = now - timedelta(hours=2)

    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-nodrop-{hash((tier, str(form_state)))!s}",
            job_title="No Drop Engineer",
            company="Complete Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/nodrop",
            apply_type="external_apply",
            status="applying",
            fit_score=95,
            discovered_at=discovered.isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        answers = draft_answers if tier == "human_review" else None

        created_record = await create_escalation(
            session=session,
            job_record=job,
            tier=tier,
            form_state_snapshot=form_state,
            draft_answers=answers,
            page=None,
            notification_settings=notification_settings,
        )

        # Capture all field values from the created record
        expected_id = created_record.id
        expected_job_id = created_record.job_id
        expected_tier = created_record.tier
        expected_form_state = created_record.form_state_snapshot
        expected_draft_answers = created_record.draft_answers
        expected_timeout_deadline = created_record.timeout_deadline
        expected_freshness_tier = created_record.freshness_tier
        expected_status = created_record.status
        expected_created_at = created_record.created_at
        expected_resolved_at = created_record.resolved_at

        await session.commit()

    # Read back in a fresh session
    async with async_session_factory() as session:
        stmt = select(EscalationRecord).where(EscalationRecord.id == expected_id)
        result = await session.execute(stmt)
        read_back = result.scalars().first()

        assert read_back is not None, "Escalation record not found after creation"

        # Verify every field matches exactly
        assert read_back.id == expected_id
        assert read_back.job_id == expected_job_id
        assert read_back.tier == expected_tier
        assert read_back.form_state_snapshot == expected_form_state
        assert read_back.draft_answers == expected_draft_answers
        assert read_back.timeout_deadline == expected_timeout_deadline
        assert read_back.freshness_tier == expected_freshness_tier
        assert read_back.status == expected_status
        assert read_back.created_at == expected_created_at
        assert read_back.resolved_at == expected_resolved_at

        # Cleanup
        await session.delete(read_back)
        job_stmt = select(JobRecord).where(JobRecord.id == expected_job_id)
        job_result = await session.execute(job_stmt)
        job_record = job_result.scalars().first()
        if job_record:
            await session.delete(job_record)
        await session.commit()
