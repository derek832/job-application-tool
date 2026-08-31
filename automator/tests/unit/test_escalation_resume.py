"""Unit tests for the escalation resume module.

Tests cover:
- resume_from_escalation dispatch logic for each resolution method
- _resume_from_captcha: page accessibility checks
- _resume_with_answers: navigation, structure verification, fill, submit
- _mark_expired: escalation and job status transitions
- _verify_form_structure: field matching logic
- Error handling for all failure modes

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import EscalationRecord
from src.pipeline.escalation_resume import (
    ResumeResult,
    _mark_expired,
    _resume_from_captcha,
    _submit_form,
    _verify_form_structure,
    resume_from_escalation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_escalation_record(
    *,
    resolution_method: str = "user_submit",
    tier: str = "human_review",
    form_state_snapshot: dict | None = None,
    draft_answers: list[dict] | None = None,
) -> EscalationRecord:
    """Create a mock EscalationRecord for testing."""
    if form_state_snapshot is None:
        form_state_snapshot = {
            "external_url": "https://boards.greenhouse.io/acme/jobs/123",
            "fields": [
                {
                    "field_id": "field_1",
                    "label": "Full Name",
                    "value": "Alex Smith",
                    "type": "text",
                    "selector": "#first_name",
                },
                {
                    "field_id": "field_5",
                    "label": "Why are you interested?",
                    "value": "",
                    "type": "textarea",
                    "selector": "#custom_question_1",
                    "is_open_ended": True,
                },
            ],
            "screenshot_path": "/data/screenshots/esc_abc.png",
            "page_title": "Apply - Senior Engineer at Acme Corp",
        }

    if draft_answers is None:
        draft_answers = [
            {
                "field_id": "field_5",
                "question_text": "Why are you interested?",
                "draft_answer": "I am drawn to Acme's mission...",
                "edited_answer": "I love Acme because...",
            }
        ]

    record = MagicMock(spec=EscalationRecord)
    record.id = "esc-test-123"
    record.job_id = "job-456"
    record.tier = tier
    record.form_state_snapshot = json.dumps(form_state_snapshot)
    record.draft_answers = json.dumps(draft_answers)
    record.status = "resolved"
    record.resolution_method = resolution_method
    record.created_at = datetime.now(tz=UTC).isoformat()
    record.resolved_at = datetime.now(tz=UTC).isoformat()
    return record


def _make_mock_page(
    *,
    page_text: str = "Application Form - Submit your details",
    url: str = "https://boards.greenhouse.io/acme/jobs/123",
    goto_status: int = 200,
    goto_raises: Exception | None = None,
    evaluate_result: list[dict] | None = None,
) -> AsyncMock:
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.url = url

    # page.inner_text("body")
    page.inner_text = AsyncMock(return_value=page_text)

    # page.wait_for_load_state
    page.wait_for_load_state = AsyncMock()

    # page.goto
    if goto_raises:
        page.goto = AsyncMock(side_effect=goto_raises)
    else:
        mock_response = MagicMock()
        mock_response.status = goto_status
        page.goto = AsyncMock(return_value=mock_response)

    # page.evaluate (for field extraction)
    if evaluate_result is None:
        evaluate_result = [
            {"selector": "#first_name", "label": "Full Name", "type": "text"},
            {
                "selector": "#custom_question_1",
                "label": "Why are you interested?",
                "type": "textarea",
            },
        ]
    page.evaluate = AsyncMock(return_value=evaluate_result)

    # page.fill
    page.fill = AsyncMock()

    # page.select_option
    page.select_option = AsyncMock()

    # page.query_selector
    mock_button = AsyncMock()
    mock_button.is_visible = AsyncMock(return_value=True)
    mock_button.scroll_into_view_if_needed = AsyncMock()
    mock_button.click = AsyncMock()
    page.query_selector = AsyncMock(return_value=mock_button)

    # page.keyboard
    page.keyboard = AsyncMock()
    page.keyboard.type = AsyncMock()

    return page


# ---------------------------------------------------------------------------
# ResumeResult
# ---------------------------------------------------------------------------


class TestResumeResult:
    """Tests for the ResumeResult dataclass."""

    def test_success_result(self) -> None:
        result = ResumeResult(ok=True)
        assert result.ok is True
        assert result.error is None
        assert result.reason is None

    def test_failure_result(self) -> None:
        result = ResumeResult(ok=False, error="Page expired", reason="page_load_failed")
        assert result.ok is False
        assert result.error == "Page expired"
        assert result.reason == "page_load_failed"


# ---------------------------------------------------------------------------
# resume_from_escalation — dispatch logic
# ---------------------------------------------------------------------------


class TestResumeFromEscalation:
    """Tests for the main resume_from_escalation dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatches_captcha_solved(self) -> None:
        """CAPTCHA resolution dispatches to _resume_from_captcha."""
        record = _make_escalation_record(resolution_method="captcha_solved", tier="captcha")
        page = _make_mock_page()
        session = AsyncMock()

        result = await resume_from_escalation(session, record, page)

        assert result.ok is True
        # Should have checked page load state
        page.wait_for_load_state.assert_called()

    @pytest.mark.asyncio
    async def test_dispatches_user_submit(self) -> None:
        """User submit resolution navigates and fills with edited answers."""
        record = _make_escalation_record(resolution_method="user_submit")
        page = _make_mock_page()
        session = AsyncMock()

        result = await resume_from_escalation(session, record, page)

        assert result.ok is True
        # Should have navigated to the external URL
        page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_auto_submit(self) -> None:
        """Auto-submit resolution navigates and fills with draft answers."""
        record = _make_escalation_record(resolution_method="auto_submit")
        page = _make_mock_page()
        session = AsyncMock()

        result = await resume_from_escalation(session, record, page)

        assert result.ok is True
        page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_resolution_method_marks_expired(self) -> None:
        """Unknown resolution method marks escalation as expired."""
        record = _make_escalation_record(resolution_method="unknown_method")
        page = _make_mock_page()
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "unknown_resolution"
        assert record.status == "expired"

    @pytest.mark.asyncio
    async def test_unexpected_exception_marks_expired(self) -> None:
        """Unexpected exceptions are caught and mark escalation as expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        page = _make_mock_page()
        session = AsyncMock()

        # Force an unexpected exception by patching json.loads to raise RuntimeError
        with (
            patch(
                "src.pipeline.escalation_resume.json.loads",
                side_effect=RuntimeError("DB crash"),
            ),
            patch(
                "src.pipeline.escalation_resume.update_job_status",
                new_callable=AsyncMock,
            ),
        ):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "resume_error"
        assert record.status == "expired"


# ---------------------------------------------------------------------------
# _resume_from_captcha
# ---------------------------------------------------------------------------


class TestResumeFromCaptcha:
    """Tests for CAPTCHA resume handler."""

    @pytest.mark.asyncio
    async def test_success_when_page_accessible(self) -> None:
        """Returns success when page is accessible with content."""
        page = _make_mock_page(page_text="Application form with fields")
        import structlog

        log = structlog.get_logger()

        result = await _resume_from_captcha(page, log)

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_failure_when_page_empty(self) -> None:
        """Returns failure when page has no content."""
        page = _make_mock_page(page_text="")
        import structlog

        log = structlog.get_logger()

        result = await _resume_from_captcha(page, log)

        assert result.ok is False
        assert result.reason == "page_empty"

    @pytest.mark.asyncio
    async def test_failure_when_page_not_accessible(self) -> None:
        """Returns failure when page throws an exception."""
        page = _make_mock_page()
        page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("Page timeout"))
        import structlog

        log = structlog.get_logger()

        result = await _resume_from_captcha(page, log)

        assert result.ok is False
        assert result.reason == "page_not_accessible"


# ---------------------------------------------------------------------------
# _resume_with_answers — navigation failures
# ---------------------------------------------------------------------------


class TestResumeWithAnswersNavigation:
    """Tests for navigation error handling in _resume_with_answers."""

    @pytest.mark.asyncio
    async def test_navigation_exception_marks_expired(self) -> None:
        """Navigation exception marks escalation expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        page = _make_mock_page(goto_raises=TimeoutError("Connection timeout"))
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "navigation_failed"
        assert record.status == "expired"
        assert record.resolution_method == "form_expired"

    @pytest.mark.asyncio
    async def test_http_error_status_marks_expired(self) -> None:
        """HTTP 404/500 response marks escalation expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        page = _make_mock_page(goto_status=404)
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "page_load_failed"
        assert record.status == "expired"

    @pytest.mark.asyncio
    async def test_no_external_url_marks_expired(self) -> None:
        """Missing external_url in snapshot marks escalation expired."""
        snapshot = {"fields": [], "screenshot_path": None, "page_title": "Test"}
        record = _make_escalation_record(
            resolution_method="user_submit",
            form_state_snapshot=snapshot,
        )
        page = _make_mock_page()
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "no_external_url"

    @pytest.mark.asyncio
    async def test_invalid_snapshot_json_marks_expired(self) -> None:
        """Invalid JSON in form_state_snapshot marks escalation expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        record.form_state_snapshot = "not valid json {"
        page = _make_mock_page()
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "snapshot_invalid"


