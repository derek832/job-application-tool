"""Open-ended field detector for external apply forms.

Classifies form fields as open-ended questions based on DOM attributes and
label text. Used by the Escalation Engine to determine which fields require
human review on high-scoring jobs.

A field is classified as open-ended when:
- It is a <textarea> element, OR
- It is a text input with maxlength > 200 characters
AND the label/prompt contains question phrasing (interrogative words,
phrases requesting description/explanation, or ends with '?').
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Interrogative words and phrases that indicate a question or prompt
# requesting a substantive written response.
INTERROGATIVE_WORDS: list[str] = [
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
]

# Phrases that request description, explanation, or elaboration
REQUEST_PHRASES: list[str] = [
    "describe",
    "explain",
    "tell us",
    "share",
    "elaborate",
    "discuss",
    "outline",
    "summarize",
    "provide",
    "walk us through",
    "give an example",
    "give us",
    "let us know",
]

# Compiled regex for matching interrogative words at word boundaries
_INTERROGATIVE_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in INTERROGATIVE_WORDS) + r")\b",
    re.IGNORECASE,
)

# Compiled regex for matching request phrases (substring match, case-insensitive)
_REQUEST_PHRASE_PATTERN: re.Pattern[str] = re.compile(
    r"(" + "|".join(re.escape(p) for p in REQUEST_PHRASES) + r")",
    re.IGNORECASE,
)


@dataclass
class OpenEndedField:
    """A form field classified as open-ended (requiring a substantive written response).

    Attributes:
        field_id: Unique identifier for the field in the DOM.
        label: The visible label text associated with the field.
        selector: CSS selector to locate the field in the page.
        question_text: The full question or prompt text for the field.
        char_limit: Maximum character limit if specified, or None.
    """

    field_id: str
    label: str
    selector: str
    question_text: str
    char_limit: int | None


def _is_open_ended_type(field: dict) -> bool:
    """Check if a field's type qualifies as potentially open-ended.

    A field qualifies if it is a textarea element, or a text input with
    maxlength > 200 characters (or no maxlength set, which implies unlimited).

    Args:
        field: Dict with 'type' and optional 'maxlength' keys.

    Returns:
        True if the field type qualifies for open-ended classification.
    """
    field_type = (field.get("type") or "").lower().strip()

    if field_type == "textarea":
        return True

    if field_type == "text":
        maxlength = field.get("maxlength")
        if maxlength is None:
            # No maxlength set — treat as potentially open-ended
            # (unlimited text input could be used for long answers)
            return True
        try:
            return int(maxlength) > 200
        except (ValueError, TypeError):
            return False

    return False


def _has_question_phrasing(label: str) -> bool:
    """Check if a label contains question phrasing.

    A label has question phrasing if it:
    - Contains an interrogative word (what, why, how, etc.) at a word boundary
    - Contains a request phrase (describe, explain, tell us, etc.)
    - Ends with a question mark

    Args:
        label: The field label or prompt text.

    Returns:
        True if the label contains question phrasing.
    """
    if not label or not label.strip():
        return False

    # Check if ends with question mark
    if label.strip().endswith("?"):
        return True

    # Check for interrogative words
    if _INTERROGATIVE_PATTERN.search(label):
        return True

    # Check for request phrases
    if _REQUEST_PHRASE_PATTERN.search(label):
        return True

    return False


def classify_open_ended_fields(
    dom_fields: list[dict],
) -> list[OpenEndedField]:
    """Identify which DOM fields are open-ended questions.

    A field is open-ended when:
    - It is a <textarea> element, OR
    - It is a text input with maxlength > 200 characters (or no maxlength)
    AND the label/prompt contains question phrasing (interrogative words,
    phrases requesting description/explanation, or ends with '?').

    Args:
        dom_fields: List of dicts representing form fields. Each dict should
            have keys: type, maxlength (int or None), label (str),
            field_id (str), selector (str).

    Returns:
        List of OpenEndedField instances for fields classified as open-ended.
    """
    results: list[OpenEndedField] = []

    for field in dom_fields:
        if not _is_open_ended_type(field):
            continue

        label = field.get("label") or ""
        if not _has_question_phrasing(label):
            continue

        # Field qualifies as open-ended
        maxlength = field.get("maxlength")
        char_limit: int | None = None
        if maxlength is not None:
            try:
                char_limit = int(maxlength)
            except (ValueError, TypeError):
                char_limit = None

        open_ended = OpenEndedField(
            field_id=field.get("field_id") or "",
            label=label,
            selector=field.get("selector") or "",
            question_text=label,
            char_limit=char_limit,
        )
        results.append(open_ended)

    logger.debug(
        "open_ended_fields_classified",
        total_fields=len(dom_fields),
        open_ended_count=len(results),
    )

    return results
