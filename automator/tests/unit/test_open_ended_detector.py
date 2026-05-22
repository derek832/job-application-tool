"""Unit tests for the open-ended field detector module."""

from __future__ import annotations

import pytest

from src.pipeline.open_ended_detector import (
    OpenEndedField,
    _has_question_phrasing,
    _is_open_ended_type,
    classify_open_ended_fields,
)


class TestIsOpenEndedType:
    """Tests for _is_open_ended_type helper."""

    def test_textarea_qualifies(self) -> None:
        """Textarea fields always qualify as open-ended type."""
        field = {"type": "textarea", "maxlength": None}
        assert _is_open_ended_type(field) is True

    def test_textarea_case_insensitive(self) -> None:
        """Textarea type matching is case-insensitive."""
        field = {"type": "TEXTAREA", "maxlength": None}
        assert _is_open_ended_type(field) is True

    def test_text_with_maxlength_above_200(self) -> None:
        """Text input with maxlength > 200 qualifies."""
        field = {"type": "text", "maxlength": 500}
        assert _is_open_ended_type(field) is True

    def test_text_with_maxlength_exactly_200(self) -> None:
        """Text input with maxlength exactly 200 does NOT qualify (must be > 200)."""
        field = {"type": "text", "maxlength": 200}
        assert _is_open_ended_type(field) is False

    def test_text_with_maxlength_below_200(self) -> None:
        """Text input with maxlength < 200 does not qualify."""
        field = {"type": "text", "maxlength": 100}
        assert _is_open_ended_type(field) is False

    def test_text_with_no_maxlength(self) -> None:
        """Text input with no maxlength (None) qualifies as potentially open-ended."""
        field = {"type": "text", "maxlength": None}
        assert _is_open_ended_type(field) is True

    def test_select_does_not_qualify(self) -> None:
        """Select fields never qualify as open-ended."""
        field = {"type": "select", "maxlength": None}
        assert _is_open_ended_type(field) is False

    def test_checkbox_does_not_qualify(self) -> None:
        """Checkbox fields never qualify as open-ended."""
        field = {"type": "checkbox", "maxlength": None}
        assert _is_open_ended_type(field) is False

    def test_radio_does_not_qualify(self) -> None:
        """Radio fields never qualify as open-ended."""
        field = {"type": "radio", "maxlength": None}
        assert _is_open_ended_type(field) is False

    def test_empty_type_does_not_qualify(self) -> None:
        """Empty type string does not qualify."""
        field = {"type": "", "maxlength": None}
        assert _is_open_ended_type(field) is False

    def test_missing_type_does_not_qualify(self) -> None:
        """Missing type key does not qualify."""
        field = {"maxlength": None}
        assert _is_open_ended_type(field) is False

    def test_text_with_maxlength_201(self) -> None:
        """Text input with maxlength 201 qualifies (boundary)."""
        field = {"type": "text", "maxlength": 201}
        assert _is_open_ended_type(field) is True


class TestHasQuestionPhrasing:
    """Tests for _has_question_phrasing helper."""

    def test_ends_with_question_mark(self) -> None:
        """Label ending with '?' is question phrasing."""
        assert _has_question_phrasing("What is your name?") is True

    def test_question_mark_with_trailing_space(self) -> None:
        """Label ending with '?' after stripping is question phrasing."""
        assert _has_question_phrasing("What is your name?  ") is True

    def test_interrogative_what(self) -> None:
        """'what' as a word triggers question phrasing."""
        assert _has_question_phrasing("What motivates you in your career") is True

    def test_interrogative_why(self) -> None:
        """'why' as a word triggers question phrasing."""
        assert _has_question_phrasing("Why are you interested in this role") is True

    def test_interrogative_how(self) -> None:
        """'how' as a word triggers question phrasing."""
        assert _has_question_phrasing("How did you hear about us") is True

    def test_interrogative_when(self) -> None:
        """'when' as a word triggers question phrasing."""
        assert _has_question_phrasing("When can you start") is True

    def test_interrogative_where(self) -> None:
        """'where' as a word triggers question phrasing."""
        assert _has_question_phrasing("Where are you located") is True

    def test_interrogative_who(self) -> None:
        """'who' as a word triggers question phrasing."""
        assert _has_question_phrasing("Who referred you to this position") is True

    def test_interrogative_which(self) -> None:
        """'which' as a word triggers question phrasing."""
        assert _has_question_phrasing("Which programming languages do you know") is True

    def test_request_phrase_describe(self) -> None:
        """'describe' triggers question phrasing."""
        assert _has_question_phrasing("Describe your experience with Python") is True

    def test_request_phrase_explain(self) -> None:
        """'explain' triggers question phrasing."""
        assert _has_question_phrasing("Explain your approach to problem solving") is True

    def test_request_phrase_tell_us(self) -> None:
        """'tell us' triggers question phrasing."""
        assert _has_question_phrasing("Tell us about yourself") is True

    def test_request_phrase_share(self) -> None:
        """'share' triggers question phrasing."""
        assert _has_question_phrasing("Share an example of leadership") is True

    def test_request_phrase_elaborate(self) -> None:
        """'elaborate' triggers question phrasing."""
        assert _has_question_phrasing("Please elaborate on your experience") is True

    def test_request_phrase_summarize(self) -> None:
        """'summarize' triggers question phrasing."""
        assert _has_question_phrasing("Summarize your relevant qualifications") is True

    def test_no_question_phrasing_plain_label(self) -> None:
        """Plain label without question phrasing returns False."""
        assert _has_question_phrasing("Full Name") is False

    def test_no_question_phrasing_email(self) -> None:
        """Email label without question phrasing returns False."""
        assert _has_question_phrasing("Email Address") is False

    def test_no_question_phrasing_phone(self) -> None:
        """Phone label without question phrasing returns False."""
        assert _has_question_phrasing("Phone Number") is False

    def test_empty_label(self) -> None:
        """Empty label returns False."""
        assert _has_question_phrasing("") is False

    def test_whitespace_only_label(self) -> None:
        """Whitespace-only label returns False."""
        assert _has_question_phrasing("   ") is False

    def test_interrogative_word_boundary(self) -> None:
        """Interrogative words must be at word boundaries (not substrings)."""
        # "showtime" contains "how" but not at a word boundary
        assert _has_question_phrasing("Showtime availability") is False

    def test_case_insensitive_matching(self) -> None:
        """Question phrasing detection is case-insensitive."""
        assert _has_question_phrasing("WHAT IS YOUR EXPERIENCE") is True
        assert _has_question_phrasing("DESCRIBE your background") is True


