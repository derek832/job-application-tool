"""Unit tests for the notification composer module."""

from __future__ import annotations

import pytest

from src.db.models import JobRecord
from src.integrations.ntfy_client import NtfySettings
from src.pipeline.notification_composer import compose_info_payload, compose_urgent_payload


@pytest.fixture
def ntfy_settings() -> NtfySettings:
    """Fixture providing test NtfySettings with LAN configured."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6g7h8",
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="test-token-abc123",
    )


@pytest.fixture
def ntfy_settings_no_lan() -> NtfySettings:
    """Fixture providing test NtfySettings without LAN configured."""
    return NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic="a1b2c3d4e5f6g7h8",
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url=None,
        api_token="test-token-abc123",
    )


@pytest.fixture
def job_with_queue_reason() -> JobRecord:
    """Fixture providing a job record with a queue_reason set."""
    return JobRecord(
        id="3987654321",
        job_title="Senior Engineer",
        company="Acme Corp",
        location="Remote",
        linkedin_url="https://linkedin.com/jobs/view/3987654321",
        apply_type="easy_apply",
        status="queued",
        fit_score=85,
        queue_reason="stretch_role",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )


@pytest.fixture
def job_without_queue_reason() -> JobRecord:
    """Fixture providing a job record without a queue_reason."""
    return JobRecord(
        id="1234567890",
        job_title="Data Analyst",
        company="BigCo",
        location="NYC",
        linkedin_url="https://linkedin.com/jobs/view/1234567890",
        apply_type="easy_apply",
        status="scored",
        fit_score=72,
        queue_reason=None,
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )


@pytest.fixture
def job_no_score() -> JobRecord:
    """Fixture providing a job record without a fit_score."""
    return JobRecord(
        id="5555555555",
        job_title="Product Manager",
        company="StartupXYZ",
        location="SF",
        linkedin_url="https://linkedin.com/jobs/view/5555555555",
        apply_type="external_apply",
        status="discovered",
        fit_score=None,
        queue_reason="captcha_detected",
        discovered_at="2024-01-15T09:00:00+00:00",
        updated_at="2024-01-15T09:00:00+00:00",
    )


class TestComposeUrgentPayload:
    """Tests for compose_urgent_payload."""

    def test_message_includes_job_title_and_company(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Message contains job title and company name."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert "Senior Engineer" in payload.message
        assert "Acme Corp" in payload.message

    def test_message_includes_fit_score_when_available(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Message includes fit score in parentheses when present."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert "(85%)" in payload.message

    def test_message_omits_fit_score_when_none(
        self, job_no_score: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Message omits score portion when fit_score is None."""
        payload = compose_urgent_payload(job_no_score, "captcha_detected", ntfy_settings)
        assert "%" not in payload.message
        assert "None" not in payload.message

    def test_message_includes_trigger_reason(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Message contains the trigger reason."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert "stretch_role" in payload.message

    def test_message_format(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Message follows the expected format: '{title} @ {company} ({score}%): {reason}'."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.message == "Senior Engineer @ Acme Corp (85%): stretch_role"

    def test_priority_is_4(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Urgent payload has priority 4 (high)."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.priority == 4

    def test_title_is_job_automator(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Urgent payload title is 'Job Automator'."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.title == "Job Automator"

    def test_tags_contain_briefcase(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Urgent payload tags include 'briefcase'."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.tags == ["briefcase"]

    def test_topic_is_urgent_topic(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Urgent payload uses the urgent_topic from settings."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.topic == "a1b2c3d4e5f6g7h8"

    def test_action_buttons_when_queue_reason_and_lan_configured(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Action buttons are included when queue_reason is set AND lan_base_url is configured."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        assert len(payload.actions) == 2

    def test_approve_action_button_url(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Approve button URL is {lan_base_url}/queue/{job_id}/approve."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        approve = payload.actions[0]
        assert approve.label == "Approve"
        assert approve.url == "http://192.168.1.100:7432/queue/3987654321/approve"
        assert approve.method == "POST"
        assert approve.action == "http"

    def test_reject_action_button_url(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Reject button URL is {lan_base_url}/queue/{job_id}/reject."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        reject = payload.actions[1]
        assert reject.label == "Reject"
        assert reject.url == "http://192.168.1.100:7432/queue/3987654321/reject"
        assert reject.method == "POST"
        assert reject.action == "http"

    def test_action_buttons_include_bearer_token(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Action buttons include Authorization header with bearer token."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        for action in payload.actions:
            assert action.headers == {"Authorization": "Bearer test-token-abc123"}

    def test_no_action_buttons_when_no_queue_reason(
        self, job_without_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """No action buttons when queue_reason is None (even with LAN configured)."""
        payload = compose_urgent_payload(
            job_without_queue_reason, "high_score", ntfy_settings
        )
        assert payload.actions is None

    def test_no_action_buttons_when_no_lan_url(
        self, job_with_queue_reason: JobRecord, ntfy_settings_no_lan: NtfySettings
    ) -> None:
        """No action buttons when lan_base_url is None (even with queue_reason set)."""
        payload = compose_urgent_payload(
            job_with_queue_reason, "stretch_role", ntfy_settings_no_lan
        )
        assert payload.actions is None


class TestComposeInfoPayload:
    """Tests for compose_info_payload."""

    def test_message_is_summary_text(self, ntfy_settings: NtfySettings) -> None:
        """Info payload message is the provided summary text."""
        text = "Run complete: found 12 jobs, scored 10, applied to 3. No errors."
        payload = compose_info_payload(text, ntfy_settings)
        assert payload.message == text

    def test_priority_is_3(self, ntfy_settings: NtfySettings) -> None:
        """Info payload has priority 3 (default)."""
        payload = compose_info_payload("summary", ntfy_settings)
        assert payload.priority == 3

    def test_title_is_job_automator(self, ntfy_settings: NtfySettings) -> None:
        """Info payload title is 'Job Automator'."""
        payload = compose_info_payload("summary", ntfy_settings)
        assert payload.title == "Job Automator"

    def test_tags_contain_chart(self, ntfy_settings: NtfySettings) -> None:
        """Info payload tags include 'chart_with_upwards_trend'."""
        payload = compose_info_payload("summary", ntfy_settings)
        assert payload.tags == ["chart_with_upwards_trend"]

    def test_topic_is_info_topic(self, ntfy_settings: NtfySettings) -> None:
        """Info payload uses the info_topic from settings."""
        payload = compose_info_payload("summary", ntfy_settings)
        assert payload.topic == "i9j0k1l2m3n4o5p6"

    def test_no_action_buttons(self, ntfy_settings: NtfySettings) -> None:
        """Info payload never includes action buttons."""
        payload = compose_info_payload("summary", ntfy_settings)
        assert payload.actions is None
