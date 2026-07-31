"""Custom exception classes for the LinkedIn Job Automator.

Each exception represents a distinct failure domain in the pipeline and carries
enough context (job_id + message) to diagnose the failure at the point of catch.
All exceptions inherit from AutomatorError for easy pipeline-level catching.
"""


class AutomatorError(Exception):
    """Base exception for all Automator failures.

    Attributes:
        job_id: The LinkedIn job ID associated with the failure, or None if not job-specific.
        message: A human-readable description of what went wrong.
    """

    def __init__(self, message: str, job_id: str | None = None) -> None:
        self.message: str = message
        self.job_id: str | None = job_id
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(message={self.message!r}, job_id={self.job_id!r})"


class ExtractionError(AutomatorError):
    """Raised when LinkedIn job description scraping fails after all retries."""


class ScoringError(AutomatorError):
    """Raised when the Claude API fit scoring call fails after all retries."""


class TailoringError(AutomatorError):
    """Raised when the Claude API resume tailoring call fails after all retries."""


class ApplyError(AutomatorError):
    """Raised when Easy Apply or external form submission fails."""


class GDocsError(AutomatorError):
    """Raised when Google Apps Script communication fails.

    Attributes:
        authorization_expired: True when the GAS endpoint returns an authorization
            error, indicating the user must re-authenticate. Used by the pipeline
            to trigger system pause and SMS notification.
    """

    def __init__(
        self,
        message: str,
        job_id: str | None = None,
        *,
        authorization_expired: bool = False,
    ) -> None:
        super().__init__(message, job_id)
        self.authorization_expired: bool = authorization_expired

    def __repr__(self) -> str:
        return (
            f"GDocsError(message={self.message!r}, job_id={self.job_id!r}, "
            f"authorization_expired={self.authorization_expired!r})"
        )


class SMSError(AutomatorError):
    """Raised when sending an SMS notification via the Gmail gateway fails."""


class ConfigError(AutomatorError):
    """Raised when required configuration is missing or invalid."""


class PipelineError(AutomatorError):
    """Raised for orchestration-level failures in the job pipeline."""
