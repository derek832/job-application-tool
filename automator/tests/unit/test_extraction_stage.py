"""Unit tests for the extraction pipeline stage."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, JobRecord
from src.exceptions import ExtractionError
from src.pipeline.extraction_stage import run_extraction


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
    """Insert and return a sample job record with status 'discovered'."""
    record = JobRecord(
        id="12345",
        job_title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://www.linkedin.com/jobs/view/12345",
        apply_type="easy_apply",
        status="discovered",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )
    async_session.add(record)
    await async_session.flush()
    return record


@pytest.mark.asyncio
async def test_extraction_success(async_session: AsyncSession, sample_job_record: JobRecord):
    """On successful extraction, status becomes 'extracted' and description is stored."""
    mock_page = AsyncMock()
    description = "We are looking for a talented software engineer..."

    with patch(
        "src.pipeline.extraction_stage.extract_description",
        new_callable=AsyncMock,
        return_value=description,
    ):
        await run_extraction(sample_job_record, mock_page, async_session)

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "extracted"
    assert sample_job_record.description_text == description
    assert sample_job_record.extracted_at is not None
    assert sample_job_record.queue_reason is None
    assert sample_job_record.error_message is None


@pytest.mark.asyncio
async def test_extraction_failure_sets_extraction_failed(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """On ExtractionError, status becomes 'extraction_failed' and queue_reason is set."""
    mock_page = AsyncMock()
    error_msg = "Element not found after 3 attempts"

    with patch(
        "src.pipeline.extraction_stage.extract_description",
        new_callable=AsyncMock,
        side_effect=ExtractionError(message=error_msg, job_id="12345"),
    ):
        await run_extraction(sample_job_record, mock_page, async_session)

    await async_session.refresh(sample_job_record)
    assert sample_job_record.status == "extraction_failed"
    assert sample_job_record.queue_reason == "extraction_failed"
    assert sample_job_record.error_message == error_msg


@pytest.mark.asyncio
async def test_extraction_success_does_not_set_error_fields(
    async_session: AsyncSession, sample_job_record: JobRecord
):
    """Successful extraction leaves error_message and queue_reason as None."""
    mock_page = AsyncMock()
    description = "Join our team as a backend developer."

    with patch(
        "src.pipeline.extraction_stage.extract_description",
        new_callable=AsyncMock,
        return_value=description,
    ):
        await run_extraction(sample_job_record, mock_page, async_session)

    await async_session.refresh(sample_job_record)
    assert sample_job_record.error_message is None
    assert sample_job_record.queue_reason is None