# ---------------------------------------------------------------------------
# _resume_with_answers — form structure mismatch
# ---------------------------------------------------------------------------


class TestResumeWithAnswersStructure:
    """Tests for form structure verification."""

    @pytest.mark.asyncio
    async def test_structure_mismatch_marks_expired(self) -> None:
        """Form structure mismatch marks escalation expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        # Page returns completely different fields
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#totally_different", "label": "Unrelated Field", "type": "text"},
            ]
        )
        session = AsyncMock()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            result = await resume_from_escalation(session, record, page)

        assert result.ok is False
        assert result.reason == "structure_mismatch"
        assert record.status == "expired"


# ---------------------------------------------------------------------------
# _resume_with_answers — answer selection
# ---------------------------------------------------------------------------


class TestResumeWithAnswersSelection:
    """Tests for correct answer selection (edited vs draft)."""

    @pytest.mark.asyncio
    async def test_user_submit_uses_edited_answers(self) -> None:
        """User submit resolution uses edited_answer from draft_answers."""
        draft_answers = [
            {
                "field_id": "field_5",
                "question_text": "Why?",
                "draft_answer": "Original draft",
                "edited_answer": "User edited version",
            }
        ]
        snapshot = {
            "external_url": "https://example.com/apply",
            "fields": [
                {
                    "field_id": "field_5",
                    "label": "Why?",
                    "value": "",
                    "type": "textarea",
                    "selector": "#q1",
                },
            ],
        }
        record = _make_escalation_record(
            resolution_method="user_submit",
            form_state_snapshot=snapshot,
            draft_answers=draft_answers,
        )
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#q1", "label": "Why?", "type": "textarea"},
            ]
        )
        session = AsyncMock()

        result = await resume_from_escalation(session, record, page)

        assert result.ok is True
        # Verify the edited answer was used in fill
        fill_calls = page.fill.call_args_list
        # Should have filled with "User edited version" (after clearing)
        filled_values = [call.args[1] for call in fill_calls if call.args[1]]
        assert "User edited version" in filled_values

    @pytest.mark.asyncio
    async def test_auto_submit_uses_draft_answers(self) -> None:
        """Auto-submit resolution uses draft_answer (not edited)."""
        draft_answers = [
            {
                "field_id": "field_5",
                "question_text": "Why?",
                "draft_answer": "Original draft",
                "edited_answer": "User edited version",
            }
        ]
        snapshot = {
            "external_url": "https://example.com/apply",
            "fields": [
                {
                    "field_id": "field_5",
                    "label": "Why?",
                    "value": "",
                    "type": "textarea",
                    "selector": "#q1",
                },
            ],
        }
        record = _make_escalation_record(
            resolution_method="auto_submit",
            form_state_snapshot=snapshot,
            draft_answers=draft_answers,
        )
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#q1", "label": "Why?", "type": "textarea"},
            ]
        )
        session = AsyncMock()

        result = await resume_from_escalation(session, record, page)

        assert result.ok is True
        # Verify the original draft was used
        fill_calls = page.fill.call_args_list
        filled_values = [call.args[1] for call in fill_calls if call.args[1]]
        assert "Original draft" in filled_values


# ---------------------------------------------------------------------------
# _verify_form_structure
# ---------------------------------------------------------------------------


class TestVerifyFormStructure:
    """Tests for form structure verification logic."""

    @pytest.mark.asyncio
    async def test_empty_snapshot_fields_returns_true(self) -> None:
        """No fields in snapshot means we can't verify — assume OK."""
        page = _make_mock_page()
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, [], log)
        assert result is True

    @pytest.mark.asyncio
    async def test_matching_selectors_returns_true(self) -> None:
        """When page has matching selectors, returns True."""
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#name", "label": "Name", "type": "text"},
                {"selector": "#email", "label": "Email", "type": "text"},
            ]
        )
        snapshot_fields = [
            {"selector": "#name", "label": "Name", "type": "text"},
            {"selector": "#email", "label": "Email", "type": "text"},
        ]
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, snapshot_fields, log)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_matching_selectors_returns_false(self) -> None:
        """When page has no matching selectors, returns False."""
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#different", "label": "Different", "type": "text"},
            ]
        )
        snapshot_fields = [
            {"selector": "#name", "label": "Name", "type": "text"},
            {"selector": "#email", "label": "Email", "type": "text"},
        ]
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, snapshot_fields, log)
        assert result is False

    @pytest.mark.asyncio
    async def test_partial_match_above_threshold_returns_true(self) -> None:
        """50%+ match returns True (some fields may have changed)."""
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#name", "label": "Name", "type": "text"},
                {"selector": "#new_field", "label": "New", "type": "text"},
            ]
        )
        snapshot_fields = [
            {"selector": "#name", "label": "Name", "type": "text"},
            {"selector": "#email", "label": "Email", "type": "text"},
        ]
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, snapshot_fields, log)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_fields_on_page_returns_false(self) -> None:
        """When page has no visible fields, returns False."""
        page = _make_mock_page(evaluate_result=[])
        snapshot_fields = [
            {"selector": "#name", "label": "Name", "type": "text"},
        ]
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, snapshot_fields, log)
        assert result is False

    @pytest.mark.asyncio
    async def test_falls_back_to_label_matching(self) -> None:
        """When snapshot has no selectors, falls back to label matching."""
        page = _make_mock_page(
            evaluate_result=[
                {"selector": "#x", "label": "full name", "type": "text"},
                {"selector": "#y", "label": "email address", "type": "text"},
            ]
        )
        # Snapshot fields without selectors
        snapshot_fields = [
            {"selector": "", "label": "Full Name", "type": "text"},
            {"selector": "", "label": "Email Address", "type": "text"},
        ]
        import structlog

        log = structlog.get_logger()

        result = await _verify_form_structure(page, snapshot_fields, log)
        assert result is True


