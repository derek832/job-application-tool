"""Ntfy message composition helpers.

Builds NtfyPayload objects for urgent (Human Queue) and info (run summary)
notifications, as well as escalation-specific notifications for CAPTCHA and
human_review tiers. Stateless — all configuration is passed in per call.

Validates: Requirements 1.2, 1.5, 2.4, 3.1, 3.2, 3.3, 3.5, 3.6, 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from src.db.models import JobRecord
from src.integrations.ntfy_client import NtfyAction, NtfyPayload, NtfySettings
from src.pipeline.escalation_engine import FreshnessTier


def compose_urgent_payload(
    job: JobRecord,
    trigger_reason: str,
    settings: NtfySettings,
) -> NtfyPayload:
    """Compose an urgent ntfy notification for a Human Queue item.

    Builds a high-priority payload containing the job title, company,
    fit score (when available), and trigger reason. Conditionally includes
    Approve/Reject action buttons when the job has a queue_reason AND a
    lan_base_url is configured.

    Args:
        job: The job record that triggered the notification.
        trigger_reason: The notification trigger condition (e.g. "stretch_role").
        settings: Ntfy client configuration including LAN URL and API token.

    Returns:
        An NtfyPayload ready for publishing to the urgent topic.
    """
    score_str = f" ({job.fit_score}%)" if job.fit_score is not None else ""
    message = f"{job.job_title} @ {job.company}{score_str}: {trigger_reason}"

    actions: list[NtfyAction] | None = None
    if job.queue_reason is not None and settings.lan_base_url:
        actions = [
            NtfyAction(
                action="view",
                label="Approve",
                url=(
                    f"{settings.lan_base_url}/ntfy-action"
                    f"?action=approve&job_id={job.id}"
                    f"&token={settings.api_token}"
                ),
                method="",
                headers={},
            ),
            NtfyAction(
                action="view",
                label="Reject",
                url=(
                    f"{settings.lan_base_url}/ntfy-action"
                    f"?action=reject&job_id={job.id}"
                    f"&token={settings.api_token}"
                ),
                method="",
                headers={},
            ),
        ]

    return NtfyPayload(
        topic=settings.urgent_topic,
        title="Job Automator",
        message=message,
        priority=4,
        tags=["briefcase"],
        actions=actions,
    )


def compose_info_payload(
    summary_text: str,
    settings: NtfySettings,
) -> NtfyPayload:
    """Compose an info ntfy notification for a run summary.

    Builds a default-priority payload for the info topic with no action
    buttons. Used for post-run summary delivery.

    Args:
        summary_text: The plain-English run summary text.
        settings: Ntfy client configuration (uses info_topic).

    Returns:
        An NtfyPayload ready for publishing to the info topic.
    """
    return NtfyPayload(
        topic=settings.info_topic,
        title="Job Automator",
        message=summary_text,
        priority=3,
        tags=["chart_with_upwards_trend"],
        actions=None,
    )


def _format_relative_deadline(deadline: datetime) -> str:
    """Format a timeout deadline as a human-readable relative time string.

    Computes the difference between the deadline and the current UTC time,
    then formats it as a concise relative string (e.g. "45 min", "6 hrs",
    "24 hrs").

    Args:
        deadline: The absolute UTC deadline datetime.

    Returns:
        A relative time string like "45 min", "6 hrs", or "24 hrs".
    """
    now = datetime.now(tz=UTC)
    remaining = deadline - now

    total_seconds = max(0, int(remaining.total_seconds()))
    total_minutes = total_seconds // 60

    if total_minutes < 60:
        return f"{total_minutes} min"
    else:
        hours = total_minutes // 60
        leftover_minutes = total_minutes % 60
        if leftover_minutes == 0:
            return f"{hours} hrs"
        else:
            return f"{hours} hrs {leftover_minutes} min"


def compose_escalation_notification(
    job_record: JobRecord,
    tier: Literal["captcha", "human_review"],
    freshness: FreshnessTier | None,
    timeout_deadline: datetime | None,
    open_ended_count: int,
    review_url: str,
) -> NtfyPayload:
    """Build the ntfy payload for an escalation notification.

    Composes a notification appropriate for the escalation tier:
    - CAPTCHA tier (priority 4): Instructs the user to solve the CAPTCHA
      in Chrome, includes the ATS domain for context.
    - human_review tier (priority 3): Summarizes the review opportunity
      with fit score, question count, freshness, and auto-submit deadline.

    Both tiers include a "Review" action button linking to the Review UI.

    Args:
        job_record: The job record being escalated.
        tier: Escalation type — "captcha" or "human_review".
        freshness: The freshness tier of the posting; None for CAPTCHA tier.
        timeout_deadline: The auto-submit deadline; None for CAPTCHA tier.
        open_ended_count: Number of open-ended questions detected.
        review_url: Full URL to the Review UI for this escalation.

    Returns:
        An NtfyPayload ready for publishing.

    Validates: Requirements 1.2, 2.4, 5.1, 5.2, 5.3, 5.4
    """
    # Action button is always present — links to the Review UI
    actions = [
        NtfyAction(
            action="view",
            label="Review",
            url=review_url,
            method="",
            headers={},
        ),
    ]

    if tier == "captcha":
        # Extract ATS domain from external_url
        ats_domain = ""
        if job_record.external_url:
            parsed = urlparse(job_record.external_url)
            ats_domain = parsed.netloc or ""

        title = f"CAPTCHA Required — {job_record.company}"
        body = f"{job_record.job_title} on {ats_domain}\nSolve CAPTCHA in Chrome to continue"

        return NtfyPayload(
            topic="",  # Topic is set by the caller from settings
            title=title,
            message=body,
            priority=4,
            tags=["lock"],
            actions=actions,
        )

    else:
        # human_review tier
        fit_score_str = str(job_record.fit_score) if job_record.fit_score is not None else "?"
        freshness_label = freshness.value if freshness else "unknown"

        # Format the relative deadline
        if timeout_deadline is not None:
            relative_deadline = _format_relative_deadline(timeout_deadline)
        else:
            relative_deadline = "unknown"

        title = f"Review Required — {job_record.company}"
        body = (
            f"{job_record.job_title} (fit: {fit_score_str})\n"
            f"{open_ended_count} open-ended questions\n"
            f"{freshness_label} posting — auto-submits in {relative_deadline}"
        )

        return NtfyPayload(
            topic="",  # Topic is set by the caller from settings
            title=title,
            message=body,
            priority=3,
            tags=["memo"],
            actions=actions,
        )
