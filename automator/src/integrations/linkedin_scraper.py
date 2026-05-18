"""LinkedIn job search URL construction and scraping utilities."""

from __future__ import annotations

import asyncio
import json
import random
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


async def _human_delay(min_seconds: float, max_seconds: float) -> None:
    """Sleep for a randomized duration to mimic human browsing behavior."""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


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

    # Time range filter — value is number of days (as string), "0" = any time
    time_range = getattr(config, "time_range", "2") or "2"
    # Support legacy string values and new numeric days
    legacy_map = {"24h": "1", "48h": "2", "week": "7", "month": "30", "any": "0"}
    time_range = legacy_map.get(time_range, time_range)
    try:
        days = int(time_range)
    except ValueError:
        days = 2  # Default to 2 days
    if days > 0:
        params["f_TPR"] = f"r{days * 86400}"
    # days == 0 means "any time" — no f_TPR parameter

    # Sort order
    sort_by = getattr(config, "sort_by", "recent") or "recent"
    if sort_by == "recent":
        params["sortBy"] = "DD"
    # "relevant" = no sortBy parameter (LinkedIn default)

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


async def _extract_company_from_structured_data(page: Page) -> str | None:
    """Extract company name from JSON-LD structured data embedded in the page.

    LinkedIn includes schema.org JobPosting markup for Google Jobs indexing.
    This is far more stable than DOM class names which change with UI redesigns.

    Args:
        page: A Playwright Page object showing a job listing.

    Returns:
        The company name string if found, or None if structured data is unavailable.
    """
    ld_json_els = await page.query_selector_all('script[type="application/ld+json"]')
    for el in ld_json_els:
        try:
            raw = await el.inner_text()
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "JobPosting":
                    org = item.get("hiringOrganization", {})
                    if isinstance(org, dict):
                        name = org.get("name", "").strip()
                        if name:
                            return name
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
    return None


@dataclass
class DiscoveredJob:
    """Job data extracted from the search results page."""

    job_id: str
    title: str
    company: str
    description: str
    linkedin_url: str
    apply_type: str = "easy_apply"  # "easy_apply" or "external_apply"
    external_url: str | None = None


