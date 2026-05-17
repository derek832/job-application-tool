"""
Property-based tests for health check failure notification specificity.

Uses Hypothesis to verify that any session health check failure produces
an error_message that identifies the specific component that failed —
never a generic "health check failed" without component identification.

Properties tested:
- Property 5: Health Check Failure Notification Specificity
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.health_checker import HealthCheckResult, check_session_health


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for CDP URLs (various valid URL formats)
cdp_url_strategy = st.sampled_from([
    "http://host.docker.internal:9222",
    "http://localhost:9222",
    "http://127.0.0.1:9222",
    "http://192.168.1.100:9222",
])

# Strategy for HTTP error exceptions that make Chrome unreachable
chrome_error_strategy = st.sampled_from([
    "ConnectionRefusedError",
    "ConnectTimeout",
    "NetworkError",
    "Connection reset by peer",
    "No route to host",
])

# Strategy for LinkedIn redirect URLs (indicating expired session)
linkedin_redirect_url_strategy = st.sampled_from([
    "https://www.linkedin.com/login",
    "https://www.linkedin.com/authwall",
    "https://www.linkedin.com/login?fromSignIn=true",
    "https://www.linkedin.com/authwall?trk=bf&trkInfo=abc",
    "https://www.linkedin.com/uas/login",
])

# Strategy for Playwright connection errors
playwright_error_strategy = st.sampled_from([
    "Browser closed unexpectedly",
    "Connection refused",
    "Target page, context or browser has been closed",
    "Protocol error: Connection closed",
    "net::ERR_CONNECTION_REFUSED",
    "Timeout 10000ms exceeded",
])

# Strategy for failure scenarios
failure_scenario_strategy = st.sampled_from([
    "chrome_unreachable",
    "linkedin_redirect",
    "playwright_error",
])


# ---------------------------------------------------------------------------
# Property 5: Health Check Failure Notification Specificity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@given(
    cdp_url=cdp_url_strategy,
    scenario=failure_scenario_strategy,
    error_detail=st.text(
        alphabet=st.characters(categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=80,
    ),
)
@settings(max_examples=150)
async def test_health_check_failure_message_identifies_specific_component(
    cdp_url: str,
    scenario: str,
    error_detail: str,
) -> None:
    """
    For any session health check that fails, the notification message (error_message
    field in HealthCheckResult) shall contain the specific failure reason — either
    "Chrome" (when CDP is unreachable) or "LinkedIn session expired" (when a login
    redirect is detected). The message shall never be a generic "health check failed"
    without identifying which component failed.

    **Validates: Requirements 2.4, 2.9**
    """
    import httpx
    from playwright.async_api import Error as PlaywrightError

    if scenario == "chrome_unreachable":
        # Mock Chrome CDP as unreachable
        with patch(
            "src.pipeline.health_checker._check_chrome_reachable",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await check_session_health(cdp_url)

    elif scenario == "linkedin_redirect":
        # Mock Chrome as reachable but LinkedIn redirects to login
        with patch(
            "src.pipeline.health_checker._check_chrome_reachable",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "src.pipeline.health_checker._check_linkedin_session",
            new_callable=AsyncMock,
            return_value=(False, "LinkedIn session expired — please log in to Chrome"),
        ):
            result = await check_session_health(cdp_url)

    elif scenario == "playwright_error":
        # Mock Chrome as reachable but Playwright connection fails
        with patch(
            "src.pipeline.health_checker._check_chrome_reachable",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "src.pipeline.health_checker._check_linkedin_session",
            new_callable=AsyncMock,
            return_value=(False, f"LinkedIn session check failed: {error_detail}"),
        ):
            result = await check_session_health(cdp_url)

    else:
        pytest.fail(f"Unknown scenario: {scenario}")

    # The result must indicate a failure
    assert not (result.chrome_reachable and result.linkedin_authenticated), (
        f"Expected a failure scenario but got healthy result: "
        f"chrome_reachable={result.chrome_reachable}, "
        f"linkedin_authenticated={result.linkedin_authenticated}"
    )

    # The error_message must be present for any failure
    assert result.error_message is not None, (
        f"Failed health check must have a non-None error_message. "
        f"Scenario: {scenario}, chrome_reachable={result.chrome_reachable}, "
        f"linkedin_authenticated={result.linkedin_authenticated}"
    )

    # PROPERTY: The error_message must identify the specific component that failed.
    # It must contain "Chrome" OR "LinkedIn" — never just a generic message.
    error_lower = result.error_message.lower()
    contains_chrome = "chrome" in error_lower
    contains_linkedin = "linkedin" in error_lower

    assert contains_chrome or contains_linkedin, (
        f"Health check failure message must identify the specific component "
        f"('Chrome' or 'LinkedIn'), but got: '{result.error_message}'. "
        f"Scenario: {scenario}"
    )

    # PROPERTY: The message must never be just a generic "health check failed"
    # without specifying which component.
    generic_messages = [
        "health check failed",
        "check failed",
        "session check failed",
    ]
    # If the message matches a generic pattern, it must ALSO contain a component name
    for generic in generic_messages:
        if generic in error_lower:
            assert contains_chrome or contains_linkedin, (
                f"Error message contains generic '{generic}' without identifying "
                f"the specific component. Message: '{result.error_message}'"
            )


@pytest.mark.asyncio
@given(cdp_url=cdp_url_strategy)
@settings(max_examples=100)
async def test_chrome_unreachable_message_mentions_chrome(
    cdp_url: str,
) -> None:
    """
    When Chrome CDP is unreachable, the error_message shall specifically mention
    "Chrome" to identify the failed component.

    **Validates: Requirements 2.4, 2.9**
    """
    with patch(
        "src.pipeline.health_checker._check_chrome_reachable",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await check_session_health(cdp_url)

    assert result.chrome_reachable is False
    assert result.error_message is not None
    assert "chrome" in result.error_message.lower(), (
        f"When Chrome is unreachable, error_message must mention 'Chrome'. "
        f"Got: '{result.error_message}'"
    )


@pytest.mark.asyncio
@given(cdp_url=cdp_url_strategy)
@settings(max_examples=100)
async def test_linkedin_expired_message_mentions_linkedin(
    cdp_url: str,
) -> None:
    """
    When LinkedIn session is expired (login redirect detected), the error_message
    shall specifically mention "LinkedIn session expired".

    **Validates: Requirements 2.4, 2.9**
    """
    with patch(
        "src.pipeline.health_checker._check_chrome_reachable",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.pipeline.health_checker._check_linkedin_session",
        new_callable=AsyncMock,
        return_value=(False, "LinkedIn session expired — please log in to Chrome"),
    ):
        result = await check_session_health(cdp_url)

    assert result.chrome_reachable is True
    assert result.linkedin_authenticated is False
    assert result.error_message is not None
    assert "linkedin session expired" in result.error_message.lower(), (
        f"When LinkedIn session is expired, error_message must mention "
        f"'LinkedIn session expired'. Got: '{result.error_message}'"
    )
