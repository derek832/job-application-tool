"""
Property-based tests for CAPTCHA Escalations Have No Timeout.

Uses Hypothesis to verify that create_escalation() with tier="captcha" always
produces an escalation record with timeout_deadline=None and freshness_tier=None,
regardless of the job's discovered_at timestamp or any other input.

Properties tested:
- Property 5: CAPTCHA Escalations Have No Timeout

Feature: human-in-the-loop-escalation, Property 5: CAPTCHA Escalations Have No Timeout
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, JobRecord
from src.pipeline.escalation_engine import create_escalation
from src.pipeline.notification_service import NotificationSettings


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate discovered_at timestamps across a wide range of ages:
# from 0 seconds ago (very fresh) to 365 days ago (very stale)
discovered_age_seconds_strategy = st.floats(
    min_value=0.0,
    max_value=365 * 24 * 3600,
    allow_nan=False,
    allow_infinity=False,
)

# Generate form state snapshots with varying content
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
                    "label": st.text(min_size=1, max_size=100),
                    "value": st.text(max_size=200),
                    "type": st.sampled_from(["text", "textarea", "select", "checkbox"]),
                }
            ),
            min_size=0,
            max_size=5,
        ),
        "page_title": st.text(min_size=1, max_size=100),
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_notification_settings = NotificationSettings(
    ntfy_enabled=False,
    ntfy=None,
    sms_enabled=False,
    sms=None,
)


async def _run_captcha_escalation_test(
    age_seconds: float,
    form_state: dict,
    fit_score: int,
    job_id_suffix: str,
) -> tuple[str | None, str | None]:
    """Create an in-memory DB, insert a job, create a CAPTCHA escalation, return results.

    Returns:
        Tuple of (timeout_deadline, freshness_tier) from the created record.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    now = datetime.now(tz=UTC)
    discovered_at = (now - timedelta(seconds=age_seconds)).isoformat()

    async with async_session_factory() as session:
        job = JobRecord(
            id=f"job-captcha-{job_id_suffix}",
            job_title="Test Engineer",
            company="Test Corp",
            location="Remote",
            linkedin_url="https://www.linkedin.com/jobs/view/test-123",
            apply_type="external_apply",
            status="applying",
            fit_score=fit_score,
            discovered_at=discovered_at,
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        record = await create_escalation(
            session=session,
            job_record=job,
            tier="captcha",
            form_state_snapshot=form_state,
            draft_answers=None,
            page=None,
            notification_settings=_notification_settings,
        )

        result = (record.timeout_deadline, record.freshness_tier)

    await engine.dispose()
    return result


# ---------------------------------------------------------------------------
# Property 5: CAPTCHA Escalations Have No Timeout
# ---------------------------------------------------------------------------


@given(
    age_seconds=discovered_age_seconds_strategy,
    form_state=form_state_strategy,
)
@settings(max_examples=150)
def test_captcha_escalation_always_has_no_timeout(
    age_seconds: float,
    form_state: dict,
) -> None:
    """
    For any escalation record created with tier="captcha", the timeout_deadline
    field should always be NULL regardless of the job's freshness tier or any
    other input.

    **Validates: Requirements 1.3**

    Feature: human-in-the-loop-escalation, Property 5: CAPTCHA Escalations Have No Timeout
    """
    job_id_suffix = f"{hash((age_seconds, str(form_state))) & 0xFFFFFFFF:08x}"

    timeout_deadline, freshness_tier = asyncio.run(
        _run_captcha_escalation_test(
            age_seconds=age_seconds,
            form_state=form_state,
            fit_score=90,
            job_id_suffix=job_id_suffix,
        )
    )

    assert timeout_deadline is None, (
        f"CAPTCHA escalation should have timeout_deadline=None, "
        f"got {timeout_deadline!r} "
        f"(job discovered_at age: {age_seconds/3600:.1f}h)"
    )
    assert freshness_tier is None, (
        f"CAPTCHA escalation should have freshness_tier=None, "
        f"got {freshness_tier!r} "
        f"(job discovered_at age: {age_seconds/3600:.1f}h)"
    )


@given(
    age_seconds=discovered_age_seconds_strategy,
    fit_score=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=150)
def test_captcha_no_timeout_regardless_of_fit_score(
    age_seconds: float,
    fit_score: int,
) -> None:
    """
    For any job with any fit_score and any discovered_at timestamp, creating
    a CAPTCHA escalation should always result in timeout_deadline=None and
    freshness_tier=None. The fit_score should have no influence on CAPTCHA
    timeout behavior.

    **Validates: Requirements 1.3**

    Feature: human-in-the-loop-escalation, Property 5: CAPTCHA Escalations Have No Timeout
    """
    form_state = {
        "external_url": "https://boards.greenhouse.io/acme/jobs/999",
        "fields": [],
        "page_title": "Apply - Test Role",
    }
    job_id_suffix = f"{hash((age_seconds, fit_score)) & 0xFFFFFFFF:08x}"

    timeout_deadline, freshness_tier = asyncio.run(
        _run_captcha_escalation_test(
            age_seconds=age_seconds,
            form_state=form_state,
            fit_score=fit_score,
            job_id_suffix=job_id_suffix,
        )
    )

    assert timeout_deadline is None, (
        f"CAPTCHA escalation should have timeout_deadline=None regardless of "
        f"fit_score={fit_score}, got {timeout_deadline!r}"
    )
    assert freshness_tier is None, (
        f"CAPTCHA escalation should have freshness_tier=None regardless of "
        f"fit_score={fit_score}, got {freshness_tier!r}"
    )
