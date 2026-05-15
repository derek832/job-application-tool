"""Gmail OAuth2 token management for sending emails via the Gmail API.

Handles the OAuth2 flow for Gmail API access:
- First-time authorization via a local redirect (run once interactively).
- Token persistence to a JSON file in the data directory.
- Automatic token refresh using the stored refresh token.

The OAuth credentials (client_id, client_secret) come from a Google Cloud
project with the Gmail API enabled. The token file stores the access and
refresh tokens and is never committed to git.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = structlog.get_logger(__name__)

# Gmail API scope for sending emails only (minimal permission).
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Default paths (overridable via environment or settings).
_DATA_DIR = Path("data")
_TOKEN_PATH = _DATA_DIR / "gmail_token.json"
_CREDENTIALS_PATH = _DATA_DIR / "gmail_credentials.json"


def get_token_path() -> Path:
    """Return the path to the stored OAuth token file."""
    return _TOKEN_PATH


def get_credentials_path() -> Path:
    """Return the path to the OAuth client credentials file."""
    return _CREDENTIALS_PATH


def load_credentials(
    token_path: Path | None = None,
    credentials_path: Path | None = None,
) -> Credentials | None:
    """Load and refresh Gmail OAuth2 credentials from disk.

    If a valid token exists, returns it (refreshing if expired). If no token
    exists or refresh fails, returns None — the user must run the interactive
    authorization flow.

    Args:
        token_path: Path to the stored token JSON. Defaults to data/gmail_token.json.
        credentials_path: Path to the client credentials JSON. Defaults to
            data/gmail_credentials.json.

    Returns:
        Valid Credentials instance, or None if authorization is needed.
    """
    token_path = token_path or _TOKEN_PATH
    credentials_path = credentials_path or _CREDENTIALS_PATH

    if not token_path.exists():
        logger.info("gmail_oauth_no_token_file", path=str(token_path))
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error("gmail_oauth_token_parse_error", error=str(exc))
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, token_path)
            logger.info("gmail_oauth_token_refreshed")
            return creds
        except Exception as exc:
            logger.error("gmail_oauth_refresh_failed", error=str(exc))
            return None

    logger.warning("gmail_oauth_token_invalid_no_refresh")
    return None


def run_authorization_flow(
    credentials_path: Path | None = None,
    token_path: Path | None = None,
) -> Credentials:
    """Run the interactive OAuth2 authorization flow.

    Opens a local browser for the user to authorize Gmail API access.
    Stores the resulting token to disk for future use.

    This should be run ONCE during initial setup (outside Docker, on the
    host machine). After that, the token file is mounted into the container.

    Args:
        credentials_path: Path to the OAuth client credentials JSON.
        token_path: Path where the token will be saved.

    Returns:
        The authorized Credentials instance.

    Raises:
        FileNotFoundError: If the credentials file does not exist.
    """
    credentials_path = credentials_path or _CREDENTIALS_PATH
    token_path = token_path or _TOKEN_PATH

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Gmail OAuth credentials file not found at {credentials_path}. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    _save_token(creds, token_path)
    logger.info("gmail_oauth_authorized", token_path=str(token_path))
    return creds


def _save_token(creds: Credentials, token_path: Path) -> None:
    """Persist credentials to a JSON file.

    Args:
        creds: The OAuth2 credentials to save.
        token_path: Destination file path.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    logger.debug("gmail_oauth_token_saved", path=str(token_path))
