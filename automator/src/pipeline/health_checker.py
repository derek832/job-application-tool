"""Session health checker for verifying Chrome CDP and LinkedIn session.

Performs a two-step health check before pipeline runs:
1. HTTP GET to Chrome's /json/version endpoint to verify CDP is reachable.
2. Playwright CDP connection to navigate to linkedin.com/feed and detect login redirects.

The entire check is bounded by a 15-second timeout.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog
from playwright.async_api import async_playwright

logger = structlog.get_logger(__name__)

# Overall timeout for the entire health check (seconds).
HEALTH_CHECK_TIMEOUT_SECONDS = 15


@dataclass
class HealthCheckResult:
    """Structured result of a session health check.

    Attributes:
        chrome_reachable: Whether Chrome CDP responded to /json/version.
        linkedin_authenticated: Whether LinkedIn did not redirect to a login page.
        error_message: Human-readable error description, or None if healthy.
        checked_at: ISO 8601 timestamp of when the check was performed.
    """

    chrome_reachable: bool
    linkedin_authenticated: bool
    error_message: str | None
    checked_at: str  # ISO 8601


async def check_session_health(cdp_url: str) -> HealthCheckResult:
    """Verify Chrome CDP and LinkedIn session are healthy.

    Steps:
        1. HTTP GET to {cdp_url}/json/version — verifies Chrome is running.
        2. Connect via Playwright CDP, navigate to linkedin.com/feed.
        3. Check final URL — if redirected to login page, session is expired.

    The entire operation is bounded by a 15-second timeout.

    Args:
        cdp_url: The base CDP URL (e.g., "http://host.docker.internal:9222").

    Returns:
        A HealthCheckResult with the status of each check.
    """
    checked_at = datetime.now(UTC).isoformat()

    try:
        result = await asyncio.wait_for(
            _perform_health_check(cdp_url, checked_at),
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        return result
    except TimeoutError:
        logger.error("health_check_timeout", timeout_seconds=HEALTH_CHECK_TIMEOUT_SECONDS)
        return HealthCheckResult(
            chrome_reachable=False,
            linkedin_authenticated=False,
            error_message=f"Health check timed out after {HEALTH_CHECK_TIMEOUT_SECONDS} seconds",
            checked_at=checked_at,
        )


async def _perform_health_check(cdp_url: str, checked_at: str) -> HealthCheckResult:
    """Internal implementation of the health check without timeout wrapper.

    Args:
        cdp_url: The base CDP URL.
        checked_at: ISO 8601 timestamp for the result.

    Returns:
        A HealthCheckResult with the status of each check.
    """
    # Step 1: Verify Chrome is reachable via /json/version
    chrome_reachable = await _check_chrome_reachable(cdp_url)
    if not chrome_reachable:
        return HealthCheckResult(
            chrome_reachable=False,
            linkedin_authenticated=False,
            error_message="Chrome CDP is not reachable",
            checked_at=checked_at,
        )

    # Step 2: Check LinkedIn session via Playwright CDP
    linkedin_authenticated, error_message = await _check_linkedin_session(cdp_url)

    return HealthCheckResult(
        chrome_reachable=True,
        linkedin_authenticated=linkedin_authenticated,
        error_message=error_message,
        checked_at=checked_at,
    )


async def _check_chrome_reachable(cdp_url: str) -> bool:
    """HTTP GET to {cdp_url}/json/version to verify Chrome is running.

    Args:
        cdp_url: The base CDP URL.

    Returns:
        True if Chrome responded with a 200 status, False otherwise.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cdp_url}/json/version", timeout=5.0)
            if resp.status_code == 200:
                logger.info("health_check_chrome_reachable", cdp_url=cdp_url)
                return True
            else:
                logger.warning(
                    "health_check_chrome_unexpected_status",
                    status_code=resp.status_code,
                )
                return False
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("health_check_chrome_unreachable", error=str(exc)[:100])
        return False


async def _check_linkedin_session(cdp_url: str) -> tuple[bool, str | None]:
    """Connect via Playwright CDP, navigate to linkedin.com/feed, check for login redirect.

    Args:
        cdp_url: The base CDP URL for Playwright to connect to.

    Returns:
        A tuple of (is_authenticated, error_message).
        If authenticated, error_message is None.
        If not authenticated, error_message describes the issue.
    """
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                try:
                    await page.goto(
                        "https://www.linkedin.com/feed",
                        wait_until="domcontentloaded",
                        timeout=10000,
                    )
                    final_url = page.url.lower()

                    if "login" in final_url or "authwall" in final_url:
                        logger.warning(
                            "health_check_linkedin_session_expired",
                            final_url=page.url,
                        )
                        return (
                            False,
                            "LinkedIn session expired — please log in to Chrome",
                        )

                    logger.info("health_check_linkedin_authenticated", final_url=page.url)
                    return True, None
                finally:
                    await page.close()
            finally:
                await browser.close()
    except Exception as exc:
        error_msg = f"LinkedIn session check failed: {str(exc)[:100]}"
        logger.error("health_check_linkedin_error", error=str(exc)[:100])
        return False, error_msg
