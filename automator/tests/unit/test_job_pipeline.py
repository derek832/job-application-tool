"""Unit tests for the main pipeline orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.config_repo import set_config
from src.db.models import Base, JobRecord, StatusTransition
from src.integrations.linkedin_scraper import DiscoveredJob
from src.pipeline.health_checker import HealthCheckResult
from src.pipeline.job_pipeline import _build_sms_settings, _get_jobs_by_status, run_pipeline


def _healthy_check_result() -> HealthCheckResult:
    """Return a healthy HealthCheckResult for mocking."""
    return HealthCheckResult(
        chrome_reachable=True,
        linkedin_authenticated=True,
        error_message=None,
        checked_at="2024-01-15T09:00:00+00:00",
    )


@pytest_asyncio.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_aborts_when_paused(async_session: AsyncSession):
    """Pipeline returns immediately when system_state.status is 'paused'."""
    await set_config(async_session, "system_state", {"status": "paused", "last_run_at": None})
    await async_session.commit()

    # Should not raise or attempt any browser operations
    await run_pipeline(async_session)

    # Verify system_state was not modified (still paused)
    from src.db.config_repo import get_config

    state = await get_config(async_session, "system_state")
    assert state["status"] == "paused"


@pytest.mark.asyncio
async def test_pipeline_pauses_when_goals_not_configured(async_session: AsyncSession):
    """Pipeline pauses the system when goals_profile is not configured."""
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await async_session.commit()

    await run_pipeline(async_session)

    from src.db.config_repo import get_config

    state = await get_config(async_session, "system_state")
    assert state["status"] == "paused"
    assert state["last_error"] == "Goals profile not configured"


@pytest.mark.asyncio
async def test_pipeline_runs_discovery_and_creates_records(async_session: AsyncSession):
    """Pipeline discovers new jobs and creates JobRecords for them."""
    # Set up required config
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        async_session,
        "goals_profile",
        {"target_titles": ["Engineer"], "deal_breakers": [], "open_to_stretch": True},
    )
    await set_config(async_session, "search_config", {"keywords": "python"})
    await set_config(async_session, "user_profile", {"full_name": "Test User"})
    await set_config(
        async_session,
        "settings",
        {"claude_api_key": "sk-test", "good_fit_threshold": 75, "stretch_threshold": 50},
    )
    await async_session.commit()

    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]

    mock_pw = AsyncMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    with (
        patch("src.pipeline.job_pipeline.async_playwright") as mock_async_pw,
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=_healthy_check_result(),
        ),
        patch(
            "src.pipeline.job_pipeline.discover_and_extract_jobs",
            new_callable=AsyncMock,
            return_value=[
                DiscoveredJob(
                    job_id="111",
                    title="Engineer",
                    company="Acme",
                    description="A great job with lots of Python work and more details here.",
                    linkedin_url="https://www.linkedin.com/jobs/view/111",
                ),
                DiscoveredJob(
                    job_id="222",
                    title="Developer",
                    company="Beta Inc",
                    description="Another great job with lots of Python work and more details.",
                    linkedin_url="https://www.linkedin.com/jobs/view/222",
                ),
            ],
        ),
        patch(
            "src.pipeline.job_pipeline.run_scoring",
            new_callable=AsyncMock,
        ),
    ):
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)

        await run_pipeline(async_session)

    # Verify job records were created
    # They may have been processed by extraction, so check they exist at all
    result = await async_session.execute(select(JobRecord))
    all_jobs = list(result.scalars().all())
    assert len(all_jobs) == 2
    job_ids = {j.id for j in all_jobs}
    assert "111" in job_ids
    assert "222" in job_ids


@pytest.mark.asyncio
async def test_pipeline_skips_terminal_status_jobs(async_session: AsyncSession):
    """_get_jobs_by_status does not return jobs in terminal states."""
    # Insert jobs with various statuses
    for status in ["discovered", "applied", "skipped", "rejected_by_user"]:
        record = JobRecord(
            id=f"job_{status}",
            job_title="Test",
            company="Test Co",
            linkedin_url=f"https://linkedin.com/jobs/view/job_{status}",
            apply_type="easy_apply",
            status=status,
            discovered_at="2024-01-15T09:00:00+00:00",
            updated_at="2024-01-15T09:00:00+00:00",
        )
        async_session.add(record)
    await async_session.flush()

    discovered = await _get_jobs_by_status(async_session, "discovered")
    assert len(discovered) == 1
    assert discovered[0].id == "job_discovered"

    # Terminal statuses should return empty
    applied = await _get_jobs_by_status(async_session, "applied")
    assert len(applied) == 0


def test_build_sms_settings_returns_none_when_incomplete():
    """_build_sms_settings returns None when required fields are missing."""
    from src.api.schemas import Settings

    settings = Settings(gmail_user=None, gmail_app_password=None, sms_gateway=None)
    assert _build_sms_settings(settings) is None


def test_build_sms_settings_returns_settings_when_complete():
    """_build_sms_settings returns SMSSettings when all fields are present."""
    from src.api.schemas import Settings

    settings = Settings(
        gmail_user="user@gmail.com",
        gmail_app_password="app-pass",
        sms_gateway="5551234567@txt.att.net",
    )
    result = _build_sms_settings(settings)
    assert result is not None
    assert result.gmail_user == "user@gmail.com"
    assert result.sms_gateway == "5551234567@txt.att.net"


def test_build_sms_settings_returns_none_when_redacted():
    """_build_sms_settings returns None when secrets are redacted ('***')."""
    from src.api.schemas import Settings

    settings = Settings(
        claude_api_key="***",
        gmail_user="***",
        gmail_app_password="***",
        sms_gateway="5551234567@txt.att.net",
    )
    result = _build_sms_settings(settings)
    assert result is None


@pytest.mark.asyncio
async def test_pipeline_idempotent_on_terminal_state_jobs(async_session: AsyncSession):
    """Re-running the pipeline on a DB with only terminal-state jobs produces no state changes.

    This verifies the idempotency guarantee: jobs in terminal states (applied,
    skipped, rejected_by_user, manually_applied) are never re-processed by any
    pipeline stage.

    Validates: Requirements 1.1, 5.4, 14.4
    """
    # Set up required config so the pipeline proceeds past the config checks
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        async_session,
        "goals_profile",
        {
            "target_titles": ["Engineer"],
            "deal_breakers": [],
            "open_to_stretch": True,
            "min_salary": 100000,
        },
    )
    await set_config(async_session, "search_config", {"keywords": "python"})
    await set_config(async_session, "user_profile", {"full_name": "Test User"})
    await set_config(
        async_session,
        "settings",
        {
            "claude_api_key": "sk-test",
            "good_fit_threshold": 75,
            "stretch_threshold": 50,
            "gdocs_script_url": "https://script.google.com/test",
        },
    )
    await async_session.commit()

    # Insert jobs in all terminal states
    terminal_jobs = []
    for status in ["applied", "skipped", "rejected_by_user", "manually_applied"]:
        record = JobRecord(
            id=f"terminal_{status}",
            job_title=f"Job {status}",
            company="Terminal Co",
            linkedin_url=f"https://linkedin.com/jobs/view/terminal_{status}",
            apply_type="easy_apply",
            status=status,
            discovered_at="2024-01-15T09:00:00+00:00",
            updated_at="2024-01-15T09:00:00+00:00",
        )
        async_session.add(record)
        terminal_jobs.append(record)
    await async_session.flush()
    await async_session.commit()

    # Capture the state before running the pipeline
    pre_run_states = {}
    for job in terminal_jobs:
        await async_session.refresh(job)
        pre_run_states[job.id] = {
            "status": job.status,
            "updated_at": job.updated_at,
        }

    # Count status transitions before the run
    pre_transitions_result = await async_session.execute(select(StatusTransition))
    pre_transition_count = len(list(pre_transitions_result.scalars().all()))

    # Mock Playwright and discovery (returns no new jobs)
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]

    mock_pw = AsyncMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_scoring = AsyncMock()
    mock_tailoring = AsyncMock()
    mock_easy_apply = AsyncMock()
    mock_restore = AsyncMock()

    with (
        patch("src.pipeline.job_pipeline.async_playwright") as mock_async_pw,
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=_healthy_check_result(),
        ),
        patch(
            "src.pipeline.job_pipeline.discover_and_extract_jobs",
            new_callable=AsyncMock,
            return_value=[],  # No new jobs discovered
        ),
        patch("src.pipeline.job_pipeline.run_scoring", mock_scoring),
        patch("src.pipeline.job_pipeline.run_tailoring", mock_tailoring),
        patch("src.pipeline.job_pipeline.run_easy_apply", mock_easy_apply),
        patch("src.pipeline.job_pipeline.restore_resume_base", mock_restore),
    ):
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)

        await run_pipeline(async_session)

    # Verify: no pipeline stages were called (no actionable jobs)
    mock_scoring.assert_not_called()
    mock_tailoring.assert_not_called()
    mock_easy_apply.assert_not_called()
    mock_restore.assert_not_called()

    # Verify: terminal-state jobs have not changed status or updated_at
    for job in terminal_jobs:
        await async_session.refresh(job)
        assert (
            job.status == pre_run_states[job.id]["status"]
        ), f"Job {job.id} status changed from {pre_run_states[job.id]['status']} to {job.status}"
        assert (
            job.updated_at == pre_run_states[job.id]["updated_at"]
        ), f"Job {job.id} updated_at changed unexpectedly"

    # Verify: no new status transitions were created for terminal jobs
    post_transitions_result = await async_session.execute(select(StatusTransition))
    post_transition_count = len(list(post_transitions_result.scalars().all()))
    assert (
        post_transition_count == pre_transition_count
    ), f"Expected no new transitions, but got {post_transition_count - pre_transition_count} new"


@pytest.mark.asyncio
async def test_pipeline_calls_all_stages_in_order(async_session: AsyncSession):
    """Pipeline calls all stages in the correct order: discovery → extraction →
    scoring → tailoring → easy_apply → restore_resume.

    Validates: Requirements 1.1, 5.4, 14.4
    """
    # Set up required config
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        async_session,
        "goals_profile",
        {
            "target_titles": ["Engineer"],
            "deal_breakers": [],
            "open_to_stretch": True,
            "min_salary": 100000,
        },
    )
    await set_config(async_session, "search_config", {"keywords": "python"})
    await set_config(async_session, "user_profile", {"full_name": "Test User"})
    await set_config(
        async_session,
        "settings",
        {
            "claude_api_key": "sk-test",
            "good_fit_threshold": 75,
            "stretch_threshold": 50,
            "gdocs_script_url": "https://script.google.com/test",
            "dry_run": False,
        },
    )
    await async_session.commit()

    # Track call order
    call_order: list[str] = []

    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]

    mock_pw = AsyncMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    async def mock_discover(*args, **kwargs):
        call_order.append("discover")
        return [
            DiscoveredJob(
                job_id="job_001",
                title="Engineer",
                company="Acme",
                description="A great job with lots of Python work and more details here.",
                linkedin_url="https://www.linkedin.com/jobs/view/job_001",
            )
        ]

    async def mock_scoring_fn(*args, **kwargs):
        call_order.append("scoring")
        # Simulate scoring advancing the job to "approved_for_apply"
        job_record = kwargs.get("job_record") or args[0]
        job_record.status = "approved_for_apply"

    async def mock_tailoring_fn(*args, **kwargs):
        call_order.append("tailoring")
        # Simulate tailoring advancing the job to "applying" (must persist to DB
        # because the pipeline does session.refresh after tailoring)
        job_record = kwargs.get("job_record") or args[0]
        job_record.status = "applying"
        sess = kwargs.get("session") or args[1]
        await sess.flush()

    async def mock_easy_apply_fn(*args, **kwargs):
        call_order.append("easy_apply")
        # Simulate successful application
        job_record = kwargs.get("job_record") or args[0]
        job_record.status = "applied"

    async def mock_restore_fn(*args, **kwargs):
        call_order.append("restore_resume")

    with (
        patch("src.pipeline.job_pipeline.async_playwright") as mock_async_pw,
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=_healthy_check_result(),
        ),
        patch(
            "src.pipeline.job_pipeline.discover_and_extract_jobs",
            side_effect=mock_discover,
        ),
        patch("src.pipeline.job_pipeline.run_scoring", side_effect=mock_scoring_fn),
        patch("src.pipeline.job_pipeline.run_tailoring", side_effect=mock_tailoring_fn),
        patch("src.pipeline.job_pipeline.run_easy_apply", side_effect=mock_easy_apply_fn),
        patch("src.pipeline.job_pipeline.restore_resume_base", side_effect=mock_restore_fn),
    ):
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)

        await run_pipeline(async_session)

    # Verify all stages were called in the correct order
    # Note: discovery and extraction are now combined in discover_and_extract_jobs
    assert "discover" in call_order, "Discovery stage was not called"
    assert "scoring" in call_order, "Scoring stage was not called"
    assert "tailoring" in call_order, "Tailoring stage was not called"
    assert "easy_apply" in call_order, "Easy Apply stage was not called"
    assert "restore_resume" in call_order, "Restore resume stage was not called"

    # Verify ordering: each stage comes after its predecessor
    assert call_order.index("discover") < call_order.index("scoring")
    assert call_order.index("scoring") < call_order.index("tailoring")
    assert call_order.index("tailoring") < call_order.index("easy_apply")
    assert call_order.index("easy_apply") < call_order.index("restore_resume")


@pytest.mark.asyncio
async def test_pipeline_blacklist_skips_matched_jobs(async_session: AsyncSession):
    """Pipeline skips jobs that match blacklist entries and increments hit_count.

    Validates: Requirements 4.3, 4.4, 4.5, 4.11
    """
    from src.db.models import BlacklistEntry

    # Set up required config
    await set_config(async_session, "system_state", {"status": "idle", "last_run_at": None})
    await set_config(
        async_session,
        "goals_profile",
        {
            "target_titles": ["Engineer"],
            "deal_breakers": [],
            "open_to_stretch": True,
            "min_salary": 0,
        },
    )
    await set_config(async_session, "search_config", {"keywords": "python"})
    await set_config(async_session, "user_profile", {"full_name": "Test User"})
    await set_config(
        async_session,
        "settings",
        {"claude_api_key": "sk-test", "good_fit_threshold": 75, "stretch_threshold": 50},
    )
    await async_session.commit()

    # Add blacklist entries
    bl_company = BlacklistEntry(
        entry_type="company",
        value="Revature",
        created_at="2024-01-01T00:00:00+00:00",
        hit_count=0,
    )
    bl_title = BlacklistEntry(
        entry_type="title_pattern",
        value="intern",
        created_at="2024-01-01T00:00:00+00:00",
        hit_count=0,
    )
    async_session.add(bl_company)
    async_session.add(bl_title)
    await async_session.flush()

    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]

    mock_pw = AsyncMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_scoring = AsyncMock()

    with (
        patch("src.pipeline.job_pipeline.async_playwright") as mock_async_pw,
        patch(
            "src.pipeline.job_pipeline.check_session_health",
            new_callable=AsyncMock,
            return_value=_healthy_check_result(),
        ),
        patch(
            "src.pipeline.job_pipeline.discover_and_extract_jobs",
            new_callable=AsyncMock,
            return_value=[
                DiscoveredJob(
                    job_id="bl_1",
                    title="Software Engineer",
                    company="Revature",
                    description="A job at Revature.",
                    linkedin_url="https://www.linkedin.com/jobs/view/bl_1",
                ),
                DiscoveredJob(
                    job_id="bl_2",
                    title="Software Engineering Intern",
                    company="Good Corp",
                    description="An internship position.",
                    linkedin_url="https://www.linkedin.com/jobs/view/bl_2",
                ),
                DiscoveredJob(
                    job_id="bl_3",
                    title="Senior Engineer",
                    company="Great Inc",
                    description="A great senior role.",
                    linkedin_url="https://www.linkedin.com/jobs/view/bl_3",
                ),
            ],
        ),
        patch(
            "src.pipeline.job_pipeline.run_scoring",
            mock_scoring,
        ),
    ):
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_pw)

        await run_pipeline(async_session)

    # Verify blacklisted jobs were skipped
    result = await async_session.execute(
        select(JobRecord).where(JobRecord.id == "bl_1")
    )
    job1 = result.scalar_one()
    assert job1.status == "skipped"

    # Check the status transition reason
    result = await async_session.execute(
        select(StatusTransition).where(
            StatusTransition.job_id == "bl_1",
            StatusTransition.to_status == "skipped",
        )
    )
    transition1 = result.scalar_one()
    assert "blacklisted" in (transition1.reason or "")
    assert "company:Revature" in (transition1.reason or "")

    result = await async_session.execute(
        select(JobRecord).where(JobRecord.id == "bl_2")
    )
    job2 = result.scalar_one()
    assert job2.status == "skipped"

    result = await async_session.execute(
        select(StatusTransition).where(
            StatusTransition.job_id == "bl_2",
            StatusTransition.to_status == "skipped",
        )
    )
    transition2 = result.scalar_one()
    assert "blacklisted" in (transition2.reason or "")
    assert "title:intern" in (transition2.reason or "")

    # Verify non-blacklisted job was NOT skipped (should be in extracted status)
    result = await async_session.execute(
        select(JobRecord).where(JobRecord.id == "bl_3")
    )
    job3 = result.scalar_one()
    assert job3.status != "skipped"

    # Verify hit_count was incremented
    await async_session.refresh(bl_company)
    await async_session.refresh(bl_title)
    assert bl_company.hit_count == 1
    assert bl_title.hit_count == 1

    # Verify scoring was only called for the non-blacklisted job
    # (scoring is called for each extracted job that passes pre-filters)
    scored_job_ids = [call.kwargs.get("job_record", call.args[0] if call.args else None)
                      for call in mock_scoring.call_args_list]
    # The non-blacklisted job should have been passed to scoring
    assert any(
        getattr(j, "id", None) == "bl_3" for j in scored_job_ids
    ), "Non-blacklisted job should have been scored"
    # Blacklisted jobs should NOT have been passed to scoring
    assert not any(
        getattr(j, "id", None) == "bl_1" for j in scored_job_ids
    ), "Blacklisted job bl_1 should not have been scored"
    assert not any(
        getattr(j, "id", None) == "bl_2" for j in scored_job_ids
    ), "Blacklisted job bl_2 should not have been scored"
