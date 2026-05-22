"""
Property-based tests for Skip Resolution Transitions Correctly.

Uses Hypothesis to verify that resolve_escalation(session, escalation_id, "skipped")
correctly transitions the escalation to status="skipped" with resolution_method="user_skip",
sets resolved_at to a non-null value, and transitions the associated job record to
status="skipped" with queue_reason="user_skipped_escalation".

Properties tested:
- Property 12: Skip Resolution Transitions Correctly

Feature: human-in-the-loop-escalation, Property 12: Skip Resolution Transitions Correctly
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord, StatusTransition
from src.pipeline.escalation_engine import resolve_escalation


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

tier_strategy = st.sampled_from(["captcha", "human_review"])

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
                    "label": st.text(min_size=1, max_size=50),
                    "value": st.text(max_size=100),
                    "type": st.sampled_from(["text", "textarea", "select"]),
                }
            ),
            min_size=0,
            max_size=5,
        ),
        "page_title": st.text(min_size=1, max_size=100),
    }
)

freshness_tier_strategy = st.sampled_from(["fresh", "recent", "stale"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_skip_resolution_test(
    tier: str,
    form_state: dict,
    freshness_tier: str,
    job_id_suffix: str,
) -> tuple[str, str | None, str | None, str, str | None]:
    """Create an in-memory DB, insert a job + pending escalation, resolve via skip.

    Returns:
        Tuple of (escalation_status, resolution_method, resolved_at,
                  job_status, transition_reason)
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    now = datetime.now(tz=UTC)
    discovered_at = (now - timedelta(hours=2)).isoformat()

    async with async_session_factory() as session:
        # Create a job record in "applying" status
        job = JobRecord(
            id=f"job-skip-{job_id_suffix}",
            job_title="Test Engineer",
            company="PropTest Corp",
            location="Remote",
            linkedin_url=f"https://www.linkedin.com/jobs/view/job-skip-{job_id_suffix}",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=discovered_at,
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create a pending escalation record
        escalation_id = str(uuid.uuid4())
        timeout_deadline = (
            (now + timedelta(minutes=45)).isoformat()
            if tier == "human_review"
            else None
        )
        draft_answers = (
            json.dumps([{"field_id": "f1", "question_text": "Q?", "draft_answer": "A"}])
            if tier == "human_review"
            else None
        )

        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job.id,
            tier=tier,
            form_state_snapshot=json.dumps(form_state),
            draft_answers=draft_answers,
            timeout_deadline=timeout_deadline,
            freshness_tier=freshness_tier if tier == "human_review" else None,
            status="pending",
            resolution_method=None,
            created_at=now.isoformat(),
            resolved_at=None,
        )
        session.add(escalation)
        await session.flush()

        # Resolve via skip
        result = await resolve_escalation(
            session=session,
            escalation_id=escalation_id,
            resolution="skipped",
        )

        # Refresh job to get updated status
        await session.refresh(job)

        # Query the status transition to check queue_reason
        stmt = select(StatusTransition).where(
            StatusTransition.job_id == job.id,
            StatusTransition.to_status == "skipped",
        )
        transition_result = await session.execute(stmt)
        transition = transition_result.scalars().first()
        transition_reason = transition.reason if transition else None

        output = (
            result.status,
            result.resolution_method,
            result.resolved_at,
            job.status,
            transition_reason,
        )

    await engine.dispose()
    return output


