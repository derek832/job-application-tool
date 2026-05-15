"""Unit tests for the Vision Agent module.

Tests sanitization, field mapping, CAPTCHA detection, and the core
process_external_apply flow using mocked Playwright and Claude client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.claude_client import FormField
from src.agents.vision_agent import (
    _is_captcha_field,
    map_fields_to_profile,
    process_external_apply,
    sanitize_value,
)
from src.api.schemas import UserProfile
from src.db.models import JobRecord

# ---------------------------------------------------------------------------
# sanitize_value tests
# ---------------------------------------------------------------------------


class TestSanitizeValue:
    """Tests for the sanitize_value function."""

    def test_strips_whitespace(self) -> None:
        assert sanitize_value("  hello  ") == "hello"

    def test_truncates_to_500_chars(self) -> None:
        long_value = "a" * 600
        result = sanitize_value(long_value)
        assert result is not None
        assert len(result) == 500

    def test_rejects_script_tag(self) -> None:
        assert sanitize_value("<script>alert('xss')</script>") is None

    def test_rejects_script_tag_case_insensitive(self) -> None:
        assert sanitize_value("<SCRIPT>alert('xss')</SCRIPT>") is None

    def test_rejects_javascript_protocol(self) -> None:
        assert sanitize_value("javascript:alert(1)") is None

    def test_rejects_javascript_protocol_case_insensitive(self) -> None:
        assert sanitize_value("JAVASCRIPT:void(0)") is None

    def test_rejects_drop_table(self) -> None:
        assert sanitize_value("'; DROP TABLE users; --") is None

    def test_rejects_insert_into(self) -> None:
        assert sanitize_value("INSERT INTO users VALUES ('hack')") is None

    def test_rejects_delete_from(self) -> None:
        assert sanitize_value("DELETE FROM job_records") is None

    def test_rejects_union_select(self) -> None:
        assert sanitize_value("' UNION SELECT * FROM passwords --") is None

    def test_rejects_select_from(self) -> None:
        assert sanitize_value("SELECT password FROM users") is None

    def test_rejects_update_set(self) -> None:
        assert sanitize_value("UPDATE users SET admin=1") is None

    def test_allows_normal_text(self) -> None:
        assert sanitize_value("John Doe") == "John Doe"

    def test_allows_email(self) -> None:
        assert sanitize_value("john@example.com") == "john@example.com"

    def test_allows_phone(self) -> None:
        assert sanitize_value("+1 (555) 123-4567") == "+1 (555) 123-4567"

    def test_allows_url(self) -> None:
        url = "https://linkedin.com/in/johndoe"
        assert sanitize_value(url) == url

    def test_empty_string(self) -> None:
        assert sanitize_value("") == ""

    def test_whitespace_only(self) -> None:
        assert sanitize_value("   ") == ""


# ---------------------------------------------------------------------------
# map_fields_to_profile tests
# ---------------------------------------------------------------------------


class TestMapFieldsToProfile:
    """Tests for the map_fields_to_profile function."""

    @pytest.fixture
    def profile(self) -> UserProfile:
        return UserProfile(
            full_name="John Doe",
            email="john@example.com",
            phone="+15551234567",
            location="New York, NY",
            work_auth="US Citizen",
            linkedin_url="https://linkedin.com/in/johndoe",
            common_answers={"years of experience": "5"},
        )

    def test_maps_known_fields(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Full Name", field_type="text"),
            FormField(field_id="f2", label="Email", field_type="text"),
            FormField(field_id="f3", label="Phone", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=80000)
        assert mapped == {
            "f1": "John Doe",
            "f2": "john@example.com",
            "f3": "+15551234567",
        }
        assert unmapped == []
        assert salary_missing is False

    def test_uses_suggested_value_when_available(self, profile: UserProfile) -> None:
        fields = [
            FormField(
                field_id="f1", label="Full Name", field_type="text", suggested_value="Jane Smith"
            ),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert mapped == {"f1": "Jane Smith"}
        assert unmapped == []

    def test_salary_field_with_min_salary(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Salary Expectation", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=90000)
        assert mapped == {"f1": "90000"}
        assert salary_missing is False

    def test_salary_field_without_min_salary(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Salary Expectation", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert "f1" not in mapped
        assert salary_missing is True

    def test_unrecognized_field(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Favorite Color", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert mapped == {}
        assert len(unmapped) == 1
        assert unmapped[0].label == "Favorite Color"

    def test_common_answers_match(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Years of Experience", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert mapped == {"f1": "5"}
        assert unmapped == []

    def test_maps_location_variants(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="City", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert mapped == {"f1": "New York, NY"}

    def test_maps_work_auth_variants(self, profile: UserProfile) -> None:
        fields = [
            FormField(field_id="f1", label="Work Authorization", field_type="text"),
        ]
        mapped, unmapped, salary_missing = map_fields_to_profile(fields, profile, min_salary=None)
        assert mapped == {"f1": "US Citizen"}


# ---------------------------------------------------------------------------
# _is_captcha_field tests
# ---------------------------------------------------------------------------


class TestIsCaptchaField:
    """Tests for CAPTCHA detection."""

    def test_detects_captcha_in_label(self) -> None:
        field = FormField(field_id="f1", label="Complete the CAPTCHA", field_type="text")
        assert _is_captcha_field(field) is True

    def test_detects_recaptcha_in_label(self) -> None:
        field = FormField(field_id="f1", label="reCAPTCHA verification", field_type="text")
        assert _is_captcha_field(field) is True

    def test_detects_captcha_in_field_id(self) -> None:
        field = FormField(field_id="recaptcha_widget", label="Verify", field_type="text")
        assert _is_captcha_field(field) is True

    def test_detects_not_a_robot(self) -> None:
        field = FormField(field_id="f1", label="I'm not a robot", field_type="checkbox")
        assert _is_captcha_field(field) is True

    def test_normal_field_not_captcha(self) -> None:
        field = FormField(field_id="email", label="Email Address", field_type="text")
        assert _is_captcha_field(field) is False


# ---------------------------------------------------------------------------
# process_external_apply tests
# ---------------------------------------------------------------------------


class TestProcessExternalApply:
    """Tests for the process_external_apply function."""

    @pytest.fixture
    def job_record(self) -> JobRecord:
        record = JobRecord(
            id="12345",
            job_title="Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/12345",
            external_url="https://acme.com/apply/12345",
            apply_type="external_apply",
            status="approved_for_apply",
            discovered_at="2024-01-15T09:00:00Z",
            updated_at="2024-01-15T09:00:00Z",
        )
        return record

    @pytest.fixture
    def profile(self) -> UserProfile:
        return UserProfile(
            full_name="John Doe",
            email="john@example.com",
            phone="+15551234567",
            location="New York, NY",
            work_auth="US Citizen",
            linkedin_url="https://linkedin.com/in/johndoe",
        )

    @pytest.fixture
    def mock_page(self) -> AsyncMock:
        page = AsyncMock(
            spec=["goto", "screenshot", "fill", "query_selector", "wait_for_load_state"]
        )
        page.goto = AsyncMock()
        page.screenshot = AsyncMock(return_value=b"fake_screenshot_bytes")
        page.fill = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.wait_for_load_state = AsyncMock()
        return page

    @pytest.fixture
    def mock_claude(self) -> AsyncMock:
        client = AsyncMock()
        client.identify_form_fields = AsyncMock(
            return_value=[
                FormField(field_id="name", label="Full Name", field_type="text"),
                FormField(field_id="email", label="Email", field_type="text"),
            ]
        )
        return client

    @pytest.mark.asyncio
    async def test_successful_single_page_apply(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        # Set up submit button
        submit_btn = AsyncMock()
        submit_btn.click = AsyncMock()

        # First query_selector call for "Next" returns None, second for "Submit" returns button
        mock_page.query_selector = AsyncMock(side_effect=[None, submit_btn])

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
            min_salary=80000,
        )

        assert result.ok is True
        assert result.error is None
        mock_page.goto.assert_called_once()
        mock_page.screenshot.assert_called_once()
        mock_claude.identify_form_fields.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_external_url(
        self,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        record = JobRecord(
            id="12345",
            job_title="Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/12345",
            external_url=None,
            apply_type="external_apply",
            status="approved_for_apply",
            discovered_at="2024-01-15T09:00:00Z",
            updated_at="2024-01-15T09:00:00Z",
        )

        result = await process_external_apply(
            job_record=record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "no_external_url"

    @pytest.mark.asyncio
    async def test_captcha_detected(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        mock_claude.identify_form_fields.return_value = [
            FormField(field_id="recaptcha", label="Complete the CAPTCHA", field_type="checkbox"),
            FormField(field_id="email", label="Email", field_type="text"),
        ]

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "captcha_detected"

    @pytest.mark.asyncio
    async def test_unrecognized_field_escalation(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        mock_claude.identify_form_fields.return_value = [
            FormField(field_id="f1", label="Email", field_type="text"),
            FormField(field_id="f2", label="Favorite Programming Language", field_type="text"),
        ]

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "unrecognized_field"

    @pytest.mark.asyncio
    async def test_salary_missing_escalation(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        mock_claude.identify_form_fields.return_value = [
            FormField(field_id="f1", label="Email", field_type="text"),
            FormField(field_id="f2", label="Salary Expectation", field_type="text"),
        ]

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
            min_salary=None,
        )

        assert result.ok is False
        assert result.reason == "salary_missing"

    @pytest.mark.asyncio
    async def test_too_many_pages_escalation(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        mock_claude.identify_form_fields.return_value = [
            FormField(field_id="email", label="Email", field_type="text"),
        ]

        # Simulate a "Next" button always present (multi-page form)
        next_btn = AsyncMock()
        next_btn.click = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=next_btn)

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "too_many_pages"

    @pytest.mark.asyncio
    async def test_navigation_failure(
        self,
        job_record: JobRecord,
        profile: UserProfile,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        mock_page.goto.side_effect = Exception("Timeout")

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "navigation_failed"

    @pytest.mark.asyncio
    async def test_unsafe_value_rejected(
        self,
        job_record: JobRecord,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
    ) -> None:
        # Profile with a malicious value
        profile = UserProfile(
            full_name="<script>alert('xss')</script>",
            email="john@example.com",
            phone="+15551234567",
            location="New York, NY",
        )

        mock_claude.identify_form_fields.return_value = [
            FormField(field_id="name", label="Full Name", field_type="text"),
        ]
        mock_page.query_selector = AsyncMock(return_value=None)

        result = await process_external_apply(
            job_record=job_record,
            profile=profile,
            page=mock_page,
            claude_client=mock_claude,
        )

        assert result.ok is False
        assert result.reason == "unsafe_value"
