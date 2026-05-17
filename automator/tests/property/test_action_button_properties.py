"""
Property-based tests for ntfy action button conditional inclusion and URL construction.

Uses Hypothesis to verify correctness properties of the compose_urgent_payload
function in src/pipeline/notification_composer.py.

Properties tested:
- Property 4: Action Button Conditional Inclusion
- Property 5: Action Button URL Construction
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.integrations.ntfy_client import NtfySettings
from src.pipeline.notification_composer import compose_urgent_payload


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for non-empty strings (job titles, companies, etc.)
non_empty_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Strategy for job IDs (LinkedIn-style numeric strings)
job_id_strategy = st.from_regex(r"[0-9]{5,15}", fullmatch=True)

# Strategy for valid LAN base URLs (http://ip:port or http://hostname:port)
lan_base_url_strategy = st.one_of(
    # IPv4 with port
    st.tuples(
        st.integers(min_value=1, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=255),
        st.integers(min_value=1024, max_value=65535),
    ).map(lambda t: f"http://{t[0]}.{t[1]}.{t[2]}.{t[3]}:{t[4]}"),
    # Hostname with port
    st.from_regex(r"[a-z][a-z0-9\-]{2,15}", fullmatch=True).flatmap(
        lambda host: st.integers(min_value=1024, max_value=65535).map(
            lambda port: f"http://{host}:{port}"
        )
    ),
)

# Strategy for bearer tokens
api_token_strategy = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=8,
    max_size=64,
).filter(lambda s: s.strip())

# Strategy for 16-char hex topic strings
hex_topic_strategy = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# Strategy for queue reasons (non-null when present)
queue_reason_strategy = st.one_of(
    st.just("stretch_role"),
    st.just("captcha_detected"),
    st.just("score_at_threshold_boundary"),
    st.just("resume_ready_external_apply"),
    non_empty_text,
)

# Strategy for fit scores (nullable integer 0-100)
fit_score_strategy = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=100),
)

# Strategy for trigger reasons
trigger_reason_strategy = st.one_of(
    st.just("stretch_role"),
    st.just("captcha_detected"),
    st.just("score_at_threshold_boundary"),
    non_empty_text,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal JobRecord-like object for testing
# ---------------------------------------------------------------------------


class FakeJobRecord:
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


# ---------------------------------------------------------------------------
# Property 4: Action Button Conditional Inclusion
# ---------------------------------------------------------------------------


@given(
    job_id=job_id_strategy,
    job_title=non_empty_text,
    company=non_empty_text,
    fit_score=fit_score_strategy,
    queue_reason=st.one_of(st.none(), queue_reason_strategy),
    lan_base_url=st.one_of(st.none(), lan_base_url_strategy),
    api_token=api_token_strategy,
    urgent_topic=hex_topic_strategy,
    info_topic=hex_topic_strategy,
    trigger_reason=trigger_reason_strategy,
)
@settings(max_examples=200)
def test_action_button_conditional_inclusion(
    job_id: str,
    job_title: str,
    company: str,
    fit_score: int | None,
    queue_reason: str | None,
    lan_base_url: str | None,
    api_token: str,
    urgent_topic: str,
    info_topic: str,
    trigger_reason: str,
) -> None:
    """
    For any notification, action buttons SHALL be present if and only if the
    job has a non-null queue_reason AND a lan_base_url is configured.
    Notifications without a queue_reason or without a configured LAN URL
    SHALL have no action buttons.

    **Validates: Requirements 3.1, 3.6**
    """
    job = FakeJobRecord(
        id=job_id,
        job_title=job_title,
        company=company,
        fit_score=fit_score,
        queue_reason=queue_reason,
    )

    ntfy_settings = NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic=urgent_topic,
        info_topic=info_topic,
        lan_base_url=lan_base_url,
        api_token=api_token,
    )

    payload = compose_urgent_payload(job, trigger_reason, ntfy_settings)

    # The biconditional: actions present IFF (queue_reason is not None AND lan_base_url is truthy)
    should_have_actions = queue_reason is not None and lan_base_url is not None

    if should_have_actions:
        assert payload.actions is not None, (
            f"Expected action buttons when queue_reason='{queue_reason}' "
            f"and lan_base_url='{lan_base_url}', but actions was None"
        )
        assert len(payload.actions) == 2, (
            f"Expected exactly 2 action buttons (Approve, Reject), "
            f"got {len(payload.actions)}"
        )
        labels = [a.label for a in payload.actions]
        assert "Approve" in labels, "Missing 'Approve' action button"
        assert "Reject" in labels, "Missing 'Reject' action button"
    else:
        assert payload.actions is None, (
            f"Expected no action buttons when queue_reason={queue_reason!r} "
            f"and lan_base_url={lan_base_url!r}, but got actions={payload.actions}"
        )


# ---------------------------------------------------------------------------
# Property 5: Action Button URL Construction
# ---------------------------------------------------------------------------


@given(
    job_id=job_id_strategy,
    job_title=non_empty_text,
    company=non_empty_text,
    fit_score=fit_score_strategy,
    queue_reason=queue_reason_strategy,  # Always non-null for this property
    lan_base_url=lan_base_url_strategy,  # Always present for this property
    api_token=api_token_strategy,
    urgent_topic=hex_topic_strategy,
    info_topic=hex_topic_strategy,
    trigger_reason=trigger_reason_strategy,
)
@settings(max_examples=200)
def test_action_button_url_construction(
    job_id: str,
    job_title: str,
    company: str,
    fit_score: int | None,
    queue_reason: str,
    lan_base_url: str,
    api_token: str,
    urgent_topic: str,
    info_topic: str,
    trigger_reason: str,
) -> None:
    """
    For any job ID and any valid LAN base URL, the "Approve" action button URL
    SHALL equal {lan_base_url}/queue/{job_id}/approve and the "Reject" action
    button URL SHALL equal {lan_base_url}/queue/{job_id}/reject, both with
    method "POST" and an Authorization header containing the configured bearer token.

    **Validates: Requirements 3.2, 3.3**
    """
    job = FakeJobRecord(
        id=job_id,
        job_title=job_title,
        company=company,
        fit_score=fit_score,
        queue_reason=queue_reason,
    )

    ntfy_settings = NtfySettings(
        server_url="https://ntfy.sh",
        urgent_topic=urgent_topic,
        info_topic=info_topic,
        lan_base_url=lan_base_url,
        api_token=api_token,
    )

    payload = compose_urgent_payload(job, trigger_reason, ntfy_settings)

    # With both queue_reason and lan_base_url set, actions must be present
    assert payload.actions is not None, "Actions should be present"
    assert len(payload.actions) == 2, f"Expected 2 actions, got {len(payload.actions)}"

    # Find Approve and Reject actions
    approve_action = next((a for a in payload.actions if a.label == "Approve"), None)
    reject_action = next((a for a in payload.actions if a.label == "Reject"), None)

    assert approve_action is not None, "Missing 'Approve' action button"
    assert reject_action is not None, "Missing 'Reject' action button"

    # Verify Approve URL construction
    expected_approve_url = f"{lan_base_url}/queue/{job_id}/approve"
    assert approve_action.url == expected_approve_url, (
        f"Approve URL mismatch: expected '{expected_approve_url}', "
        f"got '{approve_action.url}'"
    )

    # Verify Reject URL construction
    expected_reject_url = f"{lan_base_url}/queue/{job_id}/reject"
    assert reject_action.url == expected_reject_url, (
        f"Reject URL mismatch: expected '{expected_reject_url}', "
        f"got '{reject_action.url}'"
    )

    # Verify both use POST method
    assert approve_action.method == "POST", (
        f"Approve method should be 'POST', got '{approve_action.method}'"
    )
    assert reject_action.method == "POST", (
        f"Reject method should be 'POST', got '{reject_action.method}'"
    )

    # Verify both have correct Authorization header with bearer token
    expected_auth = f"Bearer {api_token}"
    assert approve_action.headers.get("Authorization") == expected_auth, (
        f"Approve Authorization header mismatch: "
        f"expected '{expected_auth}', got '{approve_action.headers.get('Authorization')}'"
    )
    assert reject_action.headers.get("Authorization") == expected_auth, (
        f"Reject Authorization header mismatch: "
        f"expected '{expected_auth}', got '{reject_action.headers.get('Authorization')}'"
    )

    # Verify action type is "http"
    assert approve_action.action == "http", (
        f"Approve action type should be 'http', got '{approve_action.action}'"
    )
    assert reject_action.action == "http", (
        f"Reject action type should be 'http', got '{reject_action.action}'"
    )
