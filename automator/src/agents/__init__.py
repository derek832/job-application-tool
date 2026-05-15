"""AI agent modules for the LinkedIn Job Automator."""

from src.agents.claude_client import ClaudeClient, FitScoreResult, FormField
from src.agents.vision_agent import (
    Result,
    map_fields_to_profile,
    process_external_apply,
    sanitize_value,
)

__all__ = [
    "ClaudeClient",
    "FitScoreResult",
    "FormField",
    "Result",
    "map_fields_to_profile",
    "process_external_apply",
    "sanitize_value",
]
