"""
Property-based tests for validation report correctness.

Uses Hypothesis to verify that generate_report() correctly produces a
ValidationReport from a ValidationSession with arbitrary platform states.

Properties tested:
- Property 10: Validation Report Correctness

Feature: visual-apply-validation, Property 10: Validation Report Correctness
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.validation_models import (
    PlatformValidationState,
    ValidationSession,
    generate_report,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

PLATFORM_NAMES = ["greenhouse", "lever", "workday", "icims", "bamboohr"]
PLATFORM_STATUSES = ["pass", "fail", "unavailable"]


def platform_state_strategy(platform: str) -> st.SearchStrategy[PlatformValidationState]:
    """Generate a PlatformValidationState with random status and fields."""
    return st.builds(
        PlatformValidationState,
        platform=st.just(platform),
        status=st.sampled_from(PLATFORM_STATUSES),
        active_url=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
        fix_cycles_used=st.integers(min_value=0, max_value=5),
        fields_filled=st.integers(min_value=0, max_value=20),
        pages_completed=st.integers(min_value=0, max_value=5),
        diagnosed_issues=st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=3),
    )


@st.composite
def validation_session_strategy(draw: st.DrawFn) -> ValidationSession:
    """Generate a ValidationSession with all 5 platforms in arbitrary states."""
    platforms: dict[str, PlatformValidationState] = {}
    for name in PLATFORM_NAMES:
        state = draw(platform_state_strategy(name))
        platforms[name] = state

    modified_files = draw(st.lists(st.text(min_size=1, max_size=40), min_size=0, max_size=5))

    return ValidationSession(
        platforms=platforms,
        overall_status="complete",
        modified_files=modified_files,
        start_time="2024-01-01T10:00:00",
        end_time="2024-01-01T11:30:00",
    )


# ---------------------------------------------------------------------------
# Property 10: Validation Report Correctness
# ---------------------------------------------------------------------------


@given(session=validation_session_strategy())
@settings(max_examples=200)
def test_validation_report_correctness(session: ValidationSession) -> None:
    """
    For any ValidationSession with 5 platforms in arbitrary states (pass, fail,
    unavailable), generate_report produces a report where:
    1. overall_pass is True iff all 5 platforms have status "pass"
    2. Report has exactly one entry per platform in the session
    3. Every platform with status != "pass" has outstanding_issues populated
       (from diagnosed_issues)
    4. Every platform with status == "pass" has empty outstanding_issues

    **Validates: Requirements 6.3, 6.5**
    """
    report = generate_report(session)

    # 1. overall_pass is True iff all 5 platforms have status "pass"
    all_pass = all(state.status == "pass" for state in session.platforms.values())
    expected_overall = all_pass and len(session.platforms) == 5
    assert report.overall_pass == expected_overall, (
        f"overall_pass is {report.overall_pass}, expected {expected_overall}. "
        f"Platform statuses: {[s.status for s in session.platforms.values()]}"
    )

    # 2. Report has exactly one entry per platform
    report_platforms = [pr.platform for pr in report.platforms]
    assert len(report.platforms) == len(session.platforms), (
        f"Report has {len(report.platforms)} entries, "
        f"expected {len(session.platforms)}"
    )
    for platform_name in session.platforms:
        assert platform_name in report_platforms, (
            f"Platform {platform_name!r} missing from report"
        )

    # 3 & 4. Check outstanding_issues based on platform status
    for platform_report in report.platforms:
        state = session.platforms[platform_report.platform]
        if state.status == "pass":
            # Passing platforms have empty outstanding_issues
            assert platform_report.outstanding_issues == [], (
                f"Platform {platform_report.platform!r} has status 'pass' "
                f"but outstanding_issues is {platform_report.outstanding_issues}"
            )
        else:
            # Failing/unavailable platforms have outstanding_issues from diagnosed_issues
            assert platform_report.outstanding_issues == list(state.diagnosed_issues), (
                f"Platform {platform_report.platform!r} has status {state.status!r} "
                f"but outstanding_issues {platform_report.outstanding_issues} "
                f"!= diagnosed_issues {state.diagnosed_issues}"
            )