async def discover_and_extract_jobs(
    page: Page,
    config: SearchConfig,
    session: AsyncSession,
    max_pages: int = 5,
    skip_viewed: bool = True,
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
    await _human_delay(3.0, 6.0)

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

                # Skip jobs marked as "Viewed" if the setting is enabled
                if skip_viewed:
                    viewed_indicator = await card.query_selector(
                        "span:has-text('Viewed'), "
                        "li[class*='viewed'], "
                        "span[class*='job-card-container__footer-item']:has-text('Viewed')"
                    )
                    if viewed_indicator:
                        logger.debug("discovery_skipped_viewed", job_id=job_id)
                        continue

                # Click the card to load the description in the right panel
                await card.click()
                await _human_delay(1.5, 4.0)

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

                # Prefer structured data for company name (stable across UI redesigns)
                structured_company = await _extract_company_from_structured_data(page)
                if structured_company:
                    company = structured_company
                    logger.debug(
                        "company_from_structured_data",
                        job_id=job_id,
                        company=company,
                    )
                else:
                    # Fallback: try DOM selectors on the right panel
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

                # Final fallback: try to get company from the card itself
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

                # Detect apply type: Easy Apply vs External
                apply_type = "easy_apply"
                external_url = None

                # LinkedIn shows "Easy Apply" button for in-platform applications
                easy_apply_btn = await page.query_selector(
                    "button.jobs-apply-button--top-card span:has-text('Easy Apply'), "
                    "button[class*='jobs-apply-button'] span.artdeco-button__text, "
                    "button[aria-label*='Easy Apply'], "
                    "span[class*='jobs-apply-button--badge']"
                )

                if easy_apply_btn:
                    btn_text = (await easy_apply_btn.inner_text()).strip().lower()
                    if "easy apply" in btn_text:
                        apply_type = "easy_apply"
                    else:
                        apply_type = "external_apply"
                else:
                    # No Easy Apply badge found — check for external apply link
                    apply_type = "external_apply"

                # Try to extract external URL from the Apply button's link
                if apply_type == "external_apply":
                    ext_link = await page.query_selector(
                        "a[class*='jobs-apply-button'], "
                        "a[data-tracking-control-name*='apply'], "
                        "a.jobs-apply-button--top-card"
                    )
                    if ext_link:
                        external_url = await ext_link.get_attribute("href")

                all_discovered.append(
                    DiscoveredJob(
                        job_id=job_id,
                        title=title,
                        company=company,
                        description=description,
                        linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
                        apply_type=apply_type,
                        external_url=external_url,
                    )
                )

                logger.info(
                    "discovery_job_extracted",
                    job_id=job_id,
                    title=title,
                    company=company,
                    desc_len=len(description),
                    apply_type=apply_type,
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
        existing_records = await session.execute(select(JobRecord.company, JobRecord.job_title))
        existing_combos: set[str] = {
            f"{row.company}|{row.job_title}".lower() for row in existing_records.all()
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

    Scrolls to the bottom of the page first to ensure pagination controls
    are rendered/visible, then looks for a Next button or link.
    Returns True if navigation succeeded, False if no next page is available.

    Args:
        page: The Playwright page currently showing LinkedIn search results.

    Returns:
        True if the page navigated to the next results page, False otherwise.
    """
    # Scroll to the bottom of the page to reveal pagination controls
    # LinkedIn lazy-loads the pagination buttons — they're below the fold
    for _ in range(8):
        await page.evaluate("window.scrollBy(0, 600)")
        await _human_delay(0.3, 0.5)

    # Extra pause for any lazy-loaded pagination to render
    await _human_delay(1.5, 2.5)

    # Try multiple selector strategies for the Next button
    # LinkedIn uses different markup depending on the page variant
    selectors = [
        "button.artdeco-pagination__button--next",
        "button[aria-label='Next']",
        "a[aria-label='Next']",
        "li.artdeco-pagination__indicator--number.active + li button",
        "li.artdeco-pagination__indicator--number.active + li a",
        "button[aria-label='Page forward']",
        ".artdeco-pagination__button--next",
    ]

    next_button = None
    for selector in selectors:
        next_button = await page.query_selector(selector)
        if next_button:
            logger.debug("pagination_button_found", selector=selector)
            break

    if next_button is None:
        # Last resort: look for any pagination container and find a "next" element
        pagination = await page.query_selector(
            ".artdeco-pagination, nav[aria-label='Pagination'], [class*='pagination']"
        )
        if pagination:
            # There IS a pagination container but we can't find the Next button
            # Take a debug screenshot
            try:
                await page.screenshot(path="data/debug_pagination.png")
                logger.warning(
                    "pagination_container_found_but_no_next_button",
                    hint="check data/debug_pagination.png",
                )
            except Exception:
                pass
        else:
            logger.debug("pagination_no_container_found")
        return False

    is_disabled = await next_button.get_attribute("disabled")
    aria_disabled = await next_button.get_attribute("aria-disabled")
    if is_disabled is not None or aria_disabled == "true":
        logger.debug("pagination_next_button_disabled")
        return False

    # Scroll the button into view and click
    await next_button.scroll_into_view_if_needed()
    await _human_delay(0.5, 1.0)
    await next_button.click()
    await page.wait_for_load_state("networkidle")
    await _human_delay(5.0, 12.0)

    # Scroll back to top for the next page's card processing
    await page.evaluate("window.scrollTo(0, 0)")
    await _human_delay(1.0, 2.0)
    return True


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
            await _human_delay(2.0, 4.0)

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


async def mark_as_applied_on_linkedin(page: Page, linkedin_url: str) -> bool:
    """Navigate to a LinkedIn job listing and mark it as applied.

    After a successful external application, this navigates to the LinkedIn
    job page and clicks the "Mark as applied" option so LinkedIn's tracking
    stays in sync with the automator's state.

    Args:
        page: A Playwright Page instance.
        linkedin_url: The LinkedIn job URL to mark.

    Returns:
        True if successfully marked, False otherwise.
    """
    try:
        await page.goto(linkedin_url, timeout=30000)
        await _human_delay(2.0, 4.0)

        # Look for the "..." or overflow menu button on the job page
        overflow_btn = await page.query_selector(
            "button[aria-label*='More actions'], "
            "button[aria-label*='more options'], "
            "button[class*='jobs-save-button'] + button, "
            "button[class*='artdeco-dropdown__trigger']"
        )

        if overflow_btn and await overflow_btn.is_visible():
            await overflow_btn.click()
            await _human_delay(0.5, 1.5)

            # Click "Mark as applied" in the dropdown
            mark_btn = await page.query_selector(
                "div[role='menuitem']:has-text('Mark as applied'), "
                "li:has-text('Mark as applied'), "
                "span:has-text('Mark as applied')"
            )
            if mark_btn:
                await mark_btn.click()
                await _human_delay(1.0, 2.0)
                logger.info("linkedin_marked_as_applied", url=linkedin_url)
                return True

        # Alternative: some pages show a direct "Mark as applied" button
        direct_btn = await page.query_selector("button:has-text('Mark as applied')")
        if direct_btn and await direct_btn.is_visible():
            await direct_btn.click()
            await _human_delay(1.0, 2.0)
            logger.info("linkedin_marked_as_applied", url=linkedin_url)
            return True

        logger.warning("linkedin_mark_applied_button_not_found", url=linkedin_url)
        return False

    except Exception as exc:
        logger.warning("linkedin_mark_applied_failed", url=linkedin_url, error=str(exc))
        return False
