"""Unit tests for the notification composer module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.db.models import JobRecord
from src.integrations.ntfy_client import NtfySettings
from src.pipeline.escalation_engine import FreshnessTier
from src.pipeline.notification_composer import (
    compose_escalation_notification,
    compose_info_payload,
    compose_urgent_payload,
)


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
        """Approve button URL is a view action with token in query params."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        approve = payload.actions[0]
        assert approve.label == "Approve"
        assert "ntfy-action" in approve.url
        assert "action=approve" in approve.url
        assert "job_id=3987654321" in approve.url
        assert "token=test-token-abc123" in approve.url
        assert approve.action == "view"

    def test_reject_action_button_url(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Reject button URL is a view action with token in query params."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        reject = payload.actions[1]
        assert reject.label == "Reject"
        assert "ntfy-action" in reject.url
        assert "action=reject" in reject.url
        assert "job_id=3987654321" in reject.url
        assert "token=test-token-abc123" in reject.url
        assert reject.action == "view"

    def test_action_buttons_have_empty_headers(
        self, job_with_queue_reason: JobRecord, ntfy_settings: NtfySettings
    ) -> None:
        """Action buttons have empty headers (token is in URL query param)."""
        payload = compose_urgent_payload(job_with_queue_reason, "stretch_role", ntfy_settings)
        assert payload.actions is not None
        for action in payload.actions:
            assert action.headers == {}

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


class TestComposeEscalationNotification:
    """Tests for compose_escalation_notification."""

    @pytest.fixture
    def captcha_job(self) -> JobRecord:
        """Job record for a CAPTCHA escalation scenario."""
        return JobRecord(
            id="9876543210",
            job_title="Backend Developer",
            company="TechCorp",
            location="Remote",
            linkedin_url="https://linkedin.com/jobs/view/9876543210",
            external_url="https://boards.greenhouse.io/techcorp/jobs/456",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            queue_reason=None,
            discovered_at="2024-01-15T09:00:00+00:00",
            updated_at="2024-01-15T09:00:00+00:00",
        )

    @pytest.fixture
    def review_job(self) -> JobRecord:
        """Job record for a human_review escalation scenario."""
        return JobRecord(
            id="1111111111",
            job_title="Staff Engineer",
            company="BigTech Inc",
            location="NYC",
            linkedin_url="https://linkedin.com/jobs/view/1111111111",
            external_url="https://jobs.lever.co/bigtech/abc123",
            apply_type="external_apply",
            status="applying",
            fit_score=92,
            queue_reason=None,
            discovered_at="2024-01-15T09:00:00+00:00",
            updated_at="2024-01-15T09:00:00+00:00",
        )

    # --- CAPTCHA tier tests ---

    def test_captcha_priority_is_4(self, captcha_job: JobRecord) -> None:
        """CAPTCHA escalation notifications have priority 4 (high)."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert payload.priority == 4

    def test_captcha_title_includes_company(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification title includes the company name."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert payload.title == "CAPTCHA Required — TechCorp"

    def test_captcha_body_includes_job_title(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification body includes the job title."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert "Backend Developer" in payload.message

    def test_captcha_body_includes_ats_domain(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification body includes the ATS domain."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert "boards.greenhouse.io" in payload.message

    def test_captcha_body_includes_solve_instruction(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification body includes the solve instruction."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert "Solve CAPTCHA in Chrome to continue" in payload.message

    def test_captcha_body_format(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification body follows expected format."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        expected = "Backend Developer on boards.greenhouse.io\nSolve CAPTCHA in Chrome to continue"
        assert payload.message == expected

    def test_captcha_has_review_action_button(self, captcha_job: JobRecord) -> None:
        """CAPTCHA notification includes a Review action button."""
        payload = compose_escalation_notification(
            job_record=captcha_job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-123",
        )
        assert payload.actions is not None
        assert len(payload.actions) == 1
        assert payload.actions[0].label == "Review"
        assert payload.actions[0].url == "http://localhost:3000/escalations/esc-123"
        assert payload.actions[0].action == "view"

    # --- human_review tier tests ---

    def test_human_review_priority_is_3(self, review_job: JobRecord) -> None:
        """human_review escalation notifications have priority 3 (default)."""
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=2,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert payload.priority == 3

    def test_human_review_title_includes_company(self, review_job: JobRecord) -> None:
        """human_review notification title includes the company name."""
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=2,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert payload.title == "Review Required — BigTech Inc"

    def test_human_review_body_includes_job_title_and_fit_score(
        self, review_job: JobRecord
    ) -> None:
        """human_review notification body includes job title and fit score."""
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=2,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "Staff Engineer (fit: 92)" in payload.message

    def test_human_review_body_includes_open_ended_count(
        self, review_job: JobRecord
    ) -> None:
        """human_review notification body includes the open-ended question count."""
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=3,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "3 open-ended questions" in payload.message

    def test_human_review_body_includes_freshness_tier(
        self, review_job: JobRecord
    ) -> None:
        """human_review notification body includes the freshness tier label."""
        deadline = datetime.now(tz=UTC) + timedelta(hours=6)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.RECENT,
            timeout_deadline=deadline,
            open_ended_count=1,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "recent posting" in payload.message

    def test_human_review_body_includes_relative_deadline(
        self, review_job: JobRecord
    ) -> None:
        """human_review notification body includes the relative timeout deadline."""
        # Add a small buffer to ensure we get exactly 45 min
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45, seconds=30)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=2,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "auto-submits in 45 min" in payload.message

    def test_human_review_body_hours_deadline(self, review_job: JobRecord) -> None:
        """human_review notification formats hours correctly for longer deadlines."""
        deadline = datetime.now(tz=UTC) + timedelta(hours=6, seconds=30)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.RECENT,
            timeout_deadline=deadline,
            open_ended_count=1,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "auto-submits in 6 hrs" in payload.message

    def test_human_review_has_review_action_button(self, review_job: JobRecord) -> None:
        """human_review notification includes a Review action button."""
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.FRESH,
            timeout_deadline=deadline,
            open_ended_count=2,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert payload.actions is not None
        assert len(payload.actions) == 1
        assert payload.actions[0].label == "Review"
        assert payload.actions[0].url == "http://localhost:3000/escalations/esc-456"
        assert payload.actions[0].action == "view"

    def test_human_review_stale_freshness(self, review_job: JobRecord) -> None:
        """human_review notification correctly shows stale freshness tier."""
        deadline = datetime.now(tz=UTC) + timedelta(hours=24, seconds=30)
        payload = compose_escalation_notification(
            job_record=review_job,
            tier="human_review",
            freshness=FreshnessTier.STALE,
            timeout_deadline=deadline,
            open_ended_count=1,
            review_url="http://localhost:3000/escalations/esc-456",
        )
        assert "stale posting" in payload.message
        assert "auto-submits in 24 hrs" in payload.message

    def test_captcha_no_external_url(self) -> None:
        """CAPTCHA notification handles missing external_url gracefully."""
        job = JobRecord(
            id="2222222222",
            job_title="Designer",
            company="DesignCo",
            location="Remote",
            linkedin_url="https://linkedin.com/jobs/view/2222222222",
            external_url=None,
            apply_type="external_apply",
            status="applying",
            fit_score=88,
            queue_reason=None,
            discovered_at="2024-01-15T09:00:00+00:00",
            updated_at="2024-01-15T09:00:00+00:00",
        )
        payload = compose_escalation_notification(
            job_record=job,
            tier="captcha",
            freshness=None,
            timeout_deadline=None,
            open_ended_count=0,
            review_url="http://localhost:3000/escalations/esc-789",
        )
        # Should not crash, domain will be empty
        assert "Designer" in payload.message
        assert "Solve CAPTCHA in Chrome to continue" in payload.message
