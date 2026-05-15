"""One-time Gmail OAuth2 authorization script.

Run this ONCE on your host machine (not inside Docker) to authorize the
Automator to send emails via the Gmail API.

Prerequisites:
    1. Create a Google Cloud project at https://console.cloud.google.com
    2. Enable the Gmail API
    3. Create OAuth 2.0 credentials (Desktop app type)
    4. Download the credentials JSON and save it as data/gmail_credentials.json

Usage:
    cd automator
    python authorize_gmail.py

This will open a browser window for you to authorize. After authorization,
the token is saved to data/gmail_token.json and will be automatically
refreshed by the Automator service.
"""

from pathlib import Path

from src.integrations.gmail_oauth import run_authorization_flow

CREDENTIALS_PATH = Path("data/gmail_credentials.json")
TOKEN_PATH = Path("data/gmail_token.json")


def main() -> None:
    """Run the interactive OAuth2 authorization flow."""
    print("=" * 60)
    print("Gmail OAuth2 Authorization for Job Application Tool")
    print("=" * 60)
    print()

    if not CREDENTIALS_PATH.exists():
        print(f"ERROR: Credentials file not found at: {CREDENTIALS_PATH}")
        print()
        print("To fix this:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a project (or select existing)")
        print("  3. Enable the Gmail API")
        print("  4. Go to APIs & Services → Credentials")
        print("  5. Create OAuth 2.0 Client ID (type: Desktop app)")
        print("  6. Download the JSON file")
        print(f"  7. Save it as: {CREDENTIALS_PATH.resolve()}")
        print()
        return

    print(f"Using credentials from: {CREDENTIALS_PATH}")
    print(f"Token will be saved to: {TOKEN_PATH}")
    print()
    print("A browser window will open for authorization...")
    print()

    creds = run_authorization_flow(
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
    )

    print()
    print("Authorization successful!")
    print(f"Token saved to: {TOKEN_PATH.resolve()}")
    print()
    print("The Automator will automatically refresh this token as needed.")
    print("You should not need to run this script again unless you revoke access.")


if __name__ == "__main__":
    main()
