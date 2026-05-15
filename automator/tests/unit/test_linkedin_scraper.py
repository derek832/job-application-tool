"""Unit tests for the LinkedIn search URL builder and job discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.schemas import SearchConfig
from src.db.models import Base, JobRecord
from src.exceptions import ExtractionError
from src.integrations.linkedin_scraper import (
    _JOB_ID_PATTERN,
    _extract_job_ids_from_page,
    build_search_url,
    discover_jobs,
    extract_description,
)


class TestBuildSearchUrl:
    """Tests for build_search_url function."""

    def test_empty_config_includes_only_recency_filter(self) -> None:
        config = SearchConfig()
        url = build_search_url(config)

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "www.linkedin.com"
        assert parsed.path == "/jobs/search/"
        assert params["f_TPR"] == ["r86400"]
        assert len(params) == 1

    def test_keywords_included(self) -> None:
        config = SearchConfig(keywords="python developer")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["keywords"] == ["python developer"]
        assert params["f_TPR"] == ["r86400"]

    def test_location_included(self) -> None:
        config = SearchConfig(location="San Francisco, CA")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["location"] == ["San Francisco, CA"]

    def test_job_type_full_time(self) -> None:
        config = SearchConfig(job_type="full-time")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_JT"] == ["F"]

    def test_job_type_part_time(self) -> None:
        config = SearchConfig(job_type="part-time")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_JT"] == ["P"]

    def test_job_type_contract(self) -> None:
        config = SearchConfig(job_type="contract")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_JT"] == ["C"]

    def test_job_type_internship(self) -> None:
        config = SearchConfig(job_type="internship")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_JT"] == ["I"]

    def test_experience_level_entry(self) -> None:
        config = SearchConfig(experience_level="entry")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["1"]

    def test_experience_level_associate(self) -> None:
        config = SearchConfig(experience_level="associate")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["2"]

    def test_experience_level_mid_senior(self) -> None:
        config = SearchConfig(experience_level="mid-senior")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["3"]

    def test_experience_level_director(self) -> None:
        config = SearchConfig(experience_level="director")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["4"]

    def test_experience_level_executive(self) -> None:
        config = SearchConfig(experience_level="executive")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["5"]

    def test_remote_pref_on_site(self) -> None:
        config = SearchConfig(remote_pref="on-site")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_WT"] == ["1"]

    def test_remote_pref_remote(self) -> None:
        config = SearchConfig(remote_pref="remote")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_WT"] == ["2"]

    def test_remote_pref_hybrid(self) -> None:
        config = SearchConfig(remote_pref="hybrid")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_WT"] == ["3"]

    def test_all_fields_populated(self) -> None:
        config = SearchConfig(
            keywords="software engineer",
            location="New York",
            job_type="full-time",
            experience_level="mid-senior",
            remote_pref="remote",
        )
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["keywords"] == ["software engineer"]
        assert params["location"] == ["New York"]
        assert params["f_JT"] == ["F"]
        assert params["f_E"] == ["3"]
        assert params["f_WT"] == ["2"]
        assert params["f_TPR"] == ["r86400"]
        assert len(params) == 6

    def test_case_insensitive_job_type(self) -> None:
        config = SearchConfig(job_type="Full-Time")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_JT"] == ["F"]

    def test_case_insensitive_experience_level(self) -> None:
        config = SearchConfig(experience_level="Mid-Senior")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["3"]

    def test_case_insensitive_remote_pref(self) -> None:
        config = SearchConfig(remote_pref="Remote")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_WT"] == ["2"]

    def test_unknown_job_type_excluded(self) -> None:
        config = SearchConfig(job_type="freelance")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert "f_JT" not in params
        assert params["f_TPR"] == ["r86400"]

    def test_unknown_experience_level_excluded(self) -> None:
        config = SearchConfig(experience_level="senior")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert "f_E" not in params

    def test_unknown_remote_pref_excluded(self) -> None:
        config = SearchConfig(remote_pref="flexible")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert "f_WT" not in params

    def test_special_characters_in_keywords_are_encoded(self) -> None:
        config = SearchConfig(keywords="C++ & Java")
        url = build_search_url(config)

        # URL should be properly encoded
        assert "C%2B%2B+%26+Java" in url or "C%2B%2B+%26+Java" in url
        params = parse_qs(urlparse(url).query)
        assert params["keywords"] == ["C++ & Java"]

    def test_recency_filter_always_present(self) -> None:
        config = SearchConfig(keywords="test")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_TPR"] == ["r86400"]


# ---------------------------------------------------------------------------
# Tests for job ID regex pattern
# ---------------------------------------------------------------------------


class TestJobIdPattern:
    """Tests for the _JOB_ID_PATTERN regex."""

    def test_matches_standard_job_url(self) -> None:
        match = _JOB_ID_PATTERN.search("/jobs/view/3987654321/")
        assert match is not None
        assert match.group(1) == "3987654321"

    def test_matches_url_without_trailing_slash(self) -> None:
        match = _JOB_ID_PATTERN.search("/jobs/view/1234567890")
        assert match is not None
        assert match.group(1) == "1234567890"

    def test_matches_full_linkedin_url(self) -> None:
        match = _JOB_ID_PATTERN.search(
            "https://www.linkedin.com/jobs/view/3987654321/?trackingId=abc"
        )
        assert match is not None
        assert match.group(1) == "3987654321"

    def test_no_match_for_non_job_url(self) -> None:
        match = _JOB_ID_PATTERN.search("/in/john-doe/")
        assert match is None

    def test_no_match_for_empty_string(self) -> None:
        match = _JOB_ID_PATTERN.search("")
        assert match is None


# ---------------------------------------------------------------------------
# Tests for _extract_job_ids_from_page
# ---------------------------------------------------------------------------


class TestExtractJobIdsFromPage:
    """Tests for extracting job IDs from a Playwright page."""

    @pytest.mark.asyncio
    async def test_extracts_ids_from_links(self) -> None:
        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        link2 = AsyncMock()
        link2.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/222222/")

        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1, link2])

        ids = await _extract_job_ids_from_page(page)
        assert ids == {"111111", "222222"}

    @pytest.mark.asyncio
    async def test_deduplicates_ids_on_same_page(self) -> None:
        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        link2 = AsyncMock()
        link2.get_attribute = AsyncMock(
            return_value="https://www.linkedin.com/jobs/view/111111/?ref=abc"
        )

        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1, link2])

        ids = await _extract_job_ids_from_page(page)
        assert ids == {"111111"}

    @pytest.mark.asyncio
    async def test_skips_links_with_no_href(self) -> None:
        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value=None)

        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1])

        ids = await _extract_job_ids_from_page(page)
        assert ids == set()

    @pytest.mark.asyncio
    async def test_returns_empty_set_when_no_links(self) -> None:
        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])

        ids = await _extract_job_ids_from_page(page)
        assert ids == set()


# ---------------------------------------------------------------------------
# Tests for discover_jobs
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as session:
        yield session

    await engine.dispose()


class TestDiscoverJobs:
    """Tests for the discover_jobs function."""

    @pytest.mark.asyncio
    async def test_returns_new_job_ids(self, async_session: AsyncSession) -> None:
        """discover_jobs returns IDs not already in the database."""
        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        link2 = AsyncMock()
        link2.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/222222/")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1, link2])
        # No next page
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="python")
        result = await discover_jobs(page, config, async_session, max_pages=1)

        assert set(result) == {"111111", "222222"}

    @pytest.mark.asyncio
    async def test_filters_out_existing_ids(self, async_session: AsyncSession) -> None:
        """discover_jobs excludes IDs that already exist in the database."""
        # Insert an existing job record
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        existing_record = JobRecord(
            id="111111",
            job_title="Existing Job",
            company="Existing Co",
            linkedin_url="https://www.linkedin.com/jobs/view/111111/",
            apply_type="easy_apply",
            status="discovered",
            discovered_at=now,
            updated_at=now,
        )
        async_session.add(existing_record)
        await async_session.flush()

        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        link2 = AsyncMock()
        link2.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/222222/")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1, link2])
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="python")
        result = await discover_jobs(page, config, async_session, max_pages=1)

        assert result == ["222222"]

    @pytest.mark.asyncio
    async def test_paginates_up_to_max_pages(self, async_session: AsyncSession) -> None:
        """discover_jobs paginates through multiple pages."""
        # Page 1 links
        link_p1 = AsyncMock()
        link_p1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        # Page 2 links
        link_p2 = AsyncMock()
        link_p2.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/222222/")

        next_button = AsyncMock()
        next_button.get_attribute = AsyncMock(return_value=None)  # not disabled
        next_button.click = AsyncMock()

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        # First call returns page 1 links, second call returns page 2 links
        page.query_selector_all = AsyncMock(side_effect=[[link_p1], [link_p2]])
        # First call for next button returns a button, second returns None (no more pages)
        page.query_selector = AsyncMock(side_effect=[next_button, None])

        config = SearchConfig(keywords="python")
        result = await discover_jobs(page, config, async_session, max_pages=2)

        assert set(result) == {"111111", "222222"}

    @pytest.mark.asyncio
    async def test_stops_pagination_when_no_next_button(self, async_session: AsyncSession) -> None:
        """discover_jobs stops early when no next page button is found."""
        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1])
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="python")
        result = await discover_jobs(page, config, async_session, max_pages=5)

        assert result == ["111111"]
        # Should only have called query_selector_all once (stopped after page 1)
        assert page.query_selector_all.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_jobs_found(self, async_session: AsyncSession) -> None:
        """discover_jobs returns empty list when no job links are found."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="nonexistent")
        result = await discover_jobs(page, config, async_session, max_pages=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_navigates_to_correct_search_url(self, async_session: AsyncSession) -> None:
        """discover_jobs navigates to the URL built from the config."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="python developer", location="NYC")
        await discover_jobs(page, config, async_session, max_pages=1)

        expected_url = build_search_url(config)
        page.goto.assert_called_once_with(expected_url)

    @pytest.mark.asyncio
    async def test_all_existing_ids_returns_empty(self, async_session: AsyncSession) -> None:
        """discover_jobs returns empty list when all found IDs already exist."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        for job_id in ["111111", "222222"]:
            record = JobRecord(
                id=job_id,
                job_title="Job",
                company="Co",
                linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                apply_type="easy_apply",
                status="discovered",
                discovered_at=now,
                updated_at=now,
            )
            async_session.add(record)
        await async_session.flush()

        link1 = AsyncMock()
        link1.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/111111/")
        link2 = AsyncMock()
        link2.get_attribute = AsyncMock(return_value="https://www.linkedin.com/jobs/view/222222/")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[link1, link2])
        page.query_selector = AsyncMock(return_value=None)

        config = SearchConfig(keywords="python")
        result = await discover_jobs(page, config, async_session, max_pages=1)

        assert result == []


