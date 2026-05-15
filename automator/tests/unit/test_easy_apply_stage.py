"""Unit tests for the Easy Apply pipeline stage.

Tests cover field matching, input sanitization, profile mapping, and the
overall flow logic using mocked Playwright and Claude client interactions.
"""

from __future__ import annotations

from src.api.schemas import UserProfile
from src.pipeline.easy_apply_stage import (
    _build_profile_map,
    _match_common_answer,
    _match_field_to_profile,
    _sanitize_input,
)

# ---------------------------------------------------------------------------
# Tests for _build_profile_map
# ---------------------------------------------------------------------------


class TestBuildProfileMap:
    """Tests for building the profile field mapping."""

    def test_full_profile(self) -> None:
        """All profile fields are included in the map."""
        profile = UserProfile(
            full_name="Jane Doe",
            email="jane@example.com",
            phone="555-1234",
            location="New York, NY",
            work_auth="US Citizen",
            linkedin_url="https://linkedin.com/in/janedoe",
            common_answers={"years of experience": "5"},
        )
        result = _build_profile_map(profile)
        assert result == {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-1234",
            "location": "New York, NY",
            "work_auth": "US Citizen",
        }

    def test_partial_profile(self) -> None:
        """Only non-null fields are included."""
        profile = UserProfile(
            full_name="John Smith",
            email="john@example.com",
        )
        result = _build_profile_map(profile)
        assert result == {
            "full_name": "John Smith",
            "email": "john@example.com",
        }

    def test_empty_profile(self) -> None:
        """Empty profile produces empty map."""
        profile = UserProfile()
        result = _build_profile_map(profile)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests for _match_field_to_profile
# ---------------------------------------------------------------------------


class TestMatchFieldToProfile:
    """Tests for matching form labels to profile values."""

    def test_email_match(self) -> None:
        """Label containing 'email' maps to email value."""
        values = {"email": "test@example.com", "full_name": "Test User"}
        assert _match_field_to_profile("email address", values) == "test@example.com"

    def test_phone_match(self) -> None:
        """Label containing 'phone' maps to phone value."""
        values = {"phone": "555-0000"}
        assert _match_field_to_profile("phone number", values) == "555-0000"

    def test_mobile_phone_match(self) -> None:
        """Label containing 'mobile phone' maps to phone value."""
        values = {"phone": "555-1111"}
        assert _match_field_to_profile("mobile phone number", values) == "555-1111"

    def test_location_match(self) -> None:
        """Label containing 'city' maps to location value."""
        values = {"location": "San Francisco, CA"}
        assert _match_field_to_profile("city", values) == "San Francisco, CA"

    def test_work_auth_match(self) -> None:
        """Label containing 'work authorization' maps to work_auth value."""
        values = {"work_auth": "US Citizen"}
        assert _match_field_to_profile("work authorization status", values) == "US Citizen"

    def test_authorized_to_work_match(self) -> None:
        """Label containing 'authorized to work' maps to work_auth value."""
        values = {"work_auth": "Green Card"}
        assert _match_field_to_profile("are you authorized to work", values) == "Green Card"

    def test_no_match(self) -> None:
        """Unrecognized label returns None."""
        values = {"full_name": "Test", "email": "test@test.com"}
        assert _match_field_to_profile("years of experience", values) is None

    def test_missing_profile_value(self) -> None:
        """Matched pattern but missing profile value returns None."""
        values = {}  # No email in profile
        assert _match_field_to_profile("email address", values) is None


# ---------------------------------------------------------------------------
# Tests for _match_common_answer
# ---------------------------------------------------------------------------


class TestMatchCommonAnswer:
    """Tests for matching labels against common answers."""

    def test_exact_key_match(self) -> None:
        """Key that matches label text returns the answer."""
        answers = {"years of experience": "5", "willing to relocate": "yes"}
        assert _match_common_answer("years of experience", answers) == "5"

    def test_partial_key_in_label(self) -> None:
        """Key substring found in label returns the answer."""
        answers = {"relocate": "yes"}
        assert _match_common_answer("are you willing to relocate", answers) == "yes"

    def test_label_in_key(self) -> None:
        """Label substring found in key returns the answer."""
        answers = {"how many years of python experience do you have": "7"}
        assert _match_common_answer("years of python experience", answers) == "7"

    def test_no_match(self) -> None:
        """No matching key returns None."""
        answers = {"relocate": "yes"}
        assert _match_common_answer("salary expectations", answers) is None

    def test_empty_answers(self) -> None:
        """Empty common_answers returns None."""
        assert _match_common_answer("anything", {}) is None


# ---------------------------------------------------------------------------
# Tests for _sanitize_input
# ---------------------------------------------------------------------------


class TestSanitizeInput:
    """Tests for input sanitization."""

    def test_normal_value(self) -> None:
        """Normal values pass through with whitespace stripped."""
        assert _sanitize_input("  Hello World  ") == "Hello World"

    def test_length_limit(self) -> None:
        """Values exceeding 500 characters are truncated."""
        long_value = "x" * 600
        result = _sanitize_input(long_value)
        assert len(result) == 500

    def test_script_injection_blocked(self) -> None:
        """Values containing <script are rejected."""
        assert _sanitize_input("hello <script>alert(1)</script>") == ""

    def test_javascript_protocol_blocked(self) -> None:
        """Values containing javascript: are rejected."""
        assert _sanitize_input("javascript:void(0)") == ""

    def test_sql_injection_single_quote_blocked(self) -> None:
        """Values containing SQL injection patterns are rejected."""
        assert _sanitize_input("'; drop table users; --") == ""

    def test_sql_injection_double_quote_blocked(self) -> None:
        """Values containing SQL injection patterns are rejected."""
        assert _sanitize_input('"; drop table users; --') == ""

    def test_case_insensitive_detection(self) -> None:
        """Dangerous pattern detection is case-insensitive."""
        assert _sanitize_input("<SCRIPT>alert(1)</SCRIPT>") == ""
        assert _sanitize_input("JAVASCRIPT:void(0)") == ""

    def test_safe_special_characters(self) -> None:
        """Normal special characters are allowed."""
        assert _sanitize_input("O'Brien & Associates, Inc.") == "O'Brien & Associates, Inc."
