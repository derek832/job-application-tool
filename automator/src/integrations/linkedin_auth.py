"""
LinkedIn authentication via Google OAuth sign-in.

Handles the automated login flow:
1. Navigate to LinkedIn login page
2. Click "Sign in with Google"
3. Enter Google email and password
4. Handle any consent screens
5. Verify we land on the LinkedIn feed

If a CAPTCHA or 2FA challenge is detected, raises an exception so the
pipeline can pause and notify the user.
"""

from __future__ import annotations

import os

import structlog
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from src.exceptions import PipelineError

logger = structlog.get_logger(__name__)

_LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
_LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"


async def ensure_linkedin_authenticated(context: BrowserContext, page: Page) -> bool:
    """Ensure the browser context has a valid LinkedIn session.

    Navigates to LinkedIn and checks if already logged in. If not, performs
    the Google OAuth login flow using credentials from environment variables.

    Args:
        context: The Playwright browser context.
        page: An active page to use for navigation.

    Returns:
        True if authentication succeeded or was already active.

    Raises:
        PipelineError: If login fails due to CAPTCHA, 2FA, or invalid credentials.
    """
    email = os.environ.get("LINKEDIN_GOOGLE_EMAIL", "")
    password = os.environ.get("LINKEDIN_GOOGLE_PASSWORD", "")

    if not email or not password:
        logger.warning("linkedin_auth_no_credentials")
        return False

    # Check if already logged in
    logger.info("linkedin_auth_checking_session")
    await page.goto("https://www.linkedin.com/feed/", timeout=30000)

    try:
        await page.wait_for_url("**/feed/**", timeout=10000)
        logger.info("linkedin_auth_already_logged_in")
        return True
    except PlaywrightTimeout:
        pass

    # Not logged in — check if we're on a login page
    current_url = page.url
    logger.info("linkedin_auth_login_required", current_url=current_url)

    # Navigate to login page
    await page.goto(_LINKEDIN_LOGIN_URL, timeout=30000)
    await page.wait_for_load_state("domcontentloaded")

    # Click "Sign in with Google" button
    # Use locator which is more forgiving with text matching
    google_locator = page.locator("button", has_text="Google").first

    try:
        await google_locator.wait_for(timeout=5000)
    except Exception:
        logger.error("linkedin_auth_google_button_not_found")
        await page.screenshot(path="data/debug_login_no_google_btn.png")
        raise PipelineError(
            message="Could not find Google sign-in button on LinkedIn login page",
            job_id=None,
        )

    # Click Google sign-in — this opens a popup or redirects
    try:
        async with context.expect_page(timeout=10000) as popup_info:
            await google_locator.click()
        google_page = await popup_info.value
    except Exception:
        # No popup — might be a redirect instead, use the same page
        google_page = page
        await page.wait_for_timeout(3000)

    await google_page.wait_for_load_state("domcontentloaded")

    # Enter email
    logger.info("linkedin_auth_entering_email")
    try:
        email_input = await google_page.wait_for_selector(
            'input[type="email"]', timeout=15000
        )
        await email_input.fill(email)
        await google_page.click('button:has-text("Next"), #identifierNext')
        await google_page.wait_for_load_state("domcontentloaded")
        await google_page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        await google_page.screenshot(path="data/debug_google_email_timeout.png")
        raise PipelineError(
            message="Timed out waiting for Google email input",
            job_id=None,
        )

    # Enter password
    logger.info("linkedin_auth_entering_password")
    try:
        password_input = await google_page.wait_for_selector(
            'input[type="password"]', timeout=15000
        )
        await password_input.fill(password)
        await google_page.click('button:has-text("Next"), #passwordNext')
        await google_page.wait_for_load_state("domcontentloaded")
        await google_page.wait_for_timeout(3000)
    except PlaywrightTimeout:
        await google_page.screenshot(path="data/debug_google_password_timeout.png")
        raise PipelineError(
            message="Timed out waiting for Google password input",
            job_id=None,
        )

    # Check for 2FA or CAPTCHA on Google
    google_url = google_page.url
    if "challenge" in google_url or "signin/v2/challenge" in google_url:
        await google_page.screenshot(path="data/debug_google_2fa.png")
        raise PipelineError(
            message="Google 2FA challenge detected — manual intervention required",
            job_id=None,
        )

    # Wait for redirect back to LinkedIn
    logger.info("linkedin_auth_waiting_for_redirect")
    try:
        await page.wait_for_url("**/feed/**", timeout=30000)
        logger.info("linkedin_auth_login_successful")
        return True
    except PlaywrightTimeout:
        # Check if there's a LinkedIn security challenge
        current_url = page.url
        page_title = await page.title()
        await page.screenshot(path="data/debug_linkedin_post_login.png")

        if "challenge" in current_url or "checkpoint" in current_url:
            raise PipelineError(
                message=f"LinkedIn security challenge detected: {page_title}",
                job_id=None,
            )

        logger.error(
            "linkedin_auth_redirect_timeout",
            url=current_url,
            title=page_title,
        )
        raise PipelineError(
            message=f"Login redirect timed out. Landed on: {page_title} ({current_url})",
            job_id=None,
        )