class TestClassifyOpenEndedFields:
    """Tests for classify_open_ended_fields function."""

    def test_textarea_with_question_label(self) -> None:
        """Textarea with question phrasing in label is classified as open-ended."""
        fields = [
            {
                "type": "textarea",
                "maxlength": None,
                "label": "Why are you interested in this role?",
                "field_id": "q1",
                "selector": "#custom_question_1",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 1
        assert result[0].field_id == "q1"
        assert result[0].label == "Why are you interested in this role?"
        assert result[0].selector == "#custom_question_1"
        assert result[0].char_limit is None

    def test_text_input_high_maxlength_with_question(self) -> None:
        """Text input with maxlength > 200 and question label is open-ended."""
        fields = [
            {
                "type": "text",
                "maxlength": 500,
                "label": "Describe your experience with cloud security",
                "field_id": "q2",
                "selector": "#experience_field",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 1
        assert result[0].field_id == "q2"
        assert result[0].char_limit == 500

    def test_textarea_without_question_label_excluded(self) -> None:
        """Textarea without question phrasing in label is NOT classified as open-ended."""
        fields = [
            {
                "type": "textarea",
                "maxlength": None,
                "label": "Additional Notes",
                "field_id": "notes",
                "selector": "#notes",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 0

    def test_text_input_low_maxlength_excluded(self) -> None:
        """Text input with maxlength <= 200 is excluded even with question label."""
        fields = [
            {
                "type": "text",
                "maxlength": 100,
                "label": "What is your name?",
                "field_id": "name",
                "selector": "#name",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 0

    def test_select_field_excluded(self) -> None:
        """Select fields are never classified as open-ended."""
        fields = [
            {
                "type": "select",
                "maxlength": None,
                "label": "How did you hear about us?",
                "field_id": "source",
                "selector": "#source",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 0

    def test_multiple_fields_mixed(self) -> None:
        """Only qualifying fields are returned from a mixed set."""
        fields = [
            {
                "type": "text",
                "maxlength": 50,
                "label": "First Name",
                "field_id": "fname",
                "selector": "#fname",
            },
            {
                "type": "textarea",
                "maxlength": None,
                "label": "Why do you want to work here?",
                "field_id": "q1",
                "selector": "#q1",
            },
            {
                "type": "text",
                "maxlength": 100,
                "label": "Email",
                "field_id": "email",
                "selector": "#email",
            },
            {
                "type": "text",
                "maxlength": 1000,
                "label": "Describe your relevant experience",
                "field_id": "q2",
                "selector": "#q2",
            },
            {
                "type": "select",
                "maxlength": None,
                "label": "Which location do you prefer?",
                "field_id": "loc",
                "selector": "#loc",
            },
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 2
        assert result[0].field_id == "q1"
        assert result[1].field_id == "q2"

    def test_empty_field_list(self) -> None:
        """Empty input returns empty list."""
        result = classify_open_ended_fields([])
        assert result == []

    def test_returns_open_ended_field_dataclass(self) -> None:
        """Results are OpenEndedField dataclass instances."""
        fields = [
            {
                "type": "textarea",
                "maxlength": 2000,
                "label": "What makes you a good fit?",
                "field_id": "fit",
                "selector": "#fit_question",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 1
        assert isinstance(result[0], OpenEndedField)
        assert result[0].question_text == "What makes you a good fit?"
        assert result[0].char_limit == 2000

    def test_text_no_maxlength_with_question(self) -> None:
        """Text input with no maxlength and question label is open-ended."""
        fields = [
            {
                "type": "text",
                "maxlength": None,
                "label": "Tell us about your background",
                "field_id": "bg",
                "selector": "#background",
            }
        ]
        result = classify_open_ended_fields(fields)
        assert len(result) == 1
        assert result[0].field_id == "bg"
        assert result[0].char_limit is None
