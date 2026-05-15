"""
Session management routes for importing browser cookies.

Provides an endpoint that accepts LinkedIn cookies from the Chrome Extension
and writes them into the Playwright persistent browser profile so the pipeline
can use the authenticated session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.auth import verify_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/session", tags=["session"])

_USER_DATA_DIR = Path(os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "data/browser-profile"))


class CookieImportRequest(BaseModel):
    """Request body for POST /session/cookies."""

    cookies: list[dict[str, object]]


class CookieImportResponse(BaseModel):
    """Response for POST /session/cookies."""

    imported: int
    message: str


@router.post("/cookies", response_model=CookieImportResponse)
async def import_cookies(
    body: CookieImportRequest,
    _: None = Depends(verify_token),
) -> CookieImportResponse:
    """Import LinkedIn cookies into the Playwright browser profile.

    Accepts cookies from the Chrome Extension (obtained via chrome.cookies API)
    and writes them into the Playwright persistent context's cookie storage.
    This allows the pipeline to use the user's authenticated LinkedIn session.

    The cookies are stored in Chromium's Default profile cookie format that
    Playwright's persistent context can read.
    """
    if not body.cookies:
        return CookieImportResponse(imported=0, message="No cookies provided")

    # Ensure the profile directory exists
    profile_dir = _USER_DATA_DIR / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Convert Chrome extension cookies to Playwright's state format
    playwright_cookies = []
    for cookie in body.cookies:
        pc = {
            "name": cookie.get("name", ""),
            "value": cookie.get("value", ""),
            "domain": cookie.get("domain", ""),
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", False),
            "httpOnly": cookie.get("httpOnly", False),
            "sameSite": _map_same_site(cookie.get("sameSite", "unspecified")),
        }
        # Add expiry if present
        expiration = cookie.get("expirationDate")
        if expiration is not None:
            pc["expires"] = float(expiration)
        else:
            pc["expires"] = -1

        playwright_cookies.append(pc)

    # Write as Playwright storage state JSON
    state_path = _USER_DATA_DIR / "storage-state.json"
    state = {
        "cookies": playwright_cookies,
        "origins": [],
    }
    state_path.write_text(json.dumps(state, indent=2))

    logger.info(
        "cookies_imported",
        count=len(playwright_cookies),
        state_path=str(state_path),
    )

    return CookieImportResponse(
        imported=len(playwright_cookies),
        message=f"Successfully imported {len(playwright_cookies)} cookies",
    )


def _map_same_site(value: object) -> str:
    """Map Chrome's sameSite values to Playwright's expected format."""
    mapping = {
        "no_restriction": "None",
        "lax": "Lax",
        "strict": "Strict",
        "unspecified": "Lax",
    }
    return mapping.get(str(value).lower(), "Lax")