# ---------------------------------------------------------------------------
# Tests for extract_description
# ---------------------------------------------------------------------------


def _make_job_record() -> JobRecord:
    """Create a minimal JobRecord for testing extract_description."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    return JobRecord(
        id="9876543210",
        job_title="Senior Python Developer",
        company="TestCorp",
        linkedin_url="https://www.linkedin.com/jobs/view/9876543210/",
        apply_type="easy_apply",
        status="discovered",
        discovered_at=now,
        updated_at=now,
    )


class TestExtractDescription:
    """Tests for the extract_description function."""

    @pytest.mark.asyncio
    async def test_extracts_description_on_first_attempt(self) -> None:
        """Successfully extracts description text on the first try."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(
            return_value="We are looking for a Python developer with 5+ years experience."
        )

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == "We are looking for a Python developer with 5+ years experience."
        page.goto.assert_called_once_with(job_record.linkedin_url, wait_until="domcontentloaded")

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_description(self) -> None:
        """Strips leading/trailing whitespace from extracted text."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(
            return_value="  \n  Job description with whitespace  \n  "
        )

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == "Job description with whitespace"

    @pytest.mark.asyncio
    async def test_tries_fallback_selectors(self) -> None:
        """Falls back to subsequent selectors when the first ones don't match."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value="Found via fallback selector")

        # Return None for first selectors, then return the element
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(side_effect=[None, None, None, description_element])

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == "Found via fallback selector"

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_failure_and_succeeds(self, mock_sleep: AsyncMock) -> None:
        """Retries after failure and succeeds on a subsequent attempt."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value="Description after retry")

        page = AsyncMock()
        page.goto = AsyncMock(side_effect=[Exception("Navigation timeout"), None, None])
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == "Description after retry"
        mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_after_all_retries_exhausted(
        self, mock_sleep: AsyncMock
    ) -> None:
        """Raises ExtractionError after 3 failed attempts."""
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=Exception("Navigation timeout"))
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        job_record = _make_job_record()

        with pytest.raises(ExtractionError) as exc_info:
            await extract_description(page, job_record)

        assert exc_info.value.job_id == "9876543210"
        assert "3 attempts" in exc_info.value.message
        # Should have slept twice (after attempt 1 and 2, not after attempt 3)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(5)
        mock_sleep.assert_any_call(15)

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_when_element_empty(self, mock_sleep: AsyncMock) -> None:
        """Raises ExtractionError when description element has empty text."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value="   ")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()

        with pytest.raises(ExtractionError) as exc_info:
            await extract_description(page, job_record)

        assert exc_info.value.job_id == "9876543210"
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_when_no_selector_matches(
        self, mock_sleep: AsyncMock
    ) -> None:
        """Raises ExtractionError when no description selector matches."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        job_record = _make_job_record()

        with pytest.raises(ExtractionError) as exc_info:
            await extract_description(page, job_record)

        assert exc_info.value.job_id == "9876543210"

    @pytest.mark.asyncio
    async def test_returns_plain_text_no_html(self) -> None:
        """inner_text() already strips HTML; verify we get plain text."""
        # Playwright's inner_text() returns visible text without HTML tags
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(
            return_value="Requirements:\nPython 3.11+\nAsync experience\nDocker knowledge"
        )

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert "<" not in result
        assert ">" not in result
        assert "Python 3.11+" in result
