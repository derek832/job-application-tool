"""
Property-based tests for ntfy payload composition.

Uses Hypothesis to verify correctness properties of the compose_urgent_payload
function in src/pipeline/notification_composer.py.

Properties tested:
- Property 1: Urgent Notification Payload Completeness
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.integrations.ntfy_client import NtfyPayload, NtfySettings
from src.pipeline.notification_composer import compose_urgent_payload


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty text for job fields (job_title, company must be non-empty per model)
non_empty_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Fit score: either None or an integer 0-100
fit_score_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=100))

# Trigger reason: non-empty text
trigger_reason_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

# NtfySettings strategy
ntfy_settings_strategy = st.builds(
    NtfySettings,
    server_url=st.just("https://ntfy.sh"),
    urgent_topic=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    info_topic=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    lan_base_url=st.one_of(
        st.none(),
        st.just("http://192.168.1.100:7432"),
    ),
    api_token=st.text(alphabet=st.characters(categories=("L", "N")), min_size=8, max_size=32),
)


class _FakeJobRecord:
    """Minimal stand-in for JobRecord with the fields compose_urgent_payload uses."""

    def __init__(
        self,
        *,
        id: str,
        job_title: str,
        company: str,
        fit_score: int | None,
        queue_reason: str | None,
    ) -> None:
        self.id = id
        self.job_title = job_title
        self.company = company
        self.fit_score = fit_score
        self.queue_reason = queue_reason


# Strategy for fake job records
job_record_strategy = st.builds(
    _FakeJobRecord,
    id=st.text(alphabet=st.characters(categories=("N",)), min_size=5, max_size=15).filter(
        lambda s: s.strip()
    ),
    job_title=non_empty_text,
    company=non_empty_text,
    fit_score=fit_score_strategy,
    queue_reason=st.one_of(st.none(), non_empty_text),
)


# ---------------------------------------------------------------------------
# Property 1: Urgent Notification Payload Completeness
# ---------------------------------------------------------------------------


@given(
    job=job_record_strategy,
    trigger_reason=trigger_reason_strategy,
    ntfy_settings=ntfy_settings_strategy,
)
@settings(max_examples=200)
def test_urgent_notification_payload_completeness(
    job: _FakeJobRecord,
    trigger_reason: str,
    ntfy_settings: NtfySettings,
) -> None:
    """
    For any job record (with any combination of job title, company name, fit
    score present or absent, and trigger reason), the composed urgent ntfy
    payload SHALL contain: the job title in the message, the company name in
    the message, the fit score when available, the trigger reason, priority
    set to 4, title set to "Job Automator", and tags containing "briefcase".

    **Validates: Requirements 1.2, 1.5**
    """
    payload: NtfyPayload = compose_urgent_payload(job, trigger_reason, ntfy_settings)

    # Priority SHALL be 4
    assert payload.priority == 4, (
        f"Expected priority 4, got {payload.priority}"
    )

    # Title SHALL be "Job Automator"
    assert payload.title == "Job Automator", (
        f"Expected title 'Job Automator', got '{payload.title}'"
    )

    # Tags SHALL contain "briefcase"
    assert "briefcase" in payload.tags, (
        f"Expected 'briefcase' in tags, got {payload.tags}"
    )

    # Message SHALL contain the job title
    assert job.job_title in payload.message, (
        f"Job title '{job.job_title}' not found in message: '{payload.message}'"
    )

    # Message SHALL contain the company name
    assert job.company in payload.message, (
        f"Company '{job.company}' not found in message: '{payload.message}'"
    )

    # Message SHALL contain the trigger reason
    assert trigger_reason in payload.message, (
        f"Trigger reason '{trigger_reason}' not found in message: '{payload.message}'"
    )

    # Message SHALL contain the fit score when available
    if job.fit_score is not None:
        assert str(job.fit_score) in payload.message, (
            f"Fit score '{job.fit_score}' not found in message: '{payload.message}'"
        )

    # Topic SHALL be the urgent topic from settings
    assert payload.topic == ntfy_settings.urgent_topic, (
        f"Expected topic '{ntfy_settings.urgent_topic}', got '{payload.topic}'"
    )
