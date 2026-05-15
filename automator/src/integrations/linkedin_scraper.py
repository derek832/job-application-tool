"""LinkedIn job search URL construction and scraping utilities."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlencode

import structlog
from playwright.async_api import Page
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import SearchConfig
from src.db.models import JobRecord
from src.exceptions import ExtractionError

logger = structlog.get_logger(__name__)

# Backoff delays (in seconds) for job description extraction retries.
_EXTRACTION_BACKOFF_DELAYS: list[int] = [5, 15, 30]

# LinkedIn query parameter mappings for job type
_JOB_TYPE_MAP: dict[str, str] = {
    "full-time": "F",
    "part-time": "P",
    "contract": "C",
    "internship": "I",
}

# LinkedIn query parameter mappings for experience level
_EXPERIENCE_LEVEL_MAP: dict[str, str] = {
    "entry": "1",
    "associate": "2",
    "mid-senior": "3",
    "director": "4",
    "executive": "5",
}

# LinkedIn query parameter mappings for remote preference
_REMOTE_PREF_MAP: dict[str, str] = {
    "on-site": "1",
    "remote": "2",
    "hybrid": "3",
}

_LINKEDIN_SEARCH_BASE = "https://www.linkedin.com/jobs/search/"


def build_search_url(config: SearchConfig) -> str:
    """Build a LinkedIn job search URL from the given search configuration.

    Maps all non-None SearchConfig fields to their corresponding LinkedIn query
    parameters and always includes the 24-hour recency filter (f_TPR=r86400).

    Args:
        config: The search configuration containing keywords, location, job type,
            experience level, and remote preference filters.

    Returns:
        A fully-encoded LinkedIn job search URL string.
    """
    params: dict[str, str] = {}

    if config.keywords is not None:
        params["keywords"] = config.keywords

    if config.location is not None:
        params["location"] = config.location

    if config.job_type is not None:
        mapped = _JOB_TYPE_MAP.get(config.job_type.lower())
        if mapped is not None:
            params["f_JT"] = mapped

    if config.experience_level is not None:
        mapped = _EXPERIENCE_LEVEL_MAP.get(config.experience_level.lower())
        if mapped is not None:
            params["f_E"] = mapped

    if config.remote_pref is not None:
        mapped = _REMOTE_PREF_MAP.get(config.remote_pref.lower())
        if mapped is not None:
            params["f_WT"] = mapped

    # Always include 24-hour recency filter
    params["f_TPR"] = "r86400"

    return f"{_LINKEDIN_SEARCH_BASE}?{urlencode(params)}"


# Regex pattern to extract job IDs from LinkedIn listing URLs.
# Matches paths like /jobs/view/3987654321/ or /jobs/view/3987654321
_JOB_ID_PATTERN = re.compile(r"/jobs/view/(\d+)")


async def _extract_job_ids_from_page(page: Page) -> set[str]:
    """Extract all job IDs from the current page's listing links.

    Finds all anchor elements whose href contains a LinkedIn job view URL
    and extracts the numeric job ID from each.

    Args:
        page: The Playwright page currently showing LinkedIn search results.

    Returns:
        A set of job ID strings found on the current page.
    """
    job_ids: set[str] = set()

    links = await page.query_selector_all("a[href*='/jobs/view/']")
    for link in links:
        href = await link.get_attribute("href")
        if href is None:
            continue
        match = _JOB_ID_PATTERN.search(href)
        if match:
            job_ids.add(match.group(1))

    return job_ids


async def _go_to_next_page(page: Page) -> bool:
    """Attempt to navigate to the next page of search results.

    Looks for a pagination button or link that advances to the next page.
    Returns True if navigation succeeded, False if no next page is available.

    Args:
        page: The Playwright page currently showing LinkedIn search results.

    Returns:
        True if the page navigated to the next results page, False otherwise.
    """
    # LinkedIn uses an aria-label="Next" button or a button with specific selectors
    next_button = await page.query_selector(
        "button[aria-label='Next'], "
        "a[aria-label='Next'], "
        "li.artdeco-pagination__indicator--number.active + li a, "
        "button[aria-label='Page forward']"
    )

    if next_button is None:
        return False

    is_disabled = await next_button.get_attribute("disabled")
    if is_disabled is not None:
        return False

    await next_button.click()
    await page.wait_for_load_state("networkidle")
    return True


async def discover_jobs(
    page: Page,
    config: SearchConfig,
    session: AsyncSession,
    max_pages: int = 5,
) -> list[str]:
    """Discover new job listings from LinkedIn search results.

    Navigates to the LinkedIn search URL built from the given config, paginates
    through up to ``max_pages`` of results, extracts job IDs from listing links,
    and returns only those IDs that do not already exist in the database.

    Args:
        page: A Playwright Page object (already authenticated with LinkedIn).
        config: The search configuration to build the LinkedIn search URL.
        session: Active async database session for deduplication queries.
        max_pages: Maximum number of result pages to scrape. Defaults to 5.

    Returns:
        A list of job ID strings that are new (not already in the database).
    """
    search_url = build_search_url(config)
    logger.info("job_discovery_started", search_url=search_url, max_pages=max_pages)

    await page.goto(search_url)
    await page.wait_for_load_state("networkidle")

    all_job_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        page_ids = await _extract_job_ids_from_page(page)
        all_job_ids.update(page_ids)

        logger.debug(
            "job_ids_extracted",
            page_number=page_num,
            ids_on_page=len(page_ids),
            total_ids=len(all_job_ids),
        )

        if page_num < max_pages:
            has_next = await _go_to_next_page(page)
            if not has_next:
                logger.info("pagination_ended", last_page=page_num)
                break

    if not all_job_ids:
        logger.info("no_job_ids_found")
        return []

    # Query DB for existing job IDs in a single batch
    result = await session.execute(select(JobRecord.id).where(JobRecord.id.in_(all_job_ids)))
    existing_ids: set[str] = set(result.scalars().all())

    new_ids = list(all_job_ids - existing_ids)

    logger.info(
        "job_discovery_completed",
        total_found=len(all_job_ids),
        already_existing=len(existing_ids),
        new_jobs=len(new_ids),
    )

    return new_ids


# ---------------------------------------------------------------------------
# LinkedIn job description selectors (ordered by specificity)
# ---------------------------------------------------------------------------

_DESCRIPTION_SELECTORS: list[str] = [
    "div.jobs-description__content",
    "div.jobs-description-content__text",
    "article.jobs-description__container",
    "div#job-details",
    "div.description__text",
    "section.show-more-less-html",
]


async def extract_description(page: Page, job_record: JobRecord) -> str:
    """Extract the full job description text from a LinkedIn job listing.

    Navigates to the job's LinkedIn URL, locates the description container
    element, and returns the inner text with all HTML stripped. Retries up to
    3 times with exponential backoff (5s, 15s, 30s) on failure.

    Args:
        page: A Playwright Page object (already authenticated with LinkedIn).
        job_record: The JobRecord whose ``linkedin_url`` will be navigated to.

    Returns:
        The plain-text job description with HTML stripped.

    Raises:
        ExtractionError: If the description cannot be extracted after all
            retry attempts are exhausted.
    """
    job_id = job_record.id
    url = job_record.linkedin_url
    last_error: Exception | None = None

    for attempt, delay in enumerate(_EXTRACTION_BACKOFF_DELAYS, start=1):
        try:
            logger.info(
                "extraction_attempt_started",
                job_id=job_id,
                attempt=attempt,
                url=url,
            )

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")

            # Try each selector in order until one matches
            description_text: str | None = None
            for selector in _DESCRIPTION_SELECTORS:
                element = await page.query_selector(selector)
                if element is not None:
                    description_text = await element.inner_text()
                    break

            if not description_text or not description_text.strip():
                raise ValueError("Job description element not found or empty")

            cleaned = description_text.strip()

            logger.info(
                "extraction_succeeded",
                job_id=job_id,
                attempt=attempt,
                description_length=len(cleaned),
            )

            return cleaned

        except Exception as exc:
            last_error = exc
            logger.warning(
                "extraction_attempt_failed",
                job_id=job_id,
                attempt=attempt,
                max_attempts=len(_EXTRACTION_BACKOFF_DELAYS),
                error=str(exc),
            )

            if attempt < len(_EXTRACTION_BACKOFF_DELAYS):
                await asyncio.sleep(delay)

    raise ExtractionError(
        message=(
            f"Failed to extract job description after "
            f"{len(_EXTRACTION_BACKOFF_DELAYS)} attempts: {last_error}"
        ),
        job_id=job_id,
    )
