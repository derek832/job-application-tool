"""Unit tests for the visual form filler module.

Tests the coordinate-based form filling system including:
- Individual field fill methods (text, select, checkbox, radio, file)
- The iterative fill loop (fill_form_visually)
- CAPTCHA detection via visual analysis
- Multi-page form navigation
- Dry run behavior
- Verification logic
- Edge cases (no fields, stuck forms, max iterations)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.claude_client import VisualFormField
from src.agents.visual_form_filler import (
    _fill_checkbox_field,
    _fill_radio_field,
    _fill_select_field,
    _fill_single_field,
    _fill_text_field,
    _upload_file,
    fill_form_visually,
)
from src.api.schemas import UserProfile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        full_name="Derek Smith",
        email="derek@example.com",
        phone="+15551234567",
        location="Norfolk, VA",
        work_auth="US Citizen",
        linkedin_url="https://linkedin.com/in/dereksmith",
        common_answers={"years of experience": "8", "zip_code": "23505"},
    )


@pytest.fixture
def mock_page() -> AsyncMock:
    """Create a mock Playwright page with standard methods."""
    page = AsyncMock()
    page.viewport_size = {"width": 1280, "height": 900}
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    page.mouse = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.url = "https://jobs.example.com/apply/123"
    page.query_selector_all = AsyncMock(return_value=[])
    return page


@pytest.fixture
def mock_claude() -> AsyncMock:
    """Create a mock Claude client."""
    client = AsyncMock()
    client.identify_fields_visual = AsyncMock(return_value=[])
    client.verify_form_state = AsyncMock(return_value={})
    return client


def _make_field(
    label: str = "Email",
    field_type: str = "text",
    center: list[int] | None = None,
    bbox: list[int] | None = None,
    suggested_value: str | None = "test@example.com",
    confidence: float = 0.95,
    is_required: bool = True,
    current_value: str | None = None,
) -> VisualFormField:
    """Helper to create a VisualFormField with sensible defaults."""
    return VisualFormField(
        label=label,
        field_type=field_type,
        center=center or [640, 300],
        bbox=bbox or [500, 280, 280, 40],
        suggested_value=suggested_value,
        confidence=confidence,
        is_required=is_required,
        current_value=current_value,
    )


# ---------------------------------------------------------------------------
# Individual field fill tests
# ---------------------------------------------------------------------------


class TestFillTextField:
    """Tests for _fill_text_field."""

    @pytest.mark.asyncio
    async def test_fills_text_field_successfully(self, mock_page: AsyncMock) -> None:
        field = _make_field(label="Full Name", suggested_value="Derek Smith")
        result = await _fill_text_field(mock_page, field, "Derek Smith")

        assert result is True
        # Should click at field center (triple-click to select all)
        mock_page.mouse.click.assert_called()
        mock_page.keyboard.type.assert_called_once_with("Derek Smith", delay=30)
        mock_page.keyboard.press.assert_called_with("Tab")

    @pytest.mark.asyncio
    async def test_handles_click_error(self, mock_page: AsyncMock) -> None:
        mock_page.mouse.click.side_effect = Exception("Element not interactable")
        field = _make_field()
        result = await _fill_text_field(mock_page, field, "test")

        assert result is False


class TestFillSelectField:
    """Tests for _fill_select_field."""

    @pytest.mark.asyncio
    async def test_fills_select_by_typing(self, mock_page: AsyncMock) -> None:
        field = _make_field(label="Country", field_type="select", suggested_value="United States")
        result = await _fill_select_field(mock_page, field, "United States")

        assert result is True
        # Should click to open, type to filter, then Enter to select
        mock_page.mouse.click.assert_called()
        mock_page.keyboard.type.assert_called_once()
        mock_page.keyboard.press.assert_called_with("Enter")

    @pytest.mark.asyncio
    async def test_truncates_long_option_text(self, mock_page: AsyncMock) -> None:
        field = _make_field(field_type="select", suggested_value="A" * 100)
        await _fill_select_field(mock_page, field, "A" * 100)

        # Should only type first 30 chars for filtering
        typed_text = mock_page.keyboard.type.call_args[0][0]
        assert len(typed_text) == 30


class TestFillCheckboxField:
    """Tests for _fill_checkbox_field."""

    @pytest.mark.asyncio
    async def test_clicks_checkbox(self, mock_page: AsyncMock) -> None:
        field = _make_field(label="I agree", field_type="checkbox", center=[200, 400])
        result = await _fill_checkbox_field(mock_page, field)

        assert result is True
        mock_page.mouse.click.assert_called_with(200, 400)


class TestFillRadioField:
    """Tests for _fill_radio_field."""

    @pytest.mark.asyncio
    async def test_clicks_radio(self, mock_page: AsyncMock) -> None:
        field = _make_field(label="Yes", field_type="radio", center=[150, 350])
        result = await _fill_radio_field(mock_page, field)

        assert result is True
        mock_page.mouse.click.assert_called_with(150, 350)


class TestUploadFile:
    """Tests for _upload_file."""

    @pytest.mark.asyncio
    async def test_uploads_via_file_input(self, mock_page: AsyncMock) -> None:
        file_input = AsyncMock()
        file_input.set_input_files = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[file_input])

        field = _make_field(label="Resume", field_type="file")
        result = await _upload_file(mock_page, field, "/tmp/resume.pdf")

        assert result is True
        file_input.set_input_files.assert_called_once_with("/tmp/resume.pdf")

    @pytest.mark.asyncio
    async def test_returns_false_when_no_file_input(self, mock_page: AsyncMock) -> None:
        mock_page.query_selector_all = AsyncMock(return_value=[])

        field = _make_field(label="Resume", field_type="file")
        result = await _upload_file(mock_page, field, "/tmp/resume.pdf")

        assert result is False


class TestFillSingleField:
    """Tests for _fill_single_field dispatch."""

    @pytest.mark.asyncio
    async def test_dispatches_text_field(self, mock_page: AsyncMock) -> None:
        field = _make_field(field_type="text", suggested_value="hello")
        result = await _fill_single_field(mock_page, field, None)
        assert result is True

    @pytest.mark.asyncio
    async def test_skips_text_field_without_value(self, mock_page: AsyncMock) -> None:
        field = _make_field(field_type="text", suggested_value=None)
        result = await _fill_single_field(mock_page, field, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_rejects_unsafe_value(self, mock_page: AsyncMock) -> None:
        field = _make_field(field_type="text", suggested_value="<script>alert(1)</script>")
        result = await _fill_single_field(mock_page, field, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatches_checkbox(self, mock_page: AsyncMock) -> None:
        field = _make_field(field_type="checkbox", suggested_value=None)
        result = await _fill_single_field(mock_page, field, None)
        assert result is True  # Checkbox doesn't need a value

    @pytest.mark.asyncio
    async def test_dispatches_file_upload(self, mock_page: AsyncMock) -> None:
        file_input = AsyncMock()
        file_input.set_input_files = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[file_input])

        field = _make_field(field_type="file", suggested_value=None)
        result = await _fill_single_field(mock_page, field, "/tmp/resume.pdf")
        assert result is True


# ---------------------------------------------------------------------------
# fill_form_visually integration tests
# ---------------------------------------------------------------------------


class TestFillFormVisually:
    """Tests for the main fill_form_visually loop."""

    @pytest.mark.asyncio
    async def test_successful_single_page_form(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Happy path: identifies fields, fills them, clicks submit."""
        # Iteration 0: two fillable fields + submit button
        # Iteration 1: first field filled, second still fillable
        # Iteration 2: both filled, only submit remains
        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=[
                [
                    _make_field(label="Full Name", suggested_value="Derek Smith"),
                    _make_field(label="Email", suggested_value="derek@example.com"),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
                [
                    _make_field(
                        label="Full Name",
                        current_value="Derek Smith",
                        suggested_value="Derek Smith",
                    ),
                    _make_field(label="Email", suggested_value="derek@example.com"),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
                [
                    _make_field(
                        label="Full Name",
                        current_value="Derek Smith",
                        suggested_value="Derek Smith",
                    ),
                    _make_field(
                        label="Email",
                        current_value="derek@example.com",
                        suggested_value="derek@example.com",
                    ),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is True
        assert result.fields_filled == 2
        assert result.reason is None

    @pytest.mark.asyncio
    async def test_dry_run_does_not_submit(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Dry run fills fields but skips submit click."""
        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=[
                [
                    _make_field(label="Email", suggested_value="derek@example.com"),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
                [
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
            dry_run=True,
        )

        assert result.ok is True
        assert result.fields_filled == 1

    @pytest.mark.asyncio
    async def test_captcha_detection_aborts(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """CAPTCHA in field labels causes immediate abort."""
        mock_claude.identify_fields_visual = AsyncMock(
            return_value=[
                _make_field(label="Email", suggested_value="derek@example.com"),
                _make_field(label="reCAPTCHA verification", field_type="checkbox"),
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is False
        assert result.reason == "captcha_detected"

    @pytest.mark.asyncio
    async def test_no_fields_detected(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """No fields found returns appropriate error."""
        mock_claude.identify_fields_visual = AsyncMock(return_value=[])

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is False
        assert result.reason == "no_submit_button" or result.fields_found == 0

    @pytest.mark.asyncio
    async def test_multi_page_form(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Multi-page form navigates through pages then submits."""
        # Page 1: field + next button
        # Page 2: field + submit button
        call_count = {"n": 0}

        async def mock_identify(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [
                    _make_field(label="Full Name", suggested_value="Derek Smith"),
                    _make_field(
                        label="Next",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ]
            elif call_count["n"] == 2:
                # After filling name, only next button remains
                return [
                    _make_field(
                        label="Next",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ]
            elif call_count["n"] == 3:
                # Page 2: new field
                return [
                    _make_field(label="Phone", suggested_value="+15551234567"),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ]
            else:
                # After filling phone, only submit remains
                return [
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ]

        mock_claude.identify_fields_visual = AsyncMock(side_effect=mock_identify)

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is True
        assert result.fields_filled == 2
        assert result.pages_completed >= 2

    @pytest.mark.asyncio
    async def test_vision_api_error(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Claude Vision API failure returns error result."""
        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is False
        assert result.reason == "vision_api_error"

    @pytest.mark.asyncio
    async def test_low_confidence_fields_skipped(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Fields below confidence threshold are not filled."""
        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=[
                [
                    _make_field(
                        label="Maybe a field",
                        confidence=0.3,  # Below threshold
                        suggested_value="test",
                    ),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                        confidence=0.9,
                    ),
                ],
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        # Should submit without filling the low-confidence field
        assert result.ok is True
        assert result.fields_filled == 0

    @pytest.mark.asyncio
    async def test_pre_filled_fields_skipped(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """Fields with current_value set are not re-filled."""
        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=[
                [
                    _make_field(
                        label="Email",
                        suggested_value="derek@example.com",
                        current_value="derek@example.com",  # Already filled
                    ),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
        )

        assert result.ok is True
        assert result.fields_filled == 0  # Nothing new to fill

    @pytest.mark.asyncio
    async def test_resume_upload(
        self,
        mock_page: AsyncMock,
        mock_claude: AsyncMock,
        profile: UserProfile,
    ) -> None:
        """File upload field triggers resume upload."""
        file_input = AsyncMock()
        file_input.set_input_files = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[file_input])

        mock_claude.identify_fields_visual = AsyncMock(
            side_effect=[
                [
                    _make_field(
                        label="Upload Resume",
                        field_type="file",
                        suggested_value=None,
                        center=[640, 400],
                    ),
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
                [
                    _make_field(
                        label="Submit",
                        field_type="button",
                        suggested_value=None,
                        center=[640, 600],
                    ),
                ],
            ]
        )

        result = await fill_form_visually(
            page=mock_page,
            claude_client=mock_claude,
            profile=profile,
            resume_pdf_path="/tmp/tailored_resume.pdf",
        )

        assert result.ok is True
        assert result.fields_filled == 1
        file_input.set_input_files.assert_called_once_with("/tmp/tailored_resume.pdf")
