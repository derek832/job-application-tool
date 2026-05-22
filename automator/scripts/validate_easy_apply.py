"""Validation script: Run Easy Apply pipeline against a LinkedIn Easy Apply job.

This script is used for iterative ATS validation (Task 2.1).
It connects to Chrome via CDP, finds an Easy Apply job from the search URL,
and runs the Easy Apply pipeline against it.
"""

import asyncio
import os
import sys

import structlog

# Ensure src is importable
sys.path.insert(0, "/app")

logger = structlog.get_logger(__name__)


async def main() -> None:
    """Run the Easy Apply validation."""
    from datetime import UTC, datetime

    from playwright.async_api import async_playwright

    from src.api.schemas import UserProfile
    from src.db.config_repo import get_config
    from src.db.database import build_engine, get_session

    # Initialize the database engine
    build_engine()

    # Step 1: Load user profile from DB
    session = None
    async for s in get_session():
        session = s
        break

    if session is None:
        print("ERROR: Could not get database session")
        return

    user_profile_raw = await get_config(session, "user_profile")
    if not user_profile_raw:
        print("ERROR: No user_profile configured in database")
        return

    user_profile = UserProfile.model_validate(user_profile_raw)
    print(f"Loaded profile: {user_profile.full_name} ({user_profile.email})")

    # Step 2: Connect to Chrome via CDP
    cdp_url = os.environ.get("CHROME_CDP_URL", "http://host.docker.internal:9222")
    print(f"Connecting to Chrome at: {cdp_url}")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        print("Connected to Chrome successfully")

        # Step 3: Navigate to LinkedIn Easy Apply search
        search_url = (
            "https://www.linkedin.com/jobs/search/"
            "?keywords=software+engineer"
            "&location=United+States"
            "&f_AL=true"
            "&f_TPR=r172800"
            "&sortBy=DD"
        )
        print(f"Navigating to search URL: {search_url}")
        await page.goto(search_url, timeout=30000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)  # Let results load

        # Step 4: Find the first Easy Apply job in results
        # LinkedIn job cards in search results
        job_cards = await page.query_selector_all(
            'div.job-card-container, li.jobs-search-results__list-item'
        )
        print(f"Found {len(job_cards)} job cards in search results")

        if not job_cards:
            # Try alternative selectors
            job_cards = await page.query_selector_all(
                'ul.jobs-search__results-list li, '
                'div[data-job-id]'
            )
            print(f"Alternative selector found {len(job_cards)} job cards")

        if not job_cards:
            # Take a screenshot for debugging
            await page.screenshot(path="/app/data/debug_easy_apply_search.png")
            print("ERROR: No job cards found. Screenshot saved to data/debug_easy_apply_search.png")
            # Print page content snippet for diagnosis
            content = await page.content()
            print(f"Page title: {await page.title()}")
            print(f"Page URL: {page.url}")
            print(f"Content length: {len(content)}")
            await page.close()
            return

        # Click the first job card to open the job details
        first_card = job_cards[0]
        await first_card.click()
        await asyncio.sleep(2)

        # Get the job URL from the current page or the job detail panel
        job_url = page.url
        print(f"Selected job URL: {job_url}")

        # Extract job title and company from the detail panel
        title_el = await page.query_selector(
            'h1.job-details-jobs-unified-top-card__job-title, '
            'h2.jobs-unified-top-card__job-title, '
            'h1.t-24'
        )
        company_el = await page.query_selector(
            'div.job-details-jobs-unified-top-card__company-name a, '
            'a.jobs-unified-top-card__company-name, '
            'span.jobs-unified-top-card__company-name'
        )

        job_title = (await title_el.inner_text()).strip() if title_el else "Unknown Title"
        company = (await company_el.inner_text()).strip() if company_el else "Unknown Company"
        print(f"Job: {job_title} at {company}")

        # Step 5: Create a mock JobRecord for the Easy Apply stage
        from src.db.models import JobRecord

        job_record = JobRecord(
            id=f"validation_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            job_title=job_title,
            company=company,
            linkedin_url=job_url,
            apply_type="easy_apply",
            status="approved_for_apply",
            discovered_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            tailored_resume_pdf=None,  # No resume for validation
        )

        # Step 6: Run the Easy Apply stage
        from src.agents.claude_client import ClaudeClient
        from src.pipeline.easy_apply_stage import run_easy_apply

        # Get Claude API key from settings
        settings_raw = await get_config(session, "settings")
        claude_api_key = settings_raw.get("claude_api_key", "") if settings_raw else ""

        claude_client = None
        if claude_api_key and claude_api_key != "***":
            claude_client = ClaudeClient(api_key=claude_api_key)
            print("Claude client initialized")
        else:
            print("WARNING: No Claude API key configured, cover letter generation will be skipped")

        print(f"\n{'='*60}")
        print(f"RUNNING EASY APPLY VALIDATION")
        print(f"Job: {job_title} at {company}")
        print(f"URL: {job_url}")
        print(f"{'='*60}\n")

        try:
            await run_easy_apply(
                job_record=job_record,
                profile=user_profile,
                session=session,
                page=page,
                claude_client=claude_client,
            )
            print(f"\nFinal job status: {job_record.status}")
            if job_record.status == "applied":
                logger.info(
                    "easy_apply_submitted",
                    job_id=job_record.id,
                    job_title=job_title,
                    company=company,
                    validation="PASSED",
                )
                print("✓ VALIDATION PASSED: easy_apply_submitted")
            else:
                print(f"✗ VALIDATION INCOMPLETE: status={job_record.status}")
                if job_record.error_message:
                    print(f"  Error: {job_record.error_message}")
                if job_record.queue_reason:
                    print(f"  Queue reason: {job_record.queue_reason}")
        except Exception as exc:
            print(f"✗ VALIDATION FAILED: {exc}")
            logger.error("easy_apply_validation_failed", error=str(exc))
            # Take screenshot on failure
            try:
                await page.screenshot(path="/app/data/debug_easy_apply_failure.png")
                print("  Screenshot saved to data/debug_easy_apply_failure.png")
            except Exception:
                pass

        await page.close()

    except Exception as exc:
        print(f"ERROR: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        await pw.stop()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
