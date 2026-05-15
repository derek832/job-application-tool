"""Unit tests for the Google Apps Script client."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import respx

from src.exceptions import GDocsError
from src.integrations.gdocs_client import GDocsClient

ENDPOINT_URL = "https://script.google.com/macros/s/test-deployment/exec"


@pytest.fixture
def client() -> GDocsClient:
    return GDocsClient(endpoint_url=ENDPOINT_URL)


@pytest.mark.asyncio
async def test_read_resume_success(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(
            return_value=httpx.Response(200, json={"content": "My resume text"})
        )
        result = await client.read_resume()
    assert result == "My resume text"


@pytest.mark.asyncio
async def test_read_resume_missing_content_field(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        with pytest.raises(GDocsError, match="missing 'content' field"):
            await client.read_resume()


@pytest.mark.asyncio
async def test_write_resume_success(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        await client.write_resume("Updated resume content")


@pytest.mark.asyncio
async def test_write_resume_no_success_field(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(200, json={"result": "ok"}))
        with pytest.raises(GDocsError, match="did not return success"):
            await client.write_resume("content")


@pytest.mark.asyncio
async def test_export_pdf_success(client: GDocsClient, tmp_path: Path) -> None:
    pdf_content = b"%PDF-1.4 fake pdf content"
    pdf_b64 = base64.b64encode(pdf_content).decode()
    dest = tmp_path / "output" / "resume.pdf"

    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(200, json={"pdf": pdf_b64}))
        await client.export_pdf(dest)

    assert dest.exists()
    assert dest.read_bytes() == pdf_content


@pytest.mark.asyncio
async def test_export_pdf_missing_pdf_field(client: GDocsClient, tmp_path: Path) -> None:
    dest = tmp_path / "resume.pdf"
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(200, json={"content": "not pdf"}))
        with pytest.raises(GDocsError, match="missing 'pdf' field"):
            await client.export_pdf(dest)


@pytest.mark.asyncio
async def test_export_pdf_invalid_base64(client: GDocsClient, tmp_path: Path) -> None:
    dest = tmp_path / "resume.pdf"
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(
            return_value=httpx.Response(200, json={"pdf": "!!!not-valid-base64!!!"})
        )
        with pytest.raises(GDocsError, match="Failed to decode base64"):
            await client.export_pdf(dest)


@pytest.mark.asyncio
async def test_http_401_raises_authorization_expired(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))
        with pytest.raises(GDocsError) as exc_info:
            await client.read_resume()
    assert exc_info.value.authorization_expired is True


@pytest.mark.asyncio
async def test_authorization_error_in_response_body(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(
            return_value=httpx.Response(200, json={"error": "authorization"})
        )
        with pytest.raises(GDocsError) as exc_info:
            await client.read_resume()
    assert exc_info.value.authorization_expired is True


@pytest.mark.asyncio
async def test_authorization_error_case_insensitive(client: GDocsClient) -> None:
    with respx.mock:
        respx.post(ENDPOINT_URL).mock(
            return_value=httpx.Response(200, json={"error": "Authorization expired"})
        )
        with pytest.raises(GDocsError) as exc_info:
            await client.write_resume("content")
    assert exc_info.value.authorization_expired is True


@pytest.mark.asyncio
async def test_non_auth_error_retries_and_raises(
    client: GDocsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patch asyncio.sleep to avoid real delays
    monkeypatch.setattr("src.integrations.gdocs_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"error": "server_error"})

    with respx.mock:
        respx.post(ENDPOINT_URL).mock(side_effect=side_effect)
        with pytest.raises(GDocsError, match="failed after 3 attempts"):
            await client.read_resume()

    assert call_count == 3


@pytest.mark.asyncio
async def test_network_error_retries_and_raises(
    client: GDocsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.integrations.gdocs_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    with respx.mock:
        respx.post(ENDPOINT_URL).mock(side_effect=side_effect)
        with pytest.raises(GDocsError, match="failed after 3 attempts"):
            await client.read_resume()

    assert call_count == 3


@pytest.mark.asyncio
async def test_http_500_retries_and_raises(
    client: GDocsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.integrations.gdocs_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="Internal Server Error")

    with respx.mock:
        respx.post(ENDPOINT_URL).mock(side_effect=side_effect)
        with pytest.raises(GDocsError, match="failed after 3 attempts"):
            await client.read_resume()

    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(
    client: GDocsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.integrations.gdocs_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, text="Temporary error")
        return httpx.Response(200, json={"content": "resume"})

    with respx.mock:
        respx.post(ENDPOINT_URL).mock(side_effect=side_effect)
        result = await client.read_resume()

    assert result == "resume"
    assert call_count == 2


async def _fake_sleep(seconds: float) -> None:
    """No-op replacement for asyncio.sleep in tests."""
