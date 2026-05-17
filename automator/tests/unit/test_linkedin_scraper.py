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
    discover_and_extract_jobs,
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
        assert params["f_E"] == ["2"]

    def test_experience_level_associate(self) -> None:
        config = SearchConfig(experience_level="associate")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["3"]

    def test_experience_level_mid_senior(self) -> None:
        config = SearchConfig(experience_level="mid-senior")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["4"]

    def test_experience_level_director(self) -> None:
        config = SearchConfig(experience_level="director")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["5"]

    def test_experience_level_executive(self) -> None:
        config = SearchConfig(experience_level="executive")
        url = build_search_url(config)

        params = parse_qs(urlparse(url).query)
        assert params["f_E"] == ["6"]

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
        assert params["f_E"] == ["4"]
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
        assert params["f_E"] == ["4"]

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
# Tests for discover_and_extract_jobs
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


class TestDiscoverAndExtractJobs:
    """Tests for the discover_and_extract_jobs function.

    Note: discover_and_extract_jobs has a complex interaction with Playwright
    (clicking cards, reading right panel). These tests verify the high-level
    behavior: deduplication against DB, pagination, and URL navigation.
    """

    @pytest.mark.asyncio
    async def test_navigates_to_correct_search_url(self, async_session: AsyncSession) -> None:
        """discover_and_extract_jobs navigates to the URL built from the config."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])

        config = SearchConfig(keywords="python developer", location="NYC")

        with patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock):
            await discover_and_extract_jobs(page, config, async_session, max_pages=1)

        expected_url = build_search_url(config)
        page.goto.assert_called_once_with(expected_url, timeout=60000)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_cards_found(
        self, async_session: AsyncSession
    ) -> None:
        """discover_and_extract_jobs returns empty list when no job cards are found."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])

        config = SearchConfig(keywords="nonexistent")

        with patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock):
            result = await discover_and_extract_jobs(page, config, async_session, max_pages=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_filters_out_existing_ids(self, async_session: AsyncSession) -> None:
        """discover_and_extract_jobs excludes jobs that already exist in the database."""
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

        # Create a mock card that yields job_id "111111"
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(
            return_value="https://www.linkedin.com/jobs/view/111111/"
        )

        card = AsyncMock()
        card.query_selector = AsyncMock(return_value=link_el)
        card.click = AsyncMock()

        # Title and company elements
        title_el = AsyncMock()
        title_el.inner_text = AsyncMock(return_value="Existing Job")
        company_el = AsyncMock()
        company_el.inner_text = AsyncMock(return_value="Existing Co")

        desc_el = AsyncMock()
        desc_el.inner_text = AsyncMock(return_value="A" * 100)

        page = AsyncMock()
        page.goto = AsyncMock()
        # First call for job cards, second for fallback links (empty)
        page.query_selector_all = AsyncMock(return_value=[card])
        # query_selector calls: title_el, structured data script tags, company_el, description, easy_apply
        page.query_selector = AsyncMock(side_effect=[title_el, None, desc_el, None])

        config = SearchConfig(keywords="python")

        with (
            patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock),
            patch(
                "src.integrations.linkedin_scraper._extract_company_from_structured_data",
                new_callable=AsyncMock,
                return_value="Existing Co",
            ),
        ):
            result = await discover_and_extract_jobs(page, config, async_session, max_pages=1)

        # The job should be filtered out because it already exists in DB
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
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    async def test_extracts_description_on_first_attempt(self, mock_delay: AsyncMock) -> None:
        """Successfully extracts description text on the first try."""
        long_description = "We are looking for a Python developer with 5+ years of experience in building scalable systems."
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value=long_description)

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == long_description
        page.goto.assert_called_once_with(
            job_record.linkedin_url, wait_until="domcontentloaded", timeout=60000
        )

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    async def test_strips_whitespace_from_description(self, mock_delay: AsyncMock) -> None:
        """Strips leading/trailing whitespace from extracted text."""
        long_text = "  \n  Job description with whitespace that is long enough to pass the minimum length check  \n  "
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value=long_text)

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == long_text.strip()

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    async def test_tries_fallback_selectors(self, mock_delay: AsyncMock) -> None:
        """Falls back to subsequent selectors when the first ones don't match."""
        long_text = "Found via fallback selector with enough content to pass the minimum length threshold for extraction"
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value=long_text)

        # Return None for first selectors, then return the element
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(side_effect=[None, None, None, description_element])

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == long_text

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_failure_and_succeeds(
        self, mock_sleep: AsyncMock, mock_delay: AsyncMock
    ) -> None:
        """Retries after failure and succeeds on a subsequent attempt."""
        long_text = "Description after retry that is long enough to pass the minimum length check for extraction"
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value=long_text)

        page = AsyncMock()
        page.goto = AsyncMock(side_effect=[Exception("Navigation timeout"), None, None])
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)

        job_record = _make_job_record()
        result = await extract_description(page, job_record)

        assert result == long_text
        mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_after_all_retries_exhausted(
        self, mock_sleep: AsyncMock, mock_delay: AsyncMock
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
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_when_element_empty(
        self, mock_sleep: AsyncMock, mock_delay: AsyncMock
    ) -> None:
        """Raises ExtractionError when description element has empty text."""
        description_element = AsyncMock()
        description_element.inner_text = AsyncMock(return_value="   ")

        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=description_element)
        page.screenshot = AsyncMock()

        job_record = _make_job_record()

        with pytest.raises(ExtractionError) as exc_info:
            await extract_description(page, job_record)

        assert exc_info.value.job_id == "9876543210"
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    @patch("src.integrations.linkedin_scraper.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_extraction_error_when_no_selector_matches(
        self, mock_sleep: AsyncMock, mock_delay: AsyncMock
    ) -> None:
        """Raises ExtractionError when no description selector matches."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.screenshot = AsyncMock()

        job_record = _make_job_record()

        with pytest.raises(ExtractionError) as exc_info:
            await extract_description(page, job_record)

        assert exc_info.value.job_id == "9876543210"

    @pytest.mark.asyncio
    @patch("src.integrations.linkedin_scraper._human_delay", new_callable=AsyncMock)
    async def test_returns_plain_text_no_html(self, mock_delay: AsyncMock) -> None:
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