# ---------------------------------------------------------------------------
# _mark_expired
# ---------------------------------------------------------------------------


class TestMarkExpired:
    """Tests for the _mark_expired helper."""

    @pytest.mark.asyncio
    async def test_sets_escalation_status_expired(self) -> None:
        """Sets escalation status to 'expired'."""
        record = _make_escalation_record(resolution_method="user_submit")
        session = AsyncMock()
        import structlog

        log = structlog.get_logger()

        with patch("src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock):
            await _mark_expired(session, record, "Form expired", log)

        assert record.status == "expired"
        assert record.resolution_method == "form_expired"
        assert record.resolved_at is not None

    @pytest.mark.asyncio
    async def test_transitions_job_to_apply_failed(self) -> None:
        """Transitions the associated job to 'apply_failed'."""
        record = _make_escalation_record(resolution_method="user_submit")
        session = AsyncMock()
        import structlog

        log = structlog.get_logger()

        with patch(
            "src.pipeline.escalation_resume.update_job_status", new_callable=AsyncMock
        ) as mock_update:
            await _mark_expired(session, record, "Form expired during escalation", log)

        mock_update.assert_called_once_with(
            session,
            "job-456",
            "apply_failed",
            reason="Form expired during escalation",
        )

    @pytest.mark.asyncio
    async def test_handles_job_update_failure_gracefully(self) -> None:
        """If job status update fails, escalation is still marked expired."""
        record = _make_escalation_record(resolution_method="user_submit")
        session = AsyncMock()
        import structlog

        log = structlog.get_logger()

        with patch(
            "src.pipeline.escalation_resume.update_job_status",
            new_callable=AsyncMock,
            side_effect=ValueError("Job not found"),
        ):
            await _mark_expired(session, record, "Form expired", log)

        # Escalation should still be marked expired
        assert record.status == "expired"
        assert record.resolution_method == "form_expired"


# ---------------------------------------------------------------------------
# _submit_form
# ---------------------------------------------------------------------------


class TestSubmitForm:
    """Tests for the form submission helper."""

    @pytest.mark.asyncio
    async def test_finds_and_clicks_submit_button(self) -> None:
        """Finds a visible submit button and clicks it."""
        page = _make_mock_page()
        import structlog

        log = structlog.get_logger()

        result = await _submit_form(page, log)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_button_found(self) -> None:
        """Returns False when no submit button is found."""
        page = _make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        import structlog

        log = structlog.get_logger()

        result = await _submit_form(page, log)
        assert result is False
