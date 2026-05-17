"""
Property-based tests for notification channel routing.

Uses Hypothesis to verify correctness properties of the determine_channel
function and the notify() routing behavior in src/pipeline/notification_service.py.

Properties tested:
- Property 8: Notification Channel Routing
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.integrations.ntfy_client import NtfyResult, NtfySettings
from src.integrations.sms_gateway import SMSSettings
from src.pipeline.notification_service import (
    NotificationSettings,
    determine_channel,
    notify,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for NtfySettings (always valid when present)
ntfy_settings_strategy = st.builds(
    NtfySettings,
    server_url=st.just("https://ntfy.sh"),
    urgent_topic=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    info_topic=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    lan_base_url=st.one_of(
        st.none(),
        st.just("http://192.168.1.100:7432"),
    ),
    api_token=st.text(
        alphabet=st.characters(categories=("L", "N")),
        min_size=8,
        max_size=32,
    ),
)

# Strategy for SMSSettings (always valid when present)
sms_settings_strategy = st.builds(
    SMSSettings,
    gmail_user=st.just("user@gmail.com"),
    sms_gateway=st.just("5551234567@vtext.com"),
)


# Strategy for NotificationSettings covering all routing scenarios
def notification_settings_strategy():
    """Generate NotificationSettings covering all channel routing cases."""
    return st.one_of(
        # Case 1: ntfy enabled with settings (primary channel)
        st.builds(
            NotificationSettings,
            ntfy_enabled=st.just(True),
            ntfy=ntfy_settings_strategy,
            sms_enabled=st.booleans(),
            sms=st.one_of(st.none(), sms_settings_strategy),
        ),
        # Case 2: ntfy disabled, SMS enabled with settings (fallback)
        st.builds(
            NotificationSettings,
            ntfy_enabled=st.just(False),
            ntfy=st.one_of(st.none(), ntfy_settings_strategy),
            sms_enabled=st.just(True),
            sms=sms_settings_strategy,
        ),
        # Case 3: both disabled or unconfigured
        st.builds(
            NotificationSettings,
            ntfy_enabled=st.just(False),
            ntfy=st.one_of(st.none(), ntfy_settings_strategy),
            sms_enabled=st.just(False),
            sms=st.one_of(st.none(), sms_settings_strategy),
        ),
        # Case 4: ntfy enabled but settings None (edge case — treated as unconfigured)
        st.builds(
            NotificationSettings,
            ntfy_enabled=st.just(True),
            ntfy=st.none(),
            sms_enabled=st.booleans(),
            sms=st.one_of(st.none(), sms_settings_strategy),
        ),
        # Case 5: SMS enabled but settings None (edge case — treated as unconfigured)
        st.builds(
            NotificationSettings,
            ntfy_enabled=st.just(False),
            ntfy=st.none(),
            sms_enabled=st.just(True),
            sms=st.none(),
        ),
    )


# ---------------------------------------------------------------------------
# Property 8: Notification Channel Routing — determine_channel (pure function)
# ---------------------------------------------------------------------------


@given(
    ntfy_enabled=st.booleans(),
    has_ntfy_settings=st.booleans(),
    sms_enabled=st.booleans(),
    has_sms_settings=st.booleans(),
)
@settings(max_examples=200)
def test_determine_channel_routes_to_ntfy_when_enabled(
    ntfy_enabled: bool,
    has_ntfy_settings: bool,
    sms_enabled: bool,
    has_sms_settings: bool,
) -> None:
    """
    For any notification event, the Notification_Service SHALL route to ntfy
    when ntfy is enabled (regardless of SMS configuration), SHALL route to SMS
    when ntfy is disabled and SMS is configured, and SHALL route to neither
    (logging a warning) when both are disabled.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.5**
    """
    # Build settings based on the boolean flags
    ntfy = NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6a7b8",
        info_topic="c9d0e1f2a3b4c5d6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="testtoken123",
    ) if has_ntfy_settings else None

    sms = SMSSettings(
        gmail_user="user@gmail.com",
        sms_gateway="5551234567@vtext.com",
    ) if has_sms_settings else None

    settings_obj = NotificationSettings(
        ntfy_enabled=ntfy_enabled,
        ntfy=ntfy,
        sms_enabled=sms_enabled,
        sms=sms,
    )

    channel = determine_channel(settings_obj)

    # Property assertions based on the routing rules
    if ntfy_enabled and ntfy is not None:
        # Requirement 8.1: ntfy is primary when enabled, regardless of SMS config
        assert channel == "ntfy", (
            f"Expected 'ntfy' when ntfy_enabled={ntfy_enabled} and ntfy settings present, "
            f"but got '{channel}' (sms_enabled={sms_enabled}, has_sms={has_sms_settings})"
        )
    elif sms_enabled and sms is not None:
        # Requirement 8.2: SMS when ntfy disabled and SMS configured
        assert channel == "sms", (
            f"Expected 'sms' when ntfy not available and sms_enabled={sms_enabled} "
            f"with sms settings present, but got '{channel}'"
        )
    else:
        # Requirement 8.3: neither when both disabled
        assert channel == "none", (
            f"Expected 'none' when both channels unavailable, but got '{channel}' "
            f"(ntfy_enabled={ntfy_enabled}, has_ntfy={has_ntfy_settings}, "
            f"sms_enabled={sms_enabled}, has_sms={has_sms_settings})"
        )


# ---------------------------------------------------------------------------
# Property 8 (continued): SMS SHALL NOT be called when ntfy succeeds
# ---------------------------------------------------------------------------


class _FakeJobRecord:
    """Minimal stand-in for JobRecord for notify() testing."""

    def __init__(self, *, id: str, job_title: str, company: str,
                 fit_score: int | None, queue_reason: str | None) -> None:
        self.id = id
        self.job_title = job_title
        self.company = company
        self.fit_score = fit_score
        self.queue_reason = queue_reason


@pytest.mark.asyncio
@given(
    fit_score=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    sms_enabled=st.booleans(),
    has_sms_settings=st.booleans(),
)
@settings(max_examples=50)
async def test_sms_not_called_when_ntfy_succeeds(
    fit_score: int | None,
    sms_enabled: bool,
    has_sms_settings: bool,
) -> None:
    """
    When ntfy is the primary channel and SMS is also configured, SMS SHALL NOT
    be called unless ntfy fails after all retries.

    **Validates: Requirements 8.1, 8.5**
    """
    ntfy_settings = NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6a7b8",
        info_topic="c9d0e1f2a3b4c5d6",
        lan_base_url=None,
        api_token="testtoken123",
    )

    sms = SMSSettings(
        gmail_user="user@gmail.com",
        sms_gateway="5551234567@vtext.com",
    ) if has_sms_settings else None

    settings_obj = NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=sms_enabled,
        sms=sms,
    )

    job = _FakeJobRecord(
        id="12345",
        job_title="Software Engineer",
        company="Acme Corp",
        fit_score=fit_score,
        queue_reason=None,
    )

    mock_session = AsyncMock()
    mock_session.add = AsyncMock()
    mock_session.flush = AsyncMock()

    # Mock ntfy publish to succeed
    with patch(
        "src.pipeline.notification_service.publish",
        new_callable=AsyncMock,
        return_value=NtfyResult(ok=True, status_code=200),
    ) as mock_publish, patch(
        "src.pipeline.notification_service.check_rate_limit",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.pipeline.notification_service.send_sms",
        new_callable=AsyncMock,
    ) as mock_send_sms:
        await notify(mock_session, job, "stretch_role", settings_obj)

        # ntfy should have been called
        mock_publish.assert_called_once()

        # SMS should NOT have been called since ntfy succeeded
        mock_send_sms.assert_not_called()


@pytest.mark.asyncio
@given(
    sms_enabled=st.booleans(),
    has_sms_settings=st.booleans(),
)
@settings(max_examples=50)
async def test_sms_fallback_only_on_ntfy_failure(
    sms_enabled: bool,
    has_sms_settings: bool,
) -> None:
    """
    When ntfy is the primary channel and fails after all retries, SMS SHALL be
    called as fallback only if SMS is enabled and configured.

    **Validates: Requirements 8.5**
    """
    ntfy_settings = NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6a7b8",
        info_topic="c9d0e1f2a3b4c5d6",
        lan_base_url=None,
        api_token="testtoken123",
    )

    sms = SMSSettings(
        gmail_user="user@gmail.com",
        sms_gateway="5551234567@vtext.com",
    ) if has_sms_settings else None

    from src.integrations.sms_gateway import Result as SMSResult

    settings_obj = NotificationSettings(
        ntfy_enabled=True,
        ntfy=ntfy_settings,
        sms_enabled=sms_enabled,
        sms=sms,
    )

    job = _FakeJobRecord(
        id="12345",
        job_title="Software Engineer",
        company="Acme Corp",
        fit_score=85,
        queue_reason=None,
    )

    mock_session = AsyncMock()
    mock_session.add = AsyncMock()
    mock_session.flush = AsyncMock()

    # Mock ntfy publish to FAIL
    with patch(
        "src.pipeline.notification_service.publish",
        new_callable=AsyncMock,
        return_value=NtfyResult(ok=False, error="Server error", status_code=500),
    ), patch(
        "src.pipeline.notification_service.check_rate_limit",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.pipeline.notification_service.send_sms",
        new_callable=AsyncMock,
        return_value=SMSResult(ok=True),
    ) as mock_send_sms:
        await notify(mock_session, job, "stretch_role", settings_obj)

        # SMS should be called as fallback ONLY if sms_enabled and sms settings present
        if sms_enabled and sms is not None:
            mock_send_sms.assert_called_once()
        else:
            mock_send_sms.assert_not_called()
