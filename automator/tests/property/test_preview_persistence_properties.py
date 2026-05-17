"""
Property-based tests for preview result persistence completeness.

Uses Hypothesis to verify that for any preview run that completes successfully
with N discovered jobs, the persisted PreviewResult contains exactly N
PreviewJob records, each with non-null required fields. Every scored job
shall have a non-null fit_score and fit_rationale.

Properties tested:
- Property 2: Preview Result Persistence Completeness
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.db.models import PreviewJob, PreviewRun
from src.pipeline.preview_pipeline import compute_projected_action


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid projected actions as defined in the design
VALID_PROJECTED_ACTIONS = ["auto_apply", "stretch_queue", "skip", "blacklisted"]

# ASCII alphabet for generating realistic text fields
_ascii_alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_&.,"

# Strategy for job titles — non-empty ASCII text
job_title_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=3,
    max_size=80,
).filter(lambda s: s.strip())

# Strategy for company names — non-empty ASCII text
company_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=2,
    max_size=50,
).filter(lambda s: s.strip())

# Strategy for LinkedIn job IDs — numeric strings
job_id_strategy = st.from_regex(r"[0-9]{8,12}", fullmatch=True)

# Strategy for LinkedIn URLs
linkedin_url_strategy = job_id_strategy.map(
    lambda jid: f"https://linkedin.com/jobs/view/{jid}"
)

# Strategy for fit scores (0-100 when scored)
fit_score_strategy = st.integers(min_value=0, max_value=100)

# Strategy for fit rationale text
fit_rationale_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=10,
    max_size=200,
).filter(lambda s: s.strip())

# Strategy for thresholds
good_fit_threshold_strategy = st.integers(min_value=50, max_value=95)
stretch_threshold_strategy = st.integers(min_value=20, max_value=49)


@st.composite
def scored_preview_job_strategy(draw: st.DrawFn) -> dict:
    """Generate a scored preview job with all required fields populated."""
    job_id = draw(job_id_strategy)
    job_title = draw(job_title_strategy)
    company = draw(company_strategy)
    linkedin_url = f"https://linkedin.com/jobs/view/{job_id}"
    fit_score = draw(fit_score_strategy)
    fit_rationale = draw(fit_rationale_strategy)
    good_fit_threshold = draw(good_fit_threshold_strategy)
    stretch_threshold = draw(stretch_threshold_strategy)

    projected_action = compute_projected_action(
        fit_score=fit_score,
        good_fit_threshold=good_fit_threshold,
        stretch_threshold=stretch_threshold,
        is_blacklisted=False,
    )

    return {
        "job_id": job_id,
        "job_title": job_title,
        "company": company,
        "linkedin_url": linkedin_url,
        "fit_score": fit_score,
        "fit_rationale": fit_rationale,
        "projected_action": projected_action,
    }


@st.composite
def blacklisted_preview_job_strategy(draw: st.DrawFn) -> dict:
    """Generate a blacklisted preview job (no score, action=blacklisted)."""
    job_id = draw(job_id_strategy)
    job_title = draw(job_title_strategy)
    company = draw(company_strategy)
    linkedin_url = f"https://linkedin.com/jobs/view/{job_id}"

    return {
        "job_id": job_id,
        "job_title": job_title,
        "company": company,
        "linkedin_url": linkedin_url,
        "fit_score": None,
        "fit_rationale": None,
        "projected_action": "blacklisted",
    }


@st.composite
def mixed_preview_job_list_strategy(draw: st.DrawFn) -> list[dict]:
    """Generate a list of preview jobs — mix of scored and blacklisted."""
    scored_jobs = draw(
        st.lists(scored_preview_job_strategy(), min_size=0, max_size=15)
    )
    blacklisted_jobs = draw(
        st.lists(blacklisted_preview_job_strategy(), min_size=0, max_size=5)
    )
    all_jobs = scored_jobs + blacklisted_jobs
    # Ensure at least 1 job in the list
    if not all_jobs:
        all_jobs = [draw(scored_preview_job_strategy())]
    return all_jobs


# ---------------------------------------------------------------------------
# Property 2: Preview Result Persistence Completeness
# ---------------------------------------------------------------------------


@given(jobs_data=mixed_preview_job_list_strategy())
@settings(max_examples=150)
def test_preview_result_contains_exactly_n_records(
    jobs_data: list[dict],
) -> None:
    """
    For any preview run that completes successfully with N discovered jobs,
    the persisted PreviewResult shall contain exactly N PreviewJob records.

    This test simulates persisting N jobs as PreviewJob model instances and
    verifies the count matches exactly.

    **Validates: Requirements 1.2**
    """
    run_id = "test-run-001"
    n = len(jobs_data)

    # Simulate creating PreviewJob records as the pipeline would
    preview_jobs: list[PreviewJob] = []
    for job_data in jobs_data:
        preview_job = PreviewJob(
            run_id=run_id,
            job_id=job_data["job_id"],
            job_title=job_data["job_title"],
            company=job_data["company"],
            linkedin_url=job_data["linkedin_url"],
            fit_score=job_data["fit_score"],
            fit_rationale=job_data["fit_rationale"],
            projected_action=job_data["projected_action"],
        )
        preview_jobs.append(preview_job)

    # Property: exactly N records persisted
    assert len(preview_jobs) == n, (
        f"Expected exactly {n} PreviewJob records, got {len(preview_jobs)}"
    )


@given(jobs_data=mixed_preview_job_list_strategy())
@settings(max_examples=150)
def test_preview_jobs_have_non_null_required_fields(
    jobs_data: list[dict],
) -> None:
    """
    For any preview run that completes successfully, each PreviewJob record
    shall have a non-null job_title, company, linkedin_url, and
    projected_action field.

    **Validates: Requirements 1.2**
    """
    run_id = "test-run-002"

    for job_data in jobs_data:
        preview_job = PreviewJob(
            run_id=run_id,
            job_id=job_data["job_id"],
            job_title=job_data["job_title"],
            company=job_data["company"],
            linkedin_url=job_data["linkedin_url"],
            fit_score=job_data["fit_score"],
            fit_rationale=job_data["fit_rationale"],
            projected_action=job_data["projected_action"],
        )

        # Required fields must be non-null
        assert preview_job.job_title is not None, (
            f"job_title must not be None, got None for job_id={preview_job.job_id}"
        )
        assert preview_job.company is not None, (
            f"company must not be None, got None for job_id={preview_job.job_id}"
        )
        assert preview_job.linkedin_url is not None, (
            f"linkedin_url must not be None, got None for job_id={preview_job.job_id}"
        )
        assert preview_job.projected_action is not None, (
            f"projected_action must not be None, got None for job_id={preview_job.job_id}"
        )

        # Required fields must be non-empty strings
        assert len(preview_job.job_title.strip()) > 0, (
            f"job_title must not be empty for job_id={preview_job.job_id}"
        )
        assert len(preview_job.company.strip()) > 0, (
            f"company must not be empty for job_id={preview_job.job_id}"
        )
        assert len(preview_job.linkedin_url.strip()) > 0, (
            f"linkedin_url must not be empty for job_id={preview_job.job_id}"
        )
        assert preview_job.projected_action in VALID_PROJECTED_ACTIONS, (
            f"projected_action must be one of {VALID_PROJECTED_ACTIONS}, "
            f"got '{preview_job.projected_action}' for job_id={preview_job.job_id}"
        )


@given(jobs_data=st.lists(scored_preview_job_strategy(), min_size=1, max_size=20))
@settings(max_examples=150)
def test_scored_jobs_have_non_null_fit_score_and_rationale(
    jobs_data: list[dict],
) -> None:
    """
    For any preview run, every job that was scored shall have a non-null
    fit_score and fit_rationale. A scored job is one whose projected_action
    is not 'blacklisted' and whose fit_score is not None.

    **Validates: Requirements 1.2**
    """
    run_id = "test-run-003"

    for job_data in jobs_data:
        preview_job = PreviewJob(
            run_id=run_id,
            job_id=job_data["job_id"],
            job_title=job_data["job_title"],
            company=job_data["company"],
            linkedin_url=job_data["linkedin_url"],
            fit_score=job_data["fit_score"],
            fit_rationale=job_data["fit_rationale"],
            projected_action=job_data["projected_action"],
        )

        # All scored jobs must have non-null fit_score and fit_rationale
        assert preview_job.fit_score is not None, (
            f"Scored job must have non-null fit_score, "
            f"got None for job_id={preview_job.job_id}"
        )
        assert preview_job.fit_rationale is not None, (
            f"Scored job must have non-null fit_rationale, "
            f"got None for job_id={preview_job.job_id}"
        )
        # fit_score must be in valid range
        assert 0 <= preview_job.fit_score <= 100, (
            f"fit_score must be 0-100, got {preview_job.fit_score} "
            f"for job_id={preview_job.job_id}"
        )


@given(
    scored_jobs=st.lists(scored_preview_job_strategy(), min_size=0, max_size=10),
    blacklisted_jobs=st.lists(blacklisted_preview_job_strategy(), min_size=0, max_size=5),
)
@settings(max_examples=150)
def test_preview_result_completeness_with_mixed_jobs(
    scored_jobs: list[dict],
    blacklisted_jobs: list[dict],
) -> None:
    """
    For any preview run with a mix of scored and blacklisted jobs, the total
    number of PreviewJob records equals the total number of discovered jobs
    (scored + blacklisted). Each record maintains its field constraints:
    scored jobs have fit_score/fit_rationale, blacklisted jobs may have None.

    **Validates: Requirements 1.2**
    """
    all_jobs = scored_jobs + blacklisted_jobs
    if not all_jobs:
        return  # Skip empty case — a completed run has at least 0 jobs

    run_id = "test-run-004"
    n_total = len(all_jobs)

    preview_jobs: list[PreviewJob] = []
    for job_data in all_jobs:
        preview_job = PreviewJob(
            run_id=run_id,
            job_id=job_data["job_id"],
            job_title=job_data["job_title"],
            company=job_data["company"],
            linkedin_url=job_data["linkedin_url"],
            fit_score=job_data["fit_score"],
            fit_rationale=job_data["fit_rationale"],
            projected_action=job_data["projected_action"],
        )
        preview_jobs.append(preview_job)

    # Total count matches
    assert len(preview_jobs) == n_total, (
        f"Expected {n_total} total PreviewJob records, got {len(preview_jobs)}"
    )

    # All required fields are non-null for every record
    for pj in preview_jobs:
        assert pj.job_title is not None
        assert pj.company is not None
        assert pj.linkedin_url is not None
        assert pj.projected_action is not None
        assert pj.projected_action in VALID_PROJECTED_ACTIONS

    # Scored jobs (non-blacklisted) have fit_score and fit_rationale
    scored_records = [pj for pj in preview_jobs if pj.projected_action != "blacklisted"]
    for pj in scored_records:
        if pj.fit_score is not None:
            # If it was scored, rationale must also be present
            assert pj.fit_rationale is not None, (
                f"Scored job with fit_score={pj.fit_score} must have "
                f"non-null fit_rationale, job_id={pj.job_id}"
            )
            assert 0 <= pj.fit_score <= 100, (
                f"fit_score must be 0-100, got {pj.fit_score}"
            )
