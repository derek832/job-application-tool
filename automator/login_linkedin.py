"""
One-time LinkedIn login helper.

Launches a visible Chromium browser with a persistent profile stored in
data/browser-profile/. Log into LinkedIn manually, then close the browser.
The session cookies will persist for the pipeline to use.

Run this on your host machine (not inside Docker):
    cd automator
    python login_linkedin.py
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


# Store in the root data/ directory (same as Docker volume mount)
PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser-profile"


async def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Launching browser with persistent profile at: {PROFILE_DIR.resolve()}")
    print("Log into LinkedIn, then close the browser window when done.")
    print()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR.resolve()),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.linkedin.com/login")

        # Wait until the user closes the browser
        print("Waiting for you to log in and close the browser...")
        while len(context.pages) > 0:
            try:
                await context.pages[0].wait_for_event("close", timeout=1000)
            except Exception:
                if len(context.pages) == 0:
                    break
                continue

        try:
            await context.close()
        except Exception:
            pass

    print()
    print("Done! LinkedIn session saved.")
    print(f"Profile stored at: {PROFILE_DIR.resolve()}")
    print("The Docker container will use this profile on the next pipeline run.")


if __name__ == "__main__":
    asyncio.run(main())
