"""Unit tests for the blacklist filter module."""

from __future__ import annotations

import pytest

from src.pipeline.blacklist_filter import BlacklistConfig, check_blacklist


class TestBlacklistConfig:
    """Tests for BlacklistConfig dataclass."""

    def test_default_empty_lists(self) -> None:
        """BlacklistConfig defaults to empty lists."""
        config = BlacklistConfig()
        assert config.companies == []
        assert config.title_patterns == []

    def test_custom_values(self) -> None:
        """BlacklistConfig accepts custom company and pattern lists."""
        config = BlacklistConfig(
            companies=["Revature", "Infosys"],
            title_patterns=["intern", "junior"],
        )
        assert config.companies == ["Revature", "Infosys"]
        assert config.title_patterns == ["intern", "junior"]


class TestCheckBlacklist:
    """Tests for check_blacklist function."""

    def test_no_match_returns_false_none(self) -> None:
        """Returns (False, None) when no blacklist entries match."""
        config = BlacklistConfig(
            companies=["Revature"],
            title_patterns=["intern"],
        )
        is_blacklisted, matched = check_blacklist("Google", "Senior Engineer", config)
        assert is_blacklisted is False
        assert matched is None

    def test_company_exact_match_case_insensitive(self) -> None:
        """Company matching is case-insensitive exact match."""
        config = BlacklistConfig(companies=["Revature", "Infosys"])
        is_blacklisted, matched = check_blacklist("revature", "Software Engineer", config)
        assert is_blacklisted is True
        assert matched == "company:Revature"

    def test_company_match_mixed_case(self) -> None:
        """Company matching works with mixed case in both input and config."""
        config = BlacklistConfig(companies=["INFOSYS"])
        is_blacklisted, matched = check_blacklist("Infosys", "Developer", config)
        assert is_blacklisted is True
        assert matched == "company:INFOSYS"

    def test_company_partial_match_does_not_trigger(self) -> None:
        """Company matching requires exact match, not substring."""
        config = BlacklistConfig(companies=["Rev"])
        is_blacklisted, matched = check_blacklist("Revature", "Engineer", config)
        assert is_blacklisted is False
        assert matched is None

    def test_title_substring_match_case_insensitive(self) -> None:
        """Title pattern matching is case-insensitive substring match."""
        config = BlacklistConfig(title_patterns=["intern"])
        is_blacklisted, matched = check_blacklist("Google", "Software Engineering Intern", config)
        assert is_blacklisted is True
        assert matched == "title:intern"

    def test_title_match_mixed_case(self) -> None:
        """Title pattern matching works with mixed case."""
        config = BlacklistConfig(title_patterns=["JUNIOR"])
        is_blacklisted, matched = check_blacklist("Acme", "Junior Developer", config)
        assert is_blacklisted is True
        assert matched == "title:JUNIOR"

    def test_title_pattern_not_found(self) -> None:
        """Title pattern that doesn't appear in title returns no match."""
        config = BlacklistConfig(title_patterns=["intern"])
        is_blacklisted, matched = check_blacklist("Google", "Senior Engineer", config)
        assert is_blacklisted is False
        assert matched is None

    def test_company_checked_before_title(self) -> None:
        """Company blacklist is checked first; short-circuits before title check."""
        config = BlacklistConfig(
            companies=["Revature"],
            title_patterns=["engineer"],
        )
        # Both would match, but company should be returned
        is_blacklisted, matched = check_blacklist("Revature", "Software Engineer", config)
        assert is_blacklisted is True
        assert matched == "company:Revature"

    def test_short_circuit_on_first_company_match(self) -> None:
        """Returns on first matching company entry."""
        config = BlacklistConfig(companies=["Revature", "Infosys", "Wipro"])
        is_blacklisted, matched = check_blacklist("Infosys", "Developer", config)
        assert is_blacklisted is True
        assert matched == "company:Infosys"

    def test_short_circuit_on_first_title_match(self) -> None:
        """Returns on first matching title pattern."""
        config = BlacklistConfig(title_patterns=["intern", "junior", "entry level"])
        is_blacklisted, matched = check_blacklist("Google", "Junior Intern Developer", config)
        assert is_blacklisted is True
        # "intern" comes first in the list and matches
        assert matched == "title:intern"

    def test_empty_blacklist_never_matches(self) -> None:
        """Empty blacklist config never matches anything."""
        config = BlacklistConfig()
        is_blacklisted, matched = check_blacklist("Revature", "Intern", config)
        assert is_blacklisted is False
        assert matched is None

    def test_empty_company_string(self) -> None:
        """Empty company input doesn't crash."""
        config = BlacklistConfig(companies=["Revature"])
        is_blacklisted, matched = check_blacklist("", "Engineer", config)
        assert is_blacklisted is False
        assert matched is None

    def test_empty_title_string(self) -> None:
        """Empty title input doesn't crash."""
        config = BlacklistConfig(title_patterns=["intern"])
        is_blacklisted, matched = check_blacklist("Google", "", config)
        assert is_blacklisted is False
        assert matched is None

    def test_title_pattern_with_spaces(self) -> None:
        """Title patterns with spaces work as substring matches."""
        config = BlacklistConfig(title_patterns=["entry level"])
        is_blacklisted, matched = check_blacklist("Acme", "Entry Level Software Engineer", config)
        assert is_blacklisted is True
        assert matched == "title:entry level"

    def test_matched_entry_preserves_original_case(self) -> None:
        """The matched_entry string preserves the original blacklist entry casing."""
        config = BlacklistConfig(companies=["TCS Limited"])
        is_blacklisted, matched = check_blacklist("tcs limited", "Developer", config)
        assert is_blacklisted is True
        assert matched == "company:TCS Limited"
