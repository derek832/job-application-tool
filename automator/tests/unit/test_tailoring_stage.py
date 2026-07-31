"""Unit tests for the resume tailoring pipeline stage."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, JobRecord
from src.exceptions import GDocsError, TailoringError
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.notification_service import NotificationSettings
from src.pipeline.tailoring_stage import restore_resume_base, run_tailoring


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


@pytest_asyncio.fixture
async def sample_job_record(async_session: AsyncSession) -> JobRecord:
    """Insert and return a sample job record with status 'approved_for_apply'."""
    record = JobRecord(
        id="99001",
        job_title="Backend Engineer",
        company="TechCo",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/99001",
        apply_type="easy_apply",
        status="approved_for_apply",
        description_text="We need a Python backend engineer with FastAPI experience.",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.fixture
def sms_settings() -> NotificationSettings:
    """Return sample notification settings for testing."""
    return NotificationSettings(
        ntfy_enabled=False,
        ntfy=None,
        sms_enabled=True,
        sms=SMSSettings(
            gmail_user="test@gmail.com",
            sms_gateway="5551234567@txt.att.net",
        ),
    )


@pytest.mark.asyncio
async def test_tailoring_success(async_session: AsyncSession, sample_job_record: JobRecord):
    """On successful tailoring, status becomes 'tailored' and PDF path is stored."""
    resume_base = "Original resume content with skills and experience."
    replacements_json = '[{"find": "skills", "replace": "ATS keywords"}]'

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = resume_base
    gdocs_client.write_resume.return_value = None
    gdocs_client.tailor_and_export.return_value = 1

    claude_client = AsyncMock()
    claude_client.tailor_resume.return_value = replacements_json
    claude_client._extract_json = lambda text: text  # sync staticmethod

    await run_tailoring(
        job_record=sample_job_record,
        session=async_session,
        gdocs_client=gdocs_client,
        claude_client=claude_client,
    )

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "tailored"
    assert sample_job_record.resume_snapshot == json.dumps(resume_base)
    assert sample_job_record.tailored_resume_pdf == "data/pdfs/TechCo_Backend_Engineer_Resume.pdf"
    assert sample_job_record.error_message is None
    assert sample_job_record.queue_reason is None


@pytest.mark.asyncio
async def test_tailoring_stores_resume_snapshot(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """The pre-tailoring resume content is stored as JSON in resume_snapshot."""
    resume_base = "My resume with special chars: quotes \"here\" and newlines\n"

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = resume_base
    gdocs_client.write_resume.return_value = None
    gdocs_client.export_pdf.return_value = None
    gdocs_client.tailor_and_export.return_value = 1

    replacements_json = '[{"find": "skills", "replace": "ATS keywords"}]'
    claude_client = AsyncMock()
    claude_client.tailor_resume.return_value = replacements_json
    claude_client._extract_json = lambda text: text

    await run_tailoring(
        job_record=sample_job_record,
        session=async_session,
        gdocs_client=gdocs_client,
        claude_client=claude_client,
    )

    await async_session.refresh(sample_job_record)
    # Verify the snapshot can be deserialized back to the original content
    restored = json.loads(sample_job_record.resume_snapshot)
    assert restored == resume_base


@pytest.mark.asyncio
async def test_tailoring_calls_claude_with_description_and_resume(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """Claude is called with the job description and resume base content."""
    resume_base = "Original resume"

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = resume_base
    gdocs_client.write_resume.return_value = None
    gdocs_client.export_pdf.return_value = None
    gdocs_client.tailor_and_export.return_value = 1

    replacements_json = '[{"find": "skills", "replace": "ATS keywords"}]'
    claude_client = AsyncMock()
    claude_client.tailor_resume.return_value = replacements_json
    claude_client._extract_json = lambda text: text

    await run_tailoring(
        job_record=sample_job_record,
        session=async_session,
        gdocs_client=gdocs_client,
        claude_client=claude_client,
    )

    claude_client.tailor_resume.assert_called_once_with(
        description=sample_job_record.description_text,
        resume_base=resume_base,
        supplementary_context=None,
    )


@pytest.mark.asyncio
async def test_tailoring_gdocs_authorization_error_pauses_system(
    async_session: AsyncSession, sample_job_record: JobRecord, sms_settings: NotificationSettings
):
    """On GDocsError with authorization_expired=True, system state is set to error."""
    gdocs_client = AsyncMock()
    gdocs_client.read_resume.side_effect = GDocsError(
        "Authorization expired", authorization_expired=True
    )

    claude_client = AsyncMock()

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock) as mock_notify:
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
            notification_settings=sms_settings,
        )

    # Job status should NOT be changed (remains approved_for_apply)
    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "approved_for_apply"

    # Verify notify was called with authorization trigger
    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args[1]
    assert call_kwargs["trigger_reason"] == "gdocs_authorization_expired"


@pytest.mark.asyncio
async def test_tailoring_gdocs_authorization_error_sets_system_state(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """On authorization error, system_state config is set to 'error'."""
    gdocs_client = AsyncMock()
    gdocs_client.read_resume.side_effect = GDocsError(
        "Authorization expired", authorization_expired=True
    )

    claude_client = AsyncMock()

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock):
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
        )

    # Verify system_state was set via config_repo
    from src.db.config_repo import get_config

    state = await get_config(async_session, "system_state")
    assert state is not None
    assert state["status"] == "error"
    assert "authorization" in state["last_error"].lower()
    assert "last_run_at" in state


@pytest.mark.asyncio
async def test_tailoring_gdocs_non_auth_error_sets_resume_failed(
    async_session: AsyncSession, sample_job_record: JobRecord, sms_settings: NotificationSettings
):
    """On non-authorization GDocsError, status becomes 'scored'."""
    gdocs_client = AsyncMock()
    gdocs_client.read_resume.side_effect = GDocsError(
        "Network timeout after 3 attempts", authorization_expired=False
    )

    claude_client = AsyncMock()

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock) as mock_notify:
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
            notification_settings=sms_settings,
        )

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "scored"
    assert sample_job_record.queue_reason == "resume_tailoring_failed"
    assert sample_job_record.error_message == "Network timeout after 3 attempts"

    # Verify SMS notification was sent
    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args[1]
    assert call_kwargs["trigger_reason"] == "resume_tailoring_failed"


@pytest.mark.asyncio
async def test_tailoring_claude_error_sets_resume_failed(
    async_session: AsyncSession, sample_job_record: JobRecord, sms_settings: NotificationSettings
):
    """On TailoringError from Claude, status becomes 'scored'."""
    resume_base = "Original resume"

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = resume_base

    claude_client = AsyncMock()
    claude_client.tailor_resume.side_effect = TailoringError(
        message="Claude API call failed after 3 attempts for resume tailoring"
    )

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock) as mock_notify:
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
            notification_settings=sms_settings,
        )

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "scored"
    assert sample_job_record.queue_reason == "resume_tailoring_failed"
    assert "Claude API" in sample_job_record.error_message

    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_tailoring_write_failure_sets_resume_failed(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """On GDocsError during tailor_and_export, status becomes 'scored'."""
    replacements_json = '[{"find": "skills", "replace": "ATS keywords"}]'

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = "Original resume"
    gdocs_client.tailor_and_export.side_effect = GDocsError(
        "Write failed after 3 attempts", authorization_expired=False
    )

    claude_client = AsyncMock()
    claude_client.tailor_resume.return_value = replacements_json
    claude_client._extract_json = lambda text: text

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock):
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
        )

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "scored"
    assert sample_job_record.queue_reason == "resume_tailoring_failed"


@pytest.mark.asyncio
async def test_tailoring_export_pdf_failure_sets_resume_failed(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """On GDocsError during tailor_and_export, status becomes 'scored'."""
    replacements_json = '[{"find": "skills", "replace": "ATS keywords"}]'

    gdocs_client = AsyncMock()
    gdocs_client.read_resume.return_value = "Original resume"
    gdocs_client.tailor_and_export.side_effect = GDocsError(
        "PDF export failed", authorization_expired=False
    )

    claude_client = AsyncMock()
    claude_client.tailor_resume.return_value = replacements_json
    claude_client._extract_json = lambda text: text

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock):
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
        )

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "scored"
    assert sample_job_record.queue_reason == "resume_tailoring_failed"


@pytest.mark.asyncio
async def test_tailoring_no_sms_settings_skips_notification(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """When notification_settings is None, notification is not attempted on failure."""
    gdocs_client = AsyncMock()
    gdocs_client.read_resume.side_effect = GDocsError(
        "Network error", authorization_expired=False
    )

    claude_client = AsyncMock()

    with patch("src.pipeline.tailoring_stage.notify", new_callable=AsyncMock) as mock_notify:
        await run_tailoring(
            job_record=sample_job_record,
            session=async_session,
            gdocs_client=gdocs_client,
            claude_client=claude_client,
            notification_settings=None,
        )

    # notify should not be called when notification_settings is None
    mock_notify.assert_not_called()

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "scored"


# ---------------------------------------------------------------------------
# Tests for restore_resume_base (Task 10.7, Requirement 14.4)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def applied_job_with_snapshot(async_session: AsyncSession) -> JobRecord:
    """Insert and return a job record with status 'applied' and a resume snapshot."""
    original_content = "John Doe\nSoftware Engineer\n5 years experience in Python"
    record = JobRecord(
        id="99002",
        job_title="Backend Developer",
        company="TechCo",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/99002",
        apply_type="easy_apply",
        status="applied",
        resume_snapshot=json.dumps(original_content),
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T10:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.mark.asyncio
async def test_restore_resume_base_success(
    async_session: AsyncSession,
    applied_job_with_snapshot: JobRecord,
):
    """Successful restore writes the decoded snapshot content to Google Docs."""
    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(return_value=None)

    await restore_resume_base(applied_job_with_snapshot, mock_client, async_session)

    expected_content = "John Doe\nSoftware Engineer\n5 years experience in Python"
    mock_client.write_resume.assert_called_once_with(expected_content)


@pytest.mark.asyncio
async def test_restore_resume_base_no_snapshot(async_session: AsyncSession):
    """When resume_snapshot is None, restore is skipped without calling GDocs."""
    record = JobRecord(
        id="99003",
        job_title="Data Scientist",
        company="DataCo",
        location="NYC",
        linkedin_url="https://www.linkedin.com/jobs/view/99003",
        apply_type="easy_apply",
        status="applied",
        resume_snapshot=None,
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T10:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(return_value=None)

    await restore_resume_base(record, mock_client, async_session)

    mock_client.write_resume.assert_not_called()


@pytest.mark.asyncio
async def test_restore_resume_base_empty_snapshot(async_session: AsyncSession):
    """When resume_snapshot is an empty string, restore is skipped."""
    record = JobRecord(
        id="99004",
        job_title="ML Engineer",
        company="AICo",
        location="SF",
        linkedin_url="https://www.linkedin.com/jobs/view/99004",
        apply_type="easy_apply",
        status="applied",
        resume_snapshot="",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T10:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(return_value=None)

    await restore_resume_base(record, mock_client, async_session)

    mock_client.write_resume.assert_not_called()


@pytest.mark.asyncio
async def test_restore_resume_base_invalid_json(async_session: AsyncSession):
    """When resume_snapshot contains invalid JSON, restore logs error and returns."""
    record = JobRecord(
        id="99005",
        job_title="DevOps Engineer",
        company="CloudCo",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/99005",
        apply_type="easy_apply",
        status="applied",
        resume_snapshot="{not valid json",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T10:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(return_value=None)

    # Should not raise â€” errors are handled gracefully
    await restore_resume_base(record, mock_client, async_session)

    mock_client.write_resume.assert_not_called()


@pytest.mark.asyncio
async def test_restore_resume_base_gdocs_error_does_not_raise(
    async_session: AsyncSession,
    applied_job_with_snapshot: JobRecord,
):
    """When GDocs write fails, the error is logged but not raised."""
    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(
        side_effect=GDocsError("Network timeout after 3 attempts")
    )

    # Should not raise â€” errors are handled gracefully
    await restore_resume_base(applied_job_with_snapshot, mock_client, async_session)

    mock_client.write_resume.assert_called_once()


@pytest.mark.asyncio
async def test_restore_resume_base_complex_content(async_session: AsyncSession):
    """Restore correctly handles multi-line resume content with special characters."""
    complex_content = (
        "Jane Smith\n"
        "Senior Software Engineer | Python, Go, Rust\n"
        "\n"
        "Experience:\n"
        "\u2022 Led team of 8 engineers at Acme Corp (2020\u20132024)\n"
        "\u2022 Designed & implemented microservices handling 10M+ req/day\n"
        '\u2022 "Best Engineer" award Q3 2023'
    )
    record = JobRecord(
        id="99006",
        job_title="Staff Engineer",
        company="BigTech",
        location="Seattle, WA",
        linkedin_url="https://www.linkedin.com/jobs/view/99006",
        apply_type="easy_apply",
        status="applied",
        resume_snapshot=json.dumps(complex_content),
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T10:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()

    mock_client = AsyncMock()
    mock_client.write_resume = AsyncMock(return_value=None)

    await restore_resume_base(record, mock_client, async_session)

    mock_client.write_resume.assert_called_once_with(complex_content)
