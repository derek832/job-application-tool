"""ATS account registration and login handling.

Detects registration/login pages, creates accounts, handles email verification,
and manages stored credentials for external ATS platforms.
"""

from __future__ import annotations

import asyncio
import base64
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse

import structlog
from googleapiclient.discovery import build as build_google_service
from playwright.async_api import Frame, Page
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ATSAccount
from src.integrations.gmail_oauth import load_credentials

logger = structlog.get_logger(__name__)

# Common registration/login page indicators
_REGISTRATION_INDICATORS: list[str] = [
    "create an account",
    "create account",
    "sign up",
    "register",
    "new user",
    "don't have an account",
]

_LOGIN_INDICATORS: list[str] = [
    "sign in",
    "log in",
    "login",
    "already have an account",
    "returning user",
]

_GOOGLE_OAUTH_INDICATORS: list[str] = [
    "sign in with google",
    "continue with google",
    "log in with google",
]


def _extract_domain(url: str) -> str:
    """Extract the base domain from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.hostname or ""
    # Remove www. prefix
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


async def get_stored_account(
    session: AsyncSession,
    domain: str,
    email: str,
) -> ATSAccount | None:
    """Look up stored credentials for an ATS domain.

    Args:
        session: Active async database session.
        domain: The ATS domain to look up.
        email: The email to match.

    Returns:
        The ATSAccount if found, or None.
    """
    result = await session.execute(
        select(ATSAccount).where(
            ATSAccount.domain == domain,
            ATSAccount.email == email,
        )
    )
    return result.scalar_one_or_none()


async def store_account(
    session: AsyncSession,
    domain: str,
    email: str,
    password: str | None,
    auth_method: str = "password",
    notes: str | None = None,
) -> ATSAccount:
    """Store new ATS account credentials.

    Args:
        session: Active async database session.
        domain: The ATS domain.
        email: The email used to register.
        password: The generated password (None for OAuth).
        auth_method: Either 'password' or 'google_oauth'.
        notes: Optional notes about the registration.

    Returns:
        The created ATSAccount record.
    """
    account = ATSAccount(
        domain=domain,
        email=email,
        password=password,
        auth_method=auth_method,
        created_at=datetime.now(UTC).isoformat(),
        notes=notes,
    )
    session.add(account)
    await session.flush()
    logger.info("ats_account_stored", domain=domain, auth_method=auth_method)
    return account


def detect_page_type(page_text: str, url: str = "") -> str:
    """Detect whether the current page is a login, registration, or application form.

    Uses contextual analysis to avoid false positives from navigation elements.
    A page with job application content (Apply buttons, job descriptions) is
    classified as 'form' even if "Sign In" appears in the navigation bar.

    Args:
        page_text: The visible text content of the page.
        url: Optional page URL for additional signal (e.g., /login in path).

    Returns:
        One of: 'registration', 'login', 'google_oauth', 'form'
    """
    lower = page_text.lower()

    # If the page has strong application/job indicators, it's a form page
    # regardless of nav elements like "Sign In"
    application_indicators = [
        "apply for this job",
        "apply now",
        "submit application",
        "upload resume",
        "upload your resume",
    ]
    for indicator in application_indicators:
        if indicator in lower:
            return "form"

    # Check for Google OAuth first (highest priority — easiest path)
    for indicator in _GOOGLE_OAUTH_INDICATORS:
        if indicator in lower:
            return "google_oauth"

    # Check for registration page — require stronger signals
    # "register" alone is too broad (e.g., "register for updates")
    # Look for registration-specific context
    for indicator in _REGISTRATION_INDICATORS:
        if indicator in lower:
            # Verify it's actually a registration page by checking for
            # password/email fields context nearby
            if any(
                ctx in lower
                for ctx in ["password", "confirm password", "email address", "create your"]
            ):
                return "registration"
            # If "create account" or "sign up" appears prominently (not just in nav),
            # check that it's not just a nav link by looking for form context
            if indicator in ("create an account", "create account", "sign up"):
                return "registration"

    # Check for login page — require password field context to avoid
    # false positives from "Sign In" navigation buttons
    login_found = False
    for indicator in _LOGIN_INDICATORS:
        if indicator in lower:
            login_found = True
            break

    if login_found:
        # Only classify as login if there's evidence of a login FORM
        # (password field, email field, or the page is primarily about signing in)
        login_form_indicators = [
            "password",
            "forgot password",
            "reset password",
            "remember me",
            "enter your email",
            "enter your credentials",
            "username",
        ]
        for form_indicator in login_form_indicators:
            if form_indicator in lower:
                return "login"

        # If "sign in" appears but no form indicators, it's likely just a nav button
        # Check if the page has substantial content (job description, etc.)
        if len(lower) > 500:
            # Long page with "sign in" but no password fields = likely a job page
            # with a nav "Sign In" button
            return "form"
        else:
            # Short page with login indicators = likely a login page
            return "login"

    # Fall back to URL pattern detection when text analysis is inconclusive
    if url:
        url_lower = url.lower()
        if "/register" in url_lower or "/signup" in url_lower or "/create-account" in url_lower:
            return "registration"
        if "/login" in url_lower or "/signin" in url_lower:
            return "login"

    return "form"


async def handle_google_oauth(page: Page | Frame) -> bool:
    """Click the 'Sign in with Google' button.

    Since the user is already logged into Google in their Chrome session,
    this should complete automatically without additional credentials.

    Args:
        page: The Playwright page.

    Returns:
        True if OAuth flow completed successfully.
    """
    oauth_selectors = [
        "button:has-text('Sign in with Google')",
        "button:has-text('Continue with Google')",
        "a:has-text('Sign in with Google')",
        "a:has-text('Continue with Google')",
        "[data-provider='google']",
        "button[class*='google']",
        "a[class*='google']",
    ]

    for selector in oauth_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                logger.info("clicking_google_oauth", selector=selector)
                await btn.click()
                # Wait for OAuth redirect to complete
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                return True
        except Exception:
            continue

    return False


async def handle_registration(
    page: Page | Frame,
    email: str,
    full_name: str | None = None,
) -> tuple[bool, str | None]:
    """Fill and submit a registration form.

    Generates a secure password and fills the registration form fields.

    Args:
        page: The Playwright page showing the registration form.
        email: The email to register with.
        full_name: The user's full name for name fields.

    Returns:
        Tuple of (success, generated_password). Password is None on failure.
    """
    password = secrets.token_urlsafe(16)

    # Extract form fields from the DOM
    from src.agents.vision_agent import _extract_dom_fields

    fields = await _extract_dom_fields(page)

    filled_any = False
    for field in fields:
        if not field.get("selector"):
            continue

        label_lower = field["label"].lower()
        value = None

        if "email" in label_lower:
            value = email
        elif "password" in label_lower and "confirm" not in label_lower:
            value = password
        elif "confirm" in label_lower and "password" in label_lower:
            value = password
        elif "name" in label_lower:
            if full_name:
                if "first" in label_lower:
                    value = full_name.split(None, 1)[0]
                elif "last" in label_lower:
                    parts = full_name.split(None, 1)
                    value = parts[1] if len(parts) > 1 else ""
                else:
                    value = full_name

        if value:
            try:
                await page.fill(field["selector"], value, timeout=5000)
                filled_any = True
                logger.debug("registration_field_filled", label=field["label"])
            except Exception as exc:
                logger.debug("registration_field_skip", label=field["label"], error=str(exc))

    if not filled_any:
        logger.warning("registration_no_fields_filled")
        return False, None

    # Check any consent/privacy/terms checkboxes (required for many ATS sites)
    consent_keywords = ["consent", "privacy", "terms", "agree", "accept", "i have read"]
    try:
        checkboxes = await page.query_selector_all("input[type='checkbox']")
        for checkbox in checkboxes:
            try:
                is_checked = await checkbox.is_checked()
                if is_checked:
                    continue
                # Check if this checkbox is related to consent/privacy
                label_el = None
                cb_id = await checkbox.get_attribute("id")
                if cb_id:
                    label_el = await page.query_selector(f"label[for='{cb_id}']")
                if not label_el:
                    label_el = await checkbox.evaluate_handle("el => el.closest('label')")
                label_text = ""
                if label_el:
                    label_text = await label_el.inner_text()
                label_lower = label_text.lower()
                cb_name = (await checkbox.get_attribute("name") or "").lower()

                if any(kw in label_lower or kw in cb_name for kw in consent_keywords):
                    await checkbox.check()
                    logger.debug("registration_checkbox_checked", label=label_text[:50])
            except Exception:
                continue
    except Exception:
        pass

    # Submit the registration form
    submit_selectors = [
        "button[type='submit']",
        "button:has-text('Create Account')",
        "button:has-text('Sign Up')",
        "button:has-text('Register')",
        "button:has-text('Submit')",
        "input[type='submit']",
    ]

    for selector in submit_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                logger.info("registration_submitted")
                return True, password
        except Exception:
            continue

    logger.warning("registration_no_submit_button")
    return False, None


async def handle_login(
    page: Page | Frame,
    email: str,
    password: str,
) -> bool:
    """Fill and submit a login form with stored credentials.

    Args:
        page: The Playwright page showing the login form.
        email: The email to log in with.
        password: The stored password.

    Returns:
        True if login form was submitted.
    """
    fields = []
    try:
        from src.agents.vision_agent import _extract_dom_fields

        fields = await _extract_dom_fields(page)
    except Exception:
        pass

    for field in fields:
        if not field.get("selector"):
            continue
        label_lower = field["label"].lower()

        if "email" in label_lower or "username" in label_lower:
            try:
                await page.fill(field["selector"], email, timeout=5000)
            except Exception:
                pass
        elif "password" in label_lower:
            try:
                await page.fill(field["selector"], password, timeout=5000)
            except Exception:
                pass

    # Submit
    submit_selectors = [
        "button[type='submit']",
        "button:has-text('Sign In')",
        "button:has-text('Log In')",
        "button:has-text('Login')",
        "input[type='submit']",
    ]

    for selector in submit_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                logger.info("login_submitted")
                return True
        except Exception:
            continue

    return False


async def wait_for_verification_email(
    email_address: str,
    domain: str,
    timeout_seconds: int = 60,
) -> str | None:
    """Poll Gmail API for a verification email and extract the verification link.

    Args:
        email_address: The email to check for verification messages.
        domain: The ATS domain to filter emails from.
        timeout_seconds: How long to wait for the email.

    Returns:
        The verification URL if found, or None.
    """
    creds = load_credentials()
    if creds is None:
        logger.error("gmail_credentials_not_available")
        return None

    service = build_google_service("gmail", "v1", credentials=creds, cache_discovery=False)

    start_time = asyncio.get_event_loop().time()
    poll_interval = 5

    while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
        try:
            # Search for recent emails from the ATS domain
            query = f"from:{domain} newer_than:5m (verify OR confirm OR activate)"
            results = service.users().messages().list(userId="me", q=query, maxResults=5).execute()

            messages = results.get("messages", [])
            for msg_meta in messages:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="full")
                    .execute()
                )

                # Extract links from the email body
                payload = msg.get("payload", {})
                body_data = ""

                # Check parts for HTML content
                parts = payload.get("parts", [])
                if parts:
                    for part in parts:
                        if part.get("mimeType") == "text/html":
                            data = part.get("body", {}).get("data", "")
                            body_data = base64.urlsafe_b64decode(data).decode("utf-8")
                            break
                else:
                    data = payload.get("body", {}).get("data", "")
                    if data:
                        body_data = base64.urlsafe_b64decode(data).decode("utf-8")

                if body_data:
                    # Find verification links
                    urls = re.findall(
                        r'href="(https?://[^"]*(?:verify|confirm|activate)[^"]*)"', body_data
                    )
                    if urls:
                        logger.info("verification_link_found", url=urls[0][:80])
                        return urls[0]

        except Exception as exc:
            logger.warning("gmail_poll_error", error=str(exc))

        await asyncio.sleep(poll_interval)

    logger.warning("verification_email_timeout", domain=domain, timeout=timeout_seconds)
    return None
