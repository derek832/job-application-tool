import asyncio
from playwright.async_api import async_playwright

async def main():
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp("ws://192.168.65.254:9222/devtools/browser/89329341-ce6e-4fb2-8090-554c13621037")
        print(f"Connected! Contexts: {len(browser.contexts)}")
        await browser.close()
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        await pw.stop()

asyncio.run(main())
