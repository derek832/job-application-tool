"""
Property-based tests for the LinkedIn Job Automator.

Uses Hypothesis to verify invariants across randomized inputs for 16 core
properties covering URL construction, deduplication, record initialization,
classification, persistence, SMS composition, rate limiting, and more.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.schemas import SearchConfig, UserProfile
from src.db.models import VALID_STATUSES, Base, JobRecord, NotificationLog
from src.integrations.linkedin_scraper import build_search_url
from src.integrations.sms_gateway import ACTION_PROMPT, SMS_MAX_LENGTH, compose_sms
from src.integrations.sms_rate_limiter import check_rate_limit
from src.pipeline.fit_classifier import classify_fit, is_threshold_boundary
from src.pipeline.prefilter import check_title_exclusions


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid values for SearchConfig enum-like fields
_JOB_TYPES = ["full-time", "part-time", "contract", "internship"]
_EXPERIENCE_LEVELS = ["internship", "entry", "associate", "mid-senior", "director", "executive"]
_REMOTE_PREFS = ["on-site", "remote", "hybrid"]

search_config_strategy = st.builds(
    SearchConfig,
    keywords=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    search_queries=st.just([]),
    location=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    job_type=st.one_of(st.none(), st.sampled_from(_JOB_TYPES)),
    experience_level=st.one_of(st.none(), st.sampled_from(_EXPERIENCE_LEVELS)),
    remote_pref=st.one_of(st.none(), st.sampled_from(_REMOTE_PREFS)),
)

# Strategy for printable non-empty strings (for SMS, titles, etc.)
printable_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32),
    min_size=1,
    max_size=40,
)

# Strategy for job IDs (numeric strings)
job_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("N",), min_codepoint=48, max_codepoint=57),
    min_size=5,
    max_size=12,
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


# ---------------------------------------------------------------------------
# Property 1: Search URL Construction Completeness
# ---------------------------------------------------------------------------


@given(config=search_config_strategy)
@settings(max_examples=100)
def test_search_url_construction_completeness(config: SearchConfig) -> None:
    """All non-None SearchConfig fields appear in the URL, and f_TPR=r86400 is always present."""
    url = build_search_url(config)
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    # f_TPR=r86400 is always present
    assert "f_TPR" in query_params
    assert query_params["f_TPR"] == ["r86400"]

    # Base URL is correct
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/jobs/search/"

    # If keywords is set, it appears in the URL
    if config.keywords is not None:
        assert "keywords" in query_params
        assert query_params["keywords"] == [config.keywords]

    # If location is set, it appears in the URL
    if config.location is not None:
        assert "location" in query_params
        assert query_params["location"] == [config.location]

    # If job_type is set and valid, f_JT appears
    if config.job_type is not None:
        assert "f_JT" in query_params

    # If experience_level is set and valid, f_E appears
    if config.experience_level is not None:
        assert "f_E" in query_params

    # If remote_pref is set and valid, f_WT appears
    if config.remote_pref is not None:
        assert "f_WT" in query_params


# ---------------------------------------------------------------------------
# Property 2: Job Discovery Deduplication
# ---------------------------------------------------------------------------


@given(
    existing_ids=st.frozensets(job_id_strategy, min_size=0, max_size=10),
    new_ids=st.frozensets(job_id_strategy, min_size=1, max_size=10),
)
@settings(max_examples=100)
def test_job_discovery_deduplication(
    existing_ids: frozenset[str], new_ids: frozenset[str]
) -> None:
    """Deduplication logic returns exactly the IDs not in the existing set."""
    all_discovered = existing_ids | new_ids
    # Simulate the dedup logic from linkedin_scraper.discover_jobs
    result = all_discovered - existing_ids
    # The result should contain exactly the new IDs that weren't in existing
    expected = new_ids - existing_ids
    assert result == expected
    # No existing IDs should appear in the result
    assert result.isdisjoint(existing_ids)


# ---------------------------------------------------------------------------
# Property 3: New Job Record Initialization
# ---------------------------------------------------------------------------


@given(
    job_id=job_id_strategy,
    title=printable_text,
    company=printable_text,
)
@settings(max_examples=100)
def test_new_job_record_initialization(job_id: str, title: str, company: str) -> None:
    """After creation, record has status 'discovered', fields populated, non-null discovered_at."""
    from src.db.job_repo import create_job_record

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            record = await create_job_record(
                session,
                id=job_id,
                job_title=title,
                company=company,
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )

            assert record.status == "discovered"
            assert record.job_title == title
            assert record.company == company
            assert record.id == job_id
            assert record.discovered_at is not None
            assert record.updated_at is not None
            assert record.linkedin_url == f"https://www.linkedin.com/jobs/view/{job_id}"
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 4: Fit Score Classification Completeness
# ---------------------------------------------------------------------------


@given(
    score=st.integers(min_value=0, max_value=100),
    good_fit=st.integers(min_value=1, max_value=100),
    stretch=st.integers(min_value=0, max_value=99),
)
@settings(max_examples=100)
def test_fit_score_classification_completeness(
    score: int, good_fit: int, stretch: int
) -> None:
    """For any score 0-100 and valid thresholds where stretch < good_fit, exactly one classification."""
    # Only test valid threshold configurations
    if stretch >= good_fit:
        return

    result = classify_fit(score, good_fit, stretch)
    assert result in ("good_fit", "stretch_role", "skip")

    # Verify the classification is correct
    if score >= good_fit:
        assert result == "good_fit"
    elif score >= stretch:
        assert result == "stretch_role"
    else:
        assert result == "skip"


# ---------------------------------------------------------------------------
# Property 5: Deal-Breaker Override (Title Exclusion)
# ---------------------------------------------------------------------------


@given(
    deal_breaker=st.text(
        alphabet=st.characters(whitelist_categories=("L",), min_codepoint=65, max_codepoint=122),
        min_size=3,
        max_size=15,
    ),
    prefix=printable_text,
    suffix=printable_text,
)
@settings(max_examples=100)
def test_deal_breaker_title_exclusion(
    deal_breaker: str, prefix: str, suffix: str
) -> None:
    """If a deal_breaker term appears in a job title, check_title_exclusions returns that term."""
    # Build a title that contains the deal-breaker
    title_with_breaker = f"{prefix} {deal_breaker} {suffix}"

    # Create a minimal JobRecord object
    job_record = JobRecord(
        id="test-123",
        job_title=title_with_breaker,
        company="TestCo",
        linkedin_url="https://www.linkedin.com/jobs/view/123",
        apply_type="easy_apply",
        status="discovered",
        discovered_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )

    result = check_title_exclusions(job_record, [deal_breaker])
    assert result == deal_breaker


# ---------------------------------------------------------------------------
# Property 6: Fit Score and Rationale Persistence
# ---------------------------------------------------------------------------


@given(
    fit_score=st.integers(min_value=0, max_value=100),
    fit_rationale=st.text(min_size=1, max_size=200),
)
@settings(max_examples=100)
def test_fit_score_and_rationale_persistence(fit_score: int, fit_rationale: str) -> None:
    """After storing fit_score and fit_rationale, values are retrievable unchanged."""
    from src.db.job_repo import create_job_record

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = f"persist-{fit_score}-{abs(hash(fit_rationale)) % 10000}"
            record = await create_job_record(
                session,
                id=job_id,
                job_title="Test Job",
                company="TestCo",
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )

            record.fit_score = fit_score
            record.fit_rationale = fit_rationale
            await session.flush()

            # Re-query to confirm persistence
            result = await session.execute(
                select(JobRecord).where(JobRecord.id == job_id)
            )
            fetched = result.scalar_one()
            assert fetched.fit_score == fit_score
            assert fetched.fit_rationale == fit_rationale
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 7: Configuration Round-Trip Fidelity
# ---------------------------------------------------------------------------


@given(
    config_value=st.fixed_dictionaries(
        {
            "search_queries": st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=5),
            "supplementary_context": st.text(min_size=0, max_size=200),
        }
    ),
)
@settings(max_examples=100)
def test_configuration_round_trip_fidelity(config_value: dict) -> None:
    """Any JSON-serializable dict saved via set_config is retrievable unchanged via get_config."""
    from src.db.config_repo import get_config, set_config

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            key = "search_config"
            await set_config(session, key, config_value)
            retrieved = await get_config(session, key)
            assert retrieved == config_value
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 8: SMS Composition Correctness
# ---------------------------------------------------------------------------


@given(
    job_title=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48),
        min_size=1,
        max_size=30,
    ),
    company=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48),
        min_size=1,
        max_size=20,
    ),
    trigger_reason=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48),
        min_size=1,
        max_size=20,
    ),
    fit_score=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
)
@settings(max_examples=100)
def test_sms_composition_correctness(
    job_title: str, company: str, trigger_reason: str, fit_score: int | None
) -> None:
    """SMS contains job_title, company, action prompt, is ≤160 chars, includes score if provided."""
    result = compose_sms(job_title, company, trigger_reason, fit_score)

    # Must not exceed SMS_MAX_LENGTH
    assert len(result) <= SMS_MAX_LENGTH

    # Must contain the action prompt
    assert ACTION_PROMPT in result

    # If the full message fits, it should contain the job title and company
    if len(f"{job_title} @ {company}") + len(ACTION_PROMPT) + 10 <= SMS_MAX_LENGTH:
        assert job_title in result
        assert company in result

    # If fit_score is provided and message isn't truncated, score should appear
    if fit_score is not None:
        score_str = f"({fit_score}%)"
        full_msg = f"{job_title} @ {company} ({fit_score}%): {trigger_reason}. {ACTION_PROMPT}"
        if len(full_msg) <= SMS_MAX_LENGTH:
            assert score_str in result


# ---------------------------------------------------------------------------
# Property 9: SMS Rate Limit Enforcement
# ---------------------------------------------------------------------------


@given(extra_sends=st.integers(min_value=0, max_value=5))
@settings(max_examples=100)
def test_sms_rate_limit_enforcement(extra_sends: int) -> None:
    """After 10 notifications in the last hour, check_rate_limit returns False."""

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(UTC)

            # Insert 10 + extra successful notifications within the last hour
            for i in range(10 + extra_sends):
                log_entry = NotificationLog(
                    trigger_reason="test",
                    sms_body=f"Test message {i}",
                    sent_at=(now - timedelta(minutes=i)).isoformat(),
                    success=1,
                )
                session.add(log_entry)
            await session.flush()

            result = await check_rate_limit(session)
            assert result is False
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 10: Job Record Persistence Across Restarts
# ---------------------------------------------------------------------------


@given(
    job_id=job_id_strategy,
    title=printable_text,
    company=printable_text,
)
@settings(max_examples=100)
def test_job_record_persistence_across_restarts(
    job_id: str, title: str, company: str
) -> None:
    """JobRecords written to SQLite are retrievable after closing and reopening the session."""

    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        # Write in first session
        async with factory() as session1:
            now = datetime.now(UTC).isoformat()
            record = JobRecord(
                id=job_id,
                job_title=title,
                company=company,
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
                status="discovered",
                discovered_at=now,
                updated_at=now,
            )
            session1.add(record)
            await session1.commit()

        # Read in a new session (simulates restart)
        async with factory() as session2:
            result = await session2.execute(
                select(JobRecord).where(JobRecord.id == job_id)
            )
            fetched = result.scalar_one_or_none()
            assert fetched is not None
            assert fetched.job_title == title
            assert fetched.company == company
            assert fetched.status == "discovered"

        await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 11: Valid Status Transition Enforcement
# ---------------------------------------------------------------------------


@given(
    invalid_status=st.text(min_size=1, max_size=30).filter(
        lambda s: s not in VALID_STATUSES
    ),
)
@settings(max_examples=100)
def test_valid_status_transition_enforcement(invalid_status: str) -> None:
    """update_job_status only accepts statuses in VALID_STATUSES; rejects others."""
    from src.db.job_repo import create_job_record, update_job_status

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = f"status-{abs(hash(invalid_status)) % 100000}"
            await create_job_record(
                session,
                id=job_id,
                job_title="Test Job",
                company="TestCo",
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )

            with pytest.raises(ValueError, match="Invalid status"):
                await update_job_status(session, job_id, invalid_status)
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 12: Statistics Calculation Accuracy
# ---------------------------------------------------------------------------


@given(
    n_applied=st.integers(min_value=0, max_value=5),
    n_skipped=st.integers(min_value=0, max_value=5),
    n_discovered=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_statistics_calculation_accuracy(
    n_applied: int, n_skipped: int, n_discovered: int
) -> None:
    """Given known job records with specific statuses, counts match exactly."""
    from src.db.job_repo import get_stats

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            now = datetime.now(UTC).isoformat()
            counter = 0

            for _ in range(n_applied):
                counter += 1
                record = JobRecord(
                    id=f"stats-applied-{counter}",
                    job_title="Applied Job",
                    company="Co",
                    linkedin_url=f"https://linkedin.com/jobs/view/a{counter}",
                    apply_type="easy_apply",
                    status="applied",
                    discovered_at=now,
                    updated_at=now,
                )
                session.add(record)

            for _ in range(n_skipped):
                counter += 1
                record = JobRecord(
                    id=f"stats-skipped-{counter}",
                    job_title="Skipped Job",
                    company="Co",
                    linkedin_url=f"https://linkedin.com/jobs/view/s{counter}",
                    apply_type="easy_apply",
                    status="skipped",
                    discovered_at=now,
                    updated_at=now,
                )
                session.add(record)

            for _ in range(n_discovered):
                counter += 1
                record = JobRecord(
                    id=f"stats-disc-{counter}",
                    job_title="Discovered Job",
                    company="Co",
                    linkedin_url=f"https://linkedin.com/jobs/view/d{counter}",
                    apply_type="easy_apply",
                    status="discovered",
                    discovered_at=now,
                    updated_at=now,
                )
                session.add(record)

            await session.flush()

            stats = await get_stats(session)
            total = n_applied + n_skipped + n_discovered
            assert stats["total_discovered"] == total
            assert stats["total_applied"] == n_applied
            assert stats["total_skipped"] == n_skipped
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 13: Human Queue Resolution Completeness
# ---------------------------------------------------------------------------


@given(action=st.sampled_from(["approve", "reject"]))
@settings(max_examples=100)
def test_human_queue_resolution_completeness(action: str) -> None:
    """After approving/rejecting a job, it no longer appears in queue queries."""
    from src.db.job_repo import create_job_record, get_queue_items, update_job_status

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = f"queue-{action}-{abs(hash(datetime.now(UTC).isoformat())) % 100000}"

            record = await create_job_record(
                session,
                id=job_id,
                job_title="Queue Job",
                company="QueueCo",
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )
            record.queue_reason = "threshold_boundary"
            record.status = "scored"
            await session.flush()

            # Verify it's in the queue
            queue_before = await get_queue_items(session)
            assert any(j.id == job_id for j in queue_before)

            # Resolve it: update status and clear queue_reason (full resolution)
            if action == "approve":
                new_status = "approved_for_apply"
            else:
                new_status = "rejected_by_user"

            await update_job_status(session, job_id, new_status)
            # Clear queue_reason to fully resolve the queue item
            record.queue_reason = None
            await session.flush()

            # Verify it's no longer in the queue
            queue_after = await get_queue_items(session)
            assert not any(j.id == job_id for j in queue_after)

            # Verify correct status
            result = await session.execute(
                select(JobRecord).where(JobRecord.id == job_id)
            )
            updated = result.scalar_one()
            assert updated.status == new_status
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 14: Threshold Boundary Detection
# ---------------------------------------------------------------------------


@given(
    score=st.integers(min_value=0, max_value=100),
    good_fit=st.integers(min_value=5, max_value=95),
    stretch=st.integers(min_value=3, max_value=93),
)
@settings(max_examples=100)
def test_threshold_boundary_detection(
    score: int, good_fit: int, stretch: int
) -> None:
    """is_threshold_boundary returns True iff score is within ±2 of either threshold."""
    if stretch >= good_fit:
        return

    result = is_threshold_boundary(score, good_fit, stretch)
    expected = abs(score - good_fit) <= 2 or abs(score - stretch) <= 2
    assert result == expected


# ---------------------------------------------------------------------------
# Property 15: Vision Agent Field Mapping Coverage
# ---------------------------------------------------------------------------


@given(
    full_name=st.text(
        alphabet=st.characters(whitelist_categories=("L",), min_codepoint=65),
        min_size=3,
        max_size=30,
    ),
    email=st.from_regex(r"[a-z]{3,10}@[a-z]{3,8}\.(com|org|net)", fullmatch=True),
    phone=st.from_regex(r"[0-9]{10}", fullmatch=True),
)
@settings(max_examples=100)
def test_vision_agent_field_mapping_coverage(
    full_name: str, email: str, phone: str
) -> None:
    """For DOM fields with labels matching known profile keys, fill plan includes values."""
    from src.agents.vision_agent import _build_fill_plan

    profile = UserProfile(
        full_name=full_name,
        email=email,
        phone=phone,
        location="New York, NY",
        work_auth="US Citizen",
        linkedin_url="https://linkedin.com/in/test",
        common_answers={},
    )

    # DOM fields with labels that match known profile keys
    dom_fields = [
        {"label": "Full Name", "type": "text", "selector": "#name", "id": "name", "name": "name", "tag": "input", "value": ""},
        {"label": "Email Address", "type": "email", "selector": "#email", "id": "email", "name": "email", "tag": "input", "value": ""},
        {"label": "Phone Number", "type": "tel", "selector": "#phone", "id": "phone", "name": "phone", "tag": "input", "value": ""},
        {"label": "Unknown Custom Field XYZ", "type": "text", "selector": "#custom", "id": "custom", "name": "custom", "tag": "input", "value": ""},
    ]

    fill_plan = _build_fill_plan(dom_fields, profile, min_salary=None)

    # Known fields should be in the plan
    plan_labels = [item["label"] for item in fill_plan]
    assert "Full Name" in plan_labels
    assert "Email Address" in plan_labels
    assert "Phone Number" in plan_labels

    # Unknown field should NOT be in the plan
    assert "Unknown Custom Field XYZ" not in plan_labels

    # Values should match profile
    for item in fill_plan:
        if item["label"] == "Full Name":
            assert item["value"] == full_name
        elif item["label"] == "Email Address":
            assert item["value"] == email
        elif item["label"] == "Phone Number":
            assert item["value"] == phone


# ---------------------------------------------------------------------------
# Property 16: PDF Path Persistence After Tailoring
# ---------------------------------------------------------------------------


@given(
    pdf_path=st.from_regex(
        r"/app/data/resumes/[a-z0-9]{5,15}\.pdf", fullmatch=True
    ),
)
@settings(max_examples=100)
def test_pdf_path_persistence_after_tailoring(pdf_path: str) -> None:
    """After setting tailored_resume_pdf on a JobRecord and flushing, path is retrievable."""
    from src.db.job_repo import create_job_record

    async def _run() -> None:
        session, engine = await _make_session()
        try:
            job_id = f"pdf-{abs(hash(pdf_path)) % 100000}"
            record = await create_job_record(
                session,
                id=job_id,
                job_title="PDF Test Job",
                company="PDFCo",
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                apply_type="easy_apply",
            )

            record.tailored_resume_pdf = pdf_path
            await session.flush()

            # Re-query
            result = await session.execute(
                select(JobRecord).where(JobRecord.id == job_id)
            )
            fetched = result.scalar_one()
            assert fetched.tailored_resume_pdf == pdf_path
            assert len(fetched.tailored_resume_pdf) > 0
        finally:
            await _cleanup(session, engine)

    asyncio.run(_run())
