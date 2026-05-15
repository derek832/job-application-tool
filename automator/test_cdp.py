"""Test CDP connection to Chrome from inside Docker."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    pw = await async_playwright().start()
    try:
        print("Connecting to http://host.docker.internal:9222 ...")
        browser = await pw.chromium.connect_over_cdp("http://host.docker.internal:9222")
        print(f"Connected! Contexts: {len(browser.contexts)}")
        if browser.contexts:
            pages = browser.contexts[0].pages
            print(f"Pages in first context: {len(pages)}")
            for p in pages:
                print(f"  - {p.url}")
        await browser.close()
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        await pw.stop()


asyncio.run(main())
