"""Google Apps Script client for resume management via Google Docs.

Communicates with a deployed Google Apps Script Web App over HTTPS POST
to read, write, and export the user's resume document. All requests use
httpx.AsyncClient with TLS verification enabled (never verify=False).
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
import structlog

from src.exceptions import GDocsError

logger = structlog.get_logger()

BACKOFF_SECONDS: list[float] = [5.0, 15.0, 30.0]
MAX_ATTEMPTS: int = 3


class GDocsClient:
    """Async client for the Google Apps Script resume management endpoint.

    Args:
        endpoint_url: The deployed Google Apps Script Web App URL.
    """

    def __init__(self, endpoint_url: str) -> None:
        self._endpoint_url = endpoint_url

    async def read_resume(self) -> str:
        """Read the current resume content from Google Docs.

        Returns:
            The plain-text content of the resume document.

        Raises:
            GDocsError: If the request fails after all retries or authorization expires.
        """
        response_data = await self._request({"action": "read"})
        content = response_data.get("content")
        if content is None:
            raise GDocsError("Response missing 'content' field from read action")
        return content

    async def write_resume(self, content: str) -> None:
        """Overwrite the resume document with new content.

        Args:
            content: The new plain-text resume content to write.

        Raises:
            GDocsError: If the request fails after all retries or authorization expires.
        """
        response_data = await self._request({"action": "write", "content": content})
        if not response_data.get("success"):
            raise GDocsError("Write action did not return success confirmation")

    async def export_pdf(self, dest_path: Path) -> None:
        """Export the resume document as a PDF and save it locally.

        Args:
            dest_path: The local file path where the PDF will be written.

        Raises:
            GDocsError: If the request fails after all retries or authorization expires.
        """
        response_data = await self._request({"action": "export_pdf"})
        pdf_base64 = response_data.get("pdf")
        if pdf_base64 is None:
            raise GDocsError("Response missing 'pdf' field from export_pdf action")

        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception as exc:
            raise GDocsError(f"Failed to decode base64 PDF data: {exc}") from exc

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(pdf_bytes)
        logger.info("pdf_exported", dest_path=str(dest_path), size_bytes=len(pdf_bytes))

    async def _request(self, payload: dict) -> dict:
        """Send a POST request to the GAS endpoint with retry logic.

        Retries up to 3 times with [5s, 15s, 30s] backoff on network errors
        or non-authorization HTTP errors. Authorization errors are raised
        immediately without retry.

        Args:
            payload: The JSON body to send (must include "action" key).

        Returns:
            The parsed JSON response as a dict.

        Raises:
            GDocsError: On authorization errors (with authorization_expired=True)
                or after all retries are exhausted.
        """
        last_error: str | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.debug(
                "gdocs_request_attempt",
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                action=payload.get("action"),
            )
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    response = await client.post(
                        self._endpoint_url,
                        json=payload,
                        timeout=30.0,
                    )

                # Check for HTTP 401 — authorization expired
                if response.status_code == 401:
                    logger.error(
                        "gdocs_authorization_expired",
                        status_code=response.status_code,
                        action=payload.get("action"),
                    )
                    raise GDocsError(
                        "Google Docs authorization expired (HTTP 401)",
                        authorization_expired=True,
                    )

                # Raise on other non-2xx status codes (will be retried)
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        "gdocs_http_error",
                        attempt=attempt,
                        status_code=response.status_code,
                        action=payload.get("action"),
                    )
                    if attempt < MAX_ATTEMPTS:
                        await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
                    continue

                # Parse JSON response
                data = response.json()

                # Check for authorization error in response body
                if isinstance(data.get("error"), str):
                    error_value = data["error"].lower()
                    if "authorization" in error_value:
                        logger.error(
                            "gdocs_authorization_expired",
                            error=data["error"],
                            action=payload.get("action"),
                        )
                        raise GDocsError(
                            f"Google Docs authorization expired: {data['error']}",
                            authorization_expired=True,
                        )
                    # Non-auth error in response body — retry
                    last_error = f"GAS error: {data['error']}"
                    logger.warning(
                        "gdocs_response_error",
                        attempt=attempt,
                        error=data["error"],
                        action=payload.get("action"),
                    )
                    if attempt < MAX_ATTEMPTS:
                        await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
                    continue

                logger.debug(
                    "gdocs_request_success",
                    attempt=attempt,
                    action=payload.get("action"),
                )
                return data

            except GDocsError:
                raise
            except httpx.HTTPError as exc:
                last_error = f"Network error: {exc}"
                logger.warning(
                    "gdocs_network_error",
                    attempt=attempt,
                    max_attempts=MAX_ATTEMPTS,
                    error=last_error,
                    action=payload.get("action"),
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])

        logger.error(
            "gdocs_request_exhausted",
            max_attempts=MAX_ATTEMPTS,
            error=last_error,
            action=payload.get("action"),
        )
        raise GDocsError(f"Google Docs request failed after {MAX_ATTEMPTS} attempts: {last_error}")