# ---------------------------------------------------------------------------
# Property 12: Skip Resolution Transitions Correctly
# ---------------------------------------------------------------------------


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    freshness_tier=freshness_tier_strategy,
)
@settings(max_examples=100)
def test_skip_resolution_sets_escalation_status_skipped(
    tier: str,
    form_state: dict,
    freshness_tier: str,
) -> None:
    """
    For any pending escalation (of either tier), resolving via skip should
    set escalation status="skipped".

    **Validates: Requirements 6.4**

    Feature: human-in-the-loop-escalation, Property 12: Skip Resolution Transitions Correctly
    """
    job_id_suffix = f"{hash((tier, str(form_state), freshness_tier)) & 0xFFFFFFFF:08x}"

    (
        escalation_status,
        resolution_method,
        resolved_at,
        job_status,
        transition_reason,
    ) = asyncio.run(
        _run_skip_resolution_test(
            tier=tier,
            form_state=form_state,
            freshness_tier=freshness_tier,
            job_id_suffix=job_id_suffix,
        )
    )

    assert escalation_status == "skipped", (
        f"Expected escalation status='skipped', got {escalation_status!r} "
        f"(tier={tier!r})"
    )


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    freshness_tier=freshness_tier_strategy,
)
@settings(max_examples=100)
def test_skip_resolution_sets_resolution_method_user_skip(
    tier: str,
    form_state: dict,
    freshness_tier: str,
) -> None:
    """
    For any pending escalation (of either tier), resolving via skip should
    set resolution_method="user_skip".

    **Validates: Requirements 6.4**

    Feature: human-in-the-loop-escalation, Property 12: Skip Resolution Transitions Correctly
    """
    job_id_suffix = f"{hash((tier, str(form_state), freshness_tier)) & 0xFFFFFFFF:08x}"

    (
        escalation_status,
        resolution_method,
        resolved_at,
        job_status,
        transition_reason,
    ) = asyncio.run(
        _run_skip_resolution_test(
            tier=tier,
            form_state=form_state,
            freshness_tier=freshness_tier,
            job_id_suffix=job_id_suffix,
        )
    )

    assert resolution_method == "user_skip", (
        f"Expected resolution_method='user_skip', got {resolution_method!r} "
        f"(tier={tier!r})"
    )


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    freshness_tier=freshness_tier_strategy,
)
@settings(max_examples=100)
def test_skip_resolution_sets_resolved_at_non_null(
    tier: str,
    form_state: dict,
    freshness_tier: str,
) -> None:
    """
    For any pending escalation (of either tier), resolving via skip should
    set resolved_at to a non-null ISO 8601 timestamp.

    **Validates: Requirements 6.4**

    Feature: human-in-the-loop-escalation, Property 12: Skip Resolution Transitions Correctly
    """
    job_id_suffix = f"{hash((tier, str(form_state), freshness_tier)) & 0xFFFFFFFF:08x}"

    (
        escalation_status,
        resolution_method,
        resolved_at,
        job_status,
        transition_reason,
    ) = asyncio.run(
        _run_skip_resolution_test(
            tier=tier,
            form_state=form_state,
            freshness_tier=freshness_tier,
            job_id_suffix=job_id_suffix,
        )
    )

    assert resolved_at is not None, (
        f"Expected resolved_at to be non-null after skip resolution "
        f"(tier={tier!r})"
    )
    # Verify it's a valid ISO 8601 timestamp
    parsed = datetime.fromisoformat(resolved_at)
    assert parsed.tzinfo is not None or "+" in resolved_at or "Z" in resolved_at, (
        f"Expected resolved_at to be a timezone-aware ISO 8601 timestamp, "
        f"got {resolved_at!r}"
    )


@given(
    tier=tier_strategy,
    form_state=form_state_strategy,
    freshness_tier=freshness_tier_strategy,
)
@settings(max_examples=100)
def test_skip_resolution_transitions_job_to_skipped(
    tier: str,
    form_state: dict,
    freshness_tier: str,
) -> None:
    """
    For any pending escalation (of either tier), resolving via skip should
    transition the associated job record to status="skipped" with
    queue_reason="user_skipped_escalation" recorded in the status transition.

    **Validates: Requirements 6.4**

    Feature: human-in-the-loop-escalation, Property 12: Skip Resolution Transitions Correctly
    """
    job_id_suffix = f"{hash((tier, str(form_state), freshness_tier)) & 0xFFFFFFFF:08x}"

    (
        escalation_status,
        resolution_method,
        resolved_at,
        job_status,
        transition_reason,
    ) = asyncio.run(
        _run_skip_resolution_test(
            tier=tier,
            form_state=form_state,
            freshness_tier=freshness_tier,
            job_id_suffix=job_id_suffix,
        )
    )

    assert job_status == "skipped", (
        f"Expected job status='skipped' after skip resolution, "
        f"got {job_status!r} (tier={tier!r})"
    )
    assert transition_reason == "user_skipped_escalation", (
        f"Expected transition reason='user_skipped_escalation', "
        f"got {transition_reason!r} (tier={tier!r})"
    )
