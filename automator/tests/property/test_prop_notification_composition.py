"""
Property-based tests for Notification Composition Completeness.

Uses Hypothesis to verify that compose_escalation_notification() produces
correct ntfy payloads for both CAPTCHA and human_review tiers, including
correct priority levels, action buttons, and required content fields.

Properties tested:
- Property 6: Notification Composition Completeness

Feature: human-in-the-loop-escalation, Property 6: Notification Composition Completeness
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.db.models import JobRecord
from src.pipeline.escalation_engine import FreshnessTier
from src.pipeline.notification_composer import compose_escalation_notification


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Job titles: non-empty printable strings
job_title_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Company names: non-empty printable strings
company_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=80,
).filter(lambda s: s.strip())

# Fit scores: 0-100 integer range
fit_score_strategy = st.integers(min_value=0, max_value=100)

# Freshness tiers for human_review
freshness_strategy = st.sampled_from(list(FreshnessTier))

# Timeout deadlines: future datetimes (1 min to 24 hours from now)
timeout_deadline_strategy = st.floats(
    min_value=60.0,
    max_value=24 * 3600.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda secs: datetime.now(tz=UTC) + timedelta(seconds=secs))

# Open-ended question counts
open_ended_count_strategy = st.integers(min_value=1, max_value=20)

# ATS domains for external URLs
ats_domain_strategy = st.from_regex(
    r"[a-z]+\.(greenhouse|lever|workday|icims|smartrecruiters)\.(io|com)",
    fullmatch=True,
)

# Review URLs containing an escalation ID
escalation_id_strategy = st.uuids().map(str)

review_url_strategy = escalation_id_strategy.map(
    lambda eid: f"http://localhost:3000/escalations/{eid}"
)


def _make_job_record(
    job_title: str,
    company: str,
    fit_score: int | None,
    external_url: str | None,
) -> JobRecord:
    """Create a minimal JobRecord for testing notification composition."""
    now = datetime.now(tz=UTC).isoformat()
    return JobRecord(
        id="job-notif-test",
        job_title=job_title,
        company=company,
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/test-123",
        external_url=external_url,
        apply_type="external_apply",
        status="applying",
        fit_score=fit_score,
        discovered_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Property 6: Notification Composition Completeness — CAPTCHA tier
# ---------------------------------------------------------------------------


@given(
    job_title=job_title_strategy,
    company=company_strategy,
    ats_domain=ats_domain_strategy,
    review_url=review_url_strategy,
)
@settings(max_examples=150)
def test_captcha_notification_priority_and_action_button(
    job_title: str,
    company: str,
    ats_domain: str,
    review_url: str,
) -> None:
    """
    For any CAPTCHA escalation, the notification should use priority 4 and
    include an action button labeled "Review" with a URL containing the
    escalation ID.

    **Validates: Requirements 1.2, 5.1, 5.3**

    Feature: human-in-the-loop-escalation, Property 6: Notification Composition Completeness
    """
    external_url = f"https://{ats_domain}/jobs/12345"
    job = _make_job_record(
        job_title=job_title,
        company=company,
        fit_score=None,
        external_url=external_url,
    )

    payload = compose_escalation_notification(
        job_record=job,
        tier="captcha",
        freshness=None,
        timeout_deadline=None,
        open_ended_count=0,
        review_url=review_url,
    )

    # (a) Priority must be 4 for CAPTCHA tier
    assert payload.priority == 4, (
        f"CAPTCHA notification should have priority 4, got {payload.priority}"
    )

    # (b) Must include a "Review" action button with the review URL
    assert payload.actions is not None, "CAPTCHA notification must have actions"
    review_actions = [a for a in payload.actions if a.label == "Review"]
    assert len(review_actions) == 1, (
        f"Expected exactly 1 'Review' action, got {len(review_actions)}"
    )
    assert review_actions[0].url == review_url, (
        f"Review action URL should be {review_url!r}, got {review_actions[0].url!r}"
    )


@given(
    job_title=job_title_strategy,
    company=company_strategy,
    ats_domain=ats_domain_strategy,
    review_url=review_url_strategy,
)
@settings(max_examples=150)
def test_captcha_notification_body_content(
    job_title: str,
    company: str,
    ats_domain: str,
    review_url: str,
) -> None:
    """
    For any CAPTCHA escalation, the notification body should include the
    job_title, company, ATS domain, and the instruction "Solve CAPTCHA in
    Chrome to continue".

    **Validates: Requirements 1.2, 5.3**

    Feature: human-in-the-loop-escalation, Property 6: Notification Composition Completeness
    """
    external_url = f"https://{ats_domain}/jobs/12345"
    job = _make_job_record(
        job_title=job_title,
        company=company,
        fit_score=None,
        external_url=external_url,
    )

    payload = compose_escalation_notification(
        job_record=job,
        tier="captcha",
        freshness=None,
        timeout_deadline=None,
        open_ended_count=0,
        review_url=review_url,
    )

    # (c) CAPTCHA notification must include job_title, company, ATS domain,
    # and "Solve CAPTCHA in Chrome to continue"
    full_text = f"{payload.title}\n{payload.message}"

    assert job_title in full_text, (
        f"CAPTCHA notification should contain job_title {job_title!r}, "
        f"got title={payload.title!r}, message={payload.message!r}"
    )
    assert company in full_text, (
        f"CAPTCHA notification should contain company {company!r}, "
        f"got title={payload.title!r}, message={payload.message!r}"
    )
    assert ats_domain in payload.message, (
        f"CAPTCHA notification should contain ATS domain {ats_domain!r}, "
        f"got message={payload.message!r}"
    )
    assert "Solve CAPTCHA in Chrome to continue" in payload.message, (
        f"CAPTCHA notification should contain 'Solve CAPTCHA in Chrome to continue', "
        f"got message={payload.message!r}"
    )


# ---------------------------------------------------------------------------
# Property 6: Notification Composition Completeness — human_review tier
# ---------------------------------------------------------------------------


@given(
    job_title=job_title_strategy,
    company=company_strategy,
    fit_score=fit_score_strategy,
    review_url=review_url_strategy,
    freshness=freshness_strategy,
    timeout_deadline=timeout_deadline_strategy,
    open_ended_count=open_ended_count_strategy,
)
@settings(max_examples=150)
def test_human_review_notification_priority_and_action_button(
    job_title: str,
    company: str,
    fit_score: int,
    review_url: str,
    freshness: FreshnessTier,
    timeout_deadline: datetime,
    open_ended_count: int,
) -> None:
    """
    For any human_review escalation, the notification should use priority 3
    and include an action button labeled "Review" with a URL containing the
    escalation ID.

    **Validates: Requirements 2.4, 5.1, 5.4**

    Feature: human-in-the-loop-escalation, Property 6: Notification Composition Completeness
    """
    job = _make_job_record(
        job_title=job_title,
        company=company,
        fit_score=fit_score,
        external_url="https://boards.greenhouse.io/acme/jobs/999",
    )

    payload = compose_escalation_notification(
        job_record=job,
        tier="human_review",
        freshness=freshness,
        timeout_deadline=timeout_deadline,
        open_ended_count=open_ended_count,
        review_url=review_url,
    )

    # (a) Priority must be 3 for human_review tier
    assert payload.priority == 3, (
        f"human_review notification should have priority 3, got {payload.priority}"
    )

    # (b) Must include a "Review" action button with the review URL
    assert payload.actions is not None, "human_review notification must have actions"
    review_actions = [a for a in payload.actions if a.label == "Review"]
    assert len(review_actions) == 1, (
        f"Expected exactly 1 'Review' action, got {len(review_actions)}"
    )
    assert review_actions[0].url == review_url, (
        f"Review action URL should be {review_url!r}, got {review_actions[0].url!r}"
    )


@given(
    job_title=job_title_strategy,
    company=company_strategy,
    fit_score=fit_score_strategy,
    freshness=freshness_strategy,
    timeout_deadline=timeout_deadline_strategy,
    open_ended_count=open_ended_count_strategy,
    review_url=review_url_strategy,
)
@settings(max_examples=150)
def test_human_review_notification_body_content(
    job_title: str,
    company: str,
    fit_score: int,
    freshness: FreshnessTier,
    timeout_deadline: datetime,
    open_ended_count: int,
    review_url: str,
) -> None:
    """
    For any human_review escalation, the notification body should include the
    job_title, company, fit_score, open-ended question count, freshness tier
    label, and relative timeout deadline.

    **Validates: Requirements 2.4, 5.2, 5.4**

    Feature: human-in-the-loop-escalation, Property 6: Notification Composition Completeness
    """
    job = _make_job_record(
        job_title=job_title,
        company=company,
        fit_score=fit_score,
        external_url="https://boards.greenhouse.io/acme/jobs/999",
    )

    payload = compose_escalation_notification(
        job_record=job,
        tier="human_review",
        freshness=freshness,
        timeout_deadline=timeout_deadline,
        open_ended_count=open_ended_count,
        review_url=review_url,
    )

    # (c) human_review notification must include job_title, company, fit_score,
    # open-ended question count, freshness tier label, and relative timeout deadline
    full_text = f"{payload.title}\n{payload.message}"

    assert job_title in full_text, (
        f"human_review notification should contain job_title {job_title!r}, "
        f"got title={payload.title!r}, message={payload.message!r}"
    )
    assert company in full_text, (
        f"human_review notification should contain company {company!r}, "
        f"got title={payload.title!r}, message={payload.message!r}"
    )
    assert str(fit_score) in payload.message, (
        f"human_review notification should contain fit_score {fit_score}, "
        f"got message={payload.message!r}"
    )
    assert str(open_ended_count) in payload.message, (
        f"human_review notification should contain open_ended_count {open_ended_count}, "
        f"got message={payload.message!r}"
    )
    assert freshness.value in payload.message, (
        f"human_review notification should contain freshness tier label "
        f"{freshness.value!r}, got message={payload.message!r}"
    )
    # The relative deadline should appear as some time string (e.g. "45 min", "6 hrs")
    assert "auto-submits in" in payload.message, (
        f"human_review notification should contain 'auto-submits in' with relative "
        f"deadline, got message={payload.message!r}"
    )
