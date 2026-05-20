"""AI agent modules for the LinkedIn Job Automator."""

from src.agents.claude_client import ClaudeClient, FitScoreResult, FormField, VisualFormField
from src.agents.vision_agent import (
    Result,
    map_fields_to_profile,
    process_external_apply,
    sanitize_value,
)
from src.agents.visual_form_filler import FillResult, fill_form_visually

__all__ = [
    "ClaudeClient",
    "FillResult",
    "FitScoreResult",
    "FormField",
    "Result",
    "VisualFormField",
    "fill_form_visually",
    "map_fields_to_profile",
    "process_external_apply",
    "sanitize_value",
]
