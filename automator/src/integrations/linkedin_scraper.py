"""LinkedIn job search URL construction and scraping utilities."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
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
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid-senior": "4",
    "director": "5",
    "executive": "6",
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

# Selectors for the job description in the right panel of search results
_RIGHT_PANEL_DESCRIPTION_SELECTORS: list[str] = [
    "div.jobs-description__content",
    "div.jobs-description-content__text",
    "div#job-details",
    "div.jobs-box__html-content",
    "section.show-more-less-html",
    "article.jobs-description__container",
    "div[class*='jobs-description']",
]


@dataclass
class DiscoveredJob:
    """Job data extracted from the search results page."""

    job_id: str
    title: str
    company: str
    description: str
    linkedin_url: str


async def discover_and_extract_jobs(
    page: Page,
    config: SearchConfig,
    session: AsyncSession,
    max_pages: int = 5,
) -> list[DiscoveredJob]:
    """Discover jobs and extract descriptions from the search results page.

    Instead of navigating to each job's individual page, this clicks each job
    card in the left panel and reads the description from the right panel.
    Much faster and more reliable than separate navigation.

    Args:
        page: A Playwright Page object (already authenticated with LinkedIn).
        config: The search configuration to build the LinkedIn search URL.
        session: Active async database session for deduplication queries.
        max_pages: Maximum number of result pages to scrape. Defaults to 5.

    Returns:
        A list of DiscoveredJob objects with title, company, and description.
    """
    search_url = build_search_url(config)
    logger.info("job_discovery_started", search_url=search_url, max_pages=max_pages)

    await page.goto(search_url, timeout=60000)
    await page.wait_for_timeout(5000)

    all_discovered: list[DiscoveredJob] = []
    seen_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        # Find all job cards on the current page
        job_cards = await page.query_selector_all(
            "li[class*='jobs-search-results__list-item'], "
            "div[class*='job-card-container'], "
            "li[data-occludable-job-id]"
        )

        if not job_cards:
            # Fallback: find links to job views
            job_cards = await page.query_selector_all("a[href*='/jobs/view/']")

        logger.info("discovery_page_cards_found", page=page_num, count=len(job_cards))

        for card in job_cards:
            try:
                # Extract job ID from the card's link
                link = await card.query_selector("a[href*='/jobs/view/']")
                if link is None:
                    # The card itself might be the link
                    href = await card.get_attribute("href")
                    if href is None:
                        continue
                else:
                    href = await link.get_attribute("href")

                if href is None:
                    continue

                match = _JOB_ID_PATTERN.search(href)
                if not match:
                    continue

                job_id = match.group(1)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Click the card to load the description in the right panel
                await card.click()
                await page.wait_for_timeout(2000)

                # Extract title and company from the right panel header
                title = "Unknown"
                company = "Unknown"

                title_el = await page.query_selector(
                    "h1.t-24, h2.t-24, h1[class*='job-title'], "
                    "h2[class*='jobs-unified-top-card__job-title'], "
                    "a[class*='job-title']"
                )
                if title_el:
                    title = (await title_el.inner_text()).strip()

                # Try to get company from the right panel
                company_el = await page.query_selector(
                    "div.job-details-jobs-unified-top-card__company-name a, "
                    "span.jobs-unified-top-card__company-name, "
                    "a[class*='company-name'], "
                    "div[class*='job-card-container__primary-description'], "
                    "span[class*='topcard__flavor'], "
                    "a[data-tracking-control-name='public_jobs_topcard-org-name']"
                )
                if company_el:
                    company = (await company_el.inner_text()).strip()

                # Fallback: try to get company from the card itself
                if company == "Unknown":
                    card_subtitle = await card.query_selector(
                        "span[class*='subtitle'], "
                        "div[class*='artdeco-entity-lockup__subtitle'], "
                        "span[class*='job-card-container__primary-description']"
                    )
                    if card_subtitle:
                        company = (await card_subtitle.inner_text()).strip().split("\n")[0]

                # Extract description from the right panel
                description = ""
                for selector in _RIGHT_PANEL_DESCRIPTION_SELECTORS:
                    try:
                        el = await page.query_selector(selector)
                        if el:
                            text = await el.inner_text()
                            if text and len(text.strip()) > 50:
                                description = text.strip()
                                break
                    except Exception:
                        continue

                if not description:
                    logger.warning("discovery_no_description", job_id=job_id)
                    continue

                all_discovered.append(DiscoveredJob(
                    job_id=job_id,
                    title=title,
                    company=company,
                    description=description,
                    linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                ))

                logger.info(
                    "discovery_job_extracted",
                    job_id=job_id,
                    title=title,
                    company=company,
                    desc_len=len(description),
                )

            except Exception as exc:
                logger.warning("discovery_card_error", error=str(exc))
                continue

        # Paginate
        if page_num < max_pages:
            has_next = await _go_to_next_page(page)
            if not has_next:
                logger.info("pagination_ended", last_page=page_num)
                break

    # Filter out jobs already in the DB (by job ID)
    if all_discovered:
        all_ids = {j.job_id for j in all_discovered}
        result = await session.execute(select(JobRecord.id).where(JobRecord.id.in_(all_ids)))
        existing_ids: set[str] = set(result.scalars().all())
        all_discovered = [j for j in all_discovered if j.job_id not in existing_ids]

    # Deduplicate by company + title (same role posted in multiple locations)
    # Also check against existing DB records to avoid re-scoring known roles
    if all_discovered:
        # Check DB for existing company+title combos
        existing_records = await session.execute(
            select(JobRecord.company, JobRecord.job_title)
        )
        existing_combos: set[str] = {
            f"{row.company}|{row.job_title}".lower()
            for row in existing_records.all()
        }

        # Deduplicate within the current batch and against DB
        seen_combos: set[str] = set()
        deduplicated: list[DiscoveredJob] = []
        for job in all_discovered:
            combo_key = f"{job.company}|{job.title}".lower()
            if combo_key in existing_combos or combo_key in seen_combos:
                logger.info(
                    "discovery_duplicate_skipped",
                    job_id=job.job_id,
                    title=job.title,
                    company=job.company,
                )
                continue
            seen_combos.add(combo_key)
            deduplicated.append(job)

        skipped_dupes = len(all_discovered) - len(deduplicated)
        if skipped_dupes > 0:
            logger.info("discovery_duplicates_removed", count=skipped_dupes)
        all_discovered = deduplicated

    logger.info(
        "job_discovery_completed",
        total_found=len(seen_ids),
        new_with_descriptions=len(all_discovered),
    )

    return all_discovered


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

    await page.goto(search_url, timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        # Take a screenshot for debugging if the page doesn't settle
        try:
            await page.screenshot(path="data/debug_linkedin_page.png")
            page_title = await page.title()
            current_url = page.url
            logger.warning(
                "job_discovery_page_load_slow",
                title=page_title,
                url=current_url,
                screenshot="data/debug_linkedin_page.png",
            )
        except Exception as ss_exc:
            logger.warning("job_discovery_screenshot_failed", error=str(ss_exc))

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
    "div.jobs-box__html-content",
    "div[class*='description']",
    "article[class*='jobs-description']",
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

            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Give the page a moment to render dynamic content
            await page.wait_for_timeout(3000)

            # Wait for the description to render
            description_text: str | None = None
            for selector in _DESCRIPTION_SELECTORS:
                try:
                    element = await page.query_selector(selector)
                    if element is not None:
                        text = await element.inner_text()
                        if text and len(text.strip()) > 50:
                            description_text = text
                            logger.debug("extraction_selector_matched", selector=selector)
                            break
                except Exception:
                    continue

            # Fallback: try to find any element with substantial text content
            if not description_text:
                logger.debug("extraction_trying_fallback", job_id=job_id)
                # Take a screenshot for debugging
                await page.screenshot(path=f"data/debug_extraction_{job_id}.png")
                # Try broader selectors
                for fallback_sel in ["main", "article", "[role='main']"]:
                    try:
                        el = await page.query_selector(fallback_sel)
                        if el:
                            text = await el.inner_text()
                            if text and len(text.strip()) > 200:
                                description_text = text
                                logger.debug("extraction_fallback_matched", selector=fallback_sel)
                                break
                    except Exception:
                        continue

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
