"""Ntfy message composition helpers.

Builds NtfyPayload objects for urgent (Human Queue) and info (run summary)
notifications. Stateless — all configuration is passed in per call.

Validates: Requirements 1.2, 1.5, 3.1, 3.2, 3.3, 3.5, 3.6, 5.3
"""

from __future__ import annotations

from src.db.models import JobRecord
from src.integrations.ntfy_client import NtfyAction, NtfyPayload, NtfySettings


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
