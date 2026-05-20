"""Unit tests for the new visual Claude client methods.

Tests identify_fields_visual and verify_form_state methods on ClaudeClient.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.claude_client import ClaudeClient, VisualFormField
from src.exceptions import VisionAgentError


@pytest.fixture
def client() -> ClaudeClient:
    """Create a ClaudeClient with a dummy API key."""
    return ClaudeClient(api_key="test-key-not-real")


class TestIdentifyFieldsVisual:
    """Tests for ClaudeClient.identify_fields_visual."""

    @pytest.mark.asyncio
    async def test_parses_valid_response(self, client: ClaudeClient) -> None:
        """Valid JSON array response is parsed into VisualFormField objects."""
        response_data = [
            {
                "label": "Full Name",
                "field_type": "text",
                "bbox": [100, 200, 300, 40],
                "center": [250, 220],
                "suggested_value": "Derek Smith",
                "confidence": 0.95,
                "is_required": True,
                "current_value": None,
            },
            {
                "label": "Submit",
                "field_type": "button",
                "bbox": [500, 600, 120, 40],
                "center": [560, 620],
                "suggested_value": None,
                "confidence": 0.99,
                "is_required": False,
                "current_value": None,
            },
        ]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_data))]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.identify_fields_visual(
                screenshot_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
                profile='{"full_name": "Derek Smith", "email": "derek@example.com"}',
                viewport_width=1280,
                viewport_height=900,
            )

        assert len(result) == 2
        assert isinstance(result[0], VisualFormField)
        assert result[0].label == "Full Name"
        assert result[0].center == [250, 220]
        assert result[0].confidence == 0.95
        assert result[1].field_type == "button"

    @pytest.mark.asyncio
    async def test_handles_markdown_wrapped_response(self, client: ClaudeClient) -> None:
        """Response wrapped in markdown code blocks is handled."""
        response_data = [
            {
                "label": "Email",
                "field_type": "text",
                "bbox": [100, 300, 300, 40],
                "center": [250, 320],
                "suggested_value": "test@example.com",
                "confidence": 0.9,
                "is_required": True,
                "current_value": None,
            },
        ]

        wrapped = f"```json\n{json.dumps(response_data)}\n```"
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=wrapped)]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.identify_fields_visual(
                screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                profile="{}",
                viewport_width=1280,
                viewport_height=900,
            )

        assert len(result) == 1
        assert result[0].label == "Email"

    @pytest.mark.asyncio
    async def test_raises_on_invalid_json(self, client: ClaudeClient) -> None:
        """Invalid JSON response raises VisionAgentError."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not valid json at all")]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            with pytest.raises(VisionAgentError, match="Failed to parse"):
                await client.identify_fields_visual(
                    screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                    profile="{}",
                    viewport_width=1280,
                    viewport_height=900,
                )

    @pytest.mark.asyncio
    async def test_raises_on_non_array_response(self, client: ClaudeClient) -> None:
        """Non-array JSON response raises VisionAgentError."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"not": "an array"}')]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            with pytest.raises(VisionAgentError, match="Expected JSON array"):
                await client.identify_fields_visual(
                    screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                    profile="{}",
                    viewport_width=1280,
                    viewport_height=900,
                )

    @pytest.mark.asyncio
    async def test_passes_filled_labels_context(self, client: ClaudeClient) -> None:
        """Filled labels are included in the prompt context."""
        response_data = []
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_data))]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            await client.identify_fields_visual(
                screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                profile="{}",
                viewport_width=1280,
                viewport_height=900,
                filled_labels=["Full Name", "Email"],
            )

        # Verify the prompt includes filled labels
        call_args = mock_create.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[0]["content"]
        text_block = next(b for b in user_content if b["type"] == "text")
        assert "Full Name" in text_block["text"]
        assert "Email" in text_block["text"]

    @pytest.mark.asyncio
    async def test_passes_job_description_context(self, client: ClaudeClient) -> None:
        """Job description is included in the prompt for context."""
        response_data = []
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_data))]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            await client.identify_fields_visual(
                screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                profile="{}",
                viewport_width=1280,
                viewport_height=900,
                job_description="Senior Python Developer at Acme Corp",
            )

        call_args = mock_create.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[0]["content"]
        text_block = next(b for b in user_content if b["type"] == "text")
        assert "Senior Python Developer" in text_block["text"]

    @pytest.mark.asyncio
    async def test_retries_on_api_error(self, client: ClaudeClient) -> None:
        """API errors trigger retry logic."""
        import anthropic

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[]")]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [
                anthropic.APIError(
                    message="rate limit",
                    request=MagicMock(),
                    body=None,
                ),
                mock_response,
            ]
            with patch("src.agents.claude_client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.identify_fields_visual(
                    screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                    profile="{}",
                    viewport_width=1280,
                    viewport_height=900,
                )

        assert result == []
        assert mock_create.call_count == 2


class TestVerifyFormState:
    """Tests for ClaudeClient.verify_form_state."""

    @pytest.mark.asyncio
    async def test_returns_verification_results(self, client: ClaudeClient) -> None:
        """Valid verification response is parsed correctly."""
        response_data = {"Full Name": True, "Email": True, "Phone": False}
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_data))]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.verify_form_state(
                screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                viewport_width=1280,
                viewport_height=900,
                expected_fills=[
                    {"label": "Full Name", "value": "Derek Smith"},
                    {"label": "Email", "value": "derek@example.com"},
                    {"label": "Phone", "value": "+15551234567"},
                ],
            )

        assert result["Full Name"] is True
        assert result["Email"] is True
        assert result["Phone"] is False

    @pytest.mark.asyncio
    async def test_returns_all_false_on_invalid_response(self, client: ClaudeClient) -> None:
        """Invalid response defaults to all fields marked as failed."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json")]

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await client.verify_form_state(
                screenshot_bytes=b"\x89PNG" + b"\x00" * 50,
                viewport_width=1280,
                viewport_height=900,
                expected_fills=[
                    {"label": "Email", "value": "test@example.com"},
                ],
            )

        assert result == {"Email": False}


class TestVisualFormFieldModel:
    """Tests for the VisualFormField Pydantic model."""

    def test_valid_field(self) -> None:
        field = VisualFormField(
            label="Email",
            field_type="text",
            bbox=[100, 200, 300, 40],
            center=[250, 220],
            suggested_value="test@example.com",
            confidence=0.95,
            is_required=True,
            current_value=None,
        )
        assert field.label == "Email"
        assert field.center == [250, 220]

    def test_bbox_must_have_4_elements(self) -> None:
        with pytest.raises(Exception):
            VisualFormField(
                label="Email",
                field_type="text",
                bbox=[100, 200],  # Too few
                center=[250, 220],
                confidence=0.9,
            )

    def test_center_must_have_2_elements(self) -> None:
        with pytest.raises(Exception):
            VisualFormField(
                label="Email",
                field_type="text",
                bbox=[100, 200, 300, 40],
                center=[250],  # Too few
                confidence=0.9,
            )

    def test_confidence_bounds(self) -> None:
        with pytest.raises(Exception):
            VisualFormField(
                label="Email",
                field_type="text",
                bbox=[100, 200, 300, 40],
                center=[250, 220],
                confidence=1.5,  # Over 1.0
            )
